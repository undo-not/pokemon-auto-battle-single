from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import pytest

from champions_sim import load_catalog, load_ruleset
from champions_sim.capabilities import (
    CapabilityReachability,
    ConstructionSelectionCorpus,
    EntityCapabilityRef,
    GroundingAssertion,
    GroundingAssertionSet,
    GroundingRequirement,
    MappingEntry,
    MappingResolutionStatus,
    SelectionPolicy,
    StateCheck,
    TargetCapability,
    TargetCapabilitySet,
    TargetPoolManifest,
    VerificationStatus,
    build_mechanic_coverage_matrix,
    build_target_capability_set,
    evaluate_external_holdout,
    resolve_grounding_assertions,
)
from champions_sim.catalog import (
    AbilityDefinition,
    CatalogSnapshot,
    ItemDefinition,
    MoveDefinition,
    RuleSetSnapshot,
    SpeciesDefinition,
)
from champions_sim.compiler import (
    SemanticCompilation,
    compile_effect_semantic_registry,
    compile_execution_registry,
    compile_probe_plan,
    run_compiled_probe_plan,
)
from champions_sim.core import (
    AbilityId,
    ItemId,
    MoveId,
    PokemonId,
    RuleSetId,
    UnsupportedMechanic,
    canonical_hash,
)
from champions_sim.capabilities import ProbeExecution


ROOT = Path(__file__).resolve().parents[1]
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64


def _synthetic_catalog() -> CatalogSnapshot:
    common = {
        "name": "same",
        "type_id": "normal",
        "category": "physical",
        "power": 40,
        "accuracy": 100,
        "pp": 20,
        "priority": 0,
        "contact": False,
        "effect": {"kind": "damage"},
    }
    moves = (
        MoveDefinition(move_id=MoveId("move-a"), **common),
        MoveDefinition(move_id=MoveId("move-b"), **common),
        MoveDefinition(
            MoveId("move-unknown"), "unknown", "normal", "status",
            None, None, 10, None, False,
            {
                "kind": "unsupported",
                "reason": "source_effect_not_compiled",
                "source_record_sha256": "7" * 64,
            },
        ),
    )
    ability = AbilityDefinition(
        AbilityId("ability-unknown"),
        "unknown",
        "unsupported:ability:future",
        source_record_sha256="8" * 64,
        unsupported_reason="source_effect_not_compiled",
    )
    species = SpeciesDefinition(
        PokemonId("mon-a"), "A", ("normal",), (ability.ability_id,),
        tuple(value.move_id for value in moves),
    )
    return CatalogSnapshot(
        schema_version="1.0.0",
        catalog_id="compiler-catalog",
        engine_semantics_version="compiler-test-v1",
        source_manifest_id="compiler-catalog-source",
        snapshot_hash=SHA_A,
        type_chart_default_multiplier=Fraction(1, 1),
        type_ids=("normal",),
        type_chart=(),
        moves=moves,
        abilities=(ability,),
        items=(
            ItemDefinition(
                ItemId("item-unknown"),
                "unknown",
                "unsupported:item:future",
                consumable=None,
                source_record_sha256="9" * 64,
                unsupported_reason="source_effect_not_compiled",
            ),
        ),
        species=(species,),
    )


def _synthetic_ruleset() -> RuleSetSnapshot:
    supported = {
        "accuracy", "critical_hit", "damage_roll", "fixed_power_damage",
        "priority", "speed_order", "stab", "stat_stages", "type_effectiveness",
    }
    return RuleSetSnapshot(
        schema_version="1.0.0",
        ruleset_id=RuleSetId("compiler-rules"),
        engine_semantics_version="compiler-test-v1",
        snapshot_hash=SHA_B,
        battle_format="singles_3v3",
        team_size=3,
        level=50,
        item_clause=True,
        max_turns=500,
        damage_rolls=tuple(range(85, 101)),
        supported_mechanics=frozenset(supported),
        unsupported_mechanics=frozenset({"mystery_mechanic"}),
        provisional_rules=(),
        provisional_decision_ids=(),
        source_manifest_ids=("compiler-rules-source",),
        critical_chance=Fraction(1, 24),
        critical_multiplier=Fraction(3, 2),
        raw={},
    )


def _corpus(role: str = "development") -> ConstructionSelectionCorpus:
    return ConstructionSelectionCorpus(
        schema_version="1.0.0",
        corpus_id=f"compiler-{role}",
        corpus_role=role,
        regulation_id="TEST",
        regulation_revision="r1",
        regulation_hash=SHA_C,
        capture_window_start="2026-01-01",
        capture_window_end="2026-01-02",
        records=(),
        evidence_refs=(),
        source_manifest_ids=(f"compiler-{role}-source",),
    )


