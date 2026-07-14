"""AI-01 competitive evaluation contracts."""

from .models import (
    ARENA_SCHEMA_VERSION,
    ARENA_VERSION,
    AgentIdentity,
    ArenaMatchRecord,
    ArenaPlan,
    ArenaReport,
    ArenaSummary,
    CandidateOutcome,
    EvaluationPartition,
    MatchLeg,
    SeatSummary,
)
from .binding import BoundAgent, bind_agent
from .policies import (
    TypeAwareDamagePolicy,
    competitive_baseline_binding,
    competitive_baseline_identity,
    random_legal_agent_binding,
    random_legal_agent_identity,
    random_reference_binding,
    random_reference_identity,
    type_aware_agent_binding,
    type_aware_agent_identity,
)
from .runner import (
    ArenaRun,
    materialize_arena_leg,
    resolve_arena_run,
    run_paired_arena,
    verify_arena_run,
)

__all__ = [
    "ARENA_SCHEMA_VERSION",
    "ARENA_VERSION",
    "AgentIdentity",
    "BoundAgent",
    "ArenaMatchRecord",
    "ArenaPlan",
    "ArenaReport",
    "ArenaRun",
    "ArenaSummary",
    "CandidateOutcome",
    "EvaluationPartition",
    "MatchLeg",
    "SeatSummary",
    "TypeAwareDamagePolicy",
    "bind_agent",
    "competitive_baseline_binding",
    "competitive_baseline_identity",
    "materialize_arena_leg",
    "random_legal_agent_binding",
    "random_legal_agent_identity",
    "random_reference_identity",
    "random_reference_binding",
    "resolve_arena_run",
    "run_paired_arena",
    "type_aware_agent_binding",
    "type_aware_agent_identity",
    "verify_arena_run",
]
