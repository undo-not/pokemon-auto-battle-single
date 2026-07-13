from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from champions_sim import load_catalog, load_ruleset
from champions_sim.regulations import (
    RehearsalResources,
    RegulationDataError,
    build_coverage_gap_report,
    build_regulation_rehearsal_report,
    diff_regulation_bundles,
    load_regulation_bundle,
    load_regulation_snapshot,
    load_source_manifest_evidence,
    load_target_pool,
)
from scripts.validate_sim01_bundle import validate_document_contract


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "data/fixtures/regulations"
MANIFESTS = ROOT / "data/manifests"
SCHEMAS = ROOT / "data/schemas"


def _bundle(regulation: str, pool: str):
    return load_regulation_bundle(
        FIXTURES / regulation,
        FIXTURES / pool,
        manifest_dir=MANIFESTS,
        repository_root=ROOT,
    )


def _sim01():
    return (
        load_catalog(ROOT / "data/fixtures/sim01_catalog.json"),
        load_ruleset(ROOT / "data/fixtures/sim01_ruleset.json"),
    )


def _delta_outputs():
    before = _bundle("m-b-current.json", "m-b-eligible-pokemon.json")
    after = _bundle(
        "m-c-synthetic-delta.json", "m-c-eligible-pokemon-synthetic.json"
    )
    catalog, ruleset = _sim01()
    before_report = build_coverage_gap_report(before, catalog, ruleset)
    after_report = build_coverage_gap_report(after, catalog, ruleset)
    diff = diff_regulation_bundles(before, after, before_report, after_report)
    return before, after, before_report, after_report, diff


def _rehearsal_report(*, t_decision: str = "2026-07-13T06:00:00+09:00"):
    before, after, before_report, after_report, diff = _delta_outputs()
    catalog, ruleset = _sim01()
    return build_regulation_rehearsal_report(
        report_id="sim02-synthetic-delta-rehearsal-20260713",
        rehearsal_kind="synthetic_internal",
        t0="2026-07-13T00:00:00+09:00",
        t_decision=t_decision,
        before_bundle=before,
        after_bundle=after,
        before_coverage=before_report,
        after_coverage=after_report,
        diff=diff,
        catalog=catalog,
        ruleset=ruleset,
        resources=RehearsalResources(
            measurement_status="synthetic_fixture",
            compute_environment="local-windows-python-3.10-single-process",
            process_count=1,
            max_parallel_workers=1,
            network_fetch_count=0,
            execution_minutes=15,
            manual_work_minutes=90,
            external_wait_minutes=0,
        ),
        silent_fallback_count=0,
        rehearsal_input_hash=(
            hashlib.sha256(
                (FIXTURES / "synthetic-rehearsal-input.json").read_bytes()
            ).hexdigest()
        ),
        report_source_manifest_ids=("sim02-regulation-rehearsal-report",),
        notes=(
            "t0, t_decision, and resource values are sealed synthetic fixture inputs, not measurements of elapsed wall-clock work in this repository.",
            "Operational success means the pipeline emitted a reasoned NO-GO within the rehearsal SLA; it is not a deployable candidate success.",
            "No network acquisition or external wait is simulated in this fixture.",
        ),
    )


def test_archived_current_and_synthetic_regulations_are_explicitly_versioned() -> None:
    archived = load_regulation_snapshot(FIXTURES / "m-a-archived.json")
    current = load_regulation_snapshot(FIXTURES / "m-b-current.json")
    synthetic = load_regulation_snapshot(FIXTURES / "m-c-synthetic-delta.json")

    assert (archived.regulation_id, archived.status) == ("M-A", "archived")
    assert archived.period.end_at == "2026-06-17T10:59:00+09:00"
    assert (current.regulation_id, current.status) == ("M-B", "current")
    assert current.period.end_at == "2026-09-02T10:59:00+09:00"
    assert current.required_mechanics == ("mega_evolution",)
    assert synthetic.status == "synthetic"
    assert synthetic.verification_status == "synthetic_rehearsal"
    assert synthetic.published_at is None


