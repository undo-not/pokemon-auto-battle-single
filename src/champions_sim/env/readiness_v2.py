"""Resolver-backed SIM-02B readiness seal for positive V2 compilations.

This module is intentionally separate from :mod:`champions_sim.env.readiness`.
The V1 resolver remains a diagnostic-only, non-issuing boundary.  V2 accepts
only an exact ``ProductionPromotionCompilationV2`` and derives every seal
field from the result returned by the production compiler's full revalidation
path.  Caller-provided flags and hashes never participate in issuance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import re
from typing import Any, Mapping

from champions_sim.core import canonical_hash, canonical_json
from champions_sim.promotion.compiler import (
    PROMOTION_COMPILATION_SCHEMA_VERSION,
    ProductionPromotionCompilationV2,
    validate_production_promotion_compilation_v2,
)
from champions_sim.promotion.reporting import (
    PROMOTION_COMPILER_ID,
    ProductionPromotionReportV2,
)
from champions_sim.promotion.sources import PromotionSourceScopeV2


CHAMPIONS_READINESS_V2_SCHEMA_VERSION = "2.0.0"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_STABLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,239}$")
_SCOPES = frozenset(
    {
        PromotionSourceScopeV2.TEST_AUTHORITATIVE.value,
        PromotionSourceScopeV2.PRODUCTION_CHAMPIONS.value,
    }
)
_COMPONENT_HASH_FIELDS = (
    "source_resolution_set_hash",
    "artifact_binding_hash",
    "regulation_hash",
    "target_pool_hash",
    "catalog_hash",
    "ruleset_hash",
    "mapping_evidence_hash",
    "target_pool_manifest_hash",
    "semantic_compilation_hash",
    "target_capability_set_hash",
    "execution_compilation_hash",
    "construction_corpus_hash",
    "scenario_corpus_hash",
    "external_holdout_scenario_corpus_hash",
    "partition_manifest_hash",
    "external_holdout_hash",
    "grounding_resolution_hash",
    "engine_probe_report_hash",
    "mechanic_coverage_matrix_hash",
    "timing_evidence_hash",
)


class ChampionsReadinessV2Error(ValueError):
    """A V2 compilation cannot issue or revalidate a readiness seal."""


def _stable(value: str, label: str) -> None:
    if type(value) is not str or _STABLE_ID.fullmatch(value) is None:
        raise ChampionsReadinessV2Error(f"{label} must be a stable ID")


def _sha256(value: str, label: str) -> None:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ChampionsReadinessV2Error(f"{label} must be a lowercase SHA-256")


def _document_set_hash(documents: Mapping[str, str]) -> str:
    if not isinstance(documents, Mapping) or not documents:
        raise ChampionsReadinessV2Error(
            "validated compilation has no portable document set"
        )
    digests: list[tuple[str, str, int]] = []
    for name, document in sorted(documents.items()):
        if (
            type(name) is not str
            or not name
            or "/" in name
            or "\\" in name
            or type(document) is not str
        ):
            raise ChampionsReadinessV2Error(
                "validated compilation documents must be named UTF-8 strings"
            )
        payload = document.encode("utf-8")
        digests.append((name, hashlib.sha256(payload).hexdigest(), len(payload)))
    return canonical_hash(tuple(digests))


def _direct_component_hashes(
    compilation: ProductionPromotionCompilationV2,
) -> dict[str, str]:
    """Read content identities from the recomputed component objects."""

    try:
        return {
            "source_resolution_set_hash": compilation.source_set.resolution_set_hash,
            "regulation_hash": (
                compilation.regulation_bundle.regulation.snapshot_hash
            ),
            "target_pool_hash": (
                compilation.regulation_bundle.target_pool.snapshot_hash
            ),
            "catalog_hash": compilation.catalog.snapshot_hash,
            "ruleset_hash": compilation.ruleset.snapshot_hash,
            "mapping_evidence_hash": compilation.mapping_evidence.snapshot_hash,
            "target_pool_manifest_hash": (
                compilation.target_pool_manifest.manifest_hash
            ),
            "semantic_compilation_hash": (
                compilation.semantic_compilation.compilation_hash
            ),
            "target_capability_set_hash": (
                compilation.target_capability_set.capability_set_hash
            ),
            "execution_compilation_hash": (
                compilation.execution_compilation.compilation_hash
            ),
            "construction_corpus_hash": (
                compilation.development_construction_corpus.snapshot_hash
            ),
            "scenario_corpus_hash": (
                compilation.development_scenario_corpus.corpus_hash
            ),
            "external_holdout_scenario_corpus_hash": (
                compilation.external_holdout_scenario_corpus.corpus_hash
            ),
            "partition_manifest_hash": (
                compilation.partition_manifest.partition_hash
            ),
            "external_holdout_hash": (
                compilation.external_holdout_report.report_hash
            ),
            # This is the resolver result, not the raw assertion-set input hash.
            "grounding_resolution_hash": canonical_hash(
                compilation.grounding_resolution
            ),
            "engine_probe_report_hash": (
                compilation.engine_probe_report.report_hash
            ),
            "mechanic_coverage_matrix_hash": (
                compilation.mechanic_coverage_matrix.matrix_hash
            ),
            "timing_evidence_hash": compilation.timing_evidence.timing_hash,
        }
    except (AttributeError, TypeError, ValueError) as error:
        raise ChampionsReadinessV2Error(
            "validated compilation is missing component identity substance"
        ) from error


def _validate_recomputed_compilation(
    compilation: ProductionPromotionCompilationV2,
) -> tuple[
    ProductionPromotionCompilationV2,
    ProductionPromotionReportV2,
    dict[str, str],
    str,
]:
    if type(compilation) is not ProductionPromotionCompilationV2:
        raise ChampionsReadinessV2Error(
            "V2 readiness requires exact ProductionPromotionCompilationV2"
        )
    try:
        resolved = validate_production_promotion_compilation_v2(compilation)
    except Exception as error:
        raise ChampionsReadinessV2Error(
            "production promotion compilation revalidation failed"
        ) from error
    if type(resolved) is not ProductionPromotionCompilationV2:
        raise ChampionsReadinessV2Error(
            "promotion validator returned a non-V2 compilation"
        )
    if resolved.schema_version != PROMOTION_COMPILATION_SCHEMA_VERSION:
        raise ChampionsReadinessV2Error(
            "validated compilation has an unsupported schema_version"
        )
    report = resolved.report
    if type(report) is not ProductionPromotionReportV2:
        raise ChampionsReadinessV2Error(
            "validated compilation requires exact ProductionPromotionReportV2"
        )
    try:
        report.__post_init__()
    except ValueError as error:
        raise ChampionsReadinessV2Error(
            "validated promotion report is structurally invalid"
        ) from error
    if type(resolved.source_set.scope) is not PromotionSourceScopeV2:
        raise ChampionsReadinessV2Error(
            "validated source set has a non-V2 attestation scope"
        )
    scope = resolved.source_set.scope.value
    if scope not in _SCOPES or report.attestation_scope != scope:
        raise ChampionsReadinessV2Error(
            "promotion report scope differs from resolver-verified source scope"
        )

    direct = _direct_component_hashes(resolved)
    direct["artifact_binding_hash"] = report.artifact_binding_hash
    for name in _COMPONENT_HASH_FIELDS:
        value = direct.get(name)
        _sha256(value, name)  # type: ignore[arg-type]
        if getattr(report, name) != value:
            raise ChampionsReadinessV2Error(
                f"promotion report component differs from recomputation: {name}"
            )
    regulation = resolved.regulation_bundle.regulation
    if (
        report.regulation_id != regulation.regulation_id
        or report.regulation_revision != regulation.revision
    ):
        raise ChampionsReadinessV2Error(
            "promotion report regulation identity differs from recomputation"
        )

    documents = resolved.documents
    if not isinstance(documents, Mapping):
        raise ChampionsReadinessV2Error(
            "validated compilation document set is missing"
        )
    expected_document_names = {
        digest.file_name for digest in report.documents
    } | {"promotion-report.json"}
    if set(documents) != expected_document_names:
        raise ChampionsReadinessV2Error(
            "validated compilation document membership differs from report"
        )
    if documents.get("promotion-report.json") != report.to_json():
        raise ChampionsReadinessV2Error(
            "validated compilation promotion-report document differs"
        )
    for digest in report.documents:
        document = documents.get(digest.file_name)
        if type(document) is not str:
            raise ChampionsReadinessV2Error(
                f"validated compilation lacks document: {digest.file_name}"
            )
        payload = document.encode("utf-8")
        if (
            hashlib.sha256(payload).hexdigest() != digest.sha256
            or len(payload) != digest.byte_count
        ):
            raise ChampionsReadinessV2Error(
                f"validated compilation document digest differs: {digest.file_name}"
            )
    document_set_hash = _document_set_hash(documents)
    try:
        portable_document_set_hash = resolved.document_set_hash
        portable_compilation_hash = resolved.compilation_hash
    except (AttributeError, TypeError, ValueError) as error:
        raise ChampionsReadinessV2Error(
            "validated compilation lacks its portable manifest identity"
        ) from error
    if document_set_hash != portable_document_set_hash:
        raise ChampionsReadinessV2Error(
            "readiness document-set hash differs from portable compilation"
        )
    _sha256(portable_compilation_hash, "portable compilation_hash")
    return resolved, report, direct, document_set_hash


def _readiness_projection_hash(
    *,
    attestation_scope: str,
    regulation_id: str,
    regulation_revision: str,
    source_set_id: str,
    promotion_report_id: str,
    promotion_report_hash: str,
    compilation_hash: str,
    component_hashes: Mapping[str, str],
    document_set_hash: str,
) -> str:
    return canonical_hash(
        {
            "attestation_scope": attestation_scope,
            "regulation_id": regulation_id,
            "regulation_revision": regulation_revision,
            "source_set_id": source_set_id,
            "promotion_report_id": promotion_report_id,
            "promotion_report_hash": promotion_report_hash,
            "compilation_hash": compilation_hash,
            "component_hashes": {
                name: component_hashes[name] for name in _COMPONENT_HASH_FIELDS
            },
            "document_set_hash": document_set_hash,
        }
    )


def _seal_id(attestation_scope: str, readiness_projection_hash: str) -> str:
    return "champions-readiness-v2-" + canonical_hash(
        (attestation_scope, readiness_projection_hash)
    )


@dataclass(frozen=True, slots=True)
class ResolvedChampionsReadinessV2:
    """Content-addressed engineering or production readiness attestation."""

    schema_version: str
    seal_id: str
    compiler_id: str
    attestation_scope: str
    readiness_status: str
    promotion_gate_passed: bool
    engineering_seal_issued: bool
    champions_candidate: bool
    champions_fidelity_status: str
    rank1_equivalence_status: str
    regulation_id: str
    regulation_revision: str
    source_set_id: str
    promotion_report_id: str
    promotion_report_hash: str
    source_resolution_set_hash: str
    artifact_binding_hash: str
    regulation_hash: str
    target_pool_hash: str
    catalog_hash: str
    ruleset_hash: str
    mapping_evidence_hash: str
    target_pool_manifest_hash: str
    semantic_compilation_hash: str
    target_capability_set_hash: str
    execution_compilation_hash: str
    construction_corpus_hash: str
    scenario_corpus_hash: str
    external_holdout_scenario_corpus_hash: str
    partition_manifest_hash: str
    external_holdout_hash: str
    grounding_resolution_hash: str
    engine_probe_report_hash: str
    mechanic_coverage_matrix_hash: str
    timing_evidence_hash: str
    document_set_hash: str
    compilation_binding_hash: str
    _compilation: ProductionPromotionCompilationV2 = field(
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if self.schema_version != CHAMPIONS_READINESS_V2_SCHEMA_VERSION:
            raise ChampionsReadinessV2Error(
                "unsupported Champions readiness V2 schema_version"
            )
        if self.compiler_id != PROMOTION_COMPILER_ID:
            raise ChampionsReadinessV2Error(
                "unsupported production promotion compiler identity"
            )
        if type(self._compilation) is not ProductionPromotionCompilationV2:
            raise ChampionsReadinessV2Error(
                "readiness seal must retain exact V2 compilation substance"
            )
        for value, label in (
            (self.seal_id, "seal_id"),
            (self.regulation_id, "regulation_id"),
            (self.regulation_revision, "regulation_revision"),
            (self.source_set_id, "source_set_id"),
            (self.promotion_report_id, "promotion_report_id"),
        ):
            _stable(value, label)
        for name in (
            "promotion_report_hash",
            *_COMPONENT_HASH_FIELDS,
            "document_set_hash",
            "compilation_binding_hash",
        ):
            _sha256(getattr(self, name), name)
        if self.attestation_scope not in _SCOPES:
            raise ChampionsReadinessV2Error("unsupported attestation_scope")
        production = (
            self.attestation_scope
            == PromotionSourceScopeV2.PRODUCTION_CHAMPIONS.value
        )
        expected_status = (
            "production_candidate" if production else "engineering_sealed"
        )
        if self.readiness_status != expected_status:
            raise ChampionsReadinessV2Error(
                "readiness status differs from attestation scope"
            )
        if (
            self.promotion_gate_passed is not True
            or self.engineering_seal_issued is not True
            or self.champions_candidate is not production
        ):
            raise ChampionsReadinessV2Error(
                "readiness issuance flags differ from attestation scope"
            )
        expected_fidelity = "evidence_attested" if production else "not_attested"
        if self.champions_fidelity_status != expected_fidelity:
            raise ChampionsReadinessV2Error(
                "Champions fidelity status differs from attestation scope"
            )
        if self.rank1_equivalence_status != "unmeasured":
            raise ChampionsReadinessV2Error(
                "SIM-02B readiness cannot claim rank-1 equivalence"
            )
        component_hashes = {
            name: getattr(self, name) for name in _COMPONENT_HASH_FIELDS
        }
        retained_report = self._compilation.report
        if type(retained_report) is not ProductionPromotionReportV2:
            raise ChampionsReadinessV2Error(
                "retained compilation lacks an exact promotion report"
            )
        retained_scope = self._compilation.source_set.scope.value
        if (
            self.compiler_id != retained_report.compiler_id
            or self.attestation_scope != retained_scope
            or self.attestation_scope != retained_report.attestation_scope
            or self.regulation_id != retained_report.regulation_id
            or self.regulation_revision != retained_report.regulation_revision
            or self.source_set_id != self._compilation.source_set.source_set_id
            or self.promotion_report_id != retained_report.report_id
            or self.promotion_report_hash != retained_report.report_hash
            or any(
                component_hashes[name] != getattr(retained_report, name)
                for name in _COMPONENT_HASH_FIELDS
            )
        ):
            raise ChampionsReadinessV2Error(
                "readiness projection differs from retained compilation"
            )
        try:
            retained_compilation_hash = self._compilation.compilation_hash
            retained_document_set_hash = self._compilation.document_set_hash
        except (AttributeError, TypeError, ValueError) as error:
            raise ChampionsReadinessV2Error(
                "retained compilation lacks its portable manifest identity"
            ) from error
        if self.compilation_binding_hash != retained_compilation_hash:
            raise ChampionsReadinessV2Error(
                "readiness compilation binding differs from portable compilation"
            )
        if self.document_set_hash != retained_document_set_hash:
            raise ChampionsReadinessV2Error(
                "readiness document binding differs from portable compilation"
            )
        readiness_projection_hash = _readiness_projection_hash(
            attestation_scope=self.attestation_scope,
            regulation_id=self.regulation_id,
            regulation_revision=self.regulation_revision,
            source_set_id=self.source_set_id,
            promotion_report_id=self.promotion_report_id,
            promotion_report_hash=self.promotion_report_hash,
            compilation_hash=self.compilation_binding_hash,
            component_hashes=component_hashes,
            document_set_hash=self.document_set_hash,
        )
        if self.seal_id != _seal_id(
            self.attestation_scope, readiness_projection_hash
        ):
            raise ChampionsReadinessV2Error("readiness seal_id is not content-derived")

    def _component_hashes(self) -> dict[str, str]:
        return {name: getattr(self, name) for name in _COMPONENT_HASH_FIELDS}

    def unsigned_data(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "seal_id": self.seal_id,
            "compiler_id": self.compiler_id,
            "attestation_scope": self.attestation_scope,
            "readiness_status": self.readiness_status,
            "promotion_gate_passed": self.promotion_gate_passed,
            "engineering_seal_issued": self.engineering_seal_issued,
            "champions_candidate": self.champions_candidate,
            "champions_fidelity_status": self.champions_fidelity_status,
            "rank1_equivalence_status": self.rank1_equivalence_status,
            "regulation_id": self.regulation_id,
            "regulation_revision": self.regulation_revision,
            "source_set_id": self.source_set_id,
            "promotion_report_id": self.promotion_report_id,
            "promotion_report_hash": self.promotion_report_hash,
            "component_hashes": self._component_hashes(),
            "document_set_hash": self.document_set_hash,
            "compilation_binding_hash": self.compilation_binding_hash,
        }

    @property
    def seal_hash(self) -> str:
        return canonical_hash(self.unsigned_data())

    def to_data(self) -> dict[str, Any]:
        return {**self.unsigned_data(), "seal_hash": self.seal_hash}

    def to_json(self) -> str:
        return canonical_json(self.to_data())

    def validate_against(self) -> None:
        resolved = resolve_champions_readiness_v2(self._compilation)
        if self.to_data() != resolved.to_data():
            raise ChampionsReadinessV2Error(
                "readiness seal differs from recomputed V2 compilation substance"
            )


def resolve_champions_readiness_v2(
    compilation: ProductionPromotionCompilationV2,
) -> ResolvedChampionsReadinessV2:
    """Recompile an exact positive V2 input and issue its scoped readiness seal."""

    resolved, report, component_hashes, document_set_hash = (
        _validate_recomputed_compilation(compilation)
    )
    scope = resolved.source_set.scope.value
    production = scope == PromotionSourceScopeV2.PRODUCTION_CHAMPIONS.value
    compilation_binding_hash = resolved.compilation_hash
    readiness_projection_hash = _readiness_projection_hash(
        attestation_scope=scope,
        regulation_id=report.regulation_id,
        regulation_revision=report.regulation_revision,
        source_set_id=resolved.source_set.source_set_id,
        promotion_report_id=report.report_id,
        promotion_report_hash=report.report_hash,
        compilation_hash=compilation_binding_hash,
        component_hashes=component_hashes,
        document_set_hash=document_set_hash,
    )
    return ResolvedChampionsReadinessV2(
        schema_version=CHAMPIONS_READINESS_V2_SCHEMA_VERSION,
        seal_id=_seal_id(scope, readiness_projection_hash),
        compiler_id=PROMOTION_COMPILER_ID,
        attestation_scope=scope,
        readiness_status=(
            "production_candidate" if production else "engineering_sealed"
        ),
        promotion_gate_passed=True,
        engineering_seal_issued=True,
        champions_candidate=production,
        champions_fidelity_status=(
            "evidence_attested" if production else "not_attested"
        ),
        rank1_equivalence_status="unmeasured",
        regulation_id=report.regulation_id,
        regulation_revision=report.regulation_revision,
        source_set_id=resolved.source_set.source_set_id,
        promotion_report_id=report.report_id,
        promotion_report_hash=report.report_hash,
        **component_hashes,
        document_set_hash=document_set_hash,
        compilation_binding_hash=compilation_binding_hash,
        _compilation=resolved,
    )


__all__ = [
    "CHAMPIONS_READINESS_V2_SCHEMA_VERSION",
    "ChampionsReadinessV2Error",
    "ResolvedChampionsReadinessV2",
    "resolve_champions_readiness_v2",
]
