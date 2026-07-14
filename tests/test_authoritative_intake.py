from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any, Callable

import pytest

import champions_sim.authoritative.compiler as authoritative_compiler
from scripts import build_m_b_authoritative_intake as m_b_cli

from champions_sim.authoritative import (
    AuthoritativeIntakeCompilation,
    AuthoritativeIntakeConfig,
    AuthoritativeIntakeError,
    canonical_sha256,
    compile_authoritative_intake,
    load_source_acquisition_plan,
    load_source_policy_registry,
    write_authoritative_intake_documents,
)
from champions_sim.intake import CatalogIntakePaths, CatalogIntakeProfile
from scripts.validate_sim01_bundle import validate_document_contract


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "data/fixtures/intake/synthetic_mini"
SOURCE_LOCK = ROOT / "data/manifests/catalog-intake-synthetic.json"
SCHEMA_ROOT = ROOT / "data/schemas"
PROFILE = CatalogIntakeProfile(
    profile_id="authoritative-synthetic-mini",
    regulation_id="TEST-B",
    regulation_revision="synthetic-v1",
    expected_target_count=3,
    expected_usage_count=2,
)
PATHS = CatalogIntakePaths(target_pool="target_pool.json")


@dataclass(frozen=True, slots=True)
class _AuthoritativeFixture:
    repository: Path
    plan_path: Path
    policy_path: Path
    raw_payload_path: Path
    raw_manifest_path: Path
    config: AuthoritativeIntakeConfig

    def compile(self) -> AuthoritativeIntakeCompilation:
        return compile_authoritative_intake(self.config)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _seal(value: dict[str, Any], hash_key: str) -> dict[str, Any]:
    unsigned = {key: item for key, item in value.items() if key != hash_key}
    return {**unsigned, hash_key: canonical_sha256(unsigned)}


