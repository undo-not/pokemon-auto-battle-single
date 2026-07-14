from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil

import pytest
import champions_sim.env.readiness as readiness_module

from champions_sim import BattleEngine, load_battle_fixture, load_catalog, load_ruleset
from champions_sim.compiler import (
    CatalogBridgeProfile,
    SourceToCapabilityConfig,
    compile_source_to_capability_bundle,
)
from champions_sim.capabilities.models import RecordIdentity
from champions_sim.core import PlayerId, SIMULATOR_VERSION, canonical_hash, canonical_json
from champions_sim.env import (
    AI_ENV_ADAPTER_SCHEMA_VERSION,
    AI_ENV_ADAPTER_VERSION,
    ChampionsReadinessError,
    DeterministicBattleEnv,
    EnvironmentBundleIdentity,
    EnvironmentScope,
    EvidenceStatus,
    ResolvedChampionsReadiness,
    SealedEnvironmentFixture,
    SealedEnvironmentInput,
    resolve_champions_readiness,
)
from champions_sim.grounding import MaskStatus
from champions_sim.intake import CatalogIntakeProfile


ROOT = Path(__file__).resolve().parents[1]
INTAKE_FIXTURE = ROOT / "data/fixtures/intake/synthetic_mini"


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _artifact(path: Path, logical_path: str) -> dict[str, object]:
    payload = path.read_bytes()
    return {
        "logical_path": logical_path,
        "byte_size": len(payload),
        "sha256": "sha256:" + hashlib.sha256(payload).hexdigest(),
    }


@pytest.fixture
def compilation(tmp_path: Path):
    repository = tmp_path / "repository"
    shutil.copytree(INTAKE_FIXTURE, repository)
    regulation_path = repository / "regulation.json"
    _write_json(
        regulation_path,
        {
            "schema_version": "1.0.0",
            "regulation_id": "TEST-B",
            "revision": "synthetic-v1",
            "title": "Synthetic readiness integration",
            "status": "synthetic",
            "verification_status": "synthetic_rehearsal",
            "published_at": None,
            "period": {
                "start_date": "2026-01-01",
                "end_at": "2026-01-31T23:59:00+09:00",
                "timezone": "Asia/Tokyo",
            },
            "battle_format": "singles_3v3",
            "team_size": 3,
            "level": 50,
            "item_clause": {
                "held_items_enabled": True,
                "duplicate_held_items_allowed": False,
            },
            "battle_timer": {
                "total_minutes": 20,
                "player_minutes": 7,
                "turn_seconds": 45,
                "selection_seconds": 90,
            },
            "required_mechanics": ["mega_evolution"],
            "source_manifest_ids": ["synthetic-catalog-intake"],
        },
    )
    manifest_dir = repository / "manifests"
    manifest_dir.mkdir()
    _write_json(
        manifest_dir / "synthetic-catalog-intake.json",
        {
            "schema_version": "1.0.0",
            "manifest_id": "synthetic-catalog-intake",
            "license_status": "unverified",
            "license": {
                "redistribution_allowed": False,
                "commercial_use_allowed": False,
            },
            "usage_policy": {
                "local_research_only": True,
                "redistribution": "prohibited",
            },
            "artifacts": [
                _artifact(regulation_path, "regulation.json"),
                _artifact(repository / "target_pool.json", "target_pool.json"),
            ],
            "trust": {"verification_status": "unverified"},
        },
    )
    config = SourceToCapabilityConfig(
        repository_root=repository,
        legacy_root=repository,
        regulation_path=regulation_path,
        target_pool_path=repository / "target_pool.json",
        ruleset_path=ROOT / "data/fixtures/sim01_ruleset.json",
        manifest_dir=manifest_dir,
        source_lock_path=ROOT / "data/manifests/catalog-intake-synthetic.json",
        intake_profile=CatalogIntakeProfile(
            "readiness_mini", "TEST-B", "synthetic-v1", 3, 2
        ),
        bridge_profile=CatalogBridgeProfile(
            "readiness_bridge",
            "TEST-B",
            "synthetic-v1",
            3,
            "catalog-intake-synthetic",
            "sim-core-0.1",
        ),
    )
    return compile_source_to_capability_bundle(config)


