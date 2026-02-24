"""Offline schema audit: compare flowise_nodes.snapshot.json against the live Flowise API.

Fetches all nodes from GET /api/v1/nodes, normalises them with _normalize_api_schema()
(the same function used by the repair path), then diffs every field against the local
snapshot.  Run this whenever Flowise is upgraded or when the snapshot feels stale.

Usage:
    python -m flowise_dev_agent.knowledge.audit
    python -m flowise_dev_agent.knowledge.audit --ci        # exit 1 on MAJOR/CRITICAL
    python -m flowise_dev_agent.knowledge.audit --output schemas/flowise_audit_report.json

Output:  schemas/flowise_audit_report.json  (default)

Severity levels:
    PASS     — snapshot and live API match exactly
    MINOR    — non-breaking difference (e.g. description text changed)
    MAJOR    — structural difference (anchor count/type mismatch, version wrong)
    CRITICAL — node missing from snapshot or outputAnchors empty

Custom nodes excluded from comparison (not in the public Flowise API):
    cis, cisChat  — Workday-specific nodes, kept in snapshot intentionally

See the implementation plan in docs/compiler-schema-hardening.md.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).parent.parent.parent
_SCHEMAS_DIR = _REPO_ROOT / "schemas"
_NODES_SNAPSHOT = _SCHEMAS_DIR / "flowise_nodes.snapshot.json"
_AUDIT_REPORT = _SCHEMAS_DIR / "flowise_audit_report.json"

# Nodes that are intentionally in our snapshot but NOT in the public Flowise API.
# These are Workday-specific or otherwise custom nodes.
_CUSTOM_NODES: frozenset[str] = frozenset({"cis", "cisChat"})

# Primitive input types — must match provider.py exactly.
_PRIMITIVE_TYPES: frozenset[str] = frozenset({
    "string", "number", "boolean", "password", "json", "code",
    "file", "date", "credential", "asyncOptions", "options",
    "datagrid", "tabs", "multiOptions", "array",
})


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


async def _fetch_json(url: str, api_key: str | None) -> Any:
    """Minimal async HTTP GET that returns parsed JSON."""
    import urllib.request
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, headers=headers)
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: json.loads(urllib.request.urlopen(req, timeout=30).read()),
    )


async def _fetch_all_nodes(base_url: str, api_key: str | None) -> list[dict]:
    """Fetch the full node list + per-node details from the live Flowise API."""
    node_list: list[dict] = await _fetch_json(f"{base_url}/api/v1/nodes", api_key)
    if not isinstance(node_list, list):
        raise ValueError(f"Expected list from /api/v1/nodes, got {type(node_list).__name__}")

    logger.info("Fetched node list: %d nodes", len(node_list))

    # Fetch per-node details in parallel (batches of 20 to avoid overloading server)
    results: list[dict] = []
    batch_size = 20
    for i in range(0, len(node_list), batch_size):
        batch = node_list[i : i + batch_size]
        tasks = [
            _fetch_json(f"{base_url}/api/v1/nodes/{n['name']}", api_key)
            for n in batch
            if n.get("name")
        ]
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)
        for n, res in zip(batch, batch_results):
            if isinstance(res, Exception):
                logger.warning("Failed to fetch node %s: %s", n.get("name"), res)
            elif isinstance(res, dict):
                results.append(res)
        logger.info("  fetched %d/%d …", min(i + batch_size, len(node_list)), len(node_list))

    return results


# ---------------------------------------------------------------------------
# Normalisation (reuses the exact same logic as provider.py)
# ---------------------------------------------------------------------------


def _normalize(raw: dict) -> dict:
    """Identical transformation used by provider._normalize_api_schema().

    Kept local here so audit.py has no runtime dependency on provider.py
    (audit is a dev tool, not a production module).
    """
    node_name = raw.get("name", "")
    base_classes: list[str] = raw.get("baseClasses") or []
    raw_inputs: list[dict] = raw.get("inputs") or []

    input_anchors: list[dict] = []
    input_params: list[dict] = []
    for inp in raw_inputs:
        entry = dict(inp)
        inp_type = entry.get("type", "")
        entry["id"] = f"{{nodeId}}-input-{entry.get('name', '')}-{inp_type}"
        if inp_type in _PRIMITIVE_TYPES:
            input_params.append(entry)
        else:
            input_anchors.append(entry)

    raw_oa: list[dict] = raw.get("outputAnchors") or []
    if raw_oa:
        output_anchors = []
        for oa in raw_oa:
            entry = dict(oa)
            oa_id = entry.get("id", "")
            if oa_id and "{nodeId}" not in oa_id:
                oa_type = entry.get("type", "")
                oa_name = entry.get("name", node_name)
                entry["id"] = f"{{nodeId}}-output-{oa_name}-{oa_type}"
            output_anchors.append(entry)
    else:
        output_anchors = [
            {
                "id": f"{{nodeId}}-output-{node_name}-{'|'.join(base_classes)}",
                "name": node_name,
                "label": raw.get("label", node_name),
                "type": " | ".join(base_classes),
            }
        ]

    return {
        **raw,
        "node_type": node_name,
        "inputAnchors": input_anchors,
        "inputParams": input_params,
        "outputAnchors": output_anchors,
        "outputs": {},
    }


# ---------------------------------------------------------------------------
# Diff helpers
# ---------------------------------------------------------------------------


def _to_float(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _anchor_key(a: dict) -> str:
    return f"{a.get('name','?')}:{a.get('type','?')}"


def _diff_anchors(snap_list: list[dict], live_list: list[dict]) -> list[str]:
    """Return a list of human-readable differences between two anchor lists."""
    diffs: list[str] = []
    snap_keys = [_anchor_key(a) for a in snap_list]
    live_keys = [_anchor_key(a) for a in live_list]

    if snap_keys == live_keys:
        return []

    snap_set = set(snap_keys)
    live_set = set(live_keys)
    for k in live_set - snap_set:
        diffs.append(f"missing_from_snapshot: {k}")
    for k in snap_set - live_set:
        diffs.append(f"extra_in_snapshot: {k}")
    # Order change (same items, different order)
    if snap_set == live_set and snap_keys != live_keys:
        diffs.append(f"order_differs: snap={snap_keys} live={live_keys}")
    return diffs


def _audit_node(snap: dict, live_norm: dict) -> dict:
    """Compare a single snapshot entry against a live-API-normalized entry.

    Returns a result dict with keys: status, version, inputAnchors, inputParams,
    outputAnchors, baseClasses, issues.
    """
    issues: list[str] = []

    # --- version ---
    snap_v = _to_float(snap.get("version"))
    live_v = _to_float(live_norm.get("version"))
    version_match = snap_v is not None and live_v is not None and snap_v == live_v
    if not version_match:
        issues.append(f"version: snap={snap.get('version')!r} live={live_norm.get('version')!r}")

    # --- baseClasses ---
    snap_bc = snap.get("baseClasses") or []
    live_bc = live_norm.get("baseClasses") or []
    bc_match = snap_bc == live_bc
    if not bc_match:
        issues.append(f"baseClasses: snap={snap_bc} live={live_bc}")

    # --- inputAnchors ---
    ia_diffs = _diff_anchors(snap.get("inputAnchors") or [], live_norm.get("inputAnchors") or [])
    if ia_diffs:
        issues.extend(f"inputAnchor/{d}" for d in ia_diffs)

    # --- inputParams ---
    ip_diffs = _diff_anchors(snap.get("inputParams") or [], live_norm.get("inputParams") or [])
    if ip_diffs:
        issues.extend(f"inputParam/{d}" for d in ip_diffs)

    # --- outputAnchors ---
    snap_oa = snap.get("outputAnchors") or []
    live_oa = live_norm.get("outputAnchors") or []
    oa_diffs = _diff_anchors(snap_oa, live_oa)
    oa_empty = len(snap_oa) == 0
    if oa_empty:
        issues.append("outputAnchors: empty in snapshot (CRITICAL)")
    elif oa_diffs:
        issues.extend(f"outputAnchor/{d}" for d in oa_diffs)

    # --- determine severity ---
    # order_differs-only issues are MINOR (param ordering doesn't affect compilation).
    # Missing/extra anchors or params are MAJOR (structural change breaks compiler).
    _structural = [
        i for i in issues
        if "missing_from_snapshot" in i or "extra_in_snapshot" in i
    ]
    _order_only = [i for i in issues if "order_differs" in i]
    _version_or_class = [i for i in issues if "version" in i or "baseClasses" in i or "outputAnchor" in i]

    if oa_empty:
        status = "CRITICAL"
    elif _structural or _version_or_class:
        status = "MAJOR"
    elif _order_only or issues:
        status = "MINOR"
    else:
        status = "PASS"

    return {
        "status": status,
        "issues": issues,
        "version": {
            "snapshot": snap.get("version"),
            "live": live_norm.get("version"),
            "match": version_match,
        },
        "baseClasses": {
            "snapshot": snap_bc,
            "live": live_bc,
            "match": bc_match,
        },
        "inputAnchors": {
            "snapshot_count": len(snap.get("inputAnchors") or []),
            "live_count": len(live_norm.get("inputAnchors") or []),
            "diff": ia_diffs,
        },
        "inputParams": {
            "snapshot_count": len(snap.get("inputParams") or []),
            "live_count": len(live_norm.get("inputParams") or []),
            "diff": ip_diffs,
        },
        "outputAnchors": {
            "snapshot_count": len(snap_oa),
            "live_count": len(live_oa),
            "diff": oa_diffs,
            "valid": not oa_empty,
        },
    }


# ---------------------------------------------------------------------------
# Main audit runner
# ---------------------------------------------------------------------------


async def run_audit(
    base_url: str,
    api_key: str | None,
    output_path: Path,
    ci_mode: bool = False,
) -> int:
    """Fetch all live nodes, compare against snapshot, write report.

    Returns exit code (0 = success/only-minor, 1 = MAJOR/CRITICAL found in CI mode).
    """
    # Load snapshot
    if not _NODES_SNAPSHOT.exists():
        logger.error("Snapshot not found: %s", _NODES_SNAPSHOT)
        return 1
    snap_raw: list[dict] = json.loads(_NODES_SNAPSHOT.read_bytes())
    snap_index: dict[str, dict] = {n["name"]: n for n in snap_raw if n.get("name")}
    logger.info("Snapshot loaded: %d nodes", len(snap_index))

    # Fetch live nodes
    logger.info("Fetching from %s …", base_url)
    try:
        live_nodes = await _fetch_all_nodes(base_url, api_key)
    except Exception:
        logger.exception("Failed to fetch nodes from live Flowise API")
        return 1

    live_index: dict[str, dict] = {n["name"]: n for n in live_nodes if n.get("name")}
    logger.info("Live API: %d nodes", len(live_index))

    # Categorise
    live_names = set(live_index)
    snap_names = set(snap_index)
    missing_from_snap = live_names - snap_names - _CUSTOM_NODES
    extra_in_snap = snap_names - live_names - _CUSTOM_NODES

    node_results: dict[str, dict] = {}
    counts = {"PASS": 0, "MINOR": 0, "MAJOR": 0, "CRITICAL": 0}

    for name in sorted(live_names):
        if name in _CUSTOM_NODES:
            continue
        snap_entry = snap_index.get(name)
        if snap_entry is None:
            node_results[name] = {
                "status": "CRITICAL",
                "issues": ["missing from snapshot"],
            }
            counts["CRITICAL"] += 1
            continue
        live_norm = _normalize(live_index[name])
        result = _audit_node(snap_entry, live_norm)
        node_results[name] = result
        counts[result["status"]] += 1

    for name in sorted(extra_in_snap):
        node_results[name] = {
            "status": "MINOR",
            "issues": ["in snapshot but not in live API (deprecated?)"],
        }
        counts["MINOR"] += 1

    # Print console summary
    print(f"\n{'='*60}")
    print("FLOWISE NODE SCHEMA AUDIT")
    print(f"{'='*60}")
    print(f"  Live API nodes : {len(live_index)}")
    print(f"  Snapshot nodes : {len(snap_index)}")
    print(f"  Custom (excl.) : {', '.join(sorted(_CUSTOM_NODES))}")
    print(f"\n  PASS     : {counts['PASS']}")
    print(f"  MINOR    : {counts['MINOR']}")
    print(f"  MAJOR    : {counts['MAJOR']}")
    print(f"  CRITICAL : {counts['CRITICAL']}")

    non_pass = {n: r for n, r in node_results.items() if r["status"] != "PASS"}
    if non_pass:
        print(f"\n{'-'*60}")
        print("NON-PASS NODES:")
        for name, r in sorted(non_pass.items()):
            sev = r["status"]
            issues = r.get("issues", [])
            print(f"\n  [{sev}] {name}")
            for issue in issues[:5]:
                print(f"    * {issue}")
            if len(issues) > 5:
                print(f"    ... (+{len(issues) - 5} more)")
    else:
        print("\n  All audited nodes PASS.")

    print(f"\n{'='*60}\n")

    # Write JSON report
    report = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
        "flowise_api": base_url,
        "summary": {
            "total_live_nodes": len(live_index),
            "total_snapshot_nodes": len(snap_index),
            "excluded_custom": sorted(_CUSTOM_NODES),
            "missing_from_snapshot": sorted(missing_from_snap),
            "extra_in_snapshot": sorted(extra_in_snap),
            **counts,
        },
        "nodes": node_results,
    }
    _SCHEMAS_DIR.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Report written: %s", output_path)

    if ci_mode and (counts["MAJOR"] > 0 or counts["CRITICAL"] > 0):
        logger.error("CI mode: %d MAJOR + %d CRITICAL findings", counts["MAJOR"], counts["CRITICAL"])
        return 1
    return 0


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m flowise_dev_agent.knowledge.audit",
        description=(
            "Compare schemas/flowise_nodes.snapshot.json against the live Flowise API. "
            "Outputs a structured JSON diff report. "
            "Run this after upgrading Flowise or when node schemas feel stale."
        ),
        epilog="""
Examples:
  python -m flowise_dev_agent.knowledge.audit
  python -m flowise_dev_agent.knowledge.audit --ci
  python -m flowise_dev_agent.knowledge.audit --output schemas/my_audit.json
""",
    )
    parser.add_argument(
        "--ci",
        action="store_true",
        help="Exit 1 if any MAJOR or CRITICAL issues are found (CI gate mode).",
    )
    parser.add_argument(
        "--output",
        default=str(_AUDIT_REPORT),
        help=f"Path to write the JSON report (default: {_AUDIT_REPORT})",
    )
    args = parser.parse_args(argv)

    base_url = os.environ.get("FLOWISE_API_ENDPOINT", "http://localhost:3000").rstrip("/")
    api_key = os.environ.get("FLOWISE_API_KEY")
    output_path = Path(args.output)

    return asyncio.run(run_audit(base_url, api_key, output_path, ci_mode=args.ci))


if __name__ == "__main__":
    sys.exit(main())
