"""Strict loader for the pinned Pokemon Showdown dependency contract."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping


_HEX_40 = re.compile(r"^[0-9a-f]{40}$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,239}$")
_FORMAT_ID = re.compile(r"^[a-z0-9]{1,128}$")
_EXTENSION = re.compile(r"^\.[A-Za-z0-9]+$")
_PATH = re.compile(r"^[A-Za-z0-9._/-]+$")
_UPSTREAM = "https://github.com/smogon/pokemon-showdown.git"


class ManifestError(ValueError):
    """Raised when the tracked dependency manifest is not exact and safe."""


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ManifestError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_float(value: str) -> None:
    raise ManifestError(f"floating-point values are not allowed: {value}")


def _reject_constant(value: str) -> None:
    raise ManifestError(f"non-finite values are not allowed: {value}")


def _load_json(path: Path) -> Any:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_pairs,
            parse_float=_reject_float,
            parse_constant=_reject_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ManifestError(f"cannot read dependency manifest {path}: {error}") from error


def _mapping(value: Any, label: str, keys: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ManifestError(f"{label} must be an object")
    actual = set(value)
    if actual != keys:
        raise ManifestError(
            f"{label} fields differ: missing={sorted(keys - actual)}, "
            f"unknown={sorted(actual - keys)}"
        )
    return value


def _string(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 512
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in value)
    ):
        raise ManifestError(f"{label} must be a non-empty control-free string")
    return value


def _relative_path(value: Any, label: str) -> str:
    text = _string(value, label)
    path = PurePosixPath(text)
    if (
        path.is_absolute()
        or ".." in text
        or "\\" in text
        or text != path.as_posix()
        or _PATH.fullmatch(text) is None
    ):
        raise ManifestError(f"{label} must be a normalized relative POSIX path")
    return text


def _hex(value: Any, label: str, pattern: re.Pattern[str]) -> str:
    text = _string(value, label)
    if pattern.fullmatch(text) is None:
        raise ManifestError(f"{label} has an invalid digest")
    return text


@dataclass(frozen=True, slots=True)
class ShowdownTeamConstraints:
    min_team_size: int
    max_team_size: int
    picked_team_size: int
    max_move_count: int
    min_source_gen: int
    min_level: int
    max_level: int
    default_level: int
    adjust_level: int
    ev_limit: int

    def to_dict(self) -> dict[str, int]:
        return {
            field: getattr(self, field)
            for field in (
                "min_team_size",
                "max_team_size",
                "picked_team_size",
                "max_move_count",
                "min_source_gen",
                "min_level",
                "max_level",
                "default_level",
                "adjust_level",
                "ev_limit",
            )
        }


@dataclass(frozen=True, slots=True)
class ShowdownFormat:
    id: str
    name: str
    mod: str
    regulation: str
    game_type: str
    ruleset: tuple[str, ...]
    rule_table: tuple[str, ...]
    team_constraints: ShowdownTeamConstraints


@dataclass(frozen=True, slots=True)
class ShowdownBuild:
    algorithm: str
    include_roots: tuple[str, ...]
    include_files: tuple[str, ...]
    extension: str
    file_count: int
    fingerprint_sha256: str


@dataclass(frozen=True, slots=True)
class ShowdownRuntimeDependency:
    name: str
    version: str
    license: str
    package_file: str
    package_sha256: str
    license_file: str
    license_sha256: str
    runtime_files: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class ShowdownManifest:
    schema_version: str
    artifact_id: str
    repository_url: str
    commit: str
    tree: str
    license: str
    license_file: str
    license_sha256: str
    minimum_node_major: int
    install_command: tuple[str, ...]
    build_command: tuple[str, ...]
    runtime_dependencies: tuple[ShowdownRuntimeDependency, ...]
    forbidden_paths: tuple[str, ...]
    formats: tuple[ShowdownFormat, ...]
    source_files: tuple[tuple[str, str], ...]
    build: ShowdownBuild
    path: Path

    @property
    def default_format(self) -> ShowdownFormat:
        return self.formats[0]


def default_manifest_path() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "manifests" / "pokemon-showdown-champions.json"


def load_showdown_manifest(path: Path | None = None) -> ShowdownManifest:
    manifest_path = (path or default_manifest_path()).resolve()
    root = _mapping(
        _load_json(manifest_path),
        "manifest",
        {"schema_version", "artifact_id", "upstream", "runtime", "runtime_dependencies", "forbidden_paths", "formats", "source_files", "build"},
    )
    schema_version = _string(root["schema_version"], "schema_version")
    if schema_version != "1.0.0":
        raise ManifestError("unsupported dependency manifest schema_version")

    upstream = _mapping(
        root["upstream"],
        "upstream",
        {"repository_url", "commit", "tree", "license", "license_file", "license_sha256"},
    )
    runtime = _mapping(
        root["runtime"],
        "runtime",
        {"minimum_node_major", "install_command", "build_command"},
    )
    if (
        not isinstance(runtime["minimum_node_major"], int)
        or isinstance(runtime["minimum_node_major"], bool)
        or runtime["minimum_node_major"] < 22
    ):
        raise ManifestError("minimum_node_major must be an integer >= 22")

    def command(value: Any, label: str) -> tuple[str, ...]:
        if not isinstance(value, list) or not value:
            raise ManifestError(f"{label} must be a non-empty array")
        return tuple(_string(part, f"{label}[]") for part in value)

    forbidden_value = root["forbidden_paths"]
    if not isinstance(forbidden_value, list) or not forbidden_value:
        raise ManifestError("forbidden_paths must be a non-empty array")
    forbidden_paths = tuple(
        _relative_path(item, "forbidden_paths[]") for item in forbidden_value
    )
    if len(forbidden_paths) != len(set(forbidden_paths)):
        raise ManifestError("forbidden_paths must contain unique paths")

    dependencies_value = root["runtime_dependencies"]
    if not isinstance(dependencies_value, list) or not dependencies_value:
        raise ManifestError("runtime_dependencies must be a non-empty array")
    dependencies: list[ShowdownRuntimeDependency] = []
    dependency_names: set[str] = set()
    for index, value in enumerate(dependencies_value):
        item = _mapping(
            value,
            f"runtime_dependencies[{index}]",
            {"name", "version", "license", "package_file", "package_sha256", "license_file", "license_sha256", "runtime_files"},
        )
        name = _string(item["name"], f"runtime_dependencies[{index}].name")
        if _ID.fullmatch(name) is None:
            raise ManifestError(f"runtime_dependencies[{index}].name must be a stable ID")
        if name in dependency_names:
            raise ManifestError(f"duplicate runtime dependency: {name}")
        dependency_names.add(name)
        version = _string(item["version"], f"runtime_dependencies[{index}].version")
        if _VERSION.fullmatch(version) is None:
            raise ManifestError(f"runtime_dependencies[{index}].version must be semantic")
        runtime_files_value = item["runtime_files"]
        if not isinstance(runtime_files_value, dict) or not runtime_files_value:
            raise ManifestError(f"runtime_dependencies[{index}].runtime_files must be non-empty")
        dependencies.append(
            ShowdownRuntimeDependency(
                name=name,
                version=version,
                license=_string(item["license"], f"runtime_dependencies[{index}].license"),
                package_file=_relative_path(item["package_file"], f"runtime_dependencies[{index}].package_file"),
                package_sha256=_hex(item["package_sha256"], f"runtime_dependencies[{index}].package_sha256", _HEX_64),
                license_file=_relative_path(item["license_file"], f"runtime_dependencies[{index}].license_file"),
                license_sha256=_hex(item["license_sha256"], f"runtime_dependencies[{index}].license_sha256", _HEX_64),
                runtime_files=tuple(
                    sorted(
                        (
                            _relative_path(relative, f"runtime_dependencies[{index}].runtime_files key"),
                            _hex(digest, f"runtime_dependencies[{index}].runtime_files[{relative}]", _HEX_64),
                        )
                        for relative, digest in runtime_files_value.items()
                    )
                ),
            )
        )

    formats_value = root["formats"]
    if not isinstance(formats_value, list) or not formats_value:
        raise ManifestError("formats must be a non-empty array")
    formats: list[ShowdownFormat] = []
    format_ids: set[str] = set()
    for index, value in enumerate(formats_value):
        item = _mapping(
            value,
            f"formats[{index}]",
            {
                "id",
                "name",
                "mod",
                "regulation",
                "game_type",
                "ruleset",
                "rule_table",
                "team_constraints",
            },
        )
        format_id = _string(item["id"], f"formats[{index}].id")
        if _FORMAT_ID.fullmatch(format_id) is None:
            raise ManifestError(f"formats[{index}].id must be a lowercase Showdown ID")
        if format_id in format_ids:
            raise ManifestError(f"duplicate format id: {format_id}")
        format_ids.add(format_id)
        mod = _string(item["mod"], f"formats[{index}].mod")
        if _ID.fullmatch(mod) is None:
            raise ManifestError(f"formats[{index}].mod must be a stable ID")
        ruleset_value = item["ruleset"]
        if not isinstance(ruleset_value, list) or not ruleset_value:
            raise ManifestError(f"formats[{index}].ruleset must be a non-empty array")
        ruleset = tuple(
            _string(rule, f"formats[{index}].ruleset[]") for rule in ruleset_value
        )
        if len(ruleset) != len(set(ruleset)):
            raise ManifestError(f"formats[{index}].ruleset must contain unique entries")
        rule_table_value = item["rule_table"]
        if not isinstance(rule_table_value, list) or not rule_table_value:
            raise ManifestError(f"formats[{index}].rule_table must be a non-empty array")
        rule_table = tuple(
            _string(rule, f"formats[{index}].rule_table[]")
            for rule in rule_table_value
        )
        if rule_table != tuple(sorted(set(rule_table))):
            raise ManifestError(
                f"formats[{index}].rule_table must be sorted and unique"
            )
        constraint_fields = {
            "min_team_size",
            "max_team_size",
            "picked_team_size",
            "max_move_count",
            "min_source_gen",
            "min_level",
            "max_level",
            "default_level",
            "adjust_level",
            "ev_limit",
        }
        constraints_value = _mapping(
            item["team_constraints"],
            f"formats[{index}].team_constraints",
            constraint_fields,
        )
        constraints: dict[str, int] = {}
        for field in constraint_fields:
            raw = constraints_value[field]
            if not isinstance(raw, int) or isinstance(raw, bool) or raw < 1:
                raise ManifestError(
                    f"formats[{index}].team_constraints.{field} must be a positive integer"
                )
            constraints[field] = raw
        if not (
            constraints["picked_team_size"]
            <= constraints["min_team_size"]
            <= constraints["max_team_size"]
        ):
            raise ManifestError(f"formats[{index}] team sizes are inconsistent")
        if not (
            constraints["min_level"]
            <= constraints["adjust_level"]
            <= constraints["max_level"]
            and constraints["min_level"]
            <= constraints["default_level"]
            <= constraints["max_level"]
        ):
            raise ManifestError(f"formats[{index}] level constraints are inconsistent")
        game_type = _string(item["game_type"], f"formats[{index}].game_type")
        if game_type != "singles":
            raise ManifestError(f"formats[{index}].game_type must be singles")
        formats.append(
            ShowdownFormat(
                id=format_id,
                name=_string(item["name"], f"formats[{index}].name"),
                mod=mod,
                regulation=_string(item["regulation"], f"formats[{index}].regulation"),
                game_type=game_type,
                ruleset=ruleset,
                rule_table=rule_table,
                team_constraints=ShowdownTeamConstraints(**constraints),
            )
        )

    source_value = root["source_files"]
    if not isinstance(source_value, dict) or not source_value:
        raise ManifestError("source_files must be a non-empty object")
    source_files = tuple(
        sorted(
            (
                _relative_path(relative, "source_files key"),
                _hex(digest, f"source_files[{relative}]", _HEX_64),
            )
            for relative, digest in source_value.items()
        )
    )

    build_value = _mapping(
        root["build"],
        "build",
        {"algorithm", "include_roots", "include_files", "extension", "file_count", "fingerprint_sha256"},
    )

    def paths(value: Any, label: str) -> tuple[str, ...]:
        if not isinstance(value, list) or not value:
            raise ManifestError(f"{label} must be a non-empty array")
        converted = tuple(_relative_path(item, f"{label}[]") for item in value)
        if len(converted) != len(set(converted)):
            raise ManifestError(f"{label} must contain unique paths")
        return converted

    file_count = build_value["file_count"]
    if not isinstance(file_count, int) or isinstance(file_count, bool) or file_count < 1:
        raise ManifestError("build.file_count must be a positive integer")
    build = ShowdownBuild(
        algorithm=_string(build_value["algorithm"], "build.algorithm"),
        include_roots=paths(build_value["include_roots"], "build.include_roots"),
        include_files=paths(build_value["include_files"], "build.include_files"),
        extension=_string(build_value["extension"], "build.extension"),
        file_count=file_count,
        fingerprint_sha256=_hex(build_value["fingerprint_sha256"], "build.fingerprint_sha256", _HEX_64),
    )
    if build.algorithm != "sha256-path-nul-sha256-lf-v1":
        raise ManifestError(f"unsupported build fingerprint algorithm: {build.algorithm}")
    if _EXTENSION.fullmatch(build.extension) is None:
        raise ManifestError("build.extension must be a simple file extension")
    required_runtime_files = {
        relative
        for dependency in dependencies
        for relative in (
            dependency.package_file,
            dependency.license_file,
            *(path for path, _digest in dependency.runtime_files),
        )
    }
    if not required_runtime_files <= set(build.include_files):
        raise ManifestError(
            "every runtime dependency identity file must be included in the build fingerprint"
        )

    license_file = _relative_path(upstream["license_file"], "upstream.license_file")
    license_sha256 = _hex(upstream["license_sha256"], "upstream.license_sha256", _HEX_64)
    source_map = dict(source_files)
    if source_map.get(license_file) != license_sha256:
        raise ManifestError("license hash must match the source_files entry")

    repository_url = _string(upstream["repository_url"], "upstream.repository_url")
    if repository_url != _UPSTREAM:
        raise ManifestError(f"upstream.repository_url must be {_UPSTREAM}")
    license_name = _string(upstream["license"], "upstream.license")
    if license_name != "MIT":
        raise ManifestError("upstream.license must be MIT")
    artifact_id = _string(root["artifact_id"], "artifact_id")
    if _ID.fullmatch(artifact_id) is None:
        raise ManifestError("artifact_id must be a stable ID")
    install_command = command(runtime["install_command"], "runtime.install_command")
    build_command = command(runtime["build_command"], "runtime.build_command")
    if install_command != ("npm", "ci", "--omit=optional"):
        raise ManifestError("runtime.install_command is unsupported")
    if build_command != ("node", "build"):
        raise ManifestError("runtime.build_command is unsupported")

    return ShowdownManifest(
        schema_version=schema_version,
        artifact_id=artifact_id,
        repository_url=repository_url,
        commit=_hex(upstream["commit"], "upstream.commit", _HEX_40),
        tree=_hex(upstream["tree"], "upstream.tree", _HEX_40),
        license=license_name,
        license_file=license_file,
        license_sha256=license_sha256,
        minimum_node_major=runtime["minimum_node_major"],
        install_command=install_command,
        build_command=build_command,
        runtime_dependencies=tuple(dependencies),
        forbidden_paths=forbidden_paths,
        formats=tuple(formats),
        source_files=source_files,
        build=build,
        path=manifest_path,
    )
