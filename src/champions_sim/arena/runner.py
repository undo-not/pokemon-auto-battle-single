"""Paired-seat execution and Replay-backed AI-01 report resolution."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Mapping

from champions_sim.core import (
    BattleState,
    MegaEvolutionStatProfile,
    MoveSlotState,
    PlayerId,
    PokemonState,
    PokemonInstanceId,
    ReplayRecord,
    SideState,
    StatBlock,
    StatStages,
    TrainingStatBlock,
    canonical_hash,
    canonical_json,
)
from champions_sim.catalog import CatalogSnapshot, RuleSetSnapshot
from champions_sim.engine import BattleEngine
from champions_sim.policies import Policy
from champions_sim.prebattle import (
    TeamPreviewRun,
    TeamSelectionPolicy,
    verify_team_preview_proof,
)
from champions_sim.runner import run_battle, verify_replay

from .binding import BoundAgent
from .models import (
    ArenaMatchRecord,
    ArenaPlan,
    ArenaReport,
    CandidateOutcome,
    MatchLeg,
    _build_arena_report,
)


MANDATORY_SCOPE_BLOCKERS = (
    "champions_fidelity_not_verified",
    "policy_process_isolation_not_implemented",
    "rank1_external_calibration_missing",
)


@dataclass(frozen=True, slots=True)
class ArenaRun:
    """A report plus the private Replay evidence required to verify it."""

    report: ArenaReport
    replays: tuple[ReplayRecord, ...]

    def __post_init__(self) -> None:
        if type(self.report) is not ArenaReport:
            raise ValueError("arena run requires the exact ArenaReport contract")
        if type(self.replays) is not tuple or any(
            type(replay) is not ReplayRecord for replay in self.replays
        ):
            raise ValueError("arena run requires exact ReplayRecord contracts")
        ArenaReport.__post_init__(self.report)
        for replay in self.replays:
            ReplayRecord.__post_init__(replay)

    @property
    def evidence_hash(self) -> str:
        return canonical_hash(
            {
                "report_hash": self.report.report_hash,
                "replay_hashes": tuple(replay.replay_hash for replay in self.replays),
            }
        )


def run_paired_arena(
    engine: BattleEngine,
    initial_state: BattleState,
    *,
    plan: ArenaPlan,
    candidate: BoundAgent,
    opponent: BoundAgent,
    prebattle_run: TeamPreviewRun | None = None,
    prebattle_policies: Mapping[PlayerId, TeamSelectionPolicy] | None = None,
    external_blockers: tuple[str, ...] = (),
) -> ArenaRun:
    """Execute both seats, then independently re-run and resolve every Replay.

    The policy bindings are checked against the plan before execution.  The
    resolver creates report records only from verified Replay evidence and a
    second policy execution with the planned role-fixed RNG streams.
    """

    _validate_execution_inputs(
        engine,
        initial_state,
        plan,
        candidate,
        opponent,
        prebattle_run,
        prebattle_policies,
    )
    replays: list[ReplayRecord] = []
    retained: list[Policy] = []
    instance_ids: set[int] = set()
    for pair_index, leg, engine_seed, agent_seed in _planned_legs(plan):
        candidate_player = _candidate_player(leg)
        state = materialize_arena_leg(
            initial_state,
            pair_index,
            leg,
            arena_namespace=f"{plan.plan_id}:{plan.scenario_id}",
        )
        battle = run_battle(
            engine,
            state,
            seed=engine_seed,
            policy_seed=agent_seed,
            policy_rng_labels={
                candidate_player: "candidate",
                candidate_player.opponent: "opponent",
            },
            policies={
                candidate_player: _fresh_policy(candidate, retained, instance_ids),
                candidate_player.opponent: _fresh_policy(
                    opponent, retained, instance_ids
                ),
            },
        )
        replays.append(battle.replay)

    return resolve_arena_run(
        engine,
        initial_state,
        plan=plan,
        candidate=candidate,
        opponent=opponent,
        replays=tuple(replays),
        prebattle_run=prebattle_run,
        prebattle_policies=prebattle_policies,
        external_blockers=external_blockers,
    )


def resolve_arena_run(
    engine: BattleEngine,
    initial_state: BattleState,
    *,
    plan: ArenaPlan,
    candidate: BoundAgent,
    opponent: BoundAgent,
    replays: tuple[ReplayRecord, ...],
    prebattle_run: TeamPreviewRun | None = None,
    prebattle_policies: Mapping[PlayerId, TeamSelectionPolicy] | None = None,
    external_blockers: tuple[str, ...] = (),
) -> ArenaRun:
    """Resolve a completed report exclusively from verified Replay evidence."""

    _validate_execution_inputs(
        engine,
        initial_state,
        plan,
        candidate,
        opponent,
        prebattle_run,
        prebattle_policies,
    )
    if type(replays) is not tuple or any(
        type(replay) is not ReplayRecord for replay in replays
    ):
        raise ValueError("arena evidence requires exact ReplayRecord contracts")
    if len(replays) != plan.pair_count * 2:
        raise ValueError("arena evidence requires exactly two Replays per pair")
    records: list[ArenaMatchRecord] = []
    retained: list[Policy] = []
    instance_ids: set[int] = set()

    for replay, (pair_index, leg, engine_seed, agent_seed) in zip(
        replays, _planned_legs(plan), strict=True
    ):
        ReplayRecord.__post_init__(replay)
        candidate_player = _candidate_player(leg)
        expected_state = materialize_arena_leg(
            initial_state,
            pair_index,
            leg,
            arena_namespace=f"{plan.plan_id}:{plan.scenario_id}",
        )
        if replay.initial_state.payload != expected_state:
            raise ValueError("Replay initial state does not match its planned arena leg")
        if replay.initial_rng.seed != engine_seed:
            raise ValueError("Replay engine seed does not match its arena plan")
        verified_state = verify_replay(engine, replay)
        if canonical_hash(verified_state) != replay.final_state_hash:
            raise RuntimeError("Replay verification returned a different final state")

        reproduced = run_battle(
            engine,
            expected_state,
            seed=engine_seed,
            policy_seed=agent_seed,
            policy_rng_labels={
                candidate_player: "candidate",
                candidate_player.opponent: "opponent",
            },
            policies={
                candidate_player: _fresh_policy(candidate, retained, instance_ids),
                candidate_player.opponent: _fresh_policy(
                    opponent, retained, instance_ids
                ),
            },
        )
        if canonical_json(reproduced.replay) != canonical_json(replay):
            raise ValueError(
                "Replay selections do not match the bound policies and planned agent seed"
            )
        outcome = _candidate_outcome(replay.result.winner, candidate_player)
        records.append(
            ArenaMatchRecord(
                pair_index=pair_index,
                engine_seed=engine_seed,
                agent_seed=agent_seed,
                leg=leg,
                candidate_player=candidate_player,
                winner=replay.result.winner,
                candidate_outcome=outcome,
                terminal_utility=outcome.terminal_utility,
                replay_hash=replay.replay_hash,
                final_state_hash=replay.final_state_hash,
                decision_windows=len(replay.steps),
                event_count=len(replay.initial_events)
                + sum(len(step.events) for step in replay.steps),
                replay_verified=True,
            )
        )

    blockers = tuple(sorted({*MANDATORY_SCOPE_BLOCKERS, *external_blockers}))
    report = _build_arena_report(plan, tuple(records), blockers=blockers)
    return ArenaRun(report=report, replays=replays)


def verify_arena_run(
    engine: BattleEngine,
    initial_state: BattleState,
    run: ArenaRun,
    *,
    candidate: BoundAgent,
    opponent: BoundAgent,
    prebattle_run: TeamPreviewRun | None = None,
    prebattle_policies: Mapping[PlayerId, TeamSelectionPolicy] | None = None,
    external_blockers: tuple[str, ...] = (),
) -> None:
    """Reject any report/Replay mutation by resolving the evidence again."""

    if type(run) is not ArenaRun:
        raise ValueError("arena verification requires the exact ArenaRun contract")
    ArenaRun.__post_init__(run)

    expected = resolve_arena_run(
        engine,
        initial_state,
        plan=run.report.plan,
        candidate=candidate,
        opponent=opponent,
        replays=run.replays,
        prebattle_run=prebattle_run,
        prebattle_policies=prebattle_policies,
        external_blockers=external_blockers,
    )
    if canonical_json(expected.report) != canonical_json(run.report):
        raise ValueError("arena report does not match its resolved Replay evidence")


def materialize_arena_leg(
    initial_state: BattleState,
    pair_index: int,
    leg: MatchLeg,
    *,
    arena_namespace: str = "synthetic-arena",
) -> BattleState:
    """Swap seats and replace caller-controlled identifiers with opaque IDs."""

    if pair_index < 0:
        raise ValueError("pair_index must be non-negative")
    if not arena_namespace:
        raise ValueError("arena_namespace must be non-empty")
    opaque_id = canonical_hash(
        {
            "arena_namespace": arena_namespace,
            "pair_index": pair_index,
            "leg": leg.value,
        }
    )[:32]
    original_candidate = initial_state.side(PlayerId.P1)
    original_opponent = initial_state.side(PlayerId.P2)
    if leg is MatchLeg.CANDIDATE_P1:
        p1_source, p2_source = original_candidate, original_opponent
    else:
        p1_source, p2_source = original_opponent, original_candidate
    return replace(
        initial_state,
        battle_id=f"arena-{opaque_id}",
        sides=(
            _remap_side(p1_source, PlayerId.P1),
            _remap_side(p2_source, PlayerId.P2),
        ),
    )


def _remap_side(side: SideState, player: PlayerId) -> SideState:
    id_map = {
        pokemon.instance_id: PokemonInstanceId(f"{player.value}-slot-{index:02d}")
        for index, pokemon in enumerate(side.team, start=1)
    }
    return replace(
        side,
        player=player,
        team=tuple(
            replace(pokemon, instance_id=id_map[pokemon.instance_id])
            for pokemon in side.team
        ),
        active_instance_id=id_map[side.active_instance_id],
    )


def _fresh_policy(
    binding: BoundAgent,
    retained: list[Policy],
    identities: set[int],
) -> Policy:
    policy = binding.new_policy()
    identity = id(policy)
    if identity in identities:
        raise ValueError("bound policy factory reused an instance across arena legs")
    identities.add(identity)
    retained.append(policy)
    return policy


def _candidate_player(leg: MatchLeg) -> PlayerId:
    return PlayerId.P1 if leg is MatchLeg.CANDIDATE_P1 else PlayerId.P2


def _candidate_outcome(
    winner: PlayerId | None,
    candidate_player: PlayerId,
) -> CandidateOutcome:
    if winner is None:
        return CandidateOutcome.DRAW
    return CandidateOutcome.WIN if winner is candidate_player else CandidateOutcome.LOSS


def _planned_legs(plan: ArenaPlan):
    for pair_index in range(plan.pair_count):
        engine_seed = plan.engine_seed_start + pair_index
        agent_seed = plan.agent_seed_start + pair_index
        for leg in (MatchLeg.CANDIDATE_P1, MatchLeg.CANDIDATE_P2):
            yield pair_index, leg, engine_seed, agent_seed


def _validate_execution_inputs(
    engine: BattleEngine,
    initial_state: BattleState,
    plan: ArenaPlan,
    candidate: BoundAgent,
    opponent: BoundAgent,
    prebattle_run: TeamPreviewRun | None,
    prebattle_policies: Mapping[PlayerId, TeamSelectionPolicy] | None,
) -> None:
    if type(engine) is not BattleEngine:
        raise ValueError("arena requires the exact BattleEngine implementation")
    if type(engine.catalog) is not CatalogSnapshot or type(
        engine.ruleset
    ) is not RuleSetSnapshot:
        raise ValueError("arena requires exact CatalogSnapshot and RuleSetSnapshot contracts")
    _validate_exact_battle_state(initial_state)
    if type(candidate) is not BoundAgent or type(opponent) is not BoundAgent:
        raise ValueError("arena requires exact BoundAgent contracts")
    if type(plan) is not ArenaPlan:
        raise ValueError("arena requires the exact ArenaPlan contract")
    ArenaPlan.__post_init__(plan)
    candidate.validate_integrity()
    opponent.validate_integrity()
    checks = (
        ("catalog_id", plan.catalog_id, engine.catalog.catalog_id),
        ("catalog_hash", plan.catalog_hash, engine.catalog.snapshot_hash),
        ("ruleset_id", plan.ruleset_id, str(engine.ruleset.ruleset_id)),
        ("ruleset_hash", plan.ruleset_hash, engine.ruleset.snapshot_hash),
        ("initial_state_hash", plan.initial_state_hash, canonical_hash(initial_state)),
        ("candidate_identity", plan.candidate, candidate.identity),
        ("opponent_identity", plan.opponent, opponent.identity),
    )
    mismatches = [
        name
        for name, actual, expected in checks
        if canonical_json(actual) != canonical_json(expected)
    ]
    if mismatches:
        raise ValueError(f"arena plan does not match bound inputs: {mismatches}")
    _validate_prebattle_binding(
        engine,
        initial_state,
        plan,
        candidate,
        opponent,
        prebattle_run,
        prebattle_policies,
    )


def _validate_exact_battle_state(state: BattleState) -> None:
    """Reject polymorphic state objects before they reach policy observations."""

    if type(state) is not BattleState or type(state.sides) is not tuple:
        raise ValueError("arena requires the exact BattleState contract")
    BattleState.__post_init__(state)
    for side in state.sides:
        if type(side) is not SideState or type(side.team) is not tuple:
            raise ValueError("arena requires exact SideState contracts")
        SideState.__post_init__(side)
        for pokemon in side.team:
            if type(pokemon) is not PokemonState:
                raise ValueError("arena requires exact PokemonState contracts")
            if type(pokemon.stats) is not StatBlock or type(
                pokemon.stat_stages
            ) is not StatStages:
                raise ValueError("arena requires exact stat contracts")
            if type(pokemon.moves) is not tuple or any(
                type(move) is not MoveSlotState for move in pokemon.moves
            ):
                raise ValueError("arena requires exact MoveSlotState contracts")
            StatBlock.__post_init__(pokemon.stats)
            StatStages.__post_init__(pokemon.stat_stages)
            for move in pokemon.moves:
                MoveSlotState.__post_init__(move)
            profile = pokemon.mega_evolution_profile
            if profile is not None:
                if type(profile) is not MegaEvolutionStatProfile:
                    raise ValueError(
                        "arena requires the exact MegaEvolutionStatProfile contract"
                    )
                if type(profile.stats) is not StatBlock or type(
                    profile.ivs
                ) is not TrainingStatBlock or type(
                    profile.evs
                ) is not TrainingStatBlock:
                    raise ValueError("arena requires exact Mega stat contracts")
                MegaEvolutionStatProfile.__post_init__(profile)
            PokemonState.__post_init__(pokemon)


def _validate_prebattle_binding(
    engine: BattleEngine,
    initial_state: BattleState,
    plan: ArenaPlan,
    candidate: BoundAgent,
    opponent: BoundAgent,
    prebattle_run: TeamPreviewRun | None,
    prebattle_policies: Mapping[PlayerId, TeamSelectionPolicy] | None,
) -> None:
    planned = plan.prebattle_proof_hash is not None
    supplied = prebattle_run is not None or prebattle_policies is not None
    if not planned:
        if supplied:
            raise ValueError("prebattle evidence was supplied for a plan without it")
        return
    if prebattle_run is None or prebattle_policies is None:
        raise ValueError("prebattle plan requires its run and exact policy inputs")
    prebattle_run.session.validate_against(engine.catalog, engine.ruleset)
    verify_team_preview_proof(
        prebattle_run,
        policies=prebattle_policies,
        seed=prebattle_run.proof.seed,
    )
    checks = (
        ("prebattle_catalog_id", plan.catalog_id, prebattle_run.proof.catalog_id),
        (
            "prebattle_catalog_hash",
            plan.catalog_hash,
            prebattle_run.proof.catalog_hash,
        ),
        ("prebattle_ruleset_id", plan.ruleset_id, str(prebattle_run.proof.ruleset_id)),
        (
            "prebattle_ruleset_hash",
            plan.ruleset_hash,
            prebattle_run.proof.ruleset_hash,
        ),
        (
            "prebattle_session_hash",
            plan.prebattle_session_hash,
            prebattle_run.proof.session_hash,
        ),
        (
            "prebattle_proof_hash",
            plan.prebattle_proof_hash,
            prebattle_run.proof.proof_hash,
        ),
        (
            "prebattle_materialized_state",
            initial_state,
            prebattle_run.session.materialize(),
        ),
    )
    mismatches = [name for name, actual, expected in checks if actual != expected]
    if mismatches:
        raise ValueError(f"arena prebattle evidence does not match plan: {mismatches}")

    for label, binding, policy_identity in (
        ("candidate", candidate, prebattle_run.proof.p1_policy),
        ("opponent", opponent, prebattle_run.proof.p2_policy),
    ):
        configuration_hash = binding.identity_configuration.get(
            "selection_policy_implementation_hash"
        )
        if configuration_hash != policy_identity.implementation_hash:
            raise ValueError(
                f"{label} battle identity is not bound to its selection policy"
            )
        component_sources = dict(binding.identity.component_source_hashes)
        if component_sources.get(policy_identity.policy_component) != (
            policy_identity.source_sha256
        ):
            raise ValueError(
                f"{label} selection source is not part of its agent identity"
            )
        component_runtime = dict(binding.identity.component_runtime_hashes)
        if component_runtime.get(policy_identity.policy_component) != (
            policy_identity.runtime_sha256
        ):
            raise ValueError(
                f"{label} live selection code is not part of its agent identity"
            )
