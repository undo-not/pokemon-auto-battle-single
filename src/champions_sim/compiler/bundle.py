"""One-command source-to-capability compilation for a regulation bundle.

The compiler treats a reasoned ``NO-GO`` as a successful operational result.
It only emits ``candidate`` when the existing capability, grounding, holdout,
license, and Catalog promotion gates all agree.  No rate or readiness flag is
accepted from a caller.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Mapping

from champions_sim.capabilities import (
    ConstructionSelectionCorpus,
    GroundingAssertionSet,
    TargetCapabilitySet,
    TargetPoolManifest,
    ValidatedGroundingAssertionSet,
    ValidatedProbeReport,
    build_mechanic_coverage_matrix,
    build_target_capability_set,
    build_target_pool_manifest,
    resolve_grounding_assertions,
)
from champions_sim.capabilities.models import MechanicCoverageMatrix
from champions_sim.catalog import CatalogSnapshot, RuleSetSnapshot, load_catalog, load_ruleset
from champions_sim.core import canonical_hash, canonical_json
from champions_sim.intake import (
    CatalogIntakeBundle,
    CatalogIntakePaths,
    CatalogIntakeProfile,
    build_catalog_intake,
    load_source_lock,
)
from champions_sim.regulations import RegulationDataBundle, load_regulation_bundle

from .bridge import CatalogBridgeProfile, compile_catalog_bridge
from .bridge_models import CatalogBridgeResult, CatalogCompilerError
from .execution import compile_execution_registry
from .models import CompiledProbePlan, ExecutionCompilation, SemanticCompilation
from .probes import compile_probe_plan, run_compiled_probe_plan
from .semantic import compile_effect_semantic_registry


COMPILER_SCHEMA_VERSION = "1.0.0"
COMPILER_ID = "source-to-capability-bundle-v1"


@dataclass(frozen=True, slots=True)
class SourceToCapabilityConfig:
    repository_root: Path
    legacy_root: Path
    regulation_path: Path
    target_pool_path: Path
    ruleset_path: Path
    manifest_dir: Path
    source_lock_path: Path
    intake_profile: CatalogIntakeProfile = CatalogIntakeProfile()
    bridge_profile: CatalogBridgeProfile = CatalogBridgeProfile()

    def __post_init__(self) -> None:
        repository = self.repository_root.resolve()
        if not repository.is_dir():
            raise CatalogCompilerError("repository root does not exist")
        if not self.legacy_root.resolve().is_dir():
            raise CatalogCompilerError("legacy root does not exist")
        for value, label in (
            (self.regulation_path, "regulation"),
            (self.target_pool_path, "target pool"),
            (self.ruleset_path, "ruleset"),
            (self.source_lock_path, "source lock"),
        ):
            if not value.resolve().is_file():
                raise CatalogCompilerError(f"{label} path does not exist")
        if not self.manifest_dir.resolve().is_dir():
            raise CatalogCompilerError("manifest directory does not exist")
        if (
            self.intake_profile.regulation_id != self.bridge_profile.regulation_id
            or self.intake_profile.regulation_revision
            != self.bridge_profile.regulation_revision
            or self.intake_profile.expected_target_count
            != self.bridge_profile.expected_target_count
        ):
            raise CatalogCompilerError("intake and bridge profiles disagree")


@dataclass(frozen=True, slots=True)
class ArtifactDigest:
    file_name: str
    sha256: str
    byte_count: int

    def to_data(self) -> dict[str, Any]:
        return {
            "file_name": self.file_name,
            "sha256": self.sha256,
            "byte_count": self.byte_count,
        }


@dataclass(frozen=True, slots=True)
class SourceToCapabilityCompilation:
    intake: CatalogIntakeBundle
    bridge: CatalogBridgeResult
    regulation_bundle: RegulationDataBundle
    catalog: CatalogSnapshot
    ruleset: RuleSetSnapshot
    semantic: SemanticCompilation
    target_pool_manifest: TargetPoolManifest
    capability_set: TargetCapabilitySet
    execution: ExecutionCompilation
    probe_plan: CompiledProbePlan
    probe_report: ValidatedProbeReport
    grounding: ValidatedGroundingAssertionSet
    matrix: MechanicCoverageMatrix
    report: Mapping[str, Any]
    documents: Mapping[str, str]

    @property
    def report_hash(self) -> str:
        return str(self.report["report_hash"])

    @property
    def candidate_ready(self) -> bool:
        return bool(self.report["candidate_ready"])


def compile_source_to_capability_bundle(
    config: SourceToCapabilityConfig,
) -> SourceToCapabilityCompilation:
    """Compile all locally available M-B inputs into candidate or ``NO-GO``.

    Structural drift raises an exception.  Missing evidence or unsupported
    semantics are normal, deterministic blockers and remain in the output.
    """

    repository = config.repository_root.resolve()
    legacy = config.legacy_root.resolve()
    target_relative = _repository_relative(config.target_pool_path, repository)
    expected_inventory = load_source_lock(config.source_lock_path)
    source_manifest_id = _source_lock_manifest_id(config.source_lock_path)
    bridge_profile = replace(
        config.bridge_profile,
        source_manifest_id=source_manifest_id,
    )
    intake = build_catalog_intake(
        repository_root=repository,
        legacy_root=legacy,
        paths=CatalogIntakePaths(target_pool=target_relative),
        profile=config.intake_profile,
        include_usage_details=True,
        expected_inventory=expected_inventory,
    )
    bridge = compile_catalog_bridge(
        intake,
        repository_root=repository,
        legacy_root=legacy,
        profile=bridge_profile,
    )
    catalog = _load_runtime_catalog(bridge)
    ruleset = load_ruleset(config.ruleset_path)
    if catalog.engine_semantics_version != ruleset.engine_semantics_version:
        raise CatalogCompilerError("runtime Catalog and RuleSet semantics differ")

    regulation_bundle = load_regulation_bundle(
        config.regulation_path,
        config.target_pool_path,
        manifest_dir=config.manifest_dir,
        repository_root=repository,
    )
    regulation = regulation_bundle.regulation
    if (
        regulation.regulation_id != bridge_profile.regulation_id
        or regulation.revision != bridge_profile.regulation_revision
    ):
        raise CatalogCompilerError("regulation identity differs from compiler profile")
    if regulation_bundle.target_pool.snapshot_hash != bridge.mapping_evidence.target_pool_hash:
        raise CatalogCompilerError("regulation target pool differs from Catalog intake")

    corpus = ConstructionSelectionCorpus(
        schema_version="1.0.0",
        corpus_id=(
            f"construction-corpus:{regulation.regulation_id}:"
            f"{regulation.revision}:empty-development"
        ),
        corpus_role="development",
        regulation_id=regulation.regulation_id,
        regulation_revision=regulation.revision,
        regulation_hash=regulation.snapshot_hash,
        capture_window_start=regulation.period.start_date,
        capture_window_end=regulation.period.end_at,
        records=(),
        evidence_refs=(),
        source_manifest_ids=(),
    )
    target_manifest = build_target_pool_manifest(
        regulation_bundle,
        catalog,
        ruleset,
        bridge.mapping_evidence,
        corpus,
    )
    restricted_ids = tuple(
        sorted(
            {
                *target_manifest.restricted_source_manifest_ids,
                *bridge.catalog_input.source_manifest_ids,
            }
        )
    )
    target_manifest = replace(
        target_manifest,
        restricted_source_manifest_ids=restricted_ids,
        blockers=tuple(
            sorted(
                {
                    *target_manifest.blockers,
                    *(f"restricted_source:{value}" for value in restricted_ids),
                    "construction_corpus_missing",
                    "catalog_not_emit_eligible",
                }
            )
        ),
    )

    semantic = compile_effect_semantic_registry(
        catalog,
        ruleset,
        tuple(sorted(regulation.required_mechanics)),
    )
    capability_set = build_target_capability_set(
        target_manifest,
        catalog,
        ruleset,
        semantic.registry,
        corpus,
    )
    execution = compile_execution_registry(
        capability_set=capability_set,
        semantic_compilation=semantic,
        catalog=catalog,
        ruleset=ruleset,
    )
    probe_plan = compile_probe_plan(capability_set, execution)
    probe_report = run_compiled_probe_plan(
        capability_set,
        execution,
        probe_plan,
        {},
    )
    raw_grounding = GroundingAssertionSet(
        schema_version="1.0.0",
        assertion_set_id=(
            f"grounding-assertions:{regulation.regulation_id}:"
            f"{regulation.revision}:none"
        ),
        target_capability_set_id=capability_set.capability_set_id,
        target_capability_set_hash=capability_set.capability_set_hash,
        assertions=(),
        source_manifest_ids=(),
    )
    grounding = resolve_grounding_assertions(
        raw_grounding,
        capability_set,
        validated_traces={},
        evidence_resolver=lambda _value: False,
    )
    matrix = build_mechanic_coverage_matrix(
        matrix_id=f"mechanic-coverage:{regulation.regulation_id}:{regulation.revision}",
        capability_set=capability_set,
        execution_registry=execution.registry,
        probe_report=probe_report,
        grounding_assertions=grounding,
        holdout_report=None,
    )

    base_documents = _base_documents(
        intake=intake,
        bridge=bridge,
        semantic=semantic,
        target_manifest=target_manifest,
        capability_set=capability_set,
        execution=execution,
        probe_plan=probe_plan,
        probe_report=probe_report,
        grounding=grounding,
        matrix=matrix,
    )
    artifact_digests = tuple(
        _artifact_digest(name, document)
        for name, document in sorted(base_documents.items())
    )
    report = _decision_report(
        bridge=bridge,
        regulation_bundle=regulation_bundle,
        semantic=semantic,
        target_manifest=target_manifest,
        capability_set=capability_set,
        execution=execution,
        probe_plan=probe_plan,
        probe_report=probe_report,
        grounding=grounding,
        matrix=matrix,
        artifacts=artifact_digests,
    )
    documents = dict(base_documents)
    documents["compiler-report.json"] = canonical_json(report)
    return SourceToCapabilityCompilation(
        intake=intake,
        bridge=bridge,
        regulation_bundle=regulation_bundle,
        catalog=catalog,
        ruleset=ruleset,
        semantic=semantic,
        target_pool_manifest=target_manifest,
        capability_set=capability_set,
        execution=execution,
        probe_plan=probe_plan,
        probe_report=probe_report,
        grounding=grounding,
        matrix=matrix,
        report=report,
        documents=documents,
    )


def write_compilation_documents(
    compilation: SourceToCapabilityCompilation,
    output_directory: Path | str,
) -> tuple[Path, ...]:
    """Atomically write the already-hashed local-only compilation documents."""

    _validate_compilation_documents(compilation)
    output = Path(output_directory).resolve()
    output.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, document in sorted(compilation.documents.items()):
        destination = output / name
        temporary = output / f".{name}.tmp"
        temporary.write_text(document, encoding="utf-8", newline="")
        temporary.replace(destination)
        written.append(destination)
    return tuple(written)


def _validate_compilation_documents(
    compilation: SourceToCapabilityCompilation,
) -> None:
    report = compilation.report
    report_hash = report.get("report_hash")
    unsigned = {key: value for key, value in report.items() if key != "report_hash"}
    if not isinstance(report_hash, str) or canonical_hash(unsigned) != report_hash:
        raise CatalogCompilerError("compiler report hash mismatch before write")

    expected_report = canonical_json(report)
    if compilation.documents.get("compiler-report.json") != expected_report:
        raise CatalogCompilerError("compiler report document differs before write")

    raw_artifacts = report.get("artifacts")
    if not isinstance(raw_artifacts, list):
        raise CatalogCompilerError("compiler report artifacts are invalid before write")
    expected_names = {"compiler-report.json"}
    for raw in raw_artifacts:
        if not isinstance(raw, dict):
            raise CatalogCompilerError("compiler artifact entry is invalid before write")
        name = raw.get("file_name")
        expected_hash = raw.get("sha256")
        expected_bytes = raw.get("byte_count")
        if not isinstance(name, str) or name == "compiler-report.json":
            raise CatalogCompilerError("compiler artifact name is invalid before write")
        document = compilation.documents.get(name)
        if not isinstance(document, str):
            raise CatalogCompilerError("compiler artifact document is missing before write")
        payload = document.encode("utf-8")
        if (
            not isinstance(expected_hash, str)
            or hashlib.sha256(payload).hexdigest() != expected_hash
            or not isinstance(expected_bytes, int)
            or len(payload) != expected_bytes
        ):
            raise CatalogCompilerError("compiler artifact digest mismatch before write")
        expected_names.add(name)
    if set(compilation.documents) != expected_names:
        raise CatalogCompilerError("compiler document set differs before write")


def _load_runtime_catalog(bridge: CatalogBridgeResult) -> CatalogSnapshot:
    with TemporaryDirectory(prefix="champions-catalog-") as directory:
        path = Path(directory) / "runtime-catalog.json"
        path.write_text(bridge.runtime_catalog_json(), encoding="utf-8", newline="")
        catalog = load_catalog(path)
    if catalog.snapshot_hash != bridge.mapping_evidence.catalog_hash:
        raise CatalogCompilerError("loaded runtime Catalog hash differs from mapping")
    return catalog


def _base_documents(
    *,
    intake: CatalogIntakeBundle,
    bridge: CatalogBridgeResult,
    semantic: SemanticCompilation,
    target_manifest: TargetPoolManifest,
    capability_set: TargetCapabilitySet,
    execution: ExecutionCompilation,
    probe_plan: CompiledProbePlan,
    probe_report: ValidatedProbeReport,
    grounding: ValidatedGroundingAssertionSet,
    matrix: MechanicCoverageMatrix,
) -> dict[str, str]:
    return {
        "catalog-intake.json": intake.to_json(),
        "runtime-catalog.json": bridge.runtime_catalog_json(),
        "mapping-evidence.json": bridge.mapping_evidence.to_json(),
        "production-catalog-input.json": bridge.catalog_input.to_json(),
        "semantic-compilation.json": canonical_json(semantic),
        "target-pool-manifest.json": target_manifest.to_json(),
        "target-capability-set.json": capability_set.to_json(),
        "execution-compilation.json": canonical_json(execution),
        "probe-plan.json": canonical_json(probe_plan),
        "probe-report.json": canonical_json(probe_report),
        "grounding-resolution.json": canonical_json(grounding),
        "mechanic-coverage-matrix.json": matrix.to_json(),
    }


def _decision_report(
    *,
    bridge: CatalogBridgeResult,
    regulation_bundle: RegulationDataBundle,
    semantic: SemanticCompilation,
    target_manifest: TargetPoolManifest,
    capability_set: TargetCapabilitySet,
    execution: ExecutionCompilation,
    probe_plan: CompiledProbePlan,
    probe_report: ValidatedProbeReport,
    grounding: ValidatedGroundingAssertionSet,
    matrix: MechanicCoverageMatrix,
    artifacts: tuple[ArtifactDigest, ...],
) -> dict[str, Any]:
    restricted = tuple(sorted(target_manifest.restricted_source_manifest_ids))
    reasons = set(matrix.blocking_reasons)
    reasons.update(target_manifest.blockers)
    if semantic.unsupported_selectors:
        reasons.add(
            f"semantic_unsupported_selector_count:{len(semantic.unsupported_selectors)}"
        )
    if execution.gaps:
        reasons.add(f"execution_gap_count:{len(execution.gaps)}")
    if not grounding.results:
        reasons.add("grounding_assertion_corpus_missing")
    if matrix.holdout_report_hash is None:
        reasons.add("external_holdout_missing")
    if not bridge.catalog_input.catalog_emit_eligible:
        reasons.add("catalog_not_emit_eligible")
    reasons.update(f"restricted_source:{value}" for value in restricted)
    candidate_ready = bool(
        matrix.candidate_ready
        and bridge.catalog_input.catalog_emit_eligible
        and not restricted
        and not reasons
    )
    mapping_counts = {
        "resolved": sum(
            value.resolution_status.value == "resolved"
            for value in bridge.mapping_evidence.entries
        ),
        "unresolved": sum(
            value.resolution_status.value == "unresolved"
            for value in bridge.mapping_evidence.entries
        ),
        "conflict": sum(
            value.resolution_status.value == "conflict"
            for value in bridge.mapping_evidence.entries
        ),
    }
    unsigned: dict[str, Any] = {
        "schema_version": COMPILER_SCHEMA_VERSION,
        "compiler_id": COMPILER_ID,
        "regulation_id": regulation_bundle.regulation.regulation_id,
        "regulation_revision": regulation_bundle.regulation.revision,
        "status": "candidate" if candidate_ready else "no_go",
        "operational_success": True,
        "candidate_ready": candidate_ready,
        "denominator_final": capability_set.denominator_final,
        "source_policy": {
            "license_status": "unverified",
            "access_scope": "local_only",
            "redistribution": "prohibited",
        },
        "counts": {
            "target_members": len(bridge.mapping_evidence.entries),
            "mapping_resolved": mapping_counts["resolved"],
            "mapping_unresolved": mapping_counts["unresolved"],
            "mapping_conflict": mapping_counts["conflict"],
            "catalog_species": len(bridge.runtime_catalog["species"]),
            "catalog_moves": len(bridge.runtime_catalog["moves"]),
            "catalog_abilities": len(bridge.runtime_catalog["abilities"]),
            "catalog_items": len(bridge.runtime_catalog["items"]),
            "semantic_selectors": len(semantic.inventory),
            "semantic_unsupported_selectors": len(semantic.unsupported_selectors),
            "target_capability_rows": len(capability_set.capabilities),
            "execution_gaps": len(execution.gaps),
            "grounding_assertions": len(grounding.results),
            "probe_explicit_unsupported": sum(
                value.explicit_unsupported for value in probe_report.results
            ),
            "probe_unexpected_errors": sum(
                value.observed_outcome == "unexpected_error"
                for value in probe_report.results
            ),
            "silent_fallbacks": probe_report.silent_fallback_count,
            "blocking_reasons": len(reasons),
        },
        "hashes": {
            "catalog_intake": bridge.catalog_input.intake_bundle_hash,
            "runtime_catalog": bridge.catalog_input.runtime_catalog_hash,
            "mapping_evidence": bridge.mapping_evidence.snapshot_hash,
            "production_catalog_input": bridge.catalog_input.input_hash,
            "semantic_compilation": semantic.compilation_hash,
            "target_pool_manifest": target_manifest.manifest_hash,
            "target_capability_set": capability_set.capability_set_hash,
            "execution_compilation": execution.compilation_hash,
            "probe_plan": probe_plan.plan_hash,
            "probe_report": probe_report.report_hash,
            "grounding_resolution": grounding.assertion_set_hash,
            "mechanic_coverage_matrix": matrix.matrix_hash,
        },
        "artifacts": [value.to_data() for value in artifacts],
        "blocking_reasons": sorted(reasons),
    }
    return {**unsigned, "report_hash": canonical_hash(unsigned)}


def _artifact_digest(name: str, document: str) -> ArtifactDigest:
    payload = document.encode("utf-8")
    return ArtifactDigest(name, hashlib.sha256(payload).hexdigest(), len(payload))


def _source_lock_manifest_id(path: Path) -> str:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CatalogCompilerError("source lock is not valid UTF-8 JSON") from error
    value = raw.get("manifest_id") if isinstance(raw, dict) else None
    if not isinstance(value, str) or not value:
        raise CatalogCompilerError("source lock manifest_id is missing")
    return value


def _repository_relative(path: Path, repository_root: Path) -> str:
    try:
        return path.resolve().relative_to(repository_root).as_posix()
    except ValueError as error:
        raise CatalogCompilerError("compiler input must be inside repository") from error
