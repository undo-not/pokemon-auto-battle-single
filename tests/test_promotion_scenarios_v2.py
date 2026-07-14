from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from champions_sim import (
    BattleEngine,
    load_battle_fixture,
    load_catalog,
    load_ruleset,
    run_battle,
)
from champions_sim.capabilities.models import (
    CapabilityReachability,
    CapabilitySignature,
    EntityCapabilityRef,
    GroundingRequirement,
    TargetCapability,
    TargetCapabilitySet,
)
from champions_sim.core import (
    ActionSelection,
    BattleEventKind,
    DecisionRequestSet,
    ReplayInitialState,
    ReplayRecord,
    canonical_hash,
)
from champions_sim.promotion.scenarios import (
    EngineScenarioV2,
    PromotionScenarioError,
    build_engine_probe_report_v2,
    build_engine_scenario_corpus_v2,
    build_scenario_partition_manifest_v2,
    replay_choice_sequence_hash,
    replay_execution_hash_v2,
    verify_engine_probe_v2,
)
from scripts.validate_sim01_bundle import (
    BundleValidationError,
    validate_document_contract,
)


ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "data/schemas"


def _simulation() -> tuple[BattleEngine, object]:
    catalog = load_catalog(ROOT / "data/fixtures/sim01_catalog.json")
    ruleset = load_ruleset(ROOT / "data/fixtures/sim01_ruleset.json")
    fixture = load_battle_fixture(
        ROOT / "data/fixtures/sim01_battle.json",
        catalog=catalog,
        ruleset=ruleset,
    )
    return BattleEngine(catalog, ruleset), fixture


def _capability_parts(
    effect_id: str,
    entity_kind: str,
    entity_id: str,
    ordinal: int,
) -> tuple[TargetCapability, EntityCapabilityRef, GroundingRequirement]:
    signature = CapabilitySignature(
        effect_id=effect_id,
        trigger="test-trigger",
        target="test-target",
        resolution_context=(),
        ruleset_branch="test-branch",
    )
    capability_id = signature.capability_id
    ref_id = f"entity-ref-{ordinal}"
    requirement_id = f"grounding-requirement-{ordinal}"
    return (
        TargetCapability(
            capability_id=capability_id,
            signature=signature,
            reachability=CapabilityReachability.LEGAL,
            entity_ref_ids=(ref_id,),
            grounding_requirement_ids=(requirement_id,),
        ),
        EntityCapabilityRef(
            ref_id=ref_id,
            entity_kind=entity_kind,
            entity_id=entity_id,
            owner_entity_id=None,
            capability_id=capability_id,
            legal_status="legal",
            observed_in_corpus=True,
            source_record_ids=(f"source-record-{ordinal}",),
            evidence_ref_ids=(f"evidence-{ordinal}",),
        ),
        GroundingRequirement(
            requirement_id=requirement_id,
            capability_id=capability_id,
            boundary_id="event",
            scope="entity_reference",
            entity_ref_id=ref_id,
            allowed_evidence_kinds=("replay_probe",),
        ),
    )


def _target_set(
    engine: BattleEngine,
    *capability_specs: tuple[str, str, str],
) -> TargetCapabilitySet:
    parts = tuple(
        _capability_parts(effect_id, entity_kind, entity_id, ordinal)
        for ordinal, (effect_id, entity_kind, entity_id) in enumerate(
            capability_specs, start=1
        )
    )
    return TargetCapabilitySet(
        schema_version="1.0.0",
        capability_set_id="target-capability-set-probe-test",
        target_pool_manifest_id="target-pool-probe-test",
        target_pool_manifest_hash="1" * 64,
        catalog_hash=engine.catalog.snapshot_hash,
        ruleset_hash=engine.ruleset.snapshot_hash,
        semantic_registry_id="semantic-registry-probe-test",
        semantic_registry_hash="2" * 64,
        closure_algorithm_version="closure-probe-test",
        denominator_final=True,
        entity_capability_refs=tuple(part[1] for part in parts),
        capabilities=tuple(part[0] for part in parts),
        grounding_requirements=tuple(part[2] for part in parts),
        unresolved_requirements=(),
        development_records=(),
        source_manifest_ids=("target-capability-source",),
    )


