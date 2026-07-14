from __future__ import annotations

from dataclasses import fields, replace
from pathlib import Path

import pytest

from champions_sim import BattleEngine, load_battle_fixture, load_catalog, load_ruleset
from champions_sim.core import (
    BattlePhase,
    MoveId,
    PlayerId,
    PokemonState,
    PokemonInstanceId,
    StatBlock,
    canonical_hash,
)
from champions_sim.prebattle import (
    TEAM_PREVIEW_CONTRACT_VERSION,
    PublicRosterMember,
    TeamPreviewError,
    TeamPreviewIntegrityError,
    TeamPreviewPhase,
    TeamPreviewPhaseError,
    TeamPreviewRoster,
    TeamPreviewSession,
)


ROOT = Path(__file__).resolve().parents[1]
P1_NONCE = "11" * 16
P2_NONCE = "22" * 16


def _loaded() -> tuple[BattleEngine, object, object]:
    catalog = load_catalog(ROOT / "data/fixtures/sim01_catalog.json")
    ruleset = load_ruleset(ROOT / "data/fixtures/sim01_ruleset.json")
    fixture = load_battle_fixture(
        ROOT / "data/fixtures/sim01_battle.json",
        catalog=catalog,
        ruleset=ruleset,
    )
    return BattleEngine(catalog, ruleset), ruleset, fixture


def _six_member_roster(side: object) -> TeamPreviewRoster:
    # SIM-01 has three battle members.  Deterministic reserve copies exercise
    # the outer six-to-three contract without changing the frozen fixture.
    members = side.team  # type: ignore[attr-defined]
    reserves = tuple(
        replace(
            member,
            instance_id=PokemonInstanceId(f"{member.instance_id}-reserve"),
            item_id=None,
        )
        for member in members
    )
    return TeamPreviewRoster(player=side.player, members=(*members, *reserves))  # type: ignore[attr-defined]


def _session() -> tuple[TeamPreviewSession, BattleEngine, object]:
    engine, ruleset, fixture = _loaded()
    state = fixture.initial_state
    session = TeamPreviewSession.create(
        session_id="sim01-preview-session",
        battle_id="sim01-preview-battle",
        catalog=engine.catalog,
        ruleset=ruleset,
        p1_roster=_six_member_roster(state.side(PlayerId.P1)),
        p2_roster=_six_member_roster(state.side(PlayerId.P2)),
    )
    return session, engine, fixture


def _ids(session: TeamPreviewSession, player: PlayerId) -> tuple[PokemonInstanceId, ...]:
    return tuple(member.instance_id for member in session.roster(player).members)


def _complete(
    session: TeamPreviewSession,
    *,
    p1_selection: tuple[PokemonInstanceId, ...] | None = None,
    p2_selection: tuple[PokemonInstanceId, ...] | None = None,
) -> TeamPreviewSession:
    p1_ids = _ids(session, PlayerId.P1)
    p2_ids = _ids(session, PlayerId.P2)
    p1 = session.seal_selection(
        PlayerId.P1,
        p1_selection or (p1_ids[1], p1_ids[0], p1_ids[2]),
        nonce_hex=P1_NONCE,
    )
    p2 = session.seal_selection(
        PlayerId.P2,
        p2_selection or (p2_ids[2], p2_ids[1], p2_ids[0]),
        nonce_hex=P2_NONCE,
    )
    # Arrival order is deliberately reversed.  Stored records remain canonical.
    session = session.commit(p2.commitment).commit(p1.commitment)
    session = session.reveal(p2.reveal).reveal(p1.reveal)
    return session


