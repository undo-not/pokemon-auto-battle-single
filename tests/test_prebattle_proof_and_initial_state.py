from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping

import pytest

from champions_sim import load_battle_fixture, load_catalog, load_ruleset
from champions_sim.core import (
    ExplicitRNG,
    ItemId,
    PlayerId,
    PokemonInstanceId,
    StatStages,
)
from champions_sim.prebattle import (
    FirstThreeTeamSelectionPolicy,
    TeamPreviewError,
    TeamPreviewIntegrityError,
    TeamPreviewProof,
    TeamPreviewRoster,
    TeamPreviewSession,
    TypeCoverageTeamSelectionPolicy,
    make_team_selection_policy_identity,
    run_team_preview,
    verify_team_preview_proof,
)


ROOT = Path(__file__).resolve().parents[1]
SEED = 20260714


class AlternativeFirstThreePolicy:
    """Same choice/config as the baseline, but intentionally different source."""

    def select(self, observation, rng: ExplicitRNG):
        return tuple(member.instance_id for member in observation.own_roster[:3]), rng

    def identity_configuration(self) -> Mapping[str, object]:
        return {}


class InheritedFirstThreePolicy(FirstThreeTeamSelectionPolicy):
    """Exercise identity binding for an inherited effective method."""


class ClassConstantSelectionPolicy:
    PICK_COUNT = 3

    def select(self, observation, rng: ExplicitRNG):
        return (
            tuple(
                member.instance_id
                for member in observation.own_roster[: self.PICK_COUNT]
            ),
            rng,
        )

    def identity_configuration(self) -> Mapping[str, object]:
        return {}


class ScalarSubclass(int):
    """A behavioral scalar subtype that must not collapse to a base int."""


class DescriptorBindingSelectionPolicy:
    def helper(*args):
        return 0 if args else 1

    def select(self, observation, rng: ExplicitRNG):
        offset = self.helper()
        members = observation.own_roster
        ordered = members[offset:] + members[:offset]
        return tuple(member.instance_id for member in ordered[:3]), rng

    def identity_configuration(self) -> Mapping[str, object]:
        return {}


class DynamicClassMetadataSelectionPolicy:
    """doc-a"""

    def select(self, observation, rng: ExplicitRNG):
        offset = 0 if getattr(type(self), "__doc__") == "doc-a" else 1
        members = observation.own_roster
        ordered = members[offset:] + members[:offset]
        return tuple(member.instance_id for member in ordered[:3]), rng

    def identity_configuration(self) -> Mapping[str, object]:
        return {}


@dataclass(frozen=True, slots=True)
class DynamicDataclassMetadataSelectionPolicy:
    def select(self, observation, rng: ExplicitRNG):
        params = getattr(type(self), "__dataclass_params__")
        offset = 0 if params.frozen else 1
        members = observation.own_roster
        ordered = members[offset:] + members[:offset]
        return tuple(member.instance_id for member in ordered[:3]), rng

    def identity_configuration(self) -> Mapping[str, object]:
        return {}


class MappingConstantSelectionPolicy:
    OFFSETS = {"first": 0, "second": 1}

    def select(self, observation, rng: ExplicitRNG):
        offset = next(iter(self.OFFSETS.values()))
        members = observation.own_roster
        ordered = members[offset:] + members[:offset]
        return tuple(member.instance_id for member in ordered[:3]), rng

    def identity_configuration(self) -> Mapping[str, object]:
        return {}


class ClassAliasSelectionPolicy:
    LEFT = [1]
    RIGHT = LEFT

    def select(self, observation, rng: ExplicitRNG):
        offset = 0 if type(self).LEFT is type(self).RIGHT else 1
        members = observation.own_roster
        ordered = members[offset:] + members[:offset]
        return tuple(member.instance_id for member in ordered[:3]), rng

    def identity_configuration(self) -> Mapping[str, object]:
        return {}