def _damage_witness(
    replay: ReplayRecord,
    move_id: str | None = None,
) -> tuple[int, int, str]:
    for step_index, step in enumerate(replay.steps):
        for event_index, event in enumerate(step.events):
            if event.kind is not BattleEventKind.DAMAGE:
                continue
            details = dict(event.details)
            source = details.get("source")
            if not isinstance(source, str):
                continue
            if move_id is not None and source != move_id:
                continue
            if any(
                candidate.kind is BattleEventKind.MOVE_USED
                and dict(candidate.details).get("move_id") == source
                and candidate.actor == event.actor
                for candidate in step.events[:event_index]
            ):
                return step_index, event_index, source
    raise AssertionError("SIM-01 Replay did not contain move damage")


def _scenario(
    *,
    scenario_id: str,
    role: str,
    capability_set: TargetCapabilitySet,
    capability_id: str,
    replay: ReplayRecord,
    lineage_tag: str,
) -> EngineScenarioV2:
    capability = next(
        value
        for value in capability_set.capabilities
        if value.capability_id == capability_id
    )
    entity_ref_ids = set(capability.entity_ref_ids)
    move_id = next(
        value.entity_id
        for value in capability_set.entity_capability_refs
        if value.ref_id in entity_ref_ids and value.entity_kind == "move"
    )
    step_index, event_index, _ = _damage_witness(replay, move_id)
    event = replay.steps[step_index].events[event_index]
    return EngineScenarioV2(
        scenario_id=scenario_id,
        partition_role=role,
        capability_id=capability_id,
        target_capability_set_hash=capability_set.capability_set_hash,
        initial_state_hash=replay.initial_state.state_hash,
        choice_sequence_hash=replay_choice_sequence_hash(replay),
        seed=replay.initial_rng.seed,
        rng_algorithm_id=replay.rng_algorithm_id,
        catalog_hash=replay.bundle.catalog_content_hash,
        ruleset_hash=replay.bundle.ruleset_content_hash,
        replay_hash=replay.replay_hash,
        replay_execution_hash=replay_execution_hash_v2(replay),
        witness_step_index=step_index,
        witness_event_index=event_index,
        witness_event_kind=event.kind.value,
        witness_event_hash=canonical_hash(event),
        source_lineage_ids=(f"source-{lineage_tag}",),
        collection_lineage_ids=(f"collection-{lineage_tag}",),
        authoring_lineage_ids=(f"author-{lineage_tag}",),
    )


def _cosmetically_relabel_replay(replay: ReplayRecord) -> ReplayRecord:
    """Relabel every record coordinate while retaining execution substance."""

    instance_labels = {
        str(pokemon.instance_id): f"cosmetic-{side.player.value}-{index}"
        for side in replay.initial_state.payload.sides
        for index, pokemon in enumerate(side.team)
    }
    sides = tuple(
        replace(
            side,
            team=tuple(
                replace(
                    pokemon,
                    instance_id=instance_labels[str(pokemon.instance_id)],
                )
                for pokemon in side.team
            ),
            active_instance_id=instance_labels[str(side.active_instance_id)],
        )
        for side in replay.initial_state.payload.sides
    )
    relabelled_battle_id = "cosmetic-battle-id"
    initial_state = ReplayInitialState.capture(
        replace(
            replay.initial_state.payload,
            battle_id=relabelled_battle_id,
            sides=sides,
        )
    )
    provisional_labels = {
        value: f"PD-{101 + index:03d}"
        for index, value in enumerate(replay.provisional_decision_ids)
    }

    def relabel_event(event, labels):
        return replace(
            event,
            subject=(
                instance_labels.get(str(event.subject), str(event.subject))
                if event.subject is not None
                else None
            ),
            details=tuple(
                (
                    key,
                    labels.get(value, value) if isinstance(value, str) else value,
                )
                for key, value in event.details
            ),
        )

    initial_labels = {
        replay.battle_id: relabelled_battle_id,
        **instance_labels,
    }
    initial_events = tuple(
        relabel_event(event, initial_labels) for event in replay.initial_events
    )
    steps = []
    for step_index, step in enumerate(replay.steps):
        request_labels = {
            request.request_id: (
                f"cosmetic-request-{step_index}-{request.player.value}"
            )
            for request in step.requests.requests
        }
        action_labels = {
            action.action_id: (
                f"cosmetic-action-{step_index}-{request.player.value}-{index}"
            )
            for request in step.requests.requests
            for index, action in enumerate(request.legal_actions)
        }
        requests = DecisionRequestSet(
            tuple(
                replace(
                    request,
                    request_id=request_labels[request.request_id],
                    legal_actions=tuple(
                        replace(
                            action,
                            action_id=action_labels[action.action_id],
                            switch_to=(
                                instance_labels[str(action.switch_to)]
                                if action.switch_to is not None
                                else None
                            ),
                        )
                        for action in request.legal_actions
                    ),
                )
                for request in step.requests.requests
            )
        )
        selections = tuple(
            ActionSelection(
                request_id=request_labels[selection.request_id],
                player=selection.player,
                action_id=action_labels[selection.action_id],
            )
            for selection in step.selections
        )
        scalar_labels = {
            replay.battle_id: relabelled_battle_id,
            **instance_labels,
            **request_labels,
            **action_labels,
        }
        steps.append(
            replace(
                step,
                requests=requests,
                selections=selections,
                events=tuple(
                    relabel_event(event, scalar_labels) for event in step.events
                ),
                provisional_decision_ids=tuple(
                    provisional_labels[value]
                    for value in step.provisional_decision_ids
                ),
            )
        )
    return replace(
        replay,
        replay_id="cosmetic-replay-id",
        initial_state=initial_state,
        initial_events=initial_events,
        steps=tuple(steps),
        provisional_decision_ids=tuple(
            provisional_labels[value] for value in replay.provisional_decision_ids
        ),
        source_manifest_ids=tuple(
            f"cosmetic-source-{index}"
            for index, _ in enumerate(replay.source_manifest_ids)
        ),
    )


