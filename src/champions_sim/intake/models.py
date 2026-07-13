"""Immutable contracts for the local-only catalog intake bundle."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping


CATALOG_INTAKE_SCHEMA_VERSION = "1.0.0"
CATALOG_INTAKE_PIPELINE_VERSION = "1.0.0"


class CatalogIntakeError(ValueError):
    """Raised when source intake cannot be made deterministic and fail-closed."""


def canonical_json(value: Any) -> str:
    """Canonical JSON for source records, including finite legacy JSON numbers."""

    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as error:
        raise CatalogIntakeError("value is not canonical JSON data") from error


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ArtifactExpectation:
    artifact_id: str
    root_kind: str
    relative_path: str
    sha256: str
    byte_count: int
    record_count: int


@dataclass(frozen=True, slots=True)
class ArtifactInventory:
    artifact_id: str
    root_kind: str
    relative_path: str
    sha256: str
    byte_count: int
    record_count: int
    license_status: str = "unverified"
    access_scope: str = "local_only"
    redistribution: str = "prohibited"

    def to_data(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "root_kind": self.root_kind,
            "relative_path": self.relative_path,
            "sha256": self.sha256,
            "byte_count": self.byte_count,
            "record_count": self.record_count,
            "license_status": self.license_status,
            "access_scope": self.access_scope,
            "redistribution": self.redistribution,
        }


@dataclass(frozen=True, slots=True)
class MappingEvidence:
    source_artifact_id: str
    source_record_key: str
    matched_by: str
    normalized_official_name: str
    candidate_pokemon_ids: tuple[str, ...]

    def to_data(self) -> dict[str, Any]:
        return {
            "source_artifact_id": self.source_artifact_id,
            "source_record_key": self.source_record_key,
            "matched_by": self.matched_by,
            "normalized_official_name": self.normalized_official_name,
            "candidate_pokemon_ids": list(self.candidate_pokemon_ids),
        }


@dataclass(frozen=True, slots=True)
class MemberIntake:
    target_key: str
    national_dex_no: int
    form_code: str
    variant_code: str
    label: str
    mapping_status: str
    selected_pokemon_id: str | None
    evidence: MappingEvidence
    detail_status: str
    detail_record_sha256: str | None

    def to_data(self) -> dict[str, Any]:
        return {
            "target_key": self.target_key,
            "national_dex_no": self.national_dex_no,
            "form_code": self.form_code,
            "variant_code": self.variant_code,
            "label": self.label,
            "mapping_status": self.mapping_status,
            "selected_pokemon_id": self.selected_pokemon_id,
            "evidence": self.evidence.to_data(),
            "detail_status": self.detail_status,
            "detail_record_sha256": self.detail_record_sha256,
        }


@dataclass(frozen=True, slots=True)
class EntityRecordHash:
    entity_id: str
    canonical_sha256: str

    def to_data(self) -> dict[str, str]:
        return {
            "entity_id": self.entity_id,
            "canonical_sha256": self.canonical_sha256,
        }


@dataclass(frozen=True, slots=True)
class EntityUnion:
    entity_kind: str
    selection_basis: str
    ids: tuple[str, ...]
    record_hashes: tuple[EntityRecordHash, ...]
    missing_record_ids: tuple[str, ...]

    def to_data(self) -> dict[str, Any]:
        return {
            "entity_kind": self.entity_kind,
            "selection_basis": self.selection_basis,
            "id_count": len(self.ids),
            "ids": list(self.ids),
            "hashed_record_count": len(self.record_hashes),
            "record_hashes": [value.to_data() for value in self.record_hashes],
            "missing_record_ids": list(self.missing_record_ids),
        }


@dataclass(frozen=True, slots=True)
class UsageDetailConflict:
    pokedb_pokemon_id: str
    target_key: str
    pokemon_name: str
    selected_pokemon_id: str
    diagnostic_pokemon_id: str
    selected_matched_by: str
    diagnostic_matched_by: str

    def to_data(self) -> dict[str, str]:
        return {
            "pokedb_pokemon_id": self.pokedb_pokemon_id,
            "target_key": self.target_key,
            "pokemon_name": self.pokemon_name,
            "selected_pokemon_id": self.selected_pokemon_id,
            "diagnostic_pokemon_id": self.diagnostic_pokemon_id,
            "selected_matched_by": self.selected_matched_by,
            "diagnostic_matched_by": self.diagnostic_matched_by,
        }


@dataclass(frozen=True, slots=True)
class IntakeBlocker:
    code: str
    scope: str
    subject: str
    detail: str

    def to_data(self) -> dict[str, str]:
        return {
            "code": self.code,
            "scope": self.scope,
            "subject": self.subject,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class CatalogIntakeBundle:
    bundle_id: str
    profile_id: str
    regulation_id: str
    regulation_revision: str
    target_pool_sha256: str
    target_key_sha256: str
    target_member_count: int
    artifacts: tuple[ArtifactInventory, ...]
    members: tuple[MemberIntake, ...]
    entity_unions: tuple[EntityUnion, ...]
    usage_detail_present: bool
    usage_detail_conflicts: tuple[UsageDetailConflict, ...]
    blockers: tuple[IntakeBlocker, ...]
    summary: Mapping[str, Any]

    def unsigned_data(self) -> dict[str, Any]:
        return {
            "schema_version": CATALOG_INTAKE_SCHEMA_VERSION,
            "pipeline_version": CATALOG_INTAKE_PIPELINE_VERSION,
            "bundle_id": self.bundle_id,
            "profile_id": self.profile_id,
            "regulation_id": self.regulation_id,
            "regulation_revision": self.regulation_revision,
            "target_pool_sha256": self.target_pool_sha256,
            "target_key_sha256": self.target_key_sha256,
            "target_member_count": self.target_member_count,
            "source_policy": {
                "license_status": "unverified",
                "access_scope": "local_only",
                "redistribution": "prohibited",
                "usage_detail_authority": "diagnostic_only",
            },
            "artifacts": [value.to_data() for value in self.artifacts],
            "members": [value.to_data() for value in self.members],
            "entity_unions": [value.to_data() for value in self.entity_unions],
            "usage_detail_diagnostics": {
                "present": self.usage_detail_present,
                "authoritative": False,
                "conflict_count": len(self.usage_detail_conflicts),
                "conflicts": [value.to_data() for value in self.usage_detail_conflicts],
            },
            "blockers": [value.to_data() for value in self.blockers],
            "ready_for_capability_promotion": not self.blockers,
            "summary": dict(self.summary),
        }

    @property
    def bundle_hash(self) -> str:
        return canonical_sha256(self.unsigned_data())

    def to_data(self) -> dict[str, Any]:
        return {**self.unsigned_data(), "bundle_hash": self.bundle_hash}

    def to_json(self) -> str:
        return canonical_json(self.to_data())
