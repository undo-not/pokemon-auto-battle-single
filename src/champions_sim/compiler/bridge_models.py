"""Immutable source-bound Catalog bridge contracts."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from champions_sim.capabilities import ArtifactRecordRef, MappingEvidenceSet, VerificationStatus
from champions_sim.intake.models import canonical_json, canonical_sha256


PRODUCTION_CATALOG_INPUT_SCHEMA_VERSION = "1.0.0"
CATALOG_BRIDGE_VERSION = "1.0.0"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class CatalogCompilerError(ValueError):
    """Raised when a source-bound compiler invariant cannot be proven."""


@dataclass(frozen=True, slots=True)
class ProductionMemberBinding:
    target_key: str
    catalog_pokemon_id: str | None
    candidate_pokemon_ids: tuple[str, ...]
    resolution_status: str
    verification_status: VerificationStatus
    mapping_method: str
    mapping_evidence_ref_ids: tuple[str, ...]
    detail_evidence_ref_id: str | None

    def __post_init__(self) -> None:
        if self.resolution_status not in {"resolved", "unresolved", "conflict"}:
            raise CatalogCompilerError("unsupported member resolution_status")
        if self.resolution_status != "resolved" and self.catalog_pokemon_id is not None:
            raise CatalogCompilerError("unresolved member cannot select a Catalog ID")
        if self.resolution_status == "resolved" and self.catalog_pokemon_id is None:
            raise CatalogCompilerError("resolved member requires a Catalog ID")
        if self.verification_status is VerificationStatus.VERIFIED:
            raise CatalogCompilerError(
                "intake bridge cannot promote implicit/name evidence to verified"
            )

    def to_data(self) -> dict[str, Any]:
        return {
            "target_key": self.target_key,
            "catalog_pokemon_id": self.catalog_pokemon_id,
            "candidate_pokemon_ids": list(self.candidate_pokemon_ids),
            "resolution_status": self.resolution_status,
            "verification_status": self.verification_status.value,
            "mapping_method": self.mapping_method,
            "mapping_evidence_ref_ids": list(self.mapping_evidence_ref_ids),
            "detail_evidence_ref_id": self.detail_evidence_ref_id,
        }


@dataclass(frozen=True, slots=True)
class ProductionCatalogRecord:
    entity_kind: str
    entity_id: str
    record_status: str
    verification_status: VerificationStatus
    source_ref: ArtifactRecordRef | None

    def __post_init__(self) -> None:
        if self.entity_kind not in {
            "pokemon", "mega_pokemon", "move", "ability", "item", "type"
        }:
            raise CatalogCompilerError("unsupported production Catalog entity_kind")
        if self.record_status not in {"source_bound", "missing"}:
            raise CatalogCompilerError("unsupported production Catalog record_status")
        if (self.record_status == "source_bound") != (self.source_ref is not None):
            raise CatalogCompilerError("record status/source reference mismatch")
        if self.verification_status is VerificationStatus.VERIFIED:
            raise CatalogCompilerError(
                "legacy intake record cannot be marked verified by the bridge"
            )

    def to_data(self) -> dict[str, Any]:
        return {
            "entity_kind": self.entity_kind,
            "entity_id": self.entity_id,
            "record_status": self.record_status,
            "verification_status": self.verification_status.value,
            "source_ref": artifact_ref_data(self.source_ref),
        }


@dataclass(frozen=True, slots=True)
class ProductionCatalogInput:
    input_id: str
    intake_bundle_hash: str
    regulation_id: str
    regulation_revision: str
    target_pool_hash: str
    target_key_hash: str
    runtime_catalog_hash: str
    target_member_count: int
    members: tuple[ProductionMemberBinding, ...]
    records: tuple[ProductionCatalogRecord, ...]
    evidence_refs: tuple[ArtifactRecordRef, ...]
    source_manifest_ids: tuple[str, ...]
    blockers: tuple[str, ...]
    denominator_final: bool
    catalog_emit_eligible: bool

    def __post_init__(self) -> None:
        for value, label in (
            (self.intake_bundle_hash, "intake_bundle_hash"),
            (self.target_pool_hash, "target_pool_hash"),
            (self.target_key_hash, "target_key_hash"),
            (self.runtime_catalog_hash, "runtime_catalog_hash"),
        ):
            if _SHA256.fullmatch(value) is None:
                raise CatalogCompilerError(f"{label} must be a lowercase SHA-256")
        if self.target_member_count <= 0 or len(self.members) != self.target_member_count:
            raise CatalogCompilerError("production member count mismatch")
        target_keys = tuple(value.target_key for value in self.members)
        if len(target_keys) != len(set(target_keys)):
            raise CatalogCompilerError("production target keys must be unique")
        record_keys = tuple((value.entity_kind, value.entity_id) for value in self.records)
        if len(record_keys) != len(set(record_keys)):
            raise CatalogCompilerError("production Catalog records must be unique")
        evidence_ids = tuple(value.evidence_ref_id for value in self.evidence_refs)
        if len(evidence_ids) != len(set(evidence_ids)):
            raise CatalogCompilerError("production evidence references must be unique")
        available = set(evidence_ids)
        for member in self.members:
            if not set(member.mapping_evidence_ref_ids) <= available:
                raise CatalogCompilerError("member references unknown mapping evidence")
            if member.detail_evidence_ref_id is not None and member.detail_evidence_ref_id not in available:
                raise CatalogCompilerError("member references unknown detail evidence")
        for record in self.records:
            if record.source_ref is not None and record.source_ref.evidence_ref_id not in available:
                raise CatalogCompilerError("Catalog record references unknown evidence")
        if self.denominator_final or self.catalog_emit_eligible:
            raise CatalogCompilerError(
                "intake-only bridge cannot finalize denominator or emit a production Catalog"
            )
        if not self.blockers:
            raise CatalogCompilerError("non-final Catalog input requires blockers")

    def unsigned_data(self) -> dict[str, Any]:
        return {
            "schema_version": PRODUCTION_CATALOG_INPUT_SCHEMA_VERSION,
            "compiler_version": CATALOG_BRIDGE_VERSION,
            "input_id": self.input_id,
            "intake_bundle_hash": self.intake_bundle_hash,
            "regulation_id": self.regulation_id,
            "regulation_revision": self.regulation_revision,
            "target_pool_hash": self.target_pool_hash,
            "target_key_hash": self.target_key_hash,
            "runtime_catalog_hash": self.runtime_catalog_hash,
            "target_member_count": self.target_member_count,
            "source_policy": {
                "license_status": "unverified",
                "access_scope": "local_only",
                "redistribution": "prohibited",
                "payload_policy": "reference_only_no_raw_effect_text",
            },
            "members": [value.to_data() for value in self.members],
            "records": [value.to_data() for value in self.records],
            "evidence_refs": [artifact_ref_data(value) for value in self.evidence_refs],
            "source_manifest_ids": list(self.source_manifest_ids),
            "blockers": list(self.blockers),
            "denominator_final": self.denominator_final,
            "catalog_emit_eligible": self.catalog_emit_eligible,
        }

    @property
    def input_hash(self) -> str:
        return canonical_sha256(self.unsigned_data())

    def to_data(self) -> dict[str, Any]:
        return {**self.unsigned_data(), "input_hash": self.input_hash}

    def to_json(self) -> str:
        return canonical_json(self.to_data())


@dataclass(frozen=True, slots=True)
class CatalogBridgeResult:
    mapping_evidence: MappingEvidenceSet
    catalog_input: ProductionCatalogInput
    runtime_catalog: dict[str, Any]

    def __post_init__(self) -> None:
        runtime_hash = canonical_sha256(self.runtime_catalog)
        if runtime_hash != self.catalog_input.runtime_catalog_hash:
            raise CatalogCompilerError("runtime Catalog hash does not match compiler input")
        if self.mapping_evidence.catalog_hash != runtime_hash:
            raise CatalogCompilerError(
                "mapping evidence must bind to the runtime Catalog canonical hash"
            )
        if self.mapping_evidence.target_pool_hash != self.catalog_input.target_pool_hash:
            raise CatalogCompilerError("bridge target-pool hashes differ")

    def runtime_catalog_json(self) -> str:
        """Bytes written from this string hash exactly to mapping.catalog_hash."""

        return canonical_json(self.runtime_catalog)


def artifact_ref_data(value: ArtifactRecordRef | None) -> dict[str, str] | None:
    if value is None:
        return None
    return {
        "evidence_ref_id": value.evidence_ref_id,
        "source_manifest_id": value.source_manifest_id,
        "artifact_id": value.artifact_id,
        "json_pointer": value.json_pointer,
        "record_sha256": value.record_sha256,
    }
