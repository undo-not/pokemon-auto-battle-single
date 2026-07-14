from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import base64
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from champions_sim.promotion.trust import (
    PRODUCTION_TRUST_ALGORITHM,
    PRODUCTION_TRUST_CANONICALIZATION,
    PRODUCTION_TRUST_DOMAIN,
    PRODUCTION_TRUST_ENVIRONMENT,
    PRODUCTION_TRUST_NAMESPACE,
    PRODUCTION_TRUST_PROJECT_ID,
    PRODUCTION_TRUST_PURPOSE,
    PRODUCTION_TRUST_SCHEMA_VERSION,
    PRODUCTION_TRUST_SCOPE,
    ProductionTrustAttestationStatementV1,
    ProductionTrustAttestationV1,
    ProductionTrustContextV1,
    ProductionTrustError,
    ProductionTrustIssuerV1,
    ProductionTrustPolicyV1,
    ProductionTrustPublicKeyV1,
    ProductionTrustStatusV1,
    ProductionTrustSubjectV1,
    encode_production_trust_signed_message_v1,
    load_production_trust_attestation_v1,
    load_production_trust_policy_v1,
    parse_resolved_production_trust_v1,
    verify_production_trust_v1,
)
from scripts.validate_sim01_bundle import validate_document_contract


NOW = datetime(2026, 7, 14, 12, 0, 0, tzinfo=timezone.utc)
SSH_KEYGEN = shutil.which("ssh-keygen")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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


def _generate_key(root: Path, name: str) -> tuple[Path, str, str]:
    if SSH_KEYGEN is None:
        pytest.skip("OpenSSH ssh-keygen is required for SIM-02C trust tests")
    key_path = root / name
    completed = subprocess.run(
        [SSH_KEYGEN, "-q", "-t", "ed25519", "-N", "", "-C", "", "-f", str(key_path)],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
    )
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    public_parts = key_path.with_suffix(".pub").read_text(encoding="ascii").split()
    public_key = " ".join(public_parts[:2])
    blob = base64.b64decode(public_parts[1], validate=True)
    fingerprint = "SHA256:" + base64.b64encode(
        hashlib.sha256(blob).digest()
    ).decode("ascii").rstrip("=")
    return key_path, public_key, fingerprint


def _subject(*, request_hash: str | None = None) -> ProductionTrustSubjectV1:
    return ProductionTrustSubjectV1(
        schema_version=PRODUCTION_TRUST_SCHEMA_VERSION,
        domain=PRODUCTION_TRUST_DOMAIN,
        project_id=PRODUCTION_TRUST_PROJECT_ID,
        purpose=PRODUCTION_TRUST_PURPOSE,
        environment=PRODUCTION_TRUST_ENVIRONMENT,
        compiler_contract_version="sim02c-compiler-v3",
        attestation_scope=PRODUCTION_TRUST_SCOPE,
        regulation_id="regulation-m-b",
        regulation_revision="2026-07-01",
        regulation_hash="1" * 64,
        target_pool_id="target-pool-m-b",
        target_pool_hash="2" * 64,
        source_authority_subject_hash="3" * 64,
        request_binding_hash=request_hash or "4" * 64,
        replay_binding_hash="5" * 64,
    )


def _statement(
    subject: ProductionTrustSubjectV1,
    *,
    attestation_id: str = "attestation-001",
    issuer_id: str = "issuer-test",
    key_id: str = "key-test",
    policy_epoch: int = 1,
    expires_at: str = "2027-01-01T00:00:00Z",
) -> ProductionTrustAttestationStatementV1:
    return ProductionTrustAttestationStatementV1(
        schema_version=PRODUCTION_TRUST_SCHEMA_VERSION,
        canonicalization=PRODUCTION_TRUST_CANONICALIZATION,
        domain=PRODUCTION_TRUST_DOMAIN,
        attestation_id=attestation_id,
        issuer_id=issuer_id,
        key_id=key_id,
        algorithm=PRODUCTION_TRUST_ALGORITHM,
        namespace=PRODUCTION_TRUST_NAMESPACE,
        issued_at="2026-07-14T00:00:00Z",
        not_before="2026-07-14T00:00:00Z",
        expires_at=expires_at,
        policy_id="policy-test",
        policy_epoch=policy_epoch,
        subject=subject,
        subject_hash=subject.subject_hash,
    )


