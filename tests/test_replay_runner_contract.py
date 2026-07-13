from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from champions_sim import (
    BattleEngine,
    ReplayVerificationError,
    load_battle_fixture,
    load_catalog,
    load_ruleset,
    run_battle,
    verify_replay,
)
from champions_sim.core import (
    BattleEventKind,
    BattlePhase,
    REPLAY_SCHEMA_VERSION,
    RNG_ALGORITHM_ID,
    ReplayRecord,
)


ROOT = Path(__file__).resolve().parents[1]


def _simulation() -> tuple[BattleEngine, object]:
    catalog = load_catalog(ROOT / "data/fixtures/sim01_catalog.json")
    ruleset = load_ruleset(ROOT / "data/fixtures/sim01_ruleset.json")
    fixture = load_battle_fixture(
        ROOT / "data/fixtures/sim01_battle.json",
        catalog=catalog,
        ruleset=ruleset,
    )
    return BattleEngine(catalog, ruleset), fixture


def test_runner_emits_self_contained_versioned_replay() -> None:
    engine, fixture = _simulation()
    run = run_battle(engine, fixture.initial_state, seed=20260713)
    replay = run.replay

    assert replay.schema_version == REPLAY_SCHEMA_VERSION
    assert replay.rng_algorithm_id == RNG_ALGORITHM_ID
    assert replay.initial_state.payload == fixture.initial_state
    assert replay.initial_state.payload.phase is BattlePhase.TEAM_PREVIEW
    assert replay.initial_events == run.initial_events
    assert replay.initial_events[0].kind is BattleEventKind.BATTLE_STARTED
    assert replay.initialized_state_hash != replay.initial_state.state_hash
    assert replay.bundle.ruleset_content_hash == engine.ruleset.snapshot_hash
    assert replay.bundle.catalog_content_hash == engine.catalog.snapshot_hash
    assert (
        replay.bundle.engine_semantics_version
        == engine.ruleset.engine_semantics_version
    )
    assert replay.provisional_decision_ids == engine.ruleset.provisional_decision_ids
    assert replay.provisional_decision_ids == ("PD-003", "PD-004", "PD-007")
    assert engine.catalog.source_manifest_id in replay.source_manifest_ids

    restored = ReplayRecord.from_json(replay.to_json())
    assert restored == replay
    assert verify_replay(engine, restored) == run.final_state


def test_replay_verifier_detects_bundle_and_initialization_drift() -> None:
    engine, fixture = _simulation()
    replay = run_battle(engine, fixture.initial_state, seed=7).replay

    wrong_bundle = replace(replay.bundle, catalog_content_hash="0" * 64)
    with pytest.raises(ReplayVerificationError, match="catalog_content_hash"):
        verify_replay(engine, replace(replay, bundle=wrong_bundle))

    with pytest.raises(ReplayVerificationError, match="initial_events"):
        verify_replay(engine, replace(replay, initial_events=()))


def test_replay_verifier_detects_action_and_transition_drift() -> None:
    engine, fixture = _simulation()
    replay = run_battle(engine, fixture.initial_state, seed=11).replay
    first = replay.steps[0]
    p1_request = first.requests.for_player(first.selections[0].player)
    assert p1_request is not None
    alternatives = [
        action
        for action in p1_request.legal_actions
        if action.action_id != first.selections[0].action_id
    ]
    assert alternatives
    changed_selection = replace(
        first.selections[0], action_id=alternatives[0].action_id
    )
    changed_step = replace(
        first,
        selections=(changed_selection, *first.selections[1:]),
    )
    changed_replay = replace(replay, steps=(changed_step, *replay.steps[1:]))

    with pytest.raises(ReplayVerificationError, match=r"step\[0\]"):
        verify_replay(engine, changed_replay)

    omitted_provisional = replace(first, provisional_decision_ids=())
    with pytest.raises(
        ReplayVerificationError,
        match=r"step\[0\]\.provisional_decision_ids",
    ):
        verify_replay(
            engine,
            replace(replay, steps=(omitted_provisional, *replay.steps[1:])),
        )
