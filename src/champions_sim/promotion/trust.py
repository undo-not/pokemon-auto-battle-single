"""Artifact-root-external production trust verification for SIM-02C.

The module deliberately contains no signing helper and accepts no private key.
An issuer signs the bytes returned by
:func:`encode_production_trust_signed_message_v1` in a separate process.  The
compiler side pins an external policy and OpenSSH binary by SHA-256, verifies
an Ed25519 SSH signature, then records replay and policy-epoch state in an
external SQLite ledger.

Portable JSON is evidence, not authority.  Authority comes from the complete
``ProductionTrustContextV1``: trusted time, pinned external policy, pinned
OpenSSH verifier, and an external replay/epoch ledger.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import base64
import binascii
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import tempfile
from typing import Any, Mapping

from champions_sim.core import canonical_hash, canonical_json


__all__ = [
    "PRODUCTION_TRUST_ALGORITHM",
    "PRODUCTION_TRUST_CANONICALIZATION",
    "PRODUCTION_TRUST_DOMAIN",
    "PRODUCTION_TRUST_ENVIRONMENT",
    "PRODUCTION_TRUST_NAMESPACE",
    "PRODUCTION_TRUST_PROJECT_ID",
    "PRODUCTION_TRUST_PURPOSE",
    "PRODUCTION_TRUST_SCHEMA_VERSION",
    "PRODUCTION_TRUST_SCOPE",
    "ProductionTrustAttestationStatementV1",
    "ProductionTrustAttestationV1",
    "ProductionTrustContextV1",
    "ProductionTrustError",
    "ProductionTrustIssuerV1",
    "ProductionTrustPolicyV1",
    "ProductionTrustPublicKeyV1",
    "ProductionTrustStatusV1",
    "ProductionTrustSubjectV1",
    "ResolvedProductionTrustV1",
    "encode_production_trust_signed_message_v1",
    "load_production_trust_attestation_v1",
    "load_production_trust_policy_v1",
    "load_resolved_production_trust_v1",
    "parse_production_trust_attestation_v1",
    "parse_production_trust_policy_v1",
    "parse_production_trust_subject_v1",
    "parse_resolved_production_trust_v1",
    "verify_production_trust_v1",
]


PRODUCTION_TRUST_SCHEMA_VERSION = "1.0.0"
PRODUCTION_TRUST_DOMAIN = "champions-sim.production-trust-attestation.v1"
PRODUCTION_TRUST_CANONICALIZATION = "champions-canonical-json-v1"
PRODUCTION_TRUST_PROJECT_ID = "champions_sim"
PRODUCTION_TRUST_PURPOSE = "production_source_approval"
PRODUCTION_TRUST_ENVIRONMENT = "private_match"
PRODUCTION_TRUST_SCOPE = "production_champions"
PRODUCTION_TRUST_ALGORITHM = "ssh-ed25519"
PRODUCTION_TRUST_NAMESPACE = "champions-sim-production-trust-v1"

_MESSAGE_PREFIX = b"CHAMPIONS_SIM_PRODUCTION_TRUST_ATTESTATION_V1\x00"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_STABLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,239}$")
_TIMESTAMP = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})$"
)
_MAX_JSON_BYTES = 4 * 1024 * 1024
_MAX_SIGNATURE_CHARS = 32 * 1024


class ProductionTrustError(ValueError):
    """Trust material or its verification is invalid."""


class ProductionTrustStatusV1(str, Enum):
    ACTIVE = "active"
    REVOKED = "revoked"


@dataclass(frozen=True, slots=True)
class ProductionTrustSubjectV1:
    schema_version: str
    domain: str
    project_id: str
    purpose: str
    environment: str
    compiler_contract_version: str
    attestation_scope: str
    regulation_id: str
    regulation_revision: str
    regulation_hash: str
    target_pool_id: str
    target_pool_hash: str
    source_authority_subject_hash: str
    request_binding_hash: str
    replay_binding_hash: str

    def __post_init__(self) -> None:
        _require_const(self.schema_version, PRODUCTION_TRUST_SCHEMA_VERSION, "subject schema_version")
        _require_const(self.domain, PRODUCTION_TRUST_DOMAIN, "subject domain")
        _require_const(self.project_id, PRODUCTION_TRUST_PROJECT_ID, "subject project_id")
        _require_const(self.purpose, PRODUCTION_TRUST_PURPOSE, "subject purpose")
        _require_const(self.environment, PRODUCTION_TRUST_ENVIRONMENT, "subject environment")
        _require_stable_id(self.compiler_contract_version, "compiler_contract_version")
        _require_const(self.attestation_scope, PRODUCTION_TRUST_SCOPE, "subject attestation_scope")
        _require_stable_id(self.regulation_id, "regulation_id")
        _require_stable_id(self.regulation_revision, "regulation_revision")
        _require_stable_id(self.target_pool_id, "target_pool_id")
        for value, label in (
            (self.regulation_hash, "regulation_hash"),
            (self.target_pool_hash, "target_pool_hash"),
            (self.source_authority_subject_hash, "source_authority_subject_hash"),
            (self.request_binding_hash, "request_binding_hash"),
            (self.replay_binding_hash, "replay_binding_hash"),
        ):
            _require_sha256(value, label)

    def to_data(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "domain": self.domain,
            "project_id": self.project_id,
            "purpose": self.purpose,
            "environment": self.environment,
            "compiler_contract_version": self.compiler_contract_version,
            "attestation_scope": self.attestation_scope,
            "regulation_id": self.regulation_id,
            "regulation_revision": self.regulation_revision,
            "regulation_hash": self.regulation_hash,
            "target_pool_id": self.target_pool_id,
            "target_pool_hash": self.target_pool_hash,
            "source_authority_subject_hash": self.source_authority_subject_hash,
            "request_binding_hash": self.request_binding_hash,
            "replay_binding_hash": self.replay_binding_hash,
        }

    @property
    def subject_hash(self) -> str:
        return canonical_hash(self.to_data())


@dataclass(frozen=True, slots=True)
class ProductionTrustAttestationStatementV1:
    schema_version: str
    canonicalization: str
    domain: str
    attestation_id: str
    issuer_id: str
    key_id: str
    algorithm: str
    namespace: str
    issued_at: str
    not_before: str
    expires_at: str
    policy_id: str
    policy_epoch: int
    subject: ProductionTrustSubjectV1
    subject_hash: str

    def __post_init__(self) -> None:
        _require_const(self.schema_version, PRODUCTION_TRUST_SCHEMA_VERSION, "statement schema_version")
        _require_const(
            self.canonicalization,
            PRODUCTION_TRUST_CANONICALIZATION,
            "statement canonicalization",
        )
        _require_const(self.domain, PRODUCTION_TRUST_DOMAIN, "statement domain")
        for value, label in (
            (self.attestation_id, "attestation_id"),
            (self.issuer_id, "issuer_id"),
            (self.key_id, "key_id"),
            (self.policy_id, "policy_id"),
        ):
            _require_stable_id(value, label)
        _require_const(self.algorithm, PRODUCTION_TRUST_ALGORITHM, "statement algorithm")
        _require_const(self.namespace, PRODUCTION_TRUST_NAMESPACE, "statement namespace")
        issued = _parse_timestamp(self.issued_at, "issued_at")
        not_before = _parse_timestamp(self.not_before, "not_before")
        expires = _parse_timestamp(self.expires_at, "expires_at")
        if issued > expires:
            raise ProductionTrustError("issued_at must not be after expires_at")
        if not_before > expires:
            raise ProductionTrustError("not_before must not be after expires_at")
        _require_positive_int(self.policy_epoch, "policy_epoch")
        if type(self.subject) is not ProductionTrustSubjectV1:
            raise ProductionTrustError("subject must use the exact ProductionTrustSubjectV1 contract")
        self.subject.__post_init__()
        _require_sha256(self.subject_hash, "subject_hash")
        if self.subject_hash != self.subject.subject_hash:
            raise ProductionTrustError("subject_hash does not match the canonical subject")

    def to_data(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "canonicalization": self.canonicalization,
            "domain": self.domain,
            "attestation_id": self.attestation_id,
            "issuer_id": self.issuer_id,
            "key_id": self.key_id,
            "algorithm": self.algorithm,
            "namespace": self.namespace,
            "issued_at": self.issued_at,
            "not_before": self.not_before,
            "expires_at": self.expires_at,
            "policy_id": self.policy_id,
            "policy_epoch": self.policy_epoch,
            "subject": self.subject.to_data(),
            "subject_hash": self.subject_hash,
        }


@dataclass(frozen=True, slots=True)
class ProductionTrustAttestationV1:
    statement: ProductionTrustAttestationStatementV1
    signature: str

    def __post_init__(self) -> None:
        if type(self.statement) is not ProductionTrustAttestationStatementV1:
            raise ProductionTrustError(
                "statement must use the exact ProductionTrustAttestationStatementV1 contract"
            )
        self.statement.__post_init__()
        _validate_armored_ssh_signature(self.signature)

    def to_data(self) -> dict[str, Any]:
        return {"statement": self.statement.to_data(), "signature": self.signature}

    @property
    def attestation_hash(self) -> str:
        return canonical_hash(self.to_data())


@dataclass(frozen=True, slots=True)
class ProductionTrustPublicKeyV1:
    key_id: str
    algorithm: str
    public_key: str
    fingerprint_sha256: str
    status: ProductionTrustStatusV1
    not_before: str
    expires_at: str

    def __post_init__(self) -> None:
        _require_stable_id(self.key_id, "key_id")
        _require_const(self.algorithm, PRODUCTION_TRUST_ALGORITHM, "key algorithm")
        calculated = _ssh_public_key_fingerprint(self.public_key)
        _require_ssh_fingerprint(self.fingerprint_sha256, "fingerprint_sha256")
        if calculated != self.fingerprint_sha256:
            raise ProductionTrustError("public-key fingerprint does not match public_key")
        if type(self.status) is not ProductionTrustStatusV1:
            raise ProductionTrustError("key status must use the exact ProductionTrustStatusV1 enum")
        not_before = _parse_timestamp(self.not_before, "key not_before")
        expires = _parse_timestamp(self.expires_at, "key expires_at")
        if not_before > expires:
            raise ProductionTrustError("key not_before must not be after key expires_at")

    def to_data(self) -> dict[str, Any]:
        return {
            "key_id": self.key_id,
            "algorithm": self.algorithm,
            "public_key": self.public_key,
            "fingerprint_sha256": self.fingerprint_sha256,
            "status": self.status.value,
            "not_before": self.not_before,
            "expires_at": self.expires_at,
        }


@dataclass(frozen=True, slots=True)
class ProductionTrustIssuerV1:
    issuer_id: str
    status: ProductionTrustStatusV1
    keys: tuple[ProductionTrustPublicKeyV1, ...]

    def __post_init__(self) -> None:
        _require_stable_id(self.issuer_id, "issuer_id")
        if type(self.status) is not ProductionTrustStatusV1:
            raise ProductionTrustError("issuer status must use the exact ProductionTrustStatusV1 enum")
        if type(self.keys) is not tuple or not self.keys:
            raise ProductionTrustError("issuer keys must be an exact non-empty tuple")
        if any(type(value) is not ProductionTrustPublicKeyV1 for value in self.keys):
            raise ProductionTrustError("issuer keys must use exact ProductionTrustPublicKeyV1 values")
        for key in self.keys:
            key.__post_init__()
        key_ids = tuple(value.key_id for value in self.keys)
        if key_ids != tuple(sorted(key_ids)) or len(key_ids) != len(set(key_ids)):
            raise ProductionTrustError("issuer keys must be unique and ordered by key_id")

    def to_data(self) -> dict[str, Any]:
        return {
            "issuer_id": self.issuer_id,
            "status": self.status.value,
            "keys": [value.to_data() for value in self.keys],
        }


@dataclass(frozen=True, slots=True)
class ProductionTrustPolicyV1:
    schema_version: str
    policy_id: str
    policy_epoch: int
    project_id: str
    purpose: str
    environment: str
    attestation_scope: str
    algorithm: str
    namespace: str
    valid_from: str
    expires_at: str
    minimum_attestation_policy_epoch: int
    issuers: tuple[ProductionTrustIssuerV1, ...]
    revoked_attestation_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_const(self.schema_version, PRODUCTION_TRUST_SCHEMA_VERSION, "policy schema_version")
        _require_stable_id(self.policy_id, "policy_id")
        _require_positive_int(self.policy_epoch, "policy_epoch")
        _require_const(self.project_id, PRODUCTION_TRUST_PROJECT_ID, "policy project_id")
        _require_const(self.purpose, PRODUCTION_TRUST_PURPOSE, "policy purpose")
        _require_const(self.environment, PRODUCTION_TRUST_ENVIRONMENT, "policy environment")
        _require_const(self.attestation_scope, PRODUCTION_TRUST_SCOPE, "policy attestation_scope")
        _require_const(self.algorithm, PRODUCTION_TRUST_ALGORITHM, "policy algorithm")
        _require_const(self.namespace, PRODUCTION_TRUST_NAMESPACE, "policy namespace")
        valid_from = _parse_timestamp(self.valid_from, "policy valid_from")
        expires = _parse_timestamp(self.expires_at, "policy expires_at")
        if valid_from > expires:
            raise ProductionTrustError("policy valid_from must not be after expires_at")
        _require_positive_int(
            self.minimum_attestation_policy_epoch,
            "minimum_attestation_policy_epoch",
        )
        if self.minimum_attestation_policy_epoch > self.policy_epoch:
            raise ProductionTrustError(
                "minimum_attestation_policy_epoch must not exceed policy_epoch"
            )
        if type(self.issuers) is not tuple or not self.issuers:
            raise ProductionTrustError("policy issuers must be an exact non-empty tuple")
        if any(type(value) is not ProductionTrustIssuerV1 for value in self.issuers):
            raise ProductionTrustError("policy issuers must use exact ProductionTrustIssuerV1 values")
        for issuer in self.issuers:
            issuer.__post_init__()
        issuer_ids = tuple(value.issuer_id for value in self.issuers)
        if issuer_ids != tuple(sorted(issuer_ids)) or len(issuer_ids) != len(set(issuer_ids)):
            raise ProductionTrustError("policy issuers must be unique and ordered by issuer_id")
        if type(self.revoked_attestation_ids) is not tuple:
            raise ProductionTrustError("revoked_attestation_ids must be an exact tuple")
        for value in self.revoked_attestation_ids:
            _require_stable_id(value, "revoked attestation_id")
        if (
            self.revoked_attestation_ids != tuple(sorted(self.revoked_attestation_ids))
            or len(self.revoked_attestation_ids) != len(set(self.revoked_attestation_ids))
        ):
            raise ProductionTrustError(
                "revoked_attestation_ids must be unique and lexicographically ordered"
            )

    def to_data(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "policy_id": self.policy_id,
            "policy_epoch": self.policy_epoch,
            "project_id": self.project_id,
            "purpose": self.purpose,
            "environment": self.environment,
            "attestation_scope": self.attestation_scope,
            "algorithm": self.algorithm,
            "namespace": self.namespace,
            "valid_from": self.valid_from,
            "expires_at": self.expires_at,
            "minimum_attestation_policy_epoch": self.minimum_attestation_policy_epoch,
            "issuers": [value.to_data() for value in self.issuers],
            "revoked_attestation_ids": list(self.revoked_attestation_ids),
        }


@dataclass(frozen=True, slots=True)
class ProductionTrustContextV1:
    """Privileged, deliberately non-portable verifier context."""

    artifact_root: Path
    policy_path: Path
    expected_policy_sha256: str
    ledger_path: Path
    trusted_time: datetime
    ssh_keygen_path: Path
    expected_ssh_keygen_sha256: str
    verification_timeout_seconds: int = 15

    def __post_init__(self) -> None:
        for value, label in (
            (self.artifact_root, "artifact_root"),
            (self.policy_path, "policy_path"),
            (self.ledger_path, "ledger_path"),
            (self.ssh_keygen_path, "ssh_keygen_path"),
        ):
            if not isinstance(value, Path):
                raise ProductionTrustError(f"{label} must be a pathlib.Path")
            if not value.is_absolute():
                raise ProductionTrustError(f"{label} must be absolute")
        _require_sha256(self.expected_policy_sha256, "expected_policy_sha256")
        _require_sha256(
            self.expected_ssh_keygen_sha256,
            "expected_ssh_keygen_sha256",
        )
        if not isinstance(self.trusted_time, datetime):
            raise ProductionTrustError("trusted_time must be a datetime")
        if self.trusted_time.tzinfo is None or self.trusted_time.utcoffset() is None:
            raise ProductionTrustError("trusted_time must be timezone-aware")
        if type(self.verification_timeout_seconds) is not int:
            raise ProductionTrustError("verification_timeout_seconds must be an exact integer")
        if not 1 <= self.verification_timeout_seconds <= 120:
            raise ProductionTrustError(
                "verification_timeout_seconds must be between 1 and 120"
            )


@dataclass(frozen=True, slots=True)
class ResolvedProductionTrustV1:
    schema_version: str
    domain: str
    attestation_id: str
    attestation_hash: str
    subject_hash: str
    policy_id: str
    policy_epoch: int
    policy_sha256: str
    issuer_id: str
    key_id: str
    key_fingerprint_sha256: str
    algorithm: str
    namespace: str
    verified_at: str
    ledger_binding_hash: str

    def __post_init__(self) -> None:
        _require_const(self.schema_version, PRODUCTION_TRUST_SCHEMA_VERSION, "receipt schema_version")
        _require_const(self.domain, PRODUCTION_TRUST_DOMAIN, "receipt domain")
        for value, label in (
            (self.attestation_id, "attestation_id"),
            (self.policy_id, "policy_id"),
            (self.issuer_id, "issuer_id"),
            (self.key_id, "key_id"),
        ):
            _require_stable_id(value, label)
        for value, label in (
            (self.attestation_hash, "attestation_hash"),
            (self.subject_hash, "subject_hash"),
            (self.policy_sha256, "policy_sha256"),
            (self.ledger_binding_hash, "ledger_binding_hash"),
        ):
            _require_sha256(value, label)
        _require_positive_int(self.policy_epoch, "policy_epoch")
        _require_ssh_fingerprint(
            self.key_fingerprint_sha256,
            "key_fingerprint_sha256",
        )
        _require_const(self.algorithm, PRODUCTION_TRUST_ALGORITHM, "receipt algorithm")
        _require_const(self.namespace, PRODUCTION_TRUST_NAMESPACE, "receipt namespace")
        _parse_timestamp(self.verified_at, "verified_at")

    def to_data(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "domain": self.domain,
            "attestation_id": self.attestation_id,
            "attestation_hash": self.attestation_hash,
            "subject_hash": self.subject_hash,
            "policy_id": self.policy_id,
            "policy_epoch": self.policy_epoch,
            "policy_sha256": self.policy_sha256,
            "issuer_id": self.issuer_id,
            "key_id": self.key_id,
            "key_fingerprint_sha256": self.key_fingerprint_sha256,
            "algorithm": self.algorithm,
            "namespace": self.namespace,
            "verified_at": self.verified_at,
            "ledger_binding_hash": self.ledger_binding_hash,
        }

    @property
    def trust_receipt_hash(self) -> str:
        return canonical_hash(self.to_data())


def encode_production_trust_signed_message_v1(
    statement: ProductionTrustAttestationStatementV1,
) -> bytes:
    """Encode the only message an issuer may sign for this contract.

    OpenSSH additionally authenticates ``statement.namespace`` through its SSH
    signature namespace.  The fixed binary prefix prevents the canonical JSON
    from being interpreted as a message from another protocol.
    """

    if type(statement) is not ProductionTrustAttestationStatementV1:
        raise ProductionTrustError(
            "statement must use the exact ProductionTrustAttestationStatementV1 contract"
        )
    statement.__post_init__()
    return _MESSAGE_PREFIX + canonical_json(statement.to_data()).encode("utf-8")


def parse_production_trust_subject_v1(value: Any) -> ProductionTrustSubjectV1:
    raw = _require_object(value, "production trust subject")
    _require_exact_keys(
        raw,
        {
            "schema_version",
            "domain",
            "project_id",
            "purpose",
            "environment",
            "compiler_contract_version",
            "attestation_scope",
            "regulation_id",
            "regulation_revision",
            "regulation_hash",
            "target_pool_id",
            "target_pool_hash",
            "source_authority_subject_hash",
            "request_binding_hash",
            "replay_binding_hash",
        },
        "production trust subject",
    )
    return ProductionTrustSubjectV1(**raw)


def parse_production_trust_attestation_v1(value: Any) -> ProductionTrustAttestationV1:
    raw = _require_object(value, "production trust attestation")
    _require_exact_keys(raw, {"statement", "signature"}, "production trust attestation")
    statement_raw = _require_object(raw["statement"], "production trust statement")
    _require_exact_keys(
        statement_raw,
        {
            "schema_version",
            "canonicalization",
            "domain",
            "attestation_id",
            "issuer_id",
            "key_id",
            "algorithm",
            "namespace",
            "issued_at",
            "not_before",
            "expires_at",
            "policy_id",
            "policy_epoch",
            "subject",
            "subject_hash",
        },
        "production trust statement",
    )
    statement_data = dict(statement_raw)
    statement_data["subject"] = parse_production_trust_subject_v1(statement_raw["subject"])
    statement = ProductionTrustAttestationStatementV1(**statement_data)
    return ProductionTrustAttestationV1(statement=statement, signature=raw["signature"])


def parse_production_trust_policy_v1(value: Any) -> ProductionTrustPolicyV1:
    raw = _require_object(value, "production trust policy")
    _require_exact_keys(
        raw,
        {
            "schema_version",
            "policy_id",
            "policy_epoch",
            "project_id",
            "purpose",
            "environment",
            "attestation_scope",
            "algorithm",
            "namespace",
            "valid_from",
            "expires_at",
            "minimum_attestation_policy_epoch",
            "issuers",
            "revoked_attestation_ids",
        },
        "production trust policy",
    )
    issuers_raw = _require_array(raw["issuers"], "policy issuers")
    issuers: list[ProductionTrustIssuerV1] = []
    for issuer_index, issuer_value in enumerate(issuers_raw):
        issuer_raw = _require_object(issuer_value, f"policy issuers[{issuer_index}]")
        _require_exact_keys(
            issuer_raw,
            {"issuer_id", "status", "keys"},
            f"policy issuers[{issuer_index}]",
        )
        keys_raw = _require_array(issuer_raw["keys"], f"policy issuers[{issuer_index}].keys")
        keys: list[ProductionTrustPublicKeyV1] = []
        for key_index, key_value in enumerate(keys_raw):
            key_raw = _require_object(
                key_value,
                f"policy issuers[{issuer_index}].keys[{key_index}]",
            )
            _require_exact_keys(
                key_raw,
                {
                    "key_id",
                    "algorithm",
                    "public_key",
                    "fingerprint_sha256",
                    "status",
                    "not_before",
                    "expires_at",
                },
                f"policy issuers[{issuer_index}].keys[{key_index}]",
            )
            key_data = dict(key_raw)
            key_data["status"] = _parse_status(key_raw["status"], "key status")
            keys.append(ProductionTrustPublicKeyV1(**key_data))
        issuers.append(
            ProductionTrustIssuerV1(
                issuer_id=issuer_raw["issuer_id"],
                status=_parse_status(issuer_raw["status"], "issuer status"),
                keys=tuple(keys),
            )
        )
    revoked_raw = _require_array(
        raw["revoked_attestation_ids"],
        "revoked_attestation_ids",
    )
    policy_data = dict(raw)
    policy_data["issuers"] = tuple(issuers)
    policy_data["revoked_attestation_ids"] = tuple(revoked_raw)
    return ProductionTrustPolicyV1(**policy_data)


def load_production_trust_attestation_v1(path: Path) -> ProductionTrustAttestationV1:
    return parse_production_trust_attestation_v1(
        _load_json_object(path, "production trust attestation")
    )


def load_production_trust_policy_v1(path: Path) -> ProductionTrustPolicyV1:
    """Load policy syntax only; authority still requires a context hash pin."""

    return parse_production_trust_policy_v1(
        _load_json_object(path, "production trust policy")
    )


def parse_resolved_production_trust_v1(value: Any) -> ResolvedProductionTrustV1:
    raw = _require_object(value, "resolved production trust receipt")
    _require_exact_keys(
        raw,
        {
            "schema_version",
            "domain",
            "attestation_id",
            "attestation_hash",
            "subject_hash",
            "policy_id",
            "policy_epoch",
            "policy_sha256",
            "issuer_id",
            "key_id",
            "key_fingerprint_sha256",
            "algorithm",
            "namespace",
            "verified_at",
            "ledger_binding_hash",
        },
        "resolved production trust receipt",
    )
    return ResolvedProductionTrustV1(**raw)


def load_resolved_production_trust_v1(path: Path) -> ResolvedProductionTrustV1:
    return parse_resolved_production_trust_v1(
        _load_json_object(path, "resolved production trust receipt")
    )


def verify_production_trust_v1(
    attestation: ProductionTrustAttestationV1,
    expected_subject: ProductionTrustSubjectV1,
    context: ProductionTrustContextV1,
) -> ResolvedProductionTrustV1:
    """Verify trust against external state and atomically consume the envelope."""

    if type(attestation) is not ProductionTrustAttestationV1:
        raise ProductionTrustError(
            "attestation must use the exact ProductionTrustAttestationV1 contract"
        )
    if type(expected_subject) is not ProductionTrustSubjectV1:
        raise ProductionTrustError(
            "expected_subject must use the exact ProductionTrustSubjectV1 contract"
        )
    if type(context) is not ProductionTrustContextV1:
        raise ProductionTrustError(
            "context must use the exact ProductionTrustContextV1 contract"
        )
    attestation.__post_init__()
    expected_subject.__post_init__()
    context.__post_init__()

    paths = _resolve_and_validate_external_paths(context)
    policy_payload = _read_bounded_file(paths.policy_path, "production trust policy")
    policy_sha256 = hashlib.sha256(policy_payload).hexdigest()
    if policy_sha256 != context.expected_policy_sha256:
        raise ProductionTrustError("production trust policy SHA-256 pin mismatch")
    policy = parse_production_trust_policy_v1(
        _parse_json_object(policy_payload, "production trust policy")
    )

    ssh_keygen_sha256 = _hash_file(paths.ssh_keygen_path, "ssh-keygen executable")
    if ssh_keygen_sha256 != context.expected_ssh_keygen_sha256:
        raise ProductionTrustError("ssh-keygen executable SHA-256 pin mismatch")

    statement = attestation.statement
    now = context.trusted_time.astimezone(timezone.utc)
    _validate_policy_and_statement(policy, statement, expected_subject, now)
    issuer = next(
        (value for value in policy.issuers if value.issuer_id == statement.issuer_id),
        None,
    )
    if issuer is None:
        raise ProductionTrustError("attestation issuer is not enrolled in trust policy")
    if issuer.status is not ProductionTrustStatusV1.ACTIVE:
        raise ProductionTrustError("attestation issuer is revoked")
    key = next((value for value in issuer.keys if value.key_id == statement.key_id), None)
    if key is None:
        raise ProductionTrustError("attestation key is not enrolled for issuer")
    if key.status is not ProductionTrustStatusV1.ACTIVE:
        raise ProductionTrustError("attestation key is revoked")
    if key.algorithm != statement.algorithm:
        raise ProductionTrustError("attestation algorithm differs from enrolled key")
    if not _time_in_closed_interval(now, key.not_before, key.expires_at):
        raise ProductionTrustError("attestation key is outside its validity interval")

    message = encode_production_trust_signed_message_v1(statement)
    _verify_openssh_signature(
        ssh_keygen_path=paths.ssh_keygen_path,
        issuer_id=statement.issuer_id,
        namespace=statement.namespace,
        public_key=key.public_key,
        signature=attestation.signature,
        message=message,
        artifact_root=paths.artifact_root,
        timeout_seconds=context.verification_timeout_seconds,
    )
    if _hash_file(paths.ssh_keygen_path, "ssh-keygen executable") != ssh_keygen_sha256:
        raise ProductionTrustError("ssh-keygen executable changed during verification")

    attestation_hash = attestation.attestation_hash
    ledger_binding = {
        "policy_id": policy.policy_id,
        "policy_epoch": policy.policy_epoch,
        "issuer_id": statement.issuer_id,
        "key_id": statement.key_id,
        "attestation_id": statement.attestation_id,
        "subject_hash": statement.subject_hash,
        "attestation_hash": attestation_hash,
    }
    ledger_binding_hash = canonical_hash(ledger_binding)
    _record_ledger_acceptance(
        paths.ledger_path,
        policy_id=policy.policy_id,
        policy_epoch=policy.policy_epoch,
        issuer_id=statement.issuer_id,
        key_id=statement.key_id,
        attestation_id=statement.attestation_id,
        subject_hash=statement.subject_hash,
        attestation_hash=attestation_hash,
        ledger_binding_hash=ledger_binding_hash,
    )
    return ResolvedProductionTrustV1(
        schema_version=PRODUCTION_TRUST_SCHEMA_VERSION,
        domain=PRODUCTION_TRUST_DOMAIN,
        attestation_id=statement.attestation_id,
        attestation_hash=attestation_hash,
        subject_hash=statement.subject_hash,
        policy_id=policy.policy_id,
        policy_epoch=policy.policy_epoch,
        policy_sha256=policy_sha256,
        issuer_id=statement.issuer_id,
        key_id=statement.key_id,
        key_fingerprint_sha256=key.fingerprint_sha256,
        algorithm=statement.algorithm,
        namespace=statement.namespace,
        verified_at=_format_timestamp(now),
        ledger_binding_hash=ledger_binding_hash,
    )


@dataclass(frozen=True, slots=True)
class _ResolvedExternalPaths:
    artifact_root: Path
    policy_path: Path
    ledger_path: Path
    ssh_keygen_path: Path


def _resolve_and_validate_external_paths(
    context: ProductionTrustContextV1,
) -> _ResolvedExternalPaths:
    try:
        artifact_root = context.artifact_root.resolve(strict=True)
        policy_path = context.policy_path.resolve(strict=True)
        ssh_keygen_path = context.ssh_keygen_path.resolve(strict=True)
        ledger_path = context.ledger_path.resolve(strict=context.ledger_path.exists())
    except OSError as error:
        raise ProductionTrustError("production trust external path cannot be resolved") from error
    if not artifact_root.is_dir():
        raise ProductionTrustError("artifact_root must resolve to a directory")
    if not policy_path.is_file():
        raise ProductionTrustError("policy_path must resolve to a regular file")
    if not ssh_keygen_path.is_file():
        raise ProductionTrustError("ssh_keygen_path must resolve to a regular file")
    if ledger_path.exists() and not ledger_path.is_file():
        raise ProductionTrustError("ledger_path must resolve to a regular file or not exist")
    if not ledger_path.parent.is_dir():
        raise ProductionTrustError("ledger_path parent must already exist")
    for value, label in (
        (policy_path, "policy_path"),
        (ledger_path, "ledger_path"),
        (ssh_keygen_path, "ssh_keygen_path"),
    ):
        if _is_within(value, artifact_root):
            raise ProductionTrustError(f"{label} must be outside artifact_root")
    if policy_path == ledger_path:
        raise ProductionTrustError("policy_path and ledger_path must be different")
    return _ResolvedExternalPaths(
        artifact_root=artifact_root,
        policy_path=policy_path,
        ledger_path=ledger_path,
        ssh_keygen_path=ssh_keygen_path,
    )


def _validate_policy_and_statement(
    policy: ProductionTrustPolicyV1,
    statement: ProductionTrustAttestationStatementV1,
    expected_subject: ProductionTrustSubjectV1,
    now: datetime,
) -> None:
    if statement.subject_hash != expected_subject.subject_hash:
        raise ProductionTrustError("attested subject differs from expected compiler subject")
    if statement.subject.to_data() != expected_subject.to_data():
        raise ProductionTrustError("attested subject content differs from expected compiler subject")
    if statement.policy_id != policy.policy_id:
        raise ProductionTrustError("attestation policy_id differs from pinned policy")
    if statement.policy_epoch != policy.policy_epoch:
        raise ProductionTrustError("attestation policy_epoch differs from pinned current policy")
    if statement.policy_epoch < policy.minimum_attestation_policy_epoch:
        raise ProductionTrustError("attestation policy_epoch is below policy minimum")
    if statement.attestation_id in policy.revoked_attestation_ids:
        raise ProductionTrustError("attestation ID is revoked")
    for actual, expected, label in (
        (statement.subject.project_id, policy.project_id, "project_id"),
        (statement.subject.purpose, policy.purpose, "purpose"),
        (statement.subject.environment, policy.environment, "environment"),
        (statement.subject.attestation_scope, policy.attestation_scope, "attestation_scope"),
        (statement.algorithm, policy.algorithm, "algorithm"),
        (statement.namespace, policy.namespace, "namespace"),
    ):
        if actual != expected:
            raise ProductionTrustError(f"attestation {label} differs from pinned policy")
    if not _time_in_closed_interval(now, policy.valid_from, policy.expires_at):
        raise ProductionTrustError("production trust policy is outside its validity interval")
    if now < _parse_timestamp(statement.not_before, "not_before"):
        raise ProductionTrustError("attestation is not yet valid")
    if now > _parse_timestamp(statement.expires_at, "expires_at"):
        raise ProductionTrustError("attestation has expired")
    if now < _parse_timestamp(statement.issued_at, "issued_at"):
        raise ProductionTrustError("attestation issued_at is in the trusted clock future")


def _verify_openssh_signature(
    *,
    ssh_keygen_path: Path,
    issuer_id: str,
    namespace: str,
    public_key: str,
    signature: str,
    message: bytes,
    artifact_root: Path,
    timeout_seconds: int,
) -> None:
    try:
        with tempfile.TemporaryDirectory(prefix="champions-sim-trust-") as temp_name:
            temp_root = Path(temp_name).resolve(strict=True)
            if _is_within(temp_root, artifact_root):
                raise ProductionTrustError(
                    "system temporary directory for signature verification is inside artifact_root"
                )
            allowed_signers = temp_root / "allowed_signers"
            signature_path = temp_root / "attestation.sig"
            allowed_signers.write_text(
                f'{issuer_id} namespaces="{namespace}" {public_key}\n',
                encoding="utf-8",
                newline="\n",
            )
            signature_path.write_text(signature, encoding="ascii", newline="\n")
            command = [
                str(ssh_keygen_path),
                "-Y",
                "verify",
                "-f",
                str(allowed_signers),
                "-I",
                issuer_id,
                "-n",
                namespace,
                "-s",
                str(signature_path),
            ]
            run_kwargs: dict[str, Any] = {}
            if os.name == "nt":
                run_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            completed = subprocess.run(
                command,
                input=message,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                check=False,
                timeout=timeout_seconds,
                cwd=temp_root,
                **run_kwargs,
            )
    except ProductionTrustError:
        raise
    except (OSError, UnicodeError, subprocess.TimeoutExpired) as error:
        raise ProductionTrustError("OpenSSH signature verifier could not complete") from error
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        if len(detail) > 300:
            detail = detail[:300] + "..."
        suffix = f": {detail}" if detail else ""
        raise ProductionTrustError(f"OpenSSH Ed25519 signature verification failed{suffix}")


def _record_ledger_acceptance(
    ledger_path: Path,
    *,
    policy_id: str,
    policy_epoch: int,
    issuer_id: str,
    key_id: str,
    attestation_id: str,
    subject_hash: str,
    attestation_hash: str,
    ledger_binding_hash: str,
) -> None:
    try:
        connection = sqlite3.connect(
            str(ledger_path),
            timeout=15.0,
            isolation_level=None,
        )
        try:
            connection.execute("PRAGMA trusted_schema = OFF")
            connection.execute("PRAGMA busy_timeout = 15000")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS production_trust_policy_epoch (
                    policy_id TEXT PRIMARY KEY NOT NULL,
                    maximum_epoch INTEGER NOT NULL CHECK (maximum_epoch > 0)
                ) STRICT
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS production_trust_attestation (
                    issuer_id TEXT NOT NULL,
                    key_id TEXT NOT NULL,
                    attestation_id TEXT NOT NULL,
                    subject_hash TEXT NOT NULL,
                    attestation_hash TEXT NOT NULL,
                    policy_id TEXT NOT NULL,
                    policy_epoch INTEGER NOT NULL CHECK (policy_epoch > 0),
                    ledger_binding_hash TEXT NOT NULL,
                    PRIMARY KEY (issuer_id, key_id, attestation_id)
                ) STRICT
                """
            )
            epoch_row = connection.execute(
                "SELECT maximum_epoch FROM production_trust_policy_epoch WHERE policy_id = ?",
                (policy_id,),
            ).fetchone()
            if epoch_row is not None and policy_epoch < epoch_row[0]:
                raise ProductionTrustError("production trust policy epoch rollback detected")
            if epoch_row is None:
                connection.execute(
                    "INSERT INTO production_trust_policy_epoch(policy_id, maximum_epoch) VALUES (?, ?)",
                    (policy_id, policy_epoch),
                )
            elif policy_epoch > epoch_row[0]:
                connection.execute(
                    "UPDATE production_trust_policy_epoch SET maximum_epoch = ? WHERE policy_id = ?",
                    (policy_epoch, policy_id),
                )
            existing = connection.execute(
                """
                SELECT subject_hash, attestation_hash, policy_id, policy_epoch,
                       ledger_binding_hash
                FROM production_trust_attestation
                WHERE issuer_id = ? AND key_id = ? AND attestation_id = ?
                """,
                (issuer_id, key_id, attestation_id),
            ).fetchone()
            expected = (
                subject_hash,
                attestation_hash,
                policy_id,
                policy_epoch,
                ledger_binding_hash,
            )
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO production_trust_attestation(
                        issuer_id, key_id, attestation_id, subject_hash,
                        attestation_hash, policy_id, policy_epoch,
                        ledger_binding_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        issuer_id,
                        key_id,
                        attestation_id,
                        subject_hash,
                        attestation_hash,
                        policy_id,
                        policy_epoch,
                        ledger_binding_hash,
                    ),
                )
            elif tuple(existing) != expected:
                raise ProductionTrustError(
                    "attestation replay ledger conflict for issuer/key/attestation ID"
                )
            connection.execute("COMMIT")
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()
    except ProductionTrustError:
        raise
    except sqlite3.Error as error:
        raise ProductionTrustError("production trust replay ledger failure") from error


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    if not isinstance(path, Path):
        raise ProductionTrustError(f"{label} path must be a pathlib.Path")
    payload = _read_bounded_file(path, label)
    return _parse_json_object(payload, label)


