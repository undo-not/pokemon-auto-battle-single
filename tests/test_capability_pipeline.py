from __future__ import annotations

from dataclasses import replace
from fractions import Fraction
import json
from pathlib import Path

import pytest

from champions_sim.catalog import (
    AbilityDefinition,
    CatalogSnapshot,
    ItemDefinition,
    MoveDefinition,
    RuleSetSnapshot,
    SpeciesDefinition,
)
from champions_sim.capabilities import (
    ArtifactRecordRef,
    CapabilityReachability,
    CapabilitySignature,
    ConstructionRecord,
    ConstructionSelectionCorpus,
    ContextAtom,
    CoverageDimensionResult,
    DimensionStatus,
    EffectSemanticRegistry,
    ExecutionRegistry,
    ExecutionSupport,
    GroundingAssertion,
    GroundingAssertionSet,
    MappingEntry,
    MappingEvidenceSet,
    MappingResolutionStatus,
    ObservationStatus,
    ObservedEntity,
    ProbeExecution,
    ProbeSpec,
    SemanticDefinition,
    StateCheck,
    VerificationStatus,
    build_mechanic_coverage_matrix,
    build_target_capability_set,
    build_target_pool_manifest,
    evaluate_external_holdout,
    load_construction_selection_corpus,
    load_grounding_assertion_set,
    load_mapping_evidence_set,
    resolve_grounding_assertions,
    run_capability_probes,
)
from champions_sim.core import AbilityId, ItemId, MoveId, PokemonId, RuleSetId, UnsupportedMechanic, canonical_hash, canonical_json
from champions_sim.core.canonical import to_canonical_data
from champions_sim.regulations import (
    RegulationDataBundle,
    load_regulation_bundle,
)
from champions_sim.regulations.models import (
    BattleTimer,
    ItemClause,
    RegulationPeriod,
    RegulationSnapshot,
    TargetPoolMember,
    TargetPoolSnapshot,
)
from scripts.validate_sim01_bundle import validate_document_contract


ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "data/schemas"
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def _catalog() -> CatalogSnapshot:
    moves = (
        MoveDefinition(MoveId("move-a"), "A", "normal", "physical", 40, 100, 20, 0, True, {"kind": "damage"}),
        MoveDefinition(MoveId("move-b"), "B", "normal", "physical", 50, 100, 20, 0, False, {"kind": "damage"}),
    )
    ability = AbilityDefinition(AbilityId("ability-a"), "Ability", "ability-shared")
    species = (
        SpeciesDefinition(PokemonId("mon-a"), "A", ("normal",), (ability.ability_id,), (moves[0].move_id, moves[1].move_id)),
        SpeciesDefinition(PokemonId("mon-b"), "B", ("normal",), (ability.ability_id,), (moves[0].move_id, moves[1].move_id)),
    )
    return CatalogSnapshot(
        schema_version="1.0.0", catalog_id="synthetic-catalog", engine_semantics_version="test-v1",
        source_manifest_id="catalog-source", snapshot_hash=SHA_A,
        type_chart_default_multiplier=Fraction(1, 1), type_ids=("normal",), type_chart=(),
        moves=moves, abilities=(ability,),
        items=(ItemDefinition(ItemId("item-a"), "Item", "item-effect"),),
        species=species,
    )


def _ruleset() -> RuleSetSnapshot:
    return RuleSetSnapshot(
        schema_version="1.0.0", ruleset_id=RuleSetId("synthetic-rules"),
        engine_semantics_version="test-v1", snapshot_hash=SHA_B,
        battle_format="singles_3v3", team_size=3, level=50, item_clause=True, max_turns=500,
        damage_rolls=tuple(range(85, 101)), supported_mechanics=frozenset({"mega_evolution"}),
        unsupported_mechanics=frozenset(), provisional_rules=(), provisional_decision_ids=(),
        source_manifest_ids=("rules-source",), critical_chance=Fraction(1, 24),
        critical_multiplier=Fraction(3, 2), raw={},
    )


