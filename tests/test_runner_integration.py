from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from champions_sim import (  # noqa: E402
    BattleEngine,
    load_battle_fixture,
    load_catalog,
    load_ruleset,
    run_battle,
    run_random_batch,
)
from champions_sim.core import BattlePhase, PlayerId  # noqa: E402
from champions_sim.policies import ScriptedPolicy  # noqa: E402


def _loaded() -> tuple[BattleEngine, object]:
    catalog = load_catalog(ROOT / "data/fixtures/sim01_catalog.json")
    ruleset = load_ruleset(ROOT / "data/fixtures/sim01_ruleset.json")
    fixture = load_battle_fixture(
        ROOT / "data/fixtures/sim01_battle.json",
        catalog=catalog,
        ruleset=ruleset,
    )
    return BattleEngine(catalog, ruleset), fixture.initial_state


def test_same_seed_is_byte_reproducible_across_one_hundred_runs() -> None:
    engine, initial_state = _loaded()
    first = run_battle(engine, initial_state, seed=20260713)  # type: ignore[arg-type]
    assert first.final_state.phase is BattlePhase.FINISHED
    expected_json = first.replay.to_json()
    for _ in range(99):
        repeated = run_battle(engine, initial_state, seed=20260713)  # type: ignore[arg-type]
        assert repeated.replay.to_json() == expected_json
        assert repeated.replay.replay_hash == first.replay.replay_hash
        assert repeated.engine_rng == first.engine_rng


def test_scripted_policy_completes_a_battle() -> None:
    engine, initial_state = _loaded()
    policy = ScriptedPolicy(
        {
            PlayerId.P1: ("move:dragon_claw",) * 24,
            PlayerId.P2: ("move:waterfall",) * 24,
        }
    )
    run = run_battle(
        engine,
        initial_state,  # type: ignore[arg-type]
        seed=7331,
        policies={PlayerId.P1: policy, PlayerId.P2: policy},
    )

    assert run.final_state.phase is BattlePhase.FINISHED
    assert run.decision_windows > 0
    assert run.event_count > run.decision_windows
    assert run.replay.steps[-1].terminal


def test_random_batch_completes_and_repeats_exactly() -> None:
    engine, initial_state = _loaded()
    first = run_random_batch(
        engine,
        initial_state,  # type: ignore[arg-type]
        battles=32,
        seed_start=1000,
    )
    second = run_random_batch(
        engine,
        initial_state,  # type: ignore[arg-type]
        battles=32,
        seed_start=1000,
    )

    assert first == second
    assert first.battles == 32
    assert first.p1_wins + first.p2_wins + first.draws == 32
    assert len(first.final_hashes) == 32
    assert first.decision_windows > 0
    assert first.events > first.decision_windows
