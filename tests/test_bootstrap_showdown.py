from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from scripts.bootstrap_showdown import _checkout


def _run(arguments: list[str], *, cwd: Path | None = None) -> str:
    result = subprocess.run(
        arguments,
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def test_checkout_materializes_a_fresh_no_checkout_clone(tmp_path: Path) -> None:
    git_command = shutil.which("git")
    if git_command is None:
        pytest.skip("git is unavailable")
    git = Path(git_command).resolve()
    source = tmp_path / "source"
    source.mkdir()
    _run([str(git), "init"], cwd=source)
    _run([str(git), "config", "user.email", "test@example.invalid"], cwd=source)
    _run([str(git), "config", "user.name", "Bootstrap Test"], cwd=source)
    (source / "tracked.txt").write_text("pinned\n", encoding="utf-8")
    _run([str(git), "add", "tracked.txt"], cwd=source)
    _run([str(git), "commit", "-m", "fixture"], cwd=source)
    commit = _run([str(git), "rev-parse", "HEAD"], cwd=source)

    destination = tmp_path / "checkout"
    _checkout(destination, git, str(source), commit)

    assert (destination / "tracked.txt").read_text(encoding="utf-8") == "pinned\n"
    assert _run(
        [str(git), "-C", str(destination), "status", "--porcelain", "--untracked-files=no"]
    ) == ""
