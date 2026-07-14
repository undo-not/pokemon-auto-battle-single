"""Resolver-backed positive promotion compiler for SIM-02B.

The frozen v1 compiler remains diagnostic-only.  This module accepts only
integrity-resolved V2 source manifests plus exact engine-scenario and Replay
objects whose canonical bytes are present in those manifests.  The public V2
API returns test-authoritative compilations only and is unconditionally
fail-closed for production.  Verified production entry is exclusively through
the V3 trust/enrollment wrapper; incomplete M-B evidence belongs in the
separate negative assessment API.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import Any, Mapping

from champions_sim.capabilities import (
    ConstructionSelectionCorpus,
    MappingResolutionStatus,
    ProbeExecution,
    ProbeSpec,
    ResolvedAssertionVerdict,
    TargetCapabilitySet,
    VerificationStatus,
    build_mechanic_coverage_matrix,
    build_target_capability_set,
    build_target_pool_manifest,
    evaluate_external_holdout,
    load_construction_selection_corpus,
    load_grounding_assertion_set,
    load_mapping_evidence_set,
    resolve_grounding_assertions,
    run_capability_probes,
)
from champions_sim.catalog import load_catalog, load_ruleset
from champions_sim.compiler.execution import compile_execution_registry
from champions_sim.compiler.semantic import compile_effect_semantic_registry
from champions_sim.core import (
    ReplayRecord,
    canonical_hash,
    canonical_json,
    to_canonical_data,
)
from champions_sim.engine import BattleEngine
from champions_sim.grounding import ValidatedGroundingTrace
from champions_sim.regulations import (
    RegulationDataBundle,
    load_regulation_snapshot,
    load_target_pool,
)

from .reporting import (
    PROMOTION_COMPILER_ID,
    PROMOTION_REPORT_SCHEMA_VERSION,
    ExactRateV2,
    ProductionPromotionReportV2,
    PromotionDocumentDigestV2,
    PromotionTimingEvidenceV2,
    exact_rate_binding_hash_v2,
    production_report_id_v2,
)
from .scenarios import (
    EngineProbeReportV2,
    EngineScenarioCorpusV2,
    ScenarioPartitionManifestV2,
    build_engine_probe_report_v2,
    build_scenario_partition_manifest_v2,
    verify_engine_probe_v2,
)
from .sources import (
    PromotionArtifactRoleV2,
    PromotionRecordReferenceV2,
    PromotionSourceScopeV2,
    ResolvedArtifactV2,
    ResolvedPromotionRecordV2,
    ResolvedPromotionSourceManifestV2,
    resolve_promotion_source_manifest_v2,
    read_resolved_artifact,
    read_resolved_json_record,
)
from .trust import ProductionTrustSubjectV1, ResolvedProductionTrustV1
from .trust_enrollment import (
    ResolvedProductionTrustEnrollmentV1,
    validate_production_trust_receipt_enrollment_v1,
)


PROMOTION_COMPILATION_SCHEMA_VERSION = "2.0.0"

# Only the dedicated V3 compiler may cross the production branch after it has
# verified an artifact-root-external trust attestation.  The public V2 API
# always calls the core with ``None`` and therefore remains unconditionally
# fail-closed for production sources.
_PRODUCTION_TRUST_CAPABILITY_V3 = object()

PROMOTION_COMPONENT_HASH_FIELDS = (
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


class PromotionCompilationError(ValueError):
    """Positive promotion evidence is absent, inconsistent, or forged."""


@dataclass(frozen=True, slots=True)
class _VerifiedProductionTrustProofV3:
    """Misuse-resistant in-process proof; not a hostile-code boundary."""

    subject: ProductionTrustSubjectV1
    receipt: ResolvedProductionTrustV1
    enrollment: ResolvedProductionTrustEnrollmentV1

    def __post_init__(self) -> None:
        if type(self.subject) is not ProductionTrustSubjectV1:
            raise PromotionCompilationError(
                "V3 trust proof requires an exact production subject"
            )
        if type(self.receipt) is not ResolvedProductionTrustV1:
            raise PromotionCompilationError(
                "V3 trust proof requires an exact resolved trust receipt"
            )
        if type(self.enrollment) is not ResolvedProductionTrustEnrollmentV1:
            raise PromotionCompilationError(
                "V3 trust proof requires an exact external trust enrollment"
            )
        self.subject.__post_init__()
        self.receipt.__post_init__()
        self.enrollment.__post_init__()
        if self.receipt.subject_hash != self.subject.subject_hash:
            raise PromotionCompilationError(
                "V3 trust proof receipt differs from its production subject"
            )
        try:
            validate_production_trust_receipt_enrollment_v1(
                self.enrollment,
                self.receipt,
            )
        except Exception as error:
            raise PromotionCompilationError(
                "V3 trust proof receipt differs from its external enrollment"
            ) from error


@dataclass(frozen=True, slots=True)
class PromotionArtifactLocatorV2:
    source_manifest_id: str
    artifact_id: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.source_manifest_id, "source_manifest_id"),
            (self.artifact_id, "artifact_id"),
        ):
            if type(value) is not str or not value:
                raise PromotionCompilationError(f"{label} must be a non-empty string")


@dataclass(frozen=True, slots=True)
class PromotionArtifactBindingsV2:
    regulation: PromotionArtifactLocatorV2
    target_pool: PromotionArtifactLocatorV2
    catalog: PromotionArtifactLocatorV2
    ruleset: PromotionArtifactLocatorV2
    mapping_evidence: PromotionArtifactLocatorV2
    development_construction_corpus: PromotionArtifactLocatorV2
    external_holdout_construction_corpus: PromotionArtifactLocatorV2
    grounding_assertions: PromotionArtifactLocatorV2
    development_scenario_corpus: PromotionArtifactLocatorV2
    external_holdout_scenario_corpus: PromotionArtifactLocatorV2
    timing_evidence: PromotionArtifactLocatorV2

    def __post_init__(self) -> None:
        values = self.values()
        if any(type(value) is not PromotionArtifactLocatorV2 for value in values):
            raise PromotionCompilationError("artifact bindings require exact locators")
        for value in values:
            value.__post_init__()
        identities = tuple((value.source_manifest_id, value.artifact_id) for value in values)
        if len(identities) != len(set(identities)):
            raise PromotionCompilationError("distinct promotion roles require distinct artifacts")

    def values(self) -> tuple[PromotionArtifactLocatorV2, ...]:
        return (
            self.regulation,
            self.target_pool,
            self.catalog,
            self.ruleset,
            self.mapping_evidence,
            self.development_construction_corpus,
            self.external_holdout_construction_corpus,
            self.grounding_assertions,
            self.development_scenario_corpus,
            self.external_holdout_scenario_corpus,
            self.timing_evidence,
        )

    @property
    def binding_hash(self) -> str:
        return canonical_hash(self)

    def to_json(self) -> str:
        return canonical_json(self)


@dataclass(frozen=True, slots=True)
class ReplayArtifactBindingV2:
    scenario_id: str
    artifact: PromotionArtifactLocatorV2

    def __post_init__(self) -> None:
        if type(self.scenario_id) is not str or not self.scenario_id:
            raise PromotionCompilationError("scenario_id must be a non-empty string")
        if type(self.artifact) is not PromotionArtifactLocatorV2:
            raise PromotionCompilationError("Replay binding requires an exact locator")
        self.artifact.__post_init__()


@dataclass(frozen=True, slots=True)
class ProductionPromotionRequestV2:
    artifact_root: Path
    manifest_relative_paths: tuple[str, ...]
    artifacts: PromotionArtifactBindingsV2
    replay_artifacts: tuple[ReplayArtifactBindingV2, ...]
    grounding_evidence_refs: tuple[PromotionRecordReferenceV2, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.artifact_root, Path):
            raise PromotionCompilationError("artifact_root must be a Path")
        try:
            root = self.artifact_root.resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise PromotionCompilationError("artifact_root does not resolve") from error
        if not root.is_dir():
            raise PromotionCompilationError("artifact_root must be a directory")
        if type(self.manifest_relative_paths) is not tuple or not self.manifest_relative_paths:
            raise PromotionCompilationError("promotion request requires source manifests")
        if self.manifest_relative_paths != tuple(sorted(self.manifest_relative_paths)):
            raise PromotionCompilationError("manifest paths must be sorted")
        if len(self.manifest_relative_paths) != len(set(self.manifest_relative_paths)):
            raise PromotionCompilationError("manifest paths must be unique")
        for value in self.manifest_relative_paths:
            _relative_path(value, "manifest_relative_path")
            _contained_path(root, value, "source manifest")
        if type(self.artifacts) is not PromotionArtifactBindingsV2:
            raise PromotionCompilationError("request requires exact artifact bindings")
        self.artifacts.__post_init__()
        if type(self.replay_artifacts) is not tuple or not self.replay_artifacts:
            raise PromotionCompilationError("request requires Replay artifact bindings")
        if any(type(value) is not ReplayArtifactBindingV2 for value in self.replay_artifacts):
            raise PromotionCompilationError("invalid Replay artifact binding type")
        for value in self.replay_artifacts:
            value.__post_init__()
        scenario_ids = tuple(value.scenario_id for value in self.replay_artifacts)
        if scenario_ids != tuple(sorted(scenario_ids)) or len(scenario_ids) != len(set(scenario_ids)):
            raise PromotionCompilationError("Replay bindings must be unique and sorted")
        if type(self.grounding_evidence_refs) is not tuple:
            raise PromotionCompilationError(
                "grounding evidence references must be an exact tuple"
            )
        if any(
            type(value) is not PromotionRecordReferenceV2
            for value in self.grounding_evidence_refs
        ):
            raise PromotionCompilationError(
                "grounding evidence references require exact V2 values"
            )
        for value in self.grounding_evidence_refs:
            value.__post_init__()
        grounding_ids = tuple(
            value.evidence_ref_id for value in self.grounding_evidence_refs
        )
        if (
            grounding_ids != tuple(sorted(grounding_ids))
            or len(grounding_ids) != len(set(grounding_ids))
        ):
            raise PromotionCompilationError(
                "grounding evidence references must be unique and sorted"
            )


@dataclass(frozen=True, slots=True)
class ResolvedPromotionSourceSetV2:
    schema_version: str
    source_set_id: str
    scope: PromotionSourceScopeV2
    manifests: tuple[ResolvedPromotionSourceManifestV2, ...]

    def __post_init__(self) -> None:
        if self.schema_version != PROMOTION_COMPILATION_SCHEMA_VERSION:
            raise PromotionCompilationError("unsupported source-set schema_version")
        if type(self.scope) is not PromotionSourceScopeV2:
            raise PromotionCompilationError("source-set scope must use exact V2 enum")
        if type(self.manifests) is not tuple or not self.manifests:
            raise PromotionCompilationError("resolved source set cannot be empty")
        if any(type(value) is not ResolvedPromotionSourceManifestV2 for value in self.manifests):
            raise PromotionCompilationError("source set requires exact resolved manifests")
        for value in self.manifests:
            value.__post_init__()
            if value.scope is not self.scope:
                raise PromotionCompilationError("mixed test/production source scopes are forbidden")
        ids = tuple(value.manifest_id for value in self.manifests)
        if ids != tuple(sorted(ids)) or len(ids) != len(set(ids)):
            raise PromotionCompilationError("source manifests must be unique and sorted")
        if self.source_set_id != "promotion-source-set-" + canonical_hash(
            tuple((value.manifest_id, value.resolution_hash) for value in self.manifests)
        ):
            raise PromotionCompilationError("source_set_id is not content-derived")

    @property
    def resolution_set_hash(self) -> str:
        return canonical_hash(self.to_data(include_hash=False))

    def to_data(self, *, include_hash: bool = True) -> dict[str, Any]:
        data = {
            "schema_version": self.schema_version,
            "source_set_id": self.source_set_id,
            "scope": self.scope.value,
            "manifests": [
                {
                    "manifest_id": value.manifest_id,
                    "manifest_hash": value.manifest_hash,
                    "resolution_hash": value.resolution_hash,
                    "license_hash": value.license.license_hash,
                    "artifact_hashes": [item.artifact_hash for item in value.artifacts],
                    "record_hashes": [item.canonical_record_hash for item in value.records],
                }
                for value in self.manifests
            ],
        }
        return {**data, "resolution_set_hash": self.resolution_set_hash} if include_hash else data

    def to_json(self) -> str:
        return canonical_json(self.to_data())

    def manifest(self, manifest_id: str) -> ResolvedPromotionSourceManifestV2:
        matches = tuple(value for value in self.manifests if value.manifest_id == manifest_id)
        if len(matches) != 1:
            raise PromotionCompilationError(f"unknown source manifest: {manifest_id}")
        return matches[0]

    def artifact(self, locator: PromotionArtifactLocatorV2) -> ResolvedArtifactV2:
        artifact = self.manifest(locator.source_manifest_id).artifact(locator.artifact_id)
        if artifact.role is not PromotionArtifactRoleV2.SOURCE_DATA:
            raise PromotionCompilationError("promotion bindings must reference source_data")
        return artifact


@dataclass(frozen=True, slots=True)
class ExternalHoldoutVerificationV2:
    """Content identity for both holdout novelty and engine re-execution."""

    schema_version: str
    verification_id: str
    target_capability_set_hash: str
    external_scenario_corpus_hash: str
    construction_gap_report_hash: str
    supplemental_probe_hashes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != PROMOTION_COMPILATION_SCHEMA_VERSION:
            raise PromotionCompilationError(
                "unsupported external holdout verification schema_version"
            )
        if type(self.verification_id) is not str or not self.verification_id:
            raise PromotionCompilationError(
                "external holdout verification_id must be non-empty"
            )
        for value, label in (
            (self.target_capability_set_hash, "target capability set hash"),
            (self.external_scenario_corpus_hash, "external scenario corpus hash"),
            (self.construction_gap_report_hash, "construction gap report hash"),
        ):
            _sha256(value, label)
        if type(self.supplemental_probe_hashes) is not tuple or not self.supplemental_probe_hashes:
            raise PromotionCompilationError(
                "external holdout verification requires supplemental probes"
            )
        for value in self.supplemental_probe_hashes:
            _sha256(value, "supplemental probe hash")
        if (
            self.supplemental_probe_hashes
            != tuple(sorted(self.supplemental_probe_hashes))
            or len(self.supplemental_probe_hashes)
            != len(set(self.supplemental_probe_hashes))
        ):
            raise PromotionCompilationError(
                "supplemental probe hashes must be unique and sorted"
            )
        expected_id = "external-holdout-verification-" + canonical_hash(
            self._unsigned_data(include_id=False)
        )
        if self.verification_id != expected_id:
            raise PromotionCompilationError(
                "external holdout verification_id is not content-derived"
            )

    def _unsigned_data(self, *, include_id: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "schema_version": self.schema_version,
            "target_capability_set_hash": self.target_capability_set_hash,
            "external_scenario_corpus_hash": self.external_scenario_corpus_hash,
            "construction_gap_report_hash": self.construction_gap_report_hash,
            "supplemental_probe_hashes": list(self.supplemental_probe_hashes),
        }
        if include_id:
            data["verification_id"] = self.verification_id
        return data

    @property
    def report_hash(self) -> str:
        return canonical_hash(self._unsigned_data())

    def to_data(self) -> dict[str, Any]:
        return {**self._unsigned_data(), "verification_hash": self.report_hash}

    def to_json(self) -> str:
        return canonical_json(self.to_data())


@dataclass(frozen=True, slots=True)
class ProductionPromotionCompilationV2:
    schema_version: str
    source_set: ResolvedPromotionSourceSetV2
    regulation_bundle: RegulationDataBundle
    catalog: Any
    ruleset: Any
    mapping_evidence: Any
    development_construction_corpus: ConstructionSelectionCorpus
    external_holdout_construction_corpus: ConstructionSelectionCorpus
    target_pool_manifest: Any
    semantic_compilation: Any
    target_capability_set: TargetCapabilitySet
    execution_compilation: Any
    development_scenario_corpus: EngineScenarioCorpusV2
    external_holdout_scenario_corpus: EngineScenarioCorpusV2
    partition_manifest: ScenarioPartitionManifestV2
    engine_probe_report: EngineProbeReportV2
    grounding_resolution: Any
    external_holdout_gap_report: Any
    external_holdout_report: Any
    mechanic_coverage_matrix: Any
    timing_evidence: PromotionTimingEvidenceV2
    report: ProductionPromotionReportV2
    documents: Mapping[str, str]
    _request: ProductionPromotionRequestV2 = field(repr=False, compare=False)
    _replays: Mapping[str, ReplayRecord] = field(repr=False, compare=False)
    _validated_traces: Mapping[str, ValidatedGroundingTrace] = field(
        repr=False,
        compare=False,
    )

    @property
    def report_hash(self) -> str:
        return self.report.report_hash

    def _document_digests(self) -> tuple[PromotionDocumentDigestV2, ...]:
        self.report.__post_init__()
        if not isinstance(self.documents, Mapping) or not self.documents:
            raise PromotionCompilationError(
                "production compilation requires a portable document set"
            )
        expected_names = {
            value.file_name for value in self.report.documents
        } | {"promotion-report.json"}
        if set(self.documents) != expected_names:
            raise PromotionCompilationError(
                "production compilation document membership differs from report"
            )
        if self.documents.get("promotion-report.json") != self.report.to_json():
            raise PromotionCompilationError(
                "production compilation promotion-report document differs"
            )
        declared_digests = {
            value.file_name: value for value in self.report.documents
        }
        digests: list[PromotionDocumentDigestV2] = []
        for file_name, document in sorted(self.documents.items()):
            if (
                type(file_name) is not str
                or not file_name
                or "/" in file_name
                or "\\" in file_name
                or type(document) is not str
            ):
                raise PromotionCompilationError(
                    "production compilation documents must be named UTF-8 strings"
                )
            payload = document.encode("utf-8")
            digest = PromotionDocumentDigestV2(
                file_name=file_name,
                sha256=hashlib.sha256(payload).hexdigest(),
                byte_count=len(payload),
            )
            if file_name != "promotion-report.json":
                declared = declared_digests[file_name]
                if digest != declared:
                    raise PromotionCompilationError(
                        f"production compilation document digest differs: {file_name}"
                    )
            digests.append(digest)
        return tuple(digests)

    @property
    def document_set_hash(self) -> str:
        return canonical_hash(
            tuple(
                (value.file_name, value.sha256, value.byte_count)
                for value in self._document_digests()
            )
        )

    @property
    def compilation_id(self) -> str:
        return "production-promotion-compilation-" + canonical_hash(
            (
                self.report.report_hash,
                self.document_set_hash,
                self.source_set.resolution_set_hash,
            )
        )

    def unsigned_data(self) -> dict[str, Any]:
        self.report.__post_init__()
        component_hashes = {
            name: getattr(self.report, name)
            for name in PROMOTION_COMPONENT_HASH_FIELDS
        }
        for name, value in component_hashes.items():
            _sha256(value, name)
        return {
            "schema_version": self.schema_version,
            "compilation_id": self.compilation_id,
            "compiler_id": self.report.compiler_id,
            "attestation_scope": self.report.attestation_scope,
            "promotion_status": self.report.status,
            "champions_candidate": self.report.champions_candidate,
            "rank1_equivalence_status": self.report.rank1_equivalence_status,
            "regulation_id": self.report.regulation_id,
            "regulation_revision": self.report.regulation_revision,
            "source_set_id": self.source_set.source_set_id,
            "promotion_report_id": self.report.report_id,
            "promotion_report_hash": self.report.report_hash,
            "component_hashes": component_hashes,
            "documents": [
                value.to_data() for value in self._document_digests()
            ],
            "document_set_hash": self.document_set_hash,
        }

    @property
    def compilation_hash(self) -> str:
        return canonical_hash(self.unsigned_data())

    def to_data(self) -> dict[str, Any]:
        return {**self.unsigned_data(), "compilation_hash": self.compilation_hash}

    def to_json(self) -> str:
        return canonical_json(self.to_data())


def resolve_promotion_source_set_v2(
    request: ProductionPromotionRequestV2,
    *,
    record_references: tuple[PromotionRecordReferenceV2, ...] = (),
) -> ResolvedPromotionSourceSetV2:
    """Resolve every manifest and derive one non-mixed attestation scope."""

    if type(request) is not ProductionPromotionRequestV2:
        raise PromotionCompilationError("source-set resolution requires exact request")
    request.__post_init__()
    if type(record_references) is not tuple:
        raise PromotionCompilationError("record references must be an exact tuple")
    if any(
        type(value) is not PromotionRecordReferenceV2
        for value in record_references
    ):
        raise PromotionCompilationError("record references require exact V2 values")
    for value in record_references:
        value.__post_init__()
    merged_references: dict[str, PromotionRecordReferenceV2] = {}
    for value in (*request.grounding_evidence_refs, *record_references):
        previous = merged_references.get(value.evidence_ref_id)
        if previous is not None and previous != value:
            raise PromotionCompilationError(
                "conflicting record evidence_ref_id definitions"
            )
        merged_references[value.evidence_ref_id] = value
    record_references = tuple(
        merged_references[key] for key in sorted(merged_references)
    )
    root = request.artifact_root.resolve()
    resolved_once = tuple(
        resolve_promotion_source_manifest_v2(
            _contained_path(root, relative, "source manifest"),
            artifact_root=root,
        )
        for relative in request.manifest_relative_paths
    )
    by_id = {value.manifest_id: value for value in resolved_once}
    if len(by_id) != len(resolved_once):
        raise PromotionCompilationError("source manifest IDs must be unique")
    unknown = sorted(
        {value.source_manifest_id for value in record_references} - set(by_id)
    )
    if unknown:
        raise PromotionCompilationError(f"record references unknown manifests: {unknown}")
    references_by_manifest: dict[str, list[PromotionRecordReferenceV2]] = {
        value.manifest_id: [] for value in resolved_once
    }
    for reference in record_references:
        references_by_manifest[reference.source_manifest_id].append(reference)

    attached: list[ResolvedPromotionSourceManifestV2] = []
    for manifest in resolved_once:
        records: list[ResolvedPromotionRecordV2] = []
        for reference in sorted(
            references_by_manifest[manifest.manifest_id],
            key=lambda item: item.evidence_ref_id,
        ):
            artifact = manifest.artifact(reference.artifact_id)
            read_resolved_json_record(root, artifact, reference)
            records.append(
                ResolvedPromotionRecordV2(
                    reference=reference,
                    canonical_record_hash=reference.record_sha256,
                )
            )
        attached.append(replace(manifest, records=tuple(records)))
    return _resolved_source_set_from_manifests(tuple(attached))


def _attach_record_references_to_source_set(
    request: ProductionPromotionRequestV2,
    source_set: ResolvedPromotionSourceSetV2,
    record_references: tuple[PromotionRecordReferenceV2, ...],
) -> ResolvedPromotionSourceSetV2:
    """Attach verified JSON records without re-reading source manifests.

    Compilation must use one manifest/artifact resolution snapshot.  Mapping
    and construction references become known only after bound artifacts are
    parsed, so they are verified against that original snapshot rather than by
    resolving mutable manifests a second time.
    """

    if type(request) is not ProductionPromotionRequestV2:
        raise PromotionCompilationError("record attachment requires exact request")
    if type(source_set) is not ResolvedPromotionSourceSetV2:
        raise PromotionCompilationError("record attachment requires exact source set")
    if type(record_references) is not tuple or any(
        type(value) is not PromotionRecordReferenceV2
        for value in record_references
    ):
        raise PromotionCompilationError("record attachment requires exact V2 references")
    request.__post_init__()
    source_set.__post_init__()
    merged: dict[str, PromotionRecordReferenceV2] = {
        record.reference.evidence_ref_id: record.reference
        for manifest in source_set.manifests
        for record in manifest.records
    }
    for reference in record_references:
        reference.__post_init__()
        previous = merged.get(reference.evidence_ref_id)
        if previous is not None and previous != reference:
            raise PromotionCompilationError(
                "conflicting record evidence_ref_id definitions"
            )
        merged[reference.evidence_ref_id] = reference
    by_id = {value.manifest_id: value for value in source_set.manifests}
    unknown = sorted(
        {value.source_manifest_id for value in merged.values()} - set(by_id)
    )
    if unknown:
        raise PromotionCompilationError(
            f"record references unknown manifests: {unknown}"
        )
    root = request.artifact_root.resolve()
    references_by_manifest: dict[str, list[PromotionRecordReferenceV2]] = {
        value.manifest_id: [] for value in source_set.manifests
    }
    for reference in merged.values():
        references_by_manifest[reference.source_manifest_id].append(reference)
    attached: list[ResolvedPromotionSourceManifestV2] = []
    for manifest in source_set.manifests:
        records: list[ResolvedPromotionRecordV2] = []
        for reference in sorted(
            references_by_manifest[manifest.manifest_id],
            key=lambda item: item.evidence_ref_id,
        ):
            artifact = manifest.artifact(reference.artifact_id)
            read_resolved_json_record(root, artifact, reference)
            records.append(
                ResolvedPromotionRecordV2(
                    reference=reference,
                    canonical_record_hash=reference.record_sha256,
                )
            )
        attached.append(replace(manifest, records=tuple(records)))
    return _resolved_source_set_from_manifests(tuple(attached))


def _resolved_source_set_from_manifests(
    manifests: tuple[ResolvedPromotionSourceManifestV2, ...],
) -> ResolvedPromotionSourceSetV2:
    if type(manifests) is not tuple or not manifests or any(
        type(value) is not ResolvedPromotionSourceManifestV2
        for value in manifests
    ):
        raise PromotionCompilationError(
            "source set requires exact non-empty resolved manifests"
        )
    for manifest in manifests:
        manifest.__post_init__()
    manifests = tuple(sorted(manifests, key=lambda value: value.manifest_id))
    scopes = {value.scope for value in manifests}
    if len(scopes) != 1:
        raise PromotionCompilationError("mixed source scopes are forbidden")
    scope = next(iter(scopes))
    source_set_id = "promotion-source-set-" + canonical_hash(
        tuple((value.manifest_id, value.resolution_hash) for value in manifests)
    )
    return ResolvedPromotionSourceSetV2(
        schema_version=PROMOTION_COMPILATION_SCHEMA_VERSION,
        source_set_id=source_set_id,
        scope=scope,
        manifests=manifests,
    )


def compile_production_promotion_v2(
    request: ProductionPromotionRequestV2,
    *,
    development_scenario_corpus: EngineScenarioCorpusV2,
    external_holdout_scenario_corpus: EngineScenarioCorpusV2,
    replays: Mapping[str, ReplayRecord],
    validated_traces: Mapping[str, ValidatedGroundingTrace] | None = None,
) -> ProductionPromotionCompilationV2:
    """Compile a positive engineering candidate from resolver-verified bytes.

    Production sources deliberately remain unavailable through the V2 API.
    SIM-02C V3 performs external trust verification before entering the shared
    compilation core with a module-private capability.
    """

    return _compile_production_promotion_v2_core(
        request,
        development_scenario_corpus=development_scenario_corpus,
        external_holdout_scenario_corpus=external_holdout_scenario_corpus,
        replays=replays,
        validated_traces=validated_traces,
        _production_trust_capability=None,
    )


def _compile_production_promotion_v2_core(
    request: ProductionPromotionRequestV2,
    *,
    development_scenario_corpus: EngineScenarioCorpusV2,
    external_holdout_scenario_corpus: EngineScenarioCorpusV2,
    replays: Mapping[str, ReplayRecord],
    validated_traces: Mapping[str, ValidatedGroundingTrace] | None = None,
    _production_trust_capability: object | None,
) -> ProductionPromotionCompilationV2:
    """Shared V2 substance compiler; production entry is module-private."""

    if type(request) is not ProductionPromotionRequestV2:
        raise PromotionCompilationError("promotion compilation requires exact request")
    if type(development_scenario_corpus) is not EngineScenarioCorpusV2:
        raise PromotionCompilationError("development scenarios require exact V2 corpus")
    if type(external_holdout_scenario_corpus) is not EngineScenarioCorpusV2:
        raise PromotionCompilationError("holdout scenarios require exact V2 corpus")
    if type(replays) is not dict or any(type(value) is not ReplayRecord for value in replays.values()):
        raise PromotionCompilationError("promotion Replay set requires an exact dict of ReplayRecord")
    trace_map = _validated_trace_map(validated_traces)
    request.__post_init__()
    development_scenario_corpus.__post_init__()
    external_holdout_scenario_corpus.__post_init__()

    initial_sources = resolve_promotion_source_set_v2(request)
    bound_bytes = {
        name: _bound_bytes(request, initial_sources, locator, name)
        for name, locator in _binding_items(request.artifacts)
    }
    with TemporaryDirectory(prefix="champions-promotion-v2-") as directory:
        root = Path(directory)
        paths = {}
        for name, payload in bound_bytes.items():
            _strict_json(payload, name)
            path = root / f"{name}.json"
            path.write_bytes(payload)
            paths[name] = path
        regulation = load_regulation_snapshot(paths["regulation"])
        target_pool = load_target_pool(paths["target_pool"])
        catalog = load_catalog(paths["catalog"])
        ruleset = load_ruleset(paths["ruleset"])
        mapping = load_mapping_evidence_set(paths["mapping_evidence"])
        development_construction = load_construction_selection_corpus(
            paths["development_construction_corpus"]
        )
        external_holdout_construction = load_construction_selection_corpus(
            paths["external_holdout_construction_corpus"]
        )

    if regulation.regulation_id != target_pool.regulation_id or regulation.revision != target_pool.regulation_revision:
        raise PromotionCompilationError("Regulation and TargetPool identities differ")
    if catalog.engine_semantics_version != ruleset.engine_semantics_version:
        raise PromotionCompilationError("Catalog and RuleSet semantics differ")
    _validate_scope(
        regulation,
        initial_sources,
        _production_trust_capability=_production_trust_capability,
    )
    _validate_declared_source_ids(
        initial_sources,
        regulation.source_manifest_ids,
        target_pool.source_manifest_ids,
        (catalog.source_manifest_id,),
        ruleset.source_manifest_ids,
        mapping.source_manifest_ids,
        development_construction.source_manifest_ids,
        external_holdout_construction.source_manifest_ids,
    )
    _validate_construction_corpus(development_construction, "development")
    _validate_construction_corpus(external_holdout_construction, "external_holdout")

    references = _collect_record_references(
        mapping.evidence_refs,
        development_construction.evidence_refs,
        external_holdout_construction.evidence_refs,
        request.grounding_evidence_refs,
    )
    sources = _attach_record_references_to_source_set(
        request,
        initial_sources,
        references,
    )
    _validate_scope(
        regulation,
        sources,
        _production_trust_capability=_production_trust_capability,
    )
    record_values = _resolved_record_values(request, sources, references)
    _validate_mapping_evidence(mapping, record_values)
    _validate_corpus_evidence(development_construction, record_values)
    _validate_corpus_evidence(external_holdout_construction, record_values)

    bundle = RegulationDataBundle(regulation, target_pool, ())
    target_manifest = build_target_pool_manifest(
        bundle, catalog, ruleset, mapping, development_construction
    )
    if target_manifest.blockers or target_manifest.restricted_source_manifest_ids:
        raise PromotionCompilationError(
            "TargetPool promotion blockers: " + ",".join(target_manifest.blockers)
        )
    semantic = compile_effect_semantic_registry(
        catalog, ruleset, tuple(sorted(regulation.required_mechanics))
    )
    if semantic.unsupported_selectors:
        raise PromotionCompilationError("Catalog contains unsupported semantic selectors")
    capability_set = build_target_capability_set(
        target_manifest, catalog, ruleset, semantic.registry, development_construction
    )
    if not capability_set.denominator_final or not capability_set.capabilities:
        raise PromotionCompilationError("TargetCapabilitySet denominator is not final/non-empty")
    execution = compile_execution_registry(
        capability_set=capability_set,
        semantic_compilation=semantic,
        catalog=catalog,
        ruleset=ruleset,
    )
    if execution.gaps:
        raise PromotionCompilationError("TargetCapabilitySet has execution gaps")

    _validate_bound_text(
        bound_bytes["development_scenario_corpus"],
        development_scenario_corpus.to_json(),
        "development scenario corpus",
    )
    _validate_bound_text(
        bound_bytes["external_holdout_scenario_corpus"],
        external_holdout_scenario_corpus.to_json(),
        "external holdout scenario corpus",
    )
    if (
        development_scenario_corpus.target_capability_set_hash
        != capability_set.capability_set_hash
        or external_holdout_scenario_corpus.target_capability_set_hash
        != capability_set.capability_set_hash
    ):
        raise PromotionCompilationError("scenario corpus capability denominator differs")
    scenario_ids = {
        value.scenario_id
        for value in (
            *development_scenario_corpus.scenarios,
            *external_holdout_scenario_corpus.scenarios,
        )
    }
    if set(replays) != scenario_ids:
        raise PromotionCompilationError("Replay map differs from all scenario IDs")
    replay_bindings = {value.scenario_id: value.artifact for value in request.replay_artifacts}
    if set(replay_bindings) != scenario_ids:
        raise PromotionCompilationError("Replay artifact bindings differ from scenarios")
    _validate_scenario_source_lineage(
        request=request,
        sources=sources,
        development_scenarios=development_scenario_corpus,
        external_holdout_scenarios=external_holdout_scenario_corpus,
        development_construction=development_construction,
        external_holdout_construction=external_holdout_construction,
        replay_bindings=replay_bindings,
    )
    partition = build_scenario_partition_manifest_v2(
        development=development_scenario_corpus,
        external_holdout=external_holdout_scenario_corpus,
    )
    for scenario_id in sorted(scenario_ids):
        payload = _bound_bytes(request, sources, replay_bindings[scenario_id], f"Replay {scenario_id}")
        _strict_json(payload, f"Replay {scenario_id}")
        _validate_bound_text(payload, replays[scenario_id].to_json(), f"Replay {scenario_id}")

    engine = BattleEngine(catalog, ruleset)
    development_replays = {
        value.scenario_id: replays[value.scenario_id]
        for value in development_scenario_corpus.scenarios
    }
    probe_report_v2 = build_engine_probe_report_v2(
        engine=engine,
        capability_set=capability_set,
        development_corpus=development_scenario_corpus,
        replays=development_replays,
    )
    supplemental_probes = tuple(
        sorted(
            (
                verify_engine_probe_v2(
                    engine=engine,
                    capability_set=capability_set,
                    scenario=scenario,
                    replay=replays[scenario.scenario_id],
                    probe_role="supplemental",
                )
                for scenario in external_holdout_scenario_corpus.scenarios
            ),
            key=lambda value: value.probe_id,
        )
    )
    holdout_report = evaluate_external_holdout(
        capability_set, external_holdout_construction
    )
    if not holdout_report.holdout_clean:
        raise PromotionCompilationError("external holdout contains novel or leaked evidence")
    supplemental_probe_hashes = tuple(
        sorted(value.probe_hash for value in supplemental_probes)
    )
    external_verification_data = {
        "schema_version": PROMOTION_COMPILATION_SCHEMA_VERSION,
        "target_capability_set_hash": capability_set.capability_set_hash,
        "external_scenario_corpus_hash": external_holdout_scenario_corpus.corpus_hash,
        "construction_gap_report_hash": holdout_report.report_hash,
        "supplemental_probe_hashes": list(supplemental_probe_hashes),
    }
    external_verification = ExternalHoldoutVerificationV2(
        schema_version=PROMOTION_COMPILATION_SCHEMA_VERSION,
        verification_id=(
            "external-holdout-verification-"
            + canonical_hash(external_verification_data)
        ),
        target_capability_set_hash=capability_set.capability_set_hash,
        external_scenario_corpus_hash=external_holdout_scenario_corpus.corpus_hash,
        construction_gap_report_hash=holdout_report.report_hash,
        supplemental_probe_hashes=supplemental_probe_hashes,
    )

    with TemporaryDirectory(prefix="champions-grounding-v2-") as directory:
        grounding_path = Path(directory) / "grounding.json"
        grounding_path.write_bytes(bound_bytes["grounding_assertions"])
        raw_grounding = load_grounding_assertion_set(grounding_path)
    _validate_declared_source_ids(sources, raw_grounding.source_manifest_ids)
    grounding_records = _validate_grounding_evidence(
        raw_grounding,
        record_values,
        references=references,
    )
    _validate_grounding_scenario_bindings(
        raw_grounding,
        capability_set,
        development_scenario_corpus,
        grounding_records,
        ruleset_id=str(ruleset.ruleset_id),
    )
    grounding = resolve_grounding_assertions(
        raw_grounding,
        capability_set,
        validated_traces=trace_map,
        evidence_resolver=lambda value: value in record_values,
    )
    required_grounding_ids = {
        value.requirement_id for value in capability_set.grounding_requirements
    }
    passed_grounding_ids = {
        requirement_id
        for result in grounding.results
        if result.verdict is ResolvedAssertionVerdict.PASS
        for requirement_id in result.requirement_ids
    }
    if passed_grounding_ids != required_grounding_ids or not required_grounding_ids:
        raise PromotionCompilationError("grounding requirements are not completely verified")

    primary = {
        value.capability_id: value
        for value in probe_report_v2.probes
        if value.probe_role == "primary"
    }
    specs = tuple(
        ProbeSpec(f"matrix-probe-{index}", capability.capability_id, "supported")
        for index, capability in enumerate(capability_set.capabilities)
    )
    executors = {
        spec.probe_id: (
            lambda replay_hash=primary[spec.capability_id].replay_hash: ProbeExecution(
                "success", True, replay_hash
            )
        )
        for spec in specs
    }
    matrix_probe_report = run_capability_probes(capability_set, specs, executors)
    matrix = build_mechanic_coverage_matrix(
        matrix_id=f"mechanic-coverage-v2:{regulation.regulation_id}:{regulation.revision}",
        capability_set=capability_set,
        execution_registry=execution.registry,
        probe_report=matrix_probe_report,
        grounding_assertions=grounding,
        holdout_report=holdout_report,
    )
    if not matrix.candidate_ready or matrix.silent_fallback_count != 0:
        raise PromotionCompilationError("mechanic coverage matrix is not candidate-ready")

    timing = _timing_evidence(bound_bytes["timing_evidence"])
    if timing.lead_time_seconds > 48 * 60 * 60:
        raise PromotionCompilationError("promotion decision exceeds 48 hours")

    grounding_hash = canonical_hash(grounding)
    base_documents = {
        "artifact-bindings.json": request.artifacts.to_json(),
        "development-scenario-corpus.json": development_scenario_corpus.to_json(),
        "engine-probe-report.json": probe_report_v2.to_json(),
        "execution-compilation.json": canonical_json(execution),
        "external-holdout-gap-report.json": holdout_report.to_json(),
        "external-holdout-verification.json": external_verification.to_json(),
        "external-holdout-scenario-corpus.json": external_holdout_scenario_corpus.to_json(),
        "grounding-resolution.json": canonical_json(grounding),
        "mechanic-coverage-matrix.json": matrix.to_json(),
        "scenario-partition.json": partition.to_json(),
        "semantic-compilation.json": canonical_json(semantic),
        "source-resolution-set.json": sources.to_json(),
        "target-capability-set.json": capability_set.to_json(),
        "target-pool-manifest.json": target_manifest.to_json(),
        "timing-evidence.json": canonical_json(timing.to_data()),
    }
    document_digests = tuple(
        PromotionDocumentDigestV2(
            name,
            hashlib.sha256(document.encode("utf-8")).hexdigest(),
            len(document.encode("utf-8")),
        )
        for name, document in sorted(base_documents.items())
    )
    declared_capability_ids = {value.capability_id for value in capability_set.capabilities}
    covered_capability_ids = {value.capability_id for value in probe_report_v2.probes}
    mapping_numerator = sum(
        value.resolution_status is MappingResolutionStatus.RESOLVED
        and value.verification_status is VerificationStatus.VERIFIED
        for value in mapping.entries
    )
    rates = _exact_rates(
        mapping_numerator=mapping_numerator,
        mapping_denominator=len(target_pool.members),
        covered_capability_count=len(covered_capability_ids),
        declared_capability_count=len(declared_capability_ids),
        passed_grounding_count=len(passed_grounding_ids),
        required_grounding_count=len(required_grounding_ids),
        probe_pass_count=probe_report_v2.verified_pass_probe_count,
        required_probe_count=probe_report_v2.required_probe_count,
        target_pool_hash=target_pool.snapshot_hash,
        target_capability_set_hash=capability_set.capability_set_hash,
        partition_hash=partition.partition_hash,
        grounding_hash=grounding_hash,
        engine_probe_hash=probe_report_v2.report_hash,
    )
    scope = sources.scope.value
    report_id = production_report_id_v2(
        attestation_scope=scope,
        source_resolution_set_hash=sources.resolution_set_hash,
        target_pool_hash=target_pool.snapshot_hash,
        target_capability_set_hash=capability_set.capability_set_hash,
        partition_manifest_hash=partition.partition_hash,
        engine_probe_report_hash=probe_report_v2.report_hash,
    )
    production = sources.scope is PromotionSourceScopeV2.PRODUCTION_CHAMPIONS
    report = ProductionPromotionReportV2(
        schema_version=PROMOTION_REPORT_SCHEMA_VERSION,
        report_id=report_id,
        compiler_id=PROMOTION_COMPILER_ID,
        attestation_scope=scope,
        status="production_candidate" if production else "engineering_candidate",
        promotion_gate_passed=True,
        champions_candidate=production,
        champions_fidelity_status="evidence_attested" if production else "not_attested",
        rank1_equivalence_status="unmeasured",
        regulation_id=regulation.regulation_id,
        regulation_revision=regulation.revision,
        source_resolution_set_hash=sources.resolution_set_hash,
        artifact_binding_hash=canonical_hash(
            (
                request.artifacts,
                request.replay_artifacts,
                request.grounding_evidence_refs,
            )
        ),
        regulation_hash=regulation.snapshot_hash,
        target_pool_hash=target_pool.snapshot_hash,
        catalog_hash=catalog.snapshot_hash,
        ruleset_hash=ruleset.snapshot_hash,
        mapping_evidence_hash=mapping.snapshot_hash,
        target_pool_manifest_hash=target_manifest.manifest_hash,
        semantic_compilation_hash=semantic.compilation_hash,
        target_capability_set_hash=capability_set.capability_set_hash,
        execution_compilation_hash=execution.compilation_hash,
        construction_corpus_hash=development_construction.snapshot_hash,
        scenario_corpus_hash=development_scenario_corpus.corpus_hash,
        external_holdout_scenario_corpus_hash=external_holdout_scenario_corpus.corpus_hash,
        partition_manifest_hash=partition.partition_hash,
        external_holdout_hash=external_verification.report_hash,
        grounding_resolution_hash=grounding_hash,
        engine_probe_report_hash=probe_report_v2.report_hash,
        mechanic_coverage_matrix_hash=matrix.matrix_hash,
        timing_evidence_hash=timing.timing_hash,
        timing_evidence=timing,
        verified_target_mapping_rate=rates[0],
        development_scenario_coverage_rate=rates[1],
        verified_grounding_conformance_rate=rates[2],
        engine_probe_pass_rate=rates[3],
        external_holdout_novel_gap_count=len(holdout_report.blocking_reasons),
        silent_fallback_count=probe_report_v2.silent_fallback_count,
        decision_lead_time_seconds=timing.lead_time_seconds,
        blockers=(),
        resume_conditions=(),
        documents=document_digests,
    )
    documents = dict(base_documents)
    documents["promotion-report.json"] = report.to_json()
    return ProductionPromotionCompilationV2(
        schema_version=PROMOTION_COMPILATION_SCHEMA_VERSION,
        source_set=sources,
        regulation_bundle=bundle,
        catalog=catalog,
        ruleset=ruleset,
        mapping_evidence=mapping,
        development_construction_corpus=development_construction,
        external_holdout_construction_corpus=external_holdout_construction,
        target_pool_manifest=target_manifest,
        semantic_compilation=semantic,
        target_capability_set=capability_set,
        execution_compilation=execution,
        development_scenario_corpus=development_scenario_corpus,
        external_holdout_scenario_corpus=external_holdout_scenario_corpus,
        partition_manifest=partition,
        engine_probe_report=probe_report_v2,
        grounding_resolution=grounding,
        external_holdout_gap_report=holdout_report,
        external_holdout_report=external_verification,
        mechanic_coverage_matrix=matrix,
        timing_evidence=timing,
        report=report,
        documents=documents,
        _request=request,
        _replays=dict(replays),
        _validated_traces=trace_map,
    )


def _compile_verified_production_promotion_v3_substance(
    request: ProductionPromotionRequestV2,
    *,
    trust_proof: _VerifiedProductionTrustProofV3,
    development_scenario_corpus: EngineScenarioCorpusV2,
    external_holdout_scenario_corpus: EngineScenarioCorpusV2,
    replays: Mapping[str, ReplayRecord],
    validated_traces: Mapping[str, ValidatedGroundingTrace] | None = None,
) -> ProductionPromotionCompilationV2:
    """Private entry used only after compiler_v3 verifies external trust."""

    if type(trust_proof) is not _VerifiedProductionTrustProofV3:
        raise PromotionCompilationError(
            "V3 production compilation requires an exact verified trust proof"
        )
    trust_proof.__post_init__()

    return _compile_production_promotion_v2_core(
        request,
        development_scenario_corpus=development_scenario_corpus,
        external_holdout_scenario_corpus=external_holdout_scenario_corpus,
        replays=replays,
        validated_traces=validated_traces,
        _production_trust_capability=_PRODUCTION_TRUST_CAPABILITY_V3,
    )


def validate_production_promotion_compilation_v2(
    compilation: ProductionPromotionCompilationV2,
) -> ProductionPromotionCompilationV2:
    """Re-read every source byte and compare a fully recomputed compilation."""

    if type(compilation) is not ProductionPromotionCompilationV2:
        raise PromotionCompilationError("validation requires exact V2 compilation")
    resolved = compile_production_promotion_v2(
        compilation._request,
        development_scenario_corpus=compilation.development_scenario_corpus,
        external_holdout_scenario_corpus=compilation.external_holdout_scenario_corpus,
        replays=dict(compilation._replays),
        validated_traces=dict(compilation._validated_traces),
    )
    if compilation != resolved:
        raise PromotionCompilationError("V2 compilation differs from recomputed substance")
    return resolved


def _binding_items(bindings: PromotionArtifactBindingsV2):
    return (
        ("regulation", bindings.regulation),
        ("target_pool", bindings.target_pool),
        ("catalog", bindings.catalog),
        ("ruleset", bindings.ruleset),
        ("mapping_evidence", bindings.mapping_evidence),
        ("development_construction_corpus", bindings.development_construction_corpus),
        ("external_holdout_construction_corpus", bindings.external_holdout_construction_corpus),
        ("grounding_assertions", bindings.grounding_assertions),
        ("development_scenario_corpus", bindings.development_scenario_corpus),
        ("external_holdout_scenario_corpus", bindings.external_holdout_scenario_corpus),
        ("timing_evidence", bindings.timing_evidence),
    )


def _validated_trace_map(
    values: Mapping[str, ValidatedGroundingTrace] | None,
) -> dict[str, ValidatedGroundingTrace]:
    if values is None:
        return {}
    if type(values) is not dict:
        raise PromotionCompilationError(
            "validated grounding traces require an exact dict"
        )
    result: dict[str, ValidatedGroundingTrace] = {}
    for trace_id in sorted(values):
        value = values[trace_id]
        if type(trace_id) is not str or not trace_id:
            raise PromotionCompilationError("validated trace ID must be non-empty")
        if type(value) is not ValidatedGroundingTrace:
            raise PromotionCompilationError(
                "validated traces require exact resolver-issued values"
            )
        if value.trace.trace_id != trace_id:
            raise PromotionCompilationError(
                "validated trace map key differs from trace identity"
            )
        result[trace_id] = value
    return result


def _bound_bytes(request, sources, locator, label) -> bytes:
    try:
        return read_resolved_artifact(request.artifact_root, sources.artifact(locator))
    except Exception as error:
        raise PromotionCompilationError(f"cannot resolve bound artifact: {label}") from error


def _collect_record_references(*groups) -> tuple[PromotionRecordReferenceV2, ...]:
    values: dict[str, PromotionRecordReferenceV2] = {}
    for group in groups:
        for value in group:
            converted = PromotionRecordReferenceV2(
                value.evidence_ref_id,
                value.source_manifest_id,
                value.artifact_id,
                value.json_pointer,
                value.record_sha256,
            )
            previous = values.get(converted.evidence_ref_id)
            if previous is not None and previous != converted:
                raise PromotionCompilationError("conflicting evidence_ref_id definitions")
            values[converted.evidence_ref_id] = converted
    if not values:
        raise PromotionCompilationError("promotion evidence references cannot be empty")
    return tuple(sorted(values.values(), key=lambda value: value.evidence_ref_id))


def _resolved_record_values(request, sources, references):
    result = {}
    for reference in references:
        artifact = sources.manifest(reference.source_manifest_id).artifact(reference.artifact_id)
        result[reference.evidence_ref_id] = read_resolved_json_record(
            request.artifact_root, artifact, reference
        )
    return result


def _validate_scenario_source_lineage(
    *,
    request,
    sources,
    development_scenarios,
    external_holdout_scenarios,
    development_construction,
    external_holdout_construction,
    replay_bindings,
) -> None:
    roles = (
        (
            "development",
            development_scenarios,
            development_construction,
            request.artifacts.development_scenario_corpus,
            request.artifacts.development_construction_corpus,
        ),
        (
            "external_holdout",
            external_holdout_scenarios,
            external_holdout_construction,
            request.artifacts.external_holdout_scenario_corpus,
            request.artifacts.external_holdout_construction_corpus,
        ),
    )
    artifact_hashes: dict[str, set[str]] = {}
    for role, scenarios, construction, scenario_locator, construction_locator in roles:
        hashes = {
            sources.artifact(scenario_locator).sha256,
            sources.artifact(construction_locator).sha256,
        }
        hashes.update(
            sources.artifact(
                PromotionArtifactLocatorV2(
                    value.source_manifest_id,
                    value.artifact_id,
                )
            ).sha256
            for value in construction.evidence_refs
        )
        for scenario in scenarios.scenarios:
            replay_locator = replay_bindings[scenario.scenario_id]
            expected_lineage = tuple(
                sorted(
                    {
                        scenario_locator.source_manifest_id,
                        replay_locator.source_manifest_id,
                        *construction.source_manifest_ids,
                    }
                )
            )
            if scenario.source_lineage_ids != expected_lineage:
                raise PromotionCompilationError(
                    f"{role} scenario source lineage differs from bound artifacts"
                )
            hashes.add(sources.artifact(replay_locator).sha256)
        artifact_hashes[role] = hashes
    overlap = tuple(
        sorted(
            artifact_hashes["development"]
            & artifact_hashes["external_holdout"]
        )
    )
    if overlap:
        raise PromotionCompilationError(
            "development/external holdout source_data artifact SHA overlap: "
            + ",".join(overlap)
        )


def _validate_mapping_evidence(mapping, records) -> None:
    refs = {value.evidence_ref_id: value for value in mapping.evidence_refs}
    declared_sources = set(mapping.source_manifest_ids)
    if any(value.source_manifest_id not in declared_sources for value in refs.values()):
        raise PromotionCompilationError(
            "mapping evidence source is absent from mapping source manifests"
        )
    for entry in mapping.entries:
        if (
            entry.resolution_status is not MappingResolutionStatus.RESOLVED
            or entry.verification_status is not VerificationStatus.VERIFIED
            or entry.catalog_pokemon_id is None
            or not entry.evidence_ref_ids
        ):
            raise PromotionCompilationError("mapping entry is not resolved and verified")
        matched = False
        for evidence_id in entry.evidence_ref_ids:
            if evidence_id not in refs or evidence_id not in records:
                raise PromotionCompilationError("mapping evidence reference is unresolved")
            record = records[evidence_id]
            if type(record) is dict and (
                record.get("target_key") == entry.target_key
                and record.get("catalog_pokemon_id") == entry.catalog_pokemon_id
                and record.get("resolution_status") == "resolved"
                and record.get("verification_status") == "verified"
            ):
                matched = True
        if not matched:
            raise PromotionCompilationError("mapping evidence record does not prove its entry")


def _validate_construction_corpus(corpus, expected_role) -> None:
    if corpus.corpus_role != expected_role or not corpus.records:
        raise PromotionCompilationError(f"{expected_role} construction corpus is empty/wrong role")
    for record in corpus.records:
        if (
            not record.source_complete
            or record.blockers
            or not record.evidence_ref_ids
            or any(value.status.value != "confirmed" for value in record.entities)
        ):
            raise PromotionCompilationError("construction record is incomplete or unresolved")


def _validate_corpus_evidence(corpus, records) -> None:
    declared = {value.evidence_ref_id for value in corpus.evidence_refs}
    declared_sources = set(corpus.source_manifest_ids)
    if any(
        value.source_manifest_id not in declared_sources
        for value in corpus.evidence_refs
    ):
        raise PromotionCompilationError(
            "construction evidence source is absent from corpus source manifests"
        )
    for record in corpus.records:
        if any(value not in declared or value not in records for value in record.evidence_ref_ids):
            raise PromotionCompilationError("construction evidence reference is unresolved")
        expected = to_canonical_data(record)
        if type(expected) is not dict:
            raise PromotionCompilationError(
                "construction record is not canonical object data"
            )
        required_fields = {
            key: expected[key]
            for key in (
                "record_id",
                "record_kind",
                "observed_at",
                "regulation_id",
                "joint_group_id",
                "target_key",
                "entities",
                "observed_capabilities",
                "source_complete",
                "evidence_ref_ids",
                "blockers",
            )
        }
        candidates = (records[value] for value in record.evidence_ref_ids)
        if not any(
            _record_contains_exact_substance(candidate, required_fields)
            for candidate in candidates
        ):
            raise PromotionCompilationError(
                "construction evidence record does not prove its observation"
            )


def _validate_grounding_evidence(
    raw,
    records,
    *,
    references,
) -> frozenset[str]:
    resolved_ids = frozenset(records)
    by_id = {value.evidence_ref_id: value for value in references}
    declared_sources = set(raw.source_manifest_ids)
    for assertion in raw.assertions:
        if assertion.claimed_verdict != "pass":
            raise PromotionCompilationError(
                "positive grounding assertion must claim pass"
            )
        if any(value not in resolved_ids for value in assertion.evidence_ref_ids):
            raise PromotionCompilationError("grounding evidence reference is unresolved")
        if any(
            value not in by_id
            or by_id[value].source_manifest_id not in declared_sources
            for value in assertion.evidence_ref_ids
        ):
            raise PromotionCompilationError(
                "grounding evidence source is absent from assertion source manifests"
            )
        expected = {
            "assertion_id": assertion.assertion_id,
            "requirement_ids": list(assertion.requirement_ids),
            "capability_ids": list(assertion.capability_ids),
            "evidence_kind": assertion.evidence_kind,
            "ruleset_id": assertion.ruleset_id,
            "ruleset_hash": assertion.ruleset_hash,
            "catalog_hash": assertion.catalog_hash,
            "initial_state_hash": assertion.initial_state_hash,
            "choice_sequence_hash": assertion.choice_sequence_hash,
            "expected_event_slice_hash": assertion.expected_event_slice_hash,
            "claimed_verdict": "pass",
        }
        if not any(
            _record_contains_exact_substance(records[value], expected)
            for value in assertion.evidence_ref_ids
        ):
            raise PromotionCompilationError(
                "grounding evidence record does not prove its assertion"
            )
    return resolved_ids


def _record_contains_exact_substance(record, expected: Mapping[str, Any]) -> bool:
    if type(record) is not dict or any(key not in record for key in expected):
        return False
    actual = {key: record[key] for key in expected}
    try:
        return canonical_json(actual) == canonical_json(dict(expected))
    except (TypeError, ValueError, UnicodeError):
        return False


def _validate_grounding_scenario_bindings(
    raw,
    capability_set,
    scenarios,
    evidence_ids,
    *,
    ruleset_id,
) -> None:
    required = {value.requirement_id for value in capability_set.grounding_requirements}
    covered = set()
    by_capability = {}
    for scenario in scenarios.scenarios:
        by_capability.setdefault(scenario.capability_id, []).append(scenario)
    if not raw.assertions:
        raise PromotionCompilationError("grounding assertion corpus is empty")
    for assertion in raw.assertions:
        if any(value not in evidence_ids for value in assertion.evidence_ref_ids):
            raise PromotionCompilationError("grounding evidence reference is unresolved")
        if assertion.ruleset_id != ruleset_id:
            raise PromotionCompilationError(
                "grounding assertion RuleSet identity differs"
            )
        if not set(assertion.requirement_ids) <= required:
            raise PromotionCompilationError("grounding assertion names unknown requirements")
        if assertion.expected_event_slice_hash is None:
            raise PromotionCompilationError(
                "positive grounding requires an exact witness event hash"
            )
        matched_capabilities: set[str] = set()
        for capability_id in assertion.capability_ids:
            candidates = [
                scenario
                for scenario in by_capability.get(capability_id, ())
                if scenario.initial_state_hash == assertion.initial_state_hash
                and scenario.choice_sequence_hash == assertion.choice_sequence_hash
                and scenario.witness_event_hash
                == assertion.expected_event_slice_hash
                and (
                    assertion.reference_replay_hash is None
                    or scenario.replay_hash == assertion.reference_replay_hash
                )
            ]
            if candidates:
                matched_capabilities.add(capability_id)
        if matched_capabilities != set(assertion.capability_ids):
            raise PromotionCompilationError("grounding assertion is not bound to a verified scenario")
        covered.update(assertion.requirement_ids)
    if covered != required:
        raise PromotionCompilationError("grounding assertions do not cover exact requirements")


def _validate_scope(
    regulation,
    sources,
    *,
    _production_trust_capability: object | None,
) -> None:
    if sources.scope is PromotionSourceScopeV2.TEST_AUTHORITATIVE:
        if regulation.status != "synthetic" or regulation.verification_status != "synthetic_rehearsal":
            raise PromotionCompilationError("test source scope requires synthetic Regulation")
        return
    if regulation.status != "current" or regulation.verification_status != "verified":
        raise PromotionCompilationError("production source scope requires current verified Regulation")
    if _production_trust_capability is _PRODUCTION_TRUST_CAPABILITY_V3:
        return
    raise PromotionCompilationError(
        "production promotion requires an artifact-root-external trust anchor "
        "and fixed enrollment; the public V2 production entry is disabled by design"
    )


def _validate_declared_source_ids(sources, *groups) -> None:
    declared = {value.manifest_id for value in sources.manifests}
    referenced = {value for group in groups for value in group}
    unknown = sorted(referenced - declared)
    if unknown:
        raise PromotionCompilationError(f"component references unknown source manifests: {unknown}")


def _timing_evidence(payload: bytes) -> PromotionTimingEvidenceV2:
    raw = _strict_json(payload, "timing evidence")
    if type(raw) is not dict or set(raw) != {
        "schema_version", "timing_id", "measurement_status", "t0", "t_decision",
        "compute_seconds", "manual_seconds", "external_wait_seconds",
    }:
        raise PromotionCompilationError("timing evidence fields differ")
    if raw["schema_version"] != PROMOTION_COMPILATION_SCHEMA_VERSION:
        raise PromotionCompilationError("unsupported timing evidence schema")
    try:
        return PromotionTimingEvidenceV2(
            timing_id=raw["timing_id"],
            measurement_status=raw["measurement_status"],
            t0=raw["t0"],
            t_decision=raw["t_decision"],
            compute_seconds=raw["compute_seconds"],
            manual_seconds=raw["manual_seconds"],
            external_wait_seconds=raw["external_wait_seconds"],
        )
    except (TypeError, ValueError) as error:
        raise PromotionCompilationError("invalid timing evidence") from error


def _exact_rates(**values):
    specs = (
        (
            "verified_target_mapping_rate",
            values["mapping_numerator"], values["mapping_denominator"],
            (values["target_pool_hash"],),
        ),
        (
            "development_scenario_coverage_rate",
            values["covered_capability_count"], values["declared_capability_count"],
            (values["target_capability_set_hash"], values["partition_hash"]),
        ),
        (
            "verified_grounding_conformance_rate",
            values["passed_grounding_count"], values["required_grounding_count"],
            (values["target_capability_set_hash"], values["partition_hash"], values["grounding_hash"]),
        ),
        (
            "engine_probe_pass_rate",
            values["probe_pass_count"], values["required_probe_count"],
            (values["target_capability_set_hash"], values["partition_hash"], values["engine_probe_hash"]),
        ),
    )
    result = []
    for metric, numerator, denominator, hashes in specs:
        result.append(
            ExactRateV2(
                metric,
                numerator,
                denominator,
                numerator * 1_000_000 // denominator,
                exact_rate_binding_hash_v2(metric, numerator, denominator, *hashes),
            )
        )
    return tuple(result)


def _strict_json(payload: bytes, label: str):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise PromotionCompilationError(f"duplicate JSON key in {label}: {key}")
            result[key] = value
        return result

    def constant(value):
        raise PromotionCompilationError(f"non-finite JSON number in {label}: {value}")

    def finite(value):
        parsed = float(value)
        if not math.isfinite(parsed):
            raise PromotionCompilationError(f"non-finite JSON number in {label}: {value}")
        return parsed

    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=constant,
            parse_float=finite,
        )
    except PromotionCompilationError:
        raise
    except (UnicodeDecodeError, ValueError) as error:
        raise PromotionCompilationError(f"invalid UTF-8 JSON: {label}") from error


def _validate_bound_text(payload: bytes, expected: str, label: str) -> None:
    try:
        actual = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise PromotionCompilationError(f"{label} is not UTF-8") from error
    if actual != expected:
        raise PromotionCompilationError(f"{label} bytes differ from exact runtime object")


def _relative_path(value: str, label: str) -> None:
    if type(value) is not str:
        raise PromotionCompilationError(f"{label} must be a string")
    path = PurePosixPath(value)
    if (
        not value
        or value.startswith("/")
        or "\\" in value
        or ":" in value
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.as_posix() != value
    ):
        raise PromotionCompilationError(f"{label} must be a normalized relative POSIX path")


def _sha256(value: str, label: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise PromotionCompilationError(f"{label} must be a lowercase SHA-256")


def _contained_path(root: Path, relative: str, label: str) -> Path:
    _relative_path(relative, label)
    try:
        path = root.joinpath(*PurePosixPath(relative).parts).resolve(strict=True)
        path.relative_to(root)
    except (OSError, RuntimeError, ValueError) as error:
        raise PromotionCompilationError(f"{label} escapes or is missing") from error
    if not path.is_file():
        raise PromotionCompilationError(f"{label} is not a regular file")
    return path


__all__ = [
    "ExternalHoldoutVerificationV2",
    "PROMOTION_COMPONENT_HASH_FIELDS",
    "PROMOTION_COMPILATION_SCHEMA_VERSION",
    "ProductionPromotionCompilationV2",
    "ProductionPromotionRequestV2",
    "PromotionArtifactBindingsV2",
    "PromotionArtifactLocatorV2",
    "PromotionCompilationError",
    "ReplayArtifactBindingV2",
    "ResolvedPromotionSourceSetV2",
    "compile_production_promotion_v2",
    "resolve_promotion_source_set_v2",
    "validate_production_promotion_compilation_v2",
]
