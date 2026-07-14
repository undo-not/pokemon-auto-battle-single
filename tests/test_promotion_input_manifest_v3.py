from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import shutil

import pytest

from champions_sim.core import canonical_hash, canonical_json
from champions_sim.promotion.input_manifest import (
    ProductionPromotionInputManifestError,
    ProductionPromotionInputManifestV3,
    build_production_promotion_input_manifest_v3,
    load_production_promotion_input_manifest_v3,
    rehydrate_production_promotion_request_v2,
)
from scripts.validate_sim01_bundle import (
    validate_document_contract,
    validate_schema_contract,
)

from _sim02b_fixture import build_test_authoritative_sim02b_fixture


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = (
    ROOT
    / "data"
    / "schemas"
    / "sim02c-production-promotion-input-manifest-v3.schema.json"
)
_INPUT_CONTENT_FIELDS = (
    "source_scope",
    "source_resolution_set_hash",
    "source_manifests",
    "artifact_bindings",
    "replay_artifact_bindings",
    "grounding_evidence_refs",
    "runtime_evidence",
)


def _manifest(tmp_path: Path):
    fixture = build_test_authoritative_sim02b_fixture(tmp_path / "artifact-root")
    return fixture, build_production_promotion_input_manifest_v3(fixture.request)


def _readdress(data: dict) -> dict:
    """Recompute only the portable self-identity after an adversarial edit."""

    data = deepcopy(data)
    content = {key: data[key] for key in _INPUT_CONTENT_FIELDS}
    data["input_content_hash"] = canonical_hash(content)
    unsigned = {key: value for key, value in data.items() if key != "manifest_id"}
    data["manifest_id"] = (
        "production-promotion-input-manifest-" + canonical_hash(unsigned)
    )
    return data


def test_round_trip_schema_file_load_and_exact_rehydration(tmp_path: Path) -> None:
    fixture, manifest = _manifest(tmp_path)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    validate_schema_contract(schema)
    validate_document_contract(manifest.to_data(), schema, "SIM-02C input manifest")
    payload = manifest.to_json()
    assert ProductionPromotionInputManifestV3.from_json(payload) == manifest
    assert ProductionPromotionInputManifestV3.from_json(payload.encode("utf-8")) == manifest
    assert manifest.rehydrate(artifact_root=fixture.artifact_root) == fixture.request
    assert (
        rehydrate_production_promotion_request_v2(
            manifest, artifact_root=fixture.artifact_root
        )
        == fixture.request
    )

    path = tmp_path / "portable-input.json"
    path.write_text(payload, encoding="utf-8")
    assert load_production_promotion_input_manifest_v3(path) == manifest


def test_serialized_form_has_no_root_secret_or_runtime_objects(tmp_path: Path) -> None:
    fixture, manifest = _manifest(tmp_path)
    payload = manifest.to_json()
    data = manifest.to_data()

    assert str(fixture.artifact_root) not in payload
    assert "artifact_root" not in payload
    assert "private_key" not in payload
    assert "credential" not in payload
    assert "secret" not in payload
    assert data["authorization_status"] == "not_authorization"
    assert data["runtime_evidence"]["evidence_status"] == (
        "references_only_not_embedded"
    )
    assert data["runtime_evidence"]["current_trust_context_required"] is True
    assert set(data["runtime_evidence"]["replay_scenario_ids"]) == {
        value.scenario_id for value in fixture.request.replay_artifacts
    }
    assert "initial_state" not in data["runtime_evidence"]
    assert "events" not in data["runtime_evidence"]


def test_manifest_rehydrates_under_a_different_external_root(tmp_path: Path) -> None:
    fixture, manifest = _manifest(tmp_path)
    relocated_root = tmp_path / "relocated-artifact-root"
    shutil.copytree(fixture.artifact_root, relocated_root)

    relocated = manifest.rehydrate(artifact_root=relocated_root)

    assert relocated.artifact_root == relocated_root.resolve()
    assert relocated.manifest_relative_paths == fixture.request.manifest_relative_paths
    assert relocated.artifacts == fixture.request.artifacts
    assert relocated.replay_artifacts == fixture.request.replay_artifacts
    assert relocated.grounding_evidence_refs == fixture.request.grounding_evidence_refs


@pytest.mark.parametrize(
    "relative_path",
    (
        "../outside.json",
        "manifests/../outside.json",
        "/absolute/manifest.json",
        "C:/absolute/manifest.json",
        "C:\\absolute\\manifest.json",
        "//server/share/manifest.json",
        "\\\\server\\share\\manifest.json",
        "manifests//core.json",
        "manifests/./core.json",
    ),
)
def test_relative_path_contract_rejects_escape_drive_unc_and_noncanonical_paths(
    tmp_path: Path,
    relative_path: str,
) -> None:
    _, manifest = _manifest(tmp_path)
    data = manifest.to_data()
    data["source_manifests"][0]["relative_path"] = relative_path

    with pytest.raises(
        ProductionPromotionInputManifestError, match="relative POSIX path"
    ):
        ProductionPromotionInputManifestV3.from_data(data)


