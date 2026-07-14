from __future__ import annotations

from dataclasses import dataclass, fields, replace
import json
from pathlib import Path

import pytest

from champions_sim import BattleEngine, load_battle_fixture, load_catalog, load_ruleset
from champions_sim.arena import (
    ArenaPlan,
    ArenaReport,
    ArenaRun,
    BoundAgent,
    EvaluationPartition,
    MatchLeg,
    TypeAwareDamagePolicy,
    bind_agent,
    materialize_arena_leg,
    random_legal_agent_binding,
    resolve_arena_run,
    run_paired_arena,
    type_aware_agent_binding,
    verify_arena_run,
)
from champions_sim.core import (
    ActionSelection,
    BattleState,
    ExplicitRNG,
    MoveId,
    PlayerId,
    PlayerObservation,
    ReplayRecord,
    canonical_hash,
)
from champions_sim.policies import FirstLegalPolicy, RandomLegalPolicy
from champions_sim.runner import run_battle
from champions_sim.arena.models import _signed_ratio_ppm
from scripts.validate_sim01_bundle import BundleValidationError, validate_document_contract


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


def _plan(engine, state, *, pairs: int = 4) -> ArenaPlan:
    candidate = type_aware_agent_binding(engine.catalog)
    opponent = random_legal_agent_binding()
    return ArenaPlan(
        plan_id="ai01-sim01-type-aware-vs-random",
        scenario_id="sim01-frozen-battle-v1",
        partition=EvaluationPartition.DEVELOPMENT,
        pair_count=pairs,
        engine_seed_start=1000,
        agent_seed_start=9000,
        catalog_id=engine.catalog.catalog_id,
        catalog_hash=engine.catalog.snapshot_hash,
        ruleset_id=str(engine.ruleset.ruleset_id),
        ruleset_hash=engine.ruleset.snapshot_hash,
        initial_state_hash=canonical_hash(state),
        candidate=candidate.identity,
        opponent=opponent.identity,
    )


def _run(pairs: int = 4):
    engine, state = _loaded()
    candidate = type_aware_agent_binding(engine.catalog)
    opponent = random_legal_agent_binding()
    return run_paired_arena(
        engine,
        state,
        plan=_plan(engine, state, pairs=pairs),
        candidate=candidate,
        opponent=opponent,
    )


def test_paired_arena_is_byte_reproducible_and_replay_verified() -> None:
    first = _run(4)
    second = _run(4)

    assert first.report.to_json() == second.report.to_json()
    assert first.report.report_hash == second.report.report_hash
    assert len(first.report.matches) == 8
    assert len(first.replays) == 8
    assert first.report.summary.pair_completeness_rate_ppm == 1_000_000
    assert first.report.summary.legal_action_rate_ppm == 1_000_000
    assert first.report.summary.replay_verification_rate_ppm == 1_000_000
    assert first.report.summary.private_state_delivery_violation_count == 0
    assert not first.report.champions_candidate
    assert first.report.rank1_equivalence_status == "unmeasured"
    assert not first.report.rank1_equivalence_claim_allowed
    assert "policy_process_isolation_not_implemented" in first.report.blockers
    schema = json.loads(
        (ROOT / "data/schemas/ai01-arena-report.schema.json").read_text(
            encoding="utf-8"
        )
    )
    validate_document_contract(
        json.loads(first.report.to_json()), schema, "AI-01 arena report"
    )


@pytest.mark.parametrize(
    "blocker",
    (
        "champions_fidelity_not_verified",
        "policy_process_isolation_not_implemented",
        "rank1_external_calibration_missing",
    ),
)
def test_arena_report_schema_rejects_missing_mandatory_blocker(blocker: str) -> None:
    report = json.loads(_run(1).report.to_json())
    report["blockers"].remove(blocker)
    schema = json.loads(
        (ROOT / "data/schemas/ai01-arena-report.schema.json").read_text(
            encoding="utf-8"
        )
    )

    with pytest.raises(BundleValidationError, match="must contain at least one item"):
        validate_document_contract(report, schema, "AI-01 arena report")


