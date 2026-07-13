"""Policy-free, version-bound AI environment adapter contracts."""

from .adapter import DeterministicBattleEnv, EnvironmentNotActionable, EnvironmentStateError
from .models import (
    AI_ENV_ADAPTER_SCHEMA_VERSION,
    AI_ENV_ADAPTER_VERSION,
    EvidenceStatus,
    EnvironmentBundleIdentity,
    EnvironmentScope,
    EnvironmentSnapshot,
    EnvironmentVersionIdentity,
    JointChoice,
    ResetInfo,
    ResetResult,
    SealedEnvironmentFixture,
    SealedEnvironmentInput,
    StepResult,
    TransitionInfo,
)

__all__ = [
    "AI_ENV_ADAPTER_SCHEMA_VERSION",
    "AI_ENV_ADAPTER_VERSION",
    "DeterministicBattleEnv",
    "EnvironmentNotActionable",
    "EnvironmentStateError",
    "EvidenceStatus",
    "EnvironmentBundleIdentity",
    "EnvironmentScope",
    "EnvironmentSnapshot",
    "EnvironmentVersionIdentity",
    "JointChoice",
    "ResetInfo",
    "ResetResult",
    "SealedEnvironmentFixture",
    "SealedEnvironmentInput",
    "StepResult",
    "TransitionInfo",
]