class EqualityDrivenSelectionPolicy:
    def __eq__(self, other):
        return True

    def select(self, observation, rng: ExplicitRNG):
        count = 3 if self == object() else 2
        return tuple(member.instance_id for member in observation.own_roster[:count]), rng

    def identity_configuration(self) -> Mapping[str, object]:
        return {}


class DunderDrivenSelectionPolicy:
    __choice__ = 3

    def select(self, observation, rng: ExplicitRNG):
        """identity-bound selection documentation"""
        return (
            tuple(
                member.instance_id
                for member in observation.own_roster[: self.__choice__]
            ),
            rng,
        )

    def identity_configuration(self) -> Mapping[str, object]:
        return {}


@dataclass(frozen=True, slots=True)
class HiddenStateSelectionPolicy:
    offset: int

    def select(self, observation, rng: ExplicitRNG):
        members = observation.own_roster
        ordered = members[self.offset :] + members[: self.offset]
        return tuple(member.instance_id for member in ordered[:3]), rng

    def identity_configuration(self) -> Mapping[str, object]:
        # The state binding must not trust this deliberately incomplete config.
        return {}


@dataclass(slots=True)
class MutatingSelectionPolicy:
    calls: int = 0

    def select(self, observation, rng: ExplicitRNG):
        self.calls += 1
        return tuple(member.instance_id for member in observation.own_roster[:3]), rng

    def identity_configuration(self) -> Mapping[str, object]:
        return {}


@dataclass(frozen=True, slots=True)
class MappingOrderSelectionPolicy:
    offsets: Mapping[str, int]

    def select(self, observation, rng: ExplicitRNG):
        offset = next(iter(self.offsets.values()))
        members = observation.own_roster
        ordered = members[offset:] + members[:offset]
        return tuple(member.instance_id for member in ordered[:3]), rng

    def identity_configuration(self) -> Mapping[str, object]:
        return {}


@dataclass(frozen=True, slots=True)
class AliasSensitiveSelectionPolicy:
    left: list[int]
    right: list[int]

    def select(self, observation, rng: ExplicitRNG):
        offset = 0 if self.left is self.right else 1
        members = observation.own_roster
        ordered = members[offset:] + members[:offset]
        return tuple(member.instance_id for member in ordered[:3]), rng

    def identity_configuration(self) -> Mapping[str, object]:
        return {}


@dataclass(frozen=True, slots=True)
class ObservationMutatingSelectionPolicy:
    def select(self, observation, rng: ExplicitRNG):
        stats = observation.own_roster[0].stats
        object.__setattr__(stats, "attack", stats.attack + 777)
        return tuple(member.instance_id for member in observation.own_roster[:3]), rng

    def identity_configuration(self) -> Mapping[str, object]:
        return {}


def _inputs():
    catalog = load_catalog(ROOT / "data/fixtures/sim01_catalog.json")
    ruleset = load_ruleset(ROOT / "data/fixtures/sim01_ruleset.json")
    fixture = load_battle_fixture(
        ROOT / "data/fixtures/sim01_battle.json",
        catalog=catalog,
        ruleset=ruleset,
    )
    rosters = {}
    for player in (PlayerId.P1, PlayerId.P2):
        originals = fixture.initial_state.side(player).team
        reserves = tuple(
            replace(
                member,
                instance_id=PokemonInstanceId(f"{member.instance_id}-proof-reserve"),
                item_id=None,
            )
            for member in originals
        )
        rosters[player] = TeamPreviewRoster(
            player=player,
            members=(*originals, *reserves),
        )
    session = TeamPreviewSession.create(
        session_id="prebattle-proof-session-v1",
        battle_id="prebattle-proof-battle-v1",
        catalog=catalog,
        ruleset=ruleset,
        p1_roster=rosters[PlayerId.P1],
        p2_roster=rosters[PlayerId.P2],
    )
    policies = {
        PlayerId.P1: TypeCoverageTeamSelectionPolicy(catalog),
        PlayerId.P2: FirstThreeTeamSelectionPolicy(),
    }
    return catalog, session, policies