@pytest.mark.parametrize(
    ("present_field", "missing_field"),
    (
        ("prebattle_session_hash", "prebattle_proof_hash"),
        ("prebattle_proof_hash", "prebattle_session_hash"),
    ),
)
def test_arena_report_schema_rejects_unpaired_prebattle_hash(
    present_field: str,
    missing_field: str,
) -> None:
    report = json.loads(_run(1).report.to_json())
    report["plan"][present_field] = "0" * 64
    schema = json.loads(
        (ROOT / "data/schemas/ai01-arena-report.schema.json").read_text(
            encoding="utf-8"
        )
    )

    with pytest.raises(BundleValidationError, match=missing_field):
        validate_document_contract(report, schema, "AI-01 arena report")


def test_side_swap_preserves_candidate_team_and_covers_both_seats() -> None:
    engine, state = _loaded()
    original_candidate = state.side(PlayerId.P1)
    p1_leg = materialize_arena_leg(state, 0, MatchLeg.CANDIDATE_P1)
    p2_leg = materialize_arena_leg(state, 0, MatchLeg.CANDIDATE_P2)

    assert tuple(item.pokemon_id for item in p1_leg.side(PlayerId.P1).team) == tuple(
        item.pokemon_id for item in original_candidate.team
    )
    assert tuple(item.pokemon_id for item in p2_leg.side(PlayerId.P2).team) == tuple(
        item.pokemon_id for item in original_candidate.team
    )
    assert all(
        str(item.instance_id).startswith(f"{side.player.value}-slot-")
        for materialized in (p1_leg, p2_leg)
        for side in materialized.sides
        for item in side.team
    )
    candidate = type_aware_agent_binding(engine.catalog)
    opponent = random_legal_agent_binding()
    report = run_paired_arena(
        engine,
        state,
        plan=_plan(engine, state, pairs=2),
        candidate=candidate,
        opponent=opponent,
    ).report
    for pair_index in range(2):
        pair = [item for item in report.matches if item.pair_index == pair_index]
        assert {item.candidate_player for item in pair} == {PlayerId.P1, PlayerId.P2}
        assert len({item.engine_seed for item in pair}) == 1
        assert len({item.agent_seed for item in pair}) == 1


def test_arena_public_identifiers_do_not_commit_opponent_private_set_data() -> None:
    _, state = _loaded()
    opponent = state.side(PlayerId.P2)
    member = opponent.team[0]
    changed_member = replace(
        member,
        item_id=None,
        moves=(
            replace(member.moves[0], move_id=MoveId("concealed-alternative-move")),
            *member.moves[1:],
        ),
        stats=replace(member.stats, attack=member.stats.attack + 1),
    )
    changed_state = replace(
        state,
        sides=(
            state.side(PlayerId.P1),
            replace(opponent, team=(changed_member, *opponent.team[1:])),
        ),
    )

    original_leg = materialize_arena_leg(
        state,
        7,
        MatchLeg.CANDIDATE_P1,
        arena_namespace="public-plan-and-scenario",
    )
    changed_leg = materialize_arena_leg(
        changed_state,
        7,
        MatchLeg.CANDIDATE_P1,
        arena_namespace="public-plan-and-scenario",
    )

    def public_identifiers(materialized):
        return (
            materialized.battle_id,
            materialized.ruleset_id,
            tuple(
                (
                    side.player,
                    side.active_instance_id,
                    tuple(pokemon.instance_id for pokemon in side.team),
                )
                for side in materialized.sides
            ),
        )

    assert public_identifiers(original_leg) == public_identifiers(changed_leg)
    assert original_leg != changed_leg


