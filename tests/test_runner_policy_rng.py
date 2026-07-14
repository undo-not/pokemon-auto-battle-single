from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from champions_sim import BattleEngine, load_battle_fixture, load_catalog, load_ruleset
from champions_sim.core import ExplicitRNG, PlayerId
from champions_sim.policies import FirstLegalPolicy
from champions_sim.runner import run_battle


ROOT = Path(__file__).resolve().parents[1]


def _loaded():
    catalog = load_catalog(ROOT / "data/fixtures/sim01_catalog.json")
    ruleset = load_ruleset(ROOT / "data/fixtures/sim01_ruleset.json")
    fixture = load_battle_fixture(
        ROOT / "data/fixtures/sim01_battle.json",
        catalog=catalog,
        ruleset=ruleset,
    )
    return BattleEngine(catalog, ruleset), fixture.initial_state


@dataclass
class RngAuditPolicy:
    observed_seeds: list[int]

    def select(self, request, observation, rng):
        self.observed_seeds.append(rng.seed)
        return FirstLegalPolicy().select(request, observation, rng)


def test_role_labels_keep_policy_rng_roots_fixed_when_seats_swap() -> None:
    engine, state = _loaded()
    policy_seed = 20260714
    candidate_p1: list[int] = []
    opponent_p2: list[int] = []
    run_battle(
        engine,
        state,
        seed=71,
        policy_seed=policy_seed,
        policies={
            PlayerId.P1: RngAuditPolicy(candidate_p1),
            PlayerId.P2: RngAuditPolicy(opponent_p2),
        },
        policy_rng_labels={
            PlayerId.P1: "candidate",
            PlayerId.P2: "opponent",
        },
    )

    opponent_p1: list[int] = []
    candidate_p2: list[int] = []
    run_battle(
        engine,
        state,
        seed=71,
        policy_seed=policy_seed,
        policies={
            PlayerId.P1: RngAuditPolicy(opponent_p1),
            PlayerId.P2: RngAuditPolicy(candidate_p2),
        },
        policy_rng_labels={
            PlayerId.P1: "opponent",
            PlayerId.P2: "candidate",
        },
    )

    root = ExplicitRNG.seeded(policy_seed)
    candidate_seed = root.branch("policy:candidate").seed
    opponent_seed = root.branch("policy:opponent").seed
    assert candidate_p1 and candidate_p2 and opponent_p1 and opponent_p2
    assert set(candidate_p1) == set(candidate_p2) == {candidate_seed}
    assert set(opponent_p1) == set(opponent_p2) == {opponent_seed}
    assert candidate_seed != opponent_seed


def test_default_policy_rng_branches_remain_p1_and_p2() -> None:
    engine, state = _loaded()
    policy_seed = 991
    default_p1: list[int] = []
    default_p2: list[int] = []
    default_run = run_battle(
        engine,
        state,
        seed=37,
        policy_seed=policy_seed,
        policies={
            PlayerId.P1: RngAuditPolicy(default_p1),
            PlayerId.P2: RngAuditPolicy(default_p2),
        },
    )
    explicit_run = run_battle(
        engine,
        state,
        seed=37,
        policy_seed=policy_seed,
        policies={
            PlayerId.P1: FirstLegalPolicy(),
            PlayerId.P2: FirstLegalPolicy(),
        },
        policy_rng_labels={PlayerId.P1: "p1", PlayerId.P2: "p2"},
    )

    root = ExplicitRNG.seeded(policy_seed)
    assert set(default_p1) == {root.branch("policy:p1").seed}
    assert set(default_p2) == {root.branch("policy:p2").seed}
    assert default_run.replay.to_json() == explicit_run.replay.to_json()


@pytest.mark.parametrize(
    "labels, message",
    [
        ({PlayerId.P1: "candidate"}, "exactly p1 and p2"),
        (
            {
                PlayerId.P1: "candidate",
                PlayerId.P2: "opponent",
                "spectator": "unused",
            },
            "exactly p1 and p2",
        ),
        ({PlayerId.P1: "", PlayerId.P2: "opponent"}, "non-empty string"),
        ({PlayerId.P1: "   ", PlayerId.P2: "opponent"}, "non-empty string"),
        ({PlayerId.P1: "same", PlayerId.P2: "same"}, "must be distinct"),
    ],
)
def test_policy_rng_labels_reject_ambiguous_mappings(labels, message: str) -> None:
    engine, state = _loaded()
    with pytest.raises(ValueError, match=message):
        run_battle(
            engine,
            state,
            seed=1,
            policies={
                PlayerId.P1: FirstLegalPolicy(),
                PlayerId.P2: FirstLegalPolicy(),
            },
            policy_rng_labels=labels,
        )
