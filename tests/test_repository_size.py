from __future__ import annotations

from pathlib import Path

from scripts.check_repo_size import ROOT, evaluate_paths, git_candidate_files


def test_current_git_candidates_satisfy_size_policy() -> None:
    assert evaluate_paths(git_candidate_files()) == ()


def test_fixture_limit_is_stricter_than_general_file_limit(tmp_path: Path) -> None:
    fixture = tmp_path / "data" / "fixtures" / "large.bin"
    source = tmp_path / "src" / "large.bin"
    fixture.parent.mkdir(parents=True)
    source.parent.mkdir(parents=True)
    fixture.write_bytes(b"x" * 11)
    source.write_bytes(b"x" * 11)

    violations = evaluate_paths(
        (fixture, source), root=tmp_path, file_limit=20, fixture_limit=10
    )

    assert tuple(value.path for value in violations) == ("data/fixtures/large.bin",)
    assert violations[0].policy_id == "ADR-0002:fixture-limit"


def test_repository_root_constant_points_to_this_checkout() -> None:
    assert (ROOT / "pyproject.toml").is_file()
