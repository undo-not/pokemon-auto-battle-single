"""Strict resolver-backed source contracts for SIM-02B promotion.

This module is intentionally independent from the frozen intake-diagnostic v1
compiler.  A caller supplies filesystem locations rather than a scope argument.
The resolver derives a metadata scope from a strict manifest and its separately
hashed license artifact after re-reading every declared artifact.  This proves
local content integrity, not issuer authenticity: production issuance also
requires an artifact-root-external trust anchor in the promotion compiler.

Resolved dataclasses contain only portable identity data.  Paths and payload
bytes remain outside their canonical hash payloads; :func:`read_resolved_artifact`
revalidates the bytes whenever a downstream compiler needs their contents.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
from typing import Any
from urllib.parse import urlparse

from champions_sim.core import canonical_hash


PROMOTION_SOURCE_SCHEMA_VERSION = "2.0.0"
PROMOTION_LICENSE_SCHEMA_VERSION = "2.0.0"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_STABLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,239}$")


class PromotionSourceError(ValueError):
    """A source manifest, license, artifact, or record cannot be resolved."""


class PromotionSourceScopeV2(str, Enum):
    TEST_AUTHORITATIVE = "test_authoritative"
    PRODUCTION_CHAMPIONS = "production_champions"


class PromotionSourceKindV2(str, Enum):
    TEST_FIXTURE = "test_fixture"
    OFFICIAL_RULE = "official_rule"
    OFFICIAL_CATALOG = "official_catalog"
    PRIMARY_REFERENCE = "primary_reference"


class PromotionSourceAuthorityV2(str, Enum):
    TEST_AUTHORITATIVE = "test_authoritative"
    OFFICIAL = "official"
    PRIMARY = "primary"


class PromotionArtifactRoleV2(str, Enum):
    LICENSE_RECORD = "license_record"
    SOURCE_DATA = "source_data"


@dataclass(frozen=True, slots=True)
class PromotionRecordReferenceV2:
    evidence_ref_id: str
    source_manifest_id: str
    artifact_id: str
    json_pointer: str
    record_sha256: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.evidence_ref_id, "evidence_ref_id"),
            (self.source_manifest_id, "source_manifest_id"),
            (self.artifact_id, "artifact_id"),
        ):
            _require_stable_id(value, label)
        _require_exact_string(self.json_pointer, "json_pointer")
        if self.json_pointer and not self.json_pointer.startswith("/"):
            raise PromotionSourceError("json_pointer must be empty or start with '/'")
        _decode_json_pointer(self.json_pointer)
        _require_sha256(self.record_sha256, "record_sha256")


@dataclass(frozen=True, slots=True)
class ResolvedArtifactV2:
    source_manifest_id: str
    artifact_id: str
    role: PromotionArtifactRoleV2
    relative_path: str
    media_type: str
    byte_count: int
    sha256: str

    def __post_init__(self) -> None:
        _require_stable_id(self.source_manifest_id, "source_manifest_id")
        _require_stable_id(self.artifact_id, "artifact_id")
        if type(self.role) is not PromotionArtifactRoleV2:
            raise PromotionSourceError("artifact role must use the exact V2 enum")
        _validate_relative_artifact_path(self.relative_path)
        _require_exact_string(self.media_type, "media_type")
        if not self.media_type.strip():
            raise PromotionSourceError("media_type must not be empty")
        if type(self.byte_count) is not int or self.byte_count < 0:
            raise PromotionSourceError("byte_count must be a non-negative exact integer")
        _require_sha256(self.sha256, "artifact sha256")

    @property
    def artifact_hash(self) -> str:
        return canonical_hash(self)


@dataclass(frozen=True, slots=True)
class ResolvedLicenseV2:
    license_id: str
    source_manifest_id: str
    artifact_id: str
    artifact_sha256: str
    record_hash: str
    verification_status: str
    license_identifier: str | None
    license_url: str | None
    local_research_allowed: bool
    private_match_allowed: bool
    training_allowed: bool
    redistribution: str
    commercial_use: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.license_id, "license_id"),
            (self.source_manifest_id, "source_manifest_id"),
            (self.artifact_id, "license artifact_id"),
        ):
            _require_stable_id(value, label)
        _require_sha256(self.artifact_sha256, "license artifact sha256")
        _require_sha256(self.record_hash, "license record hash")
        if type(self.verification_status) is not str or self.verification_status not in {
            "test_authoritative",
            "verified",
        }:
            raise PromotionSourceError("unsupported license verification_status")
        _require_optional_string(self.license_identifier, "license_identifier")
        _require_optional_string(self.license_url, "license_url")
        if self.license_url is not None:
            try:
                parsed = urlparse(self.license_url)
            except ValueError as error:
                raise PromotionSourceError(
                    "license_url must be an absolute HTTP(S) URL"
                ) from error
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise PromotionSourceError("license_url must be an absolute HTTP(S) URL")
        for value, label in (
            (self.local_research_allowed, "local_research_allowed"),
            (self.private_match_allowed, "private_match_allowed"),
            (self.training_allowed, "training_allowed"),
        ):
            if type(value) is not bool:
                raise PromotionSourceError(f"{label} must be an exact boolean")
        if self.redistribution not in {"allowed", "prohibited"}:
            raise PromotionSourceError("unsupported redistribution policy")
        _require_exact_string(self.redistribution, "redistribution")
        if self.commercial_use not in {"allowed", "prohibited"}:
            raise PromotionSourceError("unsupported commercial_use policy")
        _require_exact_string(self.commercial_use, "commercial_use")

    @property
    def license_hash(self) -> str:
        return canonical_hash(self)


@dataclass(frozen=True, slots=True)
class ResolvedPromotionRecordV2:
    reference: PromotionRecordReferenceV2
    canonical_record_hash: str

    def __post_init__(self) -> None:
        if type(self.reference) is not PromotionRecordReferenceV2:
            raise PromotionSourceError("record reference must use the exact V2 contract")
        self.reference.__post_init__()
        _require_sha256(self.canonical_record_hash, "canonical_record_hash")
        if self.canonical_record_hash != self.reference.record_sha256:
            raise PromotionSourceError("resolved record hash differs from its reference")


@dataclass(frozen=True, slots=True)
class ResolvedPromotionSourceManifestV2:
    schema_version: str
    manifest_id: str
    source_kind: PromotionSourceKindV2
    authority: PromotionSourceAuthorityV2
    title: str
    publisher: str
    locator_kind: str
    locator_value: str
    retrieved_at: str
    manifest_hash: str
    license: ResolvedLicenseV2
    scope: PromotionSourceScopeV2
    artifacts: tuple[ResolvedArtifactV2, ...]
    records: tuple[ResolvedPromotionRecordV2, ...]

    def __post_init__(self) -> None:
        _require_exact_string(self.schema_version, "schema_version")
        if self.schema_version != PROMOTION_SOURCE_SCHEMA_VERSION:
            raise PromotionSourceError("unsupported promotion source schema_version")
        _require_stable_id(self.manifest_id, "manifest_id")
        if type(self.source_kind) is not PromotionSourceKindV2:
            raise PromotionSourceError("source_kind must use the exact V2 enum")
        if type(self.authority) is not PromotionSourceAuthorityV2:
            raise PromotionSourceError("authority must use the exact V2 enum")
        for value, label in (
            (self.title, "title"),
            (self.publisher, "publisher"),
            (self.locator_kind, "locator.kind"),
            (self.locator_value, "locator.value"),
            (self.retrieved_at, "retrieved_at"),
        ):
            _require_exact_string(value, label)
            if not value.strip():
                raise PromotionSourceError(f"{label} must not be empty")
        _validate_locator(self.locator_kind, self.locator_value)
        _validate_timestamp(self.retrieved_at)
        _require_sha256(self.manifest_hash, "manifest_hash")
        if type(self.license) is not ResolvedLicenseV2:
            raise PromotionSourceError("license must use the exact resolved V2 contract")
        self.license.__post_init__()
        if self.license.source_manifest_id != self.manifest_id:
            raise PromotionSourceError("license is bound to another source manifest")
        if type(self.scope) is not PromotionSourceScopeV2:
            raise PromotionSourceError("scope must use the exact V2 enum")
        if type(self.artifacts) is not tuple or not self.artifacts:
            raise PromotionSourceError("resolved source requires an exact non-empty artifact tuple")
        if any(type(value) is not ResolvedArtifactV2 for value in self.artifacts):
            raise PromotionSourceError("artifacts must use exact ResolvedArtifactV2 values")
        for artifact in self.artifacts:
            artifact.__post_init__()
            if artifact.source_manifest_id != self.manifest_id:
                raise PromotionSourceError("artifact is bound to another source manifest")
        artifact_ids = tuple(value.artifact_id for value in self.artifacts)
        if artifact_ids != tuple(sorted(artifact_ids)) or len(artifact_ids) != len(set(artifact_ids)):
            raise PromotionSourceError("artifacts must be unique and ordered by artifact_id")
        license_artifacts = tuple(
            value for value in self.artifacts
            if value.role is PromotionArtifactRoleV2.LICENSE_RECORD
        )
        if len(license_artifacts) != 1:
            raise PromotionSourceError("resolved source requires exactly one license artifact")
        if license_artifacts[0].artifact_id != self.license.artifact_id:
            raise PromotionSourceError("license record is bound to another artifact")
        if license_artifacts[0].sha256 != self.license.artifact_sha256:
            raise PromotionSourceError("license artifact sha256 binding differs")
        if not any(
            value.role is PromotionArtifactRoleV2.SOURCE_DATA for value in self.artifacts
        ):
            raise PromotionSourceError("resolved source requires at least one source-data artifact")
        if type(self.records) is not tuple:
            raise PromotionSourceError("records must be an exact tuple")
        if any(type(value) is not ResolvedPromotionRecordV2 for value in self.records):
            raise PromotionSourceError("records must use exact ResolvedPromotionRecordV2 values")
        for record in self.records:
            record.__post_init__()
            if record.reference.source_manifest_id != self.manifest_id:
                raise PromotionSourceError("record is bound to another source manifest")
            record_artifact = next(
                (
                    artifact
                    for artifact in self.artifacts
                    if artifact.artifact_id == record.reference.artifact_id
                ),
                None,
            )
            if record_artifact is None:
                raise PromotionSourceError("record names an undeclared artifact")
            if record_artifact.role is not PromotionArtifactRoleV2.SOURCE_DATA:
                raise PromotionSourceError("record must name a source_data artifact")
        record_ids = tuple(value.reference.evidence_ref_id for value in self.records)
        if record_ids != tuple(sorted(record_ids)) or len(record_ids) != len(set(record_ids)):
            raise PromotionSourceError("records must be unique and ordered by evidence_ref_id")
        derived = _derive_scope(self.source_kind, self.authority, self.license)
        if self.scope is not derived:
            raise PromotionSourceError("source scope differs from resolved manifest/license substance")

    @property
    def resolution_hash(self) -> str:
        return canonical_hash(
            {
                "schema_version": self.schema_version,
                "manifest_id": self.manifest_id,
                "source_kind": self.source_kind,
                "authority": self.authority,
                "title": self.title,
                "publisher": self.publisher,
                "locator": {"kind": self.locator_kind, "value": self.locator_value},
                "retrieved_at": self.retrieved_at,
                "manifest_hash": self.manifest_hash,
                "license": self.license,
                "scope": self.scope,
                "artifacts": self.artifacts,
                "records": self.records,
            }
        )

    def artifact(self, artifact_id: str) -> ResolvedArtifactV2:
        _require_stable_id(artifact_id, "artifact_id")
        for value in self.artifacts:
            if value.artifact_id == artifact_id:
                return value
        raise PromotionSourceError(f"source manifest does not declare artifact: {artifact_id}")


def resolve_promotion_source_manifest_v2(
    manifest_path: Path | str,
    *,
    artifact_root: Path | str,
    record_references: tuple[PromotionRecordReferenceV2, ...] = (),
) -> ResolvedPromotionSourceManifestV2:
    """Resolve one exact manifest, license artifact, data artifacts, and records.

    Every declared artifact is re-read and checked even when no record points to
    it.  ``record_references`` are normalized by evidence ID only after their
    exact type and uniqueness contracts have been validated.
    """

    if type(record_references) is not tuple:
        raise PromotionSourceError("record_references must be an exact tuple")
    if any(type(value) is not PromotionRecordReferenceV2 for value in record_references):
        raise PromotionSourceError("record_references require exact V2 reference values")
    for value in record_references:
        value.__post_init__()
    evidence_ids = tuple(value.evidence_ref_id for value in record_references)
    if len(evidence_ids) != len(set(evidence_ids)):
        raise PromotionSourceError("record evidence_ref_ids must be unique")

    raw = _read_json_object(Path(manifest_path), "promotion source manifest")
    _require_exact_keys(
        raw,
        {
            "schema_version",
            "manifest_id",
            "source_kind",
            "authority",
            "title",
            "publisher",
            "locator",
            "retrieved_at",
            "license_artifact_id",
            "artifacts",
        },
        "promotion source manifest",
    )
    if raw["schema_version"] != PROMOTION_SOURCE_SCHEMA_VERSION:
        raise PromotionSourceError("unsupported promotion source manifest schema_version")
    manifest_id = _string(raw["manifest_id"], "manifest_id")
    _require_stable_id(manifest_id, "manifest_id")
    source_kind = _enum(
        raw["source_kind"], PromotionSourceKindV2, "source_kind"
    )
    authority = _enum(
        raw["authority"], PromotionSourceAuthorityV2, "authority"
    )
    title = _nonempty_string(raw["title"], "title")
    publisher = _nonempty_string(raw["publisher"], "publisher")
    locator_raw = _object(raw["locator"], "locator")
    _require_exact_keys(locator_raw, {"kind", "value"}, "locator")
    locator_kind = _string(locator_raw["kind"], "locator.kind")
    locator_value = _nonempty_string(locator_raw["value"], "locator.value")
    _validate_locator(locator_kind, locator_value)
    retrieved_at = _nonempty_string(raw["retrieved_at"], "retrieved_at")
    _validate_timestamp(retrieved_at)
    license_artifact_id = _string(raw["license_artifact_id"], "license_artifact_id")
    _require_stable_id(license_artifact_id, "license_artifact_id")

    artifacts_raw = _array(raw["artifacts"], "artifacts")
    if not artifacts_raw:
        raise PromotionSourceError("promotion source manifest requires artifacts")
    artifacts: list[ResolvedArtifactV2] = []
    for index, value in enumerate(artifacts_raw):
        item = _object(value, f"artifacts[{index}]")
        _require_exact_keys(
            item,
            {
                "artifact_id",
                "role",
                "relative_path",
                "media_type",
                "byte_count",
                "sha256",
            },
            f"artifacts[{index}]",
        )
        artifact = ResolvedArtifactV2(
            source_manifest_id=manifest_id,
            artifact_id=_string(item["artifact_id"], f"artifacts[{index}].artifact_id"),
            role=_enum(item["role"], PromotionArtifactRoleV2, f"artifacts[{index}].role"),
            relative_path=_string(
                item["relative_path"], f"artifacts[{index}].relative_path"
            ),
            media_type=_string(item["media_type"], f"artifacts[{index}].media_type"),
            byte_count=_integer(item["byte_count"], f"artifacts[{index}].byte_count"),
            sha256=_string(item["sha256"], f"artifacts[{index}].sha256"),
        )
        artifacts.append(artifact)
    artifact_ids = tuple(value.artifact_id for value in artifacts)
    if artifact_ids != tuple(sorted(artifact_ids)):
        raise PromotionSourceError("manifest artifacts must be ordered by artifact_id")
    if len(artifact_ids) != len(set(artifact_ids)):
        raise PromotionSourceError("manifest artifact IDs must be unique")
    resolved_artifacts = tuple(artifacts)
    by_id = {value.artifact_id: value for value in resolved_artifacts}
    if license_artifact_id not in by_id:
        raise PromotionSourceError("license_artifact_id is not declared")
    license_artifact = by_id[license_artifact_id]
    if license_artifact.role is not PromotionArtifactRoleV2.LICENSE_RECORD:
        raise PromotionSourceError("license_artifact_id must name the license_record artifact")
    if sum(
        value.role is PromotionArtifactRoleV2.LICENSE_RECORD
        for value in resolved_artifacts
    ) != 1:
        raise PromotionSourceError("manifest must declare exactly one license_record artifact")
    if not any(
        value.role is PromotionArtifactRoleV2.SOURCE_DATA
        for value in resolved_artifacts
    ):
        raise PromotionSourceError("manifest must declare source_data artifacts")

    for artifact in resolved_artifacts:
        read_resolved_artifact(artifact_root, artifact)
    license_payload = read_resolved_artifact(artifact_root, license_artifact)
    if not _json_media_type(license_artifact.media_type):
        raise PromotionSourceError("license artifact must use a JSON media type")
    license_raw = _parse_json_object(license_payload, "promotion license artifact")
    license = _resolve_license(license_raw, manifest_id, license_artifact)
    scope = _derive_scope(source_kind, authority, license)

    resolved_records: list[ResolvedPromotionRecordV2] = []
    for reference in sorted(record_references, key=lambda value: value.evidence_ref_id):
        if reference.source_manifest_id != manifest_id:
            raise PromotionSourceError("record reference names another source manifest")
        artifact = by_id.get(reference.artifact_id)
        if artifact is None:
            raise PromotionSourceError("record reference names an undeclared artifact")
        read_resolved_json_record(artifact_root, artifact, reference)
        resolved_records.append(
            ResolvedPromotionRecordV2(
                reference=reference,
                canonical_record_hash=reference.record_sha256,
            )
        )

    return ResolvedPromotionSourceManifestV2(
        schema_version=PROMOTION_SOURCE_SCHEMA_VERSION,
        manifest_id=manifest_id,
        source_kind=source_kind,
        authority=authority,
        title=title,
        publisher=publisher,
        locator_kind=locator_kind,
        locator_value=locator_value,
        retrieved_at=retrieved_at,
        manifest_hash=canonical_hash(raw),
        license=license,
        scope=scope,
        artifacts=resolved_artifacts,
        records=tuple(resolved_records),
    )


def read_resolved_artifact(
    artifact_root: Path | str,
    artifact: ResolvedArtifactV2,
) -> bytes:
    """Re-read a resolved artifact with containment, size, and hash checks."""

    if type(artifact) is not ResolvedArtifactV2:
        raise PromotionSourceError("artifact must use the exact resolved V2 contract")
    artifact.__post_init__()
    try:
        root = Path(artifact_root).resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise PromotionSourceError("artifact_root does not resolve") from error
    if not root.is_dir():
        raise PromotionSourceError("artifact_root must be a directory")
    path = PurePosixPath(artifact.relative_path)
    candidate = root.joinpath(*path.parts)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError) as error:
        raise PromotionSourceError("artifact path escapes or is missing from artifact_root") from error
    if not resolved.is_file():
        raise PromotionSourceError("resolved artifact is not a regular file")
    try:
        payload = resolved.read_bytes()
    except OSError as error:
        raise PromotionSourceError("resolved artifact cannot be read") from error
    digest = hashlib.sha256(payload).hexdigest()
    if len(payload) != artifact.byte_count:
        raise PromotionSourceError(f"artifact byte_count mismatch: {artifact.artifact_id}")
    if digest != artifact.sha256:
        raise PromotionSourceError(f"artifact sha256 mismatch: {artifact.artifact_id}")
    return payload


def read_resolved_json_record(
    artifact_root: Path | str,
    artifact: ResolvedArtifactV2,
    reference: PromotionRecordReferenceV2,
) -> Any:
    """Return one verified JSON-pointer value from a resolved source artifact."""

    if type(artifact) is not ResolvedArtifactV2:
        raise PromotionSourceError("artifact must use the exact resolved V2 contract")
    if type(reference) is not PromotionRecordReferenceV2:
        raise PromotionSourceError("reference must use the exact V2 contract")
    artifact.__post_init__()
    reference.__post_init__()
    if artifact.role is not PromotionArtifactRoleV2.SOURCE_DATA:
        raise PromotionSourceError("record references may only target source_data artifacts")
    if (
        reference.source_manifest_id != artifact.source_manifest_id
        or reference.artifact_id != artifact.artifact_id
    ):
        raise PromotionSourceError("record reference does not match its resolved artifact")
    if not _json_media_type(artifact.media_type):
        raise PromotionSourceError("record artifact must use a JSON media type")
    payload = read_resolved_artifact(artifact_root, artifact)
    document = _parse_json_value(payload, f"artifact {artifact.artifact_id}")
    record = _resolve_json_pointer(document, reference.json_pointer)
    try:
        record_hash = canonical_hash(record)
    except (TypeError, ValueError) as error:
        raise PromotionSourceError("referenced JSON record is not canonical domain data") from error
    if record_hash != reference.record_sha256:
        raise PromotionSourceError("JSON record hash mismatch")
    return record


def _resolve_license(
    raw: dict[str, Any],
    manifest_id: str,
    artifact: ResolvedArtifactV2,
) -> ResolvedLicenseV2:
    _require_exact_keys(
        raw,
        {
            "schema_version",
            "license_id",
            "source_manifest_id",
            "verification_status",
            "license_identifier",
            "license_url",
            "use_policy",
        },
        "promotion license artifact",
    )
    if raw["schema_version"] != PROMOTION_LICENSE_SCHEMA_VERSION:
        raise PromotionSourceError("unsupported promotion license schema_version")
    if raw["source_manifest_id"] != manifest_id:
        raise PromotionSourceError("license artifact names another source manifest")
    policy = _object(raw["use_policy"], "license use_policy")
    _require_exact_keys(
        policy,
        {
            "local_research_allowed",
            "private_match_allowed",
            "training_allowed",
            "redistribution",
            "commercial_use",
        },
        "license use_policy",
    )
    return ResolvedLicenseV2(
        license_id=_string(raw["license_id"], "license_id"),
        source_manifest_id=_string(raw["source_manifest_id"], "source_manifest_id"),
        artifact_id=artifact.artifact_id,
        artifact_sha256=artifact.sha256,
        record_hash=canonical_hash(raw),
        verification_status=_string(raw["verification_status"], "verification_status"),
        license_identifier=_nullable_string(raw["license_identifier"], "license_identifier"),
        license_url=_nullable_string(raw["license_url"], "license_url"),
        local_research_allowed=_boolean(
            policy["local_research_allowed"], "local_research_allowed"
        ),
        private_match_allowed=_boolean(
            policy["private_match_allowed"], "private_match_allowed"
        ),
        training_allowed=_boolean(policy["training_allowed"], "training_allowed"),
        redistribution=_string(policy["redistribution"], "redistribution"),
        commercial_use=_string(policy["commercial_use"], "commercial_use"),
    )


def _derive_scope(
    source_kind: PromotionSourceKindV2,
    authority: PromotionSourceAuthorityV2,
    license: ResolvedLicenseV2,
) -> PromotionSourceScopeV2:
    if not (
        license.local_research_allowed
        and license.private_match_allowed
        and license.training_allowed
    ):
        raise PromotionSourceError(
            "promotion requires local research, private-match, and training permission"
        )
    if source_kind is PromotionSourceKindV2.TEST_FIXTURE:
        if (
            authority is not PromotionSourceAuthorityV2.TEST_AUTHORITATIVE
            or license.verification_status != "test_authoritative"
        ):
            raise PromotionSourceError("test fixture authority/license combination is invalid")
        return PromotionSourceScopeV2.TEST_AUTHORITATIVE

    expected_authority = (
        PromotionSourceAuthorityV2.PRIMARY
        if source_kind is PromotionSourceKindV2.PRIMARY_REFERENCE
        else PromotionSourceAuthorityV2.OFFICIAL
    )
    if authority is not expected_authority or license.verification_status != "verified":
        raise PromotionSourceError("production source authority/license combination is invalid")
    if license.license_identifier is None and license.license_url is None:
        raise PromotionSourceError(
            "production verified license requires an identifier or URL"
        )
    return PromotionSourceScopeV2.PRODUCTION_CHAMPIONS


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = path.read_bytes()
    except OSError as error:
        raise PromotionSourceError(f"{label} cannot be read") from error
    return _parse_json_object(payload, label)


def _parse_json_object(payload: bytes, label: str) -> dict[str, Any]:
    value = _parse_json_value(payload, label)
    return _object(value, label)


def _parse_json_value(payload: bytes, label: str) -> Any:
    try:
        text = payload.decode("utf-8")
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_float=_parse_finite_float,
            parse_constant=_reject_nonfinite_number,
        )
    except PromotionSourceError:
        raise
    except (UnicodeDecodeError, ValueError) as error:
        raise PromotionSourceError(f"invalid UTF-8 JSON for {label}") from error


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PromotionSourceError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_nonfinite_number(value: str) -> None:
    raise PromotionSourceError(f"non-finite JSON number is prohibited: {value}")


def _parse_finite_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise PromotionSourceError(f"non-finite JSON number is prohibited: {value}")
    return result


def _resolve_json_pointer(document: Any, pointer: str) -> Any:
    tokens = _decode_json_pointer(pointer)
    current = document
    for token in tokens:
        if type(current) is dict:
            if token not in current:
                raise PromotionSourceError(f"JSON pointer object key is missing: {token}")
            current = current[token]
        elif type(current) is list:
            if re.fullmatch(r"0|[1-9][0-9]*", token) is None:
                raise PromotionSourceError(f"invalid JSON pointer array index: {token}")
            try:
                index = int(token)
            except ValueError as error:
                raise PromotionSourceError(
                    f"invalid JSON pointer array index: {token}"
                ) from error
            if index >= len(current):
                raise PromotionSourceError(f"JSON pointer array index is out of range: {token}")
            current = current[index]
        else:
            raise PromotionSourceError("JSON pointer traverses a scalar value")
    return current


def _decode_json_pointer(pointer: str) -> tuple[str, ...]:
    if pointer == "":
        return ()
    if not pointer.startswith("/"):
        raise PromotionSourceError("JSON pointer must be empty or begin with '/'")
    decoded: list[str] = []
    for raw_token in pointer[1:].split("/"):
        token: list[str] = []
        index = 0
        while index < len(raw_token):
            value = raw_token[index]
            if value != "~":
                token.append(value)
                index += 1
                continue
            if index + 1 >= len(raw_token) or raw_token[index + 1] not in {"0", "1"}:
                raise PromotionSourceError("JSON pointer contains an invalid '~' escape")
            token.append("~" if raw_token[index + 1] == "0" else "/")
            index += 2
        decoded.append("".join(token))
    return tuple(decoded)


def _validate_relative_artifact_path(value: str) -> None:
    _require_exact_string(value, "relative_path")
    path = PurePosixPath(value)
    if (
        not value
        or value.startswith("/")
        or "\\" in value
        or ":" in value
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.as_posix() != value
    ):
        raise PromotionSourceError(
            "artifact relative_path must be a normalized relative POSIX path"
        )


def _validate_locator(kind: str, value: str) -> None:
    if kind not in {"logical", "url", "doi"}:
        raise PromotionSourceError("unsupported locator kind")
    if kind == "url":
        try:
            parsed = urlparse(value)
        except ValueError as error:
            raise PromotionSourceError("URL locator must be absolute HTTP(S)") from error
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise PromotionSourceError("URL locator must be absolute HTTP(S)")
    elif kind == "doi" and not value.startswith("10."):
        raise PromotionSourceError("DOI locator must start with '10.'")


def _validate_timestamp(value: str) -> None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise PromotionSourceError("retrieved_at must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PromotionSourceError("retrieved_at must include an explicit timezone")


def _json_media_type(value: str) -> bool:
    media_type = value.split(";", 1)[0].strip().lower()
    return media_type == "application/json" or media_type.endswith("+json")


def _require_exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise PromotionSourceError(
            f"{label} fields differ; missing={sorted(expected - set(value))}, "
            f"extra={sorted(set(value) - expected)}"
        )


def _object(value: Any, label: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise PromotionSourceError(f"{label} must be an exact JSON object")
    return value


def _array(value: Any, label: str) -> list[Any]:
    if type(value) is not list:
        raise PromotionSourceError(f"{label} must be an exact JSON array")
    return value


def _string(value: Any, label: str) -> str:
    if type(value) is not str:
        raise PromotionSourceError(f"{label} must be an exact string")
    return value


def _nonempty_string(value: Any, label: str) -> str:
    result = _string(value, label)
    if not result.strip():
        raise PromotionSourceError(f"{label} must not be empty")
    return result


def _nullable_string(value: Any, label: str) -> str | None:
    if value is None:
        return None
    return _string(value, label)


def _integer(value: Any, label: str) -> int:
    if type(value) is not int:
        raise PromotionSourceError(f"{label} must be an exact integer")
    return value


def _boolean(value: Any, label: str) -> bool:
    if type(value) is not bool:
        raise PromotionSourceError(f"{label} must be an exact boolean")
    return value


def _enum(value: Any, enum_type: type[Enum], label: str):
    raw = _string(value, label)
    try:
        return enum_type(raw)
    except ValueError as error:
        raise PromotionSourceError(f"unsupported {label}: {raw}") from error


def _require_exact_string(value: Any, label: str) -> None:
    if type(value) is not str:
        raise PromotionSourceError(f"{label} must be an exact string")


def _require_optional_string(value: Any, label: str) -> None:
    if value is not None and type(value) is not str:
        raise PromotionSourceError(f"{label} must be an exact string or null")
    if type(value) is str and not value.strip():
        raise PromotionSourceError(f"{label} must not be empty")


def _require_stable_id(value: Any, label: str) -> None:
    _require_exact_string(value, label)
    if _STABLE_ID.fullmatch(value) is None:
        raise PromotionSourceError(f"{label} must be a stable ID")


def _require_sha256(value: Any, label: str) -> None:
    _require_exact_string(value, label)
    if _SHA256.fullmatch(value) is None:
        raise PromotionSourceError(f"{label} must be a lowercase SHA-256")