def _build_fixture(tmp_path: Path) -> _AuthoritativeFixture:
    repository = tmp_path / "repository"
    shutil.copytree(FIXTURE, repository)

    target_pool_path = repository / "target_pool.json"
    target_payload = target_pool_path.read_bytes()
    target_manifest_path = (
        repository / "data/manifests/synthetic-catalog-intake.json"
    )
    _write_json(
        target_manifest_path,
        {
            "schema_version": "1.0.0",
            "manifest_id": "synthetic-catalog-intake",
            "artifacts": [
                {
                    "artifact_id": "synthetic-target-pool",
                    "logical_path": "target_pool.json",
                    "media_type": "application/json",
                    "byte_size": len(target_payload),
                    "sha256": "sha256:"
                    + hashlib.sha256(target_payload).hexdigest(),
                    "record_count": 3,
                }
            ],
            "scope": {
                "regulation_ids": ["TEST-B"],
                "entity_types": ["pokemon"],
                "language": "und",
            },
            "trust": {
                "authority": "synthetic",
                "verification_status": "fixture_only",
            },
        },
    )
    target_manifest_payload = target_manifest_path.read_bytes()

    raw_payload_path = repository / "data/raw/synthetic/payload.json"
    _write_json(
        raw_payload_path,
        {
            "source_id": "synthetic-source",
            "records": [{"entity_id": "synthetic:1", "value": "fixture-only"}],
        },
    )
    payload = raw_payload_path.read_bytes()
    raw_manifest_path = repository / "data/raw/synthetic/manifest.json"
    _write_json(
        raw_manifest_path,
        {
            "source_id": "synthetic-source",
            "results": [
                {
                    "saved_to": "data/raw/synthetic/payload.json",
                    "bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            ],
        },
    )

    policy = _seal(
        {
            "schema_version": "1.0.0",
            "registry_id": "synthetic-policy-register-v1",
            "reviewed_on": "2026-07-14",
            "authorization_status": "not_authorization",
            "policies": [
                {
                    "policy_id": "synthetic-restricted-local",
                    "source_group": "synthetic-fixture",
                    "source_ids": ["synthetic-source", "synthetic_moves"],
                    "review_status": "review_required",
                    "evidence_urls": ["https://example.invalid/synthetic-policy"],
                    "decision_basis": "Synthetic negative-permission fixture.",
                    "collection_status": "manual_reference_only",
                    "candidate_use": "restricted_local",
                    "private_match_use": "review_required",
                    "training_use": "review_required",
                    "redistribution": "prohibited",
                    "production_promotion": "blocked",
                    "notes": "No permission is inferred from local availability.",
                }
            ],
        },
        "registry_hash",
    )
    policy_path = repository / "source-policy.json"
    _write_json(policy_path, policy)

    plan = _seal(
        {
            "schema_version": "1.0.0",
            "plan_id": "synthetic-authoritative-intake-v1",
            "regulation_id": "TEST-B",
            "target_pool_path": "target_pool.json",
            "target_source_manifests": [
                {
                    "manifest_id": "synthetic-catalog-intake",
                    "relative_path": (
                        "data/manifests/synthetic-catalog-intake.json"
                    ),
                    "sha256": hashlib.sha256(
                        target_manifest_payload
                    ).hexdigest(),
                    "required_authority": "synthetic",
                }
            ],
            "expected_target_count": 3,
            "policy_registry_id": policy["registry_id"],
            "routes": [
                {
                    "route_id": "synthetic-local-route",
                    "root_kind": "legacy",
                    "source_kind": "synthetic_fixture",
                    "semantic_authority": "private_observation",
                    "source_ids": ["synthetic-source", "synthetic_moves"],
                    "locators": ["https://example.invalid/synthetic-source"],
                    "policy_id": "synthetic-restricted-local",
                    "candidate_roles": ["catalog_reference"],
                    "evidence_files": [
                        {
                            "artifact_id": "synthetic-raw-manifest",
                            "role": "raw_manifest",
                            "relative_path": "data/raw/synthetic/manifest.json",
                            "required": True,
                            "expected_source_id": "synthetic-source",
                        }
                    ],
                    "raw_inventories": [
                        {
                            "inventory_id": "synthetic-raw-json",
                            "relative_path": "data/raw/synthetic",
                            "suffixes": [".json"],
                            "expected_min_files": 2,
                        }
                    ],
                    "derived_artifacts": [
                        {
                            "artifact_id": "synthetic-derived-moves",
                            "relative_path": "data/processed/moves.json",
                            "record_pointer": "/items",
                            "expected_min_records": 2,
                            "expected_source": "synthetic_moves",
                        }
                    ],
                }
            ],
        },
        "plan_hash",
    )
    plan_path = repository / "source-acquisition-plan.json"
    _write_json(plan_path, plan)

    return _AuthoritativeFixture(
        repository=repository,
        plan_path=plan_path,
        policy_path=policy_path,
        raw_payload_path=raw_payload_path,
        raw_manifest_path=raw_manifest_path,
        config=AuthoritativeIntakeConfig(
            repository_root=repository,
            legacy_root=repository,
            plan_path=plan_path,
            policy_registry_path=policy_path,
            source_lock_path=SOURCE_LOCK,
            intake_paths=PATHS,
            intake_profile=PROFILE,
        ),
    )


@pytest.fixture
def authoritative_fixture(tmp_path: Path) -> _AuthoritativeFixture:
    return _build_fixture(tmp_path)


def _blocker_codes(compilation: AuthoritativeIntakeCompilation) -> set[str]:
    return {value["code"] for value in compilation.assessment["blockers"]}


def test_compilation_is_deterministic_complete_no_go_and_not_authorization(
    authoritative_fixture: _AuthoritativeFixture,
) -> None:
    first = authoritative_fixture.compile()
    second = authoritative_fixture.compile()

    assert first.compilation_hash == second.compilation_hash
    assert first.document_map == second.document_map
    assert first.to_json() == second.to_json()
    source_lock_hash = hashlib.sha256(SOURCE_LOCK.read_bytes()).hexdigest()
    assert first.source_lock_hash == source_lock_hash
    assert first.mapping_workbench["source_lock_hash"] == source_lock_hash
    assert first.summary_data()["source_lock_hash"] == source_lock_hash
    assert first.mapping_workbench["denominator_final"] is False
    assert first.regulation_revision == "synthetic-v1"
    assert first.target_source_manifest_ids == ("synthetic-catalog-intake",)
    assert first.summary_data()["regulation_revision"] == "synthetic-v1"
    assert first.mapping_workbench["summary"]["target_member_count"] == 3
    assert len(first.mapping_workbench["members"]) == 3

    assessment = first.assessment
    assert assessment["summary"]["decision"] == "NO-GO"
    assert assessment["summary"]["candidate_for_production_promotion"] is False
    assert assessment["summary"]["fixed_target_denominator"] == 3
    assert assessment["summary"]["blocker_enumeration_complete"] is True
    assert assessment["authorization_status"] == "not_authorization"
    assert first.summary_data()["production_materialization_emitted"] is False
    assert all(
        document["authorization_status"] == "not_authorization"
        for document in first.document_map.values()
    )

    route = first.source_review["routes"][0]
    assert route["acquisition_integrity_status"] == "complete"
    assert route["raw_manifest_audits"][0]["sealed_result_count"] == 1
    assert route["production_promotable"] is False
    assert first.source_review["network_io_performed"] is False
    assert first.catalog_workbench["payload_policy"] == "restricted_local_git_external"


def test_assessment_enumerates_rights_mapping_and_catalog_field_gaps(
    authoritative_fixture: _AuthoritativeFixture,
) -> None:
    compilation = authoritative_fixture.compile()
    assessment = compilation.assessment
    blockers = assessment["blockers"]
    summary = assessment["summary"]
    codes = _blocker_codes(compilation)

    expected_rights_codes = {
        "source_policy_review_unresolved",
        "source_collection_not_approved",
        "source_candidate_use_restricted",
        "source_private_match_use_not_allowed",
        "source_training_use_not_allowed",
        "source_redistribution_prohibited",
        "source_production_promotion_blocked",
    }
    assert expected_rights_codes <= codes
    assert "target_denominator_authority_unresolved" in codes
    assert sum(value["code"] == "mapping_permission_unresolved" for value in blockers) == 3

    catalog = compilation.catalog_workbench
    assert all(
        entity["fields"]["base_stats"]["status"] == "missing"
        for entity in catalog["species"]
    )
    assert all(
        entity["fields"]["priority"]["status"] == "missing"
        for entity in catalog["moves"]
    )
    for group in ("moves", "abilities", "items"):
        assert all(
            entity["fields"]["structured_effect"]["status"]
            == "unknown_semantics"
            for entity in catalog[group]
        )
    assert any(
        value["code"] == "catalog_field_missing"
        and value["subject"].endswith(":base_stats")
        for value in blockers
    )
    assert any(
        value["code"] == "catalog_field_missing"
        and value["subject"].endswith(":priority")
        for value in blockers
    )
    assert any(
        value["code"] == "catalog_field_unknown_semantics"
        and value["subject"].endswith(":structured_effect")
        for value in blockers
    )

    code_counts = Counter(value["code"] for value in blockers)
    stage_counts = Counter(value["stage"] for value in blockers)
    assert summary["blocker_count"] == len(blockers)
    assert summary["code_blocker_counts"] == dict(sorted(code_counts.items()))
    assert summary["stage_blocker_counts"] == dict(sorted(stage_counts.items()))
    assert len(
        {
            (
                value["stage"],
                value["code"],
                value["subject"],
                value["evidence_required"],
                value["restart_condition"],
            )
            for value in blockers
        }
    ) == len(blockers)
    source_blockers = {
        (value["stage"], value["code"], value["subject"])
        for value in compilation.source_review["blockers"]
    }
    assessment_blockers = {
        (value["stage"], value["code"], value["subject"])
        for value in blockers
    }
    assert source_blockers <= assessment_blockers


def test_content_addressed_writer_is_idempotent_and_detects_collision(
    authoritative_fixture: _AuthoritativeFixture,
    tmp_path: Path,
) -> None:
    compilation = authoritative_fixture.compile()
    output_root = tmp_path / "generated"

    first = write_authoritative_intake_documents(compilation, output_root)
    first_payloads = {
        path.name: path.read_bytes() for path in sorted(first.iterdir())
    }
    second = write_authoritative_intake_documents(compilation, output_root)

    assert first == second == output_root / compilation.compilation_hash
    assert set(first_payloads) == {
        *compilation.document_map,
        "authoritative-intake-compilation.json",
    }
    assert len(first_payloads) == 5
    assert {
        path.name: path.read_bytes() for path in sorted(second.iterdir())
    } == first_payloads

    collision = first / "authoritative-intake-assessment.json"
    collision.write_bytes(collision.read_bytes() + b" ")
    with pytest.raises(AuthoritativeIntakeError, match="output collision"):
        write_authoritative_intake_documents(compilation, output_root)


def test_writer_revalidates_nested_documents_before_materialization(
    authoritative_fixture: _AuthoritativeFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compilation = authoritative_fixture.compile()
    assessment = compilation.assessment
    assert isinstance(assessment, dict)
    assessment["authorization_status"] = "authorized"
    assessment["summary"]["decision"] = "GO"
    assessment["summary"]["candidate_for_production_promotion"] = True
    assessment["assessment_hash"] = canonical_sha256(
        {key: value for key, value in assessment.items() if key != "assessment_hash"}
    )

    with pytest.raises(AuthoritativeIntakeError, match="not_authorization"):
        write_authoritative_intake_documents(compilation, tmp_path / "generated")
    assert not (tmp_path / "generated" / compilation.compilation_hash).exists()

    compilation = authoritative_fixture.compile()
    original_snapshot = AuthoritativeIntakeCompilation.validated_snapshot

    def mutate_after_snapshot(
        value: AuthoritativeIntakeCompilation,
    ) -> AuthoritativeIntakeCompilation:
        snapshot = original_snapshot(value)
        assert isinstance(value.assessment, dict)
        value.assessment["authorization_status"] = "authorized"
        value.assessment["summary"]["decision"] = "GO"
        value.assessment["summary"]["candidate_for_production_promotion"] = True
        return snapshot

    monkeypatch.setattr(
        AuthoritativeIntakeCompilation,
        "validated_snapshot",
        mutate_after_snapshot,
    )
    destination = write_authoritative_intake_documents(
        compilation,
        tmp_path / "race-output",
    )
    written = _read_json(destination / "authoritative-intake-assessment.json")
    assert written["authorization_status"] == "not_authorization"
    assert written["summary"]["decision"] == "NO-GO"
    assert written["summary"]["candidate_for_production_promotion"] is False


def test_writer_publishes_no_partial_final_directory_on_failure(
    authoritative_fixture: _AuthoritativeFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compilation = authoritative_fixture.compile()
    output_root = tmp_path / "generated"
    destination = output_root / compilation.compilation_hash
    original_open = Path.open

    def fail_second_document(path: Path, *args: Any, **kwargs: Any):
        if (
            path.name == "authoritative-mapping-workbench.json"
            and path.parent.name.startswith(f".{compilation.compilation_hash}.tmp-")
        ):
            raise OSError("injected staging failure")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_second_document)
    with pytest.raises(OSError, match="injected staging failure"):
        write_authoritative_intake_documents(compilation, output_root)

    assert not destination.exists()
    assert list(output_root.iterdir()) == []


@pytest.mark.parametrize(
    ("loader", "path_attribute", "hash_key", "mutate"),
    [
        (
            load_source_acquisition_plan,
            "plan_path",
            "plan_hash",
            lambda value: value.__setitem__("expected_target_count", 4),
        ),
        (
            load_source_policy_registry,
            "policy_path",
            "registry_hash",
            lambda value: value["policies"][0].__setitem__("notes", "tampered"),
        ),
    ],
)
def test_plan_and_policy_self_hashes_reject_unsigned_mutation(
    authoritative_fixture: _AuthoritativeFixture,
    loader: Callable[[Path], dict[str, Any]],
    path_attribute: str,
    hash_key: str,
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    path = getattr(authoritative_fixture, path_attribute)
    original = loader(path)
    assert original[hash_key] == canonical_sha256(
        {key: value for key, value in original.items() if key != hash_key}
    )

    mutate(original)
    _write_json(path, original)
    with pytest.raises(AuthoritativeIntakeError, match=f"{hash_key} mismatch"):
        loader(path)


@pytest.mark.parametrize(
    ("loader", "path_attribute"),
    [
        (load_source_acquisition_plan, "plan_path"),
        (load_source_policy_registry, "policy_path"),
    ],
)
def test_strict_json_loaders_reject_duplicate_keys(
    authoritative_fixture: _AuthoritativeFixture,
    loader: Callable[[Path], dict[str, Any]],
    path_attribute: str,
) -> None:
    path = getattr(authoritative_fixture, path_attribute)
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        '"schema_version": "1.0.0"',
        '"schema_version": "1.0.0",\n  "schema_version": "1.0.0"',
        1,
    )
    path.write_text(text, encoding="utf-8", newline="\n")

    with pytest.raises(AuthoritativeIntakeError, match="duplicate key schema_version"):
        loader(path)


def test_plan_rejects_path_escape_even_when_resealed(
    authoritative_fixture: _AuthoritativeFixture,
) -> None:
    plan = _read_json(authoritative_fixture.plan_path)
    plan["routes"][0]["evidence_files"][0]["relative_path"] = "../outside.json"
    _write_json(authoritative_fixture.plan_path, _seal(plan, "plan_hash"))

    with pytest.raises(AuthoritativeIntakeError, match="unsafe relative path"):
        load_source_acquisition_plan(authoritative_fixture.plan_path)


def test_plan_rejects_empty_evidence_route_and_windows_ads_path(
    authoritative_fixture: _AuthoritativeFixture,
) -> None:
    plan = _read_json(authoritative_fixture.plan_path)
    plan["routes"][0]["evidence_files"] = []
    _write_json(authoritative_fixture.plan_path, _seal(plan, "plan_hash"))
    with pytest.raises(AuthoritativeIntakeError, match="must not be empty"):
        load_source_acquisition_plan(authoritative_fixture.plan_path)

    fixture = _build_fixture(authoritative_fixture.repository.parent / "ads")
    plan = _read_json(fixture.plan_path)
    plan["routes"][0]["evidence_files"][0]["relative_path"] = (
        "data/raw/synthetic/manifest.json:shadow"
    )
    _write_json(fixture.plan_path, _seal(plan, "plan_hash"))
    with pytest.raises(AuthoritativeIntakeError, match="unsafe relative path"):
        load_source_acquisition_plan(fixture.plan_path)

    fixture = _build_fixture(authoritative_fixture.repository.parent / "binding")
    plan = _read_json(fixture.plan_path)
    plan["routes"][0]["derived_artifacts"][0]["expected_source"] = (
        "unreviewed-source"
    )
    _write_json(fixture.plan_path, _seal(plan, "plan_hash"))
    with pytest.raises(AuthoritativeIntakeError, match="belong to the route"):
        load_source_acquisition_plan(fixture.plan_path)

    fixture = _build_fixture(authoritative_fixture.repository.parent / "coverage")
    plan = _read_json(fixture.plan_path)
    plan["routes"][0]["source_ids"] = [
        "phantom-source",
        *plan["routes"][0]["source_ids"],
    ]
    plan["routes"][0]["evidence_files"].append(
        {
            "artifact_id": "zz-phantom-evidence",
            "role": "source_config",
            "relative_path": "missing/phantom.json",
            "required": False,
            "expected_source_id": "phantom-source",
        }
    )
    _write_json(fixture.plan_path, _seal(plan, "plan_hash"))
    with pytest.raises(AuthoritativeIntakeError, match="lack declared evidence coverage"):
        load_source_acquisition_plan(fixture.plan_path)


def test_plan_rejects_unknown_evidence_role_and_incomplete_external_chain(
    authoritative_fixture: _AuthoritativeFixture,
) -> None:
    plan = _read_json(authoritative_fixture.plan_path)
    plan["routes"][0]["evidence_files"][0]["role"] = "arbitrary_file"
    _write_json(authoritative_fixture.plan_path, _seal(plan, "plan_hash"))
    with pytest.raises(AuthoritativeIntakeError, match="role is unsupported"):
        load_source_acquisition_plan(authoritative_fixture.plan_path)

    fixture = _build_fixture(authoritative_fixture.repository.parent / "external-chain")
    plan = _read_json(fixture.plan_path)
    route = plan["routes"][0]
    route["semantic_authority"] = "third_party_reference"
    route["evidence_files"] = [
        {
            "artifact_id": "synthetic-parser",
            "role": "parser",
            "relative_path": "source-policy.json",
            "required": True,
            "expected_source_id": "synthetic-source",
        }
    ]
    route["raw_inventories"] = []
    route["derived_artifacts"] = []
    _write_json(fixture.plan_path, _seal(plan, "plan_hash"))
    with pytest.raises(AuthoritativeIntakeError, match="external acquisition profile"):
        load_source_acquisition_plan(fixture.plan_path)


def test_runtime_source_coverage_requires_present_identity_matching_evidence(
    authoritative_fixture: _AuthoritativeFixture,
) -> None:
    plan = _read_json(authoritative_fixture.plan_path)
    plan["routes"][0]["source_ids"] = [
        "phantom-source",
        *plan["routes"][0]["source_ids"],
    ]
    plan["routes"][0]["evidence_files"].append(
        {
            "artifact_id": "zz-phantom-evidence",
            "role": "raw_manifest",
            "relative_path": "missing/phantom.json",
            "required": True,
            "expected_source_id": "phantom-source",
        }
    )
    _write_json(authoritative_fixture.plan_path, _seal(plan, "plan_hash"))

    policy = _read_json(authoritative_fixture.policy_path)
    policy["policies"][0]["source_ids"] = [
        "phantom-source",
        *policy["policies"][0]["source_ids"],
    ]
    _write_json(authoritative_fixture.policy_path, _seal(policy, "registry_hash"))

    compilation = authoritative_fixture.compile()
    codes = _blocker_codes(compilation)
    assert "required_evidence_file_missing" in codes
    assert "source_evidence_coverage_incomplete" in codes
    assert (
        compilation.source_review["routes"][0]["acquisition_integrity_status"]
        == "partial"
    )


def test_m_b_cli_rechecks_compiled_identities_after_preflight(
    authoritative_fixture: _AuthoritativeFixture,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    counterfeit = authoritative_fixture.compile()
    monkeypatch.setattr(
        m_b_cli,
        "compile_authoritative_intake",
        lambda _config: counterfeit,
    )

    exit_code = m_b_cli.main(
        ["--legacy-root", str(authoritative_fixture.repository), "--dry-run"]
    )
    output = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert output["ok"] is False
    assert "changed between M-B preflight" in output["error"]


def test_empty_raw_manifest_is_partial_and_explicitly_blocked(
    authoritative_fixture: _AuthoritativeFixture,
) -> None:
    manifest = _read_json(authoritative_fixture.raw_manifest_path)
    manifest["results"] = []
    _write_json(authoritative_fixture.raw_manifest_path, manifest)

    compilation = authoritative_fixture.compile()
    assert "raw_manifest_results_empty" in _blocker_codes(compilation)
    route = compilation.source_review["routes"][0]
    assert route["acquisition_integrity_status"] == "partial"
    assert route["raw_manifest_audits"][0]["result_count"] == 0


def test_manifested_payload_must_belong_to_declared_raw_inventory(
    authoritative_fixture: _AuthoritativeFixture,
) -> None:
    plan = _read_json(authoritative_fixture.plan_path)
    inventory = plan["routes"][0]["raw_inventories"][0]
    inventory.update(
        {
            "relative_path": "data/processed",
            "suffixes": [".json"],
            "expected_min_files": 1,
        }
    )
    _write_json(authoritative_fixture.plan_path, _seal(plan, "plan_hash"))

    compilation = authoritative_fixture.compile()
    assert "raw_manifest_payload_outside_inventory" in _blocker_codes(compilation)
    assert (
        compilation.source_review["routes"][0]["acquisition_integrity_status"]
        == "partial"
    )


def test_policy_binding_and_every_intended_use_dimension_are_gated(
    authoritative_fixture: _AuthoritativeFixture,
) -> None:
    policy = _read_json(authoritative_fixture.policy_path)
    entry = policy["policies"][0]
    entry.update(
        {
            "review_status": "approved",
            "collection_status": "allowed",
            "candidate_use": "allowed",
            "private_match_use": "prohibited",
            "training_use": "prohibited",
            "redistribution": "allowed",
            "production_promotion": "allowed",
            "source_ids": ["another-source"],
        }
    )
    _write_json(authoritative_fixture.policy_path, _seal(policy, "registry_hash"))

    compilation = authoritative_fixture.compile()
    codes = _blocker_codes(compilation)
    assert "source_policy_binding_mismatch" in codes
    assert "source_private_match_use_not_allowed" in codes
    assert "source_training_use_not_allowed" in codes
    assert (
        compilation.source_review["summary"]
        ["policy_resolved_for_production_route_count"]
        == 0
    )
    assert (
        compilation.source_review["summary"]["source_policy_resolution_rate_ppm"]
        == 0
    )


def test_target_source_manifest_bytes_are_pinned_by_the_plan(
    authoritative_fixture: _AuthoritativeFixture,
) -> None:
    manifest_path = (
        authoritative_fixture.repository
        / "data/manifests/synthetic-catalog-intake.json"
    )
    manifest = _read_json(manifest_path)
    manifest["trust"]["verification_status"] = "tampered"
    _write_json(manifest_path, manifest)

    with pytest.raises(AuthoritativeIntakeError, match="manifest hash mismatch"):
        authoritative_fixture.compile()


def test_compiler_rejects_symlinked_evidence(
    authoritative_fixture: _AuthoritativeFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = authoritative_fixture.raw_manifest_path
    target = manifest.with_name("manifest-target.json")
    manifest.replace(target)
    try:
        manifest.symlink_to(target.name)
    except OSError:
        target.replace(manifest)
        path_type = type(manifest)
        original_is_symlink = path_type.is_symlink

        def reports_manifest_symlink(path: Path) -> bool:
            return path == manifest or original_is_symlink(path)

        monkeypatch.setattr(path_type, "is_symlink", reports_manifest_symlink)

    with pytest.raises(AuthoritativeIntakeError, match="symlink"):
        authoritative_fixture.compile()


def test_opened_file_handle_must_resolve_inside_its_declared_root(
    authoritative_fixture: _AuthoritativeFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outside = tmp_path / "outside-target.json"
    outside.write_bytes(b"{}")
    original = authoritative_compiler._opened_file_path

    def redirect_target_handle(descriptor: int, requested: Path) -> Path:
        if requested.name == "target_pool.json":
            return outside.resolve()
        return original(descriptor, requested)

    monkeypatch.setattr(
        authoritative_compiler,
        "_opened_file_path",
        redirect_target_handle,
    )
    with pytest.raises(AuthoritativeIntakeError, match="escapes its declared root"):
        authoritative_fixture.compile()


@pytest.mark.parametrize(
    ("field", "replacement", "expected_code"),
    [
        ("bytes", lambda value: value + 1, "raw_manifest_byte_count_mismatch"),
        ("sha256", lambda _value: "0" * 64, "raw_manifest_hash_mismatch"),
    ],
)
def test_raw_manifest_reports_sealed_payload_identity_drift(
    authoritative_fixture: _AuthoritativeFixture,
    field: str,
    replacement: Callable[[Any], Any],
    expected_code: str,
) -> None:
    manifest = _read_json(authoritative_fixture.raw_manifest_path)
    result = manifest["results"][0]
    result[field] = replacement(result[field])
    _write_json(authoritative_fixture.raw_manifest_path, manifest)

    compilation = authoritative_fixture.compile()
    assert expected_code in _blocker_codes(compilation)
    audit = compilation.source_review["routes"][0]["raw_manifest_audits"][0]
    counter = (
        "byte_mismatch_count" if field == "bytes" else "hash_mismatch_count"
    )
    assert audit[counter] == 1
    assert audit["sealed_result_count"] == 0
    assert compilation.assessment["summary"]["decision"] == "NO-GO"


def test_catalog_reread_cannot_mix_a_post_intake_snapshot(
    authoritative_fixture: _AuthoritativeFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = authoritative_compiler.build_catalog_intake

    def mutate_after_intake(**kwargs: Any):
        bundle = original(**kwargs)
        path = authoritative_fixture.repository / "data/processed/moves.json"
        raw = _read_json(path)
        raw["items"][0]["name"] = "post-intake-drift"
        _write_json(path, raw)
        return bundle

    monkeypatch.setattr(
        authoritative_compiler,
        "build_catalog_intake",
        mutate_after_intake,
    )
    with pytest.raises(
        AuthoritativeIntakeError,
        match="changed after frozen intake",
    ):
        authoritative_fixture.compile()


def test_target_change_restore_cannot_mix_two_snapshots(
    authoritative_fixture: _AuthoritativeFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_path = authoritative_fixture.repository / "target_pool.json"
    original_bytes = target_path.read_bytes()
    target = _read_json(target_path)
    target["members"][0]["label"] = "No.0001 changed-before-intake"
    _write_json(target_path, target)
    original = authoritative_compiler.build_catalog_intake

    def restore_for_intake(**kwargs: Any):
        target_path.write_bytes(original_bytes)
        return original(**kwargs)

    monkeypatch.setattr(
        authoritative_compiler,
        "build_catalog_intake",
        restore_for_intake,
    )
    with pytest.raises(
        AuthoritativeIntakeError,
        match=(
            "target (?:pool changed while|source manifest artifact identity mismatch)"
        ),
    ):
        authoritative_fixture.compile()


def test_source_review_change_restore_cannot_mix_two_snapshots(
    authoritative_fixture: _AuthoritativeFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = authoritative_fixture.repository / "data/processed/moves.json"
    original_bytes = path.read_bytes()
    raw = _read_json(path)
    raw["items"][0]["name"] = "changed-during-source-review"
    _write_json(path, raw)
    original = authoritative_compiler.build_catalog_intake

    def restore_for_intake(**kwargs: Any):
        path.write_bytes(original_bytes)
        return original(**kwargs)

    monkeypatch.setattr(
        authoritative_compiler,
        "build_catalog_intake",
        restore_for_intake,
    )
    with pytest.raises(
        AuthoritativeIntakeError,
        match="changed between review and intake",
    ):
        authoritative_fixture.compile()


def test_source_lock_change_during_resolution_is_rejected(
    authoritative_fixture: _AuthoritativeFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local_lock = authoritative_fixture.repository / "source-lock.json"
    shutil.copyfile(SOURCE_LOCK, local_lock)
    fixture = replace(
        authoritative_fixture,
        config=replace(
            authoritative_fixture.config,
            source_lock_path=local_lock,
        ),
    )
    original = authoritative_compiler.load_source_lock

    def mutate_after_load(path: Path):
        result = original(path)
        raw = _read_json(local_lock)
        raw["artifacts"][0]["byte_count"] += 1
        _write_json(local_lock, raw)
        return result

    monkeypatch.setattr(
        authoritative_compiler,
        "load_source_lock",
        mutate_after_load,
    )
    with pytest.raises(
        AuthoritativeIntakeError,
        match="changed while resolving",
    ):
        fixture.compile()


def test_duplicate_key_in_a_mapping_source_is_rejected_after_locking(
    authoritative_fixture: _AuthoritativeFixture,
) -> None:
    usage_path = (
        authoritative_fixture.repository / "data/processed/pokemon_usage.json"
    )
    original = usage_path.read_text(encoding="utf-8")
    duplicate = original.replace(
        '  "source": "synthetic_usage",',
        '  "source": "shadowed",\n  "source": "synthetic_usage",',
        1,
    )
    assert duplicate != original
    usage_path.write_text(duplicate, encoding="utf-8", newline="\n")
    payload = usage_path.read_bytes()

    local_lock = authoritative_fixture.repository / "duplicate-source-lock.json"
    lock = _read_json(SOURCE_LOCK)
    usage = next(
        value
        for value in lock["artifacts"]
        if value["artifact_id"] == "pokemon_usage"
    )
    usage["byte_count"] = len(payload)
    usage["sha256"] = hashlib.sha256(payload).hexdigest()
    _write_json(local_lock, lock)
    fixture = replace(
        authoritative_fixture,
        config=replace(
            authoritative_fixture.config,
            source_lock_path=local_lock,
        ),
    )
    with pytest.raises(
        AuthoritativeIntakeError,
        match="duplicate key source",
    ):
        fixture.compile()


def test_documents_conform_to_strict_json_schemas(
    authoritative_fixture: _AuthoritativeFixture,
) -> None:
    compilation = authoritative_fixture.compile()
    documents = {
        "sim02c-source-acquisition-plan-v1.schema.json": _read_json(
            authoritative_fixture.plan_path
        ),
        "sim02c-source-policy-register-v1.schema.json": _read_json(
            authoritative_fixture.policy_path
        ),
        "sim02c-source-acquisition-review-v1.schema.json": (
            compilation.source_review
        ),
        "sim02c-authoritative-mapping-workbench-v1.schema.json": (
            compilation.mapping_workbench
        ),
        "sim02c-authoritative-catalog-v2-workbench.schema.json": (
            compilation.catalog_workbench
        ),
        "sim02c-authoritative-intake-assessment-v1.schema.json": (
            compilation.assessment
        ),
        "sim02c-authoritative-intake-compilation-v1.schema.json": (
            compilation.summary_data()
        ),
    }
    for schema_name, document in documents.items():
        schema_path = SCHEMA_ROOT / schema_name
        assert schema_path.is_file(), f"missing authoritative intake schema: {schema_name}"
        validate_document_contract(
            document,
            _read_json(schema_path),
            schema_name,
            fail_on_unknown_keywords=True,
        )
