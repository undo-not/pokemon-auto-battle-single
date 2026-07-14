"""Immutable coordinator for simultaneous sealed team selection."""

from __future__ import annotations

from copy import deepcopy
import hmac
import re
from dataclasses import dataclass, replace

from champions_sim.catalog import CatalogSnapshot, RuleSetSnapshot
from champions_sim.core import (
    BattlePhase,
    BattleState,
    PlayerId,
    PokemonInstanceId,
    RuleSetId,
    SideState,
    canonical_hash,
)

from .models import (
    TEAM_PREVIEW_CONTRACT_VERSION,
    PublicRosterMember,
    SealedTeamSelection,
    TeamPreviewError,
    TeamPreviewIntegrityError,
    TeamPreviewObservation,
    TeamPreviewPhase,
    TeamPreviewPhaseError,
    TeamPreviewRoster,
    TeamSelectionCommitment,
    TeamSelectionReveal,
)


_COMMITMENT_DOMAIN = "champions-sim/team-preview-selection-commitment"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class TeamPreviewSession:
    """Trusted, immutable six-to-three team-preview state.

    Roster and reveal payloads are complete private state.  Policies must only
    receive ``observation_for`` results, never this coordinator object.
    """

    contract_version: str
    session_id: str
    battle_id: str
    catalog_id: str
    catalog_hash: str
    ruleset_id: RuleSetId
    ruleset_hash: str
    rosters: tuple[TeamPreviewRoster, TeamPreviewRoster]
    commitments: tuple[TeamSelectionCommitment, ...] = ()
    reveals: tuple[TeamSelectionReveal, ...] = ()

    def __post_init__(self) -> None:
        if self.contract_version != TEAM_PREVIEW_CONTRACT_VERSION:
            raise TeamPreviewError("unsupported team-preview contract version")
        if not self.session_id:
            raise TeamPreviewError("session_id must be non-empty")
        if not self.battle_id:
            raise TeamPreviewError("battle_id must be non-empty")
        if not self.catalog_id:
            raise TeamPreviewError("catalog_id must be non-empty")
        if _SHA256_RE.fullmatch(self.catalog_hash) is None:
            raise TeamPreviewError("catalog_hash must be a lowercase SHA-256 digest")
        if _SHA256_RE.fullmatch(self.ruleset_hash) is None:
            raise TeamPreviewError("ruleset_hash must be a lowercase SHA-256 digest")
        if any(type(roster) is not TeamPreviewRoster for roster in self.rosters):
            raise TeamPreviewError("rosters must use the exact TeamPreviewRoster contract")
        if tuple(roster.player for roster in self.rosters) != (
            PlayerId.P1,
            PlayerId.P2,
        ):
            raise TeamPreviewError("rosters must be ordered P1 then P2")
        all_ids = [
            member.instance_id
            for roster in self.rosters
            for member in roster.members
        ]
        if len(set(all_ids)) != len(all_ids):
            raise TeamPreviewError("Pokemon instance IDs must be unique across rosters")

        self._validate_records(self.commitments, record_name="commitment")
        self._validate_records(self.reveals, record_name="reveal")
        if self.reveals and len(self.commitments) != 2:
            raise TeamPreviewPhaseError("reveals require both player commitments")
        committed_players = {record.player for record in self.commitments}
        for reveal in self.reveals:
            if reveal.player not in committed_players:
                raise TeamPreviewPhaseError("reveal has no player commitment")
            self._validate_selection_membership(reveal)
            commitment = self._commitment_for(reveal.player)
            expected = self._commitment_hash(reveal)
            if not hmac.compare_digest(commitment.commitment_hash, expected):
                raise TeamPreviewIntegrityError(
                    f"{reveal.player.value} reveal does not match its commitment"
                )

    @classmethod
    def create(
        cls,
        *,
        session_id: str,
        battle_id: str,
        catalog: CatalogSnapshot,
        ruleset: RuleSetSnapshot,
        p1_roster: TeamPreviewRoster,
        p2_roster: TeamPreviewRoster,
    ) -> "TeamPreviewSession":
        session = cls(
            contract_version=TEAM_PREVIEW_CONTRACT_VERSION,
            session_id=session_id,
            battle_id=battle_id,
            catalog_id=catalog.catalog_id,
            catalog_hash=catalog.snapshot_hash,
            ruleset_id=ruleset.ruleset_id,
            ruleset_hash=ruleset.snapshot_hash,
            rosters=(p1_roster, p2_roster),
        )
        session.validate_against(catalog, ruleset)
        return session

    def validate_against(
        self,
        catalog: CatalogSnapshot,
        ruleset: RuleSetSnapshot,
    ) -> None:
        """Validate all six sets against the exact Catalog and RuleSet."""

        checks = (
            ("catalog_id", self.catalog_id, catalog.catalog_id),
            ("catalog_hash", self.catalog_hash, catalog.snapshot_hash),
            ("ruleset_id", self.ruleset_id, ruleset.ruleset_id),
            ("ruleset_hash", self.ruleset_hash, ruleset.snapshot_hash),
        )
        mismatches = [name for name, actual, expected in checks if actual != expected]
        if mismatches:
            raise TeamPreviewError(
                f"team-preview data identity mismatch: {mismatches}"
            )
        for roster in self.rosters:
            roster.__post_init__()
            held_items = tuple(
                str(member.item_id)
                for member in roster.members
                if member.item_id is not None
            )
            if ruleset.item_clause and len(held_items) != len(set(held_items)):
                raise TeamPreviewError(
                    f"{roster.player.value} roster violates the item clause"
                )
            species = tuple(str(member.pokemon_id) for member in roster.members)
            if bool(ruleset.raw.get("species_clause", False)) and len(species) != len(
                set(species)
            ):
                raise TeamPreviewError(
                    f"{roster.player.value} roster violates the species clause"
                )
            for member in roster.members:
                if len(member.moves) != 4:
                    raise TeamPreviewError(
                        f"{member.instance_id} must declare exactly 4 moves"
                    )
                if member.level != ruleset.level:
                    raise TeamPreviewError(
                        f"{member.instance_id} level differs from the RuleSet"
                    )
                try:
                    definition = catalog.pokemon(member.pokemon_id)
                    move_definitions = tuple(
                        catalog.move(slot.move_id) for slot in member.moves
                    )
                    if member.ability_id is None:
                        raise TeamPreviewError(
                            f"{member.instance_id} must declare its private ability"
                        )
                    catalog.ability(member.ability_id)
                    if member.item_id is not None:
                        catalog.item(member.item_id)
                except KeyError as exc:
                    raise TeamPreviewError(
                        f"{member.instance_id} references an unknown Catalog entity"
                    ) from exc
                if member.types != definition.types:
                    raise TeamPreviewError(
                        f"{member.instance_id} types differ from the Catalog"
                    )
                if member.ability_id not in definition.ability_ids:
                    raise TeamPreviewError(
                        f"{member.instance_id} ability is illegal for its species"
                    )
                if any(
                    slot.move_id not in definition.legal_move_ids
                    for slot in member.moves
                ):
                    raise TeamPreviewError(
                        f"{member.instance_id} move is illegal for its species"
                    )
                if any(
                    slot.max_pp != move.pp
                    for slot, move in zip(
                        member.moves, move_definitions, strict=True
                    )
                ):
                    raise TeamPreviewError(
                        f"{member.instance_id} move PP differs from the Catalog"
                    )
                if member.mega_evolution_profile is not None:
                    if member.item_id is None:
                        raise TeamPreviewError(
                            f"{member.instance_id} Mega profile requires an item"
                        )
                    try:
                        mega = catalog.mega_evolution(
                            member.pokemon_id, member.item_id
                        )
                    except KeyError as exc:
                        raise TeamPreviewError(
                            f"{member.instance_id} Mega profile is not Catalog-grounded"
                        ) from exc
                    if (
                        mega.mega_pokemon_id
                        != member.mega_evolution_profile.target_pokemon_id
                    ):
                        raise TeamPreviewError(
                            f"{member.instance_id} Mega target differs from the Catalog"
                        )

    @property
    def phase(self) -> TeamPreviewPhase:
        if len(self.reveals) == 2:
            return TeamPreviewPhase.COMPLETE
        if len(self.commitments) == 2:
            return TeamPreviewPhase.REVEALING
        return TeamPreviewPhase.COMMITTING

    @property
    def session_hash(self) -> str:
        """Bind the private rosters, commitments, and reveals without exposing them."""

        return canonical_hash(self)

    def roster(self, player: PlayerId) -> TeamPreviewRoster:
        return self.rosters[0] if player is PlayerId.P1 else self.rosters[1]

    def seal_selection(
        self,
        player: PlayerId,
        ordered_instance_ids: tuple[PokemonInstanceId, ...],
        *,
        nonce_hex: str,
    ) -> SealedTeamSelection:
        """Create a hash-bound commitment/reveal pair without changing state."""

        reveal = TeamSelectionReveal(
            contract_version=self.contract_version,
            session_id=self.session_id,
            player=player,
            ordered_instance_ids=ordered_instance_ids,
            nonce_hex=nonce_hex,
        )
        self._validate_selection_membership(reveal)
        commitment = TeamSelectionCommitment(
            contract_version=self.contract_version,
            session_id=self.session_id,
            player=player,
            commitment_hash=self._commitment_hash(reveal),
        )
        return SealedTeamSelection(commitment=commitment, reveal=reveal)

    def commit(self, commitment: TeamSelectionCommitment) -> "TeamPreviewSession":
        if self.phase is not TeamPreviewPhase.COMMITTING:
            raise TeamPreviewPhaseError("commit phase is closed")
        self._validate_record_metadata(commitment)
        if any(record.player is commitment.player for record in self.commitments):
            raise TeamPreviewPhaseError(
                f"{commitment.player.value} already submitted a commitment"
            )
        commitments = tuple(
            sorted(
                (*self.commitments, commitment),
                key=lambda record: record.player.value,
            )
        )
        return replace(self, commitments=commitments)

    def reveal(self, reveal: TeamSelectionReveal) -> "TeamPreviewSession":
        if self.phase is not TeamPreviewPhase.REVEALING:
            raise TeamPreviewPhaseError("both commitments are required before reveal")
        self._validate_record_metadata(reveal)
        if any(record.player is reveal.player for record in self.reveals):
            raise TeamPreviewPhaseError(
                f"{reveal.player.value} already submitted a reveal"
            )
        self._validate_selection_membership(reveal)
        commitment = self._commitment_for(reveal.player)
        if not hmac.compare_digest(
            commitment.commitment_hash,
            self._commitment_hash(reveal),
        ):
            raise TeamPreviewIntegrityError(
                f"{reveal.player.value} reveal does not match its commitment"
            )
        reveals = tuple(
            sorted((*self.reveals, reveal), key=lambda record: record.player.value)
        )
        return replace(self, reveals=reveals)

    def observation_for(self, viewer: PlayerId) -> TeamPreviewObservation:
        """Return the sole policy-safe view over private preview state."""

        own_roster = self.roster(viewer)
        opponent_roster = self.roster(viewer.opponent)
        own_reveal = self._optional_reveal_for(viewer)
        return TeamPreviewObservation(
            contract_version=self.contract_version,
            session_id=self.session_id,
            battle_id=self.battle_id,
            catalog_id=self.catalog_id,
            catalog_hash=self.catalog_hash,
            ruleset_id=self.ruleset_id,
            ruleset_hash=self.ruleset_hash,
            viewer=viewer,
            phase=self.phase,
            # Frozen dataclasses are not a memory-isolation boundary because
            # hostile in-process code can still use ``object.__setattr__``.
            # Give every policy a detached object graph so such writes cannot
            # alter the coordinator-owned roster or later materialization.
            own_roster=deepcopy(own_roster.members),
            own_roster_hash=own_roster.roster_hash,
            opponent_roster=tuple(
                PublicRosterMember(
                    preview_slot=slot,
                    pokemon_id=member.pokemon_id,
                    level=member.level,
                    types=member.types,
                )
                for slot, member in enumerate(opponent_roster.members)
            ),
            own_committed=self._has_commitment(viewer),
            opponent_committed=self._has_commitment(viewer.opponent),
            own_revealed=own_reveal is not None,
            opponent_revealed=self._optional_reveal_for(viewer.opponent) is not None,
            own_selection=(
                own_reveal.ordered_instance_ids if own_reveal is not None else None
            ),
        )

    def materialize(self) -> BattleState:
        """Build the selected three-Pokemon state expected by ``BattleEngine``."""

        if self.phase is not TeamPreviewPhase.COMPLETE:
            raise TeamPreviewPhaseError("both selections must be revealed before materialize")
        sides = []
        for player in (PlayerId.P1, PlayerId.P2):
            roster = self.roster(player)
            reveal = self._reveal_for(player)
            team = tuple(roster.member(instance_id) for instance_id in reveal.ordered_instance_ids)
            sides.append(
                SideState(
                    player=player,
                    team=team,
                    active_instance_id=reveal.ordered_instance_ids[0],
                )
            )
        return BattleState(
            battle_id=self.battle_id,
            ruleset_id=self.ruleset_id,
            turn=0,
            phase=BattlePhase.TEAM_PREVIEW,
            sides=(sides[0], sides[1]),
        )

    def _commitment_hash(self, reveal: TeamSelectionReveal) -> str:
        return canonical_hash(
            {
                "domain": _COMMITMENT_DOMAIN,
                "contract_version": self.contract_version,
                "session_id": self.session_id,
                "battle_id": self.battle_id,
                "catalog_id": self.catalog_id,
                "catalog_hash": self.catalog_hash,
                "ruleset_id": self.ruleset_id,
                "ruleset_hash": self.ruleset_hash,
                "player": reveal.player,
                "roster_hash": self.roster(reveal.player).roster_hash,
                "ordered_instance_ids": reveal.ordered_instance_ids,
                "nonce_hex": reveal.nonce_hex,
            }
        )

    def _validate_selection_membership(self, reveal: TeamSelectionReveal) -> None:
        roster_ids = {member.instance_id for member in self.roster(reveal.player).members}
        unknown = [
            instance_id
            for instance_id in reveal.ordered_instance_ids
            if instance_id not in roster_ids
        ]
        if unknown:
            raise TeamPreviewError(
                f"{reveal.player.value} selection contains out-of-roster instance IDs: "
                + ", ".join(str(value) for value in unknown)
            )

    def _validate_records(
        self,
        records: tuple[TeamSelectionCommitment, ...] | tuple[TeamSelectionReveal, ...],
        *,
        record_name: str,
    ) -> None:
        if len(records) > 2:
            raise TeamPreviewError(f"at most two {record_name} records are allowed")
        players = [record.player for record in records]
        if len(set(players)) != len(players):
            raise TeamPreviewError(f"duplicate player {record_name}")
        if tuple(players) != tuple(sorted(players, key=lambda player: player.value)):
            raise TeamPreviewError(f"{record_name} records must be ordered P1 then P2")
        for record in records:
            self._validate_record_metadata(record)

    def _validate_record_metadata(
        self,
        record: TeamSelectionCommitment | TeamSelectionReveal,
    ) -> None:
        if record.contract_version != self.contract_version:
            raise TeamPreviewError("record contract version does not match session")
        if record.session_id != self.session_id:
            raise TeamPreviewError("record session_id does not match session")

    def _has_commitment(self, player: PlayerId) -> bool:
        return any(record.player is player for record in self.commitments)

    def _commitment_for(self, player: PlayerId) -> TeamSelectionCommitment:
        for commitment in self.commitments:
            if commitment.player is player:
                return commitment
        raise TeamPreviewPhaseError(f"{player.value} has no commitment")

    def _optional_reveal_for(self, player: PlayerId) -> TeamSelectionReveal | None:
        for reveal in self.reveals:
            if reveal.player is player:
                return reveal
        return None

    def _reveal_for(self, player: PlayerId) -> TeamSelectionReveal:
        reveal = self._optional_reveal_for(player)
        if reveal is None:
            raise TeamPreviewPhaseError(f"{player.value} has no verified reveal")
        return reveal
