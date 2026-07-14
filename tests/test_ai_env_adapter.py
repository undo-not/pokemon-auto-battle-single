from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from champions_sim import BattleEngine, load_battle_fixture, load_catalog, load_ruleset
from champions_sim.core import PlayerId, SIMULATOR_VERSION, canonical_hash
from champions_sim.engine import IllegalAction
from champions_sim.env import (
    AI_ENV_ADAPTER_SCHEMA_VERSION,
    AI_ENV_ADAPTER_VERSION,
    DeterministicBattleEnv,
    EnvironmentBundleIdentity,
    EnvironmentNotActionable,
    EnvironmentScope,
    EnvironmentStateError,
    EvidenceStatus,
    SealedEnvironmentFixture,
    SealedEnvironmentInput,
)
from champions_sim.grounding import MaskStatus


ROOT = Path(__file__).resolve().parents[1]


def _loaded() -> tuple[BattleEngine, object, EnvironmentBundleIdentity, SealedEnvironmentInput]:
    catalog = load_catalog(ROOT / "data/fixtures/sim01_catalog.json")
    ruleset = load_ruleset(ROOT / "data/fixtures/sim01_ruleset.json")
    fixture = load_battle_fixture(
        ROOT / "data/fixtures/sim01_battle.json",
        catalog=catalog,
        ruleset=ruleset,
    )
    engine = BattleEngine(catalog, ruleset)
    bundle = EnvironmentBundleIdentity(
        adapter_version=AI_ENV_ADAPTER_VERSION,
        simulator_version=SIMULATOR_VERSION,
        engine_semantics_version=ruleset.engine_semantics_version,
        scope=EnvironmentScope.PURE_SIMULATOR_LOCAL,
        catalog_id=catalog.catalog_id,
        catalog_hash=catalog.snapshot_hash,
        ruleset_id=str(ruleset.ruleset_id),
        ruleset_hash=ruleset.snapshot_hash,
        regulation_id=None,
        regulation_hash=None,
        target_pool_id=None,
        target_pool_hash=None,
        capability_set_id=None,
        capability_set_hash=None,
        capability_status=EvidenceStatus.MISSING,
        grounding_assertion_set_id=None,
        grounding_assertion_set_hash=None,
        grounding_status=EvidenceStatus.MISSING,
        source_manifest_ids=fixture.source_manifest_ids,
        provisional_decision_ids=fixture.provisional_decision_ids,
    )
    sealed = SealedEnvironmentInput(
        schema_version=AI_ENV_ADAPTER_SCHEMA_VERSION,
        bundle=bundle,
        fixture=SealedEnvironmentFixture.seal(
            "fixture:sim01-battle-v1",
            fixture.initial_state,
        ),
    )
    return engine, fixture, bundle, sealed


def _first_legal(snapshot: object) -> str:
    mask = snapshot.legal_action_mask  # type: ignore[attr-defined]
    return next(
        action
        for action, legal in zip(mask.action_ids, mask.legal)
        if legal and not action.endswith(":forfeit")
    )


def _joint_action_ids(sealed: SealedEnvironmentInput, seed: int) -> dict[PlayerId, str]:
    engine, _, _, _ = _loaded()
    p1 = DeterministicBattleEnv(engine, PlayerId.P1).reset(seed=seed, sealed=sealed)
    engine2, _, _, _ = _loaded()
    p2 = DeterministicBattleEnv(engine2, PlayerId.P2).reset(seed=seed, sealed=sealed)
    return {
        PlayerId.P1: _first_legal(p1.snapshot),
        PlayerId.P2: _first_legal(p2.snapshot),
    }