def _sign(
    root: Path,
    key_path: Path,
    statement: ProductionTrustAttestationStatementV1,
    *,
    namespace: str = PRODUCTION_TRUST_NAMESPACE,
    label: str = "statement",
) -> ProductionTrustAttestationV1:
    message_path = root / f"{label}.message"
    message_path.write_bytes(encode_production_trust_signed_message_v1(statement))
    completed = subprocess.run(
        [
            str(SSH_KEYGEN),
            "-Y",
            "sign",
            "-f",
            str(key_path),
            "-n",
            namespace,
            str(message_path),
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
    )
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    signature = message_path.with_suffix(message_path.suffix + ".sig").read_text(
        encoding="ascii"
    )
    return ProductionTrustAttestationV1(statement=statement, signature=signature)


def _policy(
    public_key: str,
    fingerprint: str,
    *,
    epoch: int = 1,
    issuer_status: ProductionTrustStatusV1 = ProductionTrustStatusV1.ACTIVE,
    key_status: ProductionTrustStatusV1 = ProductionTrustStatusV1.ACTIVE,
    revoked_ids: tuple[str, ...] = (),
) -> ProductionTrustPolicyV1:
    key = ProductionTrustPublicKeyV1(
        key_id="key-test",
        algorithm=PRODUCTION_TRUST_ALGORITHM,
        public_key=public_key,
        fingerprint_sha256=fingerprint,
        status=key_status,
        not_before="2026-01-01T00:00:00Z",
        expires_at="2028-01-01T00:00:00Z",
    )
    issuer = ProductionTrustIssuerV1(
        issuer_id="issuer-test",
        status=issuer_status,
        keys=(key,),
    )
    return ProductionTrustPolicyV1(
        schema_version=PRODUCTION_TRUST_SCHEMA_VERSION,
        policy_id="policy-test",
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
        revoked_attestation_ids=revoked_ids,
    )


def _case(tmp_path: Path, *, epoch: int = 1) -> dict[str, object]:
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    trust_root = tmp_path / "external-trust"
    trust_root.mkdir()
    key_path, public_key, fingerprint = _generate_key(trust_root, "issuer-key")
    subject = _subject()
    statement = _statement(subject, policy_epoch=epoch)
    attestation = _sign(trust_root, key_path, statement)
    policy = _policy(public_key, fingerprint, epoch=epoch)
    policy_path = trust_root / "policy.json"
    policy_sha256 = _write_json(policy_path, policy.to_data())
    ssh_path = Path(SSH_KEYGEN).resolve()
    context = ProductionTrustContextV1(
        artifact_root=artifact_root.resolve(),
        policy_path=policy_path.resolve(),
        expected_policy_sha256=policy_sha256,
        ledger_path=(trust_root / "ledger.sqlite3").resolve(),
        trusted_time=NOW,
        ssh_keygen_path=ssh_path,
        expected_ssh_keygen_sha256=_sha256_file(ssh_path),
    )
    return {
        "artifact_root": artifact_root,
        "trust_root": trust_root,
        "key_path": key_path,
        "public_key": public_key,
        "fingerprint": fingerprint,
        "subject": subject,
        "statement": statement,
        "attestation": attestation,
        "policy": policy,
        "policy_path": policy_path,
        "context": context,
    }


def test_external_ed25519_trust_verifies_and_is_idempotent(tmp_path: Path) -> None:
    case = _case(tmp_path)
    receipt = verify_production_trust_v1(
        case["attestation"], case["subject"], case["context"]
    )
    repeated = verify_production_trust_v1(
        case["attestation"], case["subject"], case["context"]
    )

    assert repeated == receipt
    assert parse_resolved_production_trust_v1(receipt.to_data()) == receipt
    assert receipt.subject_hash == case["subject"].subject_hash
    assert receipt.policy_sha256 == case["context"].expected_policy_sha256
    assert receipt.key_fingerprint_sha256 == case["fingerprint"]
    assert len(receipt.trust_receipt_hash) == 64
    assert Path(case["context"].ledger_path).is_file()


def test_trust_documents_round_trip_and_match_strict_schemas(tmp_path: Path) -> None:
    case = _case(tmp_path)
    attestation_path = Path(case["trust_root"]) / "attestation.json"
    _write_json(attestation_path, case["attestation"].to_data())

    loaded_attestation = load_production_trust_attestation_v1(attestation_path)
    loaded_policy = load_production_trust_policy_v1(case["policy_path"])
    receipt = verify_production_trust_v1(
        loaded_attestation,
        case["subject"],
        case["context"],
    )

    schema_root = Path(__file__).resolve().parents[1] / "data" / "schemas"
    documents = (
        (
            loaded_attestation.to_data(),
            "sim02c-production-trust-attestation-v1.schema.json",
        ),
        (loaded_policy.to_data(), "sim02c-production-trust-policy-v1.schema.json"),
        (receipt.to_data(), "sim02c-resolved-production-trust-v1.schema.json"),
    )
    for document, schema_name in documents:
        schema = json.loads((schema_root / schema_name).read_text(encoding="utf-8"))
        validate_document_contract(
            document,
            schema,
            schema_name,
            fail_on_unknown_keywords=True,
        )


def test_wrong_subject_and_wrong_signature_namespace_fail_closed(tmp_path: Path) -> None:
    case = _case(tmp_path)
    with pytest.raises(ProductionTrustError, match="differs from expected"):
        verify_production_trust_v1(
            case["attestation"],
            _subject(request_hash="9" * 64),
            case["context"],
        )

    wrong_namespace = _sign(
        case["trust_root"],
        case["key_path"],
        case["statement"],
        namespace="unrelated-protocol",
        label="wrong-namespace",
    )
    with pytest.raises(ProductionTrustError, match="signature verification failed"):
        verify_production_trust_v1(
            wrong_namespace,
            case["subject"],
            case["context"],
        )

    wrong_key_path, _, _ = _generate_key(case["trust_root"], "wrong-issuer-key")
    wrong_key = _sign(
        case["trust_root"],
        wrong_key_path,
        case["statement"],
        label="wrong-key",
    )
    with pytest.raises(ProductionTrustError, match="signature verification failed"):
        verify_production_trust_v1(
            wrong_key,
            case["subject"],
            case["context"],
        )


@pytest.mark.parametrize(
    ("issuer_id", "key_id", "message"),
    [
        ("issuer-not-enrolled", "key-test", "issuer is not enrolled"),
        ("issuer-test", "key-not-enrolled", "key is not enrolled"),
    ],
)
def test_unenrolled_issuer_or_key_fails_closed(
    tmp_path: Path, issuer_id: str, key_id: str, message: str
) -> None:
    case = _case(tmp_path)
    statement = _statement(
        case["subject"],
        attestation_id=f"attestation-{issuer_id}-{key_id}",
        issuer_id=issuer_id,
        key_id=key_id,
    )
    attestation = _sign(
        case["trust_root"],
        case["key_path"],
        statement,
        label=f"unenrolled-{issuer_id}-{key_id}",
    )
    with pytest.raises(ProductionTrustError, match=message):
        verify_production_trust_v1(
            attestation,
            case["subject"],
            case["context"],
        )


@pytest.mark.parametrize("revocation_kind", ["issuer", "key", "attestation"])
def test_revocation_state_fails_closed(tmp_path: Path, revocation_kind: str) -> None:
    case = _case(tmp_path)
    policy = _policy(
        case["public_key"],
        case["fingerprint"],
        issuer_status=(
            ProductionTrustStatusV1.REVOKED
            if revocation_kind == "issuer"
            else ProductionTrustStatusV1.ACTIVE
        ),
        key_status=(
            ProductionTrustStatusV1.REVOKED
            if revocation_kind == "key"
            else ProductionTrustStatusV1.ACTIVE
        ),
        revoked_ids=("attestation-001",) if revocation_kind == "attestation" else (),
    )
    policy_hash = _write_json(case["policy_path"], policy.to_data())
    context = replace(case["context"], expected_policy_sha256=policy_hash)
    with pytest.raises(ProductionTrustError, match="revoked"):
        verify_production_trust_v1(case["attestation"], case["subject"], context)


def test_expiry_and_trusted_clock_future_issuance_fail_closed(tmp_path: Path) -> None:
    case = _case(tmp_path)
    expired_statement = _statement(
        case["subject"],
        attestation_id="attestation-expired",
        expires_at="2026-07-14T01:00:00Z",
    )
    expired = _sign(
        case["trust_root"], case["key_path"], expired_statement, label="expired"
    )
    with pytest.raises(ProductionTrustError, match="expired"):
        verify_production_trust_v1(expired, case["subject"], case["context"])

    future_statement = replace(
        case["statement"],
        attestation_id="attestation-future",
        issued_at="2026-07-15T00:00:00Z",
        not_before="2026-07-15T00:00:00Z",
    )
    future = _sign(
        case["trust_root"], case["key_path"], future_statement, label="future"
    )
    with pytest.raises(ProductionTrustError, match="not yet valid|future"):
        verify_production_trust_v1(future, case["subject"], case["context"])


def test_policy_and_ssh_binary_hash_pins_fail_before_verification(tmp_path: Path) -> None:
    case = _case(tmp_path)
    with pytest.raises(ProductionTrustError, match="policy SHA-256 pin mismatch"):
        verify_production_trust_v1(
            case["attestation"],
            case["subject"],
            replace(case["context"], expected_policy_sha256="0" * 64),
        )
    with pytest.raises(ProductionTrustError, match="executable SHA-256 pin mismatch"):
        verify_production_trust_v1(
            case["attestation"],
            case["subject"],
            replace(case["context"], expected_ssh_keygen_sha256="0" * 64),
        )


@pytest.mark.parametrize("external_name", ["policy", "ledger", "ssh"])
def test_trust_state_inside_artifact_root_is_rejected(
    tmp_path: Path, external_name: str
) -> None:
    case = _case(tmp_path)
    artifact_root = Path(case["artifact_root"]).resolve()
    context = case["context"]
    if external_name == "policy":
        internal = artifact_root / "policy.json"
        internal.write_bytes(Path(case["policy_path"]).read_bytes())
        context = replace(context, policy_path=internal)
    elif external_name == "ledger":
        context = replace(context, ledger_path=artifact_root / "ledger.sqlite3")
    else:
        internal = artifact_root / Path(context.ssh_keygen_path).name
        shutil.copyfile(context.ssh_keygen_path, internal)
        context = replace(context, ssh_keygen_path=internal)
    with pytest.raises(ProductionTrustError, match="outside artifact_root"):
        verify_production_trust_v1(case["attestation"], case["subject"], context)


def test_ledger_rejects_same_id_with_changed_valid_envelope(tmp_path: Path) -> None:
    case = _case(tmp_path)
    verify_production_trust_v1(case["attestation"], case["subject"], case["context"])
    changed_statement = replace(
        case["statement"], expires_at="2027-02-01T00:00:00Z"
    )
    changed = _sign(
        case["trust_root"], case["key_path"], changed_statement, label="changed-envelope"
    )
    with pytest.raises(ProductionTrustError, match="ledger conflict"):
        verify_production_trust_v1(changed, case["subject"], case["context"])


def test_ledger_rejects_policy_epoch_rollback(tmp_path: Path) -> None:
    case = _case(tmp_path, epoch=2)
    verify_production_trust_v1(case["attestation"], case["subject"], case["context"])

    old_statement = _statement(
        case["subject"],
        attestation_id="attestation-old-policy",
        policy_epoch=1,
    )
    old_attestation = _sign(
        case["trust_root"], case["key_path"], old_statement, label="old-policy"
    )
    old_policy = _policy(case["public_key"], case["fingerprint"], epoch=1)
    old_policy_hash = _write_json(case["policy_path"], old_policy.to_data())
    old_context = replace(case["context"], expected_policy_sha256=old_policy_hash)
    with pytest.raises(ProductionTrustError, match="epoch rollback"):
        verify_production_trust_v1(old_attestation, case["subject"], old_context)


def test_strict_json_rejects_duplicate_and_unknown_fields(tmp_path: Path) -> None:
    case = _case(tmp_path)
    attestation_path = Path(case["trust_root"]) / "duplicate.json"
    raw = _json_bytes(case["attestation"].to_data()).decode("utf-8")
    duplicate = raw.replace(
        '"statement":',
        '"unexpected":false,"unexpected":true,"statement":',
        1,
    )
    attestation_path.write_text(duplicate, encoding="utf-8")
    with pytest.raises(ProductionTrustError, match="duplicate JSON key"):
        load_production_trust_attestation_v1(attestation_path)

    unknown = case["attestation"].to_data()
    unknown["caller_verified"] = True
    _write_json(attestation_path, unknown)
    with pytest.raises(ProductionTrustError, match="fields differ"):
        load_production_trust_attestation_v1(attestation_path)