def _bundle() -> RegulationDataBundle:
    regulation = RegulationSnapshot(
        schema_version="1.0.0", regulation_id="TEST", revision="r1", title="test",
        status="synthetic", verification_status="synthetic_rehearsal", published_at=None,
        period=RegulationPeriod("2026-01-01", "2026-01-31T00:00:00+09:00", "Asia/Tokyo"),
        battle_format="singles_3v3", team_size=3, level=50,
        item_clause=ItemClause(True, False), battle_timer=BattleTimer(20, 7, 45, 90),
        required_mechanics=("mega_evolution",), source_manifest_ids=("reg-source",), snapshot_hash=SHA_C,
    )
    pool = TargetPoolSnapshot(
        schema_version="1.0.0", target_pool_id="eligible:TEST:r1", regulation_id="TEST",
        regulation_revision="r1", expected_member_count=2,
        members=(
            TargetPoolMember(1, "00", "0", "A", None),
            TargetPoolMember(2, "00", "0", "B", None),
        ), source_manifest_ids=("reg-source",), snapshot_hash="d" * 64,
    )
    return RegulationDataBundle(regulation, pool, ())


def _evidence(ref_id: str = "evidence-map") -> ArtifactRecordRef:
    return ArtifactRecordRef(ref_id, "source-evidence", "artifact-evidence", "/records/0", "e" * 64)


def _corpus(*, role: str = "development", record_hash: str = "f" * 64, records: bool = True) -> ConstructionSelectionCorpus:
    evidence = _evidence("evidence-corpus")
    record = ConstructionRecord(
        record_id="record-1", record_kind="usage_marginal", observed_at="2026-01-02T00:00:00+09:00",
        regulation_id="TEST", joint_group_id=None, target_key="dex:0001:form:00:variant:0",
        entities=(ObservedEntity("move", "move-a", ObservationStatus.CONFIRMED, 1, 999, (evidence.evidence_ref_id,)),),
        observed_capabilities=(), source_complete=True, evidence_ref_ids=(evidence.evidence_ref_id,),
        blockers=(), record_hash=record_hash,
    )
    return ConstructionSelectionCorpus(
        "1.0.0", f"corpus-{role}", role, "TEST", "r1", SHA_C,
        "2026-01-01T00:00:00+09:00", "2026-01-31T00:00:00+09:00",
        (record,) if records else (), (evidence,), ("corpus-source",),
    )


def _mapping(bundle=None, catalog=None, *, unresolved_second: bool = False) -> MappingEvidenceSet:
    bundle = bundle or _bundle()
    catalog = catalog or _catalog()
    evidence = _evidence()
    entries = []
    for index, member in enumerate(bundle.target_pool.members):
        unresolved = unresolved_second and index == 1
        entries.append(MappingEntry(
            member.target_key, None if unresolved else f"mon-{chr(ord('a') + index)}",
            MappingResolutionStatus.UNRESOLVED if unresolved else MappingResolutionStatus.RESOLVED,
            VerificationStatus.VERIFIED, "exact-dex-form", (),
            () if unresolved else (evidence.evidence_ref_id,),
        ))
    return MappingEvidenceSet("mapping-test", bundle.target_pool.snapshot_hash, catalog.snapshot_hash,
                              tuple(entries), (evidence,), ("mapping-source",))


def _signature(effect: str, trigger: str = "on-action", target: str = "opponent") -> CapabilitySignature:
    return CapabilitySignature(effect, trigger, target, (ContextAtom("mode", "standard"),), "normal-turn")


