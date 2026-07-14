"""Battle and batch runners that record every deterministic transition."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Mapping

from .core import (
    ActionSelection,
    BattleEvent,
    BattleEventKind,
    BattleState,
    ExplicitRNG,
    PlayerId,
    REPLAY_SCHEMA_VERSION,
    RNG_ALGORITHM_ID,
    SIMULATOR_VERSION,
    ReplayBundle,
    ReplayInitialState,
    ReplayOutcome,
    ReplayRecord,
    ReplayRedaction,
    ReplayResult,
    ReplayStep,
    ReplayVisibility,
    canonical_hash,
)
from .engine import BattleEngine
from .policies import Policy, RandomLegalPolicy


@dataclass(frozen=True, slots=True)
class BattleRun:
    replay: ReplayRecord
    initial_events: tuple[BattleEvent, ...]
    final_state: BattleState
    winner: PlayerId | None
    decision_windows: int
    event_count: int
    engine_rng: ExplicitRNG


class ReplayVerificationError(RuntimeError):
    """Raised when a replay diverges from its recorded deterministic boundary."""


@dataclass(frozen=True, slots=True)
class BatchSummary:
    battles: int
    p1_wins: int
    p2_wins: int
    draws: int
    decision_windows: int
    events: int
    final_hashes: tuple[str, ...]


def run_battle(
    engine: BattleEngine,
    initial_state: BattleState,
    *,
    seed: int,
    policy_seed: int | None = None,
    policies: Mapping[PlayerId, Policy] | None = None,
    policy_rng_labels: Mapping[PlayerId, str] | None = None,
) -> BattleRun:
    """Run one deterministic battle.

    ``policy_rng_labels`` decouples policy random streams from seats.  By
    default the streams retain the historical ``policy:p1`` and ``policy:p2``
    branches.  A paired-seat evaluator can instead assign role labels such as
    ``candidate`` and ``opponent`` to whichever player controls each role in a
    leg, keeping each role's stream fixed when the seats are swapped.
    """

    initial_rng = ExplicitRNG.seeded(seed)
    initialized = engine.initialize(initial_state, initial_rng)
    state = initialized.state
    engine_rng = initialized.rng
    steps: list[ReplayStep] = []
    event_count = len(initialized.events)
    policy_map: Mapping[PlayerId, Policy] = policies or {
        PlayerId.P1: RandomLegalPolicy(),
        PlayerId.P2: RandomLegalPolicy(),
    }
    policy_rng_root = ExplicitRNG.seeded(seed if policy_seed is None else policy_seed)
    resolved_policy_rng_labels = _resolve_policy_rng_labels(policy_rng_labels)
    policy_rngs = {
        player: policy_rng_root.branch(f"policy:{resolved_policy_rng_labels[player]}")
        for player in (PlayerId.P1, PlayerId.P2)
    }
    max_windows = engine.ruleset.max_turns * 3 + 10
    terminal = False
    winner: PlayerId | None = None

    while not terminal:
        if len(steps) >= max_windows:
            raise RuntimeError("decision-window guard exceeded before a terminal state")
        requests = engine.required_decisions(state)
        if requests is None:
            raise RuntimeError("non-terminal battle produced no decision request")
        selections: list[ActionSelection] = []
        for request in requests.requests:
            policy = policy_map[request.player]
            selection, next_policy_rng = policy.select(
                request,
                state.observation_for(request.player),
                policy_rngs[request.player],
            )
            policy_rngs[request.player] = next_policy_rng
            selections.append(selection)
        rng_before = engine_rng
        result = engine.advance(state, selections, engine_rng)
        engine_rng = result.rng
        state = result.state
        terminal = result.terminal
        winner = result.winner
        event_count += len(result.events)
        steps.append(
            ReplayStep(
                requests=requests,
                selections=tuple(selections),
                rng_before=rng_before,
                rng_after=engine_rng,
                events=result.events,
                result_state_hash=canonical_hash(state),
                terminal=terminal,
                provisional_decision_ids=engine.ruleset.provisional_decision_ids,
            )
        )

    result_reason = _result_reason(steps[-1].events)
    replay = ReplayRecord(
        schema_version=REPLAY_SCHEMA_VERSION,
        replay_id=f"{state.battle_id}:seed:{initial_rng.seed:016x}",
        bundle=ReplayBundle(
            simulator_version=SIMULATOR_VERSION,
            engine_semantics_version=engine.ruleset.engine_semantics_version,
            ruleset_id=engine.ruleset.ruleset_id,
            ruleset_content_hash=engine.ruleset.snapshot_hash,
            catalog_id=engine.catalog.catalog_id,
            catalog_content_hash=engine.catalog.snapshot_hash,
        ),
        rng_algorithm_id=RNG_ALGORITHM_ID,
        initial_rng=initial_rng,
        rng_after_initialization=initialized.rng,
        final_rng=engine_rng,
        initial_state=ReplayInitialState.capture(initial_state),
        initial_events=initialized.events,
        initialized_state_hash=canonical_hash(initialized.state),
        steps=tuple(steps),
        result=ReplayResult(
            outcome=(
                ReplayOutcome.PLAYER_WIN
                if winner is not None
                else ReplayOutcome.DRAW
            ),
            winner=winner,
            reason=result_reason,
        ),
        final_state_hash=canonical_hash(state),
        visibility=ReplayVisibility(
            contains_private_state=True,
            redaction=ReplayRedaction.NONE,
        ),
        provisional_decision_ids=engine.ruleset.provisional_decision_ids,
        source_manifest_ids=tuple(
            sorted(
                {
                    engine.catalog.source_manifest_id,
                    *engine.ruleset.source_manifest_ids,
                }
            )
        ),
    )
    return BattleRun(
        replay=replay,
        initial_events=initialized.events,
        final_state=state,
        winner=winner,
        decision_windows=len(steps),
        event_count=event_count,
        engine_rng=engine_rng,
    )


def _resolve_policy_rng_labels(
    labels: Mapping[PlayerId, str] | None,
) -> dict[PlayerId, str]:
    if labels is None:
        return {PlayerId.P1: "p1", PlayerId.P2: "p2"}

    required_players = {PlayerId.P1, PlayerId.P2}
    supplied_players = set(labels)
    if supplied_players != required_players:
        missing = sorted(player.value for player in required_players - supplied_players)
        unexpected = sorted(str(player) for player in supplied_players - required_players)
        raise ValueError(
            "policy_rng_labels must contain exactly p1 and p2 "
            f"(missing={missing!r}, unexpected={unexpected!r})"
        )

    resolved: dict[PlayerId, str] = {}
    for player in (PlayerId.P1, PlayerId.P2):
        label = labels[player]
        if not isinstance(label, str) or not label.strip():
            raise ValueError(
                f"policy_rng_labels[{player.value!r}] must be a non-empty string"
            )
        resolved[player] = label
    if len(set(resolved.values())) != len(resolved):
        raise ValueError("policy_rng_labels must be distinct for p1 and p2")
    return resolved


def _result_reason(events: tuple[BattleEvent, ...]) -> str:
    for event in reversed(events):
        if event.kind is BattleEventKind.BATTLE_ENDED:
            details = dict(event.details)
            reason = details.get("reason")
            if isinstance(reason, str) and reason:
                return reason
    raise RuntimeError("terminal transition did not include a battle-ended reason")


def verify_replay(engine: BattleEngine, replay: ReplayRecord) -> BattleState:
    """Re-execute and verify every initialization and decision boundary."""

    expected_sources = tuple(
        sorted(
            {
                engine.catalog.source_manifest_id,
                *engine.ruleset.source_manifest_ids,
            }
        )
    )
    bundle_checks = (
        ("simulator_version", replay.bundle.simulator_version, SIMULATOR_VERSION),
        (
            "engine_semantics_version",
            replay.bundle.engine_semantics_version,
            engine.ruleset.engine_semantics_version,
        ),
        ("ruleset_id", replay.bundle.ruleset_id, engine.ruleset.ruleset_id),
        (
            "ruleset_content_hash",
            replay.bundle.ruleset_content_hash,
            engine.ruleset.snapshot_hash,
        ),
        ("catalog_id", replay.bundle.catalog_id, engine.catalog.catalog_id),
        (
            "catalog_content_hash",
            replay.bundle.catalog_content_hash,
            engine.catalog.snapshot_hash,
        ),
        (
            "provisional_decision_ids",
            replay.provisional_decision_ids,
            engine.ruleset.provisional_decision_ids,
        ),
        ("source_manifest_ids", replay.source_manifest_ids, expected_sources),
    )
    for name, actual, expected in bundle_checks:
        _verify_equal(name, actual, expected)

    state = replay.initial_state.payload
    _verify_equal(
        "initial_state_hash", canonical_hash(state), replay.initial_state.state_hash
    )
    initialized = engine.initialize(state, replay.initial_rng)
    _verify_equal("initial_events", initialized.events, replay.initial_events)
    _verify_equal(
        "initialized_state_hash",
        canonical_hash(initialized.state),
        replay.initialized_state_hash,
    )
    _verify_equal(
        "rng_after_initialization",
        initialized.rng,
        replay.rng_after_initialization,
    )
    state = initialized.state
    rng = initialized.rng
    winner: PlayerId | None = None

    for index, step in enumerate(replay.steps):
        prefix = f"step[{index}]"
        _verify_equal(
            f"{prefix}.provisional_decision_ids",
            step.provisional_decision_ids,
            engine.ruleset.provisional_decision_ids,
        )
        _verify_equal(f"{prefix}.rng_before", rng, step.rng_before)
        requests = engine.required_decisions(state)
        _verify_equal(f"{prefix}.requests", requests, step.requests)
        result = engine.advance(state, step.selections, rng)
        _verify_equal(f"{prefix}.rng_after", result.rng, step.rng_after)
        _verify_equal(f"{prefix}.events", result.events, step.events)
        _verify_equal(
            f"{prefix}.result_state_hash",
            canonical_hash(result.state),
            step.result_state_hash,
        )
        _verify_equal(f"{prefix}.terminal", result.terminal, step.terminal)
        state = result.state
        rng = result.rng
        winner = result.winner

    _verify_equal("final_rng", rng, replay.final_rng)
    _verify_equal("final_state_hash", canonical_hash(state), replay.final_state_hash)
    _verify_equal("result.winner", winner, replay.result.winner)
    expected_outcome = (
        ReplayOutcome.PLAYER_WIN if winner is not None else ReplayOutcome.DRAW
    )
    _verify_equal("result.outcome", expected_outcome, replay.result.outcome)
    if not replay.steps:
        raise ReplayVerificationError("completed replay contains no decision steps")
    _verify_equal(
        "result.reason",
        _result_reason(replay.steps[-1].events),
        replay.result.reason,
    )
    return state


def _verify_equal(name: str, actual: object, expected: object) -> None:
    if actual != expected:
        raise ReplayVerificationError(
            f"replay mismatch at {name}: actual={actual!r}, expected={expected!r}"
        )


def run_random_batch(
    engine: BattleEngine,
    initial_state: BattleState,
    *,
    battles: int,
    seed_start: int = 0,
) -> BatchSummary:
    if battles <= 0:
        raise ValueError("battles must be positive")
    p1_wins = p2_wins = draws = windows = events = 0
    hashes: list[str] = []
    for offset in range(battles):
        state = replace(initial_state, battle_id=f"{initial_state.battle_id}:{seed_start + offset}")
        run = run_battle(
            engine,
            state,
            seed=seed_start + offset,
            policies={
                PlayerId.P1: RandomLegalPolicy(),
                PlayerId.P2: RandomLegalPolicy(),
            },
        )
        if run.winner is PlayerId.P1:
            p1_wins += 1
        elif run.winner is PlayerId.P2:
            p2_wins += 1
        else:
            draws += 1
        windows += run.decision_windows
        events += run.event_count
        hashes.append(run.replay.final_state_hash)
    return BatchSummary(
        battles=battles,
        p1_wins=p1_wins,
        p2_wins=p2_wins,
        draws=draws,
        decision_windows=windows,
        events=events,
        final_hashes=tuple(hashes),
    )