def test_arena_rejects_plan_and_summary_forgery() -> None:
    engine, state = _loaded()
    plan = _plan(engine, state, pairs=1)
    candidate = type_aware_agent_binding(engine.catalog)
    opponent = random_legal_agent_binding()
    with pytest.raises(ValueError, match="bound inputs"):
        run_paired_arena(
            engine,
            state,
            plan=replace(plan, initial_state_hash="0" * 64),
            candidate=candidate,
            opponent=opponent,
        )

    report = run_paired_arena(
        engine,
        state,
        plan=plan,
        candidate=candidate,
        opponent=opponent,
    ).report
    with pytest.raises(ValueError, match="outcomes|recomputed"):
        replace(
            report,
            summary=replace(report.summary, wins=report.summary.wins + 1),
        )
    with pytest.raises(ValueError, match="exactly two"):
        replace(report, matches=report.matches[:1])

    with pytest.raises(ValueError, match="unsigned 64-bit"):
        replace(plan, engine_seed_start=1 << 64)
    with pytest.raises(ValueError, match="unsigned 64-bit"):
        replace(plan, agent_seed_start=(1 << 64) - 1, pair_count=2)


def test_arena_rejects_polymorphic_report_replay_plan_and_run_forgery() -> None:
    engine, state = _loaded()
    candidate = type_aware_agent_binding(engine.catalog)
    opponent = random_legal_agent_binding()
    plan = _plan(engine, state, pairs=1)
    run = run_paired_arena(
        engine,
        state,
        plan=plan,
        candidate=candidate,
        opponent=opponent,
    )

    class ForgedArenaReport(ArenaReport):
        def __eq__(self, other):
            return True

        def __ne__(self, other):
            return False

    forged_report = ForgedArenaReport(
        **{field.name: getattr(run.report, field.name) for field in fields(ArenaReport)}
    )
    object.__setattr__(forged_report, "rank1_equivalence_claim_allowed", True)
    with pytest.raises(ValueError, match="exact ArenaReport"):
        ArenaRun(forged_report, run.replays)

    class ForgedReplay(ReplayRecord):
        def __eq__(self, other):
            return True

        def __ne__(self, other):
            return False

    forged_replay = ForgedReplay(
        **{
            field.name: getattr(run.replays[0], field.name)
            for field in fields(ReplayRecord)
        }
    )
    with pytest.raises(ValueError, match="exact ReplayRecord"):
        resolve_arena_run(
            engine,
            state,
            plan=plan,
            candidate=candidate,
            opponent=opponent,
            replays=(forged_replay, run.replays[1]),
        )

    class ForgedPlan(ArenaPlan):
        pass

    forged_plan = ForgedPlan(
        **{field.name: getattr(plan, field.name) for field in fields(ArenaPlan)}
    )
    with pytest.raises(ValueError, match="exact ArenaPlan"):
        run_paired_arena(
            engine,
            state,
            plan=forged_plan,
            candidate=candidate,
            opponent=opponent,
        )

    class ForgedArenaRun(ArenaRun):
        pass

    forged_run = ForgedArenaRun(run.report, run.replays)
    with pytest.raises(ValueError, match="exact ArenaRun"):
        verify_arena_run(
            engine,
            state,
            forged_run,
            candidate=candidate,
            opponent=opponent,
        )

    class ForgedBattleState(BattleState):
        pass

    forged_state = ForgedBattleState(
        **{field.name: getattr(state, field.name) for field in fields(BattleState)}
    )
    with pytest.raises(ValueError, match="exact BattleState"):
        run_paired_arena(
            engine,
            forged_state,
            plan=plan,
            candidate=candidate,
            opponent=opponent,
        )

    class ForgedBattleEngine(BattleEngine):
        pass

    with pytest.raises(ValueError, match="exact BattleEngine"):
        run_paired_arena(
            ForgedBattleEngine(engine.catalog, engine.ruleset),
            state,
            plan=plan,
            candidate=candidate,
            opponent=opponent,
        )


def test_arena_rejects_policy_instance_reuse() -> None:
    engine, state = _loaded()
    shared = TypeAwareDamagePolicy(engine.catalog)
    binding = bind_agent(
        agent_id="reused-type-aware",
        version="1",
        policy_type=TypeAwareDamagePolicy,
        factory=lambda: shared,
        configuration={"catalog_hash": engine.catalog.snapshot_hash},
    )
    plan = replace(_plan(engine, state, pairs=1), candidate=binding.identity)
    with pytest.raises(ValueError, match="reused an instance"):
        run_paired_arena(
            engine,
            state,
            plan=plan,
            candidate=binding,
            opponent=random_legal_agent_binding(),
        )


