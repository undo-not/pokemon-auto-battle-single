"""Deterministic simultaneous policy runner for sealed team preview."""

from __future__ import annotations

from copy import deepcopy
import hmac
from dataclasses import dataclass, replace
from typing import Mapping

from champions_sim.core import (
    ExplicitRNG,
    PlayerId,
    PokemonInstanceId,
    canonical_hash,
)

from .models import (
    TEAM_PREVIEW_CONTRACT_VERSION,
    TeamPreviewIntegrityError,
    TeamPreviewPhase,
    TeamPreviewPhaseError,
    TeamPreviewProof,
)
from .policies import TeamSelectionPolicy, make_team_selection_policy_identity
from .session import TeamPreviewSession


@dataclass(frozen=True, slots=True)
class TeamPreviewRun:
    session: TeamPreviewSession
    selections: tuple[
        tuple[PlayerId, tuple[PokemonInstanceId, ...]],
        tuple[PlayerId, tuple[PokemonInstanceId, ...]],
    ]
    proof: TeamPreviewProof

    def __post_init__(self) -> None:
        if type(self.session) is not TeamPreviewSession:
            raise TeamPreviewIntegrityError(
                "team-preview run requires the exact session contract"
            )
        if type(self.proof) is not TeamPreviewProof:
            raise TeamPreviewIntegrityError(
                "team-preview run requires the exact proof contract"
            )
        if self.session.phase is not TeamPreviewPhase.COMPLETE:
            raise TeamPreviewPhaseError("team-preview run requires a complete session")
        if tuple(player for player, _ in self.selections) != (
            PlayerId.P1,
            PlayerId.P2,
        ):
            raise TeamPreviewIntegrityError("team-preview run selections must be P1 then P2")
        expected_selections = tuple(
            (reveal.player, reveal.ordered_instance_ids)
            for reveal in self.session.reveals
        )
        if self.selections != expected_selections:
            raise TeamPreviewIntegrityError(
                "team-preview run selections do not match verified reveals"
            )
        _verify_proof_session_binding(self.proof, self.session)


def run_team_preview(
    session: TeamPreviewSession,
    *,
    policies: Mapping[PlayerId, TeamSelectionPolicy],
    seed: int,
) -> TeamPreviewRun:
    """Evaluate both policies against the same pre-commit observations."""

    if type(session) is not TeamPreviewSession:
        raise ValueError("team-preview requires the exact session contract")
    if session.phase is not TeamPreviewPhase.COMMITTING or session.commitments:
        raise TeamPreviewPhaseError("team-preview policy runner requires a fresh session")
    if set(policies) != {PlayerId.P1, PlayerId.P2}:
        raise ValueError("team-preview policies must cover P1 and P2")
    if policies[PlayerId.P1] is policies[PlayerId.P2]:
        raise ValueError("team-preview requires a distinct policy instance per player")

    _validate_fresh_session_integrity(session)
    # Run against a detached coordinator graph.  This prevents a policy that
    # happens to retain references to caller-owned fixture objects from
    # corrupting the state used for commitments and materialization.
    session = deepcopy(session)
    _validate_fresh_session_integrity(session)
    fresh_session_hash = session.session_hash
    root = ExplicitRNG.seeded(seed)
    identities = {
        player: make_team_selection_policy_identity(policies[player])
        for player in (PlayerId.P1, PlayerId.P2)
    }
    chosen: dict[PlayerId, tuple[PokemonInstanceId, ...]] = {}
    sealed = {}
    # Select both sides before the coordinator sees either commitment.
    for player in (PlayerId.P1, PlayerId.P2):
        _assert_fresh_session_unchanged(session, fresh_session_hash)
        policy_rng = root.branch(f"team-preview-policy:{player.value}")
        selection, _ = policies[player].select(
            session.observation_for(player),
            policy_rng,
        )
        post_selection_identity = make_team_selection_policy_identity(
            policies[player]
        )
        if not hmac.compare_digest(
            identities[player].implementation_hash,
            post_selection_identity.implementation_hash,
        ):
            raise TeamPreviewIntegrityError(
                f"team-preview policy {player.value} mutated during selection"
            )
        _assert_fresh_session_unchanged(session, fresh_session_hash)
        chosen[player] = selection
        nonce_rng = root.branch(f"team-preview-nonce:{player.value}")
        high, nonce_rng = nonce_rng.next_u64()
        low, _ = nonce_rng.next_u64()
        sealed[player] = session.seal_selection(
            player,
            selection,
            nonce_hex=f"{high:016x}{low:016x}",
        )

    committed = session
    for player in (PlayerId.P1, PlayerId.P2):
        committed = committed.commit(sealed[player].commitment)
    completed = committed
    for player in (PlayerId.P1, PlayerId.P2):
        completed = completed.reveal(sealed[player].reveal)
    proof = TeamPreviewProof.create(
        catalog_id=completed.catalog_id,
        catalog_hash=completed.catalog_hash,
        ruleset_id=completed.ruleset_id,
        ruleset_hash=completed.ruleset_hash,
        session_hash=completed.session_hash,
        materialized_state_hash=canonical_hash(completed.materialize()),
        seed=root.seed,
        roster_hash=_session_roster_hash(completed),
        p1_policy=identities[PlayerId.P1],
        p2_policy=identities[PlayerId.P2],
    )
    return TeamPreviewRun(
        session=completed,
        selections=(
            (PlayerId.P1, chosen[PlayerId.P1]),
            (PlayerId.P2, chosen[PlayerId.P2]),
        ),
        proof=proof,
    )


