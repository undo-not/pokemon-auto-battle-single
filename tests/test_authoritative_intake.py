from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
import hashlib
import json
import os
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
from scripts.validate_sim01_bundle import BundleValidationError, validate_document_contract


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
    parser_path: Path
    derived_path: Path
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
    raw_manifest_payload = raw_manifest_path.read_bytes()

    parser_path = repository / "tools/synthetic_parser.json"
    _write_json(
        parser_path,
        {
            "artifact": "synthetic-parser",
            "operation": "deterministic-fixture-normalization",
            "version": 1,
        },
    )
    parser_payload = parser_path.read_bytes()

    derived_path = repository / "data/processed/moves.json"
    derived_payload = derived_path.read_bytes()
    expected_lineage_hash = canonical_sha256(
        {
            "binding_domain": "sim02c-derived-lineage-v2",
            "schema_version": "2.0.0",
            "route_id": "synthetic-local-route",
            "output": {
                "artifact_id": "synthetic-derived-moves",
                "relative_path": "data/processed/moves.json",
                "byte_count": len(derived_payload),
                "sha256": hashlib.sha256(derived_payload).hexdigest(),
                "record_count": 2,
                "declared_source": "synthetic_moves",
                "actual_source": "synthetic_moves",
            },
            "source_artifacts": [
                {
                    "artifact_id": "synthetic-raw-manifest",
                    "relative_path": "data/raw/synthetic/manifest.json",
                    "role": "raw_manifest",
                    "byte_count": len(raw_manifest_payload),
                    "sha256": hashlib.sha256(raw_manifest_payload).hexdigest(),
                    "source_id": "synthetic-source",
                    "expected_source_id": "synthetic-source",
                    "inventory_id": "synthetic-raw-json",
                    "payload_inventory_hash": canonical_sha256(
                        [
                            {
                                "relative_path": "data/raw/synthetic/payload.json",
                                "byte_count": len(payload),
                                "sha256": hashlib.sha256(payload).hexdigest(),
                            }
                        ]
                    ),
                }
            ],
            "transform_artifacts": [
                {
                    "artifact_id": "synthetic-parser",
                    "relative_path": "tools/synthetic_parser.json",
                    "role": "parser",
                    "byte_count": len(parser_payload),
                    "sha256": hashlib.sha256(parser_payload).hexdigest(),
                }
            ],
        }
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
            "schema_version": "2.0.0",
            "plan_id": "synthetic-authoritative-intake-v2",
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
                            "artifact_id": "synthetic-parser",
                            "role": "parser",
                            "relative_path": "tools/synthetic_parser.json",
                            "required": True,
                            "expected_source_id": None,
                        },
                        {
                            "artifact_id": "synthetic-raw-manifest",
                            "role": "raw_manifest",
                            "relative_path": "data/raw/synthetic/manifest.json",
                            "required": True,
                            "expected_source_id": "synthetic-source",
                            "inventory_id": "synthetic-raw-json",
                        }
                    ],
                    "raw_inventories": [
                        {
                            "inventory_id": "synthetic-raw-json",
                            "relative_path": "data/raw/synthetic",
                            "suffixes": [".json"],
                            "expected_min_files": 1,
                        }
                    ],
                    "derived_artifacts": [
                        {
                            "artifact_id": "synthetic-derived-moves",
                            "relative_path": "data/processed/moves.json",
                            "record_pointer": "/items",
                            "expected_min_records": 2,
                            "expected_source": "synthetic_moves",
                            "lineage_requirements": {
                                "source_artifact_ids": [
                                    "synthetic-raw-manifest"
                                ],
                                "transform_artifact_ids": ["synthetic-parser"],
                                "expected_lineage_hash": expected_lineage_hash,
                            },
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
        parser_path=parser_path,
        derived_path=derived_path,
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

    assert first.summary_data()["schema_version"] == "2.0.0"
    assert first.summary_data()["compiler_version"] == "2.0.0"
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
    assert assessment["summary"]["blocker_enumeration_scope"] == (
        "declared_workbench_surfaces_and_known_gap_hints"
    )
    assert (
        assessment["summary"]["undeclared_dependency_enumeration_complete"]
        is False
    )
    assert assessment["authorization_status"] == "not_authorization"
    assert first.summary_data()["production_materialization_emitted"] is False
    assert all(
        document["authorization_status"] == "not_authorization"
        for document in first.document_map.values()
    )

    route = first.source_review["routes"][0]
    assert route["acquisition_integrity_status"] == "snapshot_bound"
    assert route["raw_manifest_audits"][0]["sealed_result_count"] == 1
    assert route["derived_artifacts"][0]["lineage_status"] == "snapshot_bound"
    assert first.source_review["summary"]["acquisition_route_integrity_rate_ppm"] == 0
    assert first.source_review["summary"]["snapshot_bound_route_rate_ppm"] == 1_000_000
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


def test_v2_loader_rejects_legacy_v1_plan_contract(
    authoritative_fixture: _AuthoritativeFixture,
) -> None:
    plan = _read_json(authoritative_fixture.plan_path)
    plan["schema_version"] = "1.0.0"
    plan["plan_id"] = "synthetic-authoritative-intake-v1"
    _write_json(authoritative_fixture.plan_path, _seal(plan, "plan_hash"))

    with pytest.raises(AuthoritativeIntakeError, match="unsupported acquisition plan"):
        load_source_acquisition_plan(authoritative_fixture.plan_path)


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
    version = _read_json(path)["schema_version"]
    text = text.replace(
        f'"schema_version": "{version}"',
        f'"schema_version": "{version}",\n  "schema_version": "{version}"',
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


def test_plan_loader_matches_locator_and_json_pointer_schema_constraints(
    authoritative_fixture: _AuthoritativeFixture,
) -> None:
    plan = _read_json(authoritative_fixture.plan_path)
    plan["routes"][0]["locators"] = [
        "https://example.invalid/synthetic\nforged"
    ]
    _write_json(authoritative_fixture.plan_path, _seal(plan, "plan_hash"))
    with pytest.raises(AuthoritativeIntakeError, match="control characters"):
        load_source_acquisition_plan(authoritative_fixture.plan_path)

    fixture = _build_fixture(
        authoritative_fixture.repository.parent / "invalid-record-pointer"
    )
    plan = _read_json(fixture.plan_path)
    plan["routes"][0]["derived_artifacts"][0]["record_pointer"] = (
        "/items/~2invalid"
    )
    _write_json(fixture.plan_path, _seal(plan, "plan_hash"))
    with pytest.raises(AuthoritativeIntakeError, match="RFC 6901"):
        load_source_acquisition_plan(fixture.plan_path)


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


def test_plan_rejects_one_path_declared_for_multiple_roles(
    authoritative_fixture: _AuthoritativeFixture,
) -> None:
    plan = _read_json(authoritative_fixture.plan_path)
    evidence = plan["routes"][0]["evidence_files"]
    evidence.append(
        {
            "artifact_id": "synthetic-parser-alias",
            "role": "normalizer",
            "relative_path": "tools/synthetic_parser.json",
            "required": True,
            "expected_source_id": None,
        }
    )
    evidence.sort(key=lambda value: value["artifact_id"])
    _write_json(authoritative_fixture.plan_path, _seal(plan, "plan_hash"))

    with pytest.raises(AuthoritativeIntakeError, match="relative paths must be unique"):
        load_source_acquisition_plan(authoritative_fixture.plan_path)


def test_plan_requires_raw_manifest_source_binding(
    authoritative_fixture: _AuthoritativeFixture,
) -> None:
    plan = _read_json(authoritative_fixture.plan_path)
    manifest = next(
        value
        for value in plan["routes"][0]["evidence_files"]
        if value["role"] == "raw_manifest"
    )
    manifest["expected_source_id"] = None
    _write_json(authoritative_fixture.plan_path, _seal(plan, "plan_hash"))

    with pytest.raises(AuthoritativeIntakeError, match="requires expected_source_id"):
        load_source_acquisition_plan(authoritative_fixture.plan_path)


def test_plan_rejects_evidence_and_derived_artifact_id_overlap(
    authoritative_fixture: _AuthoritativeFixture,
) -> None:
    plan = _read_json(authoritative_fixture.plan_path)
    plan["routes"][0]["derived_artifacts"][0]["artifact_id"] = "synthetic-parser"
    _write_json(authoritative_fixture.plan_path, _seal(plan, "plan_hash"))

    with pytest.raises(AuthoritativeIntakeError, match="artifact IDs must be disjoint"):
        load_source_acquisition_plan(authoritative_fixture.plan_path)


def test_plan_rejects_one_path_reused_across_routes(
    authoritative_fixture: _AuthoritativeFixture,
) -> None:
    plan = _read_json(authoritative_fixture.plan_path)
    second_route = json.loads(json.dumps(plan["routes"][0]))
    second_route["route_id"] = "zz-cross-route-alias"
    plan["routes"].append(second_route)
    _write_json(authoritative_fixture.plan_path, _seal(plan, "plan_hash"))

    with pytest.raises(AuthoritativeIntakeError, match="globally role-independent"):
        load_source_acquisition_plan(authoritative_fixture.plan_path)


@pytest.mark.parametrize("reuse_kind", ["hardlink", "identical_copy"])
def test_runtime_rejects_reused_bytes_across_evidence_roles(
    authoritative_fixture: _AuthoritativeFixture,
    reuse_kind: str,
) -> None:
    alias = authoritative_fixture.repository / "tools/synthetic_normalizer.json"
    if reuse_kind == "hardlink":
        os.link(authoritative_fixture.parser_path, alias)
        expected = "one opened file"
    else:
        shutil.copyfile(authoritative_fixture.parser_path, alias)
        expected = "identical bytes"

    plan = _read_json(authoritative_fixture.plan_path)
    evidence = plan["routes"][0]["evidence_files"]
    evidence.append(
        {
            "artifact_id": "synthetic-normalizer",
            "role": "normalizer",
            "relative_path": "tools/synthetic_normalizer.json",
            "required": True,
            "expected_source_id": None,
        }
    )
    evidence.sort(key=lambda value: value["artifact_id"])
    _write_json(authoritative_fixture.plan_path, _seal(plan, "plan_hash"))

    with pytest.raises(AuthoritativeIntakeError, match=expected):
        authoritative_fixture.compile()


@pytest.mark.parametrize("reuse_kind", ["hardlink", "identical_copy"])
def test_runtime_rejects_cross_route_role_reuse(
    authoritative_fixture: _AuthoritativeFixture,
    reuse_kind: str,
) -> None:
    repository = authoritative_fixture.repository
    implementation = repository / "second/implementation.json"
    implementation.parent.mkdir(parents=True)
    if reuse_kind == "hardlink":
        os.link(authoritative_fixture.parser_path, implementation)
        expected = "one opened file"
    else:
        shutil.copyfile(authoritative_fixture.parser_path, implementation)
        expected = "identical bytes"
    _write_json(repository / "second/review.json", {"review": "fixture-only"})
    _write_json(repository / "second/validator.json", {"validator": "fixture-only"})
    _write_json(
        repository / "second/derived.json",
        {"source": "second-local-source", "items": [{"id": "second:1"}]},
    )

    policy = _read_json(authoritative_fixture.policy_path)
    second_policy = dict(policy["policies"][0])
    second_policy.update(
        {
            "policy_id": "zz-second-local-policy",
            "source_group": "second-local-fixture",
            "source_ids": ["second-local-source"],
        }
    )
    policy["policies"].append(second_policy)
    policy["policies"].sort(key=lambda value: value["policy_id"])
    _write_json(authoritative_fixture.policy_path, _seal(policy, "registry_hash"))

    plan = _read_json(authoritative_fixture.plan_path)
    plan["routes"].append(
        {
            "route_id": "zz-second-local-route",
            "root_kind": "legacy",
            "source_kind": "local_implementation",
            "semantic_authority": "local_implementation",
            "source_ids": ["second-local-source"],
            "locators": ["legacy://second-local-fixture"],
            "policy_id": "zz-second-local-policy",
            "candidate_roles": ["mechanics_reference"],
            "evidence_files": [
                {
                    "artifact_id": "second-implementation",
                    "role": "implementation",
                    "relative_path": "second/implementation.json",
                    "required": True,
                    "expected_source_id": "second-local-source",
                },
                {
                    "artifact_id": "second-review",
                    "role": "review_record",
                    "relative_path": "second/review.json",
                    "required": True,
                    "expected_source_id": None,
                },
                {
                    "artifact_id": "second-validator",
                    "role": "validator",
                    "relative_path": "second/validator.json",
                    "required": True,
                    "expected_source_id": None,
                },
            ],
            "raw_inventories": [],
            "derived_artifacts": [
                {
                    "artifact_id": "second-derived",
                    "relative_path": "second/derived.json",
                    "record_pointer": "/items",
                    "expected_min_records": 1,
                    "expected_source": "second-local-source",
                }
            ],
        }
    )
    _write_json(authoritative_fixture.plan_path, _seal(plan, "plan_hash"))

    with pytest.raises(AuthoritativeIntakeError, match=expected):
        authoritative_fixture.compile()


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


def test_raw_manifest_source_mismatch_invalidates_lineage_and_route(
    authoritative_fixture: _AuthoritativeFixture,
) -> None:
    manifest = _read_json(authoritative_fixture.raw_manifest_path)
    manifest["source_id"] = "wrong-upstream"
    _write_json(authoritative_fixture.raw_manifest_path, manifest)

    compilation = authoritative_fixture.compile()
    codes = _blocker_codes(compilation)
    assert "source_id_mismatch" in codes
    assert "derived_lineage_invalid" in codes
    audit = compilation.source_review["routes"][0]["raw_manifest_audits"][0]
    assert audit["source_id"] == "wrong-upstream"
    assert audit["expected_source_id"] == "synthetic-source"
    assert audit["source_identity_status"] == "mismatch"
    assert audit["integrity_status"] == "incomplete"
    route = compilation.source_review["routes"][0]
    assert route["derived_artifacts"][0]["lineage_status"] == "invalid"
    assert route["acquisition_integrity_status"] == "partial"


def test_invalid_raw_source_identifier_is_normalized_and_schema_valid(
    authoritative_fixture: _AuthoritativeFixture,
) -> None:
    manifest = _read_json(authoritative_fixture.raw_manifest_path)
    manifest["source_id"] = "wrong upstream\nwith control"
    _write_json(authoritative_fixture.raw_manifest_path, manifest)

    compilation = authoritative_fixture.compile()
    audit = compilation.source_review["routes"][0]["raw_manifest_audits"][0]
    assert audit["source_id"] == "invalid_source_id"
    assert audit["source_identity_status"] == "mismatch"
    assert audit["integrity_status"] == "incomplete"
    assert "source_id_mismatch" in _blocker_codes(compilation)
    validate_document_contract(
        compilation.source_review,
        _read_json(
            SCHEMA_ROOT / "sim02c-source-acquisition-review-v2.schema.json"
        ),
        "source review with invalid raw source ID",
        fail_on_unknown_keywords=True,
    )


def test_non_string_derived_source_is_normalized_and_schema_valid(
    authoritative_fixture: _AuthoritativeFixture,
) -> None:
    extra_path = (
        authoritative_fixture.repository
        / "data/processed/invalid-derived-source.json"
    )
    _write_json(extra_path, {"source": 42, "items": [{"id": 1}]})
    plan = _read_json(authoritative_fixture.plan_path)
    plan["routes"][0]["derived_artifacts"].append(
        {
            "artifact_id": "zz-invalid-derived-source",
            "relative_path": "data/processed/invalid-derived-source.json",
            "record_pointer": "/items",
            "expected_min_records": 1,
            "expected_source": "synthetic_moves",
            "lineage_requirements": {
                "expected_lineage_hash": "0" * 64,
                "source_artifact_ids": ["synthetic-raw-manifest"],
                "transform_artifact_ids": ["synthetic-parser"],
            },
        }
    )
    _write_json(authoritative_fixture.plan_path, _seal(plan, "plan_hash"))

    compilation = authoritative_fixture.compile()
    result = next(
        value
        for value in compilation.source_review["routes"][0]["derived_artifacts"]
        if value["artifact_id"] == "zz-invalid-derived-source"
    )
    assert result["actual_source"] is None
    assert result["lineage_status"] == "invalid"
    assert "derived_source_mismatch" in _blocker_codes(compilation)
    validate_document_contract(
        compilation.source_review,
        _read_json(
            SCHEMA_ROOT / "sim02c-source-acquisition-review-v2.schema.json"
        ),
        "source review with invalid derived source",
        fail_on_unknown_keywords=True,
    )


def test_derived_source_mismatch_cannot_be_resealed_as_snapshot_bound(
    authoritative_fixture: _AuthoritativeFixture,
) -> None:
    baseline = authoritative_fixture.compile()
    route = baseline.source_review["routes"][0]
    raw_identity = next(
        value
        for value in route["evidence_artifacts"]
        if value["artifact_id"] == "synthetic-raw-manifest"
    )
    parser_identity = next(
        value
        for value in route["evidence_artifacts"]
        if value["artifact_id"] == "synthetic-parser"
    )
    raw_audit = route["raw_manifest_audits"][0]

    derived = _read_json(authoritative_fixture.derived_path)
    derived["source"] = "wrong-source"
    _write_json(authoritative_fixture.derived_path, derived)
    payload = authoritative_fixture.derived_path.read_bytes()
    forged_lineage_hash = canonical_sha256(
        {
            "binding_domain": "sim02c-derived-lineage-v2",
            "schema_version": "2.0.0",
            "route_id": route["route_id"],
            "output": {
                "artifact_id": "synthetic-derived-moves",
                "relative_path": "data/processed/moves.json",
                "byte_count": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "record_count": 2,
                "declared_source": "synthetic_moves",
                "actual_source": "wrong-source",
            },
            "source_artifacts": [
                {
                    "artifact_id": raw_identity["artifact_id"],
                    "relative_path": raw_identity["relative_path"],
                    "role": raw_identity["role"],
                    "byte_count": raw_identity["byte_count"],
                    "sha256": raw_identity["sha256"],
                    "source_id": raw_audit["source_id"],
                    "expected_source_id": raw_audit["expected_source_id"],
                    "inventory_id": raw_audit["inventory_id"],
                    "payload_inventory_hash": raw_audit[
                        "payload_inventory_hash"
                    ],
                }
            ],
            "transform_artifacts": [
                {
                    "artifact_id": parser_identity["artifact_id"],
                    "relative_path": parser_identity["relative_path"],
                    "role": parser_identity["role"],
                    "byte_count": parser_identity["byte_count"],
                    "sha256": parser_identity["sha256"],
                }
            ],
        }
    )

    plan = _read_json(authoritative_fixture.plan_path)
    plan["routes"][0]["derived_artifacts"][0]["lineage_requirements"][
        "expected_lineage_hash"
    ] = forged_lineage_hash
    _write_json(authoritative_fixture.plan_path, _seal(plan, "plan_hash"))

    local_lock = authoritative_fixture.repository / "wrong-source-lock.json"
    lock = _read_json(SOURCE_LOCK)
    locked = next(
        value for value in lock["artifacts"] if value["artifact_id"] == "moves"
    )
    locked["byte_count"] = len(payload)
    locked["sha256"] = hashlib.sha256(payload).hexdigest()
    _write_json(local_lock, lock)
    fixture = replace(
        authoritative_fixture,
        config=replace(
            authoritative_fixture.config,
            source_lock_path=local_lock,
        ),
    )

    compilation = fixture.compile()
    result = compilation.source_review["routes"][0]["derived_artifacts"][0]
    assert "derived_source_mismatch" in _blocker_codes(compilation)
    assert result["actual_source"] == "wrong-source"
    assert result["lineage_status"] == "invalid"


def test_manifest_without_source_specific_inventory_binding_is_partial(
    authoritative_fixture: _AuthoritativeFixture,
) -> None:
    plan = _read_json(authoritative_fixture.plan_path)
    manifest = next(
        value
        for value in plan["routes"][0]["evidence_files"]
        if value["role"] == "raw_manifest"
    )
    manifest.pop("inventory_id")
    _write_json(authoritative_fixture.plan_path, _seal(plan, "plan_hash"))

    compilation = authoritative_fixture.compile()
    codes = _blocker_codes(compilation)
    assert "raw_manifest_inventory_binding_missing" in codes
    assert "raw_inventory_manifest_binding_missing" in codes
    assert "source_evidence_coverage_incomplete" in codes
    assert (
        compilation.source_review["routes"][0]["acquisition_integrity_status"]
        == "partial"
    )


def test_bound_inventory_rejects_unmanifested_payload(
    authoritative_fixture: _AuthoritativeFixture,
) -> None:
    _write_json(
        authoritative_fixture.repository / "data/raw/synthetic/unmanifested.json",
        {"source_id": "unbound"},
    )

    compilation = authoritative_fixture.compile()
    assert "raw_inventory_contains_unmanifested_payload" in _blocker_codes(
        compilation
    )
    audit = compilation.source_review["routes"][0]["raw_manifest_audits"][0]
    assert audit["unmanifested_file_count"] == 1
    assert audit["integrity_status"] == "incomplete"


def test_raw_manifest_rejects_duplicate_canonical_saved_path(
    authoritative_fixture: _AuthoritativeFixture,
) -> None:
    manifest = _read_json(authoritative_fixture.raw_manifest_path)
    manifest["results"].append(dict(manifest["results"][0]))
    _write_json(authoritative_fixture.raw_manifest_path, manifest)

    compilation = authoritative_fixture.compile()
    assert "raw_manifest_duplicate_saved_path" in _blocker_codes(compilation)
    audit = compilation.source_review["routes"][0]["raw_manifest_audits"][0]
    assert audit["duplicate_saved_path_count"] == 1
    assert audit["inventory_binding_status"] == "mismatch"
    assert audit["integrity_status"] == "incomplete"


def test_plan_rejects_duplicate_raw_inventory_path(
    authoritative_fixture: _AuthoritativeFixture,
) -> None:
    plan = _read_json(authoritative_fixture.plan_path)
    duplicate = dict(plan["routes"][0]["raw_inventories"][0])
    duplicate["inventory_id"] = "zz-duplicate-inventory"
    plan["routes"][0]["raw_inventories"].append(duplicate)
    _write_json(authoritative_fixture.plan_path, _seal(plan, "plan_hash"))

    with pytest.raises(AuthoritativeIntakeError, match="relative paths must be unique"):
        load_source_acquisition_plan(authoritative_fixture.plan_path)


def test_manifest_and_inventory_cannot_mix_payload_snapshots(
    authoritative_fixture: _AuthoritativeFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_inventory = authoritative_compiler._inventory_raw_root
    mutated = False

    def mutate_before_inventory(*args: Any, **kwargs: Any):
        nonlocal mutated
        if not mutated:
            mutated = True
            payload = authoritative_fixture.raw_payload_path.read_bytes()
            authoritative_fixture.raw_payload_path.write_bytes(payload + b" ")
        return original_inventory(*args, **kwargs)

    monkeypatch.setattr(
        authoritative_compiler,
        "_inventory_raw_root",
        mutate_before_inventory,
    )
    with pytest.raises(
        AuthoritativeIntakeError,
        match="raw payload changed across source snapshot",
    ):
        authoritative_fixture.compile()


@pytest.mark.parametrize("reuse_kind", ["same_path", "hardlink", "identical_copy"])
def test_derived_artifact_cannot_reuse_raw_payload(
    authoritative_fixture: _AuthoritativeFixture,
    reuse_kind: str,
) -> None:
    if reuse_kind == "same_path":
        derived_path = authoritative_fixture.raw_payload_path
    else:
        derived_path = authoritative_fixture.repository / f"data/processed/{reuse_kind}.json"
        if reuse_kind == "hardlink":
            os.link(authoritative_fixture.raw_payload_path, derived_path)
        else:
            shutil.copyfile(authoritative_fixture.raw_payload_path, derived_path)

    plan = _read_json(authoritative_fixture.plan_path)
    declaration = plan["routes"][0]["derived_artifacts"][0]
    declaration.update(
        {
            "relative_path": derived_path.relative_to(
                authoritative_fixture.repository
            ).as_posix(),
            "record_pointer": "/records",
            "expected_min_records": 1,
        }
    )
    _write_json(authoritative_fixture.plan_path, _seal(plan, "plan_hash"))

    with pytest.raises(AuthoritativeIntakeError, match="derived artifact must be independent"):
        authoritative_fixture.compile()


def test_manifested_payload_must_belong_to_declared_raw_inventory(
    authoritative_fixture: _AuthoritativeFixture,
) -> None:
    _write_json(
        authoritative_fixture.repository / "data/other-inventory/unrelated.json",
        {"source_id": "unrelated"},
    )
    plan = _read_json(authoritative_fixture.plan_path)
    inventory = plan["routes"][0]["raw_inventories"][0]
    inventory.update(
        {
            "relative_path": "data/other-inventory",
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


def test_source_label_and_record_count_do_not_replace_lineage_requirements(
    authoritative_fixture: _AuthoritativeFixture,
) -> None:
    plan = _read_json(authoritative_fixture.plan_path)
    plan["routes"][0]["derived_artifacts"][0].pop("lineage_requirements")
    _write_json(authoritative_fixture.plan_path, _seal(plan, "plan_hash"))

    compilation = authoritative_fixture.compile()
    assert "derived_lineage_requirements_missing" in _blocker_codes(compilation)
    derived = compilation.source_review["routes"][0]["derived_artifacts"][0]
    assert derived["actual_source"] == "synthetic_moves"
    assert derived["record_count"] == 2
    assert derived["lineage_status"] == "missing"
    assert (
        compilation.source_review["routes"][0]["acquisition_integrity_status"]
        == "partial"
    )


def test_declared_lineage_graph_gap_is_machine_readable_and_never_bound(
    authoritative_fixture: _AuthoritativeFixture,
) -> None:
    plan = _read_json(authoritative_fixture.plan_path)
    declaration = plan["routes"][0]["derived_artifacts"][0]
    declaration.pop("lineage_requirements")
    declaration["lineage_gap_hint"] = {
        "reason_codes": ["derived_parent_unsupported"],
        "parent_refs": [
            {
                "route_id": "synthetic-local-route",
                "artifact_id": "synthetic-parser",
            }
        ],
        "unregistered_paths": [],
        "runtime_dependencies": [],
    }
    _write_json(authoritative_fixture.plan_path, _seal(plan, "plan_hash"))

    compilation = authoritative_fixture.compile()
    blocker = next(
        value
        for value in compilation.assessment["blockers"]
        if value["code"] == "derived_lineage_graph_unrepresentable"
    )
    assert "synthetic-local-route:synthetic-parser" in blocker["evidence_required"]
    assert "route-qualified DAG" in blocker["restart_condition"]
    derived = compilation.source_review["routes"][0]["derived_artifacts"][0]
    assert derived["lineage_status"] == "unrepresentable"
    assert derived["lineage_binding_hash"] is None
    assert derived["lineage_gap_hint"] == declaration["lineage_gap_hint"]
    assert (
        compilation.source_review["routes"][0]["acquisition_integrity_status"]
        == "partial"
    )


def test_plan_rejects_lineage_proof_and_gap_hint_together(
    authoritative_fixture: _AuthoritativeFixture,
) -> None:
    plan = _read_json(authoritative_fixture.plan_path)
    plan["routes"][0]["derived_artifacts"][0]["lineage_gap_hint"] = {
        "reason_codes": ["unregistered_transform"],
        "parent_refs": [],
        "unregistered_paths": ["tools/missing-transform.py"],
        "runtime_dependencies": [],
    }
    _write_json(authoritative_fixture.plan_path, _seal(plan, "plan_hash"))

    with pytest.raises(AuthoritativeIntakeError, match="mutually exclusive"):
        load_source_acquisition_plan(authoritative_fixture.plan_path)


def test_transform_mutation_invalidates_snapshot_lineage(
    authoritative_fixture: _AuthoritativeFixture,
) -> None:
    original = authoritative_fixture.parser_path.read_text(encoding="utf-8")
    authoritative_fixture.parser_path.write_text(
        original.rstrip() + " \n", encoding="utf-8", newline="\n"
    )

    compilation = authoritative_fixture.compile()
    assert "derived_lineage_invalid" in _blocker_codes(compilation)
    derived = compilation.source_review["routes"][0]["derived_artifacts"][0]
    assert derived["lineage_status"] == "invalid"
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
        "sim02c-source-acquisition-plan-v2.schema.json": _read_json(
            authoritative_fixture.plan_path
        ),
        "sim02c-source-policy-register-v1.schema.json": _read_json(
            authoritative_fixture.policy_path
        ),
        "sim02c-source-acquisition-review-v2.schema.json": (
            compilation.source_review
        ),
        "sim02c-authoritative-mapping-workbench-v2.schema.json": (
            compilation.mapping_workbench
        ),
        "sim02c-authoritative-catalog-v2-workbench-v2.schema.json": (
            compilation.catalog_workbench
        ),
        "sim02c-authoritative-intake-assessment-v2.schema.json": (
            compilation.assessment
        ),
        "sim02c-authoritative-intake-compilation-v2.schema.json": (
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


def test_source_review_schema_rejects_false_provenance_claims(
    authoritative_fixture: _AuthoritativeFixture,
) -> None:
    review = authoritative_fixture.compile().source_review
    schema_name = "sim02c-source-acquisition-review-v2.schema.json"
    schema = _read_json(SCHEMA_ROOT / schema_name)
    route = review["routes"][0]
    assert route["raw_manifest_audits"][0]["integrity_status"] == "verified"
    assert route["derived_artifacts"][0]["lineage_status"] == "snapshot_bound"

    mutations: list[dict[str, Any]] = []

    unknown_role = json.loads(json.dumps(review))
    unknown_role["routes"][0]["evidence_artifacts"][0]["role"] = "invented_role"
    mutations.append(unknown_role)

    false_raw_integrity = json.loads(json.dumps(review))
    false_raw_integrity["routes"][0]["raw_manifest_audits"][0][
        "hash_mismatch_count"
    ] = 1
    mutations.append(false_raw_integrity)

    false_snapshot_binding = json.loads(json.dumps(review))
    false_snapshot_binding["routes"][0]["derived_artifacts"][0][
        "lineage_binding_hash"
    ] = None
    mutations.append(false_snapshot_binding)

    false_reproduced_route = json.loads(json.dumps(review))
    false_reproduced_route["routes"][0]["acquisition_integrity_status"] = (
        "reproduced"
    )
    false_reproduced_route["summary"]["acquisition_integrity_counts"] = {
        "reproduced": 1
    }
    false_reproduced_route["summary"]["acquisition_route_integrity_rate_ppm"] = (
        1_000_000
    )
    mutations.append(false_reproduced_route)

    for mutation in mutations:
        with pytest.raises(BundleValidationError):
            validate_document_contract(
                mutation,
                schema,
                schema_name,
                fail_on_unknown_keywords=True,
            )


def test_source_review_schema_rejects_false_snapshot_bound_route(
    authoritative_fixture: _AuthoritativeFixture,
) -> None:
    manifest = _read_json(authoritative_fixture.raw_manifest_path)
    manifest["results"] = []
    _write_json(authoritative_fixture.raw_manifest_path, manifest)
    review = authoritative_fixture.compile().source_review
    assert review["routes"][0]["acquisition_integrity_status"] == "partial"

    forged = json.loads(json.dumps(review))
    route = forged["routes"][0]
    route["acquisition_integrity_status"] = "snapshot_bound"
    counts = forged["summary"]["acquisition_integrity_counts"]
    counts["partial"] -= 1
    if counts["partial"] == 0:
        del counts["partial"]
    counts["snapshot_bound"] = counts.get("snapshot_bound", 0) + 1
    forged["summary"]["snapshot_bound_route_rate_ppm"] = (
        counts["snapshot_bound"]
        * 1_000_000
        // forged["summary"]["route_count"]
    )
    unsigned = {key: value for key, value in forged.items() if key != "review_hash"}
    forged["review_hash"] = canonical_sha256(unsigned)

    schema_name = "sim02c-source-acquisition-review-v2.schema.json"
    with pytest.raises(BundleValidationError):
        validate_document_contract(
            forged,
            _read_json(SCHEMA_ROOT / schema_name),
            schema_name,
            fail_on_unknown_keywords=True,
        )


def test_compilation_schema_rejects_false_reproduced_claim(
    authoritative_fixture: _AuthoritativeFixture,
) -> None:
    summary = authoritative_fixture.compile().summary_data()
    summary["source_summary"]["acquisition_integrity_counts"] = {
        "reproduced": 1
    }
    summary["source_summary"]["acquisition_route_integrity_rate_ppm"] = 1_000_000

    with pytest.raises(BundleValidationError):
        validate_document_contract(
            summary,
            _read_json(
                SCHEMA_ROOT
                / "sim02c-authoritative-intake-compilation-v2.schema.json"
            ),
            "compilation with false reproduced claim",
            fail_on_unknown_keywords=True,
        )