def test_type_aware_policy_uses_public_type_information() -> None:
    engine, state = _loaded()
    initialized = engine.initialize(state, ExplicitRNG.seeded(7))
    requests = engine.required_decisions(initialized.state)
    assert requests is not None
    request = requests.for_player(PlayerId.P1)
    assert request is not None
    selection, _ = TypeAwareDamagePolicy(engine.catalog).select(
        request,
        initialized.state.observation_for(PlayerId.P1),
        ExplicitRNG.seeded(99),
    )
    # Ground is ineffective against the revealed Flying opponent; Dragon Claw is neutral.
    assert selection.action_id.endswith("move:dragon_claw")


@dataclass(frozen=True, slots=True)
class ObservationAuditPolicy:
    def select(self, request, observation, rng):
        for pokemon in observation.opponent_side.pokemon:
            assert pokemon.hp is None
            assert pokemon.max_hp is None
            assert pokemon.hp_fraction_millionths is None
            assert pokemon.stats is None
        selection, rng = FirstLegalPolicy().select(request, observation, rng)
        return ActionSelection(
            request_id=selection.request_id,
            player=selection.player,
            action_id=selection.action_id,
        ), rng


@dataclass(frozen=True, slots=True)
class CollectionSensitivePolicy:
    mode: object

    def select(self, request, observation, rng):
        del observation
        action = (
            request.legal_actions[0]
            if isinstance(self.mode, list)
            else request.legal_actions[-1]
        )
        return ActionSelection(request.request_id, request.player, action.action_id), rng


def test_policy_boundary_delivers_no_opponent_private_state() -> None:
    engine, state = _loaded()
    audit = bind_agent(
        agent_id="observation-audit",
        version="1",
        policy_type=ObservationAuditPolicy,
        factory=ObservationAuditPolicy,
        configuration={"asserts": "opponent-private-fields-are-none"},
    )
    plan = replace(_plan(engine, state, pairs=1), candidate=audit.identity)
    run_paired_arena(
        engine,
        state,
        plan=plan,
        candidate=audit,
        opponent=random_legal_agent_binding(),
    )


def test_plan_identity_and_report_replay_evidence_are_bound() -> None:
    engine, state = _loaded()
    candidate = type_aware_agent_binding(engine.catalog)
    opponent = random_legal_agent_binding()
    plan = _plan(engine, state, pairs=1)
    with pytest.raises(ValueError, match="candidate_identity"):
        run_paired_arena(
            engine,
            state,
            plan=plan,
            candidate=opponent,
            opponent=opponent,
        )

    run = run_paired_arena(
        engine,
        state,
        plan=plan,
        candidate=candidate,
        opponent=opponent,
    )
    forged_record = replace(run.report.matches[0], replay_hash="0" * 64)
    forged_report = replace(
        run.report,
        matches=(forged_record, *run.report.matches[1:]),
    )
    with pytest.raises(ValueError, match="resolved Replay evidence"):
        verify_arena_run(
            engine,
            state,
            ArenaRun(forged_report, run.replays),
            candidate=candidate,
            opponent=opponent,
        )
    with pytest.raises(ValueError, match="initial state"):
        verify_arena_run(
            engine,
            state,
            ArenaRun(run.report, tuple(reversed(run.replays))),
            candidate=candidate,
            opponent=opponent,
        )


def test_bound_agent_rejects_runtime_state_and_identity_substitution() -> None:
    binding = random_legal_agent_binding()
    with pytest.raises(ValueError, match="initial state"):
        replace(binding, factory=lambda: RandomLegalPolicy(allow_forfeit=True))
    with pytest.raises(ValueError, match="identity"):
        replace(
            binding,
            identity=replace(binding.identity, implementation_hash="0" * 64),
        )

    typed = bind_agent(
        agent_id="collection-sensitive",
        version="1",
        policy_type=CollectionSensitivePolicy,
        factory=lambda: CollectionSensitivePolicy(["x"]),
    )
    object.__setattr__(typed, "factory", lambda: CollectionSensitivePolicy(("x",)))
    with pytest.raises(ValueError, match="initial state"):
        typed.validate_integrity()