def _with_changed_first_member(session, changed_member) -> tuple:
    members = session.roster(PlayerId.P1).members
    return (changed_member, *members[1:])


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (lambda member: replace(member, hp=1), "full HP"),
        (lambda member: replace(member, hp=0), "must not be fainted"),
        (
            lambda member: replace(
                member,
                moves=(
                    replace(member.moves[0], pp=member.moves[0].max_pp - 1),
                    *member.moves[1:],
                ),
            ),
            "full move PP",
        ),
        (lambda member: replace(member, status_id="burn"), "status condition"),
        (
            lambda member: replace(member, stat_stages=StatStages(attack=1)),
            "zero stat stages",
        ),
        (
            lambda member: replace(member, volatile_statuses=("flinch",)),
            "volatile statuses",
        ),
        (
            lambda member: replace(
                member,
                item_id=None,
                consumed_item_id=ItemId("consumed-test-item"),
            ),
            "consumed item",
        ),
        (
            lambda member: replace(member, revealed_to_opponent=True),
            "must not be revealed",
        ),
        (
            lambda member: replace(member, item_revealed_to_opponent=True),
            "item must not be revealed",
        ),
        (
            lambda member: replace(member, ability_revealed_to_opponent=True),
            "ability must not be revealed",
        ),
        (
            lambda member: replace(
                member,
                moves=(
                    replace(member.moves[0], revealed_to_opponent=True),
                    *member.moves[1:],
                ),
            ),
            "moves must not be revealed",
        ),
        (
            lambda member: replace(member, mega_evolved=True),
            "must not already be Mega Evolved",
        ),
    ),
)
def test_team_preview_roster_rejects_battle_progress_state(mutation, message) -> None:
    _, session, _ = _inputs()
    member = session.roster(PlayerId.P1).members[0]

    with pytest.raises(TeamPreviewError, match=message):
        TeamPreviewRoster(
            player=PlayerId.P1,
            members=_with_changed_first_member(session, mutation(member)),
        )


def test_team_preview_proof_is_deterministic_and_bound_to_all_material() -> None:
    _, session, policies = _inputs()
    first = run_team_preview(session, policies=policies, seed=SEED)
    second = run_team_preview(session, policies=policies, seed=SEED)

    assert first.proof == second.proof
    assert first.proof.session_hash == first.session.session_hash
    assert first.proof.materialized_state_hash
    assert first.proof.roster_hash
    assert first.proof.p1_policy.policy_component.endswith(
        ".TypeCoverageTeamSelectionPolicy"
    )
    assert first.proof.p2_policy.policy_component.endswith(
        ".FirstThreeTeamSelectionPolicy"
    )
    assert first.proof.p1_policy.configuration_hash
    assert first.proof.p1_policy.source_sha256
    assert first.proof.proof_hash == first.proof.expected_proof_hash()
    verify_team_preview_proof(first, policies=policies, seed=SEED)