def _semantic_registry() -> EffectSemanticRegistry:
    definitions = (
        SemanticDefinition("sem-damage", "move", "damage", _signature("standard-damage"), (), ("token-damage",), ("core",)),
        SemanticDefinition("sem-ability", "ability", "ability-shared", _signature("ability-effect", "on-switch", "self"), (), ("token-ability",), ("core",)),
        SemanticDefinition("sem-item", "item", "item-effect", _signature("item-effect", "after-damage", "self"), (), ("token-item",), ("entity.item-profile",)),
        SemanticDefinition("sem-mega", "mechanic", "mega_evolution", _signature("mega-evolution", "before-order", "self"), (), ("token-mega",), ("core",)),
        SemanticDefinition("sem-interaction", "interaction", "damage-ability", _signature("damage-ability-interaction", "after-damage", "attacker"), ("token-damage", "token-ability"), (), ("order",)),
    )
    return EffectSemanticRegistry("sem-registry", "sem-v1", definitions, ("sem-source",))


def _built(*, unresolved_second: bool = False):
    bundle, catalog, ruleset, corpus = _bundle(), _catalog(), _ruleset(), _corpus()
    manifest = build_target_pool_manifest(bundle, catalog, ruleset, _mapping(bundle, catalog, unresolved_second=unresolved_second), corpus)
    capability_set = build_target_capability_set(manifest, catalog, ruleset, _semantic_registry(), corpus)
    return manifest, capability_set


def _execution_registry(capability_set, *, omit_dimension: str | None = None):
    supports = []
    for capability in capability_set.capabilities:
        dimensions = []
        for dimension in ("legality", "transition", "rng", "event", "observation", "replay"):
            if dimension == omit_dimension:
                continue
            dimensions.append(CoverageDimensionResult(
                dimension, DimensionStatus.PASS,
                "rng:none" if dimension == "rng" else f"contract:{dimension}",
                (f"test:{dimension}",),
            ))
        supports.append(ExecutionSupport(capability.capability_id, "handler-shared", tuple(dimensions)))
    return ExecutionRegistry("exec-registry", "test-v1", tuple(supports), ("1" * 64,))


def _probes(capability_set, *, silent_mutation: bool = False):
    specs = []
    executors = {}
    for index, capability in enumerate(capability_set.capabilities):
        probe_id = f"probe-{index}"
        specs.append(ProbeSpec(probe_id, capability.capability_id, "supported"))
        executors[probe_id] = lambda: ProbeExecution("success", True, None)
    if silent_mutation:
        capability = capability_set.capabilities[0]
        specs.append(ProbeSpec("probe-mutation", capability.capability_id, "explicit_unsupported"))
        executors["probe-mutation"] = lambda: ProbeExecution("success", False, None)
    return run_capability_probes(capability_set, tuple(specs), executors)


def _grounding(capability_set, *, resolver_ok: bool = True):
    assertions = []
    for index, requirement in enumerate(capability_set.grounding_requirements):
        assertions.append(GroundingAssertion(
            f"assertion-{index}", (requirement.requirement_id,), (requirement.capability_id,),
            "official_primary", "synthetic-rules", capability_set.ruleset_hash,
            capability_set.catalog_hash, None, None, None, "2" * 64, "3" * 64,
            "rng-observed", "4" * 64, (StateCheck("/turn", 1),), (),
            ("ground-evidence",), "pass",
        ))
    raw = GroundingAssertionSet("1.0.0", "assertions", capability_set.capability_set_id,
                                capability_set.capability_set_hash, tuple(assertions), ("ground-source",))
    return resolve_grounding_assertions(raw, capability_set, validated_traces={},
                                        evidence_resolver=lambda _: resolver_ok)


def test_explicit_mapping_and_legal_fixed_point_dedupe_origins() -> None:
    manifest, capability_set = _built()
    assert manifest.eligible_member_count == 2
    assert manifest.selection_policy.popularity_filter == "none"
    assert capability_set.denominator_final
    assert len(capability_set.capabilities) == 5
    damage = next(value for value in capability_set.capabilities if value.signature.effect_id == "standard-damage")
    assert damage.reachability is CapabilityReachability.OBSERVED
    refs = [value for value in capability_set.entity_capability_refs if value.capability_id == damage.capability_id]
    assert len(refs) == 4
    assert {(value.entity_id, value.owner_entity_id) for value in refs} == {
        ("move-a", "mon-a"), ("move-b", "mon-a"), ("move-a", "mon-b"), ("move-b", "mon-b")
    }
    mega = next(value for value in capability_set.capabilities if value.signature.effect_id == "mega-evolution")
    assert mega.reachability is CapabilityReachability.MANDATORY
    assert any(value.signature.effect_id == "damage-ability-interaction" for value in capability_set.capabilities)


