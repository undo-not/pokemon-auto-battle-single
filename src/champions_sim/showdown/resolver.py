"""Resolve and verify an external, pinned Pokemon Showdown build."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .manifest import ShowdownManifest, load_showdown_manifest


_NODE_VERSION = re.compile(r"^v(?P<major>[0-9]+)(?:\.[0-9]+){2}$")


class ShowdownResolutionError(RuntimeError):
    """Raised when the external engine cannot satisfy its pinned identity."""


@dataclass(frozen=True, slots=True)
class ResolvedShowdown:
    root: Path
    node_executable: Path
    node_version: str
    head: str
    tree: str
    build_fingerprint: str
    manifest_sha256: str
    manifest: ShowdownManifest

    def identity(self) -> dict[str, object]:
        return {
            "artifact_id": self.manifest.artifact_id,
            "repository_url": self.manifest.repository_url,
            "commit": self.head,
            "tree": self.tree,
            "build_fingerprint_sha256": self.build_fingerprint,
            "manifest_sha256": self.manifest_sha256,
            "node_version": self.node_version,
            "license": self.manifest.license,
        }


def default_showdown_root(manifest: ShowdownManifest) -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "pokemon-auto-battle-single" / "dependencies" / "pokemon-showdown" / manifest.commit


def _run(
    arguments: list[str],
    *,
    cwd: Path | None = None,
    environment: dict[str, str] | None = None,
) -> str:
    try:
        result = subprocess.run(
            arguments,
            cwd=cwd,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError) as error:
        raise ShowdownResolutionError(f"command failed: {arguments[0]}: {error}") from error
    return result.stdout.strip()


def _run_bytes(
    arguments: list[str],
    *,
    environment: dict[str, str] | None = None,
) -> bytes:
    try:
        result = subprocess.run(
            arguments,
            env=environment,
            check=True,
            capture_output=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ShowdownResolutionError(
            f"command failed: {arguments[0]}: {error}"
        ) from error
    return result.stdout


def sanitized_node_environment() -> dict[str, str]:
    allowed = {
        "APPDATA",
        "COMSPEC",
        "HOME",
        "LANG",
        "LC_ALL",
        "LOCALAPPDATA",
        "PATH",
        "PATHEXT",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "TMPDIR",
        "USERPROFILE",
        "WINDIR",
    }
    return {key: value for key, value in os.environ.items() if key.upper() in allowed}


def sanitized_git_environment() -> dict[str, str]:
    environment = sanitized_node_environment()
    for key, value in os.environ.items():
        if key.upper() in {"HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"}:
            environment[key] = value
    environment.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    return environment


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while block := stream.read(1024 * 1024):
                digest.update(block)
    except OSError as error:
        raise ShowdownResolutionError(f"cannot hash {path}: {error}") from error
    return digest.hexdigest()


def _sha256_lf(path: Path) -> str:
    try:
        content = path.read_bytes()
    except OSError as error:
        raise ShowdownResolutionError(f"cannot hash {path}: {error}") from error
    return hashlib.sha256(content.replace(b"\r\n", b"\n")).hexdigest()


def _safe_file(root: Path, relative: str) -> Path:
    candidate = root.joinpath(*relative.split("/"))
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as error:
        raise ShowdownResolutionError(f"required Showdown file is unavailable: {relative}: {error}") from error
    try:
        resolved.relative_to(root.resolve(strict=True))
    except ValueError as error:
        raise ShowdownResolutionError(f"Showdown path escapes dependency root: {relative}") from error
    if candidate.is_symlink() or not resolved.is_file():
        raise ShowdownResolutionError(f"Showdown path must be a regular non-symlink file: {relative}")
    return resolved


def build_fingerprint(root: Path, manifest: ShowdownManifest) -> tuple[int, str]:
    files: dict[str, Path] = {}
    dependency_root = root.resolve(strict=True)

    def build_root(relative_root: str) -> Path:
        directory = root.joinpath(*relative_root.split("/"))
        try:
            resolved_directory = directory.resolve(strict=True)
            resolved_directory.relative_to(dependency_root)
        except (OSError, ValueError) as error:
            raise ShowdownResolutionError(
                f"invalid build root {relative_root}: {error}"
            ) from error
        if directory.is_symlink() or not resolved_directory.is_dir():
            raise ShowdownResolutionError(
                f"build root must be a non-symlink directory: {relative_root}"
            )
        return resolved_directory

    for relative_root in manifest.build.include_roots:
        resolved_directory = build_root(relative_root)
        for candidate in resolved_directory.rglob(f"*{manifest.build.extension}"):
            relative = candidate.relative_to(root).as_posix()
            files[relative] = _safe_file(root, relative)
    for relative_root in manifest.build.closed_roots:
        resolved_directory = build_root(relative_root)
        for candidate in resolved_directory.rglob("*"):
            relative = candidate.relative_to(root).as_posix()
            if candidate.is_symlink():
                raise ShowdownResolutionError(
                    f"closed build root contains a symlink: {relative}"
                )
            if candidate.is_file():
                files[relative] = _safe_file(root, relative)
    for relative in manifest.build.include_files:
        files[relative] = _safe_file(root, relative)

    digest = hashlib.sha256()
    for relative in sorted(files):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(_sha256(files[relative]).encode("ascii"))
        digest.update(b"\n")
    return len(files), digest.hexdigest()


def verify_forbidden_paths(root: Path, manifest: ShowdownManifest) -> None:
    for relative in manifest.forbidden_paths:
        candidate = root.joinpath(*relative.split("/"))
        if os.path.lexists(candidate):
            raise ShowdownResolutionError(
                f"forbidden Showdown customization path exists: {relative}"
            )


def _resolve_node(explicit: Path | None) -> Path:
    configured = explicit or (
        Path(os.environ["CHAMPIONS_NODE_EXECUTABLE"])
        if os.environ.get("CHAMPIONS_NODE_EXECUTABLE")
        else None
    )
    if configured is None:
        discovered = shutil.which("node")
        if discovered:
            configured = Path(discovered)
    if configured is None:
        raise ShowdownResolutionError(
            "Node.js was not found; set CHAMPIONS_NODE_EXECUTABLE or pass node_executable"
        )
    try:
        resolved = configured.expanduser().resolve(strict=True)
    except OSError as error:
        raise ShowdownResolutionError(f"Node.js executable is unavailable: {configured}") from error
    if not resolved.is_file():
        raise ShowdownResolutionError(f"Node.js executable is not a file: {resolved}")
    return resolved


def resolve_showdown(
    *,
    root: Path | None = None,
    node_executable: Path | None = None,
    manifest_path: Path | None = None,
) -> ResolvedShowdown:
    manifest = load_showdown_manifest(manifest_path)
    configured_root = root or (
        Path(os.environ["CHAMPIONS_SHOWDOWN_ROOT"])
        if os.environ.get("CHAMPIONS_SHOWDOWN_ROOT")
        else default_showdown_root(manifest)
    )
    try:
        resolved_root = configured_root.expanduser().resolve(strict=True)
    except OSError as error:
        raise ShowdownResolutionError(
            f"pinned Showdown checkout is unavailable: {configured_root}; run scripts/bootstrap_showdown.py"
        ) from error
    if not resolved_root.is_dir():
        raise ShowdownResolutionError(f"Showdown root is not a directory: {resolved_root}")

    git = shutil.which("git")
    if not git:
        raise ShowdownResolutionError("git is required to verify the external Showdown checkout")
    git_environment = sanitized_git_environment()
    head = _run(
        [git, "-C", str(resolved_root), "rev-parse", "HEAD"],
        environment=git_environment,
    )
    tree = _run(
        [git, "-C", str(resolved_root), "rev-parse", "HEAD^{tree}"],
        environment=git_environment,
    )
    origin = _run(
        [git, "-C", str(resolved_root), "remote", "get-url", "origin"],
        environment=git_environment,
    )
    normalized_origin = origin.rstrip("/").removesuffix(".git")
    normalized_expected = manifest.repository_url.rstrip("/").removesuffix(".git")
    if normalized_origin != normalized_expected:
        raise ShowdownResolutionError(
            f"Showdown origin mismatch: expected {manifest.repository_url}, got {origin}"
        )
    verify_forbidden_paths(resolved_root, manifest)
    if head != manifest.commit:
        raise ShowdownResolutionError(f"Showdown commit mismatch: expected {manifest.commit}, got {head}")
    if tree != manifest.tree:
        raise ShowdownResolutionError(f"Showdown tree mismatch: expected {manifest.tree}, got {tree}")

    for relative, expected in manifest.source_files:
        blob = _run_bytes(
            [
                git,
                "-C",
                str(resolved_root),
                "cat-file",
                "blob",
                f"{manifest.commit}:{relative}",
            ],
            environment=git_environment,
        )
        blob_hash = hashlib.sha256(blob).hexdigest()
        worktree_hash = _sha256_lf(_safe_file(resolved_root, relative))
        if blob_hash != expected or worktree_hash != expected:
            raise ShowdownResolutionError(
                "Showdown source hash mismatch for "
                f"{relative}: expected {expected}, blob={blob_hash}, "
                f"lf_worktree={worktree_hash}"
            )
    for dependency in manifest.runtime_dependencies:
        dependency_files = (
            (dependency.package_file, dependency.package_sha256),
            (dependency.license_file, dependency.license_sha256),
            *dependency.runtime_files,
        )
        for relative, expected in dependency_files:
            actual = _sha256(_safe_file(resolved_root, relative))
            if actual != expected:
                raise ShowdownResolutionError(
                    f"Showdown runtime dependency hash mismatch for {relative}: expected {expected}, got {actual}"
                )

    count, fingerprint = build_fingerprint(resolved_root, manifest)
    if count != manifest.build.file_count:
        raise ShowdownResolutionError(
            f"Showdown build file count mismatch: expected {manifest.build.file_count}, got {count}"
        )
    if fingerprint != manifest.build.fingerprint_sha256:
        raise ShowdownResolutionError(
            "Showdown build fingerprint mismatch: "
            f"expected {manifest.build.fingerprint_sha256}, got {fingerprint}"
        )

    node = _resolve_node(node_executable)
    node_version = _run(
        [str(node), "--version"], environment=sanitized_node_environment()
    )
    match = _NODE_VERSION.fullmatch(node_version)
    if match is None or int(match.group("major")) < manifest.minimum_node_major:
        raise ShowdownResolutionError(
            f"Node.js {manifest.minimum_node_major}+ is required, got {node_version}"
        )

    return ResolvedShowdown(
        root=resolved_root,
        node_executable=node,
        node_version=node_version,
        head=head,
        tree=tree,
        build_fingerprint=fingerprint,
        manifest_sha256=_sha256(manifest.path),
        manifest=manifest,
    )
