from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from champions_sim.showdown.manifest import ManifestError, load_showdown_manifest


def test_tracked_manifest_pins_source_build_license_and_format() -> None:
    manifest = load_showdown_manifest()

    assert manifest.commit == "8ff48edc09e4aed6011c966258a5f95899128443"
    assert manifest.tree == "880678686f3fda7a712080581ad5d6cc8ef5417b"
    assert manifest.license == "MIT"
    assert tuple(
        (dependency.name, dependency.version, dependency.license)
        for dependency in manifest.runtime_dependencies
    ) == (("ts-chacha20", "1.2.0", "MIT"),)
    assert dict(manifest.source_files)[manifest.license_file] == manifest.license_sha256
    assert manifest.build.file_count == 336
    assert manifest.default_format.id == "gen9championsbssregmb"
    assert manifest.default_format.mod == "champions"

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
        '"schema_version": "1.0.0",',
        '"schema_version": "1.0.0", "schema_version": "1.0.0",',
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