def test_unresolved_mapping_keeps_denominator_and_rates_unmeasured() -> None:
    _, capability_set = _built(unresolved_second=True)
    assert not capability_set.denominator_final
    probes = _probes(capability_set)
    grounding = _grounding(capability_set)
    matrix = build_mechanic_coverage_matrix(
        matrix_id="matrix-unresolved", capability_set=capability_set,
        execution_registry=_execution_registry(capability_set), probe_report=probes,
        grounding_assertions=grounding, holdout_report=None,
    )
    assert matrix.declared_target_capability_count is None
    assert matrix.target_pool_execution_coverage_rate_ppm is None
    assert matrix.verified_grounding_conformance_rate_ppm is None
    assert "capability_denominator_not_final" in matrix.blocking_reasons


def test_partially_verified_mapping_cannot_finalize_denominator() -> None:
    bundle, catalog, ruleset, corpus = _bundle(), _catalog(), _ruleset(), _corpus()
    mapping = _mapping(bundle, catalog)
    entries = (
        replace(
            mapping.entries[0],
            verification_status=VerificationStatus.PARTIALLY_VERIFIED,
        ),
        *mapping.entries[1:],
    )
    manifest = build_target_pool_manifest(
        bundle,
        catalog,
        ruleset,
        replace(mapping, entries=entries),
        corpus,
    )
    capability_set = build_target_capability_set(
        manifest,
        catalog,
        ruleset,
        _semantic_registry(),
        corpus,
    )

    assert any(
        value.startswith("mapping_not_verified:dex:0001:form:00:variant:0")
        for value in manifest.blockers
    )
    assert capability_set.denominator_final is False


def test_full_six_dimensions_grounding_probes_and_holdout_promote_candidate() -> None:
    _, capability_set = _built()
    holdout = evaluate_external_holdout(capability_set, _corpus(role="external_holdout", record_hash="9" * 64))
    assert holdout.holdout_clean
    matrix = build_mechanic_coverage_matrix(
        matrix_id="matrix-ready", capability_set=capability_set,
        execution_registry=_execution_registry(capability_set), probe_report=_probes(capability_set),
        grounding_assertions=_grounding(capability_set), holdout_report=holdout,
    )
    assert matrix.target_pool_execution_coverage_rate_ppm == 1_000_000
    assert matrix.verified_grounding_conformance_rate_ppm == 1_000_000
    assert matrix.silent_fallback_count == 0
    assert matrix.coverage_complete and matrix.candidate_ready
    assert all(len(value.execution_dimensions) == 6 for value in matrix.rows)
    assert all(next(x for x in value.execution_dimensions if x.dimension == "rng").contract_id == "rng:none" for value in matrix.rows)


def test_missing_dimension_and_probe_derived_silent_fallback_block() -> None:
    _, capability_set = _built()
    holdout = evaluate_external_holdout(capability_set, _corpus(role="external_holdout", record_hash="9" * 64))
    matrix = build_mechanic_coverage_matrix(
        matrix_id="matrix-blocked", capability_set=capability_set,
        execution_registry=_execution_registry(capability_set, omit_dimension="replay"),
        probe_report=_probes(capability_set, silent_mutation=True),
        grounding_assertions=_grounding(capability_set), holdout_report=holdout,
    )
    assert matrix.silent_fallback_count == 1
    assert not matrix.coverage_complete and not matrix.candidate_ready
    assert all(not value.fully_supported for value in matrix.rows)