def _compiler_bound_identity(compilation) -> EnvironmentBundleIdentity:
    regulation = compilation.regulation_bundle.regulation
    target_pool = compilation.regulation_bundle.target_pool
    return EnvironmentBundleIdentity(
        adapter_version=AI_ENV_ADAPTER_VERSION,
        simulator_version=SIMULATOR_VERSION,
        engine_semantics_version=compilation.ruleset.engine_semantics_version,
        scope=EnvironmentScope.CHAMPIONS_CANDIDATE,
        catalog_id=compilation.catalog.catalog_id,
        catalog_hash=compilation.catalog.snapshot_hash,
        ruleset_id=str(compilation.ruleset.ruleset_id),
        ruleset_hash=compilation.ruleset.snapshot_hash,
        regulation_id=regulation.regulation_id,
        regulation_hash=regulation.snapshot_hash,
        target_pool_id=target_pool.target_pool_id,
        target_pool_hash=target_pool.snapshot_hash,
        capability_set_id=compilation.capability_set.capability_set_id,
        capability_set_hash=compilation.capability_set.capability_set_hash,
        capability_status=EvidenceStatus.VERIFIED,
        grounding_assertion_set_id=compilation.grounding.assertion_set_id,
        grounding_assertion_set_hash=compilation.grounding.assertion_set_hash,
        grounding_status=EvidenceStatus.VERIFIED,
        source_manifest_ids=tuple(
            sorted(
                {
                    compilation.catalog.source_manifest_id,
                    *compilation.ruleset.source_manifest_ids,
                }
            )
        ),
        provisional_decision_ids=compilation.ruleset.provisional_decision_ids,
    )


def _sealed_sim01_fixture() -> SealedEnvironmentFixture:
    catalog = load_catalog(ROOT / "data/fixtures/sim01_catalog.json")
    ruleset = load_ruleset(ROOT / "data/fixtures/sim01_ruleset.json")
    loaded = load_battle_fixture(
        ROOT / "data/fixtures/sim01_battle.json",
        catalog=catalog,
        ruleset=ruleset,
    )
    return SealedEnvironmentFixture.seal(
        "fixture:sim01-readiness-membership",
        loaded.initial_state,
    )


def _direct_readiness(
    compilation,
    bundle: EnvironmentBundleIdentity,
    fixture: SealedEnvironmentFixture,
) -> ResolvedChampionsReadiness:
    """Construct untrusted readiness-shaped data without using the resolver."""

    return ResolvedChampionsReadiness(
        schema_version="1.0.0",
        bundle_identity_hash=bundle.identity_hash,
        compiler_id="source-to-capability-bundle-v1",
        compiler_report_hash=str(compilation.report["report_hash"]),
        artifact_manifest_hash=canonical_hash(tuple(compilation.report["artifacts"])),
        capability_set_hash=compilation.capability_set.capability_set_hash,
        grounding_assertion_set_hash=compilation.grounding.assertion_set_hash,
        fixture_id=fixture.fixture_id,
        fixture_hash=fixture.fixture_hash,
        fixture_binding_hash=fixture.fixture_binding_hash,
        _compilation=compilation,
    )


def _fixture_with_first_member(
    fixture: SealedEnvironmentFixture,
    member,
) -> SealedEnvironmentFixture:
    first_side = fixture.initial_state.sides[0]
    state = replace(
        fixture.initial_state,
        sides=(
            replace(first_side, team=(member, *first_side.team[1:])),
            fixture.initial_state.sides[1],
        ),
    )
    return SealedEnvironmentFixture.seal(fixture.fixture_id, state)


