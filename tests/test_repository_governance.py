from __future__ import annotations

import shutil
from pathlib import Path

from scripts.check_repository_governance import (
    CANONICAL_SKILLS,
    ROOT,
    evaluate_repository,
    forbidden_headings,
    forbidden_path_reason,
)


def _copy_governance_fixture(target: Path) -> tuple[Path, ...]:
    for directory in (".agents", ".claude", ".github", "docs"):
        shutil.copytree(ROOT / directory, target / directory)
    for filename in ("README.md", "AGENTS.md", "CLAUDE.md", "pyproject.toml"):
        shutil.copy2(ROOT / filename, target / filename)
    return tuple(path for path in target.rglob("*") if path.is_file())


def _codes(root: Path) -> set[str]:
    paths = tuple(path for path in root.rglob("*") if path.is_file())
    return {violation.code for violation in evaluate_repository(root, paths=paths)}


def test_repository_governance_is_clean() -> None:
    assert evaluate_repository(ROOT) == ()


def test_project_state_document_names_are_rejected() -> None:
    assert forbidden_path_reason("docs/validation-report-example.md") is not None
    assert forbidden_path_reason("docs/spec-audit-log.md") is not None
    assert forbidden_path_reason("docs/reports/archive/status-notes.md") is not None
    assert forbidden_path_reason("docs/status.json") is not None
    assert forbidden_path_reason("docs/specs/archive/design.md") is not None
    assert forbidden_path_reason("docs/specs/reports/weekly-progress.md") is not None
    assert forbidden_path_reason("docs/specs/reports/status.json") is not None
    assert forbidden_path_reason("docs/specs/reports/weekly-notes.json") is not None
    assert forbidden_path_reason("docs/policies/archive/milestone-2026-08.md") is not None
    assert forbidden_path_reason("MILESTONES.md") is not None
    assert forbidden_path_reason("ROADMAP-2026.md") is not None
    assert forbidden_path_reason("src/champions_sim/progression.py") is None
    assert forbidden_path_reason("tests/test_progress_bar.py") is None
    assert forbidden_path_reason("specs/sim-phase-contract.md") is not None
    assert forbidden_path_reason("docs/specs/battle-engine.md") is None
    assert forbidden_path_reason("docs/adr/0001-example.md") is None


def test_project_state_headings_are_rejected_without_blocking_normative_language() -> None:
    assert forbidden_headings("# Product\n\n## Next steps\n") == ("Next steps",)
    assert forbidden_headings("# Product\n\n## Remaining work for release\n") == (
        "Remaining work for release",
    )
    assert forbidden_headings("# Product\n\n## 次の大きな目的\n") == (
        "次の大きな目的",
    )
    assert forbidden_headings("# Readiness\n\n## Readiness decision\n") == ()


def test_repository_validator_rejects_missing_path_and_broken_link(tmp_path: Path) -> None:
    _copy_governance_fixture(tmp_path)
    (tmp_path / "README.md").unlink()
    policy = tmp_path / "docs/policies/project-workflow.md"
    policy.write_text(
        policy.read_text(encoding="utf-8") + "\n[missing](missing.md)\n",
        encoding="utf-8",
    )

    assert {"missing_required_path", "broken_markdown_link"} <= _codes(tmp_path)


def test_repository_validator_rejects_agent_contract_drift(tmp_path: Path) -> None:
    _copy_governance_fixture(tmp_path)
    (tmp_path / "CLAUDE.md").write_text("# Claude\n", encoding="utf-8")

    invalid_frontmatter = (
        tmp_path / ".agents/skills" / CANONICAL_SKILLS[0] / "SKILL.md"
    )
    invalid_frontmatter.write_text("# Missing frontmatter\n", encoding="utf-8")

    invalid_metadata = (
        tmp_path / ".agents/skills" / CANONICAL_SKILLS[1] / "SKILL.md"
    )
    invalid_metadata.write_text(
        "---\nname: wrong-name\n---\n\n# Skill\n\n[TODO: finish]\n",
        encoding="utf-8",
    )

    wrapper = tmp_path / ".claude/skills" / CANONICAL_SKILLS[2] / "SKILL.md"
    wrapper.write_text(
        "---\n"
        f"name: {CANONICAL_SKILLS[2]}\n"
        "description: Deliberately drifted wrapper.\n"
        "---\n\n# Wrapper\n\nIndependent instructions.\n",
        encoding="utf-8",
    )

    assert {
        "claude_import",
        "invalid_skill_frontmatter",
        "invalid_skill_name",
        "invalid_skill_description",
        "skill_todo",
        "wrapper_drift",
    } <= _codes(tmp_path)


def test_repository_validator_rejects_missing_skill_and_invalid_adr(tmp_path: Path) -> None:
    _copy_governance_fixture(tmp_path)
    wrapper = tmp_path / ".claude/skills" / CANONICAL_SKILLS[0] / "SKILL.md"
    wrapper.unlink()
    adr = tmp_path / "docs/adr/9999-invalid.md"
    adr.write_text("# Invalid ADR\n\n- Status: Draft\n", encoding="utf-8")

    assert {"missing_skill", "invalid_adr"} <= _codes(tmp_path)


def test_repository_validator_rejects_invalid_yaml_contracts(tmp_path: Path) -> None:
    _copy_governance_fixture(tmp_path)
    objective = tmp_path / ".github/ISSUE_TEMPLATE/objective.yml"
    objective.write_text("name: [unterminated\n", encoding="utf-8")
    invalid_form = tmp_path / ".github/ISSUE_TEMPLATE/invalid.yml"
    invalid_form.write_text("name: Invalid\ndescription: No body\n", encoding="utf-8")
    workflow = tmp_path / ".github/workflows/ci.yml"
    workflow.write_text("name: CI\non: {}\njobs: []\n", encoding="utf-8")

    assert {"invalid_yaml", "invalid_issue_form", "invalid_workflow"} <= _codes(
        tmp_path
    )
