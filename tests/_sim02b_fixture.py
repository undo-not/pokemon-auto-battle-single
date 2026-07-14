"""Reusable positive SIM-02B source fixture built entirely under ``tmp_path``.

The fixture deliberately uses three resolver-backed test-authoritative sources:
core inputs, development evidence, and external-holdout evidence.  Keeping the
last two in separate manifests makes the positive path exercise real source,
artifact, Replay, collection, and authoring lineage separation rather than
depending on caller labels.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from champions_sim import (
    BattleEngine,
    load_battle_fixture,
    load_catalog,
    load_ruleset,
    run_battle,
)
from champions_sim.capabilities.models import (
    ArtifactRecordRef,
    ConstructionRecord,
    ConstructionSelectionCorpus,
    GroundingAssertion,
    GroundingAssertionSet,
    MappingEntry,
    MappingEvidenceSet,
    MappingResolutionStatus,
    ObservationStatus,
    ObservedEntity,
    VerificationStatus,
)
from champions_sim.capabilities.pipeline import (
    build_target_capability_set,
    build_target_pool_manifest,
)
from champions_sim.compiler.semantic import compile_effect_semantic_registry
from champions_sim.core import (
    BattleEventKind,
    PlayerId,
    ReplayRecord,
    canonical_hash,
    canonical_json,
    to_canonical_data,
)
from champions_sim.policies import FirstLegalPolicy
from champions_sim.promotion.compiler import (
    ProductionPromotionCompilationV2,
    ProductionPromotionRequestV2,
    PromotionArtifactBindingsV2,
    PromotionArtifactLocatorV2,
    ReplayArtifactBindingV2,
    compile_production_promotion_v2,
)
from champions_sim.promotion.scenarios import (
    EngineScenarioCorpusV2,
    EngineScenarioV2,
    build_engine_scenario_corpus_v2,
    replay_choice_sequence_hash,
)
from champions_sim.promotion.sources import PromotionRecordReferenceV2
from champions_sim.regulations import (
    RegulationDataBundle,
    load_regulation_snapshot,
    load_target_pool,
)


CORE_MANIFEST_ID = "sim02b-test-core-source"
DEVELOPMENT_MANIFEST_ID = "sim02b-test-development-source"
HOLDOUT_MANIFEST_ID = "sim02b-test-holdout-source"

CORE_ARTIFACT_IDS = {
    "catalog": "core-catalog",
    "grounding_assertions": "core-grounding-assertions",
    "mapping_evidence": "core-mapping-evidence",
    "records": "core-records",
    "regulation": "core-regulation",
    "ruleset": "core-ruleset",
    "target_pool": "core-target-pool",
    "timing_evidence": "core-timing-evidence",
}
DEVELOPMENT_ARTIFACT_IDS = {
    "construction": "development-construction-corpus",
    "records": "development-records",
    "replay": "development-replay",
    "scenarios": "development-scenario-corpus",
}
HOLDOUT_ARTIFACT_IDS = {
    "construction": "holdout-construction-corpus",
    "records": "holdout-records",
    "replay": "holdout-replay",
    "scenarios": "holdout-scenario-corpus",
}


@dataclass(frozen=True, slots=True)
class Sim02BTestAuthoritativeFixture:
    """Complete runtime objects plus their independently sealed source bytes."""

    artifact_root: Path
    manifest_paths: tuple[Path, ...]
    artifact_paths: Mapping[str, Path]
    request: ProductionPromotionRequestV2
    development_scenario_corpus: EngineScenarioCorpusV2
    external_holdout_scenario_corpus: EngineScenarioCorpusV2
    replays: dict[str, ReplayRecord]

    def compile(self) -> ProductionPromotionCompilationV2:
        return compile_production_promotion_v2(
            self.request,
            development_scenario_corpus=self.development_scenario_corpus,
            external_holdout_scenario_corpus=(
                self.external_holdout_scenario_corpus
            ),
            replays=dict(self.replays),
        )


def build_test_authoritative_sim02b_fixture(
    tmp_path: Path,
) -> Sim02BTestAuthoritativeFixture:
    """Materialize the smallest complete positive compiler input below tmp_path."""

    root = (tmp_path / "sim02b-production-promotion-v2").resolve()
    (root / "artifacts/core").mkdir(parents=True)
    (root / "artifacts/development").mkdir(parents=True)
    (root / "artifacts/holdout").mkdir(parents=True)
    (root / "manifests").mkdir(parents=True)

    artifact_paths: dict[str, Path] = {}

    def artifact_path(artifact_id: str, partition: str) -> Path:
        path = root / "artifacts" / partition / f"{artifact_id}.json"
        artifact_paths[artifact_id] = path
        return path

    regulation_path = artifact_path(CORE_ARTIFACT_IDS["regulation"], "core")
    target_pool_path = artifact_path(CORE_ARTIFACT_IDS["target_pool"], "core")
    catalog_path = artifact_path(CORE_ARTIFACT_IDS["catalog"], "core")
    ruleset_path = artifact_path(CORE_ARTIFACT_IDS["ruleset"], "core")

    _write_json(regulation_path, _regulation_document())
    _write_json(target_pool_path, _target_pool_document())
    _write_json(catalog_path, _catalog_document())
    _write_json(ruleset_path, _ruleset_document())

    regulation = load_regulation_snapshot(regulation_path)
    target_pool = load_target_pool(target_pool_path)
    catalog = load_catalog(catalog_path)
    ruleset = load_ruleset(ruleset_path)
    target_key = target_pool.members[0].target_key

    mapping_record = {
        "target_key": target_key,
        "catalog_pokemon_id": "fixture-mon",
        "resolution_status": "resolved",
        "verification_status": "verified",
        "mapping_method": "test-authoritative-record",
    }
    mapping_ref = _artifact_record_ref(
        evidence_ref_id="mapping-evidence-fixture-mon",
        source_manifest_id=CORE_MANIFEST_ID,
        artifact_id=CORE_ARTIFACT_IDS["records"],
        json_pointer="/records/mapping",
        record=mapping_record,
    )
    mapping = MappingEvidenceSet(
        mapping_set_id="mapping-set-sim02b-test",
        target_pool_hash=target_pool.snapshot_hash,
        catalog_hash=catalog.snapshot_hash,
        entries=(
            MappingEntry(
                target_key=target_key,
                catalog_pokemon_id="fixture-mon",
                resolution_status=MappingResolutionStatus.RESOLVED,
                verification_status=VerificationStatus.VERIFIED,
                mapping_method="test-authoritative-record",
                candidate_pokemon_ids=(),
                evidence_ref_ids=(mapping_ref.evidence_ref_id,),
            ),
        ),
        evidence_refs=(mapping_ref,),
        source_manifest_ids=(CORE_MANIFEST_ID,),
    )

    development_record, development_ref, development_record_value = (
        _construction_record_and_evidence(
            partition_role="development",
            manifest_id=DEVELOPMENT_MANIFEST_ID,
            artifact_id=DEVELOPMENT_ARTIFACT_IDS["records"],
            evidence_ref_id="construction-evidence-development",
            observed_at="2026-07-14T00:10:00+09:00",
            regulation_id=regulation.regulation_id,
            target_key=target_key,
        )
    )
    holdout_record, holdout_ref, holdout_record_value = (
        _construction_record_and_evidence(
            partition_role="external_holdout",
            manifest_id=HOLDOUT_MANIFEST_ID,
            artifact_id=HOLDOUT_ARTIFACT_IDS["records"],
            evidence_ref_id="construction-evidence-holdout",
            observed_at="2026-07-14T00:20:00+09:00",
            regulation_id=regulation.regulation_id,
            target_key=target_key,
        )
    )
    development_construction = ConstructionSelectionCorpus(
        schema_version="1.0.0",
        corpus_id="construction-corpus-development",
        corpus_role="development",
        regulation_id=regulation.regulation_id,
        regulation_revision=regulation.revision,
        regulation_hash=regulation.snapshot_hash,
        capture_window_start="2026-07-14T00:00:00+09:00",
        capture_window_end="2026-07-14T00:15:00+09:00",
        records=(development_record,),
        evidence_refs=(development_ref,),
        source_manifest_ids=(DEVELOPMENT_MANIFEST_ID,),
    )
    holdout_construction = ConstructionSelectionCorpus(
        schema_version="1.0.0",
        corpus_id="construction-corpus-external-holdout",
        corpus_role="external_holdout",
        regulation_id=regulation.regulation_id,
        regulation_revision=regulation.revision,
        regulation_hash=regulation.snapshot_hash,
        capture_window_start="2026-07-14T00:15:01+09:00",
        capture_window_end="2026-07-14T00:30:00+09:00",
        records=(holdout_record,),
        evidence_refs=(holdout_ref,),
        source_manifest_ids=(HOLDOUT_MANIFEST_ID,),
    )

    mapping_path = artifact_path(CORE_ARTIFACT_IDS["mapping_evidence"], "core")
    development_construction_path = artifact_path(
        DEVELOPMENT_ARTIFACT_IDS["construction"], "development"
    )
    holdout_construction_path = artifact_path(
        HOLDOUT_ARTIFACT_IDS["construction"], "holdout"
    )
    _write_text(mapping_path, mapping.to_json())
    _write_text(development_construction_path, development_construction.to_json())
    _write_text(holdout_construction_path, holdout_construction.to_json())

    bundle = RegulationDataBundle(regulation, target_pool, ())
    target_manifest = build_target_pool_manifest(
        bundle, catalog, ruleset, mapping, development_construction
    )
    semantic = compile_effect_semantic_registry(catalog, ruleset, ())
    capability_set = build_target_capability_set(
        target_manifest,
        catalog,
        ruleset,
        semantic.registry,
        development_construction,
    )
    effects = {value.signature.effect_id for value in capability_set.capabilities}
    if effects != {"move.damage", "ability.rough_skin", "item.leftovers"}:
        raise AssertionError(f"unexpected minimal fixture capability set: {effects}")

    battle_path = root / "battle-fixture.json"
    _write_json(battle_path, _battle_document(catalog.catalog_id, str(ruleset.ruleset_id)))
    loaded_battle = load_battle_fixture(
        battle_path,
        catalog=catalog,
        ruleset=ruleset,
    )
    engine = BattleEngine(catalog, ruleset)
    policies = {
        PlayerId.P1: FirstLegalPolicy(),
        PlayerId.P2: FirstLegalPolicy(),
    }
    development_replay = run_battle(
        engine,
        loaded_battle.initial_state,
        seed=2026071401,
        policies=policies,
    ).replay
    holdout_replay = run_battle(
        engine,
        loaded_battle.initial_state,
        seed=2026071402,
        policies={
            PlayerId.P1: FirstLegalPolicy(),
            PlayerId.P2: FirstLegalPolicy(),
        },
    ).replay

    development_scenarios = tuple(
        _scenario(
            capability=capability,
            capability_set_hash=capability_set.capability_set_hash,
            replay=development_replay,
            partition_role="development",
            source_manifest_id=DEVELOPMENT_MANIFEST_ID,
            ordinal=index,
        )
        for index, capability in enumerate(capability_set.capabilities, start=1)
    )
    holdout_move_capability = next(
        value
        for value in capability_set.capabilities
        if value.signature.effect_id == "move.damage"
    )
    holdout_scenario = _scenario(
        capability=holdout_move_capability,
        capability_set_hash=capability_set.capability_set_hash,
        replay=holdout_replay,
        partition_role="external_holdout",
        source_manifest_id=HOLDOUT_MANIFEST_ID,
        ordinal=1,
    )
    development_scenario_corpus = build_engine_scenario_corpus_v2(
        corpus_id="engine-scenarios-development",
        corpus_role="development",
        target_capability_set_hash=capability_set.capability_set_hash,
        catalog_hash=catalog.snapshot_hash,
        ruleset_hash=ruleset.snapshot_hash,
        scenarios=development_scenarios,
    )
    holdout_scenario_corpus = build_engine_scenario_corpus_v2(
        corpus_id="engine-scenarios-external-holdout",
        corpus_role="external_holdout",
        target_capability_set_hash=capability_set.capability_set_hash,
        catalog_hash=catalog.snapshot_hash,
        ruleset_hash=ruleset.snapshot_hash,
        scenarios=(holdout_scenario,),
    )

    grounding_assertions: list[GroundingAssertion] = []
    grounding_records: dict[str, Any] = {}
    grounding_references: list[PromotionRecordReferenceV2] = []
    development_by_capability = {
        value.capability_id: value for value in development_scenarios
    }
    for index, capability in enumerate(capability_set.capabilities, start=1):
        scenario = development_by_capability[capability.capability_id]
        evidence_ref_id = f"grounding-evidence-{index}"
        assertion = GroundingAssertion(
            assertion_id=f"grounding-assertion-{index}",
            requirement_ids=tuple(sorted(capability.grounding_requirement_ids)),
            capability_ids=(capability.capability_id,),
            evidence_kind="official_primary",
            ruleset_id=str(ruleset.ruleset_id),
            ruleset_hash=ruleset.snapshot_hash,
            catalog_hash=catalog.snapshot_hash,
            trace_id=None,
            trace_hash=None,
            reference_replay_hash=development_replay.replay_hash,
            initial_state_hash=scenario.initial_state_hash,
            choice_sequence_hash=scenario.choice_sequence_hash,
            rng_condition_id="exact-replay-seed",
            expected_event_slice_hash=scenario.witness_event_hash,
            expected_state_checks=(),
            conformance_check_refs=(),
            evidence_ref_ids=(evidence_ref_id,),
            claimed_verdict="pass",
        )
        pointer = f"/records/grounding/{assertion.assertion_id}"
        record = to_canonical_data(assertion)
        grounding_records[assertion.assertion_id] = record
        grounding_references.append(
            PromotionRecordReferenceV2(
                evidence_ref_id=evidence_ref_id,
                source_manifest_id=CORE_MANIFEST_ID,
                artifact_id=CORE_ARTIFACT_IDS["records"],
                json_pointer=pointer,
                record_sha256=canonical_hash(record),
            )
        )
        grounding_assertions.append(assertion)
    grounding_set = GroundingAssertionSet(
        schema_version="1.0.0",
        assertion_set_id="grounding-set-sim02b-test",
        target_capability_set_id=capability_set.capability_set_id,
        target_capability_set_hash=capability_set.capability_set_hash,
        assertions=tuple(
            sorted(grounding_assertions, key=lambda value: value.assertion_id)
        ),
        source_manifest_ids=(CORE_MANIFEST_ID,),
    )

    core_records_path = artifact_path(CORE_ARTIFACT_IDS["records"], "core")
    development_records_path = artifact_path(
        DEVELOPMENT_ARTIFACT_IDS["records"], "development"
    )
    holdout_records_path = artifact_path(HOLDOUT_ARTIFACT_IDS["records"], "holdout")
    grounding_path = artifact_path(
        CORE_ARTIFACT_IDS["grounding_assertions"], "core"
    )
    _write_json(
        core_records_path,
        {
            "records": {
                "mapping": mapping_record,
                "grounding": grounding_records,
            }
        },
    )
    _write_json(development_records_path, {"records": {"construction": development_record_value}})
    _write_json(holdout_records_path, {"records": {"construction": holdout_record_value}})
    _write_text(grounding_path, grounding_set.to_json())

    development_scenario_path = artifact_path(
        DEVELOPMENT_ARTIFACT_IDS["scenarios"], "development"
    )
    holdout_scenario_path = artifact_path(
        HOLDOUT_ARTIFACT_IDS["scenarios"], "holdout"
    )
    development_replay_path = artifact_path(
        DEVELOPMENT_ARTIFACT_IDS["replay"], "development"
    )
    holdout_replay_path = artifact_path(HOLDOUT_ARTIFACT_IDS["replay"], "holdout")
    _write_text(development_scenario_path, development_scenario_corpus.to_json())
    _write_text(holdout_scenario_path, holdout_scenario_corpus.to_json())
    _write_text(development_replay_path, development_replay.to_json())
    _write_text(holdout_replay_path, holdout_replay.to_json())

    timing_path = artifact_path(CORE_ARTIFACT_IDS["timing_evidence"], "core")
    _write_json(
        timing_path,
        {
            "schema_version": "2.0.0",
            "timing_id": "sim02b-test-turnaround",
            "measurement_status": "test_fixed",
            "t0": "2026-07-14T00:00:00+00:00",
            "t_decision": "2026-07-14T01:00:00+00:00",
            "compute_seconds": 1800,
            "manual_seconds": 900,
            "external_wait_seconds": 300,
        },
    )

    core_manifest_path = root / "manifests/core.json"
    development_manifest_path = root / "manifests/development.json"
    holdout_manifest_path = root / "manifests/holdout.json"
    _write_source_manifest(
        root=root,
        path=core_manifest_path,
        manifest_id=CORE_MANIFEST_ID,
        artifact_paths={
            artifact_id: artifact_paths[artifact_id]
            for artifact_id in CORE_ARTIFACT_IDS.values()
        },
        artifact_registry=artifact_paths,
    )
    _write_source_manifest(
        root=root,
        path=development_manifest_path,
        manifest_id=DEVELOPMENT_MANIFEST_ID,
        artifact_paths={
            artifact_id: artifact_paths[artifact_id]
            for artifact_id in DEVELOPMENT_ARTIFACT_IDS.values()
        },
        artifact_registry=artifact_paths,
    )
    _write_source_manifest(
        root=root,
        path=holdout_manifest_path,
        manifest_id=HOLDOUT_MANIFEST_ID,
        artifact_paths={
            artifact_id: artifact_paths[artifact_id]
            for artifact_id in HOLDOUT_ARTIFACT_IDS.values()
        },
        artifact_registry=artifact_paths,
    )
    manifest_paths = tuple(
        sorted(
            (core_manifest_path, development_manifest_path, holdout_manifest_path),
            key=lambda value: value.as_posix(),
        )
    )

    locator = lambda manifest_id, artifact_id: PromotionArtifactLocatorV2(  # noqa: E731
        manifest_id, artifact_id
    )
    bindings = PromotionArtifactBindingsV2(
        regulation=locator(CORE_MANIFEST_ID, CORE_ARTIFACT_IDS["regulation"]),
        target_pool=locator(CORE_MANIFEST_ID, CORE_ARTIFACT_IDS["target_pool"]),
        catalog=locator(CORE_MANIFEST_ID, CORE_ARTIFACT_IDS["catalog"]),
        ruleset=locator(CORE_MANIFEST_ID, CORE_ARTIFACT_IDS["ruleset"]),
        mapping_evidence=locator(
            CORE_MANIFEST_ID, CORE_ARTIFACT_IDS["mapping_evidence"]
        ),
        development_construction_corpus=locator(
            DEVELOPMENT_MANIFEST_ID, DEVELOPMENT_ARTIFACT_IDS["construction"]
        ),
        external_holdout_construction_corpus=locator(
            HOLDOUT_MANIFEST_ID, HOLDOUT_ARTIFACT_IDS["construction"]
        ),
        grounding_assertions=locator(
            CORE_MANIFEST_ID, CORE_ARTIFACT_IDS["grounding_assertions"]
        ),
        development_scenario_corpus=locator(
            DEVELOPMENT_MANIFEST_ID, DEVELOPMENT_ARTIFACT_IDS["scenarios"]
        ),
        external_holdout_scenario_corpus=locator(
            HOLDOUT_MANIFEST_ID, HOLDOUT_ARTIFACT_IDS["scenarios"]
        ),
        timing_evidence=locator(
            CORE_MANIFEST_ID, CORE_ARTIFACT_IDS["timing_evidence"]
        ),
    )

    replays: dict[str, ReplayRecord] = {}
    replay_bindings: list[ReplayArtifactBindingV2] = []
    for scenario in development_scenario_corpus.scenarios:
        replays[scenario.scenario_id] = development_replay
        replay_bindings.append(
            ReplayArtifactBindingV2(
                scenario.scenario_id,
                locator(DEVELOPMENT_MANIFEST_ID, DEVELOPMENT_ARTIFACT_IDS["replay"]),
            )
        )
    for scenario in holdout_scenario_corpus.scenarios:
        replays[scenario.scenario_id] = holdout_replay
        replay_bindings.append(
            ReplayArtifactBindingV2(
                scenario.scenario_id,
                locator(HOLDOUT_MANIFEST_ID, HOLDOUT_ARTIFACT_IDS["replay"]),
            )
        )

    request = ProductionPromotionRequestV2(
        artifact_root=root,
        manifest_relative_paths=tuple(
            sorted(path.relative_to(root).as_posix() for path in manifest_paths)
        ),
        artifacts=bindings,
        replay_artifacts=tuple(
            sorted(replay_bindings, key=lambda value: value.scenario_id)
        ),
        grounding_evidence_refs=tuple(
            sorted(
                grounding_references,
                key=lambda value: value.evidence_ref_id,
            )
        ),
    )
    return Sim02BTestAuthoritativeFixture(
        artifact_root=root,
        manifest_paths=manifest_paths,
        artifact_paths=dict(artifact_paths),
        request=request,
        development_scenario_corpus=development_scenario_corpus,
        external_holdout_scenario_corpus=holdout_scenario_corpus,
        replays=replays,
    )


def rewrite_manifest_artifact(
    fixture: Sim02BTestAuthoritativeFixture,
    artifact_id: str,
    payload: bytes | str,
) -> None:
    """Rewrite one artifact and re-sign its declaring test manifest."""

    encoded = payload.encode("utf-8") if isinstance(payload, str) else payload
    matches: list[tuple[Path, dict[str, Any], dict[str, Any]]] = []
    for manifest_path in fixture.manifest_paths:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for entry in manifest["artifacts"]:
            if entry["artifact_id"] == artifact_id:
                matches.append((manifest_path, manifest, entry))
    if len(matches) != 1:
        raise AssertionError(f"artifact must have one declaring manifest: {artifact_id}")
    manifest_path, manifest, entry = matches[0]
    artifact_path = fixture.artifact_root.joinpath(
        *Path(entry["relative_path"]).parts
    )
    artifact_path.write_bytes(encoded)
    entry["byte_count"] = len(encoded)
    entry["sha256"] = hashlib.sha256(encoded).hexdigest()
    _write_json(manifest_path, manifest)


def rewrite_source_manifests_as_production_claim(
    fixture: Sim02BTestAuthoritativeFixture,
) -> None:
    """Forge a coherent production label while retaining synthetic Regulation."""

    for manifest_path in fixture.manifest_paths:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        license_id = manifest["license_artifact_id"]
        license_entry = next(
            value for value in manifest["artifacts"] if value["artifact_id"] == license_id
        )
        license_path = fixture.artifact_root.joinpath(
            *Path(license_entry["relative_path"]).parts
        )
        license_document = json.loads(license_path.read_text(encoding="utf-8"))
        license_document["verification_status"] = "verified"
        license_document["license_identifier"] = (
            "test-only-production-misclaim:" + manifest["manifest_id"]
        )
        rewrite_manifest_artifact(
            fixture,
            license_id,
            canonical_json(license_document),
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["source_kind"] = "official_rule"
        manifest["authority"] = "official"
        _write_json(manifest_path, manifest)


def _regulation_document() -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "regulation_id": "SIM02B-TEST",
        "revision": "r1",
        "title": "SIM-02B test-authoritative regulation",
        "status": "synthetic",
        "verification_status": "synthetic_rehearsal",
        "published_at": None,
        "period": {
            "start_date": "2026-07-14",
            "end_at": "2026-08-01T00:00:00+09:00",
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
        "required_mechanics": [],
        "source_manifest_ids": [CORE_MANIFEST_ID],
    }


def _target_pool_document() -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "regulation_id": "SIM02B-TEST",
        "regulation_revision": "r1",
        "expected_member_count": 1,
        "members": [
            {
                "national_dex_no": 1,
                "form_code": "00",
                "variant_code": "0",
                "label": "Fixture Mon",
                "pokemon_id": None,
            }
        ],
        "source_manifest_ids": [CORE_MANIFEST_ID],
    }


def _catalog_document() -> dict[str, Any]:
    moves = [
        {
            "move_id": f"contact-{index}",
            "name": f"Contact {index}",
            "type_id": "normal",
            "category": "physical",
            "power": 40,
            "accuracy": 100,
            "pp": 35,
            "priority": 0,
            "contact": True,
            "effect": {"kind": "damage"},
        }
        for index in range(1, 5)
    ]
    return {
        "schema_version": "1.0.0",
        "catalog_id": "sim02b-test-catalog",
        "engine_semantics_version": "sim-core-0.1",
        "source_manifest_id": CORE_MANIFEST_ID,
        "type_chart_default_multiplier": "1",
        "types": [{"type_id": "normal"}],
        "type_chart": {},
        "moves": moves,
        "abilities": [
            {
                "ability_id": "rough-skin-fixture",
                "name": "Rough Skin Fixture",
                "effect_id": "rough_skin",
            }
        ],
        "items": [
            {
                "item_id": "leftovers-fixture",
                "name": "Leftovers Fixture",
                "effect_id": "leftovers",
                "consumable": False,
            }
        ],
        "species": [
            {
                "pokemon_id": "fixture-mon",
                "name": "Fixture Mon",
                "types": ["normal"],
                "ability_ids": ["rough-skin-fixture"],
                "legal_move_ids": [
                    "contact-1",
                    "contact-2",
                    "contact-3",
                    "contact-4",
                ],
            }
        ],
        "mega_evolutions": [],
    }


def _ruleset_document() -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "ruleset_id": "sim02b-test-rules",
        "engine_semantics_version": "sim-core-0.1",
        "name": "SIM-02B test-authoritative rules",
        "battle_format": "singles_3v3",
        "team_size": 3,
        "level": 50,
        "item_clause": True,
        "max_turns": 500,
        "damage_rolls": list(range(85, 101)),
        "critical": {
            "chance_numerator": 1,
            "chance_denominator": 24,
            "multiplier_numerator": 3,
            "multiplier_denominator": 2,
        },
        "residuals": {
            "leftovers": {"numerator": 1, "denominator": 16},
        },
        "ability_rules": {
            "rough_skin": {"numerator": 1, "denominator": 8},
        },
        "supported_mechanics": [
            "accuracy",
            "critical_hit",
            "damage_roll",
            "fixed_power_damage",
            "leftovers",
            "priority",
            "rough_skin",
            "speed_order",
            "stab",
            "stat_stages",
            "type_effectiveness",
        ],
        "unsupported_mechanics": [],
        "provisional_rules": [],
        "provisional_decision_ids": [],
        "source_manifest_ids": [CORE_MANIFEST_ID],
    }


def _battle_document(catalog_id: str, ruleset_id: str) -> dict[str, Any]:
    def pokemon(instance_id: str, *, item: bool, speed: int) -> dict[str, Any]:
        return {
            "instance_id": instance_id,
            "pokemon_id": "fixture-mon",
            "ability_id": "rough-skin-fixture",
            "item_id": "leftovers-fixture" if item else None,
            "stats": {
                "hp": 240,
                "atk": 120,
                "def": 120,
                "spa": 80,
                "spd": 120,
                "spe": speed,
            },
            "moves": ["contact-1", "contact-2", "contact-3", "contact-4"],
        }

    return {
        "schema_version": "1.0.0",
        "battle_id": "sim02b-test-battle",
        "ruleset_id": ruleset_id,
        "catalog_id": catalog_id,
        "seed": 20260714,
        "sides": {
            "p1": {
                "active": "p1-fixture-1",
                "team": [
                    pokemon("p1-fixture-1", item=True, speed=101),
                    pokemon("p1-fixture-2", item=False, speed=101),
                    pokemon("p1-fixture-3", item=False, speed=101),
                ],
            },
            "p2": {
                "active": "p2-fixture-1",
                "team": [
                    pokemon("p2-fixture-1", item=True, speed=100),
                    pokemon("p2-fixture-2", item=False, speed=100),
                    pokemon("p2-fixture-3", item=False, speed=100),
                ],
            },
        },
    }


def _construction_record_and_evidence(
    *,
    partition_role: str,
    manifest_id: str,
    artifact_id: str,
    evidence_ref_id: str,
    observed_at: str,
    regulation_id: str,
    target_key: str,
) -> tuple[ConstructionRecord, ArtifactRecordRef, dict[str, Any]]:
    suffix = "development" if partition_role == "development" else "holdout"
    record = ConstructionRecord(
        record_id=f"construction-record-{suffix}",
        record_kind="usage_marginal",
        observed_at=observed_at,
        regulation_id=regulation_id,
        joint_group_id=None,
        target_key=target_key,
        entities=(
            ObservedEntity(
                field="move",
                entity_id="contact-1",
                status=ObservationStatus.CONFIRMED,
                rate_ppm=1_000_000,
                rank=1,
                evidence_ref_ids=(evidence_ref_id,),
            ),
        ),
        observed_capabilities=(),
        source_complete=True,
        evidence_ref_ids=(evidence_ref_id,),
        blockers=(),
        record_hash="0" * 64,
    )
    unsigned = to_canonical_data(record)
    del unsigned["record_hash"]
    record = replace(record, record_hash=canonical_hash(unsigned))
    record_value = to_canonical_data(record)
    reference = _artifact_record_ref(
        evidence_ref_id=evidence_ref_id,
        source_manifest_id=manifest_id,
        artifact_id=artifact_id,
        json_pointer="/records/construction",
        record=record_value,
    )
    return record, reference, record_value


def _artifact_record_ref(
    *,
    evidence_ref_id: str,
    source_manifest_id: str,
    artifact_id: str,
    json_pointer: str,
    record: Any,
) -> ArtifactRecordRef:
    return ArtifactRecordRef(
        evidence_ref_id=evidence_ref_id,
        source_manifest_id=source_manifest_id,
        artifact_id=artifact_id,
        json_pointer=json_pointer,
        record_sha256=canonical_hash(record),
    )


def _scenario(
    *,
    capability: Any,
    capability_set_hash: str,
    replay: ReplayRecord,
    partition_role: str,
    source_manifest_id: str,
    ordinal: int,
) -> EngineScenarioV2:
    step_index, event_index = _witness_for_effect(
        replay, capability.signature.effect_id
    )
    event = replay.steps[step_index].events[event_index]
    suffix = (
        "development"
        if partition_role == "development"
        else "external-holdout"
    )
    return EngineScenarioV2(
        scenario_id=f"scenario-{suffix}-{ordinal}",
        partition_role=partition_role,
        capability_id=capability.capability_id,
        target_capability_set_hash=capability_set_hash,
        initial_state_hash=replay.initial_state.state_hash,
        choice_sequence_hash=replay_choice_sequence_hash(replay),
        seed=replay.initial_rng.seed,
        rng_algorithm_id=replay.rng_algorithm_id,
        catalog_hash=replay.bundle.catalog_content_hash,
        ruleset_hash=replay.bundle.ruleset_content_hash,
        replay_hash=replay.replay_hash,
        witness_step_index=step_index,
        witness_event_index=event_index,
        witness_event_kind=event.kind.value,
        witness_event_hash=canonical_hash(event),
        source_lineage_ids=(source_manifest_id,),
        collection_lineage_ids=(f"collection-{suffix}",),
        authoring_lineage_ids=(f"authoring-{suffix}",),
    )


def _witness_for_effect(replay: ReplayRecord, effect_id: str) -> tuple[int, int]:
    for step_index, step in enumerate(replay.steps):
        for event_index, event in enumerate(step.events):
            details = dict(event.details)
            if effect_id == "move.damage" and event.kind is BattleEventKind.DAMAGE:
                source = details.get("source")
                if isinstance(source, str) and source.startswith("contact-") and any(
                    prior.kind is BattleEventKind.MOVE_USED
                    and dict(prior.details).get("move_id") == source
                    and prior.actor == event.actor
                    for prior in step.events[:event_index]
                ):
                    return step_index, event_index
            if (
                effect_id == "ability.rough_skin"
                and event.kind is BattleEventKind.ABILITY_TRIGGERED
                and details.get("ability_id") == "rough-skin-fixture"
                and any(
                    later.kind is BattleEventKind.DAMAGE
                    and later.actor == event.actor
                    and dict(later.details).get("source") == "rough_skin"
                    for later in step.events[event_index + 1 :]
                )
            ):
                return step_index, event_index
            if (
                effect_id == "item.leftovers"
                and event.kind is BattleEventKind.ITEM_TRIGGERED
                and details.get("item_id") == "leftovers-fixture"
                and any(
                    later.kind is BattleEventKind.HEALED
                    and later.subject == event.subject
                    and dict(later.details).get("source") == "leftovers"
                    for later in step.events[event_index + 1 :]
                )
            ):
                return step_index, event_index
    raise AssertionError(f"Replay lacks a positive witness for {effect_id}")


def _write_source_manifest(
    *,
    root: Path,
    path: Path,
    manifest_id: str,
    artifact_paths: Mapping[str, Path],
    artifact_registry: dict[str, Path],
) -> None:
    license_id = f"{manifest_id}-license"
    partition = next(iter(artifact_paths.values())).parent.name
    license_path = root / "artifacts" / partition / f"{license_id}.json"
    artifact_registry[license_id] = license_path
    _write_json(
        license_path,
        {
            "schema_version": "2.0.0",
            "license_id": f"license-{manifest_id}",
            "source_manifest_id": manifest_id,
            "verification_status": "test_authoritative",
            "license_identifier": None,
            "license_url": None,
            "use_policy": {
                "local_research_allowed": True,
                "private_match_allowed": True,
                "training_allowed": True,
                "redistribution": "prohibited",
                "commercial_use": "prohibited",
            },
        },
    )
    all_artifacts = {**artifact_paths, license_id: license_path}
    entries = []
    for artifact_id, artifact_path in sorted(all_artifacts.items()):
        payload = artifact_path.read_bytes()
        entries.append(
            {
                "artifact_id": artifact_id,
                "role": (
                    "license_record" if artifact_id == license_id else "source_data"
                ),
                "relative_path": artifact_path.relative_to(root).as_posix(),
                "media_type": "application/json",
                "byte_count": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    _write_json(
        path,
        {
            "schema_version": "2.0.0",
            "manifest_id": manifest_id,
            "source_kind": "test_fixture",
            "authority": "test_authoritative",
            "title": f"SIM-02B fixture source {manifest_id}",
            "publisher": "champions-sim tests",
            "locator": {"kind": "logical", "value": manifest_id},
            "retrieved_at": "2026-07-14T00:00:00+00:00",
            "license_artifact_id": license_id,
            "artifacts": entries,
        },
    )


def _write_json(path: Path, value: Any) -> None:
    _write_text(path, canonical_json(value))


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="")


__all__ = [
    "CORE_ARTIFACT_IDS",
    "CORE_MANIFEST_ID",
    "DEVELOPMENT_ARTIFACT_IDS",
    "DEVELOPMENT_MANIFEST_ID",
    "HOLDOUT_ARTIFACT_IDS",
    "HOLDOUT_MANIFEST_ID",
    "Sim02BTestAuthoritativeFixture",
    "build_test_authoritative_sim02b_fixture",
    "rewrite_manifest_artifact",
    "rewrite_source_manifests_as_production_claim",
]