def _read_bounded_file(path: Path, label: str) -> bytes:
    try:
        size = path.stat().st_size
        if size > _MAX_JSON_BYTES:
            raise ProductionTrustError(f"{label} exceeds {_MAX_JSON_BYTES} bytes")
        return path.read_bytes()
    except ProductionTrustError:
        raise
    except OSError as error:
        raise ProductionTrustError(f"cannot read {label}: {path}") from error


def _parse_json_object(payload: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite_number,
            parse_float=_reject_float,
        )
    except ProductionTrustError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProductionTrustError(f"{label} is not strict UTF-8 JSON") from error
    return _require_object(value, label)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProductionTrustError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_non_finite_number(value: str) -> None:
    raise ProductionTrustError(f"non-finite JSON number is forbidden: {value}")


def _reject_float(value: str) -> None:
    raise ProductionTrustError(f"floating-point JSON number is forbidden: {value}")


def _require_object(value: Any, label: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise ProductionTrustError(f"{label} must be an exact JSON object")
    return value


def _require_array(value: Any, label: str) -> list[Any]:
    if type(value) is not list:
        raise ProductionTrustError(f"{label} must be an exact JSON array")
    return value


def _require_exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ProductionTrustError(
            f"{label} fields differ; missing={missing}, extra={extra}"
        )


def _parse_status(value: Any, label: str) -> ProductionTrustStatusV1:
    if type(value) is not str:
        raise ProductionTrustError(f"{label} must be an exact string")
    try:
        return ProductionTrustStatusV1(value)
    except ValueError as error:
        raise ProductionTrustError(f"unsupported {label}: {value!r}") from error


def _require_exact_string(value: Any, label: str) -> None:
    if type(value) is not str:
        raise ProductionTrustError(f"{label} must be an exact string")


def _require_const(value: Any, expected: str, label: str) -> None:
    _require_exact_string(value, label)
    if value != expected:
        raise ProductionTrustError(f"{label} must be {expected!r}")


def _require_stable_id(value: Any, label: str) -> None:
    _require_exact_string(value, label)
    if _STABLE_ID.fullmatch(value) is None:
        raise ProductionTrustError(f"{label} must be a stable identifier")


def _require_sha256(value: Any, label: str) -> None:
    _require_exact_string(value, label)
    if _SHA256.fullmatch(value) is None:
        raise ProductionTrustError(f"{label} must be a lowercase SHA-256 digest")


def _require_positive_int(value: Any, label: str) -> None:
    if type(value) is not int or not 1 <= value <= 9_223_372_036_854_775_807:
        raise ProductionTrustError(
            f"{label} must be a positive signed-64-bit exact integer"
        )


def _parse_timestamp(value: Any, label: str) -> datetime:
    _require_exact_string(value, label)
    if _TIMESTAMP.fullmatch(value) is None:
        raise ProductionTrustError(f"{label} must be an offset-aware RFC 3339 timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as error:
        raise ProductionTrustError(f"{label} is not a valid timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ProductionTrustError(f"{label} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _format_timestamp(value: datetime) -> str:
    utc = value.astimezone(timezone.utc)
    if utc.microsecond:
        return utc.isoformat(timespec="microseconds").replace("+00:00", "Z")
    return utc.isoformat(timespec="seconds").replace("+00:00", "Z")


def _time_in_closed_interval(now: datetime, start: str, end: str) -> bool:
    return _parse_timestamp(start, "validity start") <= now <= _parse_timestamp(
        end,
        "validity end",
    )


def _validate_armored_ssh_signature(value: Any) -> None:
    _require_exact_string(value, "signature")
    if not value.isascii() or "\x00" in value or "\r" in value:
        raise ProductionTrustError("signature must be canonical LF-only ASCII armor")
    if len(value) > _MAX_SIGNATURE_CHARS:
        raise ProductionTrustError("signature exceeds the bounded armor size")
    if not value.startswith("-----BEGIN SSH SIGNATURE-----\n"):
        raise ProductionTrustError("signature lacks OpenSSH armor header")
    if not value.endswith("\n-----END SSH SIGNATURE-----\n"):
        raise ProductionTrustError("signature lacks canonical OpenSSH armor footer")


def _ssh_public_key_fingerprint(public_key: Any) -> str:
    _require_exact_string(public_key, "public_key")
    if "\n" in public_key or "\r" in public_key or "\x00" in public_key:
        raise ProductionTrustError("public_key must be a single canonical line")
    parts = public_key.split(" ")
    if len(parts) != 2 or parts[0] != PRODUCTION_TRUST_ALGORITHM or not parts[1]:
        raise ProductionTrustError(
            "public_key must be a comment-free canonical ssh-ed25519 key"
        )
    try:
        blob = base64.b64decode(parts[1], validate=True)
    except (ValueError, binascii.Error) as error:
        raise ProductionTrustError("public_key contains invalid base64") from error
    algorithm, offset = _read_ssh_wire_string(blob, 0, "public-key algorithm")
    key_material, offset = _read_ssh_wire_string(blob, offset, "Ed25519 public key")
    if offset != len(blob):
        raise ProductionTrustError("public_key blob has trailing wire data")
    if algorithm != PRODUCTION_TRUST_ALGORITHM.encode("ascii"):
        raise ProductionTrustError("public_key blob is not ssh-ed25519")
    if len(key_material) != 32:
        raise ProductionTrustError("Ed25519 public key must contain exactly 32 bytes")
    fingerprint = base64.b64encode(hashlib.sha256(blob).digest()).decode("ascii").rstrip("=")
    return f"SHA256:{fingerprint}"


def _require_ssh_fingerprint(value: Any, label: str) -> None:
    _require_exact_string(value, label)
    if not value.startswith("SHA256:") or len(value) <= len("SHA256:"):
        raise ProductionTrustError(f"{label} must be an OpenSSH SHA256 fingerprint")
    encoded = value[len("SHA256:") :]
    if len(encoded) != 43 or re.fullmatch(r"[A-Za-z0-9+/]+", encoded) is None:
        raise ProductionTrustError(f"{label} contains invalid base64")


def _read_ssh_wire_string(blob: bytes, offset: int, label: str) -> tuple[bytes, int]:
    if len(blob) - offset < 4:
        raise ProductionTrustError(f"public_key blob truncates {label} length")
    length = int.from_bytes(blob[offset : offset + 4], "big")
    offset += 4
    end = offset + length
    if end > len(blob):
        raise ProductionTrustError(f"public_key blob truncates {label}")
    return blob[offset:end], end


def _hash_file(path: Path, label: str) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as error:
        raise ProductionTrustError(f"cannot hash {label}: {path}") from error
    return digest.hexdigest()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
