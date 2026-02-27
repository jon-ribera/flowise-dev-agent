"""Render-safe contract validator and drift detection metrics.

Roadmap 11, Milestone 4 (DD-110, DD-111).

Validates compiled node data against the render-safe minimum contract.
Detects schema drift that would cause white-screen rendering in Flowise UI.

The validator is deterministic, cheap (no API calls), and runs on node data
dicts as produced by the compiler's _build_node_data().
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Drift validation result
# ---------------------------------------------------------------------------


@dataclass
class DriftIssue:
    """A single render-critical contract violation."""

    node_id: str
    node_type: str
    field: str
    message: str
    severity: str = "error"  # "error" or "warning"


@dataclass
class DriftResult:
    """Result of validating one or more nodes against the render-safe contract."""

    ok: bool
    issues: list[DriftIssue] = field(default_factory=list)

    @property
    def severity(self) -> str:
        """Worst severity across all issues ("error" > "warning")."""
        if any(i.severity == "error" for i in self.issues):
            return "error"
        if self.issues:
            return "warning"
        return "ok"

    @property
    def affected_node_types(self) -> set[str]:
        """Distinct node types that have issues."""
        return {i.node_type for i in self.issues}

    @property
    def human_readable(self) -> list[str]:
        """Short human-readable issue descriptions."""
        return [
            f"[{i.severity.upper()}] {i.node_type}/{i.node_id}: "
            f"{i.field} — {i.message}"
            for i in self.issues
        ]


# ---------------------------------------------------------------------------
# Observability metrics
# ---------------------------------------------------------------------------


@dataclass
class DriftMetrics:
    """Counters for schema cache performance and drift detection.

    Populated during compilation and surfaced in debug["schema_substrate"].
    """

    cache_hits_memory: int = 0
    cache_hits_postgres: int = 0
    cache_misses: int = 0
    mcp_fetches: int = 0
    drift_detected_count: int = 0
    repair_attempts_count: int = 0
    repaired_node_types: list[str] = field(default_factory=list)
    compile_retry_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict for debug state."""
        return {
            "cache_hits_memory": self.cache_hits_memory,
            "cache_hits_postgres": self.cache_hits_postgres,
            "cache_misses": self.cache_misses,
            "mcp_fetches": self.mcp_fetches,
            "drift_detected_count": self.drift_detected_count,
            "repair_attempts_count": self.repair_attempts_count,
            "repaired_node_types": list(self.repaired_node_types),
            "compile_retry_count": self.compile_retry_count,
        }

    def telemetry_dict(self) -> dict[str, Any]:
        """Flat telemetry keys for LangSmith metadata."""
        total = (
            self.cache_hits_memory
            + self.cache_hits_postgres
            + self.cache_misses
        )
        hit_rate = (
            (self.cache_hits_memory + self.cache_hits_postgres) / total
            if total > 0
            else 1.0
        )
        return {
            "telemetry.cache_hit_rate": round(hit_rate, 4),
            "telemetry.mcp_fetches": self.mcp_fetches,
            "telemetry.schema_repairs": self.repair_attempts_count,
            "telemetry.drift_detected": self.drift_detected_count,
        }


# ---------------------------------------------------------------------------
# Contract validator
# ---------------------------------------------------------------------------


def validate_node_render_contract(
    node_data: dict[str, Any],
    node_id: str = "",
) -> DriftResult:
    """Validate a single compiled node's data dict against the render-safe contract.

    Checks:
    1. options param → must have 'options' list
    2. asyncOptions param → must have 'loadMethod'
    3. credential requirement → must have credential inputParam
    4. numeric defaults → must be native int/float
    5. boolean defaults → must be native bool

    Returns DriftResult with ok=True when no render-critical issues found.
    """
    issues: list[DriftIssue] = []
    nid = node_id or node_data.get("id", "?")
    ntype = node_data.get("name", "?")

    input_params = node_data.get("inputParams") or []

    for param in input_params:
        ptype = param.get("type", "")
        pname = param.get("name", "?")

        # Rule 1: options param must have options list
        if ptype == "options" and not isinstance(param.get("options"), list):
            issues.append(DriftIssue(
                node_id=nid,
                node_type=ntype,
                field=f"inputParams.{pname}.options",
                message="type=options but 'options' is missing or not a list",
                severity="error",
            ))

        # Rule 2: asyncOptions must have loadMethod
        if ptype == "asyncOptions" and not param.get("loadMethod"):
            issues.append(DriftIssue(
                node_id=nid,
                node_type=ntype,
                field=f"inputParams.{pname}.loadMethod",
                message="type=asyncOptions but 'loadMethod' is missing",
                severity="error",
            ))

        # Rule 3: credential param must have credentialNames
        if ptype == "credential" and not param.get("credentialNames"):
            issues.append(DriftIssue(
                node_id=nid,
                node_type=ntype,
                field=f"inputParams.{pname}.credentialNames",
                message="type=credential but 'credentialNames' is missing",
                severity="warning",
            ))

        # Rule 4: numeric defaults must be native
        default = param.get("default")
        if default is not None:
            if ptype == "number" and isinstance(default, str):
                issues.append(DriftIssue(
                    node_id=nid,
                    node_type=ntype,
                    field=f"inputParams.{pname}.default",
                    message=f"type=number but default={default!r} is a string",
                    severity="warning",
                ))

            # Rule 5: boolean defaults must be native
            if ptype == "boolean" and isinstance(default, str):
                issues.append(DriftIssue(
                    node_id=nid,
                    node_type=ntype,
                    field=f"inputParams.{pname}.default",
                    message=f"type=boolean but default={default!r} is a string",
                    severity="warning",
                ))

    # Rule 6: credential requirement without credential inputParam
    # Only check credentialNames (schema-level indicator). The "credential" key
    # in compiled node data is the bound credential VALUE set by BindCredential,
    # not a schema-level requirement indicator.
    cred_names = node_data.get("credentialNames") or []
    has_cred_requirement = bool(cred_names)
    if has_cred_requirement:
        has_cred_param = any(
            p.get("type") == "credential" or p.get("name") == "credential"
            for p in input_params
        )
        if not has_cred_param:
            issues.append(DriftIssue(
                node_id=nid,
                node_type=ntype,
                field="inputParams.credential",
                message="node requires credentials but no credential inputParam found",
                severity="error",
            ))

    errors = [i for i in issues if i.severity == "error"]
    return DriftResult(ok=len(errors) == 0, issues=issues)


def validate_flow_render_contract(
    flow_data: dict[str, Any],
) -> DriftResult:
    """Validate all nodes in a compiled flow_data dict.

    Aggregates DriftResults from each node.
    """
    all_issues: list[DriftIssue] = []
    nodes = flow_data.get("nodes") or []

    for raw_node in nodes:
        node_data = raw_node.get("data") or {}
        node_id = raw_node.get("id") or node_data.get("id", "?")
        result = validate_node_render_contract(node_data, node_id)
        all_issues.extend(result.issues)

    errors = [i for i in all_issues if i.severity == "error"]
    return DriftResult(ok=len(errors) == 0, issues=all_issues)
