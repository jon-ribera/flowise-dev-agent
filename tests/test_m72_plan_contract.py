"""Tests for Milestone 7.2: Cross-Domain PlanContract + TestSuite (DD-067).

Covers the three acceptance tests from the roadmap:
  Test group 1 — Full plan with all sections parsed correctly.
  Test group 2 — Missing sections default to empty lists (tolerant parser).
  Test group 3 — Multi-domain plan → domain_targets includes both domains.

Plus:
  - PlanContract fields are JSON-serialisable via dataclasses.asdict()
  - action="CREATE" when chatflow_id=None, "UPDATE" when chatflow_id is set
  - pii_fields populated only for lines with [PII]
  - TestSuite backward-compat: new fields have defaults
  - facts["flowise"]["plan_contract"] merge preserves existing keys

See roadmap7_multi_domain_runtime_hardening.md — Milestone 7.2.
"""

from __future__ import annotations

import json
from dataclasses import asdict

import pytest

from flowise_dev_agent.agent.domain import TestSuite
from flowise_dev_agent.agent.plan_schema import PlanContract, _parse_plan_contract


# ---------------------------------------------------------------------------
# Sample plan texts
# ---------------------------------------------------------------------------

_FULL_PLAN = """\
1. GOAL
   Build a customer support chatflow that answers product questions using OpenAI.

2. INPUTS
   User text message via chat interface.

3. OUTPUTS
   Natural language response from ChatOpenAI.

4. CONSTRAINTS
   - Requires openAIApi credential (present in Flowise instance).
   - GPT-4 or GPT-3.5-turbo model recommended.

5. SUCCESS CRITERIA
   - Happy-path test: "What is the return policy?" → response must contain "policy"
   - Edge-case test: empty input "" → response must handle gracefully without error
   - Response must arrive within 10 seconds

6. PATTERN
   Simple Conversation: ChatOpenAI + BufferMemory + ConversationChain

7. ACTION
   CREATE a new chatflow named "Customer Support Bot"

## DOMAINS
flowise

## CREDENTIALS
openAIApi

## DATA_CONTRACTS
(none)
"""

_MULTI_DOMAIN_PLAN = """\
1. GOAL
   Build a hiring chatflow that uses Workday MCP to create employee records in Flowise.

2. INPUTS
   HR manager request: employee name, hire date, department.

3. OUTPUTS
   Confirmation message with new employee Workday ID.

4. CONSTRAINTS
   - Requires openAIApi and workdayOAuth credentials.
   - Workday MCP node must be wired to Flowise chatflow.

5. SUCCESS CRITERIA
   - Happy-path test: "Hire Alice Smith in Engineering" → response includes Workday employee ID
   - Edge-case test: missing hire date → response asks for missing information
   - workdayOAuth credential must be bound correctly

6. PATTERN
   Tool Agent: ChatOpenAI + WorkdayMCP + ToolAgent

7. ACTION
   CREATE a new chatflow named "HR Hiring Bot"

## DOMAINS
flowise,workday

## CREDENTIALS
openAIApi, workdayOAuth

## DATA_CONTRACTS
employeeName: flowise → workday
hireDate: flowise → workday [PII]
employeeId: workday → flowise
"""

_MINIMAL_PLAN = """\
Build a simple chatflow.

7. ACTION
   CREATE a new chatflow named "Simple Bot"
"""

_NO_METADATA_PLAN = """\
1. GOAL
   A chatflow with no machine-readable metadata sections.

5. SUCCESS CRITERIA
   - The chatflow responds to user messages

7. ACTION
   CREATE
"""


# ---------------------------------------------------------------------------
# Test group 1 — Full plan with all sections parsed correctly
# ---------------------------------------------------------------------------


class TestFullPlanParsing:

    def test_goal_extracted(self):
        c = _parse_plan_contract(_FULL_PLAN, chatflow_id=None)
        assert "customer support" in c.goal.lower() or "chatflow" in c.goal.lower()

    def test_domain_targets_flowise_only(self):
        c = _parse_plan_contract(_FULL_PLAN, chatflow_id=None)
        assert c.domain_targets == ["flowise"]

    def test_credential_requirements(self):
        c = _parse_plan_contract(_FULL_PLAN, chatflow_id=None)
        assert "openAIApi" in c.credential_requirements

    def test_no_data_fields_when_none(self):
        c = _parse_plan_contract(_FULL_PLAN, chatflow_id=None)
        assert c.data_fields == []
        assert c.pii_fields == []

    def test_success_criteria_count(self):
        c = _parse_plan_contract(_FULL_PLAN, chatflow_id=None)
        assert len(c.success_criteria) == 3

    def test_success_criteria_content(self):
        c = _parse_plan_contract(_FULL_PLAN, chatflow_id=None)
        full_text = " ".join(c.success_criteria).lower()
        assert "happy-path" in full_text or "return policy" in full_text
        assert "edge-case" in full_text or "empty" in full_text

    def test_action_create_when_no_chatflow(self):
        c = _parse_plan_contract(_FULL_PLAN, chatflow_id=None)
        assert c.action == "CREATE"

    def test_action_update_when_chatflow_present(self):
        c = _parse_plan_contract(_FULL_PLAN, chatflow_id="abc-123")
        assert c.action == "UPDATE"

    def test_raw_plan_preserved(self):
        c = _parse_plan_contract(_FULL_PLAN, chatflow_id=None)
        assert c.raw_plan == _FULL_PLAN

    def test_asdict_is_json_serialisable(self):
        c = _parse_plan_contract(_FULL_PLAN, chatflow_id=None)
        d = asdict(c)
        json_str = json.dumps(d)  # must not raise
        assert "domain_targets" in json_str

    def test_asdict_keys_complete(self):
        c = _parse_plan_contract(_FULL_PLAN, chatflow_id=None)
        d = asdict(c)
        expected_keys = {
            "goal", "domain_targets", "credential_requirements",
            "data_fields", "pii_fields", "success_criteria", "action", "raw_plan",
        }
        assert expected_keys == set(d.keys())