def test_team_preview_proof_detects_field_policy_config_and_seed_tampering() -> None:
    catalog, session, policies = _inputs()
    run = run_team_preview(session, policies=policies, seed=SEED)

    with pytest.raises(TeamPreviewIntegrityError, match="proof hash"):
        replace(run.proof, session_hash="0" * 64)

    forged_seed = TeamPreviewProof.create(
        catalog_id=run.proof.catalog_id,
        catalog_hash=run.proof.catalog_hash,
        ruleset_id=run.proof.ruleset_id,
        ruleset_hash=run.proof.ruleset_hash,
        session_hash=run.proof.session_hash,
        materialized_state_hash=run.proof.materialized_state_hash,
        seed=SEED + 1,
        roster_hash=run.proof.roster_hash,
        p1_policy=run.proof.p1_policy,
        p2_policy=run.proof.p2_policy,
    )
    forged_run = replace(run, proof=forged_seed)
    with pytest.raises(TeamPreviewIntegrityError, match="seed"):
        verify_team_preview_proof(forged_run, policies=policies, seed=SEED)

    changed_catalog = replace(catalog, snapshot_hash="f" * 64)
    changed_policies = {
        PlayerId.P1: TypeCoverageTeamSelectionPolicy(changed_catalog),
        PlayerId.P2: policies[PlayerId.P2],
    }
    with pytest.raises(TeamPreviewIntegrityError, match="p1_policy"):
        verify_team_preview_proof(run, policies=changed_policies, seed=SEED)

    changed_source_policies = {
        PlayerId.P1: policies[PlayerId.P1],
        PlayerId.P2: AlternativeFirstThreePolicy(),
    }
    with pytest.raises(TeamPreviewIntegrityError, match="p2_policy"):
        verify_team_preview_proof(run, policies=changed_source_policies, seed=SEED)


def test_team_preview_rejects_same_policy_instance_for_both_players() -> None:
    _, session, policies = _inputs()
    shared = FirstThreeTeamSelectionPolicy()
    shared_policies = {PlayerId.P1: shared, PlayerId.P2: shared}

    with pytest.raises(ValueError, match="distinct policy instance"):
        run_team_preview(session, policies=shared_policies, seed=SEED)

    run = run_team_preview(session, policies=policies, seed=SEED)
    with pytest.raises(ValueError, match="distinct policy instance"):
        verify_team_preview_proof(run, policies=shared_policies, seed=SEED)


def test_team_preview_rejects_policy_runtime_monkeypatch_after_proof(
    monkeypatch,
) -> None:
    _, session, policies = _inputs()
    run = run_team_preview(session, policies=policies, seed=SEED)
    original_select = FirstThreeTeamSelectionPolicy.select

    def patched_select(self, observation, rng):
        return original_select(self, observation, rng)

    monkeypatch.setattr(FirstThreeTeamSelectionPolicy, "select", patched_select)
    with pytest.raises(TeamPreviewIntegrityError, match="p2_policy"):
        verify_team_preview_proof(run, policies=policies, seed=SEED)