def test_roster_requires_exactly_six_unique_members_and_global_ids() -> None:
    session, engine, _ = _session()
    p1 = session.roster(PlayerId.P1)
    p2 = session.roster(PlayerId.P2)

    with pytest.raises(TeamPreviewError, match="exactly 6"):
        TeamPreviewRoster(player=PlayerId.P1, members=p1.members[:5])
    with pytest.raises(TeamPreviewError, match="exactly 6"):
        TeamPreviewRoster(
            player=PlayerId.P1,
            members=(*p1.members, p1.members[0]),
        )
    with pytest.raises(TeamPreviewError, match="instance IDs must be unique"):
        TeamPreviewRoster(
            player=PlayerId.P1,
            members=(*p1.members[:5], p1.members[0]),
        )

    colliding_member = replace(
        p2.members[0],
        instance_id=p1.members[0].instance_id,
    )
    colliding_p2 = TeamPreviewRoster(
        player=PlayerId.P2,
        members=(colliding_member, *p2.members[1:]),
    )
    with pytest.raises(TeamPreviewError, match="unique across rosters"):
        TeamPreviewSession.create(
            session_id=session.session_id,
            battle_id=session.battle_id,
            catalog=engine.catalog,
            ruleset=engine.ruleset,
            p1_roster=p1,
            p2_roster=colliding_p2,
        )

    class LeakyPokemonState(PokemonState):
        leaked_private_marker = "should-never-reach-policy"

    leaky = LeakyPokemonState(
        **{
            field.name: getattr(p1.members[0], field.name)
            for field in fields(PokemonState)
        }
    )
    with pytest.raises(TeamPreviewError, match="exact PokemonState"):
        TeamPreviewRoster(
            player=PlayerId.P1,
            members=(leaky, *p1.members[1:]),
        )


def test_session_rejects_duplicate_held_items_and_catalog_illegal_moves() -> None:
    session, engine, _ = _session()
    p1 = session.roster(PlayerId.P1)
    p2 = session.roster(PlayerId.P2)

    duplicate_item_member = replace(
        p1.members[1],
        item_id=p1.members[0].item_id,
    )
    duplicate_item_roster = TeamPreviewRoster(
        player=PlayerId.P1,
        members=(p1.members[0], duplicate_item_member, *p1.members[2:]),
    )
    with pytest.raises(TeamPreviewError, match="item clause"):
        TeamPreviewSession.create(
            session_id=session.session_id,
            battle_id=session.battle_id,
            catalog=engine.catalog,
            ruleset=engine.ruleset,
            p1_roster=duplicate_item_roster,
            p2_roster=p2,
        )

    # Surf exists in the Catalog and has valid PP, but is not legal for Garchomp.
    illegal_move_member = replace(
        p1.members[0],
        moves=(p1.members[1].moves[0], *p1.members[0].moves[1:]),
    )
    illegal_move_roster = TeamPreviewRoster(
        player=PlayerId.P1,
        members=(illegal_move_member, *p1.members[1:]),
    )
    with pytest.raises(TeamPreviewError, match="move is illegal"):
        TeamPreviewSession.create(
            session_id=session.session_id,
            battle_id=session.battle_id,
            catalog=engine.catalog,
            ruleset=engine.ruleset,
            p1_roster=illegal_move_roster,
            p2_roster=p2,
        )

    missing_ability_roster = TeamPreviewRoster(
        player=PlayerId.P1,
        members=(replace(p1.members[0], ability_id=None), *p1.members[1:]),
    )
    with pytest.raises(TeamPreviewError, match="must declare its private ability"):
        TeamPreviewSession.create(
            session_id="preview-missing-ability",
            battle_id="preview-missing-ability-battle",
            catalog=engine.catalog,
            ruleset=engine.ruleset,
            p1_roster=missing_ability_roster,
            p2_roster=p2,
        )

    missing_moves_roster = TeamPreviewRoster(
        player=PlayerId.P1,
        members=(
            *p1.members[:5],
            replace(p1.members[5], moves=()),
        ),
    )
    with pytest.raises(TeamPreviewError, match="must declare exactly 4 moves"):
        TeamPreviewSession.create(
            session_id="preview-missing-moves",
            battle_id="preview-missing-moves-battle",
            catalog=engine.catalog,
            ruleset=engine.ruleset,
            p1_roster=missing_moves_roster,
            p2_roster=p2,
        )


def test_selection_validates_size_duplicates_membership_and_nonce() -> None:
    session, _, _ = _session()
    ids = _ids(session, PlayerId.P1)

    with pytest.raises(TeamPreviewError, match="exactly 3"):
        session.seal_selection(PlayerId.P1, ids[:2], nonce_hex=P1_NONCE)
    with pytest.raises(TeamPreviewError, match="must be unique"):
        session.seal_selection(
            PlayerId.P1,
            (ids[0], ids[0], ids[1]),
            nonce_hex=P1_NONCE,
        )
    with pytest.raises(TeamPreviewError, match="out-of-roster"):
        session.seal_selection(
            PlayerId.P1,
            (ids[0], ids[1], PokemonInstanceId("not-in-roster")),
            nonce_hex=P1_NONCE,
        )
    with pytest.raises(TeamPreviewError, match="128 to 512 bits"):
        session.seal_selection(
            PlayerId.P1,
            ids[:3],
            nonce_hex="too-short",
        )


