"""Read-only identity for the exact installed Pokémon Champions client build."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Callable

from champions_sim.core import canonical_hash, to_canonical_data


_ANDROID_PACKAGE_RE = re.compile(
    r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+$"
)
_APK_PATH_RE = re.compile(r"^/data/app/[A-Za-z0-9._~=/+\-]+\.apk$")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_MAX_PACKAGE_OUTPUT = 8 * 1024 * 1024
_MAX_PATH_OUTPUT = 64 * 1024
_MAX_HASH_OUTPUT = 4 * 1024
_MAX_APK_COUNT = 64


class AndroidClientIdentityError(ValueError):
    """Raised when installed-client identity cannot be proven exactly."""


@dataclass(frozen=True, slots=True)
class AndroidClientBuild:
    """Version metadata plus a fingerprint of every installed APK/split byte set."""

    version_code: int
    version_name: str
    apk_count: int
    apk_set_sha256: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.version_code, int)
            or isinstance(self.version_code, bool)
            or not 1 <= self.version_code <= 9_223_372_036_854_775_807
        ):
            raise AndroidClientIdentityError("client version_code must be positive")
        if (
            not isinstance(self.version_name, str)
            or not self.version_name
            or len(self.version_name) > 256
            or any(ord(character) < 32 or ord(character) == 127 for character in self.version_name)
        ):
            raise AndroidClientIdentityError("client version_name must be a safe string")
        if (
            not isinstance(self.apk_count, int)
            or isinstance(self.apk_count, bool)
            or not 1 <= self.apk_count <= _MAX_APK_COUNT
        ):
            raise AndroidClientIdentityError("client apk_count is invalid")
        if re.fullmatch(r"sha256:[0-9a-f]{64}", self.apk_set_sha256) is None:
            raise AndroidClientIdentityError("client apk_set_sha256 is invalid")

    def to_dict(self) -> dict[str, Any]:
        value = to_canonical_data(self)
        assert isinstance(value, dict)
        return value


def package_dump_service(target_package: str) -> str:
    _require_package(target_package)
    return f"exec:dumpsys package {target_package}"


def package_path_service(target_package: str) -> str:
    _require_package(target_package)
    return f"exec:cmd package path {target_package}"


def apk_sha256_service(path: str) -> str:
    _require_apk_path(path)
    return f"exec:sha256sum {path}"


def is_read_only_client_identity_service(service: str) -> bool:
    if not isinstance(service, str):
        return False
    for prefix in ("exec:dumpsys package ", "exec:cmd package path "):
        if service.startswith(prefix):
            value = service[len(prefix) :]
            return len(value) <= 240 and _ANDROID_PACKAGE_RE.fullmatch(value) is not None
    prefix = "exec:sha256sum "
    if service.startswith(prefix):
        value = service[len(prefix) :]
        return _valid_apk_path(value)
    return False


def observe_android_client_build(
    target_package: str,
    execute: Callable[[str, int], bytes],
) -> AndroidClientBuild:
    """Resolve installed version and APK-set bytes through allowlisted read-only calls."""

    _require_package(target_package)
    dump = _decode(
        execute(package_dump_service(target_package), _MAX_PACKAGE_OUTPUT),
        "package dump",
    )
    version_codes = set(
        re.findall(r"(?m)^\s*versionCode=([0-9]+)(?:\s|$)", dump)
    )
    version_names = {
        value.strip()
        for value in re.findall(r"(?m)^\s*versionName=([^\r\n]+)$", dump)
    }
    if len(version_codes) != 1 or len(version_names) != 1:
        raise AndroidClientIdentityError(
            "package dump does not contain one unambiguous client version"
        )

    path_output = _decode(
        execute(package_path_service(target_package), _MAX_PATH_OUTPUT),
        "package path",
    )
    apk_paths: list[str] = []
    for raw_line in path_output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if not line.startswith("package:"):
            raise AndroidClientIdentityError("package path output is malformed")
        path = line[len("package:") :]
        _require_apk_path(path)
        apk_paths.append(path)
    if (
        not apk_paths
        or len(apk_paths) > _MAX_APK_COUNT
        or len(apk_paths) != len(set(apk_paths))
    ):
        raise AndroidClientIdentityError("installed APK path set is invalid")

    entries: list[dict[str, str]] = []
    names: set[str] = set()
    for path in apk_paths:
        name = PurePosixPath(path).name
        if not name or name in names:
            raise AndroidClientIdentityError("installed APK names are not unique")
        names.add(name)
        output = _decode(
            execute(apk_sha256_service(path), _MAX_HASH_OUTPUT),
            "APK SHA-256",
        ).strip()
        parts = output.split(maxsplit=1)
        if len(parts) != 2 or _SHA256_RE.fullmatch(parts[0]) is None:
            raise AndroidClientIdentityError("APK SHA-256 output is malformed")
        reported_path = parts[1].lstrip("*")
        if reported_path != path:
            raise AndroidClientIdentityError("APK SHA-256 output names another path")
        entries.append(
            {"name": name, "sha256": "sha256:" + parts[0].lower()}
        )

    entries.sort(key=lambda value: value["name"])
    return AndroidClientBuild(
        version_code=int(next(iter(version_codes))),
        version_name=next(iter(version_names)),
        apk_count=len(entries),
        apk_set_sha256="sha256:" + canonical_hash({"apk_files": entries}),
    )


def _decode(payload: bytes, label: str) -> str:
    if not isinstance(payload, bytes):
        raise AndroidClientIdentityError(f"{label} payload must be bytes")
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise AndroidClientIdentityError(f"{label} payload is not UTF-8") from error


def _require_package(target_package: str) -> None:
    if (
        not isinstance(target_package, str)
        or len(target_package) > 240
        or _ANDROID_PACKAGE_RE.fullmatch(target_package) is None
    ):
        raise AndroidClientIdentityError("target package is invalid")


def _valid_apk_path(path: str) -> bool:
    return (
        isinstance(path, str)
        and len(path) <= 1024
        and "//" not in path
        and "/../" not in path
        and _APK_PATH_RE.fullmatch(path) is not None
    )


def _require_apk_path(path: str) -> None:
    if not _valid_apk_path(path):
        raise AndroidClientIdentityError("installed APK path is invalid")


__all__ = [
    "AndroidClientBuild",
    "AndroidClientIdentityError",
    "apk_sha256_service",
    "is_read_only_client_identity_service",
    "observe_android_client_build",
    "package_dump_service",
    "package_path_service",
]