def test_reset_is_version_bound_deterministic_and_partial_observation_safe() -> None:
    engine, _, bundle, sealed = _loaded()
    first_env = DeterministicBattleEnv(engine, PlayerId.P1)
    first = first_env.reset(seed=20260713, sealed=sealed)

    engine2, _, _, _ = _loaded()
    repeated = DeterministicBattleEnv(engine2, PlayerId.P1).reset(
        seed=20260713,
        sealed=sealed,
    )

    assert first.to_json() == repeated.to_json()
    assert first.snapshot.identity.bundle_identity_hash == bundle.identity_hash
    public_payload = first.to_dict()
    assert "sealed_input_hash" not in public_payload["snapshot"]["identity"]
    assert "fixture_hash" not in public_payload["snapshot"]["identity"]
    assert "initial_state_hash" not in public_payload["info"]
    assert "initial_events_hash" not in public_payload["info"]
    assert first.snapshot.legal_action_mask.status is MaskStatus.KNOWN
    assert first.snapshot.actionable is True
    assert first.info.reward_model_id == "none"
    assert "seed" not in public_payload["snapshot"]["identity"]
    assert "rng_algorithm_id" not in public_payload["snapshot"]["identity"]
    assert "rng_seed" not in public_payload["info"]
    opponent_side = first.snapshot.observation.opponent_side
    opponent = next(
        value
        for value in opponent_side.pokemon
        if value.instance_id == opponent_side.active_instance_id
    )
    assert opponent.hp is None
    assert opponent.max_hp is None
    assert opponent.hp_fraction_millionths is None
    assert opponent.stats is None
    assert all(not event.evidence_artifact_ids for event in first.snapshot.public_history)


def test_optional_readiness_extension_preserves_v1_simulator_input_hash() -> None:
    _, _, _, sealed = _loaded()

    assert sealed.readiness is None
    assert sealed.sealed_input_hash == canonical_hash(
        {
            "schema_version": sealed.schema_version,
            "bundle": sealed.bundle,
            "fixture": sealed.fixture,
        }
    )


def test_same_seed_and_joint_choice_produce_byte_identical_step_and_replay_lineage() -> None:
    engine1, _, _, sealed = _loaded()
    env1 = DeterministicBattleEnv(engine1, PlayerId.P1)
    reset1 = env1.reset(seed=7331, sealed=sealed)
    action_ids = _joint_action_ids(sealed, 7331)
    choice1 = env1.make_joint_choice(action_ids)
    step1 = env1.step(choice1)

    engine2, _, _, _ = _loaded()
    env2 = DeterministicBattleEnv(engine2, PlayerId.P1)
    reset2 = env2.reset(seed=7331, sealed=sealed)
    choice2 = env2.make_joint_choice(action_ids)
    step2 = env2.step(choice2)

    assert reset1.to_json() == reset2.to_json()
    assert choice1.choice_hash == choice2.choice_hash
    assert step1.to_json() == step2.to_json()
    assert step1.reward is None
    assert step1.truncated is False
    assert step1.info.source_manifest_ids == sealed.bundle.source_manifest_ids
    public_info = step1.to_dict()["info"]
    assert "state_hash_before" not in public_info
    assert "state_hash_after" not in public_info
    assert "events_hash" not in public_info
    assert "choice_hash" not in public_info
    assert "rng_state_hash_after" not in public_info


def test_policy_results_do_not_oracle_opponent_private_bench_data() -> None:
    engine, _, _, sealed = _loaded()
    state = sealed.fixture.initial_state
    opponent = state.side(PlayerId.P2)
    hidden = opponent.team[1]
    changed_hidden = replace(
        hidden,
        item_id=None,
        stats=replace(hidden.stats, attack=hidden.stats.attack + 1),
        moves=tuple(reversed(hidden.moves)),
    )
    changed_state = replace(
        state,
        sides=(
            state.side(PlayerId.P1),
            replace(opponent, team=(opponent.team[0], changed_hidden, *opponent.team[2:])),
        ),
    )
    changed_sealed = replace(
        sealed,
        fixture=SealedEnvironmentFixture.seal(
            "sim01-private-bench-variant",
            changed_state,
        ),
    )
    assert changed_sealed.sealed_input_hash != sealed.sealed_input_hash

    original = DeterministicBattleEnv(engine, PlayerId.P1).reset(
        seed=20260713,
        sealed=sealed,
    )
    engine2, _, _, _ = _loaded()
    changed = DeterministicBattleEnv(engine2, PlayerId.P1).reset(
        seed=20260714,
        sealed=changed_sealed,
    )

    assert original.snapshot.observation == changed.snapshot.observation
    assert original.to_json() == changed.to_json()
    public_identity = original.to_dict()["snapshot"]["identity"]
    assert "fixture_id" not in public_identity
    assert "seed" not in public_identity
    assert "rng_algorithm_id" not in public_identity