def test_commit_then_reveal_is_simultaneous_order_bound_and_hash_verified() -> None:
    session, _, _ = _session()
    p1_ids = _ids(session, PlayerId.P1)
    p2_ids = _ids(session, PlayerId.P2)
    p1 = session.seal_selection(
        PlayerId.P1,
        (p1_ids[1], p1_ids[0], p1_ids[2]),
        nonce_hex=P1_NONCE,
    )
    reordered = session.seal_selection(
        PlayerId.P1,
        (p1_ids[0], p1_ids[1], p1_ids[2]),
        nonce_hex=P1_NONCE,
    )
    renonced = session.seal_selection(
        PlayerId.P1,
        (p1_ids[1], p1_ids[0], p1_ids[2]),
        nonce_hex="33" * 16,
    )
    p2 = session.seal_selection(
        PlayerId.P2,
        p2_ids[:3],
        nonce_hex=P2_NONCE,
    )

    assert p1.commitment.commitment_hash != reordered.commitment.commitment_hash
    assert p1.commitment.commitment_hash != renonced.commitment.commitment_hash
    assert len(p1.commitment.commitment_hash) == 64

    one_commit = session.commit(p1.commitment)
    assert one_commit.phase is TeamPreviewPhase.COMMITTING
    with pytest.raises(TeamPreviewPhaseError, match="both commitments"):
        one_commit.reveal(p1.reveal)
    with pytest.raises(TeamPreviewPhaseError, match="already submitted"):
        one_commit.commit(p1.commitment)
    with pytest.raises(TeamPreviewPhaseError, match="revealed before materialize"):
        one_commit.materialize()

    both_committed = one_commit.commit(p2.commitment)
    assert both_committed.phase is TeamPreviewPhase.REVEALING
    assert tuple(record.player for record in both_committed.commitments) == (
        PlayerId.P1,
        PlayerId.P2,
    )
    with pytest.raises(TeamPreviewPhaseError, match="commit phase is closed"):
        both_committed.commit(reordered.commitment)
    with pytest.raises(TeamPreviewIntegrityError, match="does not match"):
        both_committed.reveal(reordered.reveal)

    one_reveal = both_committed.reveal(p1.reveal)
    assert one_reveal.phase is TeamPreviewPhase.REVEALING
    with pytest.raises(TeamPreviewPhaseError, match="already submitted"):
        one_reveal.reveal(p1.reveal)
    complete = one_reveal.reveal(p2.reveal)
    assert complete.phase is TeamPreviewPhase.COMPLETE


def test_commitment_binds_concealed_roster_set_data() -> None:
    session, _, _ = _session()
    p1_ids = _ids(session, PlayerId.P1)
    p2_ids = _ids(session, PlayerId.P2)
    original = session.seal_selection(
        PlayerId.P1,
        p1_ids[:3],
        nonce_hex=P1_NONCE,
    )

    p1 = session.roster(PlayerId.P1)
    member = p1.members[0]
    changed_move = replace(member.moves[0], move_id=MoveId("private_changed_move"))
    changed_member = replace(member, moves=(changed_move, *member.moves[1:]))
    changed_roster = TeamPreviewRoster(
        player=PlayerId.P1,
        members=(changed_member, *p1.members[1:]),
    )
    changed_session = replace(
        session,
        rosters=(changed_roster, session.roster(PlayerId.P2)),
        commitments=(),
        reveals=(),
    )
    p2 = changed_session.seal_selection(
        PlayerId.P2,
        p2_ids[:3],
        nonce_hex=P2_NONCE,
    )
    changed_session = changed_session.commit(original.commitment).commit(p2.commitment)

    with pytest.raises(TeamPreviewIntegrityError, match="does not match"):
        changed_session.reveal(original.reveal)


