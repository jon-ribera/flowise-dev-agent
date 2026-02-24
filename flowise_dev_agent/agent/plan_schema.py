"""PlanContract — structured plan metadata extracted from plan LLM output.

Roadmap 7, Milestone 7.2 (DD-067): Cross-Domain PlanContract + TestSuite.

The plan node (graph.py _make_plan_node) asks the LLM to append three
machine-readable sections to every plan:

    ## DOMAINS
    ## CREDENTIALS
    ## DATA_CONTRACTS

This module parses those sections plus the existing numbered sections
(1. GOAL, 5. SUCCESS CRITERIA) into a typed PlanContract dataclass, which
is then stored verbatim under facts["flowise"]["plan_contract"].

The converge node reads success_criteria from the contract to ground its
verdict in the exact testable conditions the developer approved.

Public API:
    PlanContract                — dataclass; all fields JSON-serialisable.
    _parse_plan_contract()      — regex parser; tolerant (missing → empty list).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# PlanContract dataclass
# ---------------------------------------------------------------------------


@dataclass
class PlanContract:
    """Structured plan metadata parsed from the plan node LLM output.

    Fields
    ------
    goal:
        One-sentence description of the chatflow's purpose.
        Parsed from "1. GOAL" section (first non-blank content line).

    domain_targets:
        Domain names involved.  Single-domain: ["flowise"].
        Multi-domain: ["flowise", "workday"].
        Parsed from "## DOMAINS" section (comma-separated).

    credential_requirements:
        Flowise credentialName values required (e.g. ["openAIApi", "workdayOAuth"]).
        Parsed from "## CREDENTIALS" section (comma-separated).

    data_fields:
        Field names that cross domain boundaries.
        Parsed from "## DATA_CONTRACTS" section (one per line, format:
        ``fieldName: source-domain → target-domain``).

    pii_fields:
        Subset of data_fields whose DATA_CONTRACTS line contains "[PII]".

    success_criteria:
        Testable conditions from "5. SUCCESS CRITERIA" or "## SUCCESS CRITERIA".
        Each bullet item (-, *, •) becomes one entry.

    action:
        "CREATE" if chatflow_id is None at plan time, else "UPDATE".
        Derived from the chatflow_id parameter — not parsed from plan text.

    raw_plan:
        Original plan text preserved verbatim for audit / debug.

    See DESIGN_DECISIONS.md — DD-067.
    See roadmap7_multi_domain_runtime_hardening.md — Milestone 7.2.
    """

    goal: str
    domain_targets: list[str]
    credential_requirements: list[str]
    data_fields: list[str]
    pii_fields: list[str]
    success_criteria: list[str]
    action: str   # "CREATE" | "UPDATE"
    raw_plan: str


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def _parse_plan_contract(
    plan_text: str,
    chatflow_id: str | None,
) -> PlanContract:
    """Extract structured PlanContract from plan LLM output.

    Parameters
    ----------
    plan_text:
        The full text returned by the plan node LLM call.
    chatflow_id:
        Current chatflow ID from AgentState (None → action="CREATE").

    Returns
    -------
    PlanContract
        Always returns a valid PlanContract.  Missing sections default to
        empty lists / empty string.  Never raises on malformed input.

    Parsing rules
    -------------
    Sections are located by header then captured until the next section
    header (``## …`` or ``N. …``) or end-of-string.  Order in the plan
    text does not matter — each section is searched independently.

    ``## DOMAINS``      comma-separated or newline-separated domain names.
    ``## CREDENTIALS``  comma-separated credentialName values; "(none)" → [].
    ``## DATA_CONTRACTS``
        One field per line: ``fieldName: source → target`` or
        ``fieldName: source → target [PII]``.  Lines with "[PII]" also
        populate pii_fields.
    ``5. SUCCESS CRITERIA`` or ``## SUCCESS CRITERIA``
        Bullet items (leading -, *, or •) become individual entries.
    ``1. GOAL``
        First non-blank, non-header content line becomes goal.
    """
    action = "UPDATE" if chatflow_id else "CREATE"

    if not plan_text:
        return PlanContract(
            goal="",
            domain_targets=[],
            credential_requirements=[],
            data_fields=[],
            pii_fields=[],
            success_criteria=[],
            action=action,
            raw_plan=plan_text or "",
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _section_text(header_pattern: str) -> str:
        """Return raw body text for a section identified by header_pattern.

        Stops at the next ``## …`` header, next numbered section ``N. ``,
        or end-of-string.  Returns "" when the section is absent.
        """
        m = re.search(
            rf"{header_pattern}\s*\n(.*?)(?=\n##\s|\n\d+\.\s|\Z)",
            plan_text,
            re.DOTALL | re.IGNORECASE,
        )
        return m.group(1).strip() if m else ""

    _NONE_TOKENS = frozenset({"(none)", "none", "n/a", "-"})

    def _parse_csv_section(header_pattern: str) -> list[str]:
        """Parse comma/newline-separated section into a clean non-empty list."""
        raw = _section_text(header_pattern)
        if not raw or raw.strip().lower() in _NONE_TOKENS:
            return []
        items = re.split(r"[,\n]", raw)
        cleaned = []
        for item in items:
            s = item.strip().strip("-•*").strip()
            if s and s.lower() not in _NONE_TOKENS:
                cleaned.append(s)
        return cleaned

    # ------------------------------------------------------------------
    # domain_targets
    # ------------------------------------------------------------------

    domain_targets = _parse_csv_section(r"##\s*DOMAINS")

    # ------------------------------------------------------------------
    # credential_requirements
    # ------------------------------------------------------------------

    credential_requirements = _parse_csv_section(r"##\s*CREDENTIALS")

    # ------------------------------------------------------------------
    # data_fields + pii_fields  (from ## DATA_CONTRACTS)
    # ------------------------------------------------------------------

    data_fields: list[str] = []
    pii_fields: list[str] = []
    dc_text = _section_text(r"##\s*DATA[_\s]CONTRACTS?")
    for line in dc_text.splitlines():
        line = line.strip()
        if not line or line.lower() in _NONE_TOKENS:
            continue
        # Expect "fieldName: source → target" or "fieldName: source → target [PII]"
        field_match = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\s*:", line)
        if field_match:
            fname = field_match.group(1)
            data_fields.append(fname)
            if re.search(r"\[PII\]", line, re.IGNORECASE):
                pii_fields.append(fname)

    # ------------------------------------------------------------------
    # success_criteria  (from numbered section 5 OR ## SUCCESS CRITERIA)
    # ------------------------------------------------------------------

    sc_header = r"(?:##\s*SUCCESS\s+CRITERIA|5\.\s+SUCCESS\s+CRITERIA)"
    sc_text = _section_text(sc_header)
    success_criteria: list[str] = []
    for line in sc_text.splitlines():
        stripped = line.strip()
        if re.match(r"^[-*•]", stripped):
            criterion = re.sub(r"^[-*•]\s*", "", stripped).strip()
            if criterion:
                success_criteria.append(criterion)

    # ------------------------------------------------------------------
    # goal  (from numbered section 1. GOAL)
    # ------------------------------------------------------------------

    goal = ""
    goal_text = _section_text(r"1\.\s+GOAL")
    for line in goal_text.splitlines():
        line = line.strip()
        # Skip the instruction line that appears in the prompt template
        if line and not line.lower().startswith("one sentence"):
            goal = line
            break

    return PlanContract(
        goal=goal,
        domain_targets=domain_targets,
        credential_requirements=credential_requirements,
        data_fields=data_fields,
        pii_fields=pii_fields,
        success_criteria=success_criteria,
        action=action,
        raw_plan=plan_text,
    )
