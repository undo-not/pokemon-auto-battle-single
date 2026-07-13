"""Compile semantic capabilities into six-dimensional engine support rows."""

from __future__ import annotations

from collections import defaultdict

from champions_sim.capabilities import (
    EXECUTION_DIMENSIONS,
    CoverageDimensionResult,
    DimensionStatus,
    ExecutionRegistry,
    ExecutionSupport,
    TargetCapabilitySet,
)
from champions_sim.catalog import CatalogSnapshot, RuleSetSnapshot
from champions_sim.core import canonical_hash

from .models import ExecutionCompilation, ExecutionGap, SemanticCompilation


_HANDLERS = {
    "move.damage": "engine.move.damage",
    "move.damage_drain": "engine.move.damage-drain",
    "move.damage_secondary_flinch": "engine.move.secondary-flinch",
    "move.damage_secondary_stage": "engine.move.secondary-stage",
    "move.damage_secondary_status": "engine.move.secondary-status",
    "move.heal_self": "engine.move.heal-self",
    "move.inflict_status": "engine.move.inflict-status",
    "move.raise_self": "engine.move.raise-self",
    "ability.rough_skin": "engine.ability.rough-skin",
    "ability.natural_cure": "engine.ability.natural-cure",
    "ability.technician": "engine.ability.technician",
    "ability.intimidate": "engine.ability.intimidate",
    "ability.overgrow": "engine.ability.overgrow",
    "ability.blaze": "engine.ability.blaze",
    "item.leftovers": "engine.item.leftovers",
    "item.sitrus_berry": "engine.item.sitrus-berry",
    "item.focus_sash": "engine.item.focus-sash",
    "item.mega_stone": "engine.item.mega-stone",
    "mechanic.mega_evolution": "engine.mechanic.mega-evolution",
}

_TRANSITION_TESTS = {
    "move.damage": "tests.test_engine_integration.test_same_state_seed_and_actions_are_deterministic_and_branch_safe",
    "move.damage_drain": "tests.test_engine_integration.test_drain_move_heals_from_actual_damage_when_target_faints",
    "move.damage_secondary_flinch": "tests.test_engine_integration.test_same_state_seed_and_actions_are_deterministic_and_branch_safe",
    "move.damage_secondary_stage": "tests.test_engine_integration.test_same_state_seed_and_actions_are_deterministic_and_branch_safe",
    "move.damage_secondary_status": "tests.test_engine_integration.test_burn_residual_and_natural_cure_switch_are_integrated",
    "move.heal_self": "tests.test_runner_integration.test_scripted_policy_completes_a_battle",
    "move.inflict_status": "tests.test_engine_integration.test_burn_residual_and_natural_cure_switch_are_integrated",
    "move.raise_self": "tests.test_engine_integration.test_same_state_seed_and_actions_are_deterministic_and_branch_safe",
    "ability.rough_skin": "tests.test_engine_integration.test_rough_skin_holder_wins_when_both_last_pokemon_faint",
    "ability.natural_cure": "tests.test_engine_integration.test_burn_residual_and_natural_cure_switch_are_integrated",
    "ability.technician": "tests.test_engine_integration.test_switch_in_contact_and_end_turn_effects_are_integrated",
    "ability.intimidate": "tests.test_engine_integration.test_switch_in_contact_and_end_turn_effects_are_integrated",
    "ability.overgrow": "tests.test_engine_integration.test_focus_sash_and_sitrus_berry_trigger_and_are_consumed",
    "ability.blaze": "tests.test_engine_integration.test_focus_sash_and_sitrus_berry_trigger_and_are_consumed",
    "item.leftovers": "tests.test_engine_integration.test_switch_in_contact_and_end_turn_effects_are_integrated",
    "item.sitrus_berry": "tests.test_engine_integration.test_focus_sash_and_sitrus_berry_trigger_and_are_consumed",
    "item.focus_sash": "tests.test_engine_integration.test_focus_sash_and_sitrus_berry_trigger_and_are_consumed",
    "item.mega_stone": "tests.test_mega_evolution_contract.test_wrong_item_generates_no_mega_action",
    "mechanic.mega_evolution": "tests.test_mega_evolution_contract.test_mega_evolution_is_explicit_pre_move_persistent_and_once_per_side",
}

_DIMENSION_TESTS = {
    "legality": "tests.test_engine_integration.test_illegal_or_stale_selections_are_rejected_without_mutation",
    "transition": "tests.test_engine_integration.test_same_state_seed_and_actions_are_deterministic_and_branch_safe",
    "rng": "tests.test_runner_integration.test_same_seed_is_byte_reproducible_across_one_hundred_runs",
    "event": "tests.test_engine_integration.test_switch_in_contact_and_end_turn_effects_are_integrated",
    "observation": "tests.test_engine_integration.test_engine_observation_does_not_leak_hidden_bench_or_private_fields",
    "replay": "tests.test_replay_runner_contract.test_runner_emits_self_contained_versioned_replay",
}