# ---------------------------------------------------------------------------
# Test group 2 — Missing sections default to empty lists
# ---------------------------------------------------------------------------


class TestMissingSectionsTolerance:

    def test_empty_string_returns_valid_contract(self):
        c = _parse_plan_contract("", chatflow_id=None)
        assert isinstance(c, PlanContract)
        assert c.domain_targets == []
        assert c.credential_requirements == []
        assert c.data_fields == []
        assert c.pii_fields == []
        assert c.success_criteria == []
        assert c.goal == ""
        assert c.action == "CREATE"

    def test_no_metadata_sections_gives_empty_lists(self):
        c = _parse_plan_contract(_MINIMAL_PLAN, chatflow_id=None)
        assert c.domain_targets == []
        assert c.credential_requirements == []
        assert c.data_fields == []
        assert c.pii_fields == []

    def test_success_criteria_parsed_from_numbered_section(self):
        """Even without ## SUCCESS CRITERIA, the numbered 5. section is parsed."""
        c = _parse_plan_contract(_NO_METADATA_PLAN, chatflow_id=None)
        assert len(c.success_criteria) >= 1
        assert any("chatflow" in s.lower() for s in c.success_criteria)

    def test_none_plan_text_returns_empty_contract(self):
        """Passing an empty plan should not raise."""
        c = _parse_plan_contract("", chatflow_id=None)
        assert c.action == "CREATE"

    def test_malformed_metadata_no_raise(self):
        """Garbage text after ## DOMAINS header should not raise."""
        plan = "## DOMAINS\n!!not a domain!!\n## CREDENTIALS\n~invalid~\n"
        c = _parse_plan_contract(plan, chatflow_id=None)
        # Parser should return something without raising
        assert isinstance(c, PlanContract)


# ---------------------------------------------------------------------------
# Test group 3 — Multi-domain plan
# ---------------------------------------------------------------------------


class TestMultiDomainPlan:

    def test_domain_targets_includes_flowise_and_workday(self):
        c = _parse_plan_contract(_MULTI_DOMAIN_PLAN, chatflow_id=None)
        assert "flowise" in c.domain_targets
        assert "workday" in c.domain_targets

    def test_domain_targets_length(self):
        c = _parse_plan_contract(_MULTI_DOMAIN_PLAN, chatflow_id=None)
        assert len(c.domain_targets) == 2

    def test_multiple_credentials(self):
        c = _parse_plan_contract(_MULTI_DOMAIN_PLAN, chatflow_id=None)
        assert "openAIApi" in c.credential_requirements
        assert "workdayOAuth" in c.credential_requirements

    def test_data_fields_cross_domain(self):
        c = _parse_plan_contract(_MULTI_DOMAIN_PLAN, chatflow_id=None)
        assert "employeeName" in c.data_fields
        assert "hireDate" in c.data_fields
        assert "employeeId" in c.data_fields

    def test_pii_fields_populated(self):
        c = _parse_plan_contract(_MULTI_DOMAIN_PLAN, chatflow_id=None)
        assert "hireDate" in c.pii_fields

    def test_non_pii_fields_not_in_pii(self):
        c = _parse_plan_contract(_MULTI_DOMAIN_PLAN, chatflow_id=None)
        assert "employeeName" not in c.pii_fields
        assert "employeeId" not in c.pii_fields

    def test_multi_domain_success_criteria_count(self):
        c = _parse_plan_contract(_MULTI_DOMAIN_PLAN, chatflow_id=None)
        assert len(c.success_criteria) == 3


# ---------------------------------------------------------------------------
# TestSuite backward-compat: new fields must have defaults
# ---------------------------------------------------------------------------


class TestTestSuiteBackwardCompat:

    def test_construct_without_new_fields(self):
        """Existing call-sites that don't pass new fields must not break."""
        ts = TestSuite(
            happy_question="What is the return policy?",
            edge_question="",
            domain_name="flowise",
        )
        assert ts.domain_scopes == []
        assert ts.integration_tests == []

    def test_construct_with_new_fields(self):
        ts = TestSuite(
            happy_question="Hire Alice",
            edge_question="Missing hire date",
            domain_name="flowise",
            domain_scopes=["flowise", "workday"],
            integration_tests=["Hire employee → Workday ID returned in Flowise response"],
        )
        assert ts.domain_scopes == ["flowise", "workday"]
        assert len(ts.integration_tests) == 1

    def test_metadata_default_still_works(self):
        ts = TestSuite(happy_question="q", edge_question="", domain_name="flowise")
        assert ts.metadata == {}