def test_explicit_unsupported_is_not_silent_fallback() -> None:
    _, capability_set = _built()
    capability = capability_set.capabilities[0]
    specs = (ProbeSpec("unsupported-probe", capability.capability_id, "explicit_unsupported"),)
    def unsupported():
        raise UnsupportedMechanic("synthetic")
    report = run_capability_probes(capability_set, specs, {"unsupported-probe": unsupported})
    assert report.silent_fallback_count == 0
    assert report.results[0].explicit_unsupported
    assert not report.positive_passed(capability.capability_id)


def test_grounding_resolver_does_not_trust_claimed_pass() -> None:
    _, capability_set = _built()
    grounding = _grounding(capability_set, resolver_ok=False)
    assert grounding.results
    assert all(value.verdict.value == "unverified" for value in grounding.results)


def test_grounding_unknown_claim_and_empty_expectation_cannot_pass() -> None:
    _, capability_set = _built()
    requirement = capability_set.grounding_requirements[0]
    base = GroundingAssertion(
        "assertion-unknown",
        (requirement.requirement_id,),
        (requirement.capability_id,),
        "official_primary",
        "synthetic-rules",
        capability_set.ruleset_hash,
        capability_set.catalog_hash,
        None,
        None,
        None,
        "2" * 64,
        "3" * 64,
        "rng-none",
        "4" * 64,
        (),
        (),
        ("source-evidence",),
        "unknown",
    )
    raw = GroundingAssertionSet(
        "1.0.0",
        "assertions-unknown",
        capability_set.capability_set_id,
        capability_set.capability_set_hash,
        (base,),
        ("ground-source",),
    )
    resolved = resolve_grounding_assertions(
        raw,
        capability_set,
        validated_traces={},
        evidence_resolver=lambda _: True,
    )
    assert resolved.results[0].verdict.value == "unverified"
    assert "assertion_claimed_unknown" in resolved.results[0].blockers

    with pytest.raises(ValueError, match="expected event slice or state check"):
        replace(base, claimed_verdict="pass", expected_event_slice_hash=None)


def test_grounding_assertion_loader_is_exact_and_rejects_noncanonical_values(
    tmp_path: Path,
) -> None:
    _, capability_set = _built()
    requirement = capability_set.grounding_requirements[0]
    assertion_set = GroundingAssertionSet(
        "1.0.0",
        "assertions-loader",
        capability_set.capability_set_id,
        capability_set.capability_set_hash,
        (
            GroundingAssertion(
                "assertion-loader",
                (requirement.requirement_id,),
                (requirement.capability_id,),
                "official_primary",
                "synthetic-rules",
                capability_set.ruleset_hash,
                capability_set.catalog_hash,
                None,
                None,
                None,
                "2" * 64,
                "3" * 64,
                "rng-observed",
                None,
                (StateCheck("/nested", {"values": (1, True, None)}),),
                (),
                ("ground-evidence",),
                "pass",
            ),
        ),
        ("ground-source",),
    )
    path = tmp_path / "grounding.json"
    path.write_text(assertion_set.to_json(), encoding="utf-8")
    assert load_grounding_assertion_set(path) == assertion_set

    extra = json.loads(assertion_set.to_json())
    extra["assertions"][0]["caller_verified"] = True
    path.write_text(json.dumps(extra), encoding="utf-8")
    with pytest.raises(ValueError, match="fields differ"):
        load_grounding_assertion_set(path)

    noncanonical = json.loads(assertion_set.to_json())
    noncanonical["assertions"][0]["expected_state_checks"][0]["expected"] = 1.5
    path.write_text(json.dumps(noncanonical), encoding="utf-8")
    with pytest.raises(ValueError, match=r"invalid assertions\[0\].expected_state_checks"):
        load_grounding_assertion_set(path)

    for field, invalid in (
        ("assertion_id", 123),
        ("evidence_kind", 123),
        ("ruleset_hash", True),
    ):
        wrong_type = json.loads(assertion_set.to_json())
        wrong_type["assertions"][0][field] = invalid
        path.write_text(json.dumps(wrong_type), encoding="utf-8")
        with pytest.raises(ValueError, match=r"invalid assertions\[0\]"):
            load_grounding_assertion_set(path)

    invalid_kind = json.loads(assertion_set.to_json())
    invalid_kind["assertions"][0]["evidence_kind"] = "caller_verified"
    path.write_text(json.dumps(invalid_kind), encoding="utf-8")
    with pytest.raises(ValueError, match=r"invalid assertions\[0\]"):
        load_grounding_assertion_set(path)

    bad_source_id = json.loads(assertion_set.to_json())
    bad_source_id["source_manifest_ids"] = [123]
    path.write_text(json.dumps(bad_source_id), encoding="utf-8")
    with pytest.raises(ValueError, match="invalid grounding assertion set"):
        load_grounding_assertion_set(path)

    relative_path = json.loads(assertion_set.to_json())
    relative_path["assertions"][0]["expected_state_checks"][0]["path"] = "relative"
    path.write_text(json.dumps(relative_path), encoding="utf-8")
    with pytest.raises(ValueError, match=r"invalid assertions\[0\].expected_state_checks"):
        load_grounding_assertion_set(path)

    path.write_text('{"value":1e999}', encoding="utf-8")
    with pytest.raises(ValueError, match="non-finite JSON number"):
        load_grounding_assertion_set(path)


