from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from champions_sim.showdown.manifest import ManifestError, load_showdown_manifest
from champions_sim.showdown.resolver import (
    ShowdownResolutionError,
    _sha256_lf,
    build_fingerprint,
    sanitized_git_environment,
    sanitized_node_environment,
    verify_forbidden_paths,
)


def test_tracked_manifest_pins_source_build_license_and_format() -> None:
    manifest = load_showdown_manifest()

    assert manifest.commit == "8ff48edc09e4aed6011c966258a5f95899128443"
    assert manifest.tree == "880678686f3fda7a712080581ad5d6cc8ef5417b"
    assert manifest.license == "MIT"
    assert manifest.license_sha256 == "b2002a9fd52ba8db3783a05fbdebfb09c34fd09513b90f6b390a2c0dfbc93ed0"
    assert manifest.source_hash_algorithm == "sha256-git-blob-and-lf-worktree-v1"
    assert tuple(
        (dependency.name, dependency.version, dependency.license)
        for dependency in manifest.runtime_dependencies
    ) == (("ts-chacha20", "1.2.0", "MIT"),)
    assert dict(manifest.source_files)[manifest.license_file] == manifest.license_sha256
    assert manifest.schema_version == "2.0.0"
    assert manifest.build.file_count == 369
    assert manifest.build.extensions == (".js", ".json")
    assert manifest.build.closed_roots == ("dist/config",)
    assert manifest.default_format.id == "gen9championsbssregmb"
    assert manifest.default_format.purpose == "battle"
    assert manifest.default_format.mod == "champions"
    assert manifest.default_format.game_type == "singles"
    assert manifest.default_format.ruleset == ("Flat Rules", "VGC Timer")
    assert "speciesclause" in manifest.default_format.rule_table
    assert manifest.default_format.team_constraints.to_dict() == {
        "min_team_size": 6,
        "max_team_size": 6,
        "picked_team_size": 3,
        "max_move_count": 4,
        "min_source_gen": 9,
        "min_level": 1,
        "max_level": 100,
        "default_level": 100,
        "adjust_level": 50,
        "ev_limit": 66,
    }
    assert manifest.minimum_node_major >= 22
    assert "config/custom-formats.ts" in manifest.forbidden_paths
    generator = manifest.format_by_id("gen9championsrandombattle")
    assert generator is not None
    assert generator.purpose == "team_generation"
    assert generator.name == "[Gen 9 Champions] Random Battle"
    assert generator.mod == manifest.default_format.mod
    assert generator.team_constraints.picked_team_size is None
    assert generator.team_constraints.adjust_level is None
    assert {
        "dist/data/random-battles/champions/sets.json",
        "dist/data/random-battles/champions/doubles-sets.json",
    } <= set(manifest.build.include_files)

    schema = json.loads(
        (manifest.path.parents[1] / "schemas" / "pokemon-showdown-dependency.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(schema).validate(
        json.loads(manifest.path.read_text(encoding="utf-8"))
    )


def test_manifest_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    original = load_showdown_manifest().path.read_text(encoding="utf-8")
    hostile = original.replace(
        '"schema_version": "2.0.0",',
        '"schema_version": "2.0.0", "schema_version": "2.0.0",',
        1,
    )
    path = tmp_path / "manifest.json"
    path.write_text(hostile, encoding="utf-8")

    with pytest.raises(ManifestError, match="duplicate JSON key"):
        load_showdown_manifest(path)


def test_manifest_rejects_path_escape(tmp_path: Path) -> None:
    source = json.loads(load_showdown_manifest().path.read_text(encoding="utf-8"))
    source["source_files"]["../outside"] = "0" * 64
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(source), encoding="utf-8")

    with pytest.raises(ManifestError, match="normalized relative POSIX path"):
        load_showdown_manifest(path)


def test_manifest_rejects_unbound_bootstrap_commands(tmp_path: Path) -> None:
    source = json.loads(load_showdown_manifest().path.read_text(encoding="utf-8"))
    source["runtime"]["build_command"] = ["node", "unreviewed-script.js"]
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(source), encoding="utf-8")

    with pytest.raises(ManifestError, match="build_command is unsupported"):
        load_showdown_manifest(path)


def test_forbidden_showdown_custom_format_fails_closed(tmp_path: Path) -> None:
    manifest = load_showdown_manifest()
    custom_format = tmp_path / "dist" / "config" / "custom-formats.js"
    custom_format.parent.mkdir(parents=True)
    custom_format.write_text("module.exports = {};", encoding="utf-8")

    with pytest.raises(ShowdownResolutionError, match="forbidden Showdown customization"):
        verify_forbidden_paths(tmp_path, manifest)


def test_node_environment_drops_runtime_injection_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NODE_OPTIONS", "--require=hostile.js")
    monkeypatch.setenv("NODE_PATH", "hostile-node-modules")
    monkeypatch.setenv("NODE_REPL_EXTERNAL_MODULE", "hostile.js")
    monkeypatch.setenv("CHAMPIONS_SHOWDOWN_ROOT", "allowed-for-python-resolution-only")
    monkeypatch.setenv("GIT_DIR", "hostile-git-dir")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")

    environment = sanitized_node_environment()

    assert "NODE_OPTIONS" not in environment
    assert "NODE_PATH" not in environment
    assert "NODE_REPL_EXTERNAL_MODULE" not in environment
    assert "CHAMPIONS_SHOWDOWN_ROOT" not in environment

    git_environment = sanitized_git_environment()
    assert "GIT_DIR" not in git_environment
    assert "GIT_CONFIG_COUNT" not in git_environment
    assert git_environment["GIT_CONFIG_NOSYSTEM"] == "1"
    assert git_environment["GIT_CONFIG_GLOBAL"]


def test_closed_build_root_fingerprints_every_file(tmp_path: Path) -> None:
    manifest = load_showdown_manifest()
    config = tmp_path / "dist" / "config"
    config.mkdir(parents=True)
    (config / "formats.js").write_text("formats\n", encoding="utf-8")
    isolated = replace(
        manifest,
        build=replace(
            manifest.build,
            include_roots=(),
            closed_roots=("dist/config",),
            include_files=(),
        ),
    )
    baseline = build_fingerprint(tmp_path, isolated)

    (config / "custom-formats.mjs").write_text("custom\n", encoding="utf-8")
    changed = build_fingerprint(tmp_path, isolated)

    assert baseline[0] == 1
    assert changed[0] == 2
    assert changed[1] != baseline[1]


def test_source_hash_normalizes_platform_crlf_only(tmp_path: Path) -> None:
    lf = tmp_path / "lf.txt"
    crlf = tmp_path / "crlf.txt"
    lf.write_bytes(b"first\nsecond\n")
    crlf.write_bytes(b"first\r\nsecond\r\n")

    assert _sha256_lf(lf) == _sha256_lf(crlf)


def test_build_fingerprint_normalizes_platform_crlf(tmp_path: Path) -> None:
    manifest = load_showdown_manifest()
    included = tmp_path / "runtime.json"
    included.write_bytes(b'{"line":1}\n')
    isolated = replace(
        manifest,
        build=replace(
            manifest.build,
            include_roots=(),
            closed_roots=(),
            include_files=("runtime.json",),
        ),
    )
    baseline = build_fingerprint(tmp_path, isolated)

    included.write_bytes(b'{"line":1}\r\n')

    assert build_fingerprint(tmp_path, isolated) == baseline
