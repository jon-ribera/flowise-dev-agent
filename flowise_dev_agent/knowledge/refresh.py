"""CLI refresh job for Flowise platform knowledge snapshots.

Usage:
    python -m flowise_dev_agent.knowledge.refresh --nodes
    python -m flowise_dev_agent.knowledge.refresh --nodes --dry-run
    python -m flowise_dev_agent.knowledge.refresh --nodes --validate
    python -m flowise_dev_agent.knowledge.refresh --templates
    python -m flowise_dev_agent.knowledge.refresh --templates --dry-run
    python -m flowise_dev_agent.knowledge.refresh --credentials
    python -m flowise_dev_agent.knowledge.refresh --credentials --dry-run
    python -m flowise_dev_agent.knowledge.refresh --credentials --validate
    python -m flowise_dev_agent.knowledge.refresh --nodes --templates --credentials
    python -m flowise_dev_agent.knowledge.refresh --workday-mcp
    python -m flowise_dev_agent.knowledge.refresh --workday-api

Milestone 1: Parses FLOWISE_NODE_REFERENCE.md (markdown) → generates
schemas/flowise_nodes.snapshot.json + schemas/flowise_nodes.meta.json.

Milestone 2: Fetches marketplace templates from live Flowise API → generates
schemas/flowise_templates.snapshot.json + schemas/flowise_templates.meta.json.
Reads FLOWISE_API_ENDPOINT and FLOWISE_API_KEY from environment.
Only metadata fields are stored (no flowData).

Milestone 3: Fetches credentials from live Flowise API → generates
schemas/flowise_credentials.snapshot.json + schemas/flowise_credentials.meta.json.
SECURITY: Only allowlisted fields are stored — no encryptedData, no secrets.
Allowlist: credential_id, name, type, tags, created_at, updated_at.
Use --validate to run the CI lint check (no write) on an existing snapshot.

Milestone 4 (stubs): --workday-mcp and --workday-api are registered no-op flags.
They exit 0 and print an informative message.  Real implementations are deferred
to Milestone 5+ (WorkdayKnowledgeProvider in knowledge/workday_provider.py).

The markdown is NEVER loaded at runtime. This script is run offline (manually
or via CI) to regenerate the snapshot from the human-maintained reference.

See ROADMAP6_Platform Knowledge.md sections C, D, F for design rationale.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import hashlib
import json
import logging
import re
import sys
import warnings
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).parent.parent.parent
_REFERENCE_MD = _REPO_ROOT / "FLOWISE_NODE_REFERENCE.md"
_SCHEMAS_DIR = _REPO_ROOT / "schemas"
_NODES_SNAPSHOT = _SCHEMAS_DIR / "flowise_nodes.snapshot.json"
_NODES_META = _SCHEMAS_DIR / "flowise_nodes.meta.json"
_TEMPLATES_SNAPSHOT = _SCHEMAS_DIR / "flowise_templates.snapshot.json"
_TEMPLATES_META = _SCHEMAS_DIR / "flowise_templates.meta.json"

# Metadata fields kept in the templates snapshot.  flowData is intentionally excluded.
_TEMPLATE_SLIM_FIELDS = ("templateName", "type", "categories", "usecases", "description")

_CRED_SNAPSHOT = _SCHEMAS_DIR / "flowise_credentials.snapshot.json"
_CRED_META = _SCHEMAS_DIR / "flowise_credentials.meta.json"

# Security allowlist: ONLY these keys may appear in the credential snapshot.
# Must match _CRED_ALLOWLIST in provider.py exactly.
_CRED_ALLOWLIST: frozenset[str] = frozenset({
    "credential_id", "name", "type", "tags", "created_at", "updated_at",
})

# Flowise input types that map to inputParams.
# Must match _FLOWISE_PRIMITIVE_TYPES in agent/tools.py and provider.py.
_PRIMITIVE_TYPES: frozenset[str] = frozenset({
    "string", "number", "boolean", "password", "json", "code",
    "file", "date", "credential", "asyncOptions", "options",
    "datagrid", "tabs", "multiOptions", "array",
})

# ---------------------------------------------------------------------------
# Markdown parser
# ---------------------------------------------------------------------------

# Patterns for node-level metadata
_RE_HEADING = re.compile(
    r"^###\s+(.+?)\s+\(`([^`]+)`\)",
    re.MULTILINE,
)
_RE_VERSION = re.compile(r"\*\*Version:\*\*\s*(.+?)(?:\s{2,}|$)", re.MULTILINE)
_RE_DESCRIPTION = re.compile(r"\*\*Description:\*\*\s*(.+?)(?:\s{2,}|$)", re.MULTILINE)
_RE_BASE_CLASSES = re.compile(r"\*\*Base Classes:\*\*\s*(.+?)(?:\s{2,}|$)", re.MULTILINE)
_RE_CREDENTIAL = re.compile(
    r"\*\*Credential Required:\*\*\s*.+?\(([^)]+)\)",
    re.MULTILINE,
)
_RE_CATEGORY_HEADING = re.compile(r"^##\s+(.+?)\s*(?:\(\d+\))?\s*$", re.MULTILINE)

# Table row: | `name` | type | ... — first cell must be backtick-wrapped.
# The type cell (group 2) may contain GFM escaped-pipe sequences "\|" to represent
# literal pipe characters used in union type strings like "Start \| Agent \| ...".
# The pattern (?:[^|\\]|\\.)+ matches: any non-pipe/non-backslash char, OR any
# backslash followed by any char (including \|).
# After matching, post-process group(2) with .replace("\\|", "|") to unescape.
_RE_TABLE_ROW = re.compile(
    r"^\|\s*`([^`]+)`\s*\|\s*((?:[^|\\]|\\.)+?)\s*\|(?:\s*([^\|]*?)\s*\|)?(?:\s*([^\|]*?)\s*\|)?",
    re.MULTILINE,
)
_RE_TABLE_SEP = re.compile(r"^\|[-| :]+\|$")

# Section markers inside an entry block
_RE_REQUIRED_INPUTS = re.compile(r"\*\*Required Inputs:\*\*")
_RE_OPTIONAL_INPUTS = re.compile(r"\*\*Optional Inputs:\*\*")
_RE_ADDITIONAL_PARAMS = re.compile(r"<details>|<summary>.*?Additional Parameters")


def _strip_html(text: str) -> str:
    """Remove HTML tags and collapse whitespace in a cell value."""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:300]  # cap at 300 chars for snapshot brevity


def _parse_base_classes(raw: str) -> list[str]:
    """Extract class names from '`Class1`, `Class2`, ...'"""
    return [m.strip() for m in re.findall(r"`([^`]+)`", raw)]


def _parse_table_rows(block: str, section: str) -> tuple[list[dict], list[dict]]:
    """Extract inputAnchors and inputParams from all table rows in a text block.

    Parameters
    ----------
    block:   Text of the node entry block.
    section: Current section context: "required", "optional", or "additional".

    Returns
    -------
    (input_anchors, input_params) where each entry is a dict with
    id, name, label, type, optional.
    """
    input_anchors: list[dict] = []
    input_params: list[dict] = []

    # Determine section context based on markers in the block
    # We scan linearly and switch context as we hit section headers.
    current_section = "optional"  # default when no header found
    lines = block.splitlines()

    i = 0
    while i < len(lines):
        line = lines[i]

        # Update section context
        if _RE_REQUIRED_INPUTS.search(line):
            current_section = "required"
            i += 1
            continue
        if _RE_OPTIONAL_INPUTS.search(line):
            current_section = "optional"
            i += 1
            continue
        if _RE_ADDITIONAL_PARAMS.search(line):
            current_section = "additional"
            i += 1
            continue

        # Table separator row — skip
        if _RE_TABLE_SEP.match(line.strip()):
            i += 1
            continue

        # Table row starting with |
        if line.strip().startswith("|"):
            # Skip header row (Name | Type | Default | Description)
            if re.match(r"^\|\s*Name\s*\|", line, re.IGNORECASE):
                i += 1
                continue

            m = _RE_TABLE_ROW.match(line.strip())
            if m:
                param_name = m.group(1).strip()
                # Unescape GFM pipe escapes (\|) used in union-type strings,
                # e.g. "Start \| Agent \| ..." → "Start | Agent | ..."
                param_type = m.group(2).strip().replace("\\|", "|")
                raw_default = (m.group(3) or "").strip()
                raw_desc = (m.group(4) or "").strip()

                # Accumulate continuation lines (multiline cell values)
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    stripped = next_line.strip()
                    if not stripped:
                        break
                    if stripped.startswith("|"):
                        break
                    if stripped.startswith("#") or stripped.startswith("**"):
                        break
                    if stripped.startswith("<"):
                        break
                    # Continuation — append to last cell (description)
                    raw_desc = (raw_desc + " " + stripped)[:300]
                    j += 1
                i = j  # advance outer pointer past continuations

                is_optional = current_section in ("optional", "additional")
                default_val = _strip_html(raw_default) or None
                description = _strip_html(raw_desc) or None

                entry: dict[str, Any] = {
                    "id": f"{{nodeId}}-input-{param_name}-{param_type}",
                    "name": param_name,
                    "label": param_name,  # markdown doesn't separate label from name
                    "type": param_type,
                    "optional": is_optional,
                }
                if default_val:
                    entry["default"] = default_val
                if description:
                    entry["description"] = description[:200]

                if param_type in _PRIMITIVE_TYPES:
                    input_params.append(entry)
                else:
                    # Non-primitive type = class name = node connection anchor
                    input_anchors.append(entry)

                continue

        i += 1

    return input_anchors, input_params


def _synthesize_output_anchors(
    node_name: str,
    label: str,
    base_classes: list[str],
) -> list[dict]:
    """Synthesize output anchors from base_classes (same logic as tools.py)."""
    if not base_classes:
        return [
            {
                "id": f"{{nodeId}}-output-{node_name}-{node_name}",
                "name": node_name,
                "label": label,
                "type": node_name,
            }
        ]
    return [
        {
            "id": f"{{nodeId}}-output-{node_name}-{'|'.join(base_classes)}",
            "name": node_name,
            "label": label,
            "type": " | ".join(base_classes),
        }
    ]


def _patch_output_anchors_from_api(schemas: list[dict]) -> tuple[list[dict], int]:
    """Fetch live output definitions from Flowise and patch outputAnchors.

    The markdown synthesis always produces a single outputAnchor named after the
    node type (e.g. "memoryVectorStore"), but many Flowise nodes expose multiple
    outputs with different names (e.g. "retriever", "vectorStore").  This function
    calls GET /api/v1/nodes/{name} for every schema, reads the "outputs" field, and
    replaces the synthesized outputAnchors with correctly-named entries.

    Silently skips nodes where the API call fails or "outputs" is absent/empty.
    Returns (patched_schemas, patch_count).
    """
    import os
    import urllib.request

    # Load .env so the function works when run via CLI without export'd vars
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    api_url = os.getenv("FLOWISE_API_URL", "http://localhost:3000")
    api_key = os.getenv("FLOWISE_API_KEY", "")
    base = api_url.rstrip("/")

    patched = 0
    result: list[dict] = []
    for schema in schemas:
        node_name = schema.get("node_type", "")
        try:
            url = f"{base}/api/v1/nodes/{node_name}"
            req = urllib.request.Request(url)
            if api_key:
                req.add_header("Authorization", f"Bearer {api_key}")
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
            live_outputs = raw.get("outputs") or []
            if live_outputs:
                new_anchors = []
                for out in live_outputs:
                    out_name = out.get("name") or node_name
                    out_bcs = out.get("baseClasses") or schema.get("baseClasses", [])
                    new_anchors.append(
                        {
                            "id": f"{{nodeId}}-output-{out_name}-{'|'.join(out_bcs)}",
                            "name": out_name,
                            "label": out.get("label", out_name),
                            "type": " | ".join(out_bcs),
                        }
                    )
                schema = {**schema, "outputAnchors": new_anchors}
                patched += 1
        except Exception:
            pass  # API unavailable or node not found — keep synthesized anchors
        result.append(schema)
    return result, patched


def _parse_node_block(
    block: str,
    category: str,
) -> dict | None:
    """Parse a single node entry block into a snapshot schema object.

    Returns None and emits a warning if the block cannot be parsed.
    """
    # --- Heading: ### Label (`node_type`) ---
    heading_m = _RE_HEADING.search(block)
    if not heading_m:
        return None

    label = heading_m.group(1).strip()
    node_type = heading_m.group(2).strip()

    # --- Metadata ---
    ver_m = _RE_VERSION.search(block)
    desc_m = _RE_DESCRIPTION.search(block)
    bc_m = _RE_BASE_CLASSES.search(block)
    cred_m = _RE_CREDENTIAL.search(block)

    version_str = ver_m.group(1).strip() if ver_m else None
    description = desc_m.group(1).strip() if desc_m else None
    base_classes = _parse_base_classes(bc_m.group(1)) if bc_m else []
    credential_required: list[str] = []
    if cred_m:
        credential_required = [c.strip() for c in cred_m.group(1).split(",")]

    # Truncate description to keep snapshot compact
    if description:
        description = description[:300]

    # --- Parse tables (Required / Optional / Additional Parameters) ---
    # Extract only the text after the heading line to avoid re-matching metadata
    body_start = heading_m.end()
    body = block[body_start:]
    input_anchors, input_params = _parse_table_rows(body, "optional")

    # --- Output anchors (synthesized from base_classes) ---
    output_anchors = _synthesize_output_anchors(node_type, label, base_classes)

    schema: dict[str, Any] = {
        "node_type": node_type,
        "name": node_type,
        "label": label,
        "category": category,
        "inputAnchors": input_anchors,
        "inputParams": input_params,
        "outputAnchors": output_anchors,
        "outputs": {},
        "_flowdata_note": (
            "Replace {nodeId} in all 'id' fields with your actual node ID "
            "(e.g. 'chatOpenAI_0'). Embed inputAnchors, inputParams, outputAnchors, "
            "and outputs verbatim in each flowData node's data object."
        ),
    }

    if version_str is not None:
        schema["version"] = version_str
    if description:
        schema["description"] = description
    if base_classes:
        schema["baseClasses"] = base_classes
    if credential_required:
        schema["credential_required"] = credential_required

    return schema


def parse_node_reference(md_path: Path) -> tuple[list[dict], list[str]]:
    """Parse FLOWISE_NODE_REFERENCE.md into a list of node schema objects.

    Returns
    -------
    (schemas, warnings) where schemas is the list of parsed node dicts and
    warnings is a list of string messages for entries that could not be parsed.
    """
    text = md_path.read_text(encoding="utf-8")

    schemas: list[dict] = []
    parse_warnings: list[str] = []
    seen: set[str] = set()

    # Determine category for each node by tracking ## section headers.
    # Strategy: split text into lines, walk them, track current category,
    # and when we see a ### heading, attribute it to the current category.
    # Then do a second pass to parse each ### block.

    # Build a map of line_number → category
    lines = text.splitlines(keepends=True)
    current_category = "Unknown"
    line_categories: dict[int, str] = {}  # line_offset → category at that point

    for idx, line in enumerate(lines):
        cat_m = _RE_CATEGORY_HEADING.match(line.rstrip())
        if cat_m and not line.startswith("###"):
            current_category = cat_m.group(1).strip()
        if line.startswith("### "):
            line_categories[idx] = current_category

    # Split by the exactly-3-dash horizontal rule used as a node separator.
    # Using ---+ (3-or-more) would also match long dash-lines that appear inside
    # multi-line table cell default values (e.g. "-----" used as a visual divider
    # inside a prompt template), splitting blocks in the wrong place.  The
    # markdown convention in this file uses exactly "---" as the separator.
    blocks = re.split(r"\n---\n", text)

    # Track category as we scan through blocks in order
    current_category = "Unknown"
    for block in blocks:
        # Check if this block contains a category heading (update tracker)
        for cat_m in _RE_CATEGORY_HEADING.finditer(block):
            candidate = cat_m.group(1).strip()
            # Only update if it's a real ## heading (not a ### node heading)
            if not block[max(0, cat_m.start() - 1): cat_m.start()].endswith("#"):
                current_category = candidate

        # Check if block contains a node entry
        heading_m = _RE_HEADING.search(block)
        if not heading_m:
            continue

        try:
            schema = _parse_node_block(block, current_category)
        except Exception as exc:
            label_guess = heading_m.group(1) if heading_m else "?"
            parse_warnings.append(
                f"Exception parsing '{label_guess}': {exc}"
            )
            continue

        if schema is None:
            continue

        node_type = schema["node_type"]
        if node_type in seen:
            parse_warnings.append(f"Duplicate node_type skipped: {node_type!r}")
            continue
        seen.add(node_type)
        schemas.append(schema)

    return schemas, parse_warnings


# ---------------------------------------------------------------------------
# Fingerprinting and meta
# ---------------------------------------------------------------------------


def _compute_meta(
    snapshot_path: Path,
    content_bytes: bytes,
    node_count: int,
    source: str,
) -> dict:
    digest = hashlib.sha256(content_bytes).hexdigest()
    return {
        "snapshot_file": str(snapshot_path.relative_to(_REPO_ROOT)),
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": source,
        "node_count": node_count,
        "fingerprint": digest,
        "status": "ok",
    }


def _diff_nodes(
    existing: list[dict],
    fresh: list[dict],
) -> tuple[list[str], list[str], list[str]]:
    """Return (added, changed, removed) node_type lists for diff reporting."""
    existing_map = {n.get("node_type") or n.get("name"): n for n in existing}
    fresh_map = {n.get("node_type") or n.get("name"): n for n in fresh}

    added = [k for k in fresh_map if k not in existing_map]
    removed = [k for k in existing_map if k not in fresh_map]

    changed: list[str] = []
    for k, fresh_node in fresh_map.items():
        if k in existing_map:
            old_hash = hashlib.sha256(
                json.dumps(existing_map[k], sort_keys=True, default=str).encode()
            ).hexdigest()
            new_hash = hashlib.sha256(
                json.dumps(fresh_node, sort_keys=True, default=str).encode()
            ).hexdigest()
            if old_hash != new_hash:
                changed.append(k)

    return added, changed, removed


# ---------------------------------------------------------------------------
# Snapshot integrity validation
# ---------------------------------------------------------------------------


def validate_nodes_snapshot(schemas: list[dict]) -> list[str]:
    """Validate a list of node schema dicts for structural integrity.

    Checks performed (all are CI-blocking):
    1. outputAnchors — every node must have at least one output anchor.
    2. version — must be parseable as float (stored as string in markdown but
       the compiler converts it; the string itself must be numeric).
    3. Anchor ID format — all inputAnchor, inputParam, and outputAnchor IDs must
       contain the '{nodeId}' placeholder so the compiler can substitute the
       actual instance ID (e.g. 'chatOpenAI_0').
    4. No duplicate node_type values — each node name must be unique.
    5. Anchor ID prefix — inputAnchor/inputParam IDs must start with
       '{nodeId}-input-' and outputAnchor IDs with '{nodeId}-output-'.

    Returns a list of error strings (empty = passed).
    """
    errors: list[str] = []
    seen_types: dict[str, int] = {}

    for i, node in enumerate(schemas):
        name = node.get("node_type") or node.get("name") or f"<index {i}>"

        # 1. outputAnchors required
        oa = node.get("outputAnchors") or []
        if not oa:
            errors.append(f"[{name}] outputAnchors is empty — compiler cannot build source handles")

        # 2. version must be parseable as float
        v = node.get("version")
        if v is not None:
            try:
                float(v)
            except (TypeError, ValueError):
                errors.append(f"[{name}] version={v!r} is not parseable as float")

        # 3 + 5. Anchor ID format checks
        for group_key, direction in (
            ("inputAnchors", "input"),
            ("inputParams", "input"),
            ("outputAnchors", "output"),
        ):
            for anchor in node.get(group_key) or []:
                aid = anchor.get("id", "")
                aname = anchor.get("name", "?")
                if not aid:
                    errors.append(f"[{name}] {group_key}/{aname}: id is empty")
                    continue
                if "{nodeId}" not in aid:
                    errors.append(
                        f"[{name}] {group_key}/{aname}: id={aid!r} missing {{nodeId}} placeholder"
                    )
                expected_prefix = f"{{nodeId}}-{direction}-"
                if not aid.startswith(expected_prefix):
                    errors.append(
                        f"[{name}] {group_key}/{aname}: id={aid!r} "
                        f"does not start with '{expected_prefix}'"
                    )

        # 4. Duplicate node_type
        key = node.get("node_type") or node.get("name")
        if key:
            if key in seen_types:
                errors.append(
                    f"[{name}] duplicate node_type — also at index {seen_types[key]}"
                )
            else:
                seen_types[key] = i

    return errors


# ---------------------------------------------------------------------------
# Main refresh command
# ---------------------------------------------------------------------------


def refresh_nodes(dry_run: bool = False, validate: bool = False) -> int:
    """Parse FLOWISE_NODE_REFERENCE.md and write the node snapshot.

    Returns exit code (0 = success, 1 = error).
    """
    if not _REFERENCE_MD.exists():
        logger.error("FLOWISE_NODE_REFERENCE.md not found at %s", _REFERENCE_MD)
        return 1

    logger.info("Parsing %s …", _REFERENCE_MD)
    schemas, parse_warnings = parse_node_reference(_REFERENCE_MD)

    if parse_warnings:
        for w in parse_warnings:
            logger.warning("  PARSE WARN: %s", w)
        logger.warning("%d parse warning(s)", len(parse_warnings))

    logger.info("Parsed %d node schemas", len(schemas))

    if not schemas:
        logger.error("No schemas parsed — aborting to avoid overwriting with empty snapshot")
        return 1

    # Enrich outputAnchors with real output names from the live Flowise API.
    # The markdown synthesis always generates a single anchor named after the node
    # type, which is wrong for multi-output nodes (e.g. memoryVectorStore outputs
    # "retriever" and "vectorStore", not "memoryVectorStore").
    # Silently skips when the API is unreachable.
    schemas, n_patched = _patch_output_anchors_from_api(schemas)
    if n_patched:
        print(f"  [nodes] patched outputAnchors for {n_patched} node(s) from live API")

    content = json.dumps(schemas, indent=2, ensure_ascii=False)
    content_bytes = content.encode("utf-8")

    # Diff against existing snapshot (for reporting)
    existing_schemas: list[dict] = []
    if _NODES_SNAPSHOT.exists():
        try:
            existing_schemas = json.loads(_NODES_SNAPSHOT.read_text(encoding="utf-8"))
        except Exception:
            pass

    added, changed, removed = _diff_nodes(existing_schemas, schemas)

    print(f"\n[nodes]  {len(schemas)} items from markdown", end="")
    if existing_schemas:
        print(f" | was {len(existing_schemas)}", end="")
    print()
    if added:
        print(f"  + added   ({len(added)}): {', '.join(added[:10])}" + (" …" if len(added) > 10 else ""))
    if changed:
        print(f"  ~ changed ({len(changed)}): {', '.join(changed[:10])}" + (" …" if len(changed) > 10 else ""))
    if removed:
        print(f"  - removed ({len(removed)}): {', '.join(removed[:10])}" + (" …" if len(removed) > 10 else ""))
    if not added and not changed and not removed and existing_schemas:
        print("  (no change — fingerprint would match)")

    if dry_run:
        logger.info("--dry-run: nothing written")
        return 0

    _SCHEMAS_DIR.mkdir(parents=True, exist_ok=True)
    _NODES_SNAPSHOT.write_bytes(content_bytes)
    meta = _compute_meta(_NODES_SNAPSHOT, content_bytes, len(schemas), "local_markdown")
    _NODES_META.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    logger.info("Written: %s", _NODES_SNAPSHOT)
    logger.info("Written: %s", _NODES_META)
    logger.info("Fingerprint: %s", meta["fingerprint"][:16] + "…")

    if validate:
        validation_errors = validate_nodes_snapshot(schemas)
        if validation_errors:
            print(f"\n[nodes] VALIDATION FAILED — {len(validation_errors)} error(s):")
            for err in validation_errors:
                print(f"  \u2717 {err}")
            logger.error(
                "Node snapshot validation FAILED — %d error(s). "
                "Fix FLOWISE_NODE_REFERENCE.md and re-run refresh --nodes.",
                len(validation_errors),
            )
            return 1
        print(f"\n[nodes] Validation PASS — {len(schemas)} nodes, all checks OK")

    return 0


# ---------------------------------------------------------------------------
# Template refresh (Milestone 2) — live Flowise API
# ---------------------------------------------------------------------------


async def _fetch_templates_slim_async() -> list[dict]:
    """Fetch marketplace templates from the Flowise API and strip flowData.

    Reads FLOWISE_API_ENDPOINT (default http://localhost:3000) and
    FLOWISE_API_KEY from the environment — same vars used by the agent at
    runtime.

    Returns a list of slim metadata dicts (no flowData).
    """
    from cursorwise.client import FlowiseClient
    from cursorwise.config import Settings

    settings = Settings.from_env()
    client = FlowiseClient(settings)
    try:
        raw = await client.list_marketplace_templates()
    finally:
        await client.close()

    if not isinstance(raw, list):
        logger.error(
            "Unexpected response type from list_marketplace_templates: %s", type(raw).__name__
        )
        return []

    slim: list[dict] = []
    for t in raw:
        if not isinstance(t, dict):
            continue
        slim.append({k: t.get(k) for k in _TEMPLATE_SLIM_FIELDS})
    return slim


def refresh_templates(dry_run: bool = False) -> int:
    """Fetch marketplace templates from the Flowise API and write the snapshot.

    Metadata only — flowData is stripped.
    Returns exit code (0 = success, 1 = error).
    """
    logger.info("Fetching marketplace templates from Flowise API …")
    try:
        templates = asyncio.run(_fetch_templates_slim_async())
    except Exception:
        logger.exception("Failed to fetch templates from API")
        return 1

    if not templates:
        logger.error(
            "No templates returned — aborting to avoid overwriting with empty snapshot"
        )
        return 1

    content = json.dumps(templates, indent=2, ensure_ascii=False)
    content_bytes = content.encode("utf-8")

    # Diff against existing snapshot (names only)
    existing: list[dict] = []
    if _TEMPLATES_SNAPSHOT.exists():
        try:
            existing = json.loads(_TEMPLATES_SNAPSHOT.read_text(encoding="utf-8"))
        except Exception:
            pass

    existing_names = {t.get("templateName") for t in existing if t.get("templateName")}
    fresh_names = {t.get("templateName") for t in templates if t.get("templateName")}
    added_names = fresh_names - existing_names
    removed_names = existing_names - fresh_names

    print(f"\n[templates]  {len(templates)} items from API", end="")
    if existing:
        print(f" | was {len(existing)}", end="")
    print()
    if added_names:
        preview = ", ".join(sorted(added_names)[:5])
        print(f"  + added   ({len(added_names)}): {preview}" + (" …" if len(added_names) > 5 else ""))
    if removed_names:
        preview = ", ".join(sorted(removed_names)[:5])
        print(f"  - removed ({len(removed_names)}): {preview}" + (" …" if len(removed_names) > 5 else ""))
    if not added_names and not removed_names and existing:
        print("  (no change)")

    if dry_run:
        logger.info("--dry-run: nothing written")
        return 0

    _SCHEMAS_DIR.mkdir(parents=True, exist_ok=True)
    _TEMPLATES_SNAPSHOT.write_bytes(content_bytes)

    digest = hashlib.sha256(content_bytes).hexdigest()
    meta = {
        "snapshot_file": str(_TEMPLATES_SNAPSHOT.relative_to(_REPO_ROOT)),
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": "flowise_api",
        "template_count": len(templates),
        "fingerprint": digest,
        "status": "ok",
    }
    _TEMPLATES_META.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    logger.info("Written: %s", _TEMPLATES_SNAPSHOT)
    logger.info("Written: %s", _TEMPLATES_META)
    logger.info("Fingerprint: %s", digest[:16] + "…")
    return 0


# ---------------------------------------------------------------------------
# Credential refresh (Milestone 3) — live Flowise API
# ---------------------------------------------------------------------------


def _normalize_credential_api(raw: dict) -> dict:
    """Normalise a raw Flowise API credential response to the allowlisted snapshot format.

    Flowise returns: id, name, credentialName (the type), createdDate, updatedDate, encryptedData, …
    We keep only the six allowlisted fields and remap API keys to snapshot keys.
    """
    return {
        "credential_id": str(raw.get("id") or raw.get("credential_id") or ""),
        "name": str(raw.get("name") or ""),
        "type": str(raw.get("credentialName") or raw.get("type") or ""),
        "tags": raw.get("tags") if isinstance(raw.get("tags"), list) else [],
        "created_at": str(raw.get("createdDate") or raw.get("created_at") or ""),
        "updated_at": str(raw.get("updatedDate") or raw.get("updated_at") or ""),
    }


def validate_credential_snapshot(path: Path = _CRED_SNAPSHOT) -> list[str]:
    """Validate that no non-allowlisted keys exist in the credential snapshot.

    Returns a list of violation messages.  An empty list means PASS.
    This is the CI lint step: any violation is a hard failure.
    """
    if not path.exists():
        return []  # No snapshot → nothing to lint
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"Failed to parse snapshot JSON: {exc}"]

    violations: list[str] = []
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        extra = set(entry.keys()) - _CRED_ALLOWLIST
        if extra:
            label = entry.get("name") or entry.get("credential_id") or f"index {i}"
            violations.append(
                f"Credential '{label}' contains banned key(s): {sorted(extra)}"
            )
    return violations


async def _fetch_credentials_async() -> list[dict]:
    """Fetch credentials from the Flowise API, normalize, and strip to allowlist.

    Reads FLOWISE_API_ENDPOINT (default http://localhost:3000) and
    FLOWISE_API_KEY from the environment.
    """
    from cursorwise.client import FlowiseClient
    from cursorwise.config import Settings

    settings = Settings.from_env()
    client = FlowiseClient(settings)
    try:
        raw = await client.list_credentials()
    finally:
        await client.close()

    if not isinstance(raw, list):
        logger.error(
            "Unexpected response type from list_credentials: %s", type(raw).__name__
        )
        return []

    normalized: list[dict] = []
    for r in raw:
        if not isinstance(r, dict):
            continue
        cid = r.get("id") or r.get("credential_id")
        if not cid:
            continue  # skip entries without an id
        entry = _normalize_credential_api(r)
        # Final hard check: ensure no banned key survived normalization
        extra = set(entry.keys()) - _CRED_ALLOWLIST
        if extra:
            logger.error(
                "BUG: normalization did not strip keys %s — skipping entry %r",
                sorted(extra),
                entry.get("name"),
            )
            continue
        normalized.append(entry)
    return normalized


def refresh_credentials(dry_run: bool = False, validate_only: bool = False) -> int:
    """Fetch credentials from the Flowise API and write the allowlisted snapshot.

    If *validate_only* is True, only checks the existing snapshot for banned keys
    (CI lint mode — no API call, no write).

    Returns exit code (0 = success, 1 = error/violation).
    """
    if validate_only:
        violations = validate_credential_snapshot(_CRED_SNAPSHOT)
        if violations:
            print(f"\n[credentials] ALLOWLIST VIOLATION(S) in {_CRED_SNAPSHOT.name}:")
            for v in violations:
                print(f"  ✗ {v}")
            logger.error(
                "Credential snapshot allowlist check FAILED — %d violation(s)",
                len(violations),
            )
            return 1
        count = 0
        if _CRED_SNAPSHOT.exists():
            try:
                count = len(json.loads(_CRED_SNAPSHOT.read_text(encoding="utf-8")))
            except Exception:
                pass
        print(
            f"\n[credentials] Allowlist check PASS — "
            f"{count} entries, no banned keys in {_CRED_SNAPSHOT.name}"
        )
        return 0

    logger.info("Fetching credentials from Flowise API …")
    try:
        credentials = asyncio.run(_fetch_credentials_async())
    except Exception:
        logger.exception("Failed to fetch credentials from API")
        return 1

    # Allow empty credential list (valid for a fresh Flowise instance)
    content = json.dumps(credentials, indent=2, ensure_ascii=False)
    content_bytes = content.encode("utf-8")

    # Diff against existing snapshot
    existing: list[dict] = []
    if _CRED_SNAPSHOT.exists():
        try:
            existing = json.loads(_CRED_SNAPSHOT.read_text(encoding="utf-8"))
        except Exception:
            pass

    existing_ids = {c.get("credential_id") for c in existing if c.get("credential_id")}
    fresh_ids = {c.get("credential_id") for c in credentials if c.get("credential_id")}
    added_ids = fresh_ids - existing_ids
    removed_ids = existing_ids - fresh_ids

    # Changed entries: same id, different allowlisted field values
    existing_map = {c.get("credential_id"): c for c in existing if c.get("credential_id")}
    fresh_map = {c.get("credential_id"): c for c in credentials if c.get("credential_id")}
    changed: list[str] = []
    for cid in fresh_ids & existing_ids:
        if fresh_map[cid] != existing_map[cid]:
            changed.append(fresh_map[cid].get("name") or cid[:8])

    print(f"\n[credentials]  {len(credentials)} items from API", end="")
    if existing:
        print(f" | was {len(existing)}", end="")
    print()
    if added_ids:
        print(f"  + added   ({len(added_ids)})")
    if removed_ids:
        print(f"  - removed ({len(removed_ids)}) (warn only — not auto-deleted)")
    if changed:
        names = ", ".join(changed[:5]) + (" …" if len(changed) > 5 else "")
        print(f"  ~ changed ({len(changed)}): {names}")
    if not added_ids and not removed_ids and not changed and existing:
        print("  (no change)")

    if dry_run:
        logger.info("--dry-run: nothing written")
        return 0

    _SCHEMAS_DIR.mkdir(parents=True, exist_ok=True)
    _CRED_SNAPSHOT.write_bytes(content_bytes)

    digest = hashlib.sha256(content_bytes).hexdigest()
    meta = {
        "snapshot_file": str(_CRED_SNAPSHOT.relative_to(_REPO_ROOT)),
        "generated_at": (
            datetime.datetime.now(datetime.timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        ),
        "source": "flowise_api",
        "credential_count": len(credentials),
        "fingerprint": digest,
        "status": "ok",
    }
    _CRED_META.write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    logger.info("Written: %s", _CRED_SNAPSHOT)
    logger.info("Written: %s", _CRED_META)
    logger.info("Fingerprint: %s", digest[:16] + "…")
    return 0


# ---------------------------------------------------------------------------
# Workday refresh stubs (Milestone 4) — no-ops until real implementation
# ---------------------------------------------------------------------------


def refresh_workday_mcp(dry_run: bool = False) -> int:
    """Write (or re-write) the Workday MCP blueprint snapshot.

    Milestone 7.5: reads ``WORKDAY_MCP_CATALOG_PATH`` env var.
    - If set, loads blueprints from that JSON file and normalises them.
    - If not set, writes the built-in default blueprint to the snapshot.

    The snapshot format is a JSON array of blueprint dicts matching:
      blueprint_id, description, selected_tool, mcp_server_url_placeholder,
      auth_var, mcp_actions, credential_type, chatflow_only, category, tags

    Returns exit code (0 = success, 1 = error).
    """
    import os

    catalog_path_str = os.environ.get("WORKDAY_MCP_CATALOG_PATH", "").strip()

    _default_blueprints = [
        {
            "blueprint_id": "workday_default",
            "description": (
                "Default Workday MCP actions for worker lookup and self-service "
                "(getMyInfo, searchForWorker, getWorkers)"
            ),
            "selected_tool": "customMCP",
            "mcp_server_url_placeholder": "https://<tenant>.workday.com/mcp",
            "auth_var": "$vars.beartoken",
            "mcp_actions": ["getMyInfo", "searchForWorker", "getWorkers"],
            "credential_type": "workdayOAuth",
            "chatflow_only": True,
            "category": "HR",
            "tags": ["workday", "mcp", "worker", "hr", "custom-mcp"],
        }
    ]

    if catalog_path_str:
        catalog_path = Path(catalog_path_str)
        if not catalog_path.exists():
            logger.error(
                "[workday-mcp] WORKDAY_MCP_CATALOG_PATH=%s not found", catalog_path
            )
            return 1
        try:
            raw = json.loads(catalog_path.read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                raise ValueError("Expected a JSON array of blueprint dicts")
            blueprints = raw
            source = f"catalog_file:{catalog_path}"
        except Exception as exc:
            logger.error("[workday-mcp] Failed to load catalog: %s", exc)
            return 1
    else:
        blueprints = _default_blueprints
        source = "built_in_defaults"

    content = json.dumps(blueprints, indent=2, ensure_ascii=False)
    content_bytes = content.encode("utf-8")

    # Diff against existing snapshot (blueprint_id set)
    _wday_snapshot = _SCHEMAS_DIR / "workday_mcp.snapshot.json"
    _wday_meta = _SCHEMAS_DIR / "workday_mcp.meta.json"

    existing: list[dict] = []
    if _wday_snapshot.exists():
        try:
            existing = json.loads(_wday_snapshot.read_text(encoding="utf-8"))
        except Exception:
            pass

    existing_ids = {b.get("blueprint_id") for b in existing if b.get("blueprint_id")}
    fresh_ids = {b.get("blueprint_id") for b in blueprints if b.get("blueprint_id")}
    added = fresh_ids - existing_ids
    removed = existing_ids - fresh_ids

    print(f"\n[workday-mcp]  {len(blueprints)} blueprint(s)  source={source}", end="")
    if existing:
        print(f" | was {len(existing)}", end="")
    print()
    if added:
        print(f"  + added   ({len(added)}): {', '.join(sorted(added))}")
    if removed:
        print(f"  - removed ({len(removed)}): {', '.join(sorted(removed))}")
    if not added and not removed and existing:
        print("  (no change)")

    if dry_run:
        logger.info("--dry-run: nothing written")
        return 0

    _SCHEMAS_DIR.mkdir(parents=True, exist_ok=True)
    _wday_snapshot.write_bytes(content_bytes)

    digest = hashlib.sha256(content_bytes).hexdigest()
    meta = {
        "snapshot_file": str(_wday_snapshot.relative_to(_REPO_ROOT)),
        "generated_at": (
            datetime.datetime.now(datetime.timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        ),
        "source": source,
        "blueprint_count": len(blueprints),
        "fingerprint": digest,
        "status": "ok",
    }
    _wday_meta.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    logger.info("Written: %s", _wday_snapshot)
    logger.info("Written: %s", _wday_meta)
    logger.info("Fingerprint: %s", digest[:16] + "…")
    return 0


def refresh_workday_api(dry_run: bool = False) -> int:
    """No-op stub for future Workday API snapshot refresh.

    Milestone 4: prints an informative message and exits 0.
    Real implementation is deferred to Milestone 5+ (WorkdayApiStore).

    Returns exit code 0 (success — stub counts as a clean no-op).
    """
    print(
        "\n[workday-api]  STUB — not yet implemented (Milestone 4).\n"
        "  WorkdayApiStore is scaffolded in "
        "flowise_dev_agent/knowledge/workday_provider.py.\n"
        "  Real Workday REST/SOAP API endpoint data population is deferred to Milestone 5+.\n"
        "  Snapshot file: schemas/workday_api.snapshot.json  (status: stub)"
    )
    if dry_run:
        logger.info("--dry-run: nothing to write (stub)")
    return 0


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Refresh Flowise platform knowledge snapshots.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m flowise_dev_agent.knowledge.refresh --nodes
  python -m flowise_dev_agent.knowledge.refresh --nodes --dry-run
  python -m flowise_dev_agent.knowledge.refresh --nodes --validate
  python -m flowise_dev_agent.knowledge.refresh --templates
  python -m flowise_dev_agent.knowledge.refresh --credentials
  python -m flowise_dev_agent.knowledge.refresh --credentials --dry-run
  python -m flowise_dev_agent.knowledge.refresh --credentials --validate
  python -m flowise_dev_agent.knowledge.refresh --nodes --templates --credentials
  python -m flowise_dev_agent.knowledge.refresh --workday-mcp
  python -m flowise_dev_agent.knowledge.refresh --workday-api
""",
    )
    parser.add_argument(
        "--nodes",
        action="store_true",
        help="Refresh node schema snapshot from FLOWISE_NODE_REFERENCE.md.",
    )
    parser.add_argument(
        "--templates",
        action="store_true",
        help=(
            "Refresh marketplace template metadata snapshot from the live Flowise API. "
            "Requires FLOWISE_API_ENDPOINT (default http://localhost:3000) and "
            "optionally FLOWISE_API_KEY in the environment."
        ),
    )
    parser.add_argument(
        "--credentials",
        action="store_true",
        help=(
            "Refresh credential metadata snapshot from the live Flowise API. "
            "SECURITY: only allowlisted fields are stored — no secrets. "
            "Requires FLOWISE_API_ENDPOINT and optionally FLOWISE_API_KEY."
        ),
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help=(
            "CI lint mode. With --nodes: run structural integrity checks on the freshly "
            "written node snapshot (outputAnchors present, versions numeric, anchor ID "
            "format, no duplicates) — exits 1 on any failure. "
            "With --credentials: check the existing credential snapshot for banned keys "
            "(no API call, no write) — exits 1 on any violation."
        ),
    )
    parser.add_argument(
        "--workday-mcp",
        action="store_true",
        help=(
            "Write (or re-write) the Workday MCP blueprint snapshot "
            "(schemas/workday_mcp.snapshot.json). "
            "Uses built-in defaults unless WORKDAY_MCP_CATALOG_PATH env var points "
            "to a custom JSON file. (Milestone 7.5)"
        ),
    )
    parser.add_argument(
        "--workday-api",
        action="store_true",
        help=(
            "Stub (Milestone 4): prints an informative message and exits 0. "
            "Real Workday API snapshot refresh is deferred to Milestone 5+."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse / fetch and diff but do not write any files.",
    )
    args = parser.parse_args(argv)

    if not (
        args.nodes
        or args.templates
        or args.credentials
        or args.workday_mcp
        or args.workday_api
    ):
        parser.print_help()
        print(
            "\nError: specify at least one of "
            "--nodes, --templates, --credentials, --workday-mcp, or --workday-api"
        )
        return 1

    exit_code = 0
    if args.nodes:
        exit_code = max(exit_code, refresh_nodes(dry_run=args.dry_run, validate=args.validate))
    if args.templates:
        exit_code = max(exit_code, refresh_templates(dry_run=args.dry_run))
    if args.credentials:
        exit_code = max(
            exit_code,
            refresh_credentials(
                dry_run=args.dry_run,
                validate_only=args.validate,
            ),
        )
    if args.workday_mcp:
        exit_code = max(exit_code, refresh_workday_mcp(dry_run=args.dry_run))
    if args.workday_api:
        exit_code = max(exit_code, refresh_workday_api(dry_run=args.dry_run))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