def test_team_preview_identity_binds_inherited_methods_and_class_constants(
    monkeypatch,
) -> None:
    _, session, policies = _inputs()
    inherited = InheritedFirstThreePolicy()
    inherited_policies = {**policies, PlayerId.P2: inherited}
    run = run_team_preview(session, policies=inherited_policies, seed=SEED)
    original_select = FirstThreeTeamSelectionPolicy.select

    def patched_select(self, observation, rng):
        return original_select(self, observation, rng)

    monkeypatch.setattr(FirstThreeTeamSelectionPolicy, "select", patched_select)
    with pytest.raises(TeamPreviewIntegrityError, match="p2_policy"):
        verify_team_preview_proof(run, policies=inherited_policies, seed=SEED)

    constant_policy = ClassConstantSelectionPolicy()
    before = make_team_selection_policy_identity(constant_policy)
    monkeypatch.setattr(ClassConstantSelectionPolicy, "PICK_COUNT", 2)
    after = make_team_selection_policy_identity(constant_policy)
    assert after.runtime_sha256 != before.runtime_sha256

    mapping_constant_policy = MappingConstantSelectionPolicy()
    before_mapping = make_team_selection_policy_identity(mapping_constant_policy)
    monkeypatch.setattr(
        MappingConstantSelectionPolicy,
        "OFFSETS",
        {"second": 1, "first": 0},
    )
    after_mapping = make_team_selection_policy_identity(mapping_constant_policy)
    assert after_mapping.runtime_sha256 != before_mapping.runtime_sha256

    shared_constant = [1]
    monkeypatch.setattr(ClassAliasSelectionPolicy, "LEFT", shared_constant)
    monkeypatch.setattr(ClassAliasSelectionPolicy, "RIGHT", shared_constant)
    alias_policy = ClassAliasSelectionPolicy()
    before_alias = make_team_selection_policy_identity(alias_policy)
    monkeypatch.setattr(ClassAliasSelectionPolicy, "RIGHT", [1])
    after_alias = make_team_selection_policy_identity(alias_policy)
    assert after_alias.runtime_sha256 != before_alias.runtime_sha256

    shared_scalar = int("1000")
    distinct_scalar = int("1000")
    assert shared_scalar is not distinct_scalar
    monkeypatch.setattr(ClassAliasSelectionPolicy, "LEFT", shared_scalar)
    monkeypatch.setattr(ClassAliasSelectionPolicy, "RIGHT", shared_scalar)
    before_scalar_alias = make_team_selection_policy_identity(alias_policy)
    monkeypatch.setattr(ClassAliasSelectionPolicy, "RIGHT", distinct_scalar)
    after_scalar_alias = make_team_selection_policy_identity(alias_policy)
    assert after_scalar_alias.runtime_sha256 != before_scalar_alias.runtime_sha256

    monkeypatch.setattr(
        ClassConstantSelectionPolicy,
        "PICK_COUNT",
        ScalarSubclass(3),
    )
    with pytest.raises(TeamPreviewError, match="implementation/state is unavailable"):
        make_team_selection_policy_identity(constant_policy)

    equality_policy = EqualityDrivenSelectionPolicy()
    before_equality = make_team_selection_policy_identity(equality_policy)
    monkeypatch.setattr(
        EqualityDrivenSelectionPolicy,
        "__eq__",
        lambda self, other: False,
    )
    after_equality = make_team_selection_policy_identity(equality_policy)
    assert after_equality.runtime_sha256 != before_equality.runtime_sha256

    dunder_policy = DunderDrivenSelectionPolicy()
    before_dunder = make_team_selection_policy_identity(dunder_policy)
    monkeypatch.setattr(DunderDrivenSelectionPolicy, "__choice__", 2)
    after_dunder = make_team_selection_policy_identity(dunder_policy)
    assert after_dunder.runtime_sha256 != before_dunder.runtime_sha256
    monkeypatch.setattr(
        DunderDrivenSelectionPolicy.select,
        "__doc__",
        "changed runtime documentation",
    )
    after_doc = make_team_selection_policy_identity(dunder_policy)
    assert after_doc.runtime_sha256 != after_dunder.runtime_sha256


def test_team_preview_identity_binds_method_descriptor_kind(monkeypatch) -> None:
    policy = DescriptorBindingSelectionPolicy()
    before = make_team_selection_policy_identity(policy)
    original_helper = DescriptorBindingSelectionPolicy.__dict__["helper"]

    monkeypatch.setattr(
        DescriptorBindingSelectionPolicy,
        "helper",
        staticmethod(original_helper),
    )
    after = make_team_selection_policy_identity(policy)

    assert before.runtime_sha256 != after.runtime_sha256
    assert before.implementation_hash != after.implementation_hash


def test_team_preview_identity_binds_dynamic_class_metadata(monkeypatch) -> None:
    policy = DynamicClassMetadataSelectionPolicy()
    before = make_team_selection_policy_identity(policy)

    monkeypatch.setattr(DynamicClassMetadataSelectionPolicy, "__doc__", "doc-b")
    after = make_team_selection_policy_identity(policy)

    assert before.runtime_sha256 != after.runtime_sha256
    assert before.implementation_hash != after.implementation_hash


def test_team_preview_fails_closed_for_dynamic_unsupported_metadata() -> None:
    with pytest.raises(TeamPreviewError, match="implementation/state is unavailable"):
        make_team_selection_policy_identity(
            DynamicDataclassMetadataSelectionPolicy()
        )


