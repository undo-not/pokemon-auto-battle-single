from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

import pytest

from champions_sim.capabilities import ConstructionRecord, ObservationStatus, ObservedEntity
from champions_sim.core import canonical_hash, to_canonical_data
from champions_sim.promotion import compiler as promotion_compiler
from champions_sim.promotion.compiler import (
    ExternalHoldoutVerificationV2,
    ProductionPromotionRequestV2,
    PromotionArtifactBindingsV2,
    PromotionArtifactLocatorV2,
    PromotionCompilationError,
    ReplayArtifactBindingV2,
    resolve_promotion_source_set_v2,
)
from champions_sim.promotion.sources import (
    PROMOTION_SOURCE_SCHEMA_VERSION,
    PromotionArtifactRoleV2,
    PromotionRecordReferenceV2,
    PromotionSourceAuthorityV2,
    PromotionSourceKindV2,
    PromotionSourceScopeV2,
    ResolvedArtifactV2,
    ResolvedLicenseV2,
    ResolvedPromotionSourceManifestV2,
)


def _bindings() -> PromotionArtifactBindingsV2:
    def locator(name: str) -> PromotionArtifactLocatorV2:
        return PromotionArtifactLocatorV2("bound-source", name)

    return PromotionArtifactBindingsV2(
        regulation=locator("regulation"),
        target_pool=locator("target-pool"),
        catalog=locator("catalog"),
        ruleset=locator("ruleset"),
        mapping_evidence=locator("mapping"),
        development_construction_corpus=locator("development-construction"),
        external_holdout_construction_corpus=locator("holdout-construction"),
        grounding_assertions=locator("grounding"),
        development_scenario_corpus=locator("development-scenarios"),
        external_holdout_scenario_corpus=locator("holdout-scenarios"),
        timing_evidence=locator("timing"),
    )


def _request(
    root: Path,
    manifest_names: tuple[str, ...] = ("a.json",),
) -> ProductionPromotionRequestV2:
    root.mkdir(parents=True, exist_ok=True)
    for name in manifest_names:
        (root / name).write_text("{}", encoding="utf-8")
    return ProductionPromotionRequestV2(
        artifact_root=root,
        manifest_relative_paths=manifest_names,
        artifacts=_bindings(),
        replay_artifacts=(
            ReplayArtifactBindingV2(
                "scenario-a",
                PromotionArtifactLocatorV2("replay-source", "replay-a"),
            ),
        ),
    )


def _manifest(manifest_id: str, ordinal: int) -> ResolvedPromotionSourceManifestV2:
    license_sha = f"{ordinal:x}" * 64
    source_sha = f"{ordinal + 2:x}" * 64
    license = ResolvedLicenseV2(
        license_id=f"license-{manifest_id}",
        source_manifest_id=manifest_id,
        artifact_id="license",
        artifact_sha256=license_sha,
        record_hash=f"{ordinal + 4:x}" * 64,
        verification_status="test_authoritative",
        license_identifier="TEST-LICENSE",
        license_url=None,
        local_research_allowed=True,
        private_match_allowed=True,
        training_allowed=True,
        redistribution="prohibited",
        commercial_use="prohibited",
    )
    artifacts = (
        ResolvedArtifactV2(
            manifest_id,
            "license",
            PromotionArtifactRoleV2.LICENSE_RECORD,
            f"{manifest_id}/license.json",
            "application/json",
            1,
            license_sha,
        ),
        ResolvedArtifactV2(
            manifest_id,
            "source",
            PromotionArtifactRoleV2.SOURCE_DATA,
            f"{manifest_id}/source.json",
            "application/json",
            1,
            source_sha,
        ),
    )
    return ResolvedPromotionSourceManifestV2(
        schema_version=PROMOTION_SOURCE_SCHEMA_VERSION,
        manifest_id=manifest_id,
        source_kind=PromotionSourceKindV2.TEST_FIXTURE,
        authority=PromotionSourceAuthorityV2.TEST_AUTHORITATIVE,
        title=f"Source {manifest_id}",
        publisher="Compiler tests",
        locator_kind="logical",
        locator_value=f"test/{manifest_id}",
        retrieved_at="2026-07-14T00:00:00+09:00",
        manifest_hash=f"{ordinal + 6:x}" * 64,
        license=license,
        scope=PromotionSourceScopeV2.TEST_AUTHORITATIVE,
        artifacts=artifacts,
        records=(),
    )


