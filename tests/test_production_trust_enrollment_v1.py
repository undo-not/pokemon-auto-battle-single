from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import base64
import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from champions_sim.promotion import trust_enrollment as enrollment_module
from champions_sim.promotion.trust import (
    PRODUCTION_TRUST_ALGORITHM,
    PRODUCTION_TRUST_ENVIRONMENT,
    PRODUCTION_TRUST_NAMESPACE,
    PRODUCTION_TRUST_PROJECT_ID,
    PRODUCTION_TRUST_PURPOSE,
    PRODUCTION_TRUST_SCHEMA_VERSION,
    PRODUCTION_TRUST_SCOPE,
    ProductionTrustContextV1,
    ProductionTrustIssuerV1,
    ProductionTrustPolicyV1,
    ProductionTrustPublicKeyV1,
    ProductionTrustStatusV1,
    ResolvedProductionTrustV1,
)
from champions_sim.promotion.trust_enrollment import (
    PRODUCTION_TRUST_ENROLLMENT_DOMAIN,
    PRODUCTION_TRUST_ENROLLMENT_SCHEMA_VERSION,
    ProductionTrustEnrollmentError,
    load_production_trust_enrollment_registry_v1,
    parse_production_trust_enrollment_registry_v1,
    production_trust_ledger_path_binding_hash_v1,
    revalidate_production_trust_enrollment_v1,
    resolve_production_trust_enrollment_v1,
    validate_production_trust_receipt_enrollment_v1,
)
from scripts.validate_sim01_bundle import validate_document_contract


NOW = datetime(2026, 7, 14, 12, 0, 0, tzinfo=timezone.utc)


@dataclass(frozen=True)
class _Case:
    artifact_root: Path
    trust_root: Path
    policy_path: Path
    policy_sha256: str
    ssh_path: Path
    ssh_sha256: str
    registry_path: Path
    registry_data: dict[str, object]
    context: ProductionTrustContextV1
    public_key: str
    fingerprint: str


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _write_json(path: Path, value: object) -> str:
    payload = _json_bytes(value)
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def _wire_string(value: bytes) -> bytes:
    return len(value).to_bytes(4, "big") + value


def _provision_ledger(path: Path, ledger_instance_id: str = "ledger-test") -> None:
    connection = sqlite3.connect(str(path))
    try:
        connection.execute(
            """
            CREATE TABLE production_trust_ledger_identity (
                singleton INTEGER PRIMARY KEY NOT NULL CHECK (singleton = 1),
                ledger_instance_id TEXT NOT NULL UNIQUE
            ) STRICT
            """
        )
        connection.execute(
            "INSERT INTO production_trust_ledger_identity"
            "(singleton, ledger_instance_id) VALUES (1, ?)",
            (ledger_instance_id,),
        )
        connection.commit()
    finally:
        connection.close()


def _test_public_key() -> tuple[str, str]:
    blob = _wire_string(b"ssh-ed25519") + _wire_string(bytes(range(32)))
    public_key = "ssh-ed25519 " + base64.b64encode(blob).decode("ascii")
    fingerprint = "SHA256:" + base64.b64encode(
        hashlib.sha256(blob).digest()
    ).decode("ascii").rstrip("=")
    return public_key, fingerprint


def _policy(
    public_key: str,
    fingerprint: str,
    *,
    policy_id: str = "policy-test",
    epoch: int = 1,
) -> ProductionTrustPolicyV1:
    key = ProductionTrustPublicKeyV1(
        key_id="key-test",
        algorithm=PRODUCTION_TRUST_ALGORITHM,
        public_key=public_key,
        fingerprint_sha256=fingerprint,
        status=ProductionTrustStatusV1.ACTIVE,
        not_before="2026-01-01T00:00:00Z",
        expires_at="2028-01-01T00:00:00Z",
    )
    issuer = ProductionTrustIssuerV1(
        issuer_id="issuer-test",
        status=ProductionTrustStatusV1.ACTIVE,
        keys=(key,),
    )
    return ProductionTrustPolicyV1(
        schema_version=PRODUCTION_TRUST_SCHEMA_VERSION,
        policy_id=policy_id,
        policy_epoch=epoch,
        project_id=PRODUCTION_TRUST_PROJECT_ID,
        purpose=PRODUCTION_TRUST_PURPOSE,
        environment=PRODUCTION_TRUST_ENVIRONMENT,
        attestation_scope=PRODUCTION_TRUST_SCOPE,
        algorithm=PRODUCTION_TRUST_ALGORITHM,
        namespace=PRODUCTION_TRUST_NAMESPACE,
        valid_from="2026-01-01T00:00:00Z",
        expires_at="2028-01-01T00:00:00Z",
        minimum_attestation_policy_epoch=epoch,
        issuers=(issuer,),
        revoked_attestation_ids=(),
    )