def test_team_preview_identity_binds_undeclared_instance_state() -> None:
    first = make_team_selection_policy_identity(HiddenStateSelectionPolicy(0))
    second = make_team_selection_policy_identity(HiddenStateSelectionPolicy(1))

    assert first.configuration_json == second.configuration_json == "{}"
    assert first.source_sha256 == second.source_sha256
    assert first.runtime_sha256 == second.runtime_sha256
    assert first.initial_policy_state_hash != second.initial_policy_state_hash
    assert first.implementation_hash != second.implementation_hash


def test_team_preview_identity_binds_mapping_order_and_alias_topology() -> None:
    forward = make_team_selection_policy_identity(
        MappingOrderSelectionPolicy({"first": 0, "second": 1})
    )
    reverse = make_team_selection_policy_identity(
        MappingOrderSelectionPolicy({"second": 1, "first": 0})
    )
    shared: list[int] = [1]
    aliased = make_team_selection_policy_identity(
        AliasSensitiveSelectionPolicy(shared, shared)
    )
    copied = make_team_selection_policy_identity(
        AliasSensitiveSelectionPolicy([1], [1])
    )
    shared_scalar = int("1000")
    distinct_scalar = int("1000")
    assert shared_scalar is not distinct_scalar
    scalar_aliased = make_team_selection_policy_identity(
        AliasSensitiveSelectionPolicy(shared_scalar, shared_scalar)  # type: ignore[arg-type]
    )
    scalar_copied = make_team_selection_policy_identity(
        AliasSensitiveSelectionPolicy(shared_scalar, distinct_scalar)  # type: ignore[arg-type]
    )

    assert forward.initial_policy_state_hash != reverse.initial_policy_state_hash
    assert forward.implementation_hash != reverse.implementation_hash
    assert aliased.initial_policy_state_hash != copied.initial_policy_state_hash
    assert aliased.implementation_hash != copied.implementation_hash
    assert scalar_aliased.initial_policy_state_hash != scalar_copied.initial_policy_state_hash
    assert scalar_aliased.implementation_hash != scalar_copied.implementation_hash


def test_team_preview_rejects_policy_state_mutation_during_selection() -> None:
    _, session, policies = _inputs()
    mutable = MutatingSelectionPolicy()

    with pytest.raises(TeamPreviewIntegrityError, match="mutated during selection"):
        run_team_preview(
            session,
            policies={**policies, PlayerId.P2: mutable},
            seed=SEED,
        )


def test_team_preview_state_binding_bypasses_subject_getattribute(
    monkeypatch,
) -> None:
    _, session, policies = _inputs()
    mutable = MutatingSelectionPolicy()

    def hiding_getattribute(self, name):
        if name == "calls":
            return 0
        return object.__getattribute__(self, name)

    monkeypatch.setattr(
        MutatingSelectionPolicy,
        "__getattribute__",
        hiding_getattribute,
    )
    with pytest.raises(TeamPreviewIntegrityError, match="mutated during selection"):
        run_team_preview(
            session,
            policies={**policies, PlayerId.P2: mutable},
            seed=SEED,
        )

    calls_descriptor = MutatingSelectionPolicy.__dict__["calls"]
    assert calls_descriptor.__get__(mutable, MutatingSelectionPolicy) == 1


def test_team_preview_policy_receives_detached_private_roster_graph() -> None:
    _, session, policies = _inputs()
    attack_before = session.roster(PlayerId.P1).members[0].stats.attack

    run = run_team_preview(
        session,
        policies={
            **policies,
            PlayerId.P1: ObservationMutatingSelectionPolicy(),
        },
        seed=SEED,
    )

    assert session.roster(PlayerId.P1).members[0].stats.attack == attack_before
    assert run.session.roster(PlayerId.P1).members[0].stats.attack == attack_before
    assert run.session.materialize().side(PlayerId.P1).active.stats.attack == attack_before