def _manifest(
    catalog: CatalogSnapshot,
    ruleset: RuleSetSnapshot,
    corpus: ConstructionSelectionCorpus,
    *,
    resolved: bool = True,
) -> TargetPoolManifest:
    mapping = MappingEntry(
        target_key="dex:0001:form:00:variant:0",
        catalog_pokemon_id="mon-a" if resolved else None,
        resolution_status=(
            MappingResolutionStatus.RESOLVED
            if resolved else MappingResolutionStatus.UNRESOLVED
        ),
        verification_status=VerificationStatus.VERIFIED,
        mapping_method="explicit-source-record",
        candidate_pokemon_ids=(),
        evidence_ref_ids=("mapping-evidence",) if resolved else (),
    )
    return TargetPoolManifest(
        schema_version="1.0.0",
        manifest_id="compiler-manifest",
        regulation_id="TEST",
        regulation_revision="r1",
        regulation_hash=SHA_C,
        eligible_pool_id="eligible-test",
        eligible_pool_hash=SHA_D,
        catalog_id=catalog.catalog_id,
        catalog_hash=catalog.snapshot_hash,
        ruleset_id=str(ruleset.ruleset_id),
        ruleset_hash=ruleset.snapshot_hash,
        construction_corpus_id=corpus.corpus_id,
        construction_corpus_hash=corpus.snapshot_hash,
        mapping_set_id="compiler-mapping",
        mapping_set_hash="e" * 64,
        selection_policy=SelectionPolicy(),
        eligible_member_count=1,
        required_mechanics=("mystery_mechanic",),
        member_mappings=(mapping,),
        included_records=(),
        duplicate_aliases=(),
        source_manifest_ids=("compiler-manifest-source",),
        restricted_source_manifest_ids=(),
        blockers=(),
    )


