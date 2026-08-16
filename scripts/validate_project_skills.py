"""Validate canonical Codex Skills and thin Claude Code wrappers."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

try:
    import yaml
except ImportError:  # pragma: no cover - exercised through a monkeypatched test
    yaml = None


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.check_repository_governance import (  # noqa: E402
    CANONICAL_SKILLS,
    forbidden_headings,
)


FRONTMATTER_RE = re.compile(r"\A---\n(?P<metadata>.*?)\n---\n(?P<body>.*)\Z", re.DOTALL)
SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(frozen=True, slots=True)
class SkillViolation:
    code: str
    path: str
    detail: str


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _load_skill(
    path: Path,
    *,
    root: Path,
    expected_name: str,
) -> tuple[dict[str, object] | None, str, list[SkillViolation]]:
    relative = _relative(path, root)
    if not path.is_file():
        return None, "", [SkillViolation("missing_skill", relative, "SKILL.md is absent")]
    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(text)
    if match is None:
        return None, text, [
            SkillViolation("invalid_frontmatter", relative, "frontmatter is missing")
        ]
    try:
        metadata = yaml.safe_load(match.group("metadata"))
    except yaml.YAMLError as error:
        return None, match.group("body"), [
            SkillViolation("invalid_frontmatter", relative, str(error).splitlines()[0])
        ]
    violations: list[SkillViolation] = []
    if not isinstance(metadata, dict):
        return None, match.group("body"), [
            SkillViolation("invalid_frontmatter", relative, "metadata must be a mapping")
        ]
    unexpected = sorted(set(metadata) - {"name", "description"})
    if unexpected:
        violations.append(
            SkillViolation(
                "unexpected_metadata", relative, f"unexpected keys: {', '.join(unexpected)}"
            )
        )
    name = metadata.get("name")
    if (
        not isinstance(name, str)
        or name != expected_name
        or SKILL_NAME_RE.fullmatch(name) is None
        or len(name) > 64
    ):
        violations.append(
            SkillViolation("invalid_name", relative, f"expected {expected_name}")
        )
    description = metadata.get("description")
    if (
        not isinstance(description, str)
        or not description.strip()
        or len(description) > 1024
        or "<" in description
        or ">" in description
    ):
        violations.append(
            SkillViolation("invalid_description", relative, "description is invalid")
        )
    body = match.group("body")
    if "[TODO" in body:
        violations.append(SkillViolation("template_todo", relative, "TODO remains"))
    for heading in forbidden_headings(body):
        violations.append(
            SkillViolation("project_state_heading", relative, f"forbidden heading: {heading}")
        )
    return metadata, body, violations


def _validate_openai_yaml(
    path: Path,
    *,
    root: Path,
    skill_name: str,
) -> list[SkillViolation]:
    relative = _relative(path, root)
    if not path.is_file():
        return [SkillViolation("missing_openai_yaml", relative, "agents/openai.yaml is absent")]
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        return [SkillViolation("invalid_openai_yaml", relative, str(error).splitlines()[0])]
    if not isinstance(document, dict) or not isinstance(document.get("interface"), dict):
        return [
            SkillViolation("invalid_openai_yaml", relative, "interface mapping is required")
        ]
    interface = document["interface"]
    violations: list[SkillViolation] = []
    display_name = interface.get("display_name")
    short_description = interface.get("short_description")
    default_prompt = interface.get("default_prompt")
    if not isinstance(display_name, str) or not display_name.strip():
        violations.append(
            SkillViolation("invalid_openai_yaml", relative, "display_name is required")
        )
    if not isinstance(short_description, str) or not 25 <= len(short_description) <= 64:
        violations.append(
            SkillViolation(
                "invalid_openai_yaml",
                relative,
                "short_description must contain 25 to 64 characters",
            )
        )
    if not isinstance(default_prompt, str) or f"${skill_name}" not in default_prompt:
        violations.append(
            SkillViolation(
                "invalid_openai_yaml",
                relative,
                f"default_prompt must mention ${skill_name}",
            )
        )
    return violations


def evaluate_skills(root: Path = ROOT) -> tuple[SkillViolation, ...]:
    if yaml is None:
        return (
            SkillViolation(
                "yaml_dependency_missing",
                "pyproject.toml",
                "install the dev extra to validate project Skills",
            ),
        )
    violations: list[SkillViolation] = []
    for skill_name in CANONICAL_SKILLS:
        canonical_root = root / ".agents/skills" / skill_name
        canonical = canonical_root / "SKILL.md"
        wrapper = root / ".claude/skills" / skill_name / "SKILL.md"

        _, canonical_body, canonical_violations = _load_skill(
            canonical, root=root, expected_name=skill_name
        )
        violations.extend(canonical_violations)
        if canonical.is_file() and len(canonical.read_text(encoding="utf-8").splitlines()) > 500:
            violations.append(
                SkillViolation(
                    "skill_too_long", _relative(canonical, root), "SKILL.md exceeds 500 lines"
                )
            )
        if not canonical_body.strip():
            violations.append(
                SkillViolation("empty_skill", _relative(canonical, root), "body is empty")
            )
        violations.extend(
            _validate_openai_yaml(
                canonical_root / "agents/openai.yaml",
                root=root,
                skill_name=skill_name,
            )
        )

        _, wrapper_body, wrapper_violations = _load_skill(
            wrapper, root=root, expected_name=skill_name
        )
        violations.extend(wrapper_violations)
        expected_reference = f"../../../.agents/skills/{skill_name}/SKILL.md"
        if expected_reference not in wrapper_body:
            violations.append(
                SkillViolation(
                    "wrapper_drift",
                    _relative(wrapper, root),
                    f"must reference {expected_reference}",
                )
            )
        if len(wrapper_body.splitlines()) > 8 or "\n## " in wrapper_body:
            violations.append(
                SkillViolation(
                    "wrapper_not_thin",
                    _relative(wrapper, root),
                    "Claude wrapper must not duplicate the canonical workflow",
                )
            )

    return tuple(sorted(violations, key=lambda value: (value.path, value.code, value.detail)))


def main(argv: Sequence[str] | None = None) -> int:
    if argv:
        raise SystemExit("validate_project_skills.py takes no arguments")
    violations = evaluate_skills()
    print(
        json.dumps(
            {"ok": not violations, "violations": [asdict(value) for value in violations]},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if not violations else 2


if __name__ == "__main__":
    raise SystemExit(main())