def _registry_entry(case: _Case, **overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "enrollment_id": "enrollment-main",
        "status": "active",
        "policy_id": "policy-test",
        "policy_sha256": case.policy_sha256,
        "ssh_keygen_sha256": case.ssh_sha256,
        "ledger_instance_id": "ledger-test",
        "ledger_path_binding_hash": production_trust_ledger_path_binding_hash_v1(
            case.context.ledger_path
        ),
        "minimum_policy_epoch": 1,
        "not_before": "2026-07-01T00:00:00Z",
        "expires_at": "2027-01-01T00:00:00Z",
    }
    value.update(overrides)
    return value


def _registry(case: _Case, entries: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema_version": PRODUCTION_TRUST_ENROLLMENT_SCHEMA_VERSION,
        "domain": PRODUCTION_TRUST_ENROLLMENT_DOMAIN,
        "registry_id": "registry-test",
        "project_id": PRODUCTION_TRUST_PROJECT_ID,
        "purpose": PRODUCTION_TRUST_PURPOSE,
        "environment": PRODUCTION_TRUST_ENVIRONMENT,
        "attestation_scope": PRODUCTION_TRUST_SCOPE,
        "entries": entries,
    }


@pytest.fixture
def case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Case:
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    trust_root = tmp_path / "external-trust"
    trust_root.mkdir()
    public_key, fingerprint = _test_public_key()
    policy_path = trust_root / "policy.json"
    policy_sha256 = _write_json(
        policy_path,
        _policy(public_key, fingerprint).to_data(),
    )
    ssh_path = trust_root / "ssh-keygen-test-binary"
    ssh_path.write_bytes(b"test-only verifier bytes\n")
    ssh_sha256 = hashlib.sha256(ssh_path.read_bytes()).hexdigest()
    registry_path = trust_root / "enrollment-registry-v1.json"
    ledger_path = (trust_root / "ledger.sqlite3").resolve()
    _provision_ledger(ledger_path)
    context = ProductionTrustContextV1(
        artifact_root=artifact_root.resolve(),
        policy_path=policy_path.resolve(),
        expected_policy_sha256=policy_sha256,
        ledger_path=ledger_path,
        trusted_time=NOW,
        ssh_keygen_path=ssh_path.resolve(),
        expected_ssh_keygen_sha256=ssh_sha256,
    )
    partial = _Case(
        artifact_root=artifact_root,
        trust_root=trust_root,
        policy_path=policy_path,
        policy_sha256=policy_sha256,
        ssh_path=ssh_path,
        ssh_sha256=ssh_sha256,
        registry_path=registry_path,
        registry_data={},
        context=context,
        public_key=public_key,
        fingerprint=fingerprint,
    )
    registry_data = _registry(partial, [_registry_entry(partial)])
    _write_json(registry_path, registry_data)
    monkeypatch.setattr(
        enrollment_module,
        "production_trust_enrollment_registry_path_v1",
        lambda: registry_path.resolve(),
    )
    return replace(partial, registry_data=registry_data)


def test_fixed_registry_resolves_exact_binding_and_matches_schema(case: _Case) -> None:
    registry, registry_sha256 = load_production_trust_enrollment_registry_v1()
    resolved = resolve_production_trust_enrollment_v1(case.context)

    assert parse_production_trust_enrollment_registry_v1(registry.to_data()) == registry
    assert resolved.registry_id == "registry-test"
    assert resolved.registry_sha256 == registry_sha256
    assert resolved.enrollment_id == "enrollment-main"
    assert resolved.policy_sha256 == case.policy_sha256
    assert resolved.ssh_keygen_sha256 == case.ssh_sha256
    assert resolved.ledger_instance_id == "ledger-test"
    assert resolved.ledger_path_binding_hash == (
        production_trust_ledger_path_binding_hash_v1(case.context.ledger_path)
    )
    assert len(resolved.enrollment_binding_hash) == 64

    schema_path = (
        Path(__file__).resolve().parents[1]
        / "data"
        / "schemas"
        / "sim02c-production-trust-enrollment-registry-v1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validate_document_contract(
        registry.to_data(),
        schema,
        "production trust enrollment registry",
        fail_on_unknown_keywords=True,
    )


