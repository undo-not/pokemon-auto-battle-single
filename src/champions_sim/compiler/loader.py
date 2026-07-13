"""Strict loaders for sealed intake and production Catalog compiler inputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from champions_sim.capabilities import ArtifactRecordRef, VerificationStatus
from champions_sim.intake.models import (
    ArtifactInventory,
    CatalogIntakeBundle,
    EntityRecordHash,
    EntityUnion,
    IntakeBlocker,
    MappingEvidence,
    MemberIntake,
    UsageDetailConflict,
    canonical_sha256,
)

from .bridge_models import (
    CatalogCompilerError,
    ProductionCatalogInput,
    ProductionCatalogRecord,
    ProductionMemberBinding,
)


def load_verified_intake_document(path: Path | str) -> CatalogIntakeBundle:
    """Load a CatalogIntake JSON document and verify its canonical bundle hash."""

    raw = _read_object(path, "CatalogIntake bundle")
    expected_keys = {
        "schema_version",
        "pipeline_version",
        "bundle_id",
        "profile_id",
        "regulation_id",
        "regulation_revision",
        "target_pool_sha256",
        "target_key_sha256",
        "target_member_count",
        "source_policy",
        "artifacts",
        "members",
        "entity_unions",
        "usage_detail_diagnostics",
        "blockers",
        "ready_for_capability_promotion",
        "summary",
        "bundle_hash",
    }
    _exact(raw, expected_keys, "CatalogIntake bundle")
    if raw["schema_version"] != "1.0.0" or raw["pipeline_version"] != "1.0.0":
        raise CatalogCompilerError("unsupported CatalogIntake version")
    supplied_hash = _string(raw["bundle_hash"], "bundle_hash")
    unsigned = {key: value for key, value in raw.items() if key != "bundle_hash"}
    if canonical_sha256(unsigned) != supplied_hash:
        raise CatalogCompilerError("CatalogIntake bundle hash mismatch")
    _restricted_policy(raw["source_policy"], include_usage_authority=True)

    artifacts = tuple(
        ArtifactInventory(
            artifact_id=_string(value["artifact_id"], "artifact_id"),
            root_kind=_string(value["root_kind"], "root_kind"),
            relative_path=_string(value["relative_path"], "relative_path"),
            sha256=_string(value["sha256"], "sha256"),
            byte_count=_integer(value["byte_count"], "byte_count"),
            record_count=_integer(value["record_count"], "record_count"),
            license_status=_string(value["license_status"], "license_status"),
            access_scope=_string(value["access_scope"], "access_scope"),
            redistribution=_string(value["redistribution"], "redistribution"),
        )
        for value in _object_list(raw["artifacts"], "artifacts")
    )
    members = []
    for value in _object_list(raw["members"], "members"):
        evidence_raw = _object(value["evidence"], "member evidence")
        evidence = MappingEvidence(
            source_artifact_id=_string(evidence_raw["source_artifact_id"], "source_artifact_id"),
            source_record_key=_string(evidence_raw["source_record_key"], "source_record_key"),
            matched_by=_string(evidence_raw["matched_by"], "matched_by"),
            normalized_official_name=_string(
                evidence_raw["normalized_official_name"], "normalized_official_name"
            ),
            candidate_pokemon_ids=tuple(
                _string(item, "candidate_pokemon_id")
                for item in _list(evidence_raw["candidate_pokemon_ids"], "candidate_pokemon_ids")
            ),
        )
        detail_hash = value["detail_record_sha256"]
        members.append(
            MemberIntake(
                target_key=_string(value["target_key"], "target_key"),
                national_dex_no=_integer(value["national_dex_no"], "national_dex_no"),
                form_code=_string(value["form_code"], "form_code"),
                variant_code=_string(value["variant_code"], "variant_code"),
                label=_string(value["label"], "label"),
                mapping_status=_string(value["mapping_status"], "mapping_status"),
                selected_pokemon_id=(
                    _string(value["selected_pokemon_id"], "selected_pokemon_id")
                    if value["selected_pokemon_id"] is not None
                    else None
                ),
                evidence=evidence,
                detail_status=_string(value["detail_status"], "detail_status"),
                detail_record_sha256=(
                    _string(detail_hash, "detail_record_sha256")
                    if detail_hash is not None
                    else None
                ),
            )
        )
    unions = []
    for value in _object_list(raw["entity_unions"], "entity_unions"):
        hashes = tuple(
            EntityRecordHash(
                _string(item["entity_id"], "entity_id"),
                _string(item["canonical_sha256"], "canonical_sha256"),
            )
            for item in _object_list(value["record_hashes"], "record_hashes")
        )
        entity_ids = tuple(_string(item, "entity_id") for item in _list(value["ids"], "ids"))
        if value["id_count"] != len(entity_ids) or value["hashed_record_count"] != len(hashes):
            raise CatalogCompilerError("entity union declared counts do not match arrays")
        unions.append(
            EntityUnion(
                entity_kind=_string(value["entity_kind"], "entity_kind"),
                selection_basis=_string(value["selection_basis"], "selection_basis"),
                ids=entity_ids,
                record_hashes=hashes,
                missing_record_ids=tuple(
                    _string(item, "missing_record_id")
                    for item in _list(value["missing_record_ids"], "missing_record_ids")
                ),
            )
        )
    diagnostics = _object(raw["usage_detail_diagnostics"], "usage_detail_diagnostics")
    conflicts = tuple(
        UsageDetailConflict(
            pokedb_pokemon_id=_string(value["pokedb_pokemon_id"], "pokedb_pokemon_id"),
            target_key=_string(value["target_key"], "target_key"),
            pokemon_name=_string(value["pokemon_name"], "pokemon_name"),
            selected_pokemon_id=_string(value["selected_pokemon_id"], "selected_pokemon_id"),
            diagnostic_pokemon_id=_string(value["diagnostic_pokemon_id"], "diagnostic_pokemon_id"),
            selected_matched_by=_string(value["selected_matched_by"], "selected_matched_by"),
            diagnostic_matched_by=_string(value["diagnostic_matched_by"], "diagnostic_matched_by"),
        )
        for value in _object_list(diagnostics["conflicts"], "conflicts")
    )
    if diagnostics["authoritative"] is not False or diagnostics["conflict_count"] != len(conflicts):
        raise CatalogCompilerError("usage-detail diagnostic contract mismatch")
    blockers = tuple(
        IntakeBlocker(
            _string(value["code"], "blocker code"),
            _string(value["scope"], "blocker scope"),
            _string(value["subject"], "blocker subject"),
            _string(value["detail"], "blocker detail"),
        )
        for value in _object_list(raw["blockers"], "blockers")
    )
    result = CatalogIntakeBundle(
        bundle_id=_string(raw["bundle_id"], "bundle_id"),
        profile_id=_string(raw["profile_id"], "profile_id"),
        regulation_id=_string(raw["regulation_id"], "regulation_id"),
        regulation_revision=_string(raw["regulation_revision"], "regulation_revision"),
        target_pool_sha256=_string(raw["target_pool_sha256"], "target_pool_sha256"),
        target_key_sha256=_string(raw["target_key_sha256"], "target_key_sha256"),
        target_member_count=_integer(raw["target_member_count"], "target_member_count"),
        artifacts=artifacts,
        members=tuple(members),
        entity_unions=tuple(unions),
        usage_detail_present=bool(diagnostics["present"]),
        usage_detail_conflicts=conflicts,
        blockers=blockers,
        summary=_object(raw["summary"], "summary"),
    )
    if result.bundle_hash != supplied_hash:
        raise CatalogCompilerError("CatalogIntake semantic reconstruction changed its hash")
    if raw["ready_for_capability_promotion"] != (not blockers):
        raise CatalogCompilerError("CatalogIntake readiness flag does not reflect blockers")
    return result


def load_production_catalog_input(path: Path | str) -> ProductionCatalogInput:
    raw = _read_object(path, "production Catalog input")
    required = {
        "schema_version",
        "compiler_version",
        "input_id",
        "intake_bundle_hash",
        "regulation_id",
        "regulation_revision",
        "target_pool_hash",
        "target_key_hash",
        "runtime_catalog_hash",
        "target_member_count",
        "source_policy",
        "members",
        "records",
        "evidence_refs",
        "source_manifest_ids",
        "blockers",
        "denominator_final",
        "catalog_emit_eligible",
        "input_hash",
    }
    _exact(raw, required, "production Catalog input")
    if raw["schema_version"] != "1.0.0" or raw["compiler_version"] != "1.0.0":
        raise CatalogCompilerError("unsupported production Catalog input version")
    supplied_hash = _string(raw["input_hash"], "input_hash")
    unsigned = {key: value for key, value in raw.items() if key != "input_hash"}
    if canonical_sha256(unsigned) != supplied_hash:
        raise CatalogCompilerError("production Catalog input hash mismatch")
    _restricted_policy(raw["source_policy"], include_usage_authority=False)
    evidence = tuple(
        _artifact_ref(value) for value in _object_list(raw["evidence_refs"], "evidence_refs")
    )
    members = tuple(
        ProductionMemberBinding(
            target_key=_string(value["target_key"], "target_key"),
            catalog_pokemon_id=(
                _string(value["catalog_pokemon_id"], "catalog_pokemon_id")
                if value["catalog_pokemon_id"] is not None
                else None
            ),
            candidate_pokemon_ids=tuple(
                _string(item, "candidate_pokemon_id")
                for item in _list(value["candidate_pokemon_ids"], "candidate_pokemon_ids")
            ),
            resolution_status=_string(value["resolution_status"], "resolution_status"),
            verification_status=VerificationStatus(value["verification_status"]),
            mapping_method=_string(value["mapping_method"], "mapping_method"),
            mapping_evidence_ref_ids=tuple(
                _string(item, "mapping_evidence_ref_id")
                for item in _list(value["mapping_evidence_ref_ids"], "mapping_evidence_ref_ids")
            ),
            detail_evidence_ref_id=(
                _string(value["detail_evidence_ref_id"], "detail_evidence_ref_id")
                if value["detail_evidence_ref_id"] is not None
                else None
            ),
        )
        for value in _object_list(raw["members"], "members")
    )
    evidence_by_id = {value.evidence_ref_id: value for value in evidence}
    records = []
    for value in _object_list(raw["records"], "records"):
        source_ref_raw = value["source_ref"]
        source_ref = _artifact_ref(source_ref_raw) if source_ref_raw is not None else None
        if source_ref is not None and evidence_by_id.get(source_ref.evidence_ref_id) != source_ref:
            raise CatalogCompilerError("record source_ref differs from evidence inventory")
        records.append(
            ProductionCatalogRecord(
                entity_kind=_string(value["entity_kind"], "entity_kind"),
                entity_id=_string(value["entity_id"], "entity_id"),
                record_status=_string(value["record_status"], "record_status"),
                verification_status=VerificationStatus(value["verification_status"]),
                source_ref=source_ref,
            )
        )
    result = ProductionCatalogInput(
        input_id=_string(raw["input_id"], "input_id"),
        intake_bundle_hash=_string(raw["intake_bundle_hash"], "intake_bundle_hash"),
        regulation_id=_string(raw["regulation_id"], "regulation_id"),
        regulation_revision=_string(raw["regulation_revision"], "regulation_revision"),
        target_pool_hash=_string(raw["target_pool_hash"], "target_pool_hash"),
        target_key_hash=_string(raw["target_key_hash"], "target_key_hash"),
        runtime_catalog_hash=_string(raw["runtime_catalog_hash"], "runtime_catalog_hash"),
        target_member_count=_integer(raw["target_member_count"], "target_member_count"),
        members=members,
        records=tuple(records),
        evidence_refs=evidence,
        source_manifest_ids=tuple(
            _string(item, "source_manifest_id")
            for item in _list(raw["source_manifest_ids"], "source_manifest_ids")
        ),
        blockers=tuple(_string(item, "blocker") for item in _list(raw["blockers"], "blockers")),
        denominator_final=bool(raw["denominator_final"]),
        catalog_emit_eligible=bool(raw["catalog_emit_eligible"]),
    )
    if result.input_hash != supplied_hash:
        raise CatalogCompilerError("production Catalog input semantic hash mismatch")
    return result


def _artifact_ref(raw: Any) -> ArtifactRecordRef:
    value = _object(raw, "artifact record reference")
    return ArtifactRecordRef(
        _string(value["evidence_ref_id"], "evidence_ref_id"),
        _string(value["source_manifest_id"], "source_manifest_id"),
        _string(value["artifact_id"], "artifact_id"),
        _string(value["json_pointer"], "json_pointer"),
        _string(value["record_sha256"], "record_sha256"),
    )


def _restricted_policy(raw: Any, *, include_usage_authority: bool) -> None:
    value = _object(raw, "source_policy")
    if (
        value.get("license_status") != "unverified"
        or value.get("access_scope") != "local_only"
        or value.get("redistribution") != "prohibited"
    ):
        raise CatalogCompilerError("source policy must remain unverified/local-only/prohibited")
    if include_usage_authority and value.get("usage_detail_authority") != "diagnostic_only":
        raise CatalogCompilerError("usage details must remain diagnostic-only")
    if not include_usage_authority and value.get("payload_policy") != "reference_only_no_raw_effect_text":
        raise CatalogCompilerError("production Catalog input payload policy mismatch")


def _read_object(path: Path | str, label: str) -> dict[str, Any]:
    source = Path(path)
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise CatalogCompilerError(f"{label} does not exist: {source}") from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CatalogCompilerError(f"invalid {label} JSON") from error
    return _object(raw, label)


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CatalogCompilerError(f"{label} must be an object")
    return value


def _object_list(value: Any, label: str) -> list[dict[str, Any]]:
    result = _list(value, label)
    if any(not isinstance(item, dict) for item in result):
        raise CatalogCompilerError(f"{label} entries must be objects")
    return result


def _list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise CatalogCompilerError(f"{label} must be an array")
    return value


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise CatalogCompilerError(f"{label} must be a non-empty string")
    return value


def _integer(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise CatalogCompilerError(f"{label} must be a non-negative integer")
    return value


def _exact(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise CatalogCompilerError(
            f"{label} fields mismatch; missing={sorted(expected - set(value))}; "
            f"extra={sorted(set(value) - expected)}"
        )
