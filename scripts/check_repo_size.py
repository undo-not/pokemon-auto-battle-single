"""Check candidate Git files against the provisional repository size policy."""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FILE_LIMIT = 2 * 1024 * 1024
DEFAULT_FIXTURE_LIMIT = 256 * 1024


@dataclass(frozen=True, slots=True)
class SizeViolation:
    path: str
    byte_size: int
    limit: int
    policy_id: str


def git_candidate_files(root: Path = ROOT) -> tuple[Path, ...]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    values = [value for value in result.stdout.decode("utf-8").split("\0") if value]
    return tuple(root / value for value in values)


def evaluate_paths(
    paths: Iterable[Path],
    *,
    root: Path = ROOT,
    file_limit: int = DEFAULT_FILE_LIMIT,
    fixture_limit: int = DEFAULT_FIXTURE_LIMIT,
) -> tuple[SizeViolation, ...]:
    violations: list[SizeViolation] = []
    for path in paths:
        if not path.is_file():
            continue
        relative = path.resolve().relative_to(root.resolve())
        is_fixture = any(part in {"fixtures", "golden"} for part in relative.parts)
        limit = fixture_limit if is_fixture else file_limit
        size = path.stat().st_size
        if size > limit:
            violations.append(
                SizeViolation(
                    path=relative.as_posix(),
                    byte_size=size,
                    limit=limit,
                    policy_id="PD-002" if is_fixture else "PD-001",
                )
            )
    return tuple(violations)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check provisional Git size limits")
    parser.add_argument("--file-limit", type=int, default=DEFAULT_FILE_LIMIT)
    parser.add_argument("--fixture-limit", type=int, default=DEFAULT_FIXTURE_LIMIT)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    paths = git_candidate_files()
    violations = evaluate_paths(
        paths,
        file_limit=args.file_limit,
        fixture_limit=args.fixture_limit,
    )
    print(
        json.dumps(
            {
                "ok": not violations,
                "candidate_file_count": len(paths),
                "file_limit": args.file_limit,
                "fixture_limit": args.fixture_limit,
                "violations": [asdict(value) for value in violations],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if not violations else 2


if __name__ == "__main__":
    raise SystemExit(main())
