"""Ephemeral SIM-02C production-trust fixture for integration tests only."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import base64
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
from typing import Any

import pytest

import _sim02b_fixture as fixture_module
from _sim02b_fixture import (
    CORE_ARTIFACT_IDS,
    Sim02BTestAuthoritativeFixture,
    build_test_authoritative_sim02b_fixture,
    rewrite_manifest_artifact,
    rewrite_source_manifests_as_production_claim,
)
from champions_sim.core import canonical_json
from champions_sim.promotion.compiler_v3 import (
    AttestedProductionPromotionCompilationV3,
    compile_attested_production_promotion_v3,
    derive_production_trust_subject_v1,
)
from champions_sim.promotion.input_manifest import (
    ProductionPromotionInputManifestV3,
    build_production_promotion_input_manifest_v3,
)
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
    ProductionTrustIssuerV1,
    ProductionTrustPolicyV1,
    ProductionTrustPublicKeyV1,
    ProductionTrustStatusV1,
    ProductionTrustSubjectV1,
    encode_production_trust_signed_message_v1,
)
import champions_sim.promotion.trust_enrollment as trust_enrollment_module
from champions_sim.promotion.trust_enrollment import (
    PRODUCTION_TRUST_ENROLLMENT_DOMAIN,
    PRODUCTION_TRUST_ENROLLMENT_SCHEMA_VERSION,
    production_trust_ledger_path_binding_hash_v1,
)


TRUST_NOW = datetime(2026, 7, 14, 12, 0, 0, tzinfo=timezone.utc)


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> str:
    payload = canonical_json(value).encode("utf-8")
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def _generate_key(root: Path) -> tuple[Path, str, str, Path]:
    executable = shutil.which("ssh-keygen")
    if executable is None:
        pytest.skip("OpenSSH ssh-keygen is required for SIM-02C integration tests")
    ssh_path = Path(executable).resolve()
    key_path = root / "ephemeral-test-issuer"
    completed = subprocess.run(
        [
            str(ssh_path),
            "-q",
            "-t",
            "ed25519",
            "-N",
            "",
            "-C",
            "",
            "-f",
            str(key_path),
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
    )
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    parts = key_path.with_suffix(".pub").read_text(encoding="ascii").split()
    public_key = " ".join(parts[:2])
    blob = base64.b64decode(parts[1], validate=True)
    fingerprint = "SHA256:" + base64.b64encode(
        hashlib.sha256(blob).digest()
    ).decode("ascii").rstrip("=")
    return key_path, public_key, fingerprint, ssh_path


def _provision_test_ledger(path: Path, ledger_instance_id: str) -> None:
    connection = sqlite3.connect(str(path))
    try:
        connection.execute("PRAGMA trusted_schema = OFF")
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


def _sign(
    root: Path,
    key_path: Path,
    statement: ProductionTrustAttestationStatementV1,
) -> ProductionTrustAttestationV1:
    executable = shutil.which("ssh-keygen")
    assert executable is not None
    message_path = root / "production-attestation.message"
    message_path.write_bytes(encode_production_trust_signed_message_v1(statement))
    completed = subprocess.run(
        [
            executable,
            "-Y",
            "sign",
            "-f",
            str(key_path),
            "-n",
            PRODUCTION_TRUST_NAMESPACE,
            str(message_path),
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
    )
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    signature = message_path.with_suffix(".message.sig").read_text(encoding="ascii")
    return ProductionTrustAttestationV1(statement=statement, signature=signature)


def production_policy(
    public_key: str,
    fingerprint: str,
    *,
    revoked_attestation_ids: tuple[str, ...] = (),
) -> ProductionTrustPolicyV1:
    return ProductionTrustPolicyV1(
        schema_version=PRODUCTION_TRUST_SCHEMA_VERSION,
        policy_id="sim02c-ephemeral-test-policy",
        policy_epoch=1,
        project_id=PRODUCTION_TRUST_PROJECT_ID,
        purpose=PRODUCTION_TRUST_PURPOSE,
        environment=PRODUCTION_TRUST_ENVIRONMENT,
        attestation_scope=PRODUCTION_TRUST_SCOPE,
        algorithm=PRODUCTION_TRUST_ALGORITHM,
        namespace=PRODUCTION_TRUST_NAMESPACE,
        valid_from="2026-01-01T00:00:00Z",
        expires_at="2028-01-01T00:00:00Z",
        minimum_attestation_policy_epoch=1,
        issuers=(
            ProductionTrustIssuerV1(
                issuer_id="sim02c-ephemeral-test-issuer",
                status=ProductionTrustStatusV1.ACTIVE,
                keys=(
                    ProductionTrustPublicKeyV1(
                        key_id="sim02c-ephemeral-test-key",
                        algorithm=PRODUCTION_TRUST_ALGORITHM,
                        public_key=public_key,
                        fingerprint_sha256=fingerprint,
                        status=ProductionTrustStatusV1.ACTIVE,
                        not_before="2026-01-01T00:00:00Z",
                        expires_at="2028-01-01T00:00:00Z",
                    ),
                ),
            ),
        ),
        revoked_attestation_ids=revoked_attestation_ids,
    )


@dataclass(frozen=True, slots=True)
class Sim02CProductionFixture:
    sim02b: Sim02BTestAuthoritativeFixture
    input_manifest: ProductionPromotionInputManifestV3
    subject: ProductionTrustSubjectV1
    attestation: ProductionTrustAttestationV1
    policy: ProductionTrustPolicyV1
    context: ProductionTrustContextV1
    trust_root: Path
    policy_path: Path
    enrollment_registry_path: Path
    private_key_path: Path
    public_key: str
    fingerprint: str

    def compile(self) -> AttestedProductionPromotionCompilationV3:
        return compile_attested_production_promotion_v3(
            self.input_manifest,
            attestation=self.attestation,
            trust_context=self.context,
            development_scenario_corpus=self.sim02b.development_scenario_corpus,
            external_holdout_scenario_corpus=(
                self.sim02b.external_holdout_scenario_corpus
            ),
            replays=dict(self.sim02b.replays),
        )

    def context_at(self, trusted_time: datetime) -> ProductionTrustContextV1:
        return replace(self.context, trusted_time=trusted_time)

    def write_policy(
        self,
        policy: ProductionTrustPolicyV1,
        *,
        trusted_time: datetime | None = None,
    ) -> ProductionTrustContextV1:
        digest = _write_json(self.policy_path, policy.to_data())
        return replace(
            self.context,
            expected_policy_sha256=digest,
            trusted_time=trusted_time or self.context.trusted_time,
        )


def build_sim02c_production_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Sim02CProductionFixture:
    original_regulation = fixture_module._regulation_document

    def current_regulation() -> dict[str, Any]:
        document = original_regulation()
        document.update(
            {
                "status": "current",
                "verification_status": "verified",
                "published_at": "2026-07-13T00:00:00+00:00",
            }
        )
        return document

    monkeypatch.setattr(fixture_module, "_regulation_document", current_regulation)
    sim02b = build_test_authoritative_sim02b_fixture(tmp_path)
    rewrite_source_manifests_as_production_claim(sim02b)
    timing_id = CORE_ARTIFACT_IDS["timing_evidence"]
    timing = json.loads(sim02b.artifact_paths[timing_id].read_text(encoding="utf-8"))
    timing["measurement_status"] = "measured"
    rewrite_manifest_artifact(sim02b, timing_id, canonical_json(timing))

    input_manifest = build_production_promotion_input_manifest_v3(sim02b.request)
    subject = derive_production_trust_subject_v1(
        input_manifest,
        artifact_root=sim02b.artifact_root,
    )

    trust_root = (tmp_path / "external-production-trust").resolve()
    trust_root.mkdir()
    key_path, public_key, fingerprint, ssh_path = _generate_key(trust_root)
    policy = production_policy(public_key, fingerprint)
    policy_path = trust_root / "policy.json"
    policy_sha = _write_json(policy_path, policy.to_data())
    statement = ProductionTrustAttestationStatementV1(
        schema_version=PRODUCTION_TRUST_SCHEMA_VERSION,
        canonicalization=PRODUCTION_TRUST_CANONICALIZATION,
        domain=PRODUCTION_TRUST_DOMAIN,
        attestation_id="sim02c-ephemeral-attestation-001",
        issuer_id="sim02c-ephemeral-test-issuer",
        key_id="sim02c-ephemeral-test-key",
        algorithm=PRODUCTION_TRUST_ALGORITHM,
        namespace=PRODUCTION_TRUST_NAMESPACE,
        issued_at="2026-07-14T00:00:00Z",
        not_before="2026-07-14T00:00:00Z",
        expires_at="2027-01-01T00:00:00Z",
        policy_id=policy.policy_id,
        policy_epoch=policy.policy_epoch,
        subject=subject,
        subject_hash=subject.subject_hash,
    )
    attestation = _sign(trust_root, key_path, statement)
    ledger_path = (trust_root / "ledger.sqlite3").resolve()
    ledger_instance_id = "sim02c-ephemeral-engineering-ledger"
    _provision_test_ledger(ledger_path, ledger_instance_id)
    context = ProductionTrustContextV1(
        artifact_root=sim02b.artifact_root.resolve(),
        policy_path=policy_path,
        expected_policy_sha256=policy_sha,
        ledger_path=ledger_path,
        trusted_time=TRUST_NOW,
        ssh_keygen_path=ssh_path,
        expected_ssh_keygen_sha256=_hash_file(ssh_path),
    )
    enrollment_registry_path = trust_root / "enrollment-registry-v1.json"
    _write_json(
        enrollment_registry_path,
        {
            "schema_version": PRODUCTION_TRUST_ENROLLMENT_SCHEMA_VERSION,
            "domain": PRODUCTION_TRUST_ENROLLMENT_DOMAIN,
            "registry_id": "sim02c-ephemeral-engineering-registry",
            "project_id": PRODUCTION_TRUST_PROJECT_ID,
            "purpose": PRODUCTION_TRUST_PURPOSE,
            "environment": PRODUCTION_TRUST_ENVIRONMENT,
            "attestation_scope": PRODUCTION_TRUST_SCOPE,
            "entries": [
                {
                    "enrollment_id": "sim02c-ephemeral-engineering-enrollment",
                    "status": "active",
                    "policy_id": policy.policy_id,
                    "policy_sha256": policy_sha,
                    "ssh_keygen_sha256": context.expected_ssh_keygen_sha256,
                    "ledger_instance_id": ledger_instance_id,
                    "ledger_path_binding_hash": (
                        production_trust_ledger_path_binding_hash_v1(ledger_path)
                    ),
                    "minimum_policy_epoch": policy.policy_epoch,
                    "not_before": "2026-01-01T00:00:00Z",
                    "expires_at": "2028-01-01T00:00:00Z",
                }
            ],
        },
    )
    monkeypatch.setattr(
        trust_enrollment_module,
        "production_trust_enrollment_registry_path_v1",
        lambda: enrollment_registry_path,
    )
    return Sim02CProductionFixture(
        sim02b=sim02b,
        input_manifest=input_manifest,
        subject=subject,
        attestation=attestation,
        policy=policy,
        context=context,
        trust_root=trust_root,
        policy_path=policy_path,
        enrollment_registry_path=enrollment_registry_path,
        private_key_path=key_path,
        public_key=public_key,
        fingerprint=fingerprint,
    )