def _corpus(
    *,
    corpus_id: str,
    role: str,
    capability_set: TargetCapabilitySet,
    scenarios: tuple[EngineScenarioV2, ...],
):
    return build_engine_scenario_corpus_v2(
        corpus_id=corpus_id,
        corpus_role=role,
        target_capability_set_hash=capability_set.capability_set_hash,
        catalog_hash=capability_set.catalog_hash,
        ruleset_hash=capability_set.ruleset_hash,
        scenarios=scenarios,
    )


def _artifacts():
    engine, fixture = _simulation()
    replays = tuple(
        run_battle(engine, fixture.initial_state, seed=seed).replay
        for seed in (20260711, 20260712, 20260713)
    )
    damage_sources = tuple(
        {
            str(dict(event.details)["source"])
            for step in replay.steps
            for event in step.events
            if event.kind is BattleEventKind.DAMAGE
            and isinstance(dict(event.details).get("source"), str)
            and any(
                candidate.kind is BattleEventKind.MOVE_USED
                and dict(candidate.details).get("move_id")
                == dict(event.details).get("source")
                and candidate.actor == event.actor
                for candidate in step.events[: step.events.index(event)]
            )
        }
        for replay in replays
    )
    shared_sources = set.intersection(*damage_sources)
    assert shared_sources
    move_id = sorted(shared_sources)[0]
    capability_set = _target_set(engine, ("move.damage", "move", move_id))
    capability_id = capability_set.capabilities[0].capability_id
    first = _scenario(
        scenario_id="scenario-development-a",
        role="development",
        capability_set=capability_set,
        capability_id=capability_id,
        replay=replays[0],
        lineage_tag="development-a",
    )
    second = _scenario(
        scenario_id="scenario-development-b",
        role="development",
        capability_set=capability_set,
        capability_id=capability_id,
        replay=replays[1],
        lineage_tag="development-b",
    )
    holdout = _scenario(
        scenario_id="scenario-holdout-a",
        role="external_holdout",
        capability_set=capability_set,
        capability_id=capability_id,
        replay=replays[2],
        lineage_tag="holdout-a",
    )
    development = _corpus(
        corpus_id="development-scenario-corpus",
        role="development",
        capability_set=capability_set,
        scenarios=(second, first),
    )
    external_holdout = _corpus(
        corpus_id="external-holdout-scenario-corpus",
        role="external_holdout",
        capability_set=capability_set,
        scenarios=(holdout,),
    )
    replay_map = {first.scenario_id: replays[0], second.scenario_id: replays[1]}
    return (
        engine,
        capability_set,
        replays,
        first,
        second,
        holdout,
        development,
        external_holdout,
        replay_map,
    )