def _built(*, resolved: bool = True):
    catalog = _synthetic_catalog()
    ruleset = _synthetic_ruleset()
    corpus = _corpus()
    semantic = compile_effect_semantic_registry(
        catalog, ruleset, ("mystery_mechanic",)
    )
    capability_set = build_target_capability_set(
        _manifest(catalog, ruleset, corpus, resolved=resolved),
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
    return catalog, ruleset, semantic, capability_set, execution


def _grounding(capability_set: TargetCapabilitySet):
    requirement_ids = tuple(
        value.requirement_id for value in capability_set.grounding_requirements
    )
    capability_ids = tuple(value.capability_id for value in capability_set.capabilities)
    assertion = GroundingAssertion(
        assertion_id="compiler-assertion",
        requirement_ids=requirement_ids,
        capability_ids=capability_ids,
        evidence_kind="official_primary",
        ruleset_id="compiler-rules",
        ruleset_hash=capability_set.ruleset_hash,
        catalog_hash=capability_set.catalog_hash,
        trace_id=None,
        trace_hash=None,
        reference_replay_hash=None,
        initial_state_hash="1" * 64,
        choice_sequence_hash="2" * 64,
        rng_condition_id="rng-observed",
        expected_event_slice_hash="3" * 64,
        expected_state_checks=(StateCheck("/turn", 1),),
        conformance_check_refs=(),
        evidence_ref_ids=("compiler-grounding-evidence",),
        claimed_verdict="pass",
    )
    raw = GroundingAssertionSet(
        schema_version="1.0.0",
        assertion_set_id="compiler-assertions",
        target_capability_set_id=capability_set.capability_set_id,
        target_capability_set_hash=capability_set.capability_set_hash,
        assertions=(assertion,),
        source_manifest_ids=("compiler-grounding-source",),
    )
    return resolve_grounding_assertions(
        raw,
        capability_set,
        validated_traces={},
        evidence_resolver=lambda _: True,
    )


def _executors(plan, *, silent_unsupported: bool = False):
    executors = {}
    for spec in plan.specs:
        if spec.expected_outcome == "supported":
            executors[spec.capability_id] = lambda: ProbeExecution("success", True, None)
        elif silent_unsupported:
            executors[spec.capability_id] = lambda: ProbeExecution("success", False, None)
        else:
            def unsupported() -> ProbeExecution:
                raise UnsupportedMechanic("compiler-explicit-unsupported")
            executors[spec.capability_id] = unsupported
    return executors


def test_compiler_dedupes_equal_signatures_and_keeps_all_origin_refs() -> None:
    _, _, semantic, capability_set, execution = _built()

    assert len(semantic.inventory) == 6
    assert len(semantic.unsupported_selectors) == 4
    assert all(
        "catalog_declared_unsupported" in value.reason_codes
        for value in semantic.unsupported_selectors
        if value.entity_kind in {"move", "ability", "item"}
    )
    ability_definition = next(
        value for value in semantic.registry.definitions
        if value.entity_kind == "ability"
    )
    ability_context = {
        value.key: value.value
        for value in ability_definition.signature.resolution_context
    }
    assert ability_context["source.unsupported_selector_identity"] == "8" * 64
    ability_diagnostic = next(
        value for value in semantic.unsupported_selectors
        if value.entity_kind == "ability"
    )
    assert ability_diagnostic.source_record_sha256 == "8" * 64
    assert ability_diagnostic.source_reason == "source_effect_not_compiled"
    damage_definitions = tuple(
        value for value in semantic.registry.definitions
        if value.signature.effect_id == "move.damage"
    )
    assert len(damage_definitions) == 2
    assert len({value.signature.capability_id for value in damage_definitions}) == 1

    damage = next(
        value for value in capability_set.capabilities
        if value.signature.effect_id == "move.damage"
    )
    refs = tuple(
        value for value in capability_set.entity_capability_refs
        if value.capability_id == damage.capability_id
    )
    assert {(value.entity_id, value.owner_entity_id) for value in refs} == {
        ("move-a", "mon-a"),
        ("move-b", "mon-a"),
    }
    assert capability_set.denominator_final
    assert len(execution.gaps) == 4
    assert all(len(value.dimensions) == 6 for value in execution.registry.supports)


def test_explicit_unsupported_probe_is_not_silent_but_blocks_candidate() -> None:
    _, _, _, capability_set, execution = _built()
    plan = compile_probe_plan(capability_set, execution)
    assert sum(value.expected_outcome == "supported" for value in plan.specs) == 1
    assert sum(value.expected_outcome == "explicit_unsupported" for value in plan.specs) == 4

    report = run_compiled_probe_plan(
        capability_set, execution, plan, _executors(plan)
    )
    assert report.silent_fallback_count == 0
    assert sum(value.explicit_unsupported for value in report.results) == 4

    holdout = evaluate_external_holdout(capability_set, _corpus("external_holdout"))
    matrix = build_mechanic_coverage_matrix(
        matrix_id="compiler-matrix",
        capability_set=capability_set,
        execution_registry=execution.registry,
        probe_report=report,
        grounding_assertions=_grounding(capability_set),
        holdout_report=holdout,
    )
    assert matrix.silent_fallback_count == 0
    assert not matrix.coverage_complete
    assert not matrix.candidate_ready
    assert matrix.target_pool_execution_coverage_rate_ppm == 200_000


def test_success_from_unsupported_branch_is_derived_as_silent_fallback() -> None:
    _, _, _, capability_set, execution = _built()
    plan = compile_probe_plan(capability_set, execution)
    report = run_compiled_probe_plan(
        capability_set,
        execution,
        plan,
        _executors(plan, silent_unsupported=True),
    )
    assert report.silent_fallback_count == 4


def test_probe_runner_rejects_caller_rewritten_expectations() -> None:
    _, _, _, capability_set, execution = _built()
    plan = compile_probe_plan(capability_set, execution)
    unsupported_index = next(
        index
        for index, value in enumerate(plan.specs)
        if value.expected_outcome == "explicit_unsupported"
    )
    forged_specs = list(plan.specs)
    forged_specs[unsupported_index] = replace(
        forged_specs[unsupported_index], expected_outcome="supported"
    )
    forged = replace(plan, specs=tuple(forged_specs))

    with pytest.raises(ValueError, match="compiler-derived expectations"):
        run_compiled_probe_plan(
            capability_set, execution, forged, _executors(forged)
        )


def test_nonfinal_mapping_keeps_catalog_wide_diagnostics_and_null_rates() -> None:
    _, _, semantic, capability_set, execution = _built(resolved=False)
    assert len(semantic.inventory) == 6
    assert any(value.entity_id == "move-unknown" for value in semantic.unsupported_selectors)
    assert not capability_set.denominator_final
    assert {value.signature.effect_id for value in capability_set.capabilities} == {
        next(
            value.signature.effect_id
            for value in semantic.registry.definitions
            if value.entity_kind == "item"
        ),
        next(
            value.signature.effect_id
            for value in semantic.registry.definitions
            if value.entity_kind == "mechanic"
        ),
    }

    plan = compile_probe_plan(capability_set, execution)
    report = run_compiled_probe_plan(
        capability_set, execution, plan, _executors(plan)
    )
    matrix = build_mechanic_coverage_matrix(
        matrix_id="compiler-nonfinal",
        capability_set=capability_set,
        execution_registry=execution.registry,
        probe_report=report,
        grounding_assertions=_grounding(capability_set),
        holdout_report=evaluate_external_holdout(
            capability_set, _corpus("external_holdout")
        ),
    )
    assert matrix.declared_target_capability_count is None
    assert matrix.fully_supported_target_capability_count is None
    assert matrix.target_pool_execution_coverage_rate_ppm is None


def _capability_set_for_registry(
    semantic: SemanticCompilation,
    catalog: CatalogSnapshot,
    ruleset: RuleSetSnapshot,
) -> TargetCapabilitySet:
    grouped = defaultdict(list)
    for definition in semantic.registry.definitions:
        grouped[definition.signature.capability_id].append(definition)
    refs = []
    capabilities = []
    requirements = []
    for capability_id in sorted(grouped):
        definitions = grouped[capability_id]
        ref_ids = []
        for definition in definitions:
            ref_id = "ref-" + canonical_hash(definition.semantic_id)
            ref_ids.append(ref_id)
            refs.append(
                EntityCapabilityRef(
                    ref_id=ref_id,
                    entity_kind=definition.entity_kind,
                    entity_id=definition.selector_id.removeprefix("entity:"),
                    owner_entity_id=None,
                    capability_id=capability_id,
                    legal_status="legal",
                    observed_in_corpus=False,
                    source_record_ids=(),
                    evidence_ref_ids=(),
                )
            )
        requirement_id = "ground-" + canonical_hash(capability_id)
        requirements.append(
            GroundingRequirement(
                requirement_id=requirement_id,
                capability_id=capability_id,
                boundary_id="compiler",
                scope="shared_semantics",
                entity_ref_id=None,
                allowed_evidence_kinds=("official_primary",),
            )
        )
        capabilities.append(
            TargetCapability(
                capability_id=capability_id,
                signature=definitions[0].signature,
                reachability=(
                    CapabilityReachability.MANDATORY
                    if any(value.entity_kind == "mechanic" for value in definitions)
                    else CapabilityReachability.LEGAL
                ),
                entity_ref_ids=tuple(sorted(ref_ids)),
                grounding_requirement_ids=(requirement_id,),
            )
        )
    return TargetCapabilitySet(
        schema_version="1.0.0",
        capability_set_id="fixture-compiler-capabilities",
        target_pool_manifest_id="fixture-compiler-manifest",
        target_pool_manifest_hash="4" * 64,
        catalog_hash=catalog.snapshot_hash,
        ruleset_hash=ruleset.snapshot_hash,
        semantic_registry_id=semantic.registry.registry_id,
        semantic_registry_hash=semantic.registry.registry_hash,
        closure_algorithm_version="compiler-test-v1",
        denominator_final=True,
        entity_capability_refs=tuple(sorted(refs, key=lambda value: value.ref_id)),
        capabilities=tuple(capabilities),
        grounding_requirements=tuple(requirements),
        unresolved_requirements=(),
        development_records=(),
        source_manifest_ids=semantic.registry.source_manifest_ids,
    )


def test_real_sim01_fixture_compiles_all_catalog_selectors_and_blocks_mega() -> None:
    catalog = load_catalog(ROOT / "data/fixtures/sim01_catalog.json")
    ruleset = load_ruleset(ROOT / "data/fixtures/sim01_ruleset.json")
    semantic = compile_effect_semantic_registry(
        catalog, ruleset, ("mega_evolution",)
    )
    assert len(semantic.inventory) == (
        len(catalog.moves) + len(catalog.abilities) + len(catalog.items) + 1
    )
    assert semantic.unsupported_selectors == ()
    assert semantic.registry.registry_hash == compile_effect_semantic_registry(
        catalog, ruleset, ("mega_evolution",)
    ).registry.registry_hash

    capability_set = _capability_set_for_registry(semantic, catalog, ruleset)
    execution = compile_execution_registry(
        capability_set=capability_set,
        semantic_compilation=semantic,
        catalog=catalog,
        ruleset=ruleset,
    )
    assert len(execution.gaps) == 1
    assert execution.gaps[0].effect_id == "mechanic.mega_evolution"
    assert any(
        value.startswith("ruleset_prerequisite_unsupported:mega_evolution")
        for value in execution.gaps[0].reason_codes
    )
    assert all(len(value.dimensions) == 6 for value in execution.registry.supports)
    rng_none_rows = tuple(
        value for value in execution.registry.supports
        if next(
            capability.signature.effect_id
            for capability in capability_set.capabilities
            if capability.capability_id == value.capability_id
        ).startswith(("ability.", "item."))
        and not any(dimension.status.value == "fail" for dimension in value.dimensions)
    )
    assert rng_none_rows
    assert all(
        next(value for value in row.dimensions if value.dimension == "rng").contract_id
        == "rng:none"
        for row in rng_none_rows
    )


def test_signature_is_bound_to_exact_catalog_and_ruleset_hashes() -> None:
    catalog = _synthetic_catalog()
    ruleset = _synthetic_ruleset()
    first = compile_effect_semantic_registry(catalog, ruleset, ())
    changed = compile_effect_semantic_registry(
        replace(catalog, snapshot_hash="9" * 64), ruleset, ()
    )
    assert first.registry.registry_hash != changed.registry.registry_hash
    assert {
        value.signature.capability_id for value in first.registry.definitions
    } != {
        value.signature.capability_id for value in changed.registry.definitions
    }


def test_known_aliases_dedupe_semantics_while_preserving_source_diagnostics() -> None:
    catalog = _synthetic_catalog()
    abilities = (
        AbilityDefinition(
            AbilityId("alias-a"),
            "alias A",
            "intimidate",
            source_record_sha256="1" * 64,
        ),
        AbilityDefinition(
            AbilityId("alias-b"),
            "alias B",
            "intimidate",
            source_record_sha256="2" * 64,
        ),
    )
    compiled = compile_effect_semantic_registry(
        replace(catalog, abilities=abilities), _synthetic_ruleset(), ()
    )
    definitions = tuple(
        value for value in compiled.registry.definitions
        if value.entity_kind == "ability"
    )
    diagnostics = tuple(
        value for value in compiled.inventory
        if value.entity_kind == "ability"
    )
    assert len({value.signature.capability_id for value in definitions}) == 1
    assert {value.source_record_sha256 for value in diagnostics} == {
        "1" * 64,
        "2" * 64,
    }


def test_sealed_intake_bridge_catalog_keeps_every_unknown_selector_in_inventory(
    tmp_path: Path,
) -> None:
    from champions_sim.compiler.bridge import CatalogBridgeProfile, compile_catalog_bridge
    from champions_sim.intake import (
        CatalogIntakePaths,
        CatalogIntakeProfile,
        build_catalog_intake,
    )

    fixture = ROOT / "data/fixtures/intake/synthetic_mini"
    intake = build_catalog_intake(
        repository_root=fixture,
        legacy_root=fixture,
        paths=CatalogIntakePaths(target_pool="target_pool.json"),
        profile=CatalogIntakeProfile(
            "synthetic_mini", "TEST-B", "synthetic-v1", 3, 2
        ),
    )
    bridge = compile_catalog_bridge(
        intake,
        repository_root=fixture,
        legacy_root=fixture,
        profile=CatalogBridgeProfile(
            "synthetic_bridge",
            "TEST-B",
            "synthetic-v1",
            3,
            "synthetic-local-unverified",
            "sim-core-0.1",
        ),
    )
    catalog_path = tmp_path / "bridge-catalog.json"
    catalog_path.write_text(bridge.runtime_catalog_json(), encoding="utf-8")
    catalog = load_catalog(catalog_path)
    ruleset = load_ruleset(ROOT / "data/fixtures/sim01_ruleset.json")

    semantic = compile_effect_semantic_registry(
        catalog, ruleset, ("mega_evolution",)
    )
    expected_unknown_count = (
        len(catalog.moves) + len(catalog.abilities) + len(catalog.items)
    )
    assert len(semantic.inventory) == expected_unknown_count + 1
    assert len(semantic.unsupported_selectors) == expected_unknown_count
    assert {
        value.entity_id for value in semantic.unsupported_selectors
    } == {
        *(str(value.move_id) for value in catalog.moves),
        *(str(value.ability_id) for value in catalog.abilities),
        *(str(value.item_id) for value in catalog.items),
    }
    assert all(
        "catalog_declared_unsupported" in value.reason_codes
        for value in semantic.unsupported_selectors
    )
