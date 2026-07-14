"""Versioned, hash-bound contracts for synthetic competitive evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json

from champions_sim.core import PlayerId, canonical_hash, canonical_json


ARENA_SCHEMA_VERSION = "ai01-arena-report-v1"
ARENA_VERSION = "ai01-arena-1.0"
SYNTHETIC_LOCAL_SCOPE = "synthetic_local"
RANK1_UNMEASURED = "unmeasured"
MAX_SEED = (1 << 64) - 1


class EvaluationPartition(str, Enum):
    DEVELOPMENT = "development"
    HOLDOUT = "holdout"


class MatchLeg(str, Enum):
    CANDIDATE_P1 = "candidate_p1"
    CANDIDATE_P2 = "candidate_p2"


class CandidateOutcome(str, Enum):
    WIN = "win"
    DRAW = "draw"
    LOSS = "loss"

    @property
    def terminal_utility(self) -> int:
        return {
            CandidateOutcome.WIN: 1,
            CandidateOutcome.DRAW: 0,
            CandidateOutcome.LOSS: -1,
        }[self]


@dataclass(frozen=True, slots=True)
class AgentIdentity:
    agent_id: str
    version: str
    implementation_hash: str
    implementation_components: tuple[str, ...]
    component_source_hashes: tuple[tuple[str, str], ...]
    component_runtime_hashes: tuple[tuple[str, str], ...]
    battle_policy_component: str
    configuration_json: str
    configuration_hash: str
    observation_contract: str = "player-observation-v1"

    def __post_init__(self) -> None:
        if (
            not self.agent_id
            or not self.version
            or not self.observation_contract
            or not self.battle_policy_component
        ):
            raise ValueError("agent identity fields must be non-empty")
        _require_sha256("implementation_hash", self.implementation_hash)
        if not self.implementation_components or len(
            set(self.implementation_components)
        ) != len(self.implementation_components):
            raise ValueError("agent implementation components must be non-empty and unique")
        source_paths = tuple(path for path, _ in self.component_source_hashes)
        if source_paths != self.implementation_components:
            raise ValueError(
                "component source hashes must cover implementation components in order"
            )
        for path, source_hash in self.component_source_hashes:
            if not path:
                raise ValueError("component source paths must be non-empty")
            _require_sha256("component_source_hash", source_hash)
        runtime_paths = tuple(path for path, _ in self.component_runtime_hashes)
        if runtime_paths != self.implementation_components:
            raise ValueError(
                "component runtime hashes must cover implementation components in order"
            )
        for path, runtime_hash in self.component_runtime_hashes:
            if not path:
                raise ValueError("component runtime paths must be non-empty")
            _require_sha256("component_runtime_hash", runtime_hash)
        if self.battle_policy_component not in self.implementation_components:
            raise ValueError("battle policy must be one of the hashed implementation components")
        _require_sha256("configuration_hash", self.configuration_hash)
        try:
            configuration = json.loads(self.configuration_json)
        except json.JSONDecodeError as exc:
            raise ValueError("agent configuration must be valid JSON") from exc
        if not isinstance(configuration, dict) or canonical_json(configuration) != self.configuration_json:
            raise ValueError("agent configuration must be a canonical JSON object")
        if hashlib.sha256(self.configuration_json.encode("utf-8")).hexdigest() != (
            self.configuration_hash
        ):
            raise ValueError("agent configuration hash does not match configuration JSON")


@dataclass(frozen=True, slots=True)
class ArenaPlan:
    plan_id: str
    scenario_id: str
    partition: EvaluationPartition
    pair_count: int
    engine_seed_start: int
    agent_seed_start: int
    catalog_id: str
    catalog_hash: str
    ruleset_id: str
    ruleset_hash: str
    initial_state_hash: str
    candidate: AgentIdentity
    opponent: AgentIdentity
    scope: str = SYNTHETIC_LOCAL_SCOPE
    prebattle_session_hash: str | None = field(
        default=None,
        metadata={"canonical_omit_default": True},
    )
    prebattle_proof_hash: str | None = field(
        default=None,
        metadata={"canonical_omit_default": True},
    )
    provisional_decision_ids: tuple[str, ...] = field(
        default=(),
        metadata={"canonical_omit_default": True},
    )

    def __post_init__(self) -> None:
        if not self.plan_id or not self.scenario_id:
            raise ValueError("plan_id and scenario_id must be non-empty")
        if type(self.candidate) is not AgentIdentity or type(self.opponent) is not AgentIdentity:
            raise ValueError("arena plan requires exact AgentIdentity contracts")
        AgentIdentity.__post_init__(self.candidate)
        AgentIdentity.__post_init__(self.opponent)
        if self.pair_count <= 0:
            raise ValueError("pair_count must be positive")
        if self.engine_seed_start < 0 or self.agent_seed_start < 0:
            raise ValueError("seed starts must be non-negative")
        if self.engine_seed_start + self.pair_count - 1 > MAX_SEED:
            raise ValueError("engine seed range must fit unsigned 64-bit")
        if self.agent_seed_start + self.pair_count - 1 > MAX_SEED:
            raise ValueError("agent seed range must fit unsigned 64-bit")
        if not self.catalog_id or not self.ruleset_id:
            raise ValueError("catalog_id and ruleset_id must be non-empty")
        for name, value in (
            ("catalog_hash", self.catalog_hash),
            ("ruleset_hash", self.ruleset_hash),
            ("initial_state_hash", self.initial_state_hash),
        ):
            _require_sha256(name, value)
        if self.scope != SYNTHETIC_LOCAL_SCOPE:
            raise ValueError("AI-01 v1 only accepts synthetic_local plans")
        if self.prebattle_session_hash is not None:
            _require_sha256("prebattle_session_hash", self.prebattle_session_hash)
        if self.prebattle_proof_hash is not None:
            _require_sha256("prebattle_proof_hash", self.prebattle_proof_hash)
        if (self.prebattle_session_hash is None) != (self.prebattle_proof_hash is None):
            raise ValueError(
                "prebattle session and proof hashes must either both be present or both absent"
            )
        if len(set(self.provisional_decision_ids)) != len(
            self.provisional_decision_ids
        ) or any(not value for value in self.provisional_decision_ids):
            raise ValueError("provisional decision IDs must be unique and non-empty")

    @property
    def plan_hash(self) -> str:
        return canonical_hash(self)


@dataclass(frozen=True, slots=True)
class ArenaMatchRecord:
    pair_index: int
    engine_seed: int
    agent_seed: int
    leg: MatchLeg
    candidate_player: PlayerId
    winner: PlayerId | None
    candidate_outcome: CandidateOutcome
    terminal_utility: int
    replay_hash: str
    final_state_hash: str
    decision_windows: int
    event_count: int
    replay_verified: bool

    def __post_init__(self) -> None:
        if self.pair_index < 0 or self.engine_seed < 0 or self.agent_seed < 0:
            raise ValueError("pair index and seeds must be non-negative")
        expected_player = (
            PlayerId.P1 if self.leg is MatchLeg.CANDIDATE_P1 else PlayerId.P2
        )
        if self.candidate_player is not expected_player:
            raise ValueError("candidate_player does not match the match leg")
        expected_outcome = (
            CandidateOutcome.DRAW
            if self.winner is None
            else (
                CandidateOutcome.WIN
                if self.winner is self.candidate_player
                else CandidateOutcome.LOSS
            )
        )
        if self.candidate_outcome is not expected_outcome:
            raise ValueError("candidate_outcome does not match winner")
        if self.terminal_utility != self.candidate_outcome.terminal_utility:
            raise ValueError("terminal utility does not match outcome")
        _require_sha256("replay_hash", self.replay_hash)
        _require_sha256("final_state_hash", self.final_state_hash)
        if self.decision_windows <= 0 or self.event_count <= 0:
            raise ValueError("completed matches require positive execution counts")


@dataclass(frozen=True, slots=True)
class SeatSummary:
    matches: int
    wins: int
    draws: int
    losses: int

    def __post_init__(self) -> None:
        if min(self.matches, self.wins, self.draws, self.losses) < 0:
            raise ValueError("seat summary counts must be non-negative")
        if self.wins + self.draws + self.losses != self.matches:
            raise ValueError("seat summary outcomes must equal matches")


@dataclass(frozen=True, slots=True)
class ArenaSummary:
    pairs: int
    matches: int
    wins: int
    draws: int
    losses: int
    net_utility_numerator: int
    net_utility_denominator: int
    paired_net_utility_ppm: int
    pair_completeness_rate_ppm: int
    legal_action_rate_ppm: int
    replay_verification_rate_ppm: int
    private_state_delivery_violation_count: int
    execution_error_count: int
    candidate_as_p1: SeatSummary
    candidate_as_p2: SeatSummary

    def __post_init__(self) -> None:
        if type(self.candidate_as_p1) is not SeatSummary or type(
            self.candidate_as_p2
        ) is not SeatSummary:
            raise ValueError("arena summary requires exact SeatSummary contracts")
        SeatSummary.__post_init__(self.candidate_as_p1)
        SeatSummary.__post_init__(self.candidate_as_p2)
        if self.pairs <= 0 or self.matches != self.pairs * 2:
            raise ValueError("a completed paired summary requires two legs per pair")
        if self.wins + self.draws + self.losses != self.matches:
            raise ValueError("summary outcomes must equal matches")
        if self.net_utility_numerator != self.wins - self.losses:
            raise ValueError("net utility numerator must equal wins minus losses")
        if self.net_utility_denominator != self.matches:
            raise ValueError("net utility denominator must equal matches")
        if self.paired_net_utility_ppm != _signed_ratio_ppm(
            self.net_utility_numerator, self.net_utility_denominator
        ):
            raise ValueError("paired utility ppm must use symmetric truncation")
        if not -1_000_000 <= self.paired_net_utility_ppm <= 1_000_000:
            raise ValueError("paired utility rate is outside its exact range")
        for name, value in (
            ("pair_completeness_rate_ppm", self.pair_completeness_rate_ppm),
            ("legal_action_rate_ppm", self.legal_action_rate_ppm),
            ("replay_verification_rate_ppm", self.replay_verification_rate_ppm),
        ):
            if not 0 <= value <= 1_000_000:
                raise ValueError(f"{name} must be between 0 and 1,000,000")
        if self.private_state_delivery_violation_count < 0 or self.execution_error_count < 0:
            raise ValueError("violation and error counts must be non-negative")
        if self.candidate_as_p1.matches + self.candidate_as_p2.matches != self.matches:
            raise ValueError("seat summaries must cover every match")


@dataclass(frozen=True, slots=True)
class ArenaReport:
    schema_version: str
    arena_version: str
    plan: ArenaPlan
    matches: tuple[ArenaMatchRecord, ...]
    summary: ArenaSummary
    decision: str
    champions_readiness_decision: str
    champions_candidate: bool
    rank1_equivalence_status: str
    rank1_equivalence_claim_allowed: bool
    blockers: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != ARENA_SCHEMA_VERSION:
            raise ValueError("unsupported arena report schema")
        if self.arena_version != ARENA_VERSION:
            raise ValueError("unsupported arena implementation version")
        if type(self.plan) is not ArenaPlan:
            raise ValueError("arena report requires the exact ArenaPlan contract")
        if type(self.summary) is not ArenaSummary:
            raise ValueError("arena report requires the exact ArenaSummary contract")
        if any(type(item) is not ArenaMatchRecord for item in self.matches):
            raise ValueError("arena report requires exact ArenaMatchRecord contracts")
        ArenaPlan.__post_init__(self.plan)
        for item in self.matches:
            ArenaMatchRecord.__post_init__(item)
        ArenaSummary.__post_init__(self.summary)
        _validate_pair_records(self.plan, self.matches)
        expected_summary = summarize_matches(self.plan.pair_count, self.matches)
        if canonical_json(self.summary) != canonical_json(expected_summary):
            raise ValueError("arena summary must be recomputed from match records")
        if self.decision != "synthetic_benchmark_complete":
            raise ValueError("AI-01 v1 only emits completed synthetic benchmarks")
        if self.champions_readiness_decision != "no_go":
            raise ValueError("synthetic AI-01 reports must retain Champions NO-GO")
        if self.champions_candidate:
            raise ValueError("synthetic AI-01 reports cannot be Champions candidates")
        if self.rank1_equivalence_status != RANK1_UNMEASURED:
            raise ValueError("rank-1 equivalence must remain unmeasured")
        if self.rank1_equivalence_claim_allowed:
            raise ValueError("rank-1 equivalence claims are forbidden in AI-01")
        required = {
            "champions_fidelity_not_verified",
            "policy_process_isolation_not_implemented",
            "rank1_external_calibration_missing",
        }
        if not required <= set(self.blockers):
            raise ValueError("arena report is missing mandatory scope blockers")
        if len(set(self.blockers)) != len(self.blockers):
            raise ValueError("arena blockers must be unique")

    @property
    def report_hash(self) -> str:
        return canonical_hash(self)

    def to_json(self) -> str:
        return canonical_json(self)


def _build_arena_report(
    plan: ArenaPlan,
    matches: tuple[ArenaMatchRecord, ...],
    *,
    blockers: tuple[str, ...] = (
        "champions_fidelity_not_verified",
        "policy_process_isolation_not_implemented",
        "rank1_external_calibration_missing",
    ),
) -> ArenaReport:
    ordered = tuple(sorted(matches, key=_record_sort_key))
    return ArenaReport(
        schema_version=ARENA_SCHEMA_VERSION,
        arena_version=ARENA_VERSION,
        plan=plan,
        matches=ordered,
        summary=summarize_matches(plan.pair_count, ordered),
        decision="synthetic_benchmark_complete",
        champions_readiness_decision="no_go",
        champions_candidate=False,
        rank1_equivalence_status=RANK1_UNMEASURED,
        rank1_equivalence_claim_allowed=False,
        blockers=tuple(sorted(blockers)),
    )


def summarize_matches(
    pair_count: int,
    matches: tuple[ArenaMatchRecord, ...],
) -> ArenaSummary:
    wins = sum(item.candidate_outcome is CandidateOutcome.WIN for item in matches)
    draws = sum(item.candidate_outcome is CandidateOutcome.DRAW for item in matches)
    losses = sum(item.candidate_outcome is CandidateOutcome.LOSS for item in matches)
    total = len(matches)
    verified = sum(item.replay_verified for item in matches)
    p1 = tuple(item for item in matches if item.candidate_player is PlayerId.P1)
    p2 = tuple(item for item in matches if item.candidate_player is PlayerId.P2)
    return ArenaSummary(
        pairs=pair_count,
        matches=total,
        wins=wins,
        draws=draws,
        losses=losses,
        net_utility_numerator=wins - losses,
        net_utility_denominator=total,
        paired_net_utility_ppm=_signed_ratio_ppm(wins - losses, total),
        pair_completeness_rate_ppm=1_000_000 if total == pair_count * 2 else 0,
        # A completed run cannot contain an illegal selection: the engine rejects it
        # before a record exists.  This derived value is not caller supplied.
        legal_action_rate_ppm=1_000_000 if total == pair_count * 2 else 0,
        replay_verification_rate_ppm=(verified * 1_000_000) // total if total else 0,
        # Policies receive only DecisionRequest + centrally filtered PlayerObservation.
        private_state_delivery_violation_count=0,
        execution_error_count=0,
        candidate_as_p1=_seat_summary(p1),
        candidate_as_p2=_seat_summary(p2),
    )


def _seat_summary(matches: tuple[ArenaMatchRecord, ...]) -> SeatSummary:
    return SeatSummary(
        matches=len(matches),
        wins=sum(item.candidate_outcome is CandidateOutcome.WIN for item in matches),
        draws=sum(item.candidate_outcome is CandidateOutcome.DRAW for item in matches),
        losses=sum(item.candidate_outcome is CandidateOutcome.LOSS for item in matches),
    )


def _validate_pair_records(
    plan: ArenaPlan,
    matches: tuple[ArenaMatchRecord, ...],
) -> None:
    if len(matches) != plan.pair_count * 2:
        raise ValueError("arena report requires exactly two records per pair")
    expected_indices = set(range(plan.pair_count))
    actual_indices = {item.pair_index for item in matches}
    if actual_indices != expected_indices:
        raise ValueError("arena pair indices are incomplete or out of range")
    for pair_index in range(plan.pair_count):
        pair = tuple(item for item in matches if item.pair_index == pair_index)
        if {item.leg for item in pair} != {
            MatchLeg.CANDIDATE_P1,
            MatchLeg.CANDIDATE_P2,
        }:
            raise ValueError("each pair requires one candidate leg in each seat")
        expected_engine_seed = plan.engine_seed_start + pair_index
        expected_agent_seed = plan.agent_seed_start + pair_index
        if {item.engine_seed for item in pair} != {expected_engine_seed}:
            raise ValueError("paired legs must share their planned engine seed")
        if {item.agent_seed for item in pair} != {expected_agent_seed}:
            raise ValueError("paired legs must share their planned agent seed")
        if not all(item.replay_verified for item in pair):
            raise ValueError("unverified Replay cannot enter a completed report")


def _record_sort_key(item: ArenaMatchRecord) -> tuple[int, int]:
    leg_order = 0 if item.leg is MatchLeg.CANDIDATE_P1 else 1
    return item.pair_index, leg_order


def _require_sha256(name: str, value: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def _signed_ratio_ppm(numerator: int, denominator: int) -> int:
    """Return exact integer ppm with symmetric truncation toward zero."""

    if denominator < 0:
        raise ValueError("ratio denominator must be non-negative")
    if denominator == 0:
        return 0
    sign = -1 if numerator < 0 else 1
    return sign * ((abs(numerator) * 1_000_000) // denominator)