def test_arena_revalidates_bound_agent_after_forced_field_substitution() -> None:
    engine, state = _loaded()
    candidate = type_aware_agent_binding(engine.catalog)
    opponent = random_legal_agent_binding()
    object.__setattr__(
        opponent,
        "factory",
        lambda: RandomLegalPolicy(allow_forfeit=True),
    )

    with pytest.raises(ValueError, match="initial state"):
        run_paired_arena(
            engine,
            state,
            plan=_plan(engine, state, pairs=1),
            candidate=candidate,
            opponent=opponent,
        )


def test_arena_rejects_factory_installed_runtime_code_swap(monkeypatch) -> None:
    engine, state = _loaded()
    candidate = type_aware_agent_binding(engine.catalog)
    original_select = TypeAwareDamagePolicy.select

    def evil_select(self, request, observation, rng):
        selection, rng = original_select(self, request, observation, rng)
        return selection, rng

    def evil_factory():
        monkeypatch.setattr(TypeAwareDamagePolicy, "select", evil_select)
        return TypeAwareDamagePolicy(engine.catalog)

    object.__setattr__(candidate, "factory", evil_factory)
    with pytest.raises(ValueError, match="identity"):
        run_paired_arena(
            engine,
            state,
            plan=_plan(engine, state, pairs=1),
            candidate=candidate,
            opponent=random_legal_agent_binding(),
        )


def test_arena_rejects_bound_agent_subclasses() -> None:
    engine, state = _loaded()
    binding = type_aware_agent_binding(engine.catalog)

    class DerivedBoundAgent(BoundAgent):
        pass

    derived = DerivedBoundAgent(
        binding.identity,
        binding.policy_type,
        binding.component_types,
        binding.factory,
        binding.identity_configuration_json,
        binding.expected_initial_policy_hash,
    )
    with pytest.raises(ValueError, match="exact BoundAgent"):
        run_paired_arena(
            engine,
            state,
            plan=_plan(engine, state, pairs=1),
            candidate=derived,
            opponent=random_legal_agent_binding(),
        )


def test_arena_rejects_battle_policy_runtime_monkeypatch_after_binding(
    monkeypatch,
) -> None:
    engine, state = _loaded()
    candidate = type_aware_agent_binding(engine.catalog)
    original_select = TypeAwareDamagePolicy.select

    def patched_select(self, request, observation, rng):
        return original_select(self, request, observation, rng)

    monkeypatch.setattr(TypeAwareDamagePolicy, "select", patched_select)
    with pytest.raises(ValueError, match="identity"):
        run_paired_arena(
            engine,
            state,
            plan=_plan(engine, state, pairs=1),
            candidate=candidate,
            opponent=random_legal_agent_binding(),
        )


def test_negative_utility_rounding_is_symmetric_toward_zero() -> None:
    assert _signed_ratio_ppm(1, 3) == 333_333
    assert _signed_ratio_ppm(-1, 3) == -333_333


@dataclass
class RngAuditPolicy:
    observed_seeds: list[int]

    def select(self, request, observation, rng):
        self.observed_seeds.append(rng.seed)
        return FirstLegalPolicy().select(request, observation, rng)


def test_engine_and_agent_rng_roots_are_separate() -> None:
    engine, state = _loaded()
    p1_seeds: list[int] = []
    p2_seeds: list[int] = []
    run_battle(
        engine,
        state,
        seed=17,
        policy_seed=999,
        policies={
            PlayerId.P1: RngAuditPolicy(p1_seeds),
            PlayerId.P2: RngAuditPolicy(p2_seeds),
        },
    )
    expected_root = ExplicitRNG.seeded(999)
    assert set(p1_seeds) == {expected_root.branch("policy:p1").seed}
    assert set(p2_seeds) == {expected_root.branch("policy:p2").seed}
    assert expected_root.branch("policy:p1").seed != ExplicitRNG.seeded(17).branch(
        "policy:p1"
    ).seed


def test_type_aware_baseline_has_positive_synthetic_paired_utility() -> None:
    report = _run(32).report
    assert report.summary.paired_net_utility_ppm > 0
