from __future__ import annotations

from pathlib import Path

import scripts.validate_project_skills as validator
from scripts.validate_project_skills import CANONICAL_SKILLS, ROOT, evaluate_skills


def _write_valid_skills(root: Path) -> None:
    for skill_name in CANONICAL_SKILLS:
        canonical = root / ".agents/skills" / skill_name
        wrapper = root / ".claude/skills" / skill_name
        (canonical / "agents").mkdir(parents=True)
        wrapper.mkdir(parents=True)
        (canonical / "SKILL.md").write_text(
            f"---\nname: {skill_name}\ndescription: Valid project workflow for testing.\n---\n\n# Skill\n\nDo the work.\n",
            encoding="utf-8",
        )
        (canonical / "agents/openai.yaml").write_text(
            "interface:\n"
            f'  display_name: "{skill_name}"\n'
            '  short_description: "A sufficiently long project skill summary"\n'
            f'  default_prompt: "Use ${skill_name} for this task."\n',
            encoding="utf-8",
        )
        (wrapper / "SKILL.md").write_text(
            f"---\nname: {skill_name}\ndescription: Valid Claude wrapper for testing.\n---\n\n"
            f"# Wrapper\n\nRead `../../../.agents/skills/{skill_name}/SKILL.md`.\n",
            encoding="utf-8",
        )


def test_project_skills_are_valid() -> None:
    assert evaluate_skills(ROOT) == ()


def test_skill_validator_rejects_wrapper_workflow_copy(tmp_path: Path) -> None:
    _write_valid_skills(tmp_path)

    target = tmp_path / ".claude/skills/execute-github-issue/SKILL.md"
    target.write_text(
        target.read_text(encoding="utf-8")
        + "\n## Duplicated workflow\n\n1. Maintain independent steps here.\n",
        encoding="utf-8",
    )

    violations = evaluate_skills(tmp_path)
    assert any(value.code == "wrapper_not_thin" for value in violations)


def test_skill_validator_rejects_invalid_skill_and_metadata(tmp_path: Path) -> None:
    _write_valid_skills(tmp_path)
    first = tmp_path / ".agents/skills" / CANONICAL_SKILLS[0] / "SKILL.md"
    first.write_text("# Missing frontmatter\n", encoding="utf-8")
    second = tmp_path / ".agents/skills" / CANONICAL_SKILLS[1] / "SKILL.md"
    second.write_text(
        "---\n"
        "name: wrong_name\n"
        "description: '<invalid>'\n"
        "extra: rejected\n"
        "---\n\n[TODO: complete]\n",
        encoding="utf-8",
    )

    codes = {value.code for value in evaluate_skills(tmp_path)}
    assert {
        "invalid_frontmatter",
        "invalid_name",
        "invalid_description",
        "unexpected_metadata",
        "template_todo",
    } <= codes


def test_skill_validator_rejects_openai_metadata_and_wrapper_drift(
    tmp_path: Path,
) -> None:
    _write_valid_skills(tmp_path)
    openai_yaml = (
        tmp_path
        / ".agents/skills"
        / CANONICAL_SKILLS[0]
        / "agents/openai.yaml"
    )
    openai_yaml.write_text("interface:\n  display_name: ''\n", encoding="utf-8")
    missing_openai_yaml = (
        tmp_path
        / ".agents/skills"
        / CANONICAL_SKILLS[1]
        / "agents/openai.yaml"
    )
    missing_openai_yaml.unlink()
    wrapper = tmp_path / ".claude/skills" / CANONICAL_SKILLS[2] / "SKILL.md"
    wrapper.write_text(
        f"---\nname: {CANONICAL_SKILLS[2]}\ndescription: Valid wrapper.\n---\n\n"
        "# Wrapper\n\nNo canonical reference.\n",
        encoding="utf-8",
    )

    codes = {value.code for value in evaluate_skills(tmp_path)}
    assert {"invalid_openai_yaml", "missing_openai_yaml", "wrapper_drift"} <= codes


def test_skill_validator_reports_missing_yaml_dependency(monkeypatch) -> None:
    monkeypatch.setattr(validator, "yaml", None)

    violations = validator.evaluate_skills(ROOT)

    assert tuple(value.code for value in violations) == ("yaml_dependency_missing",)
