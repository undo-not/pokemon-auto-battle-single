"""Current-context Champions readiness for trust-attested SIM-02C V3 inputs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from champions_sim.core import canonical_hash, canonical_json
from champions_sim.promotion.compiler import PROMOTION_COMPONENT_HASH_FIELDS
from champions_sim.promotion.compiler_v3 import (
    AttestedProductionPromotionCompilationV3,
    validate_attested_production_promotion_compilation_v3,
)
from champions_sim.promotion.trust import ProductionTrustContextV1


CHAMPIONS_READINESS_V3_SCHEMA_VERSION = "3.0.0"
CHAMPIONS_READINESS_V3_COMPILER_ID = "champions-readiness-v3"


class ChampionsReadinessV3Error(ValueError):
    """A V3 readiness seal cannot be issued or revalidated."""


@dataclass(frozen=True, slots=True)
class ResolvedChampionsReadinessV3:
    """Stable seal whose use always requires a fresh external trust context."""

    schema_version: str
    compiler_id: str
    compilation_binding_hash: str
    stable_trust_binding_hash: str
    _compilation: AttestedProductionPromotionCompilationV3 = field(
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if self.schema_version != CHAMPIONS_READINESS_V3_SCHEMA_VERSION:
            raise ChampionsReadinessV3Error("unsupported V3 readiness schema_version")
        if self.compiler_id != CHAMPIONS_READINESS_V3_COMPILER_ID:
            raise ChampionsReadinessV3Error("unsupported V3 readiness compiler identity")
        if type(self._compilation) is not AttestedProductionPromotionCompilationV3:
            raise ChampionsReadinessV3Error(
                "V3 readiness requires exact attested compilation substance"
            )
        try:
            self._compilation.__post_init__()
        except Exception as error:
            raise ChampionsReadinessV3Error(
                "retained V3 compilation is structurally invalid"
            ) from error
        if self.compilation_binding_hash != self._compilation.compilation_hash:
            raise ChampionsReadinessV3Error(
                "readiness compilation binding differs from V3 compilation"
            )
        if self.stable_trust_binding_hash != self._compilation.stable_trust_binding_hash:
            raise ChampionsReadinessV3Error(
                "readiness trust binding differs from V3 compilation"
            )

    def _projection(self) -> dict[str, Any]:
        compilation = self._compilation
        base = compilation.base_compilation
        report = base.report
        subject = compilation.trust_subject
        receipt = compilation._trust_receipt
        enrollment = compilation._trust_enrollment
        component_hashes = {
            name: getattr(report, name) for name in PROMOTION_COMPONENT_HASH_FIELDS
        }
        return {
            "schema_version": self.schema_version,
            "compiler_id": self.compiler_id,
            "authorization_status": "not_authorization",
            "current_trust_context_required": True,
            "readiness_status": "production_candidate",
            "promotion_gate_passed": True,
            "champions_candidate": True,
            "champions_fidelity_status": "evidence_attested",
            "rank1_equivalence_status": "unmeasured",
            "attestation_scope": "production_champions",
            "regulation_id": subject.regulation_id,
            "regulation_revision": subject.regulation_revision,
            "regulation_hash": subject.regulation_hash,
            "target_pool_id": subject.target_pool_id,
            "target_pool_hash": subject.target_pool_hash,
            "input_manifest_id": compilation.input_manifest.manifest_id,
            "input_manifest_hash": compilation.input_manifest.manifest_hash,
            "input_content_hash": compilation.input_manifest.input_content_hash,
            "request_binding_hash": compilation.input_manifest.request_binding_hash,
            "replay_binding_hash": subject.replay_binding_hash,
            "source_authority_subject_hash": subject.source_authority_subject_hash,
            "base_compilation_id": base.compilation_id,
            "base_compilation_hash": base.compilation_hash,
            "base_promotion_report_id": report.report_id,
            "base_promotion_report_hash": report.report_hash,
            "component_hashes": component_hashes,
            "v3_document_set_hash": compilation.document_set_hash,
            "trust_attestation_id": receipt.attestation_id,
            "trust_attestation_hash": receipt.attestation_hash,
            "trust_subject_hash": receipt.subject_hash,
            "stable_trust_binding_hash": self.stable_trust_binding_hash,
            "trust_policy_id": receipt.policy_id,
            "trust_policy_epoch": receipt.policy_epoch,
            "trust_policy_sha256": receipt.policy_sha256,
            "trust_issuer_id": receipt.issuer_id,
            "trust_key_id": receipt.key_id,
            "trust_key_fingerprint_sha256": receipt.key_fingerprint_sha256,
            "trust_ledger_binding_hash": receipt.ledger_binding_hash,
            "trust_registry_id": enrollment.registry_id,
            "trust_registry_sha256": enrollment.registry_sha256,
            "trust_enrollment_id": enrollment.enrollment_id,
            "trust_enrollment_binding_hash": enrollment.enrollment_binding_hash,
            "trust_enrollment_minimum_policy_epoch": (
                enrollment.minimum_policy_epoch
            ),
            "trust_enrollment_ssh_keygen_sha256": enrollment.ssh_keygen_sha256,
            "trust_ledger_instance_id": enrollment.ledger_instance_id,
            "trust_ledger_path_binding_hash": enrollment.ledger_path_binding_hash,
            "compilation_binding_hash": self.compilation_binding_hash,
        }

    @property
    def seal_id(self) -> str:
        return "champions-readiness-v3-" + canonical_hash(self._projection())

    def unsigned_data(self) -> dict[str, Any]:
        return {**self._projection(), "seal_id": self.seal_id}

    @property
    def seal_hash(self) -> str:
        return canonical_hash(self.unsigned_data())

    def to_data(self) -> dict[str, Any]:
        return {**self.unsigned_data(), "seal_hash": self.seal_hash}

    def to_json(self) -> str:
        return canonical_json(self.to_data())

    def validate_against(
        self,
        *,
        trust_context: ProductionTrustContextV1,
    ) -> None:
        validate_champions_readiness_v3(self, trust_context=trust_context)


def resolve_champions_readiness_v3(
    compilation: AttestedProductionPromotionCompilationV3,
    *,
    trust_context: ProductionTrustContextV1,
) -> ResolvedChampionsReadinessV3:
    """Recompile and reverify current trust before issuing a stable V3 seal."""

    try:
        resolved = validate_attested_production_promotion_compilation_v3(
            compilation,
            trust_context=trust_context,
        )
    except Exception as error:
        raise ChampionsReadinessV3Error(
            "current-context V3 compilation validation failed"
        ) from error
    return ResolvedChampionsReadinessV3(
        schema_version=CHAMPIONS_READINESS_V3_SCHEMA_VERSION,
        compiler_id=CHAMPIONS_READINESS_V3_COMPILER_ID,
        compilation_binding_hash=resolved.compilation_hash,
        stable_trust_binding_hash=resolved.stable_trust_binding_hash,
        _compilation=resolved,
    )


def validate_champions_readiness_v3(
    readiness: ResolvedChampionsReadinessV3,
    *,
    trust_context: ProductionTrustContextV1,
) -> ResolvedChampionsReadinessV3:
    if type(readiness) is not ResolvedChampionsReadinessV3:
        raise ChampionsReadinessV3Error("validation requires exact V3 readiness")
    readiness.__post_init__()
    resolved = resolve_champions_readiness_v3(
        readiness._compilation,
        trust_context=trust_context,
    )
    if resolved.to_data() != readiness.to_data():
        raise ChampionsReadinessV3Error(
            "V3 readiness differs from current-context recomputation"
        )
    return readiness


__all__ = [
    "CHAMPIONS_READINESS_V3_COMPILER_ID",
    "CHAMPIONS_READINESS_V3_SCHEMA_VERSION",
    "ChampionsReadinessV3Error",
    "ResolvedChampionsReadinessV3",
    "resolve_champions_readiness_v3",
    "validate_champions_readiness_v3",
]
