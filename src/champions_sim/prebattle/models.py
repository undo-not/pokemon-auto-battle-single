"""Versioned contracts for sealed singles team preview.

The battle engine deliberately starts from an already-selected three-Pokemon
``BattleState``.  These models keep the six-Pokemon roster and its private set
data outside that engine, and define the information that a preview policy may
observe.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Mapping

from champions_sim.core import (
    PlayerId,
    MegaEvolutionStatProfile,
    MoveSlotState,
    PokemonId,
    PokemonInstanceId,
    PokemonState,
    RuleSetId,
    StatBlock,
    StatStages,
    TrainingStatBlock,
    canonical_hash,
    canonical_json,
)


TEAM_PREVIEW_CONTRACT_VERSION = "1.0.0"
TEAM_PREVIEW_ROSTER_SIZE = 6
TEAM_PREVIEW_SELECTION_SIZE = 3

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_NONCE_RE = re.compile(r"[0-9a-f]{32,128}\Z")

_POLICY_IDENTITY_DOMAIN = "champions-sim/team-selection-policy-identity-v1"
_TEAM_PREVIEW_PROOF_DOMAIN = "champions-sim/team-preview-proof-v1"


class TeamPreviewError(ValueError):
    """Base error for an invalid team-preview contract operation."""


class TeamPreviewPhaseError(TeamPreviewError):
    """Raised when commit, reveal, or materialization happens out of phase."""


class TeamPreviewIntegrityError(TeamPreviewError):
    """Raised when a reveal, identity, or proof does not match bound material."""


class TeamPreviewPhase(str, Enum):
    COMMITTING = "committing"
    REVEALING = "revealing"
    COMPLETE = "complete"


@dataclass(frozen=True, slots=True)
class TeamPreviewRoster:
    """One player's private, ordered six-Pokemon roster.

    The order is the public preview-slot order.  The complete ``PokemonState``
    values remain private to the owning player and the trusted arena.
    """

    player: PlayerId
    members: tuple[PokemonState, ...]

    def __post_init__(self) -> None:
        if type(self.members) is not tuple or any(
            type(member) is not PokemonState for member in self.members
        ):
            raise TeamPreviewError(
                "team-preview rosters require exact PokemonState contracts"
            )
        if len(self.members) != TEAM_PREVIEW_ROSTER_SIZE:
            raise TeamPreviewError(
                f"{self.player.value} roster must contain exactly "
                f"{TEAM_PREVIEW_ROSTER_SIZE} Pokemon"
            )
        instance_ids = [member.instance_id for member in self.members]
        if len(set(instance_ids)) != len(instance_ids):
            raise TeamPreviewError(
                f"{self.player.value} roster instance IDs must be unique"
            )
        for member in self.members:
            _validate_exact_pokemon_state(member)
            self._validate_initial_member(member)

    def _validate_initial_member(self, member: PokemonState) -> None:
        """Reject battle-progress state at the six-Pokemon preview boundary."""

        prefix = f"{self.player.value} roster member {member.instance_id}"
        if member.fainted:
            raise TeamPreviewError(f"{prefix} must not be fainted")
        if member.hp != member.stats.max_hp:
            raise TeamPreviewError(f"{prefix} must start at full HP")
        if any(move.pp != move.max_pp for move in member.moves):
            raise TeamPreviewError(f"{prefix} must start with full move PP")
        if member.status_id is not None:
            raise TeamPreviewError(f"{prefix} must not have a status condition")
        if any(
            value != 0
            for value in (
                member.stat_stages.attack,
                member.stat_stages.defense,
                member.stat_stages.special_attack,
                member.stat_stages.special_defense,
                member.stat_stages.speed,
                member.stat_stages.accuracy,
                member.stat_stages.evasion,
            )
        ):
            raise TeamPreviewError(f"{prefix} must have zero stat stages")
        if member.volatile_statuses:
            raise TeamPreviewError(f"{prefix} must not have volatile statuses")
        if member.consumed_item_id is not None:
            raise TeamPreviewError(f"{prefix} must not have a consumed item")
        if member.revealed_to_opponent:
            raise TeamPreviewError(f"{prefix} must not be revealed to the opponent")
        if member.item_revealed_to_opponent:
            raise TeamPreviewError(f"{prefix} item must not be revealed to the opponent")
        if member.ability_revealed_to_opponent:
            raise TeamPreviewError(
                f"{prefix} ability must not be revealed to the opponent"
            )
        if any(move.revealed_to_opponent for move in member.moves):
            raise TeamPreviewError(f"{prefix} moves must not be revealed to the opponent")
        if member.mega_evolved:
            raise TeamPreviewError(f"{prefix} must not already be Mega Evolved")

    @property
    def roster_hash(self) -> str:
        """Integrity identity for the full roster, including concealed sets."""

        return canonical_hash(
            {
                "contract_version": TEAM_PREVIEW_CONTRACT_VERSION,
                "player": self.player,
                "members": self.members,
            }
        )

    def member(self, instance_id: PokemonInstanceId) -> PokemonState:
        for member in self.members:
            if member.instance_id == instance_id:
                return member
        raise KeyError(instance_id)


def _validate_exact_pokemon_state(member: PokemonState) -> None:
    if type(member.stats) is not StatBlock or type(member.stat_stages) is not StatStages:
        raise TeamPreviewError("team-preview members require exact stat contracts")
    if type(member.moves) is not tuple or any(
        type(move) is not MoveSlotState for move in member.moves
    ):
        raise TeamPreviewError("team-preview members require exact move-slot contracts")
    StatBlock.__post_init__(member.stats)
    StatStages.__post_init__(member.stat_stages)
    for move in member.moves:
        MoveSlotState.__post_init__(move)
    profile = member.mega_evolution_profile
    if profile is not None:
        if type(profile) is not MegaEvolutionStatProfile:
            raise TeamPreviewError("team-preview members require exact Mega profiles")
        if type(profile.stats) is not StatBlock or type(
            profile.ivs
        ) is not TrainingStatBlock or type(profile.evs) is not TrainingStatBlock:
            raise TeamPreviewError("team-preview members require exact Mega stat contracts")
        MegaEvolutionStatProfile.__post_init__(profile)
    PokemonState.__post_init__(member)


@dataclass(frozen=True, slots=True)
class TeamSelectionPolicyIdentity:
    """Canonical identity of the exact selection implementation/state/config."""

    policy_component: str
    source_sha256: str
    runtime_sha256: str
    initial_policy_state_hash: str
    configuration_json: str
    configuration_hash: str
    implementation_hash: str

    @classmethod
    def create(
        cls,
        *,
        policy_component: str,
        source_sha256: str,
        runtime_sha256: str,
        initial_policy_state_hash: str,
        configuration: Mapping[str, object],
    ) -> "TeamSelectionPolicyIdentity":
        configuration_json = canonical_json(configuration)
        configuration_hash = hashlib.sha256(
            configuration_json.encode("utf-8")
        ).hexdigest()
        payload = {
            "domain": _POLICY_IDENTITY_DOMAIN,
            "contract_version": TEAM_PREVIEW_CONTRACT_VERSION,
            "policy_component": policy_component,
            "source_sha256": source_sha256,
            "runtime_sha256": runtime_sha256,
            "initial_policy_state_hash": initial_policy_state_hash,
            "configuration_json": configuration_json,
            "configuration_hash": configuration_hash,
        }
        return cls(
            policy_component=policy_component,
            source_sha256=source_sha256,
            runtime_sha256=runtime_sha256,
            initial_policy_state_hash=initial_policy_state_hash,
            configuration_json=configuration_json,
            configuration_hash=configuration_hash,
            implementation_hash=canonical_hash(payload),
        )

    def __post_init__(self) -> None:
        if not self.policy_component:
            raise TeamPreviewError("policy_component must be non-empty")
        for name, value in (
            ("source_sha256", self.source_sha256),
            ("runtime_sha256", self.runtime_sha256),
            ("initial_policy_state_hash", self.initial_policy_state_hash),
            ("configuration_hash", self.configuration_hash),
            ("implementation_hash", self.implementation_hash),
        ):
            if not _SHA256_RE.fullmatch(value):
                raise TeamPreviewError(f"{name} must be a lowercase SHA-256 digest")
        try:
            configuration = json.loads(self.configuration_json)
        except json.JSONDecodeError as error:
            raise TeamPreviewError("configuration_json must be valid JSON") from error
        if not isinstance(configuration, dict):
            raise TeamPreviewError("policy configuration must be a JSON object")
        try:
            normalized = canonical_json(configuration)
        except TypeError as error:
            raise TeamPreviewError("policy configuration must be canonical") from error
        if normalized != self.configuration_json:
            raise TeamPreviewError("configuration_json must use canonical encoding")
        if hashlib.sha256(self.configuration_json.encode("utf-8")).hexdigest() != (
            self.configuration_hash
        ):
            raise TeamPreviewIntegrityError(
                "policy configuration hash does not match configuration_json"
            )
        if self.implementation_hash != self.expected_implementation_hash():
            raise TeamPreviewIntegrityError(
                "policy implementation hash does not match source/runtime/state/config identity"
            )

    def identity_payload(self) -> dict[str, object]:
        return {
            "domain": _POLICY_IDENTITY_DOMAIN,
            "contract_version": TEAM_PREVIEW_CONTRACT_VERSION,
            "policy_component": self.policy_component,
            "source_sha256": self.source_sha256,
            "runtime_sha256": self.runtime_sha256,
            "initial_policy_state_hash": self.initial_policy_state_hash,
            "configuration_json": self.configuration_json,
            "configuration_hash": self.configuration_hash,
        }

    def expected_implementation_hash(self) -> str:
        return canonical_hash(self.identity_payload())


@dataclass(frozen=True, slots=True)
class TeamPreviewProof:
    """Tamper-evident receipt for a completed deterministic preview run."""

    contract_version: str
    catalog_id: str
    catalog_hash: str
    ruleset_id: RuleSetId
    ruleset_hash: str
    session_hash: str
    materialized_state_hash: str
    seed: int
    roster_hash: str
    p1_policy: TeamSelectionPolicyIdentity
    p2_policy: TeamSelectionPolicyIdentity
    proof_hash: str

    @classmethod
    def create(
        cls,
        *,
        catalog_id: str,
        catalog_hash: str,
        ruleset_id: RuleSetId,
        ruleset_hash: str,
        session_hash: str,
        materialized_state_hash: str,
        seed: int,
        roster_hash: str,
        p1_policy: TeamSelectionPolicyIdentity,
        p2_policy: TeamSelectionPolicyIdentity,
    ) -> "TeamPreviewProof":
        payload = {
            "domain": _TEAM_PREVIEW_PROOF_DOMAIN,
            "contract_version": TEAM_PREVIEW_CONTRACT_VERSION,
            "catalog_id": catalog_id,
            "catalog_hash": catalog_hash,
            "ruleset_id": ruleset_id,
            "ruleset_hash": ruleset_hash,
            "session_hash": session_hash,
            "materialized_state_hash": materialized_state_hash,
            "seed": seed,
            "roster_hash": roster_hash,
            "p1_policy": p1_policy,
            "p2_policy": p2_policy,
        }
        return cls(
            contract_version=TEAM_PREVIEW_CONTRACT_VERSION,
            catalog_id=catalog_id,
            catalog_hash=catalog_hash,
            ruleset_id=ruleset_id,
            ruleset_hash=ruleset_hash,
            session_hash=session_hash,
            materialized_state_hash=materialized_state_hash,
            seed=seed,
            roster_hash=roster_hash,
            p1_policy=p1_policy,
            p2_policy=p2_policy,
            proof_hash=canonical_hash(payload),
        )

    def __post_init__(self) -> None:
        if self.contract_version != TEAM_PREVIEW_CONTRACT_VERSION:
            raise TeamPreviewError("unsupported team-preview proof contract version")
        if not self.catalog_id or not str(self.ruleset_id):
            raise TeamPreviewError("team-preview proof data identities must be non-empty")
        if type(self.p1_policy) is not TeamSelectionPolicyIdentity or type(
            self.p2_policy
        ) is not TeamSelectionPolicyIdentity:
            raise TeamPreviewError(
                "team-preview proof policies must be selection policy identities"
            )
        for name, value in (
            ("catalog_hash", self.catalog_hash),
            ("ruleset_hash", self.ruleset_hash),
            ("session_hash", self.session_hash),
            ("materialized_state_hash", self.materialized_state_hash),
            ("roster_hash", self.roster_hash),
            ("proof_hash", self.proof_hash),
        ):
            if not _SHA256_RE.fullmatch(value):
                raise TeamPreviewError(f"{name} must be a lowercase SHA-256 digest")
        if not 0 <= self.seed < 2**64:
            raise TeamPreviewError("team-preview proof seed must be unsigned 64-bit")
        if self.proof_hash != self.expected_proof_hash():
            raise TeamPreviewIntegrityError("team-preview proof hash does not match payload")

    def proof_payload(self) -> dict[str, object]:
        return {
            "domain": _TEAM_PREVIEW_PROOF_DOMAIN,
            "contract_version": self.contract_version,
            "catalog_id": self.catalog_id,
            "catalog_hash": self.catalog_hash,
            "ruleset_id": self.ruleset_id,
            "ruleset_hash": self.ruleset_hash,
            "session_hash": self.session_hash,
            "materialized_state_hash": self.materialized_state_hash,
            "seed": self.seed,
            "roster_hash": self.roster_hash,
            "p1_policy": self.p1_policy,
            "p2_policy": self.p2_policy,
        }

    def expected_proof_hash(self) -> str:
        return canonical_hash(self.proof_payload())


@dataclass(frozen=True, slots=True)
class PublicRosterMember:
    """Opponent-safe team-preview information for one roster slot.

    Instance IDs, stats, moves, item, ability, HP, and all runtime reveal flags
    are intentionally absent.  ``preview_slot`` is stable even when species are
    duplicated.
    """

    preview_slot: int
    pokemon_id: PokemonId
    level: int
    types: tuple[str, ...]

    def __post_init__(self) -> None:
        if not 0 <= self.preview_slot < TEAM_PREVIEW_ROSTER_SIZE:
            raise TeamPreviewError("preview_slot is outside the six-Pokemon roster")


@dataclass(frozen=True, slots=True)
class TeamSelectionReveal:
    """Private reveal payload submitted to the trusted preview coordinator."""

    contract_version: str
    session_id: str
    player: PlayerId
    ordered_instance_ids: tuple[PokemonInstanceId, ...]
    nonce_hex: str

    def __post_init__(self) -> None:
        if self.contract_version != TEAM_PREVIEW_CONTRACT_VERSION:
            raise TeamPreviewError("unsupported team-preview contract version")
        if not self.session_id:
            raise TeamPreviewError("session_id must be non-empty")
        if len(self.ordered_instance_ids) != TEAM_PREVIEW_SELECTION_SIZE:
            raise TeamPreviewError(
                f"selection must contain exactly {TEAM_PREVIEW_SELECTION_SIZE} Pokemon"
            )
        if len(set(self.ordered_instance_ids)) != len(self.ordered_instance_ids):
            raise TeamPreviewError("selection instance IDs must be unique")
        if not _NONCE_RE.fullmatch(self.nonce_hex):
            raise TeamPreviewError(
                "nonce_hex must be 128 to 512 bits of lowercase hexadecimal"
            )


@dataclass(frozen=True, slots=True)
class TeamSelectionCommitment:
    """Opaque SHA-256 commitment safe to submit before either reveal."""

    contract_version: str
    session_id: str
    player: PlayerId
    commitment_hash: str

    def __post_init__(self) -> None:
        if self.contract_version != TEAM_PREVIEW_CONTRACT_VERSION:
            raise TeamPreviewError("unsupported team-preview contract version")
        if not self.session_id:
            raise TeamPreviewError("session_id must be non-empty")
        if not _SHA256_RE.fullmatch(self.commitment_hash):
            raise TeamPreviewError(
                "commitment_hash must be a lowercase SHA-256 hexadecimal digest"
            )


@dataclass(frozen=True, slots=True)
class SealedTeamSelection:
    """Caller-owned pair; only ``commitment`` is submitted in commit phase."""

    commitment: TeamSelectionCommitment
    reveal: TeamSelectionReveal

    def __post_init__(self) -> None:
        if (
            self.commitment.contract_version != self.reveal.contract_version
            or self.commitment.session_id != self.reveal.session_id
            or self.commitment.player is not self.reveal.player
        ):
            raise TeamPreviewError("sealed selection commitment/reveal metadata mismatch")


@dataclass(frozen=True, slots=True)
class TeamPreviewObservation:
    """Centrally filtered policy input for one preview participant.

    The opponent's committed selection is never included, even after the
    coordinator has verified both reveals.  The battle engine will reveal only
    information made public by normal battle events.
    """

    contract_version: str
    session_id: str
    battle_id: str
    catalog_id: str
    catalog_hash: str
    ruleset_id: RuleSetId
    ruleset_hash: str
    viewer: PlayerId
    phase: TeamPreviewPhase
    own_roster: tuple[PokemonState, ...]
    own_roster_hash: str
    opponent_roster: tuple[PublicRosterMember, ...]
    own_committed: bool
    opponent_committed: bool
    own_revealed: bool
    opponent_revealed: bool
    own_selection: tuple[PokemonInstanceId, ...] | None