def test_scenario_partition_and_probe_report_are_deterministic_and_schema_valid() -> None:
    (
        engine,
        capability_set,
        _,
        first,
        second,
        _,
        development,
        external_holdout,
        replay_map,
    ) = _artifacts()
    partition = build_scenario_partition_manifest_v2(
        development=development,
        external_holdout=external_holdout,
    )
    report = build_engine_probe_report_v2(
        engine=engine,
        capability_set=capability_set,
        development_corpus=development,
        replays=replay_map,
    )

    assert development.scenarios == (first, second)
    assert sum(probe.probe_role == "primary" for probe in report.probes) == 1
    assert sum(probe.probe_role == "supplemental" for probe in report.probes) == 1
    assert report.verified_pass_probe_count == report.required_probe_count == 1
    assert report.verified_scenario_probe_count == report.scenario_probe_count == 2
    assert report.silent_fallback_count == 0
    assert report.to_json() == build_engine_probe_report_v2(
        engine=engine,
        capability_set=capability_set,
        development_corpus=development,
        replays=dict(reversed(tuple(replay_map.items()))),
    ).to_json()
    partition.validate_against(development, external_holdout)
    report.validate_against(
        engine=engine,
        capability_set=capability_set,
        development_corpus=development,
        replays=replay_map,
    )

    for document, schema_name in (
        (development.to_data(), "sim02b-scenario-corpus.schema.json"),
        (partition.to_data(), "sim02b-scenario-partition.schema.json"),
        (report.to_data(), "sim02b-engine-probe-report.schema.json"),
    ):
        schema = json.loads((SCHEMAS / schema_name).read_text(encoding="utf-8"))
        validate_document_contract(document, schema, schema_name)


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("target_capability_set_hash", "0" * 64),
        ("initial_state_hash", "0" * 64),
        ("choice_sequence_hash", "0" * 64),
        ("seed", 1),
        ("catalog_hash", "0" * 64),
        ("ruleset_hash", "0" * 64),
        ("replay_hash", "0" * 64),
        ("witness_step_index", 99_999),
        ("witness_event_index", 99_999),
        ("witness_event_kind", "turn_started"),
        ("witness_event_hash", "0" * 64),
    ),
)
def test_probe_rejects_every_scenario_binding_mutation(
    field: str,
    replacement: object,
) -> None:
    engine, capability_set, replays, scenario, *_ = _artifacts()
    attacked = replace(scenario, **{field: replacement})
    with pytest.raises(PromotionScenarioError):
        verify_engine_probe_v2(
            engine=engine,
            capability_set=capability_set,
            scenario=attacked,
            replay=replays[0],
        )


def test_probe_recomputes_execution_hash_from_bound_replay() -> None:
    engine, capability_set, replays, scenario, *_ = _artifacts()
    attacked = replace(scenario, replay_execution_hash="0" * 64)

    with pytest.raises(
        PromotionScenarioError,
        match="replay_execution_hash",
    ):
        verify_engine_probe_v2(
            engine=engine,
            capability_set=capability_set,
            scenario=attacked,
            replay=replays[0],
        )


def test_probe_rejects_rng_algorithm_and_replay_body_mutations() -> None:
    engine, capability_set, replays, scenario, *_ = _artifacts()

    attacked_scenario = replace(scenario)
    object.__setattr__(attacked_scenario, "rng_algorithm_id", "rng-attacked")
    with pytest.raises(PromotionScenarioError, match="RNG"):
        verify_engine_probe_v2(
            engine=engine,
            capability_set=capability_set,
            scenario=attacked_scenario,
            replay=replays[0],
        )

    replay = replays[0]
    step = replay.steps[scenario.witness_step_index]
    event = step.events[scenario.witness_event_index]
    details = dict(event.details)
    details["amount"] = int(details["amount"]) + 1
    attacked_event = replace(event, details=tuple(details.items()))
    attacked_step = replace(
        step,
        events=(
            *step.events[: scenario.witness_event_index],
            attacked_event,
            *step.events[scenario.witness_event_index + 1 :],
        ),
    )
    attacked_replay = replace(
        replay,
        steps=(
            *replay.steps[: scenario.witness_step_index],
            attacked_step,
            *replay.steps[scenario.witness_step_index + 1 :],
        ),
    )
    with pytest.raises(PromotionScenarioError, match="re-execution"):
        verify_engine_probe_v2(
            engine=engine,
            capability_set=capability_set,
            scenario=scenario,
            replay=attacked_replay,
        )