def test_stale_cross_episode_and_illegal_choices_are_rejected() -> None:
    engine, _, _, sealed = _loaded()
    env = DeterministicBattleEnv(engine, PlayerId.P1)
    env.reset(seed=11, sealed=sealed)
    action_ids = _joint_action_ids(sealed, 11)
    choice = env.make_joint_choice(action_ids)
    env.step(choice)

    with pytest.raises(EnvironmentStateError, match="stale"):
        env.step(choice)

    engine2, _, _, _ = _loaded()
    other = DeterministicBattleEnv(engine2, PlayerId.P1)
    other.reset(seed=12, sealed=sealed)
    with pytest.raises(EnvironmentStateError, match="another episode"):
        other.step(choice)

    engine3, _, _, _ = _loaded()
    invalid_env = DeterministicBattleEnv(engine3, PlayerId.P1)
    invalid_env.reset(seed=11, sealed=sealed)
    invalid = invalid_env.make_joint_choice(
        {**action_ids, PlayerId.P1: "p1:move:not-a-real-move"}
    )
    with pytest.raises(IllegalAction, match="illegal action_id"):
        invalid_env.step(invalid)


def test_reset_replaces_episode_state_and_history() -> None:
    engine, _, _, sealed = _loaded()
    env = DeterministicBattleEnv(engine, PlayerId.P1)
    initial = env.reset(seed=99, sealed=sealed)
    choice = env.make_joint_choice(_joint_action_ids(sealed, 99))
    env.step(choice)
    reset_again = env.reset(seed=99, sealed=sealed)

    assert reset_again.to_json() == initial.to_json()
    assert reset_again.snapshot.step_index == 0


def test_champions_candidate_is_not_actionable_without_verified_evidence() -> None:
    engine, _, bundle, sealed = _loaded()
    candidate = replace(
        bundle,
        scope=EnvironmentScope.CHAMPIONS_CANDIDATE,
        regulation_id="M-B",
        regulation_hash="1" * 64,
        target_pool_id="m-b-eligible-235",
        target_pool_hash="2" * 64,
        capability_status=EvidenceStatus.UNVERIFIED,
        grounding_status=EvidenceStatus.MISSING,
    )
    blocked_input = replace(sealed, bundle=candidate)
    env = DeterministicBattleEnv(engine, PlayerId.P1)
    result = env.reset(seed=1, sealed=blocked_input)

    assert result.snapshot.actionable is False
    assert result.snapshot.legal_action_mask.status is MaskStatus.ALL_ILLEGAL
    assert result.snapshot.blockers == (
        "capability_evidence_not_verified",
        "grounding_evidence_not_verified",
    )
    choice = env.make_joint_choice(_joint_action_ids(sealed, 1))
    with pytest.raises(EnvironmentNotActionable):
        env.step(choice)


def test_sealed_bundle_and_fixture_tampering_are_rejected() -> None:
    engine, _, bundle, sealed = _loaded()
    with pytest.raises(ValueError, match="catalog_hash"):
        DeterministicBattleEnv(engine, PlayerId.P1).reset(
            seed=0,
            sealed=replace(sealed, bundle=replace(bundle, catalog_hash="0" * 64)),
        )

    with pytest.raises(ValueError, match="fixture_hash"):
        replace(sealed.fixture, fixture_hash="0" * 64)