def test_opponent_observation_is_noninterfering_for_sets_and_selection() -> None:
    session, _, _ = _session()
    p1 = session.roster(PlayerId.P1)
    member = p1.members[0]
    private_move = replace(member.moves[0], move_id=MoveId("opponent_secret_move"))
    private_member = replace(
        member,
        moves=(private_move, *member.moves[1:]),
        stats=StatBlock(
            max_hp=member.stats.max_hp + 1,
            attack=member.stats.attack + 7,
            defense=member.stats.defense,
            special_attack=member.stats.special_attack,
            special_defense=member.stats.special_defense,
            speed=member.stats.speed,
        ),
        hp=member.hp + 1,
    )
    private_roster = TeamPreviewRoster(
        player=PlayerId.P1,
        members=(private_member, *p1.members[1:]),
    )
    private_session = replace(
        session,
        rosters=(private_roster, session.roster(PlayerId.P2)),
        commitments=(),
        reveals=(),
    )

    public_fields = {field.name for field in fields(PublicRosterMember)}
    assert public_fields == {"preview_slot", "pokemon_id", "level", "types"}
    assert session.observation_for(PlayerId.P2) == private_session.observation_for(
        PlayerId.P2
    )
    assert session.roster(PlayerId.P1).roster_hash != private_roster.roster_hash

    p1_ids = _ids(session, PlayerId.P1)
    p2_ids = _ids(session, PlayerId.P2)
    p2 = session.seal_selection(
        PlayerId.P2,
        p2_ids[:3],
        nonce_hex=P2_NONCE,
    )
    choice_a = session.seal_selection(
        PlayerId.P1,
        p1_ids[:3],
        nonce_hex=P1_NONCE,
    )
    choice_b = session.seal_selection(
        PlayerId.P1,
        (p1_ids[3], p1_ids[4], p1_ids[5]),
        nonce_hex="44" * 16,
    )
    committed_a = session.commit(choice_a.commitment).commit(p2.commitment)
    committed_b = session.commit(choice_b.commitment).commit(p2.commitment)
    # Commitment digests and selections are both excluded from policy input.
    assert committed_a.observation_for(PlayerId.P2) == committed_b.observation_for(
        PlayerId.P2
    )

    revealed_a = committed_a.reveal(choice_a.reveal)
    revealed_b = committed_b.reveal(choice_b.reveal)
    assert revealed_a.observation_for(PlayerId.P2) == revealed_b.observation_for(
        PlayerId.P2
    )
    complete_a = revealed_a.reveal(p2.reveal)
    complete_b = revealed_b.reveal(p2.reveal)
    assert complete_a.observation_for(PlayerId.P2) == complete_b.observation_for(
        PlayerId.P2
    )
    assert complete_a.observation_for(PlayerId.P1).own_selection == p1_ids[:3]


def test_materialize_preserves_order_excludes_reserves_and_initializes_engine() -> None:
    session, engine, fixture = _session()
    p1_ids = _ids(session, PlayerId.P1)
    p2_ids = _ids(session, PlayerId.P2)
    p1_selection = (p1_ids[1], p1_ids[0], p1_ids[2])
    p2_selection = (p2_ids[2], p2_ids[1], p2_ids[0])
    complete = _complete(
        session,
        p1_selection=p1_selection,
        p2_selection=p2_selection,
    )

    state = complete.materialize()
    repeated = complete.materialize()
    assert complete.contract_version == TEAM_PREVIEW_CONTRACT_VERSION
    assert state.phase is BattlePhase.TEAM_PREVIEW
    assert state.turn == 0
    assert tuple(member.instance_id for member in state.side(PlayerId.P1).team) == p1_selection
    assert tuple(member.instance_id for member in state.side(PlayerId.P2).team) == p2_selection
    assert state.side(PlayerId.P1).active_instance_id == p1_selection[0]
    assert state.side(PlayerId.P2).active_instance_id == p2_selection[0]
    assert len(state.side(PlayerId.P1).team) == 3
    assert not set(p1_ids[3:]) & {
        member.instance_id for member in state.side(PlayerId.P1).team
    }
    assert canonical_hash(state) == canonical_hash(repeated)

    initialized = engine.initialize(state, fixture.rng)
    assert initialized.state.phase is BattlePhase.AWAITING_DECISIONS
    assert initialized.next_decisions is not None
