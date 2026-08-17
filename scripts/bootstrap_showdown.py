"""Materialize and verify the pinned Pokemon Showdown build outside the workspace."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from champions_sim.core.canonical import canonical_json  # noqa: E402
from champions_sim.showdown.manifest import load_showdown_manifest  # noqa: E402
from champions_sim.showdown.resolver import (  # noqa: E402
    default_showdown_root,
    resolve_showdown,
)


class BootstrapError(RuntimeError):
    pass


def _run(
    arguments: Sequence[str],
    *,
    cwd: Path | None = None,
    environment: dict[str, str] | None = None,
) -> None:
    try:
        subprocess.run(arguments, cwd=cwd, env=environment, check=True)
    except (OSError, subprocess.CalledProcessError) as error:
        raise BootstrapError(f"command failed: {arguments[0]}: {error}") from error


def _output(arguments: Sequence[str], *, cwd: Path | None = None) -> str:
    try:
        result = subprocess.run(
            arguments,
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
        )
    except (OSError, subprocess.CalledProcessError, UnicodeError) as error:
        raise BootstrapError(f"command failed: {arguments[0]}: {error}") from error
    return result.stdout.strip()


def _executable(explicit: Path | None, environment: str, command: str) -> Path | None:
    candidate = explicit
    if candidate is None and os.environ.get(environment):
        candidate = Path(os.environ[environment])
    if candidate is None:
        discovered = shutil.which(command)
        candidate = Path(discovered) if discovered else None
    if candidate is None:
        return None
    try:
        resolved = candidate.expanduser().resolve(strict=True)
    except OSError as error:
        raise BootstrapError(f"executable is unavailable: {candidate}") from error
    if not resolved.is_file():
        raise BootstrapError(f"executable is not a file: {resolved}")
    return resolved


def _ensure_external(destination: Path) -> Path:
    resolved = destination.expanduser().resolve(strict=False)
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError:
        return resolved
    raise BootstrapError("Pokemon Showdown must be materialized outside the repository workspace")


def _checkout(destination: Path, git: Path, repository_url: str, commit: str) -> None:
    created = False
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        _run(
            [
                str(git),
                "clone",
                "--filter=blob:none",
                "--no-checkout",
                repository_url,
                str(destination),
            ]
        )
        created = True
    if not (destination / ".git").is_dir():
        raise BootstrapError(f"destination is not a Git checkout: {destination}")
    if not created and _output(
        [str(git), "-C", str(destination), "status", "--porcelain", "--untracked-files=no"]
    ):
        raise BootstrapError("external Showdown checkout has tracked modifications")
    origin = _output([str(git), "-C", str(destination), "remote", "get-url", "origin"])
    if origin.rstrip("/") not in {repository_url.rstrip("/"), repository_url.removesuffix(".git").rstrip("/")}:
        raise BootstrapError(f"unexpected Showdown origin: {origin}")
    try:
        _run([str(git), "-C", str(destination), "cat-file", "-e", f"{commit}^{{commit}}"])
    except BootstrapError:
        _run([str(git), "-C", str(destination), "fetch", "--depth", "1", "origin", commit])
    _run([str(git), "-C", str(destination), "checkout", "--detach", commit])
    if _output(
        [str(git), "-C", str(destination), "status", "--porcelain", "--untracked-files=no"]
    ):
        raise BootstrapError("external Showdown checkout is not clean after checkout")


def _parser() -> argparse.ArgumentParser:
    manifest = load_showdown_manifest()
    parser = argparse.ArgumentParser(
        description="Clone, build, and verify the pinned Pokemon Showdown dependency outside Git"
    )
    parser.add_argument("--destination", type=Path, default=default_showdown_root(manifest))
    parser.add_argument("--node", type=Path)
    parser.add_argument("--npm", type=Path)
    parser.add_argument("--pnpm", type=Path)
    parser.add_argument("--verify-only", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    manifest = load_showdown_manifest()
    destination = _ensure_external(args.destination)
    node = _executable(args.node, "CHAMPIONS_NODE_EXECUTABLE", "node")
    if node is None:
        raise BootstrapError("Node.js was not found; use --node or CHAMPIONS_NODE_EXECUTABLE")

    if not args.verify_only:
        git = _executable(None, "CHAMPIONS_GIT_EXECUTABLE", "git")
        if git is None:
            raise BootstrapError("git was not found")
        _checkout(destination, git, manifest.repository_url, manifest.commit)
        npm = _executable(args.npm, "CHAMPIONS_NPM_EXECUTABLE", "npm")
        if npm is not None:
            install = [str(npm), *manifest.install_command[1:]]
        else:
            pnpm = _executable(args.pnpm, "CHAMPIONS_PNPM_EXECUTABLE", "pnpm")
            if pnpm is None:
                raise BootstrapError(
                    "npm was not found; pass --npm or pass --pnpm for the pinned npm@11.6.2 fallback"
                )
            install = [str(pnpm), "dlx", "npm@11.6.2", *manifest.install_command[1:]]
        build_environment = os.environ.copy()
        build_environment["PATH"] = os.pathsep.join(
            [str(node.parent), build_environment.get("PATH", "")]
        )
        _run(install, cwd=destination, environment=build_environment)
        _run(
            [str(node), *manifest.build_command[1:]],
            cwd=destination,
            environment=build_environment,
        )

    resolved = resolve_showdown(root=destination, node_executable=node)
    print(canonical_json({"ok": True, "identity": resolved.identity(), "root": str(resolved.root)}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BootstrapError as error:
        print(canonical_json({"ok": False, "error": str(error)}))
        raise SystemExit(2)