def test_self_declared_verified_identity_remains_non_actionable_without_seal() -> None:
    catalog = load_catalog(ROOT / "data/fixtures/sim01_catalog.json")
    ruleset = load_ruleset(ROOT / "data/fixtures/sim01_ruleset.json")
    fixture = load_battle_fixture(
        ROOT / "data/fixtures/sim01_battle.json", catalog=catalog, ruleset=ruleset
    )
    bundle = EnvironmentBundleIdentity(
        adapter_version=AI_ENV_ADAPTER_VERSION,
        simulator_version=SIMULATOR_VERSION,
        engine_semantics_version=ruleset.engine_semantics_version,
        scope=EnvironmentScope.CHAMPIONS_CANDIDATE,
        catalog_id=catalog.catalog_id,
        catalog_hash=catalog.snapshot_hash,
        ruleset_id=str(ruleset.ruleset_id),
        ruleset_hash=ruleset.snapshot_hash,
        regulation_id="M-B",
        regulation_hash="1" * 64,
        target_pool_id="m-b-pool",
        target_pool_hash="2" * 64,
        capability_set_id="forged-capabilities",
        capability_set_hash="3" * 64,
        capability_status=EvidenceStatus.VERIFIED,
        grounding_assertion_set_id="forged-grounding",
        grounding_assertion_set_hash="4" * 64,
        grounding_status=EvidenceStatus.VERIFIED,
        source_manifest_ids=fixture.source_manifest_ids,
        provisional_decision_ids=fixture.provisional_decision_ids,
    )
    sealed = SealedEnvironmentInput(
        AI_ENV_ADAPTER_SCHEMA_VERSION,
        bundle,
        SealedEnvironmentFixture.seal("fixture:readiness-forgery", fixture.initial_state),
    )

    result = DeterministicBattleEnv(BattleEngine(catalog, ruleset), PlayerId.P1).reset(
        seed=1, sealed=sealed
    )

    assert result.snapshot.actionable is False
    assert result.snapshot.legal_action_mask.status is MaskStatus.ALL_ILLEGAL
    assert result.snapshot.blockers == ("compiler_readiness_not_resolved",)


def test_resolver_rejects_fake_bundle_binding_before_no_go(compilation) -> None:
    bundle = _compiler_bound_identity(compilation)
    for forged, expected_field in (
        (replace(bundle, capability_set_hash="f" * 64), "capability_set_hash"),
        (
            replace(bundle, grounding_assertion_set_id="grounding:aliased"),
            "grounding_assertion_set_id",
        ),
    ):
        with pytest.raises(ChampionsReadinessError, match=expected_field):
            resolve_champions_readiness(
                forged,
                compilation,
                _sealed_sim01_fixture(),
            )


def test_resolver_recomputes_candidate_ready_instead_of_trusting_report(
    compilation,
) -> None:
    tampered_report = dict(compilation.report)
    tampered_report["candidate_ready"] = True
    tampered_report["status"] = "candidate"
    unsigned = {
        key: value for key, value in tampered_report.items() if key != "report_hash"
    }
    tampered_report["report_hash"] = canonical_hash(unsigned)
    documents = dict(compilation.documents)
    documents["compiler-report.json"] = canonical_json(tampered_report)
    tampered = replace(
        compilation, report=tampered_report, documents=documents
    )

    with pytest.raises(ChampionsReadinessError, match="candidate_ready"):
        resolve_champions_readiness(
            _compiler_bound_identity(compilation),
            tampered,
            _sealed_sim01_fixture(),
        )


def test_resolver_rejects_forged_report_hash_and_missing_artifact(compilation) -> None:
    forged_report = dict(compilation.report)
    forged_report["report_hash"] = "0" * 64
    forged_documents = dict(compilation.documents)
    forged_documents["compiler-report.json"] = canonical_json(forged_report)
    with pytest.raises(ChampionsReadinessError, match="report hash mismatch"):
        resolve_champions_readiness(
            _compiler_bound_identity(compilation),
            replace(
                compilation, report=forged_report, documents=forged_documents
            ),
            _sealed_sim01_fixture(),
        )

    incomplete_documents = dict(compilation.documents)
    del incomplete_documents["target-capability-set.json"]
    with pytest.raises(ChampionsReadinessError, match="substance is incomplete"):
        resolve_champions_readiness(
            _compiler_bound_identity(compilation),
            replace(compilation, documents=incomplete_documents),
            _sealed_sim01_fixture(),
        )


def test_resolver_rejects_sim01_disguise_and_real_no_go(compilation) -> None:
    compiler_bundle = _compiler_bound_identity(compilation)
    sim01_disguise = EnvironmentBundleIdentity(
        adapter_version=compiler_bundle.adapter_version,
        simulator_version=compiler_bundle.simulator_version,
        engine_semantics_version=compiler_bundle.engine_semantics_version,
        scope=EnvironmentScope.PURE_SIMULATOR_LOCAL,
        catalog_id=compiler_bundle.catalog_id,
        catalog_hash=compiler_bundle.catalog_hash,
        ruleset_id=compiler_bundle.ruleset_id,
        ruleset_hash=compiler_bundle.ruleset_hash,
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
        source_manifest_ids=compiler_bundle.source_manifest_ids,
        provisional_decision_ids=compiler_bundle.provisional_decision_ids,
    )
    with pytest.raises(ChampionsReadinessError, match="pure simulator"):
        resolve_champions_readiness(
            sim01_disguise, compilation, _sealed_sim01_fixture()
        )
    with pytest.raises(
        ChampionsReadinessError,
        match="compiler_candidate_not_ready.*fixture_species_not_in_verified_target_pool",
    ):
        resolve_champions_readiness(
            compiler_bundle, compilation, _sealed_sim01_fixture()
        )