def test_context_and_self_created_policy_cannot_self_enroll(case: _Case) -> None:
    foreign_path = case.trust_root / "caller-policy.json"
    foreign_sha256 = _write_json(
        foreign_path,
        _policy(
            case.public_key,
            case.fingerprint,
            policy_id="policy-created-by-caller",
        ).to_data(),
    )
    foreign_context = replace(
        case.context,
        policy_path=foreign_path.resolve(),
        expected_policy_sha256=foreign_sha256,
    )

    with pytest.raises(ProductionTrustEnrollmentError, match="no unique active"):
        resolve_production_trust_enrollment_v1(foreign_context)


def test_missing_fixed_registry_rejects_even_valid_context(
    case: _Case, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = case.trust_root / "not-enrolled.json"
    monkeypatch.setattr(
        enrollment_module,
        "production_trust_enrollment_registry_path_v1",
        lambda: missing.resolve(),
    )
    with pytest.raises(ProductionTrustEnrollmentError, match="unavailable"):
        resolve_production_trust_enrollment_v1(case.context)


def test_registry_inside_artifact_root_is_rejected(
    case: _Case, monkeypatch: pytest.MonkeyPatch
) -> None:
    internal = case.artifact_root / "enrollment-registry-v1.json"
    internal.write_bytes(case.registry_path.read_bytes())
    monkeypatch.setattr(
        enrollment_module,
        "production_trust_enrollment_registry_path_v1",
        lambda: internal.resolve(),
    )
    with pytest.raises(ProductionTrustEnrollmentError, match="outside artifact_root"):
        resolve_production_trust_enrollment_v1(case.context)


def test_registry_strict_json_rejects_duplicate_and_unknown_keys(case: _Case) -> None:
    raw = _json_bytes(case.registry_data).decode("utf-8")
    duplicate_path = case.trust_root / "duplicate-registry.json"
    duplicate_path.write_text(
        raw.replace(
            '"registry_id":"registry-test"',
            '"registry_id":"shadow","registry_id":"registry-test"',
            1,
        ),
        encoding="utf-8",
    )
    with pytest.raises(ProductionTrustEnrollmentError, match="duplicate JSON key"):
        load_production_trust_enrollment_registry_v1(duplicate_path.resolve())

    unknown = deepcopy(case.registry_data)
    unknown["caller_authorized"] = True
    unknown_path = case.trust_root / "unknown-registry.json"
    _write_json(unknown_path, unknown)
    with pytest.raises(ProductionTrustEnrollmentError, match="fields differ"):
        load_production_trust_enrollment_registry_v1(unknown_path.resolve())

    entry_unknown = deepcopy(case.registry_data)
    entry_unknown["entries"][0]["caller_verified"] = True  # type: ignore[index]
    with pytest.raises(ProductionTrustEnrollmentError, match="fields differ"):
        parse_production_trust_enrollment_registry_v1(entry_unknown)


def test_registry_rejects_duplicate_or_ambiguous_enrollments(case: _Case) -> None:
    duplicate_id = _registry(
        case,
        [
            _registry_entry(case),
            _registry_entry(case, status="revoked"),
        ],
    )
    with pytest.raises(ProductionTrustEnrollmentError, match="unique and ordered"):
        parse_production_trust_enrollment_registry_v1(duplicate_id)

    ambiguous = _registry(
        case,
        [
            _registry_entry(case, enrollment_id="enrollment-a"),
            _registry_entry(case, enrollment_id="enrollment-b"),
        ],
    )
    _write_json(case.registry_path, ambiguous)
    with pytest.raises(ProductionTrustEnrollmentError, match="no unique active"):
        resolve_production_trust_enrollment_v1(case.context)


@pytest.mark.parametrize(
    ("overrides", "trusted_time"),
    [
        ({"status": "revoked"}, NOW),
        ({"expires_at": "2026-07-14T11:59:59Z"}, NOW),
        ({"not_before": "2026-07-14T12:00:01Z"}, NOW),
    ],
)
def test_revoked_expired_and_not_yet_valid_enrollment_rejects(
    case: _Case,
    overrides: dict[str, object],
    trusted_time: datetime,
) -> None:
    _write_json(
        case.registry_path,
        _registry(case, [_registry_entry(case, **overrides)]),
    )
    with pytest.raises(ProductionTrustEnrollmentError, match="no unique active"):
        resolve_production_trust_enrollment_v1(
            replace(case.context, trusted_time=trusted_time)
        )


def test_policy_hash_ssh_hash_and_minimum_epoch_are_bound(case: _Case) -> None:
    with pytest.raises(ProductionTrustEnrollmentError, match="policy pin differs"):
        resolve_production_trust_enrollment_v1(
            replace(case.context, expected_policy_sha256="0" * 64)
        )

    with pytest.raises(ProductionTrustEnrollmentError, match="no unique active"):
        resolve_production_trust_enrollment_v1(
            replace(case.context, expected_ssh_keygen_sha256="0" * 64)
        )

    _write_json(
        case.registry_path,
        _registry(case, [_registry_entry(case, minimum_policy_epoch=2)]),
    )
    with pytest.raises(ProductionTrustEnrollmentError, match="no unique active"):
        resolve_production_trust_enrollment_v1(case.context)


def test_ledger_path_identity_removal_and_replacement_are_fail_closed(
    case: _Case,
) -> None:
    alternate = (case.trust_root / "alternate-ledger.sqlite3").resolve()
    _provision_ledger(alternate, "ledger-test")
    with pytest.raises(ProductionTrustEnrollmentError, match="no unique active"):
        resolve_production_trust_enrollment_v1(
            replace(case.context, ledger_path=alternate)
        )

    case.context.ledger_path.unlink()
    with pytest.raises(ProductionTrustEnrollmentError, match="ledger is unavailable"):
        resolve_production_trust_enrollment_v1(case.context)

    case.context.ledger_path.write_bytes(b"")
    with pytest.raises(ProductionTrustEnrollmentError, match="identity"):
        resolve_production_trust_enrollment_v1(case.context)


def test_registry_parser_rejects_noncanonical_types_and_timestamps(case: _Case) -> None:
    too_large = _registry(
        case,
        [_registry_entry(case, minimum_policy_epoch=9_223_372_036_854_775_808)],
    )
    with pytest.raises(ProductionTrustEnrollmentError, match="signed-64-bit"):
        parse_production_trust_enrollment_registry_v1(too_large)

    non_rfc3339 = _registry(
        case,
        [_registry_entry(case, not_before="2026-07-01 00:00:00+00:00")],
    )
    with pytest.raises(ProductionTrustEnrollmentError, match="RFC 3339"):
        parse_production_trust_enrollment_registry_v1(non_rfc3339)

    boolean_epoch = _registry(
        case,
        [_registry_entry(case, minimum_policy_epoch=True)],
    )
    with pytest.raises(ProductionTrustEnrollmentError, match="exact integer"):
        parse_production_trust_enrollment_registry_v1(boolean_epoch)


def test_registry_drift_is_detected_by_exact_revalidation(case: _Case) -> None:
    first = resolve_production_trust_enrollment_v1(case.context)
    drifted = _registry(
        case,
        [
            _registry_entry(case),
            _registry_entry(
                case,
                enrollment_id="enrollment-retired",
                status="revoked",
            ),
        ],
    )
    _write_json(case.registry_path, drifted)

    second = resolve_production_trust_enrollment_v1(case.context)
    assert second.registry_sha256 != first.registry_sha256
    with pytest.raises(ProductionTrustEnrollmentError, match="changed"):
        revalidate_production_trust_enrollment_v1(case.context, first)


def test_receipt_must_match_enrolled_policy_and_minimum_epoch(case: _Case) -> None:
    enrollment = resolve_production_trust_enrollment_v1(case.context)
    receipt = ResolvedProductionTrustV1(
        schema_version=PRODUCTION_TRUST_SCHEMA_VERSION,
        domain="champions-sim.production-trust-attestation.v1",
        attestation_id="attestation-test",
        attestation_hash="1" * 64,
        subject_hash="2" * 64,
        policy_id="policy-test",
        policy_epoch=1,
        policy_sha256=case.policy_sha256,
        issuer_id="issuer-test",
        key_id="key-test",
        key_fingerprint_sha256=case.fingerprint,
        algorithm=PRODUCTION_TRUST_ALGORITHM,
        namespace=PRODUCTION_TRUST_NAMESPACE,
        verified_at="2026-07-14T12:00:00Z",
        ledger_binding_hash="3" * 64,
    )
    validate_production_trust_receipt_enrollment_v1(enrollment, receipt)

    with pytest.raises(ProductionTrustEnrollmentError, match="differs"):
        validate_production_trust_receipt_enrollment_v1(
            enrollment,
            replace(receipt, policy_sha256="0" * 64),
        )
    stricter = replace(enrollment, minimum_policy_epoch=2)
    with pytest.raises(ProductionTrustEnrollmentError, match="differs"):
        validate_production_trust_receipt_enrollment_v1(stricter, receipt)