@pytest.mark.parametrize(
    "mutation, message",
    (
        ("source_id", "source manifest IDs"),
        ("source_path", "source manifest paths"),
        ("source_path_case", "source manifest paths"),
        ("artifact_role", "artifact binding roles"),
        ("artifact_path_alias", "relative path"),
        ("replay_id", "Replay scenario IDs"),
        ("evidence_id", "grounding evidence reference IDs"),
    ),
)
def test_duplicate_ids_roles_and_paths_are_rejected(
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    _, manifest = _manifest(tmp_path)
    data = manifest.to_data()
    if mutation == "source_id":
        data["source_manifests"][1]["source_manifest_id"] = data[
            "source_manifests"
        ][0]["source_manifest_id"]
    elif mutation == "source_path":
        data["source_manifests"][1]["relative_path"] = data["source_manifests"][
            0
        ]["relative_path"]
    elif mutation == "source_path_case":
        data["source_manifests"][1]["relative_path"] = data["source_manifests"][
            0
        ]["relative_path"].upper()
    elif mutation == "artifact_role":
        data["artifact_bindings"][1]["binding_role"] = data["artifact_bindings"][
            0
        ]["binding_role"]
    elif mutation == "artifact_path_alias":
        data["artifact_bindings"][1]["artifact"]["relative_path"] = data[
            "artifact_bindings"
        ][0]["artifact"]["relative_path"]
    elif mutation == "replay_id":
        data["replay_artifact_bindings"][1]["scenario_id"] = data[
            "replay_artifact_bindings"
        ][0]["scenario_id"]
    elif mutation == "evidence_id":
        data["grounding_evidence_refs"][1]["evidence_ref_id"] = data[
            "grounding_evidence_refs"
        ][0]["evidence_ref_id"]
    else:  # pragma: no cover - guards the test table itself
        raise AssertionError(mutation)

    with pytest.raises(ProductionPromotionInputManifestError, match=message):
        ProductionPromotionInputManifestV3.from_data(data)


def test_parser_rejects_duplicate_unknown_and_noncanonical_json(tmp_path: Path) -> None:
    _, manifest = _manifest(tmp_path)

    with pytest.raises(ProductionPromotionInputManifestError, match="duplicate JSON key"):
        ProductionPromotionInputManifestV3.from_json(
            '{"schema_version":"3.0.0","schema_version":"3.0.0"}'
        )

    unknown = manifest.to_data()
    unknown["credential"] = "must-not-be-accepted"
    with pytest.raises(ProductionPromotionInputManifestError, match="unexpected"):
        ProductionPromotionInputManifestV3.from_json(canonical_json(unknown))

    noncanonical = json.dumps(
        manifest.to_data(), ensure_ascii=False, indent=2, sort_keys=True
    )
    with pytest.raises(ProductionPromotionInputManifestError, match="canonical"):
        ProductionPromotionInputManifestV3.from_json(noncanonical)


def test_content_derived_ids_reject_unaddressed_mutation(tmp_path: Path) -> None:
    _, manifest = _manifest(tmp_path)
    data = manifest.to_data()
    data["request_binding_hash"] = "0" * 64

    with pytest.raises(ProductionPromotionInputManifestError, match="manifest_id"):
        ProductionPromotionInputManifestV3.from_data(data)


def test_rehydration_rejects_source_manifest_and_artifact_byte_drift(
    tmp_path: Path,
) -> None:
    fixture, manifest = _manifest(tmp_path)
    source_path = fixture.artifact_root.joinpath(
        *Path(manifest.source_manifests[0].relative_path).parts
    )
    source_path.write_bytes(source_path.read_bytes() + b" ")

    with pytest.raises(ProductionPromotionInputManifestError, match="byte_count"):
        manifest.rehydrate(artifact_root=fixture.artifact_root)

    fixture, manifest = _manifest(tmp_path / "second")
    artifact_relative_path = manifest.artifact_bindings[0].artifact.relative_path
    artifact_path = fixture.artifact_root.joinpath(*Path(artifact_relative_path).parts)
    artifact_path.write_bytes(artifact_path.read_bytes() + b"\n")

    with pytest.raises(ProductionPromotionInputManifestError, match="do not resolve"):
        manifest.rehydrate(artifact_root=fixture.artifact_root)


def test_rehydration_rechecks_resolver_identity_not_only_self_consistent_json(
    tmp_path: Path,
) -> None:
    fixture, manifest = _manifest(tmp_path)
    data = manifest.to_data()
    data["artifact_bindings"][0]["artifact"]["sha256"] = "0" * 64
    forged_summary = ProductionPromotionInputManifestV3.from_data(_readdress(data))

    with pytest.raises(
        ProductionPromotionInputManifestError,
        match="content identity differs",
    ):
        forged_summary.rehydrate(artifact_root=fixture.artifact_root)


def test_rehydration_requires_external_existing_root(tmp_path: Path) -> None:
    _, manifest = _manifest(tmp_path)

    with pytest.raises(ProductionPromotionInputManifestError, match="externally as a Path"):
        manifest.rehydrate(artifact_root=str(tmp_path))  # type: ignore[arg-type]
    with pytest.raises(ProductionPromotionInputManifestError, match="does not resolve"):
        manifest.rehydrate(artifact_root=tmp_path / "missing")
