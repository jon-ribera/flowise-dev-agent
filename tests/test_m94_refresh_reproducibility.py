"""M9.4 — Refresh reproducibility tests.

Verifies that:

  1. The canonical reference filename is declared as a named constant.
  2. _REFERENCE_MD resolves to <repo_root>/<_CANONICAL_REFERENCE_NAME>.
  3. The canonical file exists in the repo root (clean-checkout guarantee).
  4. `refresh --nodes --dry-run` exits 0 when the canonical file is present.
  5. `refresh_nodes(dry_run=True)` exits 1 when the reference file is missing.
  6. The missing-file error message contains the canonical name and a recovery hint.
  7. `refresh_nodes(dry_run=True)` exits 0 when the file is present (no write).
  8. Dry-run with --nodes does NOT create or modify the snapshot file.

See roadmap9_production_graph_runtime_hardening.md — Milestone 9.4.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from flowise_dev_agent.knowledge.refresh import (
    _CANONICAL_REFERENCE_NAME,
    _NODES_SNAPSHOT,
    _REFERENCE_MD,
    _REPO_ROOT,
    refresh_nodes,
)


# ---------------------------------------------------------------------------
# 1. _CANONICAL_REFERENCE_NAME is a non-empty string constant
# ---------------------------------------------------------------------------


def test_canonical_reference_name_is_string():
    """_CANONICAL_REFERENCE_NAME must be a non-empty string."""
    assert isinstance(_CANONICAL_REFERENCE_NAME, str)
    assert _CANONICAL_REFERENCE_NAME.strip(), "_CANONICAL_REFERENCE_NAME must not be blank"


def test_canonical_reference_name_is_markdown():
    """The canonical reference must be a Markdown file."""
    assert _CANONICAL_REFERENCE_NAME.endswith(".md"), (
        f"Expected a .md file, got {_CANONICAL_REFERENCE_NAME!r}"
    )


# ---------------------------------------------------------------------------
# 2. _REFERENCE_MD resolves to repo_root / _CANONICAL_REFERENCE_NAME
# ---------------------------------------------------------------------------


def test_reference_md_path_matches_canonical_name():
    """_REFERENCE_MD must resolve to <repo_root>/<_CANONICAL_REFERENCE_NAME>."""
    expected = _REPO_ROOT / _CANONICAL_REFERENCE_NAME
    assert _REFERENCE_MD == expected, (
        f"_REFERENCE_MD={_REFERENCE_MD!r} does not match "
        f"_REPO_ROOT / _CANONICAL_REFERENCE_NAME={expected!r}"
    )


def test_reference_md_is_in_repo_root():
    """_REFERENCE_MD must live directly in the repository root (not a subdirectory)."""
    assert _REFERENCE_MD.parent == _REPO_ROOT, (
        f"_REFERENCE_MD parent is {_REFERENCE_MD.parent!r}, expected repo root {_REPO_ROOT!r}"
    )


# ---------------------------------------------------------------------------
# 3. Canonical file is present in the repo
# ---------------------------------------------------------------------------


def test_canonical_reference_file_exists():
    """FLOWISE_NODE_REFERENCE.md must exist in the repo root for reproducible snapshots."""
    assert _REFERENCE_MD.exists(), (
        f"Canonical reference file missing: {_REFERENCE_MD}\n"
        f"Restore with: git checkout HEAD -- {_CANONICAL_REFERENCE_NAME}"
    )


def test_canonical_reference_file_is_non_empty():
    """The reference file must contain actual content (at least 1 000 characters)."""
    content = _REFERENCE_MD.read_text(encoding="utf-8", errors="replace")
    assert len(content) >= 1_000, (
        f"Reference file looks empty or truncated: {len(content)} chars"
    )


# ---------------------------------------------------------------------------
# 4. subprocess dry-run exits 0 with canonical file present
# ---------------------------------------------------------------------------


def test_dry_run_nodes_exits_zero():
    """python -m flowise_dev_agent.knowledge.refresh --nodes --dry-run must exit 0."""
    result = subprocess.run(
        [sys.executable, "-m", "flowise_dev_agent.knowledge.refresh", "--nodes", "--dry-run"],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    assert result.returncode == 0, (
        f"--nodes --dry-run exited {result.returncode}.\n"
        f"stdout: {result.stdout[:500]}\n"
        f"stderr: {result.stderr[:500]}"
    )


def test_dry_run_output_mentions_node_count():
    """Dry-run output should report how many schemas were parsed."""
    result = subprocess.run(
        [sys.executable, "-m", "flowise_dev_agent.knowledge.refresh", "--nodes", "--dry-run"],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    combined = result.stdout + result.stderr
    # Should mention a node count > 0 somewhere
    assert any(char.isdigit() for char in combined), (
        "Dry-run output contains no numeric count — did parsing succeed?"
    )
    assert "nodes" in combined.lower()


# ---------------------------------------------------------------------------
# 5. Missing reference file → exit code 1
# ---------------------------------------------------------------------------


def test_missing_reference_file_returns_exit_1():
    """refresh_nodes(dry_run=True) must return 1 when the reference file is absent."""
    with patch(
        "flowise_dev_agent.knowledge.refresh._REFERENCE_MD",
        Path("/nonexistent/__test_missing_reference__.md"),
    ):
        exit_code = refresh_nodes(dry_run=True)

    assert exit_code == 1, (
        f"Expected exit code 1 for missing reference file, got {exit_code}"
    )


# ---------------------------------------------------------------------------
# 6. Missing-file error message is actionable
# ---------------------------------------------------------------------------


def test_missing_reference_error_contains_canonical_name(capsys, caplog):
    """The error message when the file is missing must name the canonical file."""
    import logging

    with patch(
        "flowise_dev_agent.knowledge.refresh._REFERENCE_MD",
        Path("/nonexistent/__test_missing_reference__.md"),
    ):
        with caplog.at_level(logging.ERROR, logger="flowise_dev_agent.knowledge.refresh"):
            refresh_nodes(dry_run=True)

    combined = caplog.text + capsys.readouterr().err
    assert _CANONICAL_REFERENCE_NAME in combined, (
        f"Error message does not mention canonical filename {_CANONICAL_REFERENCE_NAME!r}.\n"
        f"Log output: {caplog.text!r}"
    )


def test_missing_reference_error_contains_recovery_hint(capsys, caplog):
    """The error message must include a git-based recovery hint."""
    import logging

    with patch(
        "flowise_dev_agent.knowledge.refresh._REFERENCE_MD",
        Path("/nonexistent/__test_missing_reference__.md"),
    ):
        with caplog.at_level(logging.ERROR, logger="flowise_dev_agent.knowledge.refresh"):
            refresh_nodes(dry_run=True)

    log_text = caplog.text.lower()
    assert "git" in log_text or "restore" in log_text, (
        "Missing-file error must include a recovery hint (git checkout / restore). "
        f"Got: {caplog.text!r}"
    )


# ---------------------------------------------------------------------------
# 7. Dry-run with file present → exit 0
# ---------------------------------------------------------------------------


def test_dry_run_with_present_file_exits_zero():
    """refresh_nodes(dry_run=True) must return 0 when the canonical file exists."""
    exit_code = refresh_nodes(dry_run=True)
    assert exit_code == 0, (
        f"Expected exit code 0 from dry_run=True with present file, got {exit_code}"
    )


# ---------------------------------------------------------------------------
# 8. Dry-run must NOT write the snapshot file
# ---------------------------------------------------------------------------


def test_dry_run_does_not_write_snapshot(tmp_path):
    """Dry-run must not create or modify flowise_nodes.snapshot.json."""
    fake_snapshot = tmp_path / "flowise_nodes.snapshot.json"

    with patch("flowise_dev_agent.knowledge.refresh._NODES_SNAPSHOT", fake_snapshot), \
         patch("flowise_dev_agent.knowledge.refresh._SCHEMAS_DIR", tmp_path):
        exit_code = refresh_nodes(dry_run=True)

    assert exit_code == 0
    assert not fake_snapshot.exists(), (
        "--dry-run must not write flowise_nodes.snapshot.json, but the file was created"
    )
