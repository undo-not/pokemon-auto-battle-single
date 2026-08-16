"""Validate the repository's issue-driven documentation and agent contract."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Sequence


ROOT = Path(__file__).resolve().parents[1]

REQUIRED_PATHS = (
    "README.md",
    "AGENTS.md",
    "CLAUDE.md",
    ".github/ISSUE_TEMPLATE/objective.yml",
    ".github/pull_request_template.md",
    ".github/workflows/ci.yml",
    "docs/specs/product-boundaries.md",
    "docs/specs/battle-engine.md",
    "docs/specs/regulation-and-catalog.md",
    "docs/specs/evidence-and-readiness.md",
    "docs/specs/ai-evaluation.md",
    "docs/policies/project-workflow.md",
    "docs/policies/artifacts-and-data.md",
    "docs/policies/evidence-and-claims.md",
    "docs/policies/agent-collaboration.md",
    "docs/adr/README.md",
)

CANONICAL_SKILLS = (
    "execute-github-issue",
    "validate-simulator-change",
    "update-regulation",
)

FORBIDDEN_BASENAMES = {
    "progress.md",
    "roadmap.md",
    "status.md",
    "spec-audit-log.md",
    "provisional-decisions.md",
    "traceability.md",
}

FORBIDDEN_NAME_FRAGMENTS = (
    "milestone",
    "progress",
    "roadmap",
    "validation-report",
    "phase-contract",
    "phase-status",
)

FORBIDDEN_HEADINGS = {
    "status",
    "current status",
    "project status",
    "progress",
    "roadmap",
    "next",
    "next step",
    "next steps",
    "next objective",
    "gate decision",
    "current gate decision",
    "現在の状態",
    "現在の判定",
    "進捗",
    "ロードマップ",
    "次",
    "次の作業",
    "次の目的",
    "次の大きな目的",
    "次のゲート",
    "未達と次目的",
}

FORBIDDEN_HEADING_PREFIXES = (
    "current gate",
    "next ",
    "milestone",
    "completion status",
    "remaining work",
    "project progress",
    "現在のゲート",
    "次の",
    "進捗 ",
    "未達 ",
    "残る作業",
)

FRONTMATTER_RE = re.compile(r"\A---\n(?P<body>.*?)\n---\n", re.DOTALL)
HEADING_RE = re.compile(r"^#{1,6}\s+(?P<title>.+?)\s*#*\s*$", re.MULTILINE)
NAME_RE = re.compile(r"^name:\s*(?P<value>[a-z0-9-]+)\s*$", re.MULTILINE)
DESCRIPTION_RE = re.compile(r"^description:\s*(?P<value>.+?)\s*$", re.MULTILINE)
MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\((?P<target>[^)]+\.md)(?:#[^)]+)?\)")


@dataclass(frozen=True, slots=True)
class GovernanceViolation:
    code: str
    path: str
    detail: str


def candidate_files(root: Path = ROOT) -> tuple[Path, ...]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    relative = (
        Path(value)
        for value in result.stdout.decode("utf-8").split("\0")
        if value
    )
    return tuple(root / value for value in relative if (root / value).is_file())


def forbidden_path_reason(relative: str) -> str | None:
    path = PurePosixPath(relative)
    lowered = path.name.lower()
    if path.parts and path.parts[0] == "specs":
        return "legacy specs/ tree is replaced by docs/specs/"
    if lowered in FORBIDDEN_BASENAMES:
        return f"{path.name} is a project-state document"
    if any(fragment in lowered for fragment in FORBIDDEN_NAME_FRAGMENTS):
        return f"{path.name} uses a prohibited project-state filename"
    if path.parts and path.parts[0] == "docs":
        if len(path.parts) < 3 or path.parts[1] not in {"specs", "policies", "adr"}:
            return "files under docs/ must live in specs/, policies/, or adr/"
        if lowered.endswith(".md") and len(path.parts) != 3:
            return "Markdown in docs/ must be a direct specification, policy, or ADR"
    return None


def forbidden_headings(text: str) -> tuple[str, ...]:
    headings: list[str] = []
    for match in HEADING_RE.finditer(text):
        title = " ".join(match.group("title").strip().lower().split())
        if title in FORBIDDEN_HEADINGS or any(
            title.startswith(prefix) for prefix in FORBIDDEN_HEADING_PREFIXES
        ):
            headings.append(match.group("title").strip())
    return tuple(headings)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _yaml_violations(root: Path, selected: Iterable[Path]) -> list[GovernanceViolation]:
    yaml_paths = tuple(
        path
        for path in selected
        if path.is_file()
        and path.suffix.lower() in {".yml", ".yaml"}
        and (
            path.resolve().is_relative_to((root / ".github").resolve())
            or path.name == "openai.yaml"
        )
    )
    if not yaml_paths:
        return []
    try:
        import yaml
    except ImportError:
        return [
            GovernanceViolation(
                "yaml_dependency_missing",
                "pyproject.toml",
                "install the dev extra to validate tracked YAML",
            )
        ]

    violations: list[GovernanceViolation] = []
    for path in yaml_paths:
        relative = path.resolve().relative_to(root.resolve()).as_posix()
        try:
            document = yaml.load(_read_text(path), Loader=yaml.BaseLoader)
        except yaml.YAMLError as error:
            violations.append(
                GovernanceViolation("invalid_yaml", relative, str(error).splitlines()[0])
            )
            continue
        if not isinstance(document, dict):
            violations.append(
                GovernanceViolation("invalid_yaml", relative, "top level must be a mapping")
            )
            continue
        if relative.startswith(".github/ISSUE_TEMPLATE/") and path.name != "config.yml":
            required = {"name", "description", "body"}
            missing = sorted(required - set(document))
            if missing or not isinstance(document.get("body"), list):
                detail = (
                    f"missing keys: {', '.join(missing)}"
                    if missing
                    else "body must be a sequence"
                )
                violations.append(GovernanceViolation("invalid_issue_form", relative, detail))
        if relative == ".github/workflows/ci.yml":
            required = {"name", "on", "jobs"}
            missing = sorted(required - set(document))
            if missing or not isinstance(document.get("jobs"), dict):
                detail = (
                    f"missing keys: {', '.join(missing)}"
                    if missing
                    else "jobs must be a mapping"
                )
                violations.append(GovernanceViolation("invalid_workflow", relative, detail))
    return violations


def _skill_violations(root: Path, skill_name: str) -> list[GovernanceViolation]:
    violations: list[GovernanceViolation] = []
    canonical_relative = f".agents/skills/{skill_name}/SKILL.md"
    wrapper_relative = f".claude/skills/{skill_name}/SKILL.md"
    canonical = root / canonical_relative
    wrapper = root / wrapper_relative
    for relative, path in ((canonical_relative, canonical), (wrapper_relative, wrapper)):
        if not path.is_file():
            violations.append(
                GovernanceViolation("missing_skill", relative, "SKILL.md is required")
            )
            continue
        text = _read_text(path)
        frontmatter = FRONTMATTER_RE.match(text)
        if frontmatter is None:
            violations.append(
                GovernanceViolation(
                    "invalid_skill_frontmatter", relative, "YAML frontmatter is missing"
                )
            )
            continue
        metadata = frontmatter.group("body")
        name_match = NAME_RE.search(metadata)
        description_match = DESCRIPTION_RE.search(metadata)
        if name_match is None or name_match.group("value") != skill_name:
            violations.append(
                GovernanceViolation(
                    "invalid_skill_name", relative, f"expected name: {skill_name}"
                )
            )
        if description_match is None or not description_match.group("value").strip():
            violations.append(
                GovernanceViolation(
                    "invalid_skill_description", relative, "description is required"
                )
            )
        if "[TODO" in text:
            violations.append(
                GovernanceViolation("skill_todo", relative, "template TODO remains")
            )
    if wrapper.is_file():
        expected = f"../../../.agents/skills/{skill_name}/SKILL.md"
        if expected not in _read_text(wrapper):
            violations.append(
                GovernanceViolation(
                    "wrapper_drift", wrapper_relative, f"must reference {expected}"
                )
            )
    return violations


def evaluate_repository(
    root: Path = ROOT,
    *,
    paths: Iterable[Path] | None = None,
) -> tuple[GovernanceViolation, ...]:
    violations: list[GovernanceViolation] = []
    selected = tuple(paths) if paths is not None else candidate_files(root)
    selected_relative = {
        path.resolve().relative_to(root.resolve()).as_posix(): path for path in selected
    }

    for required in REQUIRED_PATHS:
        if not (root / required).is_file():
            violations.append(
                GovernanceViolation("missing_required_path", required, "required file is absent")
            )

    for relative, path in sorted(selected_relative.items()):
        reason = forbidden_path_reason(relative)
        if reason is not None:
            violations.append(GovernanceViolation("forbidden_path", relative, reason))
        if path.suffix.lower() != ".md":
            continue
        text = _read_text(path)
        for heading in forbidden_headings(text):
            violations.append(
                GovernanceViolation(
                    "forbidden_heading", relative, f"project-state heading: {heading}"
                )
            )
        for match in MARKDOWN_LINK_RE.finditer(text):
            target = match.group("target")
            if "://" in target or target.startswith("#"):
                continue
            resolved = (path.parent / target).resolve()
            try:
                resolved.relative_to(root.resolve())
            except ValueError:
                continue
            if not resolved.is_file():
                violations.append(
                    GovernanceViolation(
                        "broken_markdown_link", relative, f"missing target: {target}"
                    )
                )

    violations.extend(_yaml_violations(root, selected_relative.values()))

    claude = root / "CLAUDE.md"
    if claude.is_file() and _read_text(claude).lstrip().splitlines()[0] != "@AGENTS.md":
        violations.append(
            GovernanceViolation(
                "claude_import", "CLAUDE.md", "first content line must be @AGENTS.md"
            )
        )

    for skill_name in CANONICAL_SKILLS:
        violations.extend(_skill_violations(root, skill_name))

    adr_root = root / "docs/adr"
    if adr_root.is_dir():
        for adr in sorted(adr_root.glob("[0-9][0-9][0-9][0-9]-*.md")):
            text = _read_text(adr)
            relative = adr.relative_to(root).as_posix()
            for required_section in ("## Context", "## Decision", "## Consequences"):
                if required_section not in text:
                    violations.append(
                        GovernanceViolation(
                            "invalid_adr", relative, f"missing {required_section}"
                        )
                    )
            if not re.search(
                r"^- Status: (Accepted|Rejected|Superseded by ADR-[0-9]{4})$",
                text,
                re.MULTILINE,
            ):
                violations.append(
                    GovernanceViolation(
                        "invalid_adr", relative, "invalid or missing ADR status"
                    )
                )

    return tuple(sorted(violations, key=lambda value: (value.path, value.code, value.detail)))


def _parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(description="Check repository governance layout")


def main(argv: Sequence[str] | None = None) -> int:
    _parser().parse_args(argv)
    violations = evaluate_repository()
    print(
        json.dumps(
            {
                "ok": not violations,
                "violations": [asdict(value) for value in violations],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if not violations else 2


if __name__ == "__main__":
    raise SystemExit(main())
