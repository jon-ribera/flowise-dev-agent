"""Platform knowledge layer — local-first snapshots for Flowise platform data.

Roadmap 6, Milestones 1–3:
  M1: Node schema snapshots from FLOWISE_NODE_REFERENCE.md, O(1) local-first
      lookup with repair-only API fallback.
  M2: Marketplace template metadata snapshot (no flowData), TTL-based stale
      detection, find() for planning hints.
  M3: Credential metadata snapshot (allowlisted — no secrets), TTL 1 h,
      resolve() for BindCredential auto-fill, validate() for CI lint.

Public surface:
    FlowiseKnowledgeProvider — holds NodeSchemaStore + TemplateStore + CredentialStore.
    NodeSchemaStore          — loads schemas/flowise_nodes.snapshot.json.
    TemplateStore            — loads schemas/flowise_templates.snapshot.json.
    CredentialStore          — loads schemas/flowise_credentials.snapshot.json.
    _CRED_ALLOWLIST          — frozenset of allowed credential snapshot keys.

See ROADMAP6_Platform Knowledge.md for full design rationale.
"""

from flowise_dev_agent.knowledge.provider import (
    CredentialStore,
    FlowiseKnowledgeProvider,
    NodeSchemaStore,
    TemplateStore,
    _CRED_ALLOWLIST,
)

__all__ = [
    "CredentialStore",
    "FlowiseKnowledgeProvider",
    "NodeSchemaStore",
    "TemplateStore",
    "_CRED_ALLOWLIST",
]
