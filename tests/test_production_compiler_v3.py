from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
import json
from pathlib import Path

import pytest

from _sim02b_fixture import (
    CORE_ARTIFACT_IDS,
    build_test_authoritative_sim02b_fixture,
    rewrite_manifest_artifact,
)
from _sim02c_fixture import (
    TRUST_NOW,
    _sign,
    _provision_test_ledger,
    _write_json,
    build_sim02c_production_fixture,
    production_policy,
)
from champions_sim.env.readiness_v2 import (
    ChampionsReadinessV2Error,
    resolve_champions_readiness_v2,
)
from champions_sim.core import canonical_json
from champions_sim.env.readiness_v3 import (
    ChampionsReadinessV3Error,
    ResolvedChampionsReadinessV3,
    resolve_champions_readiness_v3,
    validate_champions_readiness_v3,
)
from champions_sim.promotion import compiler_v3
from champions_sim.promotion.compiler import PromotionCompilationError
from champions_sim.promotion.compiler_v3 import (
    AttestedProductionPromotionCompilationV3,
    ProductionPromotionV3Error,
    compile_attested_production_promotion_v3,
    derive_production_trust_subject_v1,
    validate_attested_production_promotion_compilation_v3,
)
from champions_sim.promotion.input_manifest import (
    build_production_promotion_input_manifest_v3,
)
from champions_sim.promotion.trust import ProductionTrustAttestationV1
import champions_sim.promotion.trust_enrollment as trust_enrollment_module
from scripts.validate_sim01_bundle import BundleValidationError, validate_document_contract


def _compile_with_context(case, context):
    return compile_attested_production_promotion_v3(
        case.input_manifest,
        attestation=case.attestation,
        trust_context=context,
        development_scenario_corpus=case.sim02b.development_scenario_corpus,
        external_holdout_scenario_corpus=(
            case.sim02b.external_holdout_scenario_corpus
        ),
        replays=dict(case.sim02b.replays),
    )


def test_v3_compiles_revalidates_and_issues_current_context_readiness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = build_sim02c_production_fixture(tmp_path, monkeypatch)

    with pytest.raises(PromotionCompilationError, match="external trust anchor"):
        case.sim02b.compile()

    compilation = case.compile()
    validated = validate_attested_production_promotion_compilation_v3(
        compilation,
        trust_context=case.context,
    )
    readiness = resolve_champions_readiness_v3(
        compilation,
        trust_context=case.context,
    )
    assert validated is compilation
    assert compilation.base_compilation.report.champions_candidate is True
    assert compilation.base_compilation.report.rank1_equivalence_status == "unmeasured"
    assert compilation.to_data()["authorization_status"] == "not_authorization"
    assert compilation.to_data()["current_trust_context_required"] is True
    assert compilation.to_data()["trust_registry_id"] == (
        "sim02c-ephemeral-engineering-registry"
    )
    assert compilation.to_data()["trust_enrollment_id"] == (
        "sim02c-ephemeral-engineering-enrollment"
    )
    assert readiness.to_data()["champions_candidate"] is True
    assert readiness.to_data()["rank1_equivalence_status"] == "unmeasured"
    assert readiness.to_data()["authorization_status"] == "not_authorization"
    assert readiness.to_data()["trust_enrollment_binding_hash"] == (
        compilation._trust_enrollment.enrollment_binding_hash
    )
    validate_champions_readiness_v3(readiness, trust_context=case.context)

    with pytest.raises(
        ChampionsReadinessV2Error,
        match="revalidation failed",
    ):
        resolve_champions_readiness_v2(compilation.base_compilation)