def test_holdout_overlap_new_capability_and_unknown_are_fail_closed() -> None:
    _, capability_set = _built()
    new_signature = _signature("new-holdout-effect")
    evidence = _evidence("holdout-evidence")
    record = ConstructionRecord(
        "record-holdout", "battle_reveal", None, "TEST", None, None,
        (ObservedEntity("move", None, ObservationStatus.UNKNOWN, None, None, (evidence.evidence_ref_id,)),),
        (new_signature,), True, (evidence.evidence_ref_id,), ("replay_drift",),
        capability_set.development_records[0].record_hash,
    )
    holdout = ConstructionSelectionCorpus(
        "1.0.0", "holdout-bad", "external_holdout", "TEST", "r1", SHA_C,
        "2026-02-01", "2026-02-02", (record,), (evidence,), ("holdout-source",),
    )
    report = evaluate_external_holdout(capability_set, holdout)
    assert not report.holdout_clean
    assert report.overlapping_record_hashes
    assert report.new_capability_ids == (new_signature.capability_id,)
    assert report.unknown_observation_refs and report.quality_blockers


def test_official_235_requires_exact_explicit_mapping_and_never_uses_legacy_name_fallback() -> None:
    bundle = load_regulation_bundle(
        ROOT / "data/fixtures/regulations/m-b-current.json",
        ROOT / "data/fixtures/regulations/m-b-eligible-pokemon.json",
        manifest_dir=ROOT / "data/manifests", repository_root=ROOT,
    )
    from champions_sim import load_catalog, load_ruleset
    catalog = load_catalog(ROOT / "data/fixtures/sim01_catalog.json")
    ruleset = load_ruleset(ROOT / "data/fixtures/sim01_ruleset.json")
    entries = tuple(MappingEntry(
        member.target_key, None, MappingResolutionStatus.UNRESOLVED,
        VerificationStatus.UNVERIFIED, "not-mapped", (), (),
    ) for member in bundle.target_pool.members)
    mapping = MappingEvidenceSet("mapping-m-b-explicit", bundle.target_pool.snapshot_hash,
                                 catalog.snapshot_hash, entries, (), ("mapping-source",))
    corpus = ConstructionSelectionCorpus(
        "1.0.0", "corpus-m-b-empty", "development", "M-B", bundle.regulation.revision,
        bundle.regulation.snapshot_hash, "2026-07-01", "2026-07-02", (), (), ("corpus-source",),
    )
    manifest = build_target_pool_manifest(bundle, catalog, ruleset, mapping, corpus)
    assert manifest.eligible_member_count == len(manifest.member_mappings) == 235
    assert sum(value.resolution_status is MappingResolutionStatus.RESOLVED for value in manifest.member_mappings) == 0
    with pytest.raises(ValueError, match="exact official pool"):
        build_target_pool_manifest(bundle, catalog, ruleset, replace(mapping, entries=entries[:-1]), corpus)


