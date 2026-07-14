"""Resolver-only seal for actionable Champions environment bundles.

An :class:`EnvironmentBundleIdentity` is descriptive data, not an
attestation.  In particular, callers must not be able to make an episode
actionable merely by setting both evidence statuses to ``verified`` and
supplying well-formed hashes.  This module validates the complete in-memory
source-to-capability compilation and issues a seal bound to the exact bundle
identity only when the compiler's independently derived promotion gates pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from typing import Any, Mapping

from champions_sim.compiler.bundle import (
    COMPILER_ID,
    COMPILER_SCHEMA_VERSION,
    SourceToCapabilityCompilation,
)
from champions_sim.core import (
    SIMULATOR_VERSION,
    BattlePhase,
    StatStages,
    canonical_hash,
    canonical_json,
)

from .models import (
    AI_ENV_ADAPTER_VERSION,
    EnvironmentBundleIdentity,
    EnvironmentScope,
    EvidenceStatus,
    SealedEnvironmentFixture,
)


CHAMPIONS_READINESS_SCHEMA_VERSION = "1.0.0"
# ``SourceToCapabilityCompilation`` is the frozen intake-diagnostic v1
# contract.  It deliberately cannot issue a Champions readiness seal.  A
# future promotion compiler must use a separate resolver/type rather than
# making v1 caller flags actionable.
_V1_POSITIVE_ISSUANCE_SUPPORTED = False


class ChampionsReadinessError(ValueError):
    """The compiler result cannot attest an actionable Champions bundle."""


@dataclass(frozen=True, slots=True)
class ResolvedChampionsReadiness:
    """Content-bound attestation that retains its revalidation substance.

    The complete compilation is deliberately kept in memory and revalidated
    whenever the seal is attached to an environment input.  A private module
    token would not be an authentication boundary in Python because callers
    can import it; proof therefore comes from recomputation, not construction.
    """

    schema_version: str
    bundle_identity_hash: str
    compiler_id: str
    compiler_report_hash: str
    artifact_manifest_hash: str
    capability_set_hash: str
    grounding_assertion_set_hash: str
    fixture_id: str
    fixture_hash: str
    fixture_binding_hash: str
    _compilation: SourceToCapabilityCompilation = field(repr=False, compare=False)

    def attestation_payload(self) -> dict[str, str]:
        return {
            "schema_version": self.schema_version,
            "bundle_identity_hash": self.bundle_identity_hash,
            "compiler_id": self.compiler_id,
            "compiler_report_hash": self.compiler_report_hash,
            "artifact_manifest_hash": self.artifact_manifest_hash,
            "capability_set_hash": self.capability_set_hash,
            "grounding_assertion_set_hash": self.grounding_assertion_set_hash,
            "fixture_id": self.fixture_id,
            "fixture_hash": self.fixture_hash,
            "fixture_binding_hash": self.fixture_binding_hash,
        }

    @property
    def seal_hash(self) -> str:
        return canonical_hash(self.attestation_payload())

    def validate_against(
        self,
        bundle: EnvironmentBundleIdentity,
        fixture: SealedEnvironmentFixture,
    ) -> None:
        resolved = resolve_champions_readiness(bundle, self._compilation, fixture)
        if self.attestation_payload() != resolved.attestation_payload():
            raise ChampionsReadinessError(
                "readiness attestation differs from recomputed compiler substance"
            )


def resolve_champions_readiness(
    bundle: EnvironmentBundleIdentity,
    compilation: SourceToCapabilityCompilation,
    fixture: SealedEnvironmentFixture,
) -> ResolvedChampionsReadiness:
    """Validate compiler substance and bind its candidate to ``bundle``.

    Validation is deliberately repeated here rather than trusting the report's
    self-declared status, counts, hashes, or ``candidate_ready`` flag.  A valid
    NO-GO compilation remains a successful compiler result, but cannot issue a
    readiness seal.
    """

    if type(compilation) is not SourceToCapabilityCompilation:
        raise ChampionsReadinessError(
            "readiness resolution requires a complete compiler compilation"
        )
    if type(bundle) is not EnvironmentBundleIdentity:
        raise ChampionsReadinessError(
            "readiness resolution requires the exact environment identity contract"
        )
    if type(fixture) is not SealedEnvironmentFixture:
        raise ChampionsReadinessError(
            "readiness resolution requires the exact sealed fixture contract"
        )
    # Resolver inputs may have been tampered after frozen-dataclass
    # construction, so their structural hashes and contracts are recomputed.
    try:
        bundle.__post_init__()
        fixture.__post_init__()
    except ValueError as error:
        raise ChampionsReadinessError(
            f"invalid readiness resolver input: {error}"
        ) from error

    report, artifacts = _validate_compilation_substance(compilation)
    _validate_bundle_binding(bundle, compilation)
    fixture_blockers = _candidate_fixture_blockers(fixture, compilation)
    compiler_ready = _derived_candidate_ready(compilation)
    if (
        not compiler_ready
        or fixture_blockers
        or not _V1_POSITIVE_ISSUANCE_SUPPORTED
    ):
        reasons = []
        if not compiler_ready:
            reasons.append("compiler_candidate_not_ready")
        if not _V1_POSITIVE_ISSUANCE_SUPPORTED:
            reasons.append("readiness_positive_path_not_implemented")
        reasons.extend(fixture_blockers)
        raise ChampionsReadinessError(
            "Champions environment is not ready: " + ";".join(reasons)
        )

    return ResolvedChampionsReadiness(
        schema_version=CHAMPIONS_READINESS_SCHEMA_VERSION,
        bundle_identity_hash=bundle.identity_hash,
        compiler_id=COMPILER_ID,
        compiler_report_hash=str(report["report_hash"]),
        artifact_manifest_hash=canonical_hash(artifacts),
        capability_set_hash=compilation.capability_set.capability_set_hash,
        grounding_assertion_set_hash=compilation.grounding.assertion_set_hash,
        fixture_id=fixture.fixture_id,
        fixture_hash=fixture.fixture_hash,
        fixture_binding_hash=fixture.fixture_binding_hash,
        _compilation=compilation,
    )


def _candidate_fixture_blockers(
    fixture: SealedEnvironmentFixture,
    compilation: SourceToCapabilityCompilation,
) -> tuple[str, ...]:
    """Resolve an exact initial state against the candidate target closure."""

    state = fixture.initial_state
    blockers: set[str] = set()
    if state.ruleset_id != compilation.ruleset.ruleset_id:
        blockers.add("fixture_ruleset_mismatch")
    if state.phase is not BattlePhase.TEAM_PREVIEW or state.turn != 0:
        blockers.add("fixture_not_initial_team_preview")
    if state.winner is not None or state.field_conditions:
        blockers.add("fixture_contains_runtime_outcome_or_field_state")
    if any(len(side.team) != compilation.ruleset.team_size for side in state.sides):
        blockers.add("fixture_team_size_mismatch")
    development_records = {
        (record.record_id, record.record_hash)
        for record in compilation.capability_set.development_records
    }
    fixture_record_refs = {
        (record.record_id, record.record_hash)
        for record in fixture.development_record_refs
    }
    if not fixture_record_refs:
        blockers.add("fixture_development_record_refs_missing")
    elif not fixture_record_refs <= development_records:
        blockers.add("fixture_development_record_ref_not_in_capability_set")

    zero_stages = StatStages()
    members = tuple(member for side in state.sides for member in side.team)
    if any(member.hp != member.stats.max_hp for member in members):
        blockers.add("fixture_pokemon_hp_not_full")
    if any(slot.pp != slot.max_pp for member in members for slot in member.moves):
        blockers.add("fixture_move_pp_not_full")
    if any(member.status_id is not None for member in members):
        blockers.add("fixture_contains_status")
    if any(member.stat_stages != zero_stages for member in members):
        blockers.add("fixture_contains_stat_stages")
    if any(member.volatile_statuses for member in members):
        blockers.add("fixture_contains_volatile_status")
    if any(member.consumed_item_id is not None for member in members):
        blockers.add("fixture_contains_consumed_item")
    if any(
        member.revealed_to_opponent
        or member.item_revealed_to_opponent
        or member.ability_revealed_to_opponent
        or any(slot.revealed_to_opponent for slot in member.moves)
        for member in members
    ):
        blockers.add("fixture_contains_reveal_state")
    if any(member.mega_evolved for member in members):
        blockers.add("fixture_contains_mega_evolved_state")

    verified_species = {
        str(entry.catalog_pokemon_id)
        for entry in compilation.target_pool_manifest.member_mappings
        if entry.catalog_pokemon_id is not None
        and entry.resolution_status.value == "resolved"
        and entry.verification_status.value == "verified"
    }
    fixture_species = {
        str(member.pokemon_id) for side in state.sides for member in side.team
    }
    if not fixture_species <= verified_species:
        blockers.add("fixture_species_not_in_verified_target_pool")

    reachable: dict[str, set[str]] = {"move": set(), "ability": set(), "item": set()}
    for reference in compilation.capability_set.entity_capability_refs:
        if reference.entity_kind in reachable:
            reachable[reference.entity_kind].add(reference.entity_id)
    fixture_moves = {
        str(slot.move_id)
        for side in state.sides
        for member in side.team
        for slot in member.moves
    }
    fixture_abilities = {
        str(member.ability_id)
        for side in state.sides
        for member in side.team
        if member.ability_id is not None
    }
    fixture_items = {
        str(member.item_id)
        for side in state.sides
        for member in side.team
        if member.item_id is not None
    }
    for kind, fixture_entities in (
        ("move", fixture_moves),
        ("ability", fixture_abilities),
        ("item", fixture_items),
    ):
        if not fixture_entities <= reachable[kind]:
            blockers.add(f"fixture_{kind}_outside_target_capability_closure")

    mega_targets = {
        str(member.mega_evolution_profile.target_pokemon_id)
        for side in state.sides
        for member in side.team
        if member.mega_evolution_profile is not None
    }
    if not mega_targets <= verified_species:
        blockers.add("fixture_mega_target_not_in_verified_target_pool")
    return tuple(sorted(blockers))


def _validate_compilation_substance(
    compilation: SourceToCapabilityCompilation,
) -> tuple[Mapping[str, Any], tuple[Mapping[str, Any], ...]]:
    _validate_compilation_cross_bindings(compilation)
    report = compilation.report
    if not isinstance(report, Mapping):
        raise ChampionsReadinessError("compiler report payload is missing")
    report_hash = report.get("report_hash")
    unsigned = {key: value for key, value in report.items() if key != "report_hash"}
    if not isinstance(report_hash, str) or canonical_hash(unsigned) != report_hash:
        raise ChampionsReadinessError("compiler report hash mismatch")
    if report.get("schema_version") != COMPILER_SCHEMA_VERSION:
        raise ChampionsReadinessError("unsupported compiler report schema")
    if report.get("compiler_id") != COMPILER_ID:
        raise ChampionsReadinessError("unsupported compiler identity")

    expected_documents = _expected_base_documents(compilation)
    documents = compilation.documents
    if not isinstance(documents, Mapping):
        raise ChampionsReadinessError("compiler document collection is missing")
    expected_names = {*expected_documents, "compiler-report.json"}
    if set(documents) != expected_names:
        raise ChampionsReadinessError("compiler artifact substance is incomplete")
    for name, expected in expected_documents.items():
        if documents.get(name) != expected:
            raise ChampionsReadinessError(f"compiler artifact payload mismatch: {name}")
    if documents.get("compiler-report.json") != canonical_json(report):
        raise ChampionsReadinessError("compiler report document mismatch")

    artifacts_raw = report.get("artifacts")
    if not isinstance(artifacts_raw, list):
        raise ChampionsReadinessError("compiler artifact manifest is missing")
    expected_artifacts = tuple(
        {
            "file_name": name,
            "sha256": hashlib.sha256(document.encode("utf-8")).hexdigest(),
            "byte_count": len(document.encode("utf-8")),
        }
        for name, document in sorted(expected_documents.items())
    )
    artifacts = tuple(artifacts_raw)
    if artifacts != expected_artifacts:
        raise ChampionsReadinessError("compiler artifact manifest mismatch")

    expected_hashes = {
        "catalog_intake": compilation.bridge.catalog_input.intake_bundle_hash,
        "runtime_catalog": compilation.bridge.catalog_input.runtime_catalog_hash,
        "mapping_evidence": compilation.bridge.mapping_evidence.snapshot_hash,
        "production_catalog_input": compilation.bridge.catalog_input.input_hash,
        "semantic_compilation": compilation.semantic.compilation_hash,
        "target_pool_manifest": compilation.target_pool_manifest.manifest_hash,
        "target_capability_set": compilation.capability_set.capability_set_hash,
        "execution_compilation": compilation.execution.compilation_hash,
        "probe_plan": compilation.probe_plan.plan_hash,
        "probe_report": compilation.probe_report.report_hash,
        "grounding_resolution": compilation.grounding.assertion_set_hash,
        "mechanic_coverage_matrix": compilation.matrix.matrix_hash,
    }
    if report.get("hashes") != expected_hashes:
        raise ChampionsReadinessError("compiler report hashes disagree with artifacts")

    regulation = compilation.regulation_bundle.regulation
    if (
        report.get("regulation_id") != regulation.regulation_id
        or report.get("regulation_revision") != regulation.revision
    ):
        raise ChampionsReadinessError("compiler report regulation identity mismatch")

    expected_reasons = _derived_blocking_reasons(compilation)
    expected_ready = _derived_candidate_ready(compilation, expected_reasons)
    if report.get("candidate_ready") is not expected_ready:
        raise ChampionsReadinessError(
            "compiler candidate_ready flag disagrees with validated gates"
        )
    if report.get("status") != ("candidate" if expected_ready else "no_go"):
        raise ChampionsReadinessError("compiler status disagrees with validated gates")
    if report.get("blocking_reasons") != list(expected_reasons):
        raise ChampionsReadinessError(
            "compiler blocking reasons disagree with validated gates"
        )
    if report.get("counts") != _derived_counts(compilation, expected_reasons):
        raise ChampionsReadinessError("compiler report counts disagree with artifacts")
    if report.get("denominator_final") is not compilation.capability_set.denominator_final:
        raise ChampionsReadinessError("compiler denominator flag disagrees with artifacts")
    if report.get("operational_success") is not True:
        raise ChampionsReadinessError("compiler result is not operationally complete")
    return report, artifacts


def _validate_compilation_cross_bindings(
    compilation: SourceToCapabilityCompilation,
) -> None:
    """Recheck the hash lineage between every compiler stage."""

    regulation = compilation.regulation_bundle.regulation
    target_pool = compilation.regulation_bundle.target_pool
    manifest = compilation.target_pool_manifest
    capabilities = compilation.capability_set
    checks = (
        (
            "intake/bridge",
            compilation.intake.bundle_hash,
            compilation.bridge.catalog_input.intake_bundle_hash,
        ),
        (
            "bridge/runtime Catalog",
            compilation.bridge.catalog_input.runtime_catalog_hash,
            compilation.catalog.snapshot_hash,
        ),
        ("semantic/Catalog", compilation.semantic.catalog_hash, compilation.catalog.snapshot_hash),
        ("semantic/ruleset", compilation.semantic.ruleset_hash, compilation.ruleset.snapshot_hash),
        ("manifest/regulation ID", manifest.regulation_id, regulation.regulation_id),
        ("manifest/regulation revision", manifest.regulation_revision, regulation.revision),
        ("manifest/regulation hash", manifest.regulation_hash, regulation.snapshot_hash),
        ("manifest/target pool ID", manifest.eligible_pool_id, target_pool.target_pool_id),
        ("manifest/target pool hash", manifest.eligible_pool_hash, target_pool.snapshot_hash),
        ("manifest/Catalog ID", manifest.catalog_id, compilation.catalog.catalog_id),
        ("manifest/Catalog hash", manifest.catalog_hash, compilation.catalog.snapshot_hash),
        ("manifest/ruleset ID", manifest.ruleset_id, str(compilation.ruleset.ruleset_id)),
        ("manifest/ruleset hash", manifest.ruleset_hash, compilation.ruleset.snapshot_hash),
        (
            "capability/manifest ID",
            capabilities.target_pool_manifest_id,
            manifest.manifest_id,
        ),
        (
            "capability/manifest hash",
            capabilities.target_pool_manifest_hash,
            manifest.manifest_hash,
        ),
        ("capability/Catalog", capabilities.catalog_hash, compilation.catalog.snapshot_hash),
        ("capability/ruleset", capabilities.ruleset_hash, compilation.ruleset.snapshot_hash),
        (
            "capability/semantic ID",
            capabilities.semantic_registry_id,
            compilation.semantic.registry.registry_id,
        ),
        (
            "capability/semantic hash",
            capabilities.semantic_registry_hash,
            compilation.semantic.registry.registry_hash,
        ),
        (
            "execution/capability",
            compilation.execution.target_capability_set_hash,
            capabilities.capability_set_hash,
        ),
        (
            "execution/semantic",
            compilation.execution.semantic_compilation_hash,
            compilation.semantic.compilation_hash,
        ),
        (
            "probe plan/capability",
            compilation.probe_plan.target_capability_set_hash,
            capabilities.capability_set_hash,
        ),
        (
            "probe plan/execution",
            compilation.probe_plan.execution_registry_hash,
            compilation.execution.registry.registry_hash,
        ),
        (
            "probe report/capability",
            compilation.probe_report.capability_set_hash,
            capabilities.capability_set_hash,
        ),
        (
            "grounding/capability",
            compilation.grounding.target_capability_set_hash,
            capabilities.capability_set_hash,
        ),
        (
            "matrix/capability ID",
            compilation.matrix.target_capability_set_id,
            capabilities.capability_set_id,
        ),
        (
            "matrix/capability hash",
            compilation.matrix.target_capability_set_hash,
            capabilities.capability_set_hash,
        ),
        (
            "matrix/execution",
            compilation.matrix.execution_registry_hash,
            compilation.execution.registry.registry_hash,
        ),
        (
            "matrix/probe report",
            compilation.matrix.probe_report_hash,
            compilation.probe_report.report_hash,
        ),
        (
            "matrix/grounding",
            compilation.matrix.grounding_assertion_set_hash,
            compilation.grounding.assertion_set_hash,
        ),
    )
    mismatches = [label for label, actual, expected in checks if actual != expected]
    if mismatches:
        raise ChampionsReadinessError(
            f"compiler stage hash lineage mismatch: {mismatches}"
        )


def _expected_base_documents(
    compilation: SourceToCapabilityCompilation,
) -> dict[str, str]:
    return {
        "catalog-intake.json": compilation.intake.to_json(),
        "runtime-catalog.json": compilation.bridge.runtime_catalog_json(),
        "mapping-evidence.json": compilation.bridge.mapping_evidence.to_json(),
        "production-catalog-input.json": compilation.bridge.catalog_input.to_json(),
        "semantic-compilation.json": canonical_json(compilation.semantic),
        "target-pool-manifest.json": compilation.target_pool_manifest.to_json(),
        "target-capability-set.json": compilation.capability_set.to_json(),
        "execution-compilation.json": canonical_json(compilation.execution),
        "probe-plan.json": canonical_json(compilation.probe_plan),
        "probe-report.json": canonical_json(compilation.probe_report),
        "grounding-resolution.json": canonical_json(compilation.grounding),
        "mechanic-coverage-matrix.json": compilation.matrix.to_json(),
    }


def _derived_blocking_reasons(
    compilation: SourceToCapabilityCompilation,
) -> tuple[str, ...]:
    reasons = set(compilation.matrix.blocking_reasons)
    reasons.update(compilation.target_pool_manifest.blockers)
    if compilation.semantic.unsupported_selectors:
        reasons.add(
            "semantic_unsupported_selector_count:"
            f"{len(compilation.semantic.unsupported_selectors)}"
        )
    if compilation.execution.gaps:
        reasons.add(f"execution_gap_count:{len(compilation.execution.gaps)}")
    if not compilation.grounding.results:
        reasons.add("grounding_assertion_corpus_missing")
    if compilation.matrix.holdout_report_hash is None:
        reasons.add("external_holdout_missing")
    if not compilation.bridge.catalog_input.catalog_emit_eligible:
        reasons.add("catalog_not_emit_eligible")
    reasons.update(
        f"restricted_source:{value}"
        for value in sorted(compilation.target_pool_manifest.restricted_source_manifest_ids)
    )
    return tuple(sorted(reasons))


def _derived_candidate_ready(
    compilation: SourceToCapabilityCompilation,
    reasons: tuple[str, ...] | None = None,
) -> bool:
    blockers = _derived_blocking_reasons(compilation) if reasons is None else reasons
    return bool(
        compilation.matrix.candidate_ready
        and compilation.bridge.catalog_input.catalog_emit_eligible
        and not compilation.target_pool_manifest.restricted_source_manifest_ids
        and not blockers
    )


def _derived_counts(
    compilation: SourceToCapabilityCompilation,
    reasons: tuple[str, ...],
) -> dict[str, int]:
    entries = compilation.bridge.mapping_evidence.entries
    results = compilation.probe_report.results
    return {
        "target_members": len(entries),
        "mapping_resolved": sum(
            value.resolution_status.value == "resolved" for value in entries
        ),
        "mapping_unresolved": sum(
            value.resolution_status.value == "unresolved" for value in entries
        ),
        "mapping_conflict": sum(
            value.resolution_status.value == "conflict" for value in entries
        ),
        "catalog_species": len(compilation.bridge.runtime_catalog["species"]),
        "catalog_moves": len(compilation.bridge.runtime_catalog["moves"]),
        "catalog_abilities": len(compilation.bridge.runtime_catalog["abilities"]),
        "catalog_items": len(compilation.bridge.runtime_catalog["items"]),
        "semantic_selectors": len(compilation.semantic.inventory),
        "semantic_unsupported_selectors": len(
            compilation.semantic.unsupported_selectors
        ),
        "target_capability_rows": len(compilation.capability_set.capabilities),
        "execution_gaps": len(compilation.execution.gaps),
        "grounding_assertions": len(compilation.grounding.results),
        "probe_explicit_unsupported": sum(
            value.explicit_unsupported for value in results
        ),
        "probe_unexpected_errors": sum(
            value.observed_outcome == "unexpected_error" for value in results
        ),
        "silent_fallbacks": compilation.probe_report.silent_fallback_count,
        "blocking_reasons": len(reasons),
    }


def _validate_bundle_binding(
    bundle: EnvironmentBundleIdentity,
    compilation: SourceToCapabilityCompilation,
) -> None:
    if bundle.scope is not EnvironmentScope.CHAMPIONS_CANDIDATE:
        raise ChampionsReadinessError(
            "Champions readiness cannot attest pure simulator scope"
        )
    if (
        bundle.capability_status is not EvidenceStatus.VERIFIED
        or bundle.grounding_status is not EvidenceStatus.VERIFIED
    ):
        raise ChampionsReadinessError(
            "Champions readiness requires verified evidence statuses"
        )

    regulation = compilation.regulation_bundle.regulation
    target_pool = compilation.regulation_bundle.target_pool
    checks = (
        ("adapter_version", bundle.adapter_version, AI_ENV_ADAPTER_VERSION),
        ("simulator_version", bundle.simulator_version, SIMULATOR_VERSION),
        (
            "engine_semantics_version",
            bundle.engine_semantics_version,
            compilation.ruleset.engine_semantics_version,
        ),
        ("catalog_id", bundle.catalog_id, compilation.catalog.catalog_id),
        ("catalog_hash", bundle.catalog_hash, compilation.catalog.snapshot_hash),
        ("ruleset_id", bundle.ruleset_id, str(compilation.ruleset.ruleset_id)),
        ("ruleset_hash", bundle.ruleset_hash, compilation.ruleset.snapshot_hash),
        ("regulation_id", bundle.regulation_id, regulation.regulation_id),
        ("regulation_hash", bundle.regulation_hash, regulation.snapshot_hash),
        ("target_pool_id", bundle.target_pool_id, target_pool.target_pool_id),
        ("target_pool_hash", bundle.target_pool_hash, target_pool.snapshot_hash),
        (
            "capability_set_id",
            bundle.capability_set_id,
            compilation.capability_set.capability_set_id,
        ),
        (
            "capability_set_hash",
            bundle.capability_set_hash,
            compilation.capability_set.capability_set_hash,
        ),
        (
            "grounding_assertion_set_hash",
            bundle.grounding_assertion_set_hash,
            compilation.grounding.assertion_set_hash,
        ),
        (
            "grounding_assertion_set_id",
            bundle.grounding_assertion_set_id,
            compilation.grounding.assertion_set_id,
        ),
        (
            "source_manifest_ids",
            bundle.source_manifest_ids,
            tuple(
                sorted(
                    {
                        compilation.catalog.source_manifest_id,
                        *compilation.ruleset.source_manifest_ids,
                    }
                )
            ),
        ),
        (
            "provisional_decision_ids",
            bundle.provisional_decision_ids,
            compilation.ruleset.provisional_decision_ids,
        ),
    )
    mismatches = [name for name, actual, expected in checks if actual != expected]
    if mismatches:
        raise ChampionsReadinessError(
            f"environment bundle mismatches compiler substance: {mismatches}"
        )
