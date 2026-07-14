from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from champions_sim.core import canonical_hash
from champions_sim.promotion.sources import (
    PromotionArtifactRoleV2,
    PromotionRecordReferenceV2,
    PromotionSourceError,
    PromotionSourceScopeV2,
    ResolvedArtifactV2,
    ResolvedPromotionSourceManifestV2,
    read_resolved_artifact,
    read_resolved_json_record,
    resolve_promotion_source_manifest_v2,
)
from scripts.validate_sim01_bundle import (
    BundleValidationError,
    validate_document_contract,
)


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_case(
    root: Path,
    *,
    source_kind: str = "test_fixture",
    authority: str = "test_authoritative",
    verification_status: str = "test_authoritative",
    local_research_allowed: bool = True,
    private_match_allowed: bool = True,
    training_allowed: bool = True,
    redistribution: str = "prohibited",
    license_identifier: str | None = "TEST-LICENSE-1",
    license_url: str | None = None,
) -> tuple[Path, Path, PromotionRecordReferenceV2]:
    artifact_root = root / "artifacts"
    artifact_root.mkdir(parents=True)
    manifest_id = "promotion-source-test-v2"
    license_record = {
        "schema_version": "2.0.0",
        "license_id": "license-test-v2",
        "source_manifest_id": manifest_id,
        "verification_status": verification_status,
        "license_identifier": license_identifier,
        "license_url": license_url,
        "use_policy": {
            "local_research_allowed": local_research_allowed,
            "private_match_allowed": private_match_allowed,
            "training_allowed": training_allowed,
            "redistribution": redistribution,
            "commercial_use": "prohibited",
        },
    }
    source_document = {
        "records": {
            "a/b": {
                "~key": {
                    "catalog_pokemon_id": "pokemon-0001",
                    "target_key": "dex:0001:form:00:variant:0",
                }
            }
        },
        "items": [{"value": 1}, {"value": 2}],
    }
    license_payload = _json_bytes(license_record)
    source_payload = _json_bytes(source_document)
    (artifact_root / "license.json").write_bytes(license_payload)
    (artifact_root / "records.json").write_bytes(source_payload)
    artifacts = [
        {
            "artifact_id": "license-record",
            "role": "license_record",
            "relative_path": "license.json",
            "media_type": "application/json",
            "byte_count": len(license_payload),
            "sha256": _digest(license_payload),
        },
        {
            "artifact_id": "source-records",
            "role": "source_data",
            "relative_path": "records.json",
            "media_type": "application/json",
            "byte_count": len(source_payload),
            "sha256": _digest(source_payload),
        },
    ]
    manifest = {
        "schema_version": "2.0.0",
        "manifest_id": manifest_id,
        "source_kind": source_kind,
        "authority": authority,
        "title": "Authoritative promotion source fixture",
        "publisher": "ChampionSim tests",
        "locator": {"kind": "logical", "value": "test/promotion-source-v2"},
        "retrieved_at": "2026-07-14T00:00:00+09:00",
        "license_artifact_id": "license-record",
        "artifacts": artifacts,
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_bytes(_json_bytes(manifest))
    record = source_document["records"]["a/b"]["~key"]
    reference = PromotionRecordReferenceV2(
        evidence_ref_id="mapping-record-1",
        source_manifest_id=manifest_id,
        artifact_id="source-records",
        json_pointer="/records/a~1b/~0key",
        record_sha256=canonical_hash(record),
    )
    return manifest_path, artifact_root, reference


def _replace_artifact_payload(
    manifest_path: Path,
    artifact_root: Path,
    artifact_id: str,
    payload: bytes,
) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifact = next(
        value for value in manifest["artifacts"] if value["artifact_id"] == artifact_id
    )
    (artifact_root / artifact["relative_path"]).write_bytes(payload)
    artifact["byte_count"] = len(payload)
    artifact["sha256"] = _digest(payload)
    manifest_path.write_bytes(_json_bytes(manifest))


def test_v2_source_and_license_documents_have_strict_public_schemas(
    tmp_path: Path,
) -> None:
    manifest_path, artifact_root, _ = _write_case(tmp_path)
    schema_root = Path(__file__).resolve().parents[1] / "data/schemas"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    license_document = json.loads(
        (artifact_root / "license.json").read_text(encoding="utf-8")
    )
    manifest_schema = json.loads(
        (
            schema_root / "sim02b-promotion-source-manifest-v2.schema.json"
        ).read_text(encoding="utf-8")
    )
    license_schema = json.loads(
        (schema_root / "sim02b-promotion-license-v2.schema.json").read_text(
            encoding="utf-8"
        )
    )

    validate_document_contract(
        manifest,
        manifest_schema,
        "SIM-02B source manifest",
        fail_on_unknown_keywords=True,
    )
    validate_document_contract(
        license_document,
        license_schema,
        "SIM-02B license",
        fail_on_unknown_keywords=True,
    )

    manifest["caller_verified"] = True
    license_document["use_policy"]["ranked_match_allowed"] = True
    with pytest.raises(BundleValidationError):
        validate_document_contract(
            manifest,
            manifest_schema,
            "forged SIM-02B source manifest",
            fail_on_unknown_keywords=True,
        )
    with pytest.raises(BundleValidationError):
        validate_document_contract(
            license_document,
            license_schema,
            "forged SIM-02B license",
            fail_on_unknown_keywords=True,
        )


def test_test_scope_resolution_is_deterministic_and_records_are_retrievable(
    tmp_path: Path,
) -> None:
    manifest_path, artifact_root, reference = _write_case(tmp_path)

    first = resolve_promotion_source_manifest_v2(
        manifest_path,
        artifact_root=artifact_root,
        record_references=(reference,),
    )
    second = resolve_promotion_source_manifest_v2(
        manifest_path,
        artifact_root=artifact_root,
        record_references=(reference,),
    )

    assert first == second
    assert first.scope is PromotionSourceScopeV2.TEST_AUTHORITATIVE
    assert first.manifest_hash == canonical_hash(
        json.loads(manifest_path.read_text(encoding="utf-8"))
    )
    assert first.resolution_hash == second.resolution_hash
    assert first.records[0].canonical_record_hash == reference.record_sha256
    source_artifact = first.artifact("source-records")
    assert read_resolved_artifact(artifact_root, source_artifact) == (
        artifact_root / "records.json"
    ).read_bytes()
    assert read_resolved_json_record(artifact_root, source_artifact, reference) == {
        "catalog_pokemon_id": "pokemon-0001",
        "target_key": "dex:0001:form:00:variant:0",
    }


def test_scope_is_derived_as_production_and_redistribution_may_remain_prohibited(
    tmp_path: Path,
) -> None:
    manifest_path, artifact_root, reference = _write_case(
        tmp_path,
        source_kind="official_catalog",
        authority="official",
        verification_status="verified",
        redistribution="prohibited",
        license_identifier="Official-Private-Research-Grant",
        license_url="https://example.test/license",
    )

    resolved = resolve_promotion_source_manifest_v2(
        manifest_path,
        artifact_root=artifact_root,
        record_references=(reference,),
    )

    assert resolved.scope is PromotionSourceScopeV2.PRODUCTION_CHAMPIONS
    assert resolved.license.redistribution == "prohibited"
    assert resolved.license.local_research_allowed
    assert resolved.license.private_match_allowed
    assert resolved.license.training_allowed


@pytest.mark.parametrize(
    "permission",
    ["local_research_allowed", "private_match_allowed", "training_allowed"],
)
def test_each_required_use_permission_fails_closed(
    tmp_path: Path,
    permission: str,
) -> None:
    kwargs = {
        "local_research_allowed": True,
        "private_match_allowed": True,
        "training_allowed": True,
    }
    kwargs[permission] = False
    manifest_path, artifact_root, _ = _write_case(tmp_path, **kwargs)

    with pytest.raises(PromotionSourceError, match="requires local research"):
        resolve_promotion_source_manifest_v2(
            manifest_path,
            artifact_root=artifact_root,
        )


@pytest.mark.parametrize(
    ("source_kind", "authority", "verification"),
    [
        ("test_fixture", "official", "test_authoritative"),
        ("test_fixture", "test_authoritative", "verified"),
        ("official_rule", "primary", "verified"),
        ("primary_reference", "official", "verified"),
        ("official_catalog", "official", "test_authoritative"),
    ],
)
def test_scope_cannot_be_selected_with_inconsistent_manifest_license_claims(
    tmp_path: Path,
    source_kind: str,
    authority: str,
    verification: str,
) -> None:
    manifest_path, artifact_root, _ = _write_case(
        tmp_path,
        source_kind=source_kind,
        authority=authority,
        verification_status=verification,
    )

    with pytest.raises(PromotionSourceError, match="authority/license combination"):
        resolve_promotion_source_manifest_v2(
            manifest_path,
            artifact_root=artifact_root,
        )


def test_production_license_requires_stable_identifier_or_url(tmp_path: Path) -> None:
    manifest_path, artifact_root, _ = _write_case(
        tmp_path,
        source_kind="official_rule",
        authority="official",
        verification_status="verified",
        license_identifier=None,
        license_url=None,
    )

    with pytest.raises(PromotionSourceError, match="identifier or URL"):
        resolve_promotion_source_manifest_v2(
            manifest_path,
            artifact_root=artifact_root,
        )


def test_artifact_and_license_bytes_are_rechecked_after_resolution(tmp_path: Path) -> None:
    manifest_path, artifact_root, reference = _write_case(tmp_path)
    resolved = resolve_promotion_source_manifest_v2(
        manifest_path,
        artifact_root=artifact_root,
        record_references=(reference,),
    )
    source_artifact = resolved.artifact("source-records")

    (artifact_root / "records.json").write_bytes(b"{}")
    with pytest.raises(PromotionSourceError, match="byte_count mismatch"):
        read_resolved_artifact(artifact_root, source_artifact)
    with pytest.raises(PromotionSourceError, match="byte_count mismatch"):
        resolve_promotion_source_manifest_v2(
            manifest_path,
            artifact_root=artifact_root,
            record_references=(reference,),
        )

    # Restore data, then mutate the separately declared license artifact.
    source_payload = _json_bytes(
        {
            "records": {
                "a/b": {
                    "~key": {
                        "catalog_pokemon_id": "pokemon-0001",
                        "target_key": "dex:0001:form:00:variant:0",
                    }
                }
            },
            "items": [{"value": 1}, {"value": 2}],
        }
    )
    (artifact_root / "records.json").write_bytes(source_payload)
    (artifact_root / "license.json").write_bytes(b"{}")
    with pytest.raises(PromotionSourceError, match="byte_count mismatch"):
        resolve_promotion_source_manifest_v2(
            manifest_path,
            artifact_root=artifact_root,
        )


def test_manifest_and_license_semantic_mutations_change_identity(tmp_path: Path) -> None:
    manifest_path, artifact_root, reference = _write_case(tmp_path)
    first = resolve_promotion_source_manifest_v2(
        manifest_path,
        artifact_root=artifact_root,
        record_references=(reference,),
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["title"] = "Mutated but structurally valid title"
    manifest_path.write_bytes(_json_bytes(manifest))
    title_mutated = resolve_promotion_source_manifest_v2(
        manifest_path,
        artifact_root=artifact_root,
        record_references=(reference,),
    )
    assert title_mutated.manifest_hash != first.manifest_hash
    assert title_mutated.resolution_hash != first.resolution_hash

    license_record = json.loads((artifact_root / "license.json").read_text(encoding="utf-8"))
    license_record["license_identifier"] = "TEST-LICENSE-2"
    _replace_artifact_payload(
        manifest_path,
        artifact_root,
        "license-record",
        _json_bytes(license_record),
    )
    license_mutated = resolve_promotion_source_manifest_v2(
        manifest_path,
        artifact_root=artifact_root,
        record_references=(reference,),
    )
    assert license_mutated.license.record_hash != title_mutated.license.record_hash
    assert license_mutated.manifest_hash != title_mutated.manifest_hash
    assert license_mutated.resolution_hash != title_mutated.resolution_hash


def test_duplicate_manifest_or_license_keys_are_rejected(tmp_path: Path) -> None:
    manifest_path, artifact_root, _ = _write_case(tmp_path)
    manifest_text = manifest_path.read_text(encoding="utf-8")
    manifest_path.write_text(
        manifest_text.replace(
            '"title":"Authoritative promotion source fixture"',
            '"title":"first","title":"second"',
        ),
        encoding="utf-8",
    )
    with pytest.raises(PromotionSourceError, match="duplicate JSON key: title"):
        resolve_promotion_source_manifest_v2(
            manifest_path,
            artifact_root=artifact_root,
        )

    manifest_path, artifact_root, _ = _write_case(tmp_path / "license-duplicate")
    license_text = (artifact_root / "license.json").read_text(encoding="utf-8")
    duplicate = license_text.replace(
        '"license_id":"license-test-v2"',
        '"license_id":"first","license_id":"second"',
    ).encode("utf-8")
    _replace_artifact_payload(
        manifest_path,
        artifact_root,
        "license-record",
        duplicate,
    )
    with pytest.raises(PromotionSourceError, match="duplicate JSON key: license_id"):
        resolve_promotion_source_manifest_v2(
            manifest_path,
            artifact_root=artifact_root,
        )


def test_overflow_number_outside_referenced_pointer_is_rejected(tmp_path: Path) -> None:
    manifest_path, artifact_root, reference = _write_case(tmp_path)
    source_text = (artifact_root / "records.json").read_text(encoding="utf-8")
    source_with_overflow = f'{source_text[:-1]},"overflow":1e999}}'.encode("utf-8")
    _replace_artifact_payload(
        manifest_path,
        artifact_root,
        "source-records",
        source_with_overflow,
    )

    with pytest.raises(PromotionSourceError, match="non-finite JSON number"):
        resolve_promotion_source_manifest_v2(
            manifest_path,
            artifact_root=artifact_root,
            record_references=(reference,),
        )


def test_duplicate_source_key_outside_referenced_pointer_is_rejected(
    tmp_path: Path,
) -> None:
    manifest_path, artifact_root, reference = _write_case(tmp_path)
    source_text = (artifact_root / "records.json").read_text(encoding="utf-8")
    source_with_duplicate = source_text.replace(
        '"items":',
        '"shadow":1,"shadow":2,"items":',
        1,
    ).encode("utf-8")
    _replace_artifact_payload(
        manifest_path,
        artifact_root,
        "source-records",
        source_with_duplicate,
    )

    with pytest.raises(PromotionSourceError, match="duplicate JSON key: shadow"):
        resolve_promotion_source_manifest_v2(
            manifest_path,
            artifact_root=artifact_root,
            record_references=(reference,),
        )


def test_manifest_artifact_digest_and_exact_shape_mutations_are_rejected(
    tmp_path: Path,
) -> None:
    manifest_path, artifact_root, _ = _write_case(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"][1]["sha256"] = "0" * 64
    manifest_path.write_bytes(_json_bytes(manifest))
    with pytest.raises(PromotionSourceError, match="artifact sha256 mismatch"):
        resolve_promotion_source_manifest_v2(
            manifest_path,
            artifact_root=artifact_root,
        )

    manifest_path, artifact_root, _ = _write_case(tmp_path / "extra")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["caller_verified"] = True
    manifest_path.write_bytes(_json_bytes(manifest))
    with pytest.raises(PromotionSourceError, match="extra=.*caller_verified"):
        resolve_promotion_source_manifest_v2(
            manifest_path,
            artifact_root=artifact_root,
        )


def test_artifact_paths_are_contained_and_normalized(tmp_path: Path) -> None:
    manifest_path, artifact_root, _ = _write_case(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"][1]["relative_path"] = "../outside.json"
    manifest_path.write_bytes(_json_bytes(manifest))

    with pytest.raises(PromotionSourceError, match="normalized relative POSIX"):
        resolve_promotion_source_manifest_v2(
            manifest_path,
            artifact_root=artifact_root,
        )

    with pytest.raises(PromotionSourceError, match="normalized relative POSIX"):
        ResolvedArtifactV2(
            source_manifest_id="manifest",
            artifact_id="artifact",
            role=PromotionArtifactRoleV2.SOURCE_DATA,
            relative_path="records//value.json",
            media_type="application/json",
            byte_count=0,
            sha256="0" * 64,
        )


def test_rfc6901_root_array_and_escaped_tokens_are_supported(tmp_path: Path) -> None:
    manifest_path, artifact_root, reference = _write_case(tmp_path)
    resolved = resolve_promotion_source_manifest_v2(
        manifest_path,
        artifact_root=artifact_root,
        record_references=(reference,),
    )
    artifact = resolved.artifact("source-records")

    array_reference = PromotionRecordReferenceV2(
        evidence_ref_id="array-value",
        source_manifest_id=resolved.manifest_id,
        artifact_id=artifact.artifact_id,
        json_pointer="/items/1",
        record_sha256=canonical_hash({"value": 2}),
    )
    assert read_resolved_json_record(
        artifact_root, artifact, array_reference
    ) == {"value": 2}

    document = json.loads((artifact_root / "records.json").read_text(encoding="utf-8"))
    root_reference = PromotionRecordReferenceV2(
        evidence_ref_id="root-value",
        source_manifest_id=resolved.manifest_id,
        artifact_id=artifact.artifact_id,
        json_pointer="",
        record_sha256=canonical_hash(document),
    )
    assert read_resolved_json_record(artifact_root, artifact, root_reference) == document


@pytest.mark.parametrize("pointer", ["not-absolute", "/records/~2bad"])
def test_invalid_json_pointer_syntax_is_rejected(pointer: str) -> None:
    with pytest.raises(PromotionSourceError, match="JSON pointer|json_pointer"):
        PromotionRecordReferenceV2(
            evidence_ref_id="bad-pointer",
            source_manifest_id="manifest",
            artifact_id="artifact",
            json_pointer=pointer,
            record_sha256="0" * 64,
        )


@pytest.mark.parametrize("pointer", ["/items/01", "/items/-", "/items/2", "/missing"])
def test_json_pointer_missing_or_noncanonical_array_paths_fail_closed(
    tmp_path: Path,
    pointer: str,
) -> None:
    manifest_path, artifact_root, reference = _write_case(tmp_path)
    resolved = resolve_promotion_source_manifest_v2(
        manifest_path,
        artifact_root=artifact_root,
        record_references=(reference,),
    )
    candidate = PromotionRecordReferenceV2(
        evidence_ref_id="bad-record",
        source_manifest_id=resolved.manifest_id,
        artifact_id="source-records",
        json_pointer=pointer,
        record_sha256="0" * 64,
    )
    with pytest.raises(PromotionSourceError, match="JSON pointer|array index"):
        read_resolved_json_record(
            artifact_root,
            resolved.artifact("source-records"),
            candidate,
        )


@pytest.mark.parametrize(
    "pointer",
    ["/items/²", "/items/" + ("9" * 5000)],
    ids=["non-ascii-index", "oversized-index"],
)
def test_json_pointer_extreme_array_indices_fail_closed(
    tmp_path: Path,
    pointer: str,
) -> None:
    manifest_path, artifact_root, reference = _write_case(tmp_path)
    resolved = resolve_promotion_source_manifest_v2(
        manifest_path,
        artifact_root=artifact_root,
        record_references=(reference,),
    )
    candidate = replace(
        reference,
        evidence_ref_id="extreme-index",
        json_pointer=pointer,
        record_sha256="0" * 64,
    )

    with pytest.raises(PromotionSourceError, match="array index"):
        read_resolved_json_record(
            artifact_root,
            resolved.artifact("source-records"),
            candidate,
        )


def test_record_hash_manifest_binding_and_role_are_enforced(tmp_path: Path) -> None:
    manifest_path, artifact_root, reference = _write_case(tmp_path)
    resolved = resolve_promotion_source_manifest_v2(
        manifest_path,
        artifact_root=artifact_root,
    )
    artifact = resolved.artifact("source-records")

    with pytest.raises(PromotionSourceError, match="record hash mismatch"):
        read_resolved_json_record(
            artifact_root,
            artifact,
            replace(reference, record_sha256="0" * 64),
        )
    with pytest.raises(PromotionSourceError, match="does not match"):
        read_resolved_json_record(
            artifact_root,
            artifact,
            replace(reference, source_manifest_id="another-manifest"),
        )
    with pytest.raises(PromotionSourceError, match="source_data"):
        read_resolved_json_record(
            artifact_root,
            resolved.artifact("license-record"),
            replace(reference, artifact_id="license-record"),
        )


def test_exact_types_and_derived_scope_are_rechecked(tmp_path: Path) -> None:
    manifest_path, artifact_root, reference = _write_case(tmp_path)
    with pytest.raises(PromotionSourceError, match="exact tuple"):
        resolve_promotion_source_manifest_v2(
            manifest_path,
            artifact_root=artifact_root,
            record_references=[reference],  # type: ignore[arg-type]
        )

    resolved = resolve_promotion_source_manifest_v2(
        manifest_path,
        artifact_root=artifact_root,
        record_references=(reference,),
    )
    with pytest.raises(PromotionSourceError, match="scope differs"):
        ResolvedPromotionSourceManifestV2(
            schema_version=resolved.schema_version,
            manifest_id=resolved.manifest_id,
            source_kind=resolved.source_kind,
            authority=resolved.authority,
            title=resolved.title,
            publisher=resolved.publisher,
            locator_kind=resolved.locator_kind,
            locator_value=resolved.locator_value,
            retrieved_at=resolved.retrieved_at,
            manifest_hash=resolved.manifest_hash,
            license=resolved.license,
            scope=PromotionSourceScopeV2.PRODUCTION_CHAMPIONS,
            artifacts=resolved.artifacts,
            records=resolved.records,
        )

    class StringSubclass(str):
        pass

    with pytest.raises(PromotionSourceError, match="redistribution must be an exact string"):
        replace(
            resolved.license,
            redistribution=StringSubclass("prohibited"),
        )
    with pytest.raises(PromotionSourceError, match="schema_version must be an exact string"):
        replace(resolved, schema_version=StringSubclass("2.0.0"))


def test_resolved_internal_artifact_bindings_are_rechecked(tmp_path: Path) -> None:
    manifest_path, artifact_root, reference = _write_case(tmp_path)
    resolved = resolve_promotion_source_manifest_v2(
        manifest_path,
        artifact_root=artifact_root,
        record_references=(reference,),
    )

    forged_license = replace(resolved.license, artifact_sha256="0" * 64)
    with pytest.raises(PromotionSourceError, match="license artifact sha256 binding"):
        replace(resolved, license=forged_license)

    forged_record = replace(
        resolved.records[0],
        reference=replace(reference, artifact_id="undeclared-artifact"),
    )
    with pytest.raises(PromotionSourceError, match="undeclared artifact"):
        replace(resolved, records=(forged_record,))


def test_training_permission_type_is_exact_not_truthy(tmp_path: Path) -> None:
    manifest_path, artifact_root, _ = _write_case(tmp_path)
    license_record = json.loads((artifact_root / "license.json").read_text(encoding="utf-8"))
    license_record["use_policy"]["training_allowed"] = 1
    _replace_artifact_payload(
        manifest_path,
        artifact_root,
        "license-record",
        _json_bytes(license_record),
    )

    with pytest.raises(PromotionSourceError, match="training_allowed must be an exact boolean"):
        resolve_promotion_source_manifest_v2(
            manifest_path,
            artifact_root=artifact_root,
        )