def test_official_m_b_target_pool_identity_and_count_are_fixed() -> None:
    path = FIXTURES / "m-b-eligible-pokemon.json"
    pool = load_target_pool(path)

    assert pool.regulation_id == "M-B"
    assert pool.expected_member_count == len(pool.members) == 235
    assert pool.members[0].label == "No.0003 フシギバナ"
    assert pool.members[-1].label == "No.1019 カミツオロチ"
    assert len({member.target_key for member in pool.members}) == 235
    canonical = [
        {
            "national_dex_no": member.national_dex_no,
            "form_code": member.form_code,
            "variant_code": member.variant_code,
            "label": member.label,
        }
        for member in pool.members
    ]
    payload = json.dumps(
        canonical, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    assert hashlib.sha256(payload).hexdigest() == (
        "8110141f34c226c9dcff8ff58e83b30ae9f4a8efdd3e51cf0eace1853590f6c1"
    )


def test_bundle_verifies_all_source_artifacts_and_license_restrictions() -> None:
    bundle = _bundle("m-b-current.json", "m-b-eligible-pokemon.json")

    assert [item.manifest_id for item in bundle.manifests] == [
        "pokemon-home-regulation-m-b-current"
    ]
    assert bundle.restricted_source_manifest_ids == (
        "pokemon-home-regulation-m-b-current",
    )
    evidence = bundle.manifests[0]
    assert evidence.license_status == "unverified"
    assert evidence.local_research_only is True
    assert evidence.redistribution == "prohibited"
    assert set(evidence.declared_artifact_paths) == {
        "data/fixtures/regulations/m-b-current.json",
        "data/fixtures/regulations/m-b-eligible-pokemon.json",
    }


def test_current_coverage_uses_full_235_denominator_and_fails_closed() -> None:
    bundle = _bundle("m-b-current.json", "m-b-eligible-pokemon.json")
    catalog, ruleset = _sim01()
    report = build_coverage_gap_report(bundle, catalog, ruleset)

    assert report.eligible_member_count == 235
    assert report.mapped_member_count == 0
    assert report.covered_member_count == 0
    assert report.covered_pokemon_ids == ()
    assert len(report.unmapped_target_keys) == 235
    assert report.missing_pokemon_ids == ()
    assert report.unsupported_mechanics == ("mega_evolution",)
    assert report.coverage_complete is False
    assert "unsupported_mechanic:mega_evolution" in report.blocking_reasons
    assert len(report.blocking_reasons) == 236


def test_synthetic_delta_diff_names_rule_pool_and_coverage_changes() -> None:
    _, _, _, _, diff = _delta_outputs()

    assert diff.added_mechanics == ("terrain",)
    assert diff.removed_mechanics == ("mega_evolution",)
    assert diff.added_target_keys == ("dex:9999:form:00:variant:0",)
    assert diff.removed_target_keys == ("dex:1019:form:00:variant:0",)
    changes = {item.field: (item.before, item.after) for item in diff.changed_fields}
    assert changes == {
        "period.start_date": ("2026-06-17", "2026-09-02"),
        "period.end_at": (
            "2026-09-02T10:59:00+09:00",
            "2026-09-23T10:59:00+09:00",
        ),
        "battle_timer.turn_seconds": (45, 40),
    }
    assert "unsupported_mechanic:terrain" in diff.added_blocking_reasons
    assert "unsupported_mechanic:mega_evolution" in diff.resolved_blocking_reasons
    assert diff.requires_simulator_update is True
    assert set(diff.source_manifest_ids) == {
        "pokemon-home-regulation-m-b-current",
        "sim02-regulation-delta-rehearsal",
    }


def test_sealed_synthetic_rehearsal_issues_reasoned_no_go_within_48_hours() -> None:
    report = _rehearsal_report()

    assert report.outcome == "no_go"
    assert report.decision_lead_time_seconds == 6 * 60 * 60
    assert report.within_48_hours is True
    assert report.operational_rehearsal_success is True
    assert report.deployable_candidate_success is False
    assert report.target_pool_execution_coverage_rate_ppm is None
    assert report.verified_grounding_conformance_rate_ppm is None
    assert report.silent_fallback_count == 0
    assert report.provisional_decision_ids == ("PD-008",)
    assert "synthetic_input_not_deployable" in report.no_go_reason_codes
    assert "unsupported_mechanic:terrain" in report.no_go_reason_codes
    assert "target_pool_execution_coverage_unmeasured" in report.no_go_reason_codes
    assert "verified_grounding_conformance_unmeasured" in report.no_go_reason_codes
    assert report.resources.measurement_status == "synthetic_fixture"
    assert report.resources.external_wait_minutes == 0
    assert report.candidate_bundle_hash is None
    assert "sim02-regulation-rehearsal-report" in report.source_manifest_ids
    assert {value.artifact_id for value in report.sealed_input_hashes} == {
        "before_regulation",
        "before_target_pool",
        "after_regulation",
        "after_target_pool",
        "after_coverage_report",
        "catalog",
        "ruleset",
        "regulation_diff",
        "rehearsal_input",
    }
    golden = ROOT / "data/golden/sim02-regulation-rehearsal-no-go.json"
    assert golden.read_text(encoding="utf-8") == report.to_json() + "\n"
    report_manifest = load_source_manifest_evidence(
        "sim02-regulation-rehearsal-report",
        manifest_dir=MANIFESTS,
        repository_root=ROOT,
    )
    assert set(report_manifest.declared_artifact_paths) == {
        "data/fixtures/regulations/synthetic-rehearsal-input.json",
        "data/golden/sim02-regulation-rehearsal-no-go.json",
    }


def test_rehearsal_after_48_hours_is_not_operational_success() -> None:
    report = _rehearsal_report(t_decision="2026-07-15T00:00:01+09:00")

    assert report.decision_lead_time_seconds == 48 * 60 * 60 + 1
    assert report.within_48_hours is False
    assert report.operational_rehearsal_success is False
    assert report.deployable_candidate_success is False


def test_rehearsal_rejects_negative_time_and_unsealed_diff_hash() -> None:
    before, after, before_report, after_report, diff = _delta_outputs()
    catalog, ruleset = _sim01()
    resources = RehearsalResources(
        measurement_status="synthetic_fixture",
        compute_environment="test",
        process_count=1,
        max_parallel_workers=1,
        network_fetch_count=0,
        execution_minutes=0,
        manual_work_minutes=0,
        external_wait_minutes=0,
    )
    common = {
        "report_id": "negative-rehearsal",
        "rehearsal_kind": "synthetic_internal",
        "before_bundle": before,
        "after_bundle": after,
        "before_coverage": before_report,
        "after_coverage": after_report,
        "catalog": catalog,
        "ruleset": ruleset,
        "resources": resources,
        "silent_fallback_count": 0,
        "rehearsal_input_hash": hashlib.sha256(
            (FIXTURES / "synthetic-rehearsal-input.json").read_bytes()
        ).hexdigest(),
    }
    with pytest.raises(ValueError, match="must not precede"):
        build_regulation_rehearsal_report(
            **common,
            t0="2026-07-13T01:00:00+09:00",
            t_decision="2026-07-13T00:00:00+09:00",
            diff=diff,
        )

    unsealed = replace(
        diff,
        after=replace(diff.after, regulation_hash="0" * 64),
    )
    with pytest.raises(ValueError, match="diff does not match"):
        build_regulation_rehearsal_report(
            **common,
            t0="2026-07-13T00:00:00+09:00",
            t_decision="2026-07-13T01:00:00+09:00",
            diff=unsealed,
        )


def test_rehearsal_rejects_forged_before_reference_and_coverage_candidate() -> None:
    before, after, before_report, after_report, diff = _delta_outputs()
    catalog, ruleset = _sim01()
    common = {
        "report_id": "forgery-rehearsal",
        "rehearsal_kind": "synthetic_internal",
        "t0": "2026-07-13T00:00:00+09:00",
        "t_decision": "2026-07-13T01:00:00+09:00",
        "before_bundle": before,
        "after_bundle": after,
        "before_coverage": before_report,
        "after_coverage": after_report,
        "catalog": catalog,
        "ruleset": ruleset,
        "resources": RehearsalResources(
            measurement_status="synthetic_fixture",
            compute_environment="test",
            process_count=1,
            max_parallel_workers=1,
            network_fetch_count=0,
            execution_minutes=0,
            manual_work_minutes=0,
            external_wait_minutes=0,
        ),
        "silent_fallback_count": 0,
        "rehearsal_input_hash": hashlib.sha256(
            (FIXTURES / "synthetic-rehearsal-input.json").read_bytes()
        ).hexdigest(),
    }
    forged_before = replace(
        diff,
        before=replace(diff.before, regulation_hash="0" * 64),
    )
    with pytest.raises(ValueError, match="diff does not match"):
        build_regulation_rehearsal_report(**common, diff=forged_before)

    forged_coverage = replace(
        after_report,
        mapped_member_count=after_report.eligible_member_count,
        covered_member_count=after_report.eligible_member_count,
        unmapped_target_keys=(),
        unsupported_mechanics=(),
        blocking_reasons=(),
        coverage_complete=True,
    )
    with pytest.raises(ValueError, match="coverage report does not match"):
        build_regulation_rehearsal_report(
            **{**common, "after_coverage": forged_coverage},
            diff=diff,
        )

    with pytest.raises(ValueError, match="only supports synthetic_internal"):
        build_regulation_rehearsal_report(
            **{**common, "rehearsal_kind": "live"},
            diff=diff,
        )

    valid_report = _rehearsal_report()
    with pytest.raises(ValueError, match="fail-closed NO-GO only"):
        replace(
            valid_report,
            outcome="candidate",
            candidate_bundle_hash="a" * 64,
            no_go_reason_codes=(),
            deployable_candidate_success=True,
        )


def test_fixtures_and_generated_outputs_match_recursive_schemas() -> None:
    fixture_cases = (
        ("m-a-archived.json", "regulation-snapshot.schema.json"),
        ("m-b-current.json", "regulation-snapshot.schema.json"),
        ("m-c-synthetic-delta.json", "regulation-snapshot.schema.json"),
        ("m-b-eligible-pokemon.json", "target-pool.schema.json"),
        ("m-c-eligible-pokemon-synthetic.json", "target-pool.schema.json"),
        ("synthetic-rehearsal-input.json", "regulation-rehearsal-input.schema.json"),
    )
    for fixture_name, schema_name in fixture_cases:
        document = json.loads((FIXTURES / fixture_name).read_text(encoding="utf-8"))
        schema = json.loads((SCHEMAS / schema_name).read_text(encoding="utf-8"))
        validate_document_contract(document, schema, fixture_name)

    _, _, before_report, _, diff = _delta_outputs()
    validate_document_contract(
        json.loads(before_report.to_json()),
        json.loads((SCHEMAS / "coverage-gap.schema.json").read_text(encoding="utf-8")),
        "coverage report",
    )
    validate_document_contract(
        json.loads(diff.to_json()),
        json.loads((SCHEMAS / "regulation-diff.schema.json").read_text(encoding="utf-8")),
        "regulation diff",
    )
    rehearsal = _rehearsal_report()
    validate_document_contract(
        json.loads(rehearsal.to_json()),
        json.loads(
            (SCHEMAS / "regulation-rehearsal-report.schema.json").read_text(
                encoding="utf-8"
            )
        ),
        "regulation rehearsal report",
    )

    manifest_schema = json.loads(
        (SCHEMAS / "source-manifest.schema.json").read_text(encoding="utf-8")
    )
    for name in (
        "pokemon-home-regulation-m-a-archived.json",
        "pokemon-home-regulation-m-b-current.json",
        "sim02-regulation-delta-rehearsal.json",
        "sim02-regulation-rehearsal-report.json",
    ):
        validate_document_contract(
            json.loads((MANIFESTS / name).read_text(encoding="utf-8")),
            manifest_schema,
            name,
        )


def test_missing_fields_wrong_counts_and_manifest_drift_fail_closed(tmp_path: Path) -> None:
    raw = json.loads((FIXTURES / "m-b-current.json").read_text(encoding="utf-8"))
    del raw["battle_timer"]
    invalid_regulation = tmp_path / "missing.json"
    invalid_regulation.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(RegulationDataError, match="missing=.*battle_timer"):
        load_regulation_snapshot(invalid_regulation)

    pool_raw = json.loads(
        (FIXTURES / "m-b-eligible-pokemon.json").read_text(encoding="utf-8")
    )
    pool_raw["expected_member_count"] = 234
    invalid_pool = tmp_path / "count.json"
    invalid_pool.write_text(json.dumps(pool_raw), encoding="utf-8")
    with pytest.raises(RegulationDataError, match="member count"):
        load_target_pool(invalid_pool)

    manifest_raw = json.loads(
        (MANIFESTS / "pokemon-home-regulation-m-b-current.json").read_text(
            encoding="utf-8"
        )
    )
    manifest_raw["artifacts"][0]["sha256"] = "sha256:" + "0" * 64
    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    (manifest_dir / "pokemon-home-regulation-m-b-current.json").write_text(
        json.dumps(manifest_raw), encoding="utf-8"
    )
    with pytest.raises(RegulationDataError, match="sha256 mismatch"):
        load_regulation_bundle(
            FIXTURES / "m-b-current.json",
            FIXTURES / "m-b-eligible-pokemon.json",
            manifest_dir=manifest_dir,
            repository_root=ROOT,
        )

    current_manifest = MANIFESTS / "pokemon-home-regulation-m-b-current.json"
    delta_manifest = MANIFESTS / "sim02-regulation-delta-rehearsal.json"
    synthetic_manifest_dir = tmp_path / "synthetic-manifests"
    synthetic_manifest_dir.mkdir()
    (synthetic_manifest_dir / current_manifest.name).write_bytes(
        current_manifest.read_bytes()
    )
    delta_raw = json.loads(delta_manifest.read_text(encoding="utf-8"))
    rehearsal_artifact = next(
        value
        for value in delta_raw["artifacts"]
        if value["artifact_id"] == "sim02-regulation-rehearsal-input"
    )
    rehearsal_artifact["sha256"] = "sha256:" + "f" * 64
    (synthetic_manifest_dir / delta_manifest.name).write_text(
        json.dumps(delta_raw), encoding="utf-8"
    )
    with pytest.raises(RegulationDataError, match="sha256 mismatch"):
        load_regulation_bundle(
            FIXTURES / "m-c-synthetic-delta.json",
            FIXTURES / "m-c-eligible-pokemon-synthetic.json",
            manifest_dir=synthetic_manifest_dir,
            repository_root=ROOT,
        )
