"""Out-of-band enrollment anchor for SIM-02C production trust policies.

The compiler caller may present a policy path and its hash, but may not decide
whether that policy is enrolled.  Enrollment is an explicit user-controlled
state change at one fixed per-user path outside the artifact root and project
workspace.  This module never creates or modifies that registry.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from typing import Any, Mapping

from champions_sim.core import canonical_hash

from .trust import (
    PRODUCTION_TRUST_ENVIRONMENT,
    PRODUCTION_TRUST_PROJECT_ID,
    PRODUCTION_TRUST_PURPOSE,
    PRODUCTION_TRUST_SCOPE,
    ProductionTrustContextV1,
    ResolvedProductionTrustV1,
    parse_production_trust_policy_v1,
)


PRODUCTION_TRUST_ENROLLMENT_SCHEMA_VERSION = "1.0.0"
PRODUCTION_TRUST_ENROLLMENT_DOMAIN = (
    "champions-sim.production-trust-enrollment.v1"
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_STABLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,239}$")
_TIMESTAMP = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})$"
)
_MAX_SIGNED_64 = 9_223_372_036_854_775_807
_MAX_REGISTRY_BYTES = 1024 * 1024
_MAX_POLICY_BYTES = 4 * 1024 * 1024
_FIXED_ENROLLMENT_REGISTRY_PATH = (
    Path.home()
    / ".champions_sim"
    / "production-trust"
    / "enrollment-registry-v1.json"
).resolve()


class ProductionTrustEnrollmentError(ValueError):
    """No exact active out-of-band enrollment authorizes this context."""


def production_trust_enrollment_registry_path_v1() -> Path:
    """Return the fixed per-user registry path; never create it implicitly."""

    return _FIXED_ENROLLMENT_REGISTRY_PATH


@dataclass(frozen=True, slots=True)
class ProductionTrustEnrollmentEntryV1:
    enrollment_id: str
    status: str
    policy_id: str
    policy_sha256: str
    ssh_keygen_sha256: str
    ledger_instance_id: str
    ledger_path_binding_hash: str
    minimum_policy_epoch: int
    not_before: str
    expires_at: str

    def __post_init__(self) -> None:
        _stable(self.enrollment_id, "enrollment_id")
        if type(self.status) is not str or self.status not in {"active", "revoked"}:
            raise ProductionTrustEnrollmentError("unsupported enrollment status")
        _stable(self.policy_id, "policy_id")
        _sha(self.policy_sha256, "policy_sha256")
        _sha(self.ssh_keygen_sha256, "ssh_keygen_sha256")
        _stable(self.ledger_instance_id, "ledger_instance_id")
        _sha(self.ledger_path_binding_hash, "ledger_path_binding_hash")
        if (
            type(self.minimum_policy_epoch) is not int
            or not 1 <= self.minimum_policy_epoch <= _MAX_SIGNED_64
        ):
            raise ProductionTrustEnrollmentError(
                "minimum_policy_epoch must be a positive signed-64-bit exact integer"
            )
        start = _timestamp(self.not_before, "not_before")
        end = _timestamp(self.expires_at, "expires_at")
        if start > end:
            raise ProductionTrustEnrollmentError(
                "enrollment not_before must not be after expires_at"
            )

    def to_data(self) -> dict[str, Any]:
        return {
            "enrollment_id": self.enrollment_id,
            "status": self.status,
            "policy_id": self.policy_id,
            "policy_sha256": self.policy_sha256,
            "ssh_keygen_sha256": self.ssh_keygen_sha256,
            "ledger_instance_id": self.ledger_instance_id,
            "ledger_path_binding_hash": self.ledger_path_binding_hash,
            "minimum_policy_epoch": self.minimum_policy_epoch,
            "not_before": self.not_before,
            "expires_at": self.expires_at,
        }


@dataclass(frozen=True, slots=True)
class ProductionTrustEnrollmentRegistryV1:
    schema_version: str
    domain: str
    registry_id: str
    project_id: str
    purpose: str
    environment: str
    attestation_scope: str
    entries: tuple[ProductionTrustEnrollmentEntryV1, ...]

    def __post_init__(self) -> None:
        _constant(
            self.schema_version,
            PRODUCTION_TRUST_ENROLLMENT_SCHEMA_VERSION,
            "enrollment registry schema_version",
        )
        _constant(
            self.domain,
            PRODUCTION_TRUST_ENROLLMENT_DOMAIN,
            "enrollment registry domain",
        )
        _stable(self.registry_id, "registry_id")
        _constant(
            self.project_id,
            PRODUCTION_TRUST_PROJECT_ID,
            "enrollment project_id",
        )
        _constant(self.purpose, PRODUCTION_TRUST_PURPOSE, "enrollment purpose")
        _constant(
            self.environment,
            PRODUCTION_TRUST_ENVIRONMENT,
            "enrollment environment",
        )
        _constant(
            self.attestation_scope,
            PRODUCTION_TRUST_SCOPE,
            "enrollment attestation_scope",
        )
        if type(self.entries) is not tuple or not self.entries:
            raise ProductionTrustEnrollmentError(
                "enrollment registry requires exact non-empty entries"
            )
        if any(type(value) is not ProductionTrustEnrollmentEntryV1 for value in self.entries):
            raise ProductionTrustEnrollmentError(
                "enrollment registry entries require exact V1 values"
            )
        for value in self.entries:
            value.__post_init__()
        ids = tuple(value.enrollment_id for value in self.entries)
        if ids != tuple(sorted(ids)) or len(ids) != len(set(ids)):
            raise ProductionTrustEnrollmentError(
                "enrollment entries must be unique and ordered by enrollment_id"
            )

    def to_data(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "domain": self.domain,
            "registry_id": self.registry_id,
            "project_id": self.project_id,
            "purpose": self.purpose,
            "environment": self.environment,
            "attestation_scope": self.attestation_scope,
            "entries": [value.to_data() for value in self.entries],
        }


@dataclass(frozen=True, slots=True)
class ResolvedProductionTrustEnrollmentV1:
    schema_version: str
    domain: str
    registry_id: str
    registry_sha256: str
    enrollment_id: str
    policy_id: str
    policy_sha256: str
    ssh_keygen_sha256: str
    ledger_instance_id: str
    ledger_path_binding_hash: str
    minimum_policy_epoch: int
    not_before: str
    expires_at: str

    def __post_init__(self) -> None:
        _constant(
            self.schema_version,
            PRODUCTION_TRUST_ENROLLMENT_SCHEMA_VERSION,
            "resolved enrollment schema_version",
        )
        _constant(
            self.domain,
            PRODUCTION_TRUST_ENROLLMENT_DOMAIN,
            "resolved enrollment domain",
        )
        for value, label in (
            (self.registry_id, "registry_id"),
            (self.enrollment_id, "enrollment_id"),
            (self.policy_id, "policy_id"),
            (self.ledger_instance_id, "ledger_instance_id"),
        ):
            _stable(value, label)
        for value, label in (
            (self.registry_sha256, "registry_sha256"),
            (self.policy_sha256, "policy_sha256"),
            (self.ssh_keygen_sha256, "ssh_keygen_sha256"),
            (self.ledger_path_binding_hash, "ledger_path_binding_hash"),
        ):
            _sha(value, label)
        if (
            type(self.minimum_policy_epoch) is not int
            or not 1 <= self.minimum_policy_epoch <= _MAX_SIGNED_64
        ):
            raise ProductionTrustEnrollmentError("invalid minimum_policy_epoch")
        if _timestamp(self.not_before, "not_before") > _timestamp(
            self.expires_at, "expires_at"
        ):
            raise ProductionTrustEnrollmentError("resolved enrollment interval differs")

    def to_data(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "domain": self.domain,
            "registry_id": self.registry_id,
            "registry_sha256": self.registry_sha256,
            "enrollment_id": self.enrollment_id,
            "policy_id": self.policy_id,
            "policy_sha256": self.policy_sha256,
            "ssh_keygen_sha256": self.ssh_keygen_sha256,
            "ledger_instance_id": self.ledger_instance_id,
            "ledger_path_binding_hash": self.ledger_path_binding_hash,
            "minimum_policy_epoch": self.minimum_policy_epoch,
            "not_before": self.not_before,
            "expires_at": self.expires_at,
        }

    @property
    def enrollment_binding_hash(self) -> str:
        return canonical_hash(self.to_data())


def parse_production_trust_enrollment_registry_v1(
    value: Any,
) -> ProductionTrustEnrollmentRegistryV1:
    raw = _object(value, "production trust enrollment registry")
    _exact(
        raw,
        {
            "schema_version",
            "domain",
            "registry_id",
            "project_id",
            "purpose",
            "environment",
            "attestation_scope",
            "entries",
        },
        "production trust enrollment registry",
    )
    entries_raw = raw["entries"]
    if type(entries_raw) is not list:
        raise ProductionTrustEnrollmentError("enrollment entries must be an array")
    entries: list[ProductionTrustEnrollmentEntryV1] = []
    for index, value in enumerate(entries_raw):
        item = _object(value, f"enrollment entries[{index}]")
        _exact(
            item,
            {
                "enrollment_id",
                "status",
                "policy_id",
                "policy_sha256",
                "ssh_keygen_sha256",
                "ledger_instance_id",
                "ledger_path_binding_hash",
                "minimum_policy_epoch",
                "not_before",
                "expires_at",
            },
            f"enrollment entries[{index}]",
        )
        entries.append(ProductionTrustEnrollmentEntryV1(**item))
    data = dict(raw)
    data["entries"] = tuple(entries)
    return ProductionTrustEnrollmentRegistryV1(**data)


def load_production_trust_enrollment_registry_v1(
    path: Path | None = None,
) -> tuple[ProductionTrustEnrollmentRegistryV1, str]:
    registry_path = (
        production_trust_enrollment_registry_path_v1() if path is None else path
    )
    if not isinstance(registry_path, Path) or not registry_path.is_absolute():
        raise ProductionTrustEnrollmentError(
            "enrollment registry path must be an absolute pathlib.Path"
        )
    try:
        resolved = registry_path.resolve(strict=True)
        payload = _read_bounded_file(
            resolved,
            "production trust enrollment registry",
            _MAX_REGISTRY_BYTES,
        )
        raw = _parse_json_payload(
            payload,
            "production trust enrollment registry",
        )
    except ProductionTrustEnrollmentError:
        raise
    except (OSError, UnicodeError, ValueError) as error:
        raise ProductionTrustEnrollmentError(
            "fixed production trust enrollment registry is unavailable or invalid"
        ) from error
    return (
        parse_production_trust_enrollment_registry_v1(raw),
        hashlib.sha256(payload).hexdigest(),
    )


def resolve_production_trust_enrollment_v1(
    context: ProductionTrustContextV1,
) -> ResolvedProductionTrustEnrollmentV1:
    """Resolve one active enrollment from the fixed external registry path."""

    if type(context) is not ProductionTrustContextV1:
        raise ProductionTrustEnrollmentError(
            "enrollment resolution requires exact ProductionTrustContextV1"
        )
    context.__post_init__()
    registry_path = production_trust_enrollment_registry_path_v1()
    if not isinstance(registry_path, Path) or not registry_path.is_absolute():
        raise ProductionTrustEnrollmentError(
            "fixed production trust enrollment registry path is invalid"
        )
    try:
        resolved_registry_path = registry_path.resolve(strict=True)
        artifact_root = context.artifact_root.resolve(strict=True)
        resolved_registry_path.relative_to(artifact_root)
    except ValueError:
        pass
    except OSError as error:
        raise ProductionTrustEnrollmentError(
            "fixed production trust enrollment registry is unavailable"
        ) from error
    else:
        raise ProductionTrustEnrollmentError(
            "production trust enrollment registry must be outside artifact_root"
        )
    registry, registry_sha = load_production_trust_enrollment_registry_v1(
        resolved_registry_path
    )
    try:
        policy_path = context.policy_path.resolve(strict=True)
        policy_payload = _read_bounded_file(
            policy_path,
            "enrolled production trust policy",
            _MAX_POLICY_BYTES,
        )
    except ProductionTrustEnrollmentError:
        raise
    except OSError as error:
        raise ProductionTrustEnrollmentError(
            "enrolled policy cannot be read"
        ) from error
    if hashlib.sha256(policy_payload).hexdigest() != context.expected_policy_sha256:
        raise ProductionTrustEnrollmentError("context policy pin differs before enrollment")
    try:
        policy = parse_production_trust_policy_v1(
            _parse_json_payload(policy_payload, "enrolled production trust policy")
        )
    except Exception as error:
        raise ProductionTrustEnrollmentError("enrolled policy is invalid") from error
    try:
        ledger_path = context.ledger_path.resolve(strict=True)
    except OSError as error:
        raise ProductionTrustEnrollmentError(
            "enrolled production trust ledger is unavailable"
        ) from error
    if not ledger_path.is_file() or _is_within(ledger_path, artifact_root):
        raise ProductionTrustEnrollmentError(
            "enrolled production trust ledger must be a file outside artifact_root"
        )
    ledger_path_binding_hash = production_trust_ledger_path_binding_hash_v1(
        ledger_path
    )
    ledger_instance_id = _read_ledger_instance_id(ledger_path)
    now = context.trusted_time.astimezone(timezone.utc)
    matches = tuple(
        value
        for value in registry.entries
        if value.status == "active"
        and value.policy_id == policy.policy_id
        and value.policy_sha256 == context.expected_policy_sha256
        and value.ssh_keygen_sha256 == context.expected_ssh_keygen_sha256
        and value.ledger_instance_id == ledger_instance_id
        and value.ledger_path_binding_hash == ledger_path_binding_hash
        and policy.policy_epoch >= value.minimum_policy_epoch
        and _timestamp(value.not_before, "not_before") <= now
        <= _timestamp(value.expires_at, "expires_at")
    )
    if len(matches) != 1:
        raise ProductionTrustEnrollmentError(
            "current policy/verifier has no unique active out-of-band enrollment"
        )
    entry = matches[0]
    return ResolvedProductionTrustEnrollmentV1(
        schema_version=PRODUCTION_TRUST_ENROLLMENT_SCHEMA_VERSION,
        domain=PRODUCTION_TRUST_ENROLLMENT_DOMAIN,
        registry_id=registry.registry_id,
        registry_sha256=registry_sha,
        enrollment_id=entry.enrollment_id,
        policy_id=entry.policy_id,
        policy_sha256=entry.policy_sha256,
        ssh_keygen_sha256=entry.ssh_keygen_sha256,
        ledger_instance_id=entry.ledger_instance_id,
        ledger_path_binding_hash=entry.ledger_path_binding_hash,
        minimum_policy_epoch=entry.minimum_policy_epoch,
        not_before=entry.not_before,
        expires_at=entry.expires_at,
    )


def validate_production_trust_receipt_enrollment_v1(
    enrollment: ResolvedProductionTrustEnrollmentV1,
    receipt: ResolvedProductionTrustV1,
) -> None:
    if type(enrollment) is not ResolvedProductionTrustEnrollmentV1:
        raise ProductionTrustEnrollmentError("receipt validation requires exact enrollment")
    if type(receipt) is not ResolvedProductionTrustV1:
        raise ProductionTrustEnrollmentError("receipt validation requires exact trust receipt")
    enrollment.__post_init__()
    receipt.__post_init__()
    if (
        receipt.policy_id != enrollment.policy_id
        or receipt.policy_sha256 != enrollment.policy_sha256
        or receipt.policy_epoch < enrollment.minimum_policy_epoch
    ):
        raise ProductionTrustEnrollmentError(
            "resolved trust receipt differs from out-of-band enrollment"
        )


def production_trust_ledger_path_binding_hash_v1(path: Path) -> str:
    """Return a domain-separated identity for one already-provisioned ledger path."""

    if not isinstance(path, Path) or not path.is_absolute():
        raise ProductionTrustEnrollmentError(
            "ledger path binding requires an absolute pathlib.Path"
        )
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise ProductionTrustEnrollmentError(
            "ledger path binding target is unavailable"
        ) from error
    if not resolved.is_file():
        raise ProductionTrustEnrollmentError(
            "ledger path binding target must be a regular file"
        )
    normalized = str(resolved).replace("\\", "/")
    if os.name == "nt":
        normalized = normalized.casefold()
    return canonical_hash(
        {
            "domain": PRODUCTION_TRUST_ENROLLMENT_DOMAIN,
            "kind": "production-trust-ledger-path-v1",
            "normalized_absolute_path": normalized,
        }
    )


def _read_ledger_instance_id(path: Path) -> str:
    try:
        uri = path.resolve(strict=True).as_uri() + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=5.0)
        try:
            connection.execute("PRAGMA trusted_schema = OFF")
            connection.execute("PRAGMA query_only = ON")
            rows = connection.execute(
                "SELECT singleton, ledger_instance_id "
                "FROM production_trust_ledger_identity ORDER BY singleton"
            ).fetchall()
        finally:
            connection.close()
    except (OSError, sqlite3.Error) as error:
        raise ProductionTrustEnrollmentError(
            "production trust ledger identity is unavailable or invalid"
        ) from error
    if len(rows) != 1 or rows[0][0] != 1:
        raise ProductionTrustEnrollmentError(
            "production trust ledger requires one enrolled identity"
        )
    ledger_instance_id = rows[0][1]
    _stable(ledger_instance_id, "ledger_instance_id")
    return ledger_instance_id


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def revalidate_production_trust_enrollment_v1(
    context: ProductionTrustContextV1,
    expected: ResolvedProductionTrustEnrollmentV1,
) -> ResolvedProductionTrustEnrollmentV1:
    """Require the fixed registry to retain the exact previously resolved binding."""

    if type(expected) is not ResolvedProductionTrustEnrollmentV1:
        raise ProductionTrustEnrollmentError(
            "enrollment revalidation requires an exact resolved enrollment"
        )
    expected.__post_init__()
    current = resolve_production_trust_enrollment_v1(context)
    if current != expected:
        raise ProductionTrustEnrollmentError(
            "production trust enrollment registry changed during verification"
        )
    return current


def _timestamp(value: Any, label: str) -> datetime:
    if type(value) is not str or not value:
        raise ProductionTrustEnrollmentError(f"{label} must be a timestamp string")
    if _TIMESTAMP.fullmatch(value) is None:
        raise ProductionTrustEnrollmentError(
            f"{label} must be an offset-aware RFC 3339 timestamp"
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ProductionTrustEnrollmentError(f"invalid {label}") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ProductionTrustEnrollmentError(f"{label} must include timezone")
    return parsed.astimezone(timezone.utc)


def _stable(value: Any, label: str) -> None:
    if type(value) is not str or _STABLE_ID.fullmatch(value) is None:
        raise ProductionTrustEnrollmentError(f"{label} must be a stable ID")


def _constant(value: Any, expected: str, label: str) -> None:
    if type(value) is not str or value != expected:
        raise ProductionTrustEnrollmentError(f"{label} differs")


def _sha(value: Any, label: str) -> None:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ProductionTrustEnrollmentError(f"{label} must be a lowercase SHA-256")


def _object(value: Any, label: str) -> dict[str, Any]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise ProductionTrustEnrollmentError(f"{label} must be an object")
    return value


def _exact(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ProductionTrustEnrollmentError(f"{label} fields differ")


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProductionTrustEnrollmentError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_number(value: str) -> None:
    raise ProductionTrustEnrollmentError(f"non-integer JSON number is prohibited: {value}")


def _read_bounded_file(path: Path, label: str, maximum_bytes: int) -> bytes:
    try:
        if not path.is_file():
            raise OSError(f"{label} is not a regular file")
        if path.stat().st_size > maximum_bytes:
            raise OSError(f"{label} exceeds size limit")
        payload = path.read_bytes()
        if len(payload) > maximum_bytes:
            raise OSError(f"{label} exceeds size limit")
        return payload
    except OSError as error:
        raise ProductionTrustEnrollmentError(f"cannot read {label}") from error


def _parse_json_payload(payload: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicates,
            parse_float=_reject_number,
            parse_constant=_reject_number,
        )
    except ProductionTrustEnrollmentError:
        raise
    except (UnicodeError, ValueError) as error:
        raise ProductionTrustEnrollmentError(f"{label} is not strict UTF-8 JSON") from error
    return _object(value, label)


__all__ = [
    "PRODUCTION_TRUST_ENROLLMENT_DOMAIN",
    "PRODUCTION_TRUST_ENROLLMENT_SCHEMA_VERSION",
    "ProductionTrustEnrollmentEntryV1",
    "ProductionTrustEnrollmentError",
    "ProductionTrustEnrollmentRegistryV1",
    "ResolvedProductionTrustEnrollmentV1",
    "load_production_trust_enrollment_registry_v1",
    "parse_production_trust_enrollment_registry_v1",
    "production_trust_ledger_path_binding_hash_v1",
    "production_trust_enrollment_registry_path_v1",
    "revalidate_production_trust_enrollment_v1",
    "resolve_production_trust_enrollment_v1",
    "validate_production_trust_receipt_enrollment_v1",
]