def compile_execution_registry(
    *,
    capability_set: TargetCapabilitySet,
    semantic_compilation: SemanticCompilation,
    catalog: CatalogSnapshot,
    ruleset: RuleSetSnapshot,
) -> ExecutionCompilation:
    """Create one exact six-dimension row for every frozen capability.

    A row can be all-PASS only when the effect has an engine handler and every
    prerequisite is declared supported by the exact RuleSet.  Unknown effects,
    missing semantic definitions, and unsupported RuleSet branches receive six
    explicit FAIL dimensions; they are never omitted or treated as no-ops.
    """

    if capability_set.catalog_hash != catalog.snapshot_hash:
        raise ValueError("TargetCapabilitySet Catalog hash mismatch")
    if capability_set.ruleset_hash != ruleset.snapshot_hash:
        raise ValueError("TargetCapabilitySet RuleSet hash mismatch")
    if semantic_compilation.catalog_hash != catalog.snapshot_hash:
        raise ValueError("semantic compilation Catalog hash mismatch")
    if semantic_compilation.ruleset_hash != ruleset.snapshot_hash:
        raise ValueError("semantic compilation RuleSet hash mismatch")
    if capability_set.semantic_registry_hash != semantic_compilation.registry.registry_hash:
        raise ValueError("TargetCapabilitySet semantic registry hash mismatch")
    if catalog.engine_semantics_version != ruleset.engine_semantics_version:
        raise ValueError("Catalog and RuleSet engine semantics versions differ")

    definitions_by_capability = defaultdict(list)
    for definition in semantic_compilation.registry.definitions:
        definitions_by_capability[definition.signature.capability_id].append(definition)

    supports: list[ExecutionSupport] = []
    gaps: list[ExecutionGap] = []
    for capability in sorted(capability_set.capabilities, key=lambda value: value.capability_id):
        signature = capability.signature
        definitions = definitions_by_capability.get(capability.capability_id, ())
        reasons: list[str] = []
        handler_id = _HANDLERS.get(signature.effect_id)
        if not definitions:
            reasons.append("semantic_definition_missing")
        if signature.effect_id.startswith("unsupported."):
            reasons.append("uninterpreted_selector")
        if handler_id is None:
            reasons.append("engine_handler_missing")
        elif signature.effect_id not in _TRANSITION_TESTS:
            reasons.append("execution_test_contract_missing")

        context = {value.key: value.value for value in signature.resolution_context}
        required = {
            key.removeprefix("requires.")
            for key, value in context.items()
            if key.startswith("requires.") and value is True
        }
        explicitly_unsupported_set = required & set(ruleset.unsupported_mechanics)
        missing = sorted(
            required
            - set(ruleset.supported_mechanics)
            - explicitly_unsupported_set
        )
        explicitly_unsupported = sorted(explicitly_unsupported_set)
        reasons.extend(f"ruleset_prerequisite_missing:{value}" for value in missing)
        reasons.extend(
            f"ruleset_prerequisite_unsupported:{value}"
            for value in explicitly_unsupported
        )

        rng_contract = context.get("rng_contract")
        if not isinstance(rng_contract, str) or not rng_contract.startswith("rng:"):
            reasons.append("rng_contract_missing")
            rng_contract = "rng:unsupported"
        if (
            context.get("ruleset_rule_payload_required") is True
            and context.get("ruleset_rule_payload_present") is not True
        ):
            reasons.append("ruleset_rule_payload_missing")

        reasons_tuple = tuple(sorted(set(reasons)))
        if reasons_tuple:
            digest = canonical_hash((capability.capability_id, reasons_tuple))[:20]
            dimensions = tuple(
                CoverageDimensionResult(
                    dimension=dimension,
                    status=DimensionStatus.FAIL,
                    contract_id=f"unsupported:{dimension}:{digest}",
                    test_ids=(),
                )
                for dimension in EXECUTION_DIMENSIONS
            )
            final_handler_id = "unsupported:" + digest
            gaps.append(
                ExecutionGap(
                    capability_id=capability.capability_id,
                    effect_id=signature.effect_id,
                    reason_codes=reasons_tuple,
                )
            )
        else:
            assert handler_id is not None
            effect_test = _TRANSITION_TESTS[signature.effect_id]
            dimensions = tuple(
                CoverageDimensionResult(
                    dimension=dimension,
                    status=DimensionStatus.PASS,
                    contract_id=(
                        rng_contract
                        if dimension == "rng"
                        else f"contract:{handler_id}:{dimension}"
                    ),
                    test_ids=tuple(sorted({_DIMENSION_TESTS[dimension], effect_test})),
                )
                for dimension in EXECUTION_DIMENSIONS
            )
            final_handler_id = handler_id
        supports.append(
            ExecutionSupport(
                capability_id=capability.capability_id,
                handler_id=final_handler_id,
                dimensions=dimensions,
            )
        )

    registry = ExecutionRegistry(
        registry_id="execution-registry:" + canonical_hash(
            (capability_set.capability_set_hash, semantic_compilation.compilation_hash)
        )[:24],
        engine_semantics_version=ruleset.engine_semantics_version,
        supports=tuple(supports),
        source_hashes=tuple(
            sorted(
                {
                    catalog.snapshot_hash,
                    ruleset.snapshot_hash,
                    semantic_compilation.registry.registry_hash,
                    capability_set.capability_set_hash,
                }
            )
        ),
    )
    return ExecutionCompilation(
        target_capability_set_hash=capability_set.capability_set_hash,
        semantic_compilation_hash=semantic_compilation.compilation_hash,
        registry=registry,
        gaps=tuple(gaps),
    )