def test_direct_readiness_shape_cannot_be_attached_and_no_token_exists(
    compilation,
) -> None:
    bundle = _compiler_bound_identity(compilation)
    fixture = _sealed_sim01_fixture()
    forged = _direct_readiness(compilation, bundle, fixture)

    assert not hasattr(readiness_module, "_READINESS_TOKEN")
    with pytest.raises(ChampionsReadinessError, match="compiler_candidate_not_ready"):
        SealedEnvironmentInput(
            AI_ENV_ADAPTER_SCHEMA_VERSION,
            bundle,
            fixture,
            forged,
        )


def test_adapter_reset_revalidates_readiness_injected_after_construction(
    compilation,
) -> None:
    bundle = _compiler_bound_identity(compilation)
    fixture = _sealed_sim01_fixture()
    sealed = SealedEnvironmentInput(
        AI_ENV_ADAPTER_SCHEMA_VERSION,
        bundle,
        fixture,
    )
    # Frozen dataclasses are not an authentication boundary. Simulate a caller
    # bypassing normal construction and ensure reset still invokes the resolver.
    object.__setattr__(
        sealed,
        "readiness",
        _direct_readiness(compilation, bundle, fixture),
    )

    engine = object.__new__(BattleEngine)
    engine.catalog = compilation.catalog
    engine.ruleset = compilation.ruleset
    with pytest.raises(ChampionsReadinessError, match="compiler_candidate_not_ready"):
        DeterministicBattleEnv(
            engine,
            PlayerId.P1,
        ).reset(seed=1, sealed=sealed)


def test_fixture_requires_explicit_valid_development_record_binding(compilation) -> None:
    bundle = _compiler_bound_identity(compilation)
    fixture = _sealed_sim01_fixture()
    missing = fixture
    unknown = SealedEnvironmentFixture.seal(
        fixture.fixture_id,
        fixture.initial_state,
        development_record_refs=(RecordIdentity("record:unknown", "f" * 64),),
    )
    with pytest.raises(
        ChampionsReadinessError,
        match="fixture_development_record_refs_missing",
    ):
        resolve_champions_readiness(bundle, compilation, missing)
    with pytest.raises(
        ChampionsReadinessError,
        match="fixture_development_record_ref_not_in_capability_set",
    ):
        resolve_champions_readiness(bundle, compilation, unknown)

    # The intake-only compiler intentionally emits an empty construction
    # corpus, so no public resolver call can have a valid fixture membership
    # yet.  Exercise the positive membership branch with the smallest
    # structurally valid capability-set variant; production issuance remains
    # gated on the future promoted corpus path.
    record = RecordIdentity("record:registered", "a" * 64)
    capability_set = replace(
        compilation.capability_set,
        development_records=(record,),
    )
    compilation_with_record = replace(
        compilation,
        capability_set=capability_set,
    )
    bound = SealedEnvironmentFixture.seal(
        fixture.fixture_id,
        fixture.initial_state,
        development_record_refs=(record,),
    )
    blockers = readiness_module._candidate_fixture_blockers(
        bound,
        compilation_with_record,
    )
    assert not any(
        blocker.startswith("fixture_development_record_ref")
        for blocker in blockers
    )


def test_v1_readiness_resolver_explicitly_retains_positive_path_no_go(
    compilation,
) -> None:
    with pytest.raises(
        ChampionsReadinessError,
        match="readiness_positive_path_not_implemented",
    ):
        resolve_champions_readiness(
            _compiler_bound_identity(compilation),
            compilation,
            _sealed_sim01_fixture(),
        )