def test_request_accepts_the_concrete_path_subclass(tmp_path: Path) -> None:
    request = _request(tmp_path / "artifacts")

    assert isinstance(request.artifact_root, Path)


def test_source_set_resolves_each_manifest_once_and_attaches_verified_records(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(tmp_path / "artifacts", ("a.json", "b.json"))
    manifests = {"a.json": _manifest("manifest-a", 1), "b.json": _manifest("manifest-b", 2)}
    calls: list[str] = []

    def resolve(path, *, artifact_root, record_references=()):
        calls.append(Path(path).name)
        assert record_references == ()
        return manifests[Path(path).name]

    monkeypatch.setattr(
        promotion_compiler,
        "resolve_promotion_source_manifest_v2",
        resolve,
    )
    monkeypatch.setattr(
        promotion_compiler,
        "read_resolved_json_record",
        lambda artifact_root, artifact, reference: {"verified": True},
    )
    reference = PromotionRecordReferenceV2(
        evidence_ref_id="evidence-a",
        source_manifest_id="manifest-a",
        artifact_id="source",
        json_pointer="/record",
        record_sha256="a" * 64,
    )

    resolved = resolve_promotion_source_set_v2(
        request,
        record_references=(reference,),
    )

    assert calls == ["a.json", "b.json"]
    assert resolved.manifest("manifest-a").records[0].reference == reference
    assert resolved.manifest("manifest-b").records == ()


def test_source_set_rejects_non_v2_reference_before_resolution(tmp_path: Path) -> None:
    request = _request(tmp_path / "artifacts")

    with pytest.raises(PromotionCompilationError, match="exact V2"):
        resolve_promotion_source_set_v2(
            request,
            record_references=(object(),),  # type: ignore[arg-type]
        )


def _grounding_assertion(**changes):
    values = {
        "assertion_id": "assertion-a",
        "requirement_ids": ("requirement-a",),
        "capability_ids": ("capability-a",),
        "evidence_kind": "official_primary",
        "ruleset_id": "ruleset-a",
        "ruleset_hash": "1" * 64,
        "catalog_hash": "2" * 64,
        "trace_id": None,
        "trace_hash": None,
        "reference_replay_hash": "6" * 64,
        "initial_state_hash": "3" * 64,
        "choice_sequence_hash": "4" * 64,
        "rng_condition_id": "rng-a",
        "expected_event_slice_hash": "5" * 64,
        "evidence_ref_ids": ("grounding-record",),
        "claimed_verdict": "pass",
    }
    values.update(changes)
    return SimpleNamespace(**values)


def _grounding_context(assertion):
    raw = SimpleNamespace(assertions=(assertion,))
    capability_set = SimpleNamespace(
        grounding_requirements=(SimpleNamespace(requirement_id="requirement-a"),)
    )
    scenarios = SimpleNamespace(
        scenarios=(
            SimpleNamespace(
                capability_id="capability-a",
                initial_state_hash="3" * 64,
                choice_sequence_hash="4" * 64,
                witness_event_hash="5" * 64,
                replay_hash="6" * 64,
            ),
        )
    )
    return raw, capability_set, scenarios


def test_state_check_only_grounding_cannot_pass_without_event_witness() -> None:
    assertion = _grounding_assertion(expected_event_slice_hash=None)
    raw, capability_set, scenarios = _grounding_context(assertion)

    with pytest.raises(PromotionCompilationError, match="witness event hash"):
        promotion_compiler._validate_grounding_scenario_bindings(
            raw,
            capability_set,
            scenarios,
            frozenset({"grounding-record"}),
            ruleset_id="ruleset-a",
        )


def test_grounding_record_must_match_assertion_substance() -> None:
    assertion = _grounding_assertion()
    raw = SimpleNamespace(
        assertions=(assertion,),
        source_manifest_ids=("grounding-source",),
    )
    references = (
        SimpleNamespace(
            evidence_ref_id="grounding-record",
            source_manifest_id="grounding-source",
        ),
    )
    unrelated_mapping_record = {
        "target_key": "dex:0001:form:00:variant:0",
        "catalog_pokemon_id": "pokemon-0001",
        "resolution_status": "resolved",
        "verification_status": "verified",
    }

    with pytest.raises(PromotionCompilationError, match="does not prove"):
        promotion_compiler._validate_grounding_evidence(
            raw,
            {"grounding-record": unrelated_mapping_record},
            references=references,
        )

    exact_record = {
        "assertion_id": assertion.assertion_id,
        "requirement_ids": list(assertion.requirement_ids),
        "capability_ids": list(assertion.capability_ids),
        "evidence_kind": assertion.evidence_kind,
        "ruleset_id": assertion.ruleset_id,
        "ruleset_hash": assertion.ruleset_hash,
        "catalog_hash": assertion.catalog_hash,
        "initial_state_hash": assertion.initial_state_hash,
        "choice_sequence_hash": assertion.choice_sequence_hash,
        "expected_event_slice_hash": assertion.expected_event_slice_hash,
        "claimed_verdict": "pass",
    }
    assert promotion_compiler._validate_grounding_evidence(
        raw,
        {"grounding-record": exact_record},
        references=references,
    ) == frozenset({"grounding-record"})


def _construction_record() -> ConstructionRecord:
    return ConstructionRecord(
        record_id="construction-a",
        record_kind="usage_marginal",
        observed_at="2026-07-14T00:00:00+09:00",
        regulation_id="regulation-a",
        joint_group_id=None,
        target_key="dex:0001:form:00:variant:0",
        entities=(
            ObservedEntity(
                field="pokemon",
                entity_id="pokemon-a",
                status=ObservationStatus.CONFIRMED,
                rate_ppm=1_000_000,
                rank=1,
                evidence_ref_ids=("construction-evidence",),
            ),
        ),
        observed_capabilities=(),
        source_complete=True,
        evidence_ref_ids=("construction-evidence",),
        blockers=(),
        record_hash="7" * 64,
    )


def test_construction_corpus_rejects_unrelated_reused_record() -> None:
    record = _construction_record()
    corpus = SimpleNamespace(
        evidence_refs=(
            SimpleNamespace(
                evidence_ref_id="construction-evidence",
                source_manifest_id="construction-source",
            ),
        ),
        source_manifest_ids=("construction-source",),
        records=(record,),
    )
    mapping_record = {
        "target_key": record.target_key,
        "catalog_pokemon_id": "pokemon-a",
    }

    with pytest.raises(PromotionCompilationError, match="does not prove"):
        promotion_compiler._validate_corpus_evidence(
            corpus,
            {"construction-evidence": mapping_record},
        )

    promotion_compiler._validate_corpus_evidence(
        corpus,
        {"construction-evidence": to_canonical_data(record)},
    )


class _SourceSet:
    def __init__(self, hashes):
        self.hashes = hashes

    def artifact(self, locator):
        return SimpleNamespace(
            sha256=self.hashes[(locator.source_manifest_id, locator.artifact_id)]
        )


def _lineage_case(*, overlap: bool = False, relabel: bool = False):
    dev_scenario_locator = PromotionArtifactLocatorV2("dev-scenario-source", "corpus")
    hold_scenario_locator = PromotionArtifactLocatorV2("hold-scenario-source", "corpus")
    dev_construction_locator = PromotionArtifactLocatorV2("dev-construction-source", "corpus")
    hold_construction_locator = PromotionArtifactLocatorV2("hold-construction-source", "corpus")
    dev_replay = PromotionArtifactLocatorV2("dev-replay-source", "replay")
    hold_replay = PromotionArtifactLocatorV2("hold-replay-source", "replay")
    dev_evidence = SimpleNamespace(
        source_manifest_id="dev-evidence-source",
        artifact_id="record",
    )
    hold_evidence = SimpleNamespace(
        source_manifest_id="hold-evidence-source",
        artifact_id="record",
    )
    request = SimpleNamespace(
        artifacts=SimpleNamespace(
            development_scenario_corpus=dev_scenario_locator,
            external_holdout_scenario_corpus=hold_scenario_locator,
            development_construction_corpus=dev_construction_locator,
            external_holdout_construction_corpus=hold_construction_locator,
        )
    )
    development_construction = SimpleNamespace(
        source_manifest_ids=("dev-evidence-source",),
        evidence_refs=(dev_evidence,),
    )
    holdout_construction = SimpleNamespace(
        source_manifest_ids=("hold-evidence-source",),
        evidence_refs=(hold_evidence,),
    )
    development = SimpleNamespace(
        scenarios=(
            SimpleNamespace(
                scenario_id="dev-a",
                source_lineage_ids=(
                    ("forged-label",)
                    if relabel
                    else (
                        "dev-evidence-source",
                        "dev-replay-source",
                        "dev-scenario-source",
                    )
                ),
            ),
        )
    )
    holdout = SimpleNamespace(
        scenarios=(
            SimpleNamespace(
                scenario_id="hold-a",
                source_lineage_ids=(
                    "hold-evidence-source",
                    "hold-replay-source",
                    "hold-scenario-source",
                ),
            ),
        )
    )
    identities = (
        dev_scenario_locator,
        hold_scenario_locator,
        dev_construction_locator,
        hold_construction_locator,
        dev_replay,
        hold_replay,
        PromotionArtifactLocatorV2("dev-evidence-source", "record"),
        PromotionArtifactLocatorV2("hold-evidence-source", "record"),
    )
    hashes = {
        (value.source_manifest_id, value.artifact_id): f"{index:x}" * 64
        for index, value in enumerate(identities, start=1)
    }
    if overlap:
        hashes[(hold_replay.source_manifest_id, hold_replay.artifact_id)] = hashes[
            (dev_replay.source_manifest_id, dev_replay.artifact_id)
        ]
    return (
        request,
        _SourceSet(hashes),
        development,
        holdout,
        development_construction,
        holdout_construction,
        {"dev-a": dev_replay, "hold-a": hold_replay},
    )


def test_scenario_lineage_is_derived_and_source_artifact_overlap_is_rejected() -> None:
    values = _lineage_case()
    promotion_compiler._validate_scenario_source_lineage(
        request=values[0],
        sources=values[1],
        development_scenarios=values[2],
        external_holdout_scenarios=values[3],
        development_construction=values[4],
        external_holdout_construction=values[5],
        replay_bindings=values[6],
    )

    relabelled = _lineage_case(relabel=True)
    with pytest.raises(PromotionCompilationError, match="lineage differs"):
        promotion_compiler._validate_scenario_source_lineage(
            request=relabelled[0],
            sources=relabelled[1],
            development_scenarios=relabelled[2],
            external_holdout_scenarios=relabelled[3],
            development_construction=relabelled[4],
            external_holdout_construction=relabelled[5],
            replay_bindings=relabelled[6],
        )

    overlapping = _lineage_case(overlap=True)
    with pytest.raises(PromotionCompilationError, match="artifact SHA overlap"):
        promotion_compiler._validate_scenario_source_lineage(
            request=overlapping[0],
            sources=overlapping[1],
            development_scenarios=overlapping[2],
            external_holdout_scenarios=overlapping[3],
            development_construction=overlapping[4],
            external_holdout_construction=overlapping[5],
            replay_bindings=overlapping[6],
        )


def _external_verification(probe_hashes: tuple[str, ...]):
    data = {
        "schema_version": "2.0.0",
        "target_capability_set_hash": "a" * 64,
        "external_scenario_corpus_hash": "b" * 64,
        "construction_gap_report_hash": "c" * 64,
        "supplemental_probe_hashes": list(probe_hashes),
    }
    return ExternalHoldoutVerificationV2(
        schema_version="2.0.0",
        verification_id="external-holdout-verification-" + canonical_hash(data),
        target_capability_set_hash="a" * 64,
        external_scenario_corpus_hash="b" * 64,
        construction_gap_report_hash="c" * 64,
        supplemental_probe_hashes=probe_hashes,
    )


def test_external_holdout_identity_retains_supplemental_probe_hashes() -> None:
    first = _external_verification(("d" * 64,))
    same = _external_verification(("d" * 64,))
    mutated = _external_verification(("e" * 64,))

    assert first.to_json() == same.to_json()
    assert first.report_hash == same.report_hash
    assert first.report_hash != mutated.report_hash
    assert "d" * 64 in first.to_json()
