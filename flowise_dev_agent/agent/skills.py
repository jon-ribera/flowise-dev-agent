"""Skill file loader for the agent domain plugin system.

Skills are structured markdown files in flowise_dev_agent/skills/ that define
domain-specific knowledge for each phase of the agent loop.

Each skill file is parsed into named ## sections. Three sections are injected
into agent system prompts:
  - "Discover Context"  → injected into Discover phase prompt
  - "Patch Context"     → injected into Patch phase prompt
  - "Test Context"      → injected into Test phase prompt

Additional sections (Overview, Error Reference, etc.) are documentation only.

See flowise_dev_agent/skills/README.md for the full skill authoring guide.
See DESIGN_DECISIONS.md — DD-014.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("flowise_dev_agent.agent.skills")

# Skills live alongside the Python package, inside flowise_dev_agent/skills/
# This resolves to the flowise_dev_agent/skills/ directory regardless of where
# the package is installed or run from.
_SKILLS_DIR = Path(__file__).parent.parent / "skills"


# ---------------------------------------------------------------------------
# Skill class
# ---------------------------------------------------------------------------


class Skill:
    """A parsed skill file providing domain-specific context for agent phases.

    Instantiate via load_skill() rather than directly.
    """

    def __init__(self, name: str, content: str) -> None:
        self.name = name
        self._sections: dict[str, str] = _parse_sections(content)

    def section(self, heading: str, default: str = "") -> str:
        """Return the content of a ## heading section, or default if not found."""
        return self._sections.get(heading, default)

    @property
    def discover_context(self) -> str:
        """Text injected into the Discover phase system prompt."""
        return self.section("Discover Context")

    @property
    def patch_context(self) -> str:
        """Text injected into the Patch phase system prompt."""
        return self.section("Patch Context")

    @property
    def test_context(self) -> str:
        """Text injected into the Test phase system prompt."""
        return self.section("Test Context")

    @property
    def overview(self) -> str:
        """Skill overview (documentation only, not injected into prompts)."""
        return self.section("Overview")

    def __repr__(self) -> str:
        sections = list(self._sections.keys())
        return f"Skill(name={self.name!r}, sections={sections})"


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def _parse_sections(content: str) -> dict[str, str]:
    """Parse a markdown file into a dict of {## heading: body text}.

    Only parses level-2 headings (## Heading). Content before the first
    ## heading is ignored. Nested headings (###) are kept as-is in the body.

    Example:
        ## Discover Context
        Rule 1: ...
        Rule 2: ...

        ## Patch Context
        Rule A: ...

    Returns:
        {"Discover Context": "Rule 1: ...\nRule 2: ...", "Patch Context": "Rule A: ..."}
    """
    sections: dict[str, str] = {}
    current_key: str | None = None
    current_lines: list[str] = []

    for line in content.splitlines():
        if line.startswith("## "):
            if current_key is not None:
                sections[current_key] = "\n".join(current_lines).strip()
            current_key = line[3:].strip()
            current_lines = []
        elif current_key is not None:
            current_lines.append(line)

    if current_key is not None:
        sections[current_key] = "\n".join(current_lines).strip()

    return sections


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_skill(filename: str) -> Skill | None:
    """Load and parse a skill from flowise_dev_agent/skills/<filename>.md.

    Args:
        filename: Skill filename without the .md extension.
                  Examples: "flowise_builder", "workday_extend"

    Returns:
        Parsed Skill if the file exists, None if not found.
        On parse errors, logs a warning and returns None.

    The caller should always handle None gracefully — skills are optional
    enhancements, not hard dependencies. DomainTools falls back to its
    hardcoded context strings when no skill file is present.
    """
    path = _SKILLS_DIR / f"{filename}.md"

    if not path.exists():
        logger.debug("Skill file not found (using hardcoded defaults): %s", path)
        return None

    try:
        content = path.read_text(encoding="utf-8")
        skill = Skill(filename, content)
        logger.debug("Loaded skill '%s' from %s (%d sections)", filename, path, len(skill._sections))
        return skill
    except OSError as e:
        logger.warning("Failed to read skill file %s: %s", path, e)
        return None
    except Exception as e:
        logger.warning("Failed to parse skill file %s: %s", path, e)
        return None


def list_skills() -> list[str]:
    """Return the names of all skill files in the skills directory."""
    if not _SKILLS_DIR.exists():
        return []
    return [p.stem for p in _SKILLS_DIR.glob("*.md") if p.stem != "README"]