def test_valid_damage_replay_cannot_prove_an_ability_by_capability_id_swap() -> None:
    engine, _, replays, _, *_ = _artifacts()
    _, _, move_id = _damage_witness(replays[0])
    ability_id = str(engine.catalog.abilities[0].ability_id)
    capability_set = _target_set(
        engine,
        ("move.damage", "move", move_id),
        ("ability.rough_skin", "ability", ability_id),
    )
    move_capability, ability_capability = capability_set.capabilities
    scenario = _scenario(
        scenario_id="scenario-capability-swap",
        role="development",
        capability_set=capability_set,
        capability_id=move_capability.capability_id,
        replay=replays[0],
        lineage_tag="capability-swap",
    )

    verify_engine_probe_v2(
        engine=engine,
        capability_set=capability_set,
        scenario=scenario,
        replay=replays[0],
    )
    attacked = replace(scenario, capability_id=ability_capability.capability_id)
    with pytest.raises(PromotionScenarioError, match="witness kind"):
        verify_engine_probe_v2(
            engine=engine,
            capability_set=capability_set,
            scenario=attacked,
            replay=replays[0],
        )


@pytest.mark.parametrize(
    ("field", "expected"),
    (
        ("source_lineage_ids", "source_lineage_overlap"),
        ("collection_lineage_ids", "collection_lineage_overlap"),
        ("authoring_lineage_ids", "authoring_lineage_overlap"),
    ),
)
def test_partition_rejects_each_lineage_overlap(field: str, expected: str) -> None:
    *_, first, _, holdout, development, _, _ = _artifacts()
    attacked = replace(holdout, **{field: getattr(first, field)})
    attacked_holdout = _corpus(
        corpus_id="attacked-holdout-corpus",
        role="external_holdout",
        capability_set=_artifacts()[1],
        scenarios=(attacked,),
    )
    with pytest.raises(PromotionScenarioError, match=expected):
        build_scenario_partition_manifest_v2(
            development=development,
            external_holdout=attacked_holdout,
        )


def test_partition_rejects_executable_and_replay_hash_overlap() -> None:
    (
        _, capability_set, _, first, _, _, development, _, _,
    ) = _artifacts()
    relabelled = replace(
        first,
        scenario_id="scenario-relabelled-as-holdout",
        partition_role="external_holdout",
        source_lineage_ids=("source-relabelled",),
        collection_lineage_ids=("collection-relabelled",),
        authoring_lineage_ids=("author-relabelled",),
    )
    attacked_holdout = _corpus(
        corpus_id="relabelled-holdout-corpus",
        role="external_holdout",
        capability_set=capability_set,
        scenarios=(relabelled,),
    )
    with pytest.raises(
        PromotionScenarioError,
        match=(
            "scenario_hash_overlap,replay_hash_overlap,"
            "replay_execution_hash_overlap"
        ),
    ):
        build_scenario_partition_manifest_v2(
            development=development,
            external_holdout=attacked_holdout,
        )


def test_partition_rejects_semantic_replay_overlap_after_all_id_relabelling() -> None:
    (
        _, capability_set, replays, first, _, _, development, _, _,
    ) = _artifacts()
    relabelled_replay = _cosmetically_relabel_replay(replays[0])

    assert relabelled_replay.replay_hash != replays[0].replay_hash
    assert replay_choice_sequence_hash(relabelled_replay) != first.choice_sequence_hash
    assert replay_execution_hash_v2(relabelled_replay) == (
        first.replay_execution_hash
    )

    relabelled_scenario = _scenario(
        scenario_id="scenario-cosmetically-relabeled-holdout",
        role="external_holdout",
        capability_set=capability_set,
        capability_id=first.capability_id,
        replay=relabelled_replay,
        lineage_tag="cosmetically-relabeled-holdout",
    )
    assert relabelled_scenario.scenario_hash != first.scenario_hash
    attacked_holdout = _corpus(
        corpus_id="cosmetically-relabeled-holdout-corpus",
        role="external_holdout",
        capability_set=capability_set,
        scenarios=(relabelled_scenario,),
    )

    with pytest.raises(
        PromotionScenarioError,
        match="replay_execution_hash_overlap",
    ):
        build_scenario_partition_manifest_v2(
            development=development,
            external_holdout=attacked_holdout,
        )