def verify_team_preview_proof(
    run: TeamPreviewRun,
    *,
    policies: Mapping[PlayerId, TeamSelectionPolicy],
    seed: int,
) -> None:
    """Recompute runtime bindings and reject a proof from other policies/config."""

    if type(run) is not TeamPreviewRun:
        raise ValueError("team-preview verification requires the exact run contract")
    run.session.__post_init__()
    for roster in run.session.rosters:
        roster.__post_init__()
    run.proof.p1_policy.__post_init__()
    run.proof.p2_policy.__post_init__()
    run.proof.__post_init__()
    run.__post_init__()
    if set(policies) != {PlayerId.P1, PlayerId.P2}:
        raise ValueError("team-preview policies must cover P1 and P2")
    if policies[PlayerId.P1] is policies[PlayerId.P2]:
        raise ValueError("team-preview requires a distinct policy instance per player")
    _verify_proof_session_binding(run.proof, run.session)
    expected_seed = ExplicitRNG.seeded(seed).seed
    expected_p1 = make_team_selection_policy_identity(policies[PlayerId.P1])
    expected_p2 = make_team_selection_policy_identity(policies[PlayerId.P2])
    mismatches = (
        ("seed", str(run.proof.seed), str(expected_seed)),
        (
            "p1_policy",
            run.proof.p1_policy.implementation_hash,
            expected_p1.implementation_hash,
        ),
        (
            "p2_policy",
            run.proof.p2_policy.implementation_hash,
            expected_p2.implementation_hash,
        ),
    )
    for name, actual, expected in mismatches:
        if not hmac.compare_digest(actual, expected):
            raise TeamPreviewIntegrityError(
                f"team-preview proof {name} does not match runtime input"
            )
    fresh_session = replace(run.session, commitments=(), reveals=())
    reproduced = run_team_preview(fresh_session, policies=policies, seed=seed)
    if reproduced != run:
        raise TeamPreviewIntegrityError(
            "team-preview selections do not match bound policies and seed"
        )


def _session_roster_hash(session: TeamPreviewSession) -> str:
    return canonical_hash(
        {
            "contract_version": TEAM_PREVIEW_CONTRACT_VERSION,
            "p1_roster_hash": session.roster(PlayerId.P1).roster_hash,
            "p2_roster_hash": session.roster(PlayerId.P2).roster_hash,
        }
    )


def _validate_fresh_session_integrity(session: TeamPreviewSession) -> None:
    session.__post_init__()
    for roster in session.rosters:
        roster.__post_init__()


def _assert_fresh_session_unchanged(
    session: TeamPreviewSession,
    expected_hash: str,
) -> None:
    try:
        _validate_fresh_session_integrity(session)
        actual_hash = session.session_hash
    except (TypeError, ValueError) as error:
        raise TeamPreviewIntegrityError(
            "team-preview session was corrupted during policy execution"
        ) from error
    if not hmac.compare_digest(actual_hash, expected_hash):
        raise TeamPreviewIntegrityError(
            "team-preview session changed during policy execution"
        )


def _verify_proof_session_binding(
    proof: TeamPreviewProof,
    session: TeamPreviewSession,
) -> None:
    if session.phase is not TeamPreviewPhase.COMPLETE:
        raise TeamPreviewPhaseError("team-preview proof requires a complete session")
    expected = (
        ("catalog_id", proof.catalog_id, session.catalog_id),
        ("catalog_hash", proof.catalog_hash, session.catalog_hash),
        ("ruleset_id", proof.ruleset_id, session.ruleset_id),
        ("ruleset_hash", proof.ruleset_hash, session.ruleset_hash),
        ("session_hash", proof.session_hash, session.session_hash),
        (
            "materialized_state_hash",
            proof.materialized_state_hash,
            canonical_hash(session.materialize()),
        ),
        ("roster_hash", proof.roster_hash, _session_roster_hash(session)),
    )
    for name, actual, wanted in expected:
        if not hmac.compare_digest(actual, wanted):
            raise TeamPreviewIntegrityError(
                f"team-preview proof {name} does not match completed session"
            )
