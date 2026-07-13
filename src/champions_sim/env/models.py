"""Versioned contracts for the policy-free deterministic AI environment."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from champions_sim.core import (
    ActionSelection,
    BattleState,
    ExplicitRNG,
    PlayerId,
    PlayerObservation,
    canonical_hash,
    canonical_json,
    to_canonical_data,
)
from champions_sim.grounding import LegalActionMask, PublicEvent


AI_ENV_ADAPTER_SCHEMA_VERSION = "1.0.0"
AI_ENV_ADAPTER_VERSION = "ai-env-adapter-1.0.0"
NO_REWARD_MODEL_ID = "none"

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_STABLE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,239}$")
_PD_RE = re.compile(r"^PD-[0-9]{3}$")


def _require_hash(value: str, label: str) -> None:
    if _HASH_RE.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")


def _require_optional_hash(value: str | None, label: str) -> None:
    if value is not None:
        _require_hash(value, label)


def _require_stable_id(value: str, label: str) -> None:
    if _STABLE_ID_RE.fullmatch(value) is None:
        raise ValueError(f"{label} must be a stable ID")


def _require_pair(identifier: str | None, digest: str | None, label: str) -> None:
    if (identifier is None) != (digest is None):
        raise ValueError(f"{label} ID and hash must both be set or both be null")
    if identifier is not None:
        _require_stable_id(identifier, f"{label} ID")
    _require_optional_hash(digest, f"{label} hash")


def _require_unique(values: tuple[str, ...], label: str) -> None:
    if any(not value for value in values) or len(values) != len(set(values)):
        raise ValueError(f"{label} must contain unique non-empty values")


class EnvironmentScope(str, Enum):
    PURE_SIMULATOR_LOCAL = "pure_simulator_local"
    CHAMPIONS_CANDIDATE = "champions_candidate"


class EvidenceStatus(str, Enum):
    MISSING = "missing"
    UNVERIFIED = "unverified"
    VERIFIED = "verified"


@dataclass(frozen=True, slots=True)
class EnvironmentBundleIdentity:
    """Exact data and semantics identity used for an environment episode."""

    adapter_version: str
    simulator_version: str
    engine_semantics_version: str
    scope: EnvironmentScope
    catalog_id: str
    catalog_hash: str
    ruleset_id: str
    ruleset_hash: str
    regulation_id: str | None
    regulation_hash: str | None
    target_pool_id: str | None
    target_pool_hash: str | None
    capability_set_id: str | None
    capability_set_hash: str | None
    capability_status: EvidenceStatus
    grounding_assertion_set_id: str | None
    grounding_assertion_set_hash: str | None
    grounding_status: EvidenceStatus
    source_manifest_ids: tuple[str, ...]
    provisional_decision_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.adapter_version != AI_ENV_ADAPTER_VERSION:
            raise ValueError("unsupported AI environment adapter version")
        for value, label in (
            (self.simulator_version, "simulator_version"),
            (self.engine_semantics_version, "engine_semantics_version"),
            (self.catalog_id, "catalog_id"),
            (self.ruleset_id, "ruleset_id"),
        ):
            _require_stable_id(value, label)
        _require_hash(self.catalog_hash, "catalog_hash")
        _require_hash(self.ruleset_hash, "ruleset_hash")
        _require_pair(self.regulation_id, self.regulation_hash, "regulation")
        _require_pair(self.target_pool_id, self.target_pool_hash, "target pool")
        _require_pair(self.capability_set_id, self.capability_set_hash, "capability set")
        _require_pair(
            self.grounding_assertion_set_id,
            self.grounding_assertion_set_hash,
            "grounding assertion set",
        )
        if self.capability_status is EvidenceStatus.VERIFIED and self.capability_set_hash is None:
            raise ValueError("verified capability status requires a capability-set hash")
        if self.grounding_status is EvidenceStatus.VERIFIED and self.grounding_assertion_set_hash is None:
            raise ValueError("verified grounding status requires a grounding-set hash")
        _require_unique(self.source_manifest_ids, "source_manifest_ids")
        for value in self.source_manifest_ids:
            _require_stable_id(value, "source_manifest_id")
        _require_unique(self.provisional_decision_ids, "provisional_decision_ids")
        if any(_PD_RE.fullmatch(value) is None for value in self.provisional_decision_ids):
            raise ValueError("invalid provisional decision ID")
        if self.scope is EnvironmentScope.PURE_SIMULATOR_LOCAL:
            if any(
                value is not None
                for value in (
                    self.regulation_id,
                    self.target_pool_id,
                    self.capability_set_id,
                    self.grounding_assertion_set_id,
                )
            ):
                raise ValueError("pure simulator scope cannot claim external bundle identities")
            if (
                self.capability_status is not EvidenceStatus.MISSING
                or self.grounding_status is not EvidenceStatus.MISSING
            ):
                raise ValueError("pure simulator scope requires missing external evidence status")
        elif self.regulation_hash is None or self.target_pool_hash is None:
            raise ValueError("Champions candidate scope requires regulation and target-pool identity")

    @property
    def identity_hash(self) -> str:
        return canonical_hash(self)


@dataclass(frozen=True, slots=True)
class SealedEnvironmentFixture:
    fixture_id: str
    fixture_hash: str
    initial_state: BattleState

    def __post_init__(self) -> None:
        _require_stable_id(self.fixture_id, "fixture_id")
        _require_hash(self.fixture_hash, "fixture_hash")
        if canonical_hash(self.initial_state) != self.fixture_hash:
            raise ValueError("fixture_hash does not match the canonical initial state")

    @classmethod
    def seal(cls, fixture_id: str, initial_state: BattleState) -> "SealedEnvironmentFixture":
        return cls(
            fixture_id=fixture_id,
            fixture_hash=canonical_hash(initial_state),
            initial_state=initial_state,
        )


@dataclass(frozen=True, slots=True)
class SealedEnvironmentInput:
    schema_version: str
    bundle: EnvironmentBundleIdentity
    fixture: SealedEnvironmentFixture

    def __post_init__(self) -> None:
        if self.schema_version != AI_ENV_ADAPTER_SCHEMA_VERSION:
            raise ValueError("unsupported sealed environment input schema")
        if self.fixture.initial_state.ruleset_id != self.bundle.ruleset_id:
            raise ValueError("sealed fixture ruleset differs from bundle identity")

    @property
    def sealed_input_hash(self) -> str:
        return canonical_hash(self)


@dataclass(frozen=True, slots=True)
class EnvironmentVersionIdentity:
    adapter_schema_version: str
    bundle: EnvironmentBundleIdentity
    bundle_identity_hash: str
    fixture_id: str
    fixture_hash: str
    sealed_input_hash: str
    episode_id: str
    viewer: PlayerId
    seed: int
    rng_algorithm_id: str

    def __post_init__(self) -> None:
        if self.adapter_schema_version != AI_ENV_ADAPTER_SCHEMA_VERSION:
            raise ValueError("unsupported environment identity schema")
        if self.bundle_identity_hash != self.bundle.identity_hash:
            raise ValueError("bundle identity hash does not match its payload")
        _require_stable_id(self.fixture_id, "fixture_id")
        for value, label in (
            (self.fixture_hash, "fixture_hash"),
            (self.sealed_input_hash, "sealed_input_hash"),
        ):
            _require_hash(value, label)
        _require_stable_id(self.episode_id, "episode_id")
        if not 0 <= self.seed < 2**64:
            raise ValueError("seed must be an unsigned 64-bit integer")
        _require_stable_id(self.rng_algorithm_id, "rng_algorithm_id")


@dataclass(frozen=True, slots=True)
class EnvironmentSnapshot:
    schema_version: str
    identity: EnvironmentVersionIdentity
    step_index: int
    observation: PlayerObservation
    public_history: tuple[PublicEvent, ...]
    legal_action_mask: LegalActionMask
    decision_commitment: str | None
    actionable: bool
    blockers: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != AI_ENV_ADAPTER_SCHEMA_VERSION:
            raise ValueError("unsupported environment snapshot schema")
        if self.step_index < 0:
            raise ValueError("step_index must be non-negative")
        if self.observation.viewer is not self.identity.viewer:
            raise ValueError("observation viewer differs from episode identity")
        if self.decision_commitment is not None:
            _require_hash(self.decision_commitment, "decision_commitment")
        sequences = tuple(value.sequence for value in self.public_history)
        if sequences != tuple(range(len(sequences))):
            raise ValueError("public history sequences must be contiguous from zero")
        _require_unique(self.blockers, "snapshot blockers")
        expected_actionable = not self.blockers and self.legal_action_mask.actionable
        if self.actionable != expected_actionable:
            raise ValueError("snapshot actionable flag disagrees with blockers/legal mask")
        if self.legal_action_mask.actionable and self.decision_commitment is None:
            raise ValueError("actionable observations require a decision commitment")

    def to_dict(self) -> dict[str, Any]:
        payload = to_canonical_data(self)
        assert isinstance(payload, dict)
        return payload

    def to_json(self) -> str:
        return canonical_json(self)


@dataclass(frozen=True, slots=True)
class JointChoice:
    episode_id: str
    step_index: int
    decision_commitment: str
    selections: tuple[ActionSelection, ...]

    def __post_init__(self) -> None:
        _require_stable_id(self.episode_id, "episode_id")
        if self.step_index < 0:
            raise ValueError("step_index must be non-negative")
        _require_hash(self.decision_commitment, "decision_commitment")
        if not self.selections:
            raise ValueError("joint choice requires at least one selection")
        players = tuple(value.player for value in self.selections)
        if len(players) != len(set(players)):
            raise ValueError("joint choice may select once per player")
        expected_order = tuple(sorted(players, key=lambda value: value.value))
        if players != expected_order:
            raise ValueError("joint choice selections must be ordered by player ID")

    @property
    def choice_hash(self) -> str:
        return canonical_hash(self)


@dataclass(frozen=True, slots=True)
class ResetInfo:
    reset_id: str
    initial_state_hash: str
    initialized_state_hash: str
    initial_events_hash: str
    public_history_hash: str
    rng_seed: int
    rng_cursor_before: int
    rng_cursor_after: int
    rng_state_hash_before: str
    rng_state_hash_after: str
    reward_model_id: str

    def __post_init__(self) -> None:
        _require_stable_id(self.reset_id, "reset_id")
        for value, label in (
            (self.initial_state_hash, "initial_state_hash"),
            (self.initialized_state_hash, "initialized_state_hash"),
            (self.initial_events_hash, "initial_events_hash"),
            (self.public_history_hash, "public_history_hash"),
            (self.rng_state_hash_before, "rng_state_hash_before"),
            (self.rng_state_hash_after, "rng_state_hash_after"),
        ):
            _require_hash(value, label)
        if self.rng_cursor_before < 0 or self.rng_cursor_after < self.rng_cursor_before:
            raise ValueError("reset RNG cursors are not monotonic")
        if self.reward_model_id != NO_REWARD_MODEL_ID:
            raise ValueError("AI environment contract does not define a reward model")


@dataclass(frozen=True, slots=True)
class TransitionInfo:
    transition_id: str
    state_hash_before: str
    state_hash_after: str
    decision_commitment_before: str
    choice_hash: str
    events_hash: str
    public_history_hash: str
    rng_seed: int
    rng_cursor_before: int
    rng_cursor_after: int
    rng_state_hash_before: str
    rng_state_hash_after: str
    reward_model_id: str
    provisional_decision_ids: tuple[str, ...]
    source_manifest_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_stable_id(self.transition_id, "transition_id")
        for value, label in (
            (self.state_hash_before, "state_hash_before"),
            (self.state_hash_after, "state_hash_after"),
            (self.decision_commitment_before, "decision_commitment_before"),
            (self.choice_hash, "choice_hash"),
            (self.events_hash, "events_hash"),
            (self.public_history_hash, "public_history_hash"),
            (self.rng_state_hash_before, "rng_state_hash_before"),
            (self.rng_state_hash_after, "rng_state_hash_after"),
        ):
            _require_hash(value, label)
        if self.rng_cursor_before < 0 or self.rng_cursor_after < self.rng_cursor_before:
            raise ValueError("transition RNG cursors are not monotonic")
        if self.reward_model_id != NO_REWARD_MODEL_ID:
            raise ValueError("AI environment contract does not define a reward model")
        _require_unique(self.provisional_decision_ids, "provisional_decision_ids")
        _require_unique(self.source_manifest_ids, "source_manifest_ids")


@dataclass(frozen=True, slots=True)
class ResetResult:
    schema_version: str
    kind: str
    snapshot: EnvironmentSnapshot
    info: ResetInfo

    def __post_init__(self) -> None:
        if self.schema_version != AI_ENV_ADAPTER_SCHEMA_VERSION or self.kind != "reset":
            raise ValueError("invalid reset result envelope")

    def to_dict(self) -> dict[str, Any]:
        payload = to_canonical_data(self)
        assert isinstance(payload, dict)
        return payload

    def to_json(self) -> str:
        return canonical_json(self)


@dataclass(frozen=True, slots=True)
class StepResult:
    schema_version: str
    kind: str
    snapshot: EnvironmentSnapshot
    reward: None
    terminated: bool
    truncated: bool
    info: TransitionInfo

    def __post_init__(self) -> None:
        if self.schema_version != AI_ENV_ADAPTER_SCHEMA_VERSION or self.kind != "step":
            raise ValueError("invalid step result envelope")
        if self.reward is not None:
            raise ValueError("reward is intentionally undefined in the AI environment contract")
        if self.truncated:
            raise ValueError("adapter v1 has no wrapper-level truncation policy")
        if self.terminated != (self.snapshot.observation.winner is not None or self.snapshot.observation.phase.value == "finished"):
            raise ValueError("terminated flag disagrees with the player observation")

    def to_dict(self) -> dict[str, Any]:
        payload = to_canonical_data(self)
        assert isinstance(payload, dict)
        return payload

    def to_json(self) -> str:
        return canonical_json(self)


def rng_state_hash(rng: ExplicitRNG) -> str:
    return canonical_hash(rng)