def test_replay_execution_hash_changes_with_battle_substance() -> None:
    replay = _artifacts()[2][0]
    step_index, event_index, _ = _damage_witness(replay)
    step = replay.steps[step_index]
    event = step.events[event_index]
    details = dict(event.details)
    details["amount"] = int(details["amount"]) + 1
    attacked_event = replace(event, details=tuple(details.items()))
    attacked_step = replace(
        step,
        events=(
            *step.events[:event_index],
            attacked_event,
            *step.events[event_index + 1 :],
        ),
    )
    attacked_replay = replace(
        replay,
        steps=(
            *replay.steps[:step_index],
            attacked_step,
            *replay.steps[step_index + 1 :],
        ),
    )

    assert replay_execution_hash_v2(attacked_replay) != (
        replay_execution_hash_v2(replay)
    )


def test_corpora_and_report_fail_closed_on_empty_missing_and_extra_inputs() -> None:
    (
        engine,
        capability_set,
        replays,
        first,
        _,
        _,
        development,
        _,
        replay_map,
    ) = _artifacts()
    with pytest.raises(PromotionScenarioError, match="empty"):
        _corpus(
            corpus_id="empty-corpus",
            role="development",
            capability_set=capability_set,
            scenarios=(),
        )

    with pytest.raises(PromotionScenarioError, match="artifact set"):
        build_engine_probe_report_v2(
            engine=engine,
            capability_set=capability_set,
            development_corpus=development,
            replays={first.scenario_id: replays[0]},
        )
    with pytest.raises(PromotionScenarioError, match="artifact set"):
        build_engine_probe_report_v2(
            engine=engine,
            capability_set=capability_set,
            development_corpus=development,
            replays={**replay_map, "extra-scenario": replays[2]},
        )

    _, _, move_id = _damage_witness(replays[0])
    expanded = _target_set(
        engine,
        ("move.damage", "move", move_id),
        ("ability.rough_skin", "ability", str(engine.catalog.abilities[0].ability_id)),
    )
    expanded_first = replace(
        first,
        target_capability_set_hash=expanded.capability_set_hash,
        capability_id=expanded.capabilities[0].capability_id,
    )
    incomplete = _corpus(
        corpus_id="incomplete-capability-corpus",
        role="development",
        capability_set=expanded,
        scenarios=(expanded_first,),
    )
    with pytest.raises(PromotionScenarioError, match="lack development scenarios"):
        build_engine_probe_report_v2(
            engine=engine,
            capability_set=expanded,
            development_corpus=incomplete,
            replays={expanded_first.scenario_id: replays[0]},
        )


def test_all_new_schemas_reject_missing_and_unknown_fields() -> None:
    (
        engine,
        capability_set,
        _,
        _,
        _,
        _,
        development,
        external_holdout,
        replay_map,
    ) = _artifacts()
    partition = build_scenario_partition_manifest_v2(
        development=development,
        external_holdout=external_holdout,
    )
    report = build_engine_probe_report_v2(
        engine=engine,
        capability_set=capability_set,
        development_corpus=development,
        replays=replay_map,
    )
    for document, schema_name in (
        (development.to_data(), "sim02b-scenario-corpus.schema.json"),
        (partition.to_data(), "sim02b-scenario-partition.schema.json"),
        (report.to_data(), "sim02b-engine-probe-report.schema.json"),
    ):
        schema = json.loads((SCHEMAS / schema_name).read_text(encoding="utf-8"))
        missing = dict(document)
        missing.pop(next(iter(schema["required"])))
        with pytest.raises(BundleValidationError):
            validate_document_contract(missing, schema, schema_name)
        extra = {**document, "caller_verified": True}
        with pytest.raises(BundleValidationError):
            validate_document_contract(extra, schema, schema_name)