def test_fixture_binding_hash_changes_for_id_state_or_record_alias(compilation) -> None:
    fixture = _sealed_sim01_fixture()
    bound = SealedEnvironmentFixture.seal(
        fixture.fixture_id,
        fixture.initial_state,
        development_record_refs=compilation.capability_set.development_records[:1],
    )
    aliases = (
        SealedEnvironmentFixture.seal(
            "fixture:unregistered-alias",
            bound.initial_state,
            development_record_refs=bound.development_record_refs,
        ),
        SealedEnvironmentFixture.seal(
            bound.fixture_id,
            replace(bound.initial_state, battle_id="sim01-readiness-mutated"),
            development_record_refs=bound.development_record_refs,
        ),
        SealedEnvironmentFixture.seal(
            bound.fixture_id,
            bound.initial_state,
            development_record_refs=(RecordIdentity("record:other", "e" * 64),),
        ),
    )
    for alias in aliases:
        assert alias.fixture_binding_hash != bound.fixture_binding_hash


def test_candidate_fixture_rejects_runtime_battle_state(compilation) -> None:
    bundle = _compiler_bound_identity(compilation)
    fixture = _sealed_sim01_fixture()
    member = fixture.initial_state.sides[0].team[0]
    runtime_members = (
        (
            "fixture_pokemon_hp_not_full",
            replace(member, hp=member.stats.max_hp - 1),
        ),
        (
            "fixture_move_pp_not_full",
            replace(
                member,
                moves=(
                    replace(member.moves[0], pp=member.moves[0].max_pp - 1),
                    *member.moves[1:],
                ),
            ),
        ),
        ("fixture_contains_status", replace(member, status_id="burn")),
        (
            "fixture_contains_stat_stages",
            replace(member, stat_stages=replace(member.stat_stages, attack=1)),
        ),
        (
            "fixture_contains_volatile_status",
            replace(member, volatile_statuses=("confusion",)),
        ),
        (
            "fixture_contains_consumed_item",
            replace(
                member,
                item_id=None,
                consumed_item_id=member.item_id or "consumed-test-item",
            ),
        ),
        (
            "fixture_contains_reveal_state",
            replace(member, revealed_to_opponent=True),
        ),
        (
            "fixture_contains_reveal_state",
            replace(
                member,
                moves=(
                    replace(member.moves[0], revealed_to_opponent=True),
                    *member.moves[1:],
                ),
            ),
        ),
        (
            "fixture_contains_mega_evolved_state",
            replace(member, mega_evolved=True),
        ),
    )

    for blocker, runtime_member in runtime_members:
        candidate = _fixture_with_first_member(fixture, runtime_member)
        with pytest.raises(ChampionsReadinessError, match=blocker):
            resolve_champions_readiness(bundle, compilation, candidate)


def test_resolver_rechecks_tampered_fixture_hash(compilation) -> None:
    fixture = _sealed_sim01_fixture()
    object.__setattr__(fixture, "fixture_hash", "0" * 64)

    with pytest.raises(
        ChampionsReadinessError,
        match="fixture_hash does not match the canonical initial state",
    ):
        resolve_champions_readiness(
            _compiler_bound_identity(compilation),
            compilation,
            fixture,
        )


def test_attestation_fixture_binding_rejects_id_or_hash_alias(compilation) -> None:
    bundle = _compiler_bound_identity(compilation)
    fixture = _sealed_sim01_fixture()
    forged = _direct_readiness(compilation, bundle, fixture)
    aliases = (
        SealedEnvironmentFixture.seal("fixture:other-id", fixture.initial_state),
        SealedEnvironmentFixture.seal(
            fixture.fixture_id,
            replace(fixture.initial_state, battle_id="sim01-readiness-other-state"),
        ),
    )

    for alias in aliases:
        with pytest.raises(ValueError, match="bound to another fixture"):
            SealedEnvironmentInput(
                AI_ENV_ADAPTER_SCHEMA_VERSION,
                bundle,
                alias,
                forged,
            )


def test_attestation_compares_every_recomputed_field(
    compilation,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _compiler_bound_identity(compilation)
    fixture = _sealed_sim01_fixture()
    expected = _direct_readiness(compilation, bundle, fixture)
    tampered = replace(expected, compiler_report_hash="0" * 64)
    monkeypatch.setattr(
        readiness_module,
        "resolve_champions_readiness",
        lambda candidate_bundle, candidate_compilation, candidate_fixture: expected,
    )

    with pytest.raises(
        ChampionsReadinessError,
        match="differs from recomputed compiler substance",
    ):
        tampered.validate_against(bundle, fixture)