def test_generated_outputs_match_recursive_schemas_and_hashes_are_stable() -> None:
    manifest, capability_set = _built()
    holdout = evaluate_external_holdout(capability_set, _corpus(role="external_holdout", record_hash="9" * 64))
    matrix = build_mechanic_coverage_matrix(
        matrix_id="matrix-schema", capability_set=capability_set,
        execution_registry=_execution_registry(capability_set), probe_report=_probes(capability_set),
        grounding_assertions=_grounding(capability_set), holdout_report=holdout,
    )
    for value, schema_name in (
        (json.loads(_corpus().to_json()), "construction-selection-corpus.schema.json"),
        (json.loads(manifest.to_json()), "target-pool-manifest.schema.json"),
        (json.loads(capability_set.to_json()), "target-capability-set.schema.json"),
        (json.loads(holdout.to_json()), "holdout-gap.schema.json"),
        (json.loads(matrix.to_json()), "mechanic-coverage-matrix.schema.json"),
    ):
        schema = json.loads((SCHEMAS / schema_name).read_text(encoding="utf-8"))
        validate_document_contract(value, schema, schema_name)
    assert manifest.manifest_hash == canonical_hash(manifest)
    assert capability_set.capability_set_hash == canonical_hash(capability_set)
    assert matrix.matrix_hash == canonical_hash(matrix)
    assert capability_set.to_json() == canonical_json(capability_set)


def test_strict_loaders_verify_record_hashes_and_mapping_schema(tmp_path: Path) -> None:
    corpus_raw = to_canonical_data(_corpus())
    record = corpus_raw["records"][0]
    record["record_hash"] = canonical_hash(
        {key: value for key, value in record.items() if key != "record_hash"}
    )
    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_text(json.dumps(corpus_raw, ensure_ascii=False), encoding="utf-8")
    loaded = load_construction_selection_corpus(corpus_path)
    assert loaded.records[0].record_hash == record["record_hash"]
    record["record_hash"] = "0" * 64
    corpus_path.write_text(json.dumps(corpus_raw), encoding="utf-8")
    with pytest.raises(ValueError, match="record_hash mismatch"):
        load_construction_selection_corpus(corpus_path)

    mapping = _mapping()
    mapping_path = tmp_path / "mapping.json"
    mapping_path.write_text(mapping.to_json(), encoding="utf-8")
    assert load_mapping_evidence_set(mapping_path) == mapping


def test_assertion_and_execution_registry_documents_match_schemas() -> None:
    _, capability_set = _built()
    requirement = capability_set.grounding_requirements[0]
    assertion_set = GroundingAssertionSet(
        "1.0.0", "assertion-schema", capability_set.capability_set_id,
        capability_set.capability_set_hash,
        (GroundingAssertion(
            "assertion-schema-1", (requirement.requirement_id,), (requirement.capability_id,),
            "official_primary", "synthetic-rules", capability_set.ruleset_hash,
            capability_set.catalog_hash, None, None, None, "2" * 64, "3" * 64,
            "rng-none", "4" * 64, (), (), ("source-evidence",), "pass",
        ),), ("source-manifest",),
    )
    for document, schema_name in (
        (json.loads(assertion_set.to_json()), "grounding-assertion-set.schema.json"),
        (json.loads(canonical_json(_execution_registry(capability_set))), "execution-capability-registry.schema.json"),
        (json.loads(_mapping().to_json()), "target-mapping-evidence.schema.json"),
    ):
        schema = json.loads((SCHEMAS / schema_name).read_text(encoding="utf-8"))
        validate_document_contract(document, schema, schema_name)