def test_v3_stable_outputs_do_not_change_when_valid_trusted_time_advances(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = build_sim02c_production_fixture(tmp_path, monkeypatch)
    first = case.compile()
    first_readiness = resolve_champions_readiness_v3(
        first,
        trust_context=case.context,
    )
    later_context = case.context_at(TRUST_NOW + timedelta(days=1))
    second = _compile_with_context(case, later_context)
    second_readiness = resolve_champions_readiness_v3(
        first,
        trust_context=later_context,
    )

    assert first.to_json() == second.to_json()
    assert first.compilation_hash == second.compilation_hash
    assert first_readiness.to_json() == second_readiness.to_json()
    assert "verified_at" not in first.to_json()
    assert "verified_at" not in first_readiness.to_json()


def test_v3_portable_documents_are_strict_schemas_and_not_authorization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = build_sim02c_production_fixture(tmp_path, monkeypatch)
    compilation = case.compile()
    readiness = resolve_champions_readiness_v3(
        compilation,
        trust_context=case.context,
    )
    root = Path(__file__).resolve().parents[1]
    documents = (
        (
            compilation.to_data(),
            "sim02c-attested-production-compilation-v3.schema.json",
        ),
        (readiness.to_data(), "sim02c-champions-readiness-v3.schema.json"),
        (
            json.loads(
                compilation.documents[
                    "production-trust-authorization-binding-v1.json"
                ]
            ),
            "sim02c-production-trust-authorization-binding-v1.schema.json",
        ),
    )
    for document, schema_name in documents:
        schema = json.loads(
            (root / "data" / "schemas" / schema_name).read_text(encoding="utf-8")
        )
        validate_document_contract(
            document,
            schema,
            schema_name,
            fail_on_unknown_keywords=True,
        )

    compilation_schema = json.loads(
        (
            root
            / "data"
            / "schemas"
            / "sim02c-attested-production-compilation-v3.schema.json"
        ).read_text(encoding="utf-8")
    )
    duplicate_documents = compilation.to_data()
    duplicate_documents["documents"] = [duplicate_documents["documents"][0]] * 4
    with pytest.raises(BundleValidationError):
        validate_document_contract(
            duplicate_documents,
            compilation_schema,
            "duplicate V3 documents",
            fail_on_unknown_keywords=True,
        )

    portable = (
        compilation.to_json()
        + readiness.to_json()
        + "".join(compilation.documents.values())
    )
    assert str(case.sim02b.artifact_root) not in portable
    assert str(case.trust_root) not in portable
    assert str(case.private_key_path) not in portable
    assert str(case.enrollment_registry_path) not in portable
    assert str(case.context.ledger_path) not in portable
    assert not hasattr(AttestedProductionPromotionCompilationV3, "from_json")
    assert not hasattr(ResolvedChampionsReadinessV3, "from_json")


def test_v3_rejects_test_scope_and_signed_subject_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engineering = build_test_authoritative_sim02b_fixture(tmp_path / "engineering")
    manifest = build_production_promotion_input_manifest_v3(engineering.request)
    with pytest.raises(ProductionPromotionV3Error, match="production_champions"):
        derive_production_trust_subject_v1(
            manifest,
            artifact_root=engineering.artifact_root,
        )

    case = build_sim02c_production_fixture(tmp_path / "production", monkeypatch)
    forged_subject = replace(
        case.subject,
        request_binding_hash="9" * 64,
    )
    forged_statement = replace(
        case.attestation.statement,
        subject=forged_subject,
        subject_hash=forged_subject.subject_hash,
    )
    forged_attestation = ProductionTrustAttestationV1(
        statement=forged_statement,
        signature=case.attestation.signature,
    )
    with pytest.raises(ProductionPromotionV3Error, match="compilation failed"):
        compile_attested_production_promotion_v3(
            case.input_manifest,
            attestation=forged_attestation,
            trust_context=case.context,
            development_scenario_corpus=case.sim02b.development_scenario_corpus,
            external_holdout_scenario_corpus=(
                case.sim02b.external_holdout_scenario_corpus
            ),
            replays=dict(case.sim02b.replays),
        )


def test_v3_current_context_revocation_and_expiry_invalidate_readiness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = build_sim02c_production_fixture(tmp_path, monkeypatch)
    compilation = case.compile()
    readiness = resolve_champions_readiness_v3(
        compilation,
        trust_context=case.context,
    )

    revoked = production_policy(
        case.public_key,
        case.fingerprint,
        revoked_attestation_ids=(case.attestation.statement.attestation_id,),
    )
    revoked_context = case.write_policy(revoked)
    with pytest.raises(ProductionPromotionV3Error, match="recompilation failed"):
        validate_attested_production_promotion_compilation_v3(
            compilation,
            trust_context=revoked_context,
        )
    with pytest.raises(ChampionsReadinessV3Error, match="validation failed"):
        validate_champions_readiness_v3(
            readiness,
            trust_context=revoked_context,
        )

    restored_context = case.write_policy(
        case.policy,
        trusted_time=TRUST_NOW + timedelta(days=300),
    )
    with pytest.raises(ProductionPromotionV3Error, match="recompilation failed"):
        validate_attested_production_promotion_compilation_v3(
            compilation,
            trust_context=restored_context,
        )


def test_v3_revalidation_rejects_artifact_and_document_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = build_sim02c_production_fixture(tmp_path, monkeypatch)
    compilation = case.compile()
    compilation.documents["production-trust-attestation-v1.json"] += " "
    with pytest.raises(ProductionPromotionV3Error, match="document content differs"):
        validate_attested_production_promotion_compilation_v3(
            compilation,
            trust_context=case.context,
        )

    fresh = build_sim02c_production_fixture(tmp_path / "artifact", monkeypatch)
    artifact_compilation = fresh.compile()
    catalog_path = fresh.sim02b.artifact_paths[CORE_ARTIFACT_IDS["catalog"]]
    catalog_path.write_bytes(catalog_path.read_bytes() + b"\n")
    with pytest.raises(ProductionPromotionV3Error):
        validate_attested_production_promotion_compilation_v3(
            artifact_compilation,
            trust_context=fresh.context,
        )


def test_v3_post_compile_subject_check_rejects_toctou_artifact_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = build_sim02c_production_fixture(tmp_path, monkeypatch)
    original = compiler_v3._compile_verified_production_promotion_v3_substance
    catalog_path = case.sim02b.artifact_paths[CORE_ARTIFACT_IDS["catalog"]]

    def mutate_after_compile(*args, **kwargs):
        result = original(*args, **kwargs)
        catalog_path.write_bytes(catalog_path.read_bytes() + b"\n")
        return result

    monkeypatch.setattr(
        compiler_v3,
        "_compile_verified_production_promotion_v3_substance",
        mutate_after_compile,
    )
    with pytest.raises(ProductionPromotionV3Error):
        case.compile()


def test_v3_rejects_change_compile_restore_source_snapshot_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = build_sim02c_production_fixture(tmp_path, monkeypatch)
    original = compiler_v3._compile_verified_production_promotion_v3_substance
    timing_id = CORE_ARTIFACT_IDS["timing_evidence"]
    timing_path = case.sim02b.artifact_paths[timing_id]
    original_timing = timing_path.read_bytes()
    original_manifests = {
        path: path.read_bytes() for path in case.sim02b.manifest_paths
    }

    def compile_transient_snapshot(*args, **kwargs):
        timing = json.loads(original_timing.decode("utf-8"))
        timing["compute_seconds"] = 1799
        rewrite_manifest_artifact(
            case.sim02b,
            timing_id,
            canonical_json(timing),
        )
        try:
            return original(*args, **kwargs)
        finally:
            timing_path.write_bytes(original_timing)
            for path, payload in original_manifests.items():
                path.write_bytes(payload)

    monkeypatch.setattr(
        compiler_v3,
        "_compile_verified_production_promotion_v3_substance",
        compile_transient_snapshot,
    )
    with pytest.raises(ProductionPromotionV3Error, match="base source snapshot"):
        case.compile()


def test_v3_rejects_caller_pinned_policy_that_is_not_out_of_band_enrolled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = build_sim02c_production_fixture(tmp_path, monkeypatch)
    substituted_policy_data = case.policy.to_data()
    substituted_policy_data["expires_at"] = "2029-01-01T00:00:00Z"
    substituted_policy_path = case.trust_root / "caller-substituted-policy.json"
    substituted_policy_hash = _write_json(
        substituted_policy_path,
        substituted_policy_data,
    )
    substituted_context = replace(
        case.context,
        policy_path=substituted_policy_path,
        expected_policy_sha256=substituted_policy_hash,
    )

    with pytest.raises(ProductionPromotionV3Error, match="enrollment"):
        _compile_with_context(case, substituted_context)


def test_v3_revalidation_rejects_registry_drift_revocation_and_removal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = build_sim02c_production_fixture(tmp_path, monkeypatch)
    compilation = case.compile()
    original = case.enrollment_registry_path.read_bytes()

    case.enrollment_registry_path.write_bytes(original + b"\n")
    with pytest.raises(ProductionPromotionV3Error, match="recompilation failed"):
        validate_attested_production_promotion_compilation_v3(
            compilation,
            trust_context=case.context,
        )

    case.enrollment_registry_path.write_bytes(original)
    registry = json.loads(original.decode("utf-8"))
    registry["entries"][0]["status"] = "revoked"
    _write_json(case.enrollment_registry_path, registry)
    with pytest.raises(ProductionPromotionV3Error, match="recompilation failed"):
        validate_attested_production_promotion_compilation_v3(
            compilation,
            trust_context=case.context,
        )

    case.enrollment_registry_path.unlink()
    with pytest.raises(ProductionPromotionV3Error, match="recompilation failed"):
        validate_attested_production_promotion_compilation_v3(
            compilation,
            trust_context=case.context,
        )


def test_v3_default_fixed_registry_is_not_created_by_compiler(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = build_sim02c_production_fixture(tmp_path, monkeypatch)
    absent = (tmp_path / "never-provisioned" / "registry.json").resolve()
    monkeypatch.setattr(
        trust_enrollment_module,
        "production_trust_enrollment_registry_path_v1",
        lambda: absent,
    )

    with pytest.raises(ProductionPromotionV3Error, match="enrollment"):
        case.compile()
    assert not absent.exists()
    assert not absent.parent.exists()


def test_v3_revalidation_requires_the_enrolled_ledger_installation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = build_sim02c_production_fixture(tmp_path, monkeypatch)
    compilation = case.compile()
    ledger_path = case.context.ledger_path

    ledger_path.unlink()
    with pytest.raises(ProductionPromotionV3Error, match="recompilation failed"):
        validate_attested_production_promotion_compilation_v3(
            compilation,
            trust_context=case.context,
        )

    _provision_test_ledger(ledger_path, "replacement-ledger")
    with pytest.raises(ProductionPromotionV3Error, match="recompilation failed"):
        validate_attested_production_promotion_compilation_v3(
            compilation,
            trust_context=case.context,
        )
