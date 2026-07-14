from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from champions_sim import BattleEngine, load_battle_fixture, load_catalog, load_ruleset
from champions_sim.arena import (
    ArenaPlan,
    EvaluationPartition,
    competitive_baseline_binding,
    random_reference_binding,
    run_paired_arena,
)
from champions_sim.core import MoveId, PlayerId, PokemonInstanceId, canonical_hash
from champions_sim.prebattle import (
    FirstThreeTeamSelectionPolicy,
    TeamPreviewRoster,
    TeamPreviewSession,
    TypeCoverageTeamSelectionPolicy,
    run_team_preview,
)


ROOT = Path(__file__).resolve().parents[1]


def _inputs():
    catalog = load_catalog(ROOT / "data/fixtures/sim01_catalog.json")
    ruleset = load_ruleset(ROOT / "data/fixtures/sim01_ruleset.json")
    fixture = load_battle_fixture(
        ROOT / "data/fixtures/sim01_battle.json",
        catalog=catalog,
        ruleset=ruleset,
    )
    rosters = {}
    for player in (PlayerId.P1, PlayerId.P2):
        originals = fixture.initial_state.side(player).team
        reserves = tuple(
            replace(
                member,
                instance_id=PokemonInstanceId(f"{member.instance_id}-reserve"),
                item_id=None,
            )
            for member in originals
        )
        rosters[player] = TeamPreviewRoster(
            player=player,
            members=(*originals, *reserves),
        )
    session = TeamPreviewSession.create(
        session_id="ai01-selection-baseline-v1",
        battle_id="ai01-selection-battle-v1",
        catalog=catalog,
        ruleset=ruleset,
        p1_roster=rosters[PlayerId.P1],
        p2_roster=rosters[PlayerId.P2],
    )
    return catalog, ruleset, fixture, session


def _run_preview(session, catalog):
    policies = _preview_policies(catalog)
    return run_team_preview(
        session,
        policies=policies,
        seed=20260714,
    )


def _preview_policies(catalog):
    return {
        PlayerId.P1: TypeCoverageTeamSelectionPolicy(catalog),
        PlayerId.P2: FirstThreeTeamSelectionPolicy(),
    }


def test_type_coverage_selection_is_deterministic_and_materializable() -> None:
    catalog, ruleset, fixture, session = _inputs()
    first = _run_preview(session, catalog)
    second = _run_preview(session, catalog)

    assert first.selections == second.selections
    assert first.session.session_hash == second.session.session_hash
    for _, selection in first.selections:
        assert len(selection) == 3
        assert len(set(selection)) == 3
    state = first.session.materialize()
    initialized = BattleEngine(catalog, ruleset).initialize(state, fixture.rng)
    assert initialized.next_decisions is not None


def test_selection_policy_cannot_observe_opponent_private_set_mutation() -> None:
    catalog, _, _, session = _inputs()
    p2 = session.roster(PlayerId.P2)
    member = p2.members[0]
    changed_move = replace(member.moves[0], move_id=MoveId("private-opponent-move"))
    changed_member = replace(member, moves=(changed_move, *member.moves[1:]))
    changed_p2 = TeamPreviewRoster(
        player=PlayerId.P2,
        members=(changed_member, *p2.members[1:]),
    )
    changed_session = replace(
        session,
        rosters=(session.roster(PlayerId.P1), changed_p2),
        commitments=(),
        reveals=(),
    )
    policy = TypeCoverageTeamSelectionPolicy(catalog)
    original_observation = session.observation_for(PlayerId.P1)
    changed_observation = changed_session.observation_for(PlayerId.P1)
    assert original_observation == changed_observation

    from champions_sim.core import ExplicitRNG

    original_selection, _ = policy.select(
        original_observation, ExplicitRNG.seeded(1)
    )
    changed_selection, _ = policy.select(
        changed_observation, ExplicitRNG.seeded(1)
    )
    assert original_selection == changed_selection


def test_sealed_team_preview_flows_into_paired_arena_identity() -> None:
    catalog, ruleset, _, session = _inputs()
    preview = _run_preview(session, catalog)
    state = preview.session.materialize()
    engine = BattleEngine(catalog, ruleset)
    candidate = competitive_baseline_binding(catalog)
    opponent = random_reference_binding()
    preview_policies = _preview_policies(catalog)
    plan = ArenaPlan(
        plan_id="ai01-prebattle-through-arena-v1",
        scenario_id="ai01-six-to-three-synthetic-v1",
        partition=EvaluationPartition.DEVELOPMENT,
        pair_count=2,
        engine_seed_start=500,
        agent_seed_start=800,
        catalog_id=catalog.catalog_id,
        catalog_hash=catalog.snapshot_hash,
        ruleset_id=str(ruleset.ruleset_id),
        ruleset_hash=ruleset.snapshot_hash,
        initial_state_hash=canonical_hash(state),
        candidate=candidate.identity,
        opponent=opponent.identity,
        prebattle_session_hash=preview.session.session_hash,
        prebattle_proof_hash=preview.proof.proof_hash,
    )
    arena = run_paired_arena(
        engine,
        state,
        plan=plan,
        candidate=candidate,
        opponent=opponent,
        prebattle_run=preview,
        prebattle_policies=preview_policies,
    )

    assert arena.report.plan.prebattle_session_hash == preview.session.session_hash
    assert arena.report.plan.prebattle_proof_hash == preview.proof.proof_hash
    assert arena.report.summary.matches == 4
    assert arena.report.summary.replay_verification_rate_ppm == 1_000_000

    with pytest.raises(ValueError, match="prebattle evidence"):
        run_paired_arena(
            engine,
            state,
            plan=replace(plan, prebattle_session_hash="0" * 64),
            candidate=candidate,
            opponent=opponent,
            prebattle_run=preview,
            prebattle_policies=preview_policies,
        )
    with pytest.raises(ValueError, match="requires its run"):
        run_paired_arena(
            engine,
            state,
            plan=plan,
            candidate=candidate,
            opponent=opponent,
        )
