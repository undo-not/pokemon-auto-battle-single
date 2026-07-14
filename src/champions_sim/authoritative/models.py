"""Immutable, portable models for the SIM-02C-A intake workbench.

These documents are evidence-review work products.  They are deliberately not
accepted by the SIM-02B/V3 promotion compiler and always state that they are not
authorization.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Mapping


AUTHORITATIVE_INTAKE_SCHEMA_VERSION = "1.0.0"
AUTHORITATIVE_INTAKE_COMPILER_VERSION = "1.0.0"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_STABLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,239}$")


class AuthoritativeIntakeError(ValueError):
    """Raised when intake evidence cannot be reviewed deterministically."""


def canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as error:
        raise AuthoritativeIntakeError("value is not canonical JSON data") from error


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def require_stable_id(value: str, label: str) -> None:
    if type(value) is not str or not _STABLE_ID.fullmatch(value):
        raise AuthoritativeIntakeError(f"{label} is not a stable ID")


def require_sha256(value: str, label: str) -> None:
    if type(value) is not str or not _SHA256.fullmatch(value):
        raise AuthoritativeIntakeError(f"{label} is not a lowercase SHA-256")


@dataclass(frozen=True, slots=True)
class ArtifactIdentity:
    artifact_id: str
    root_kind: str
    relative_path: str
    role: str
    byte_count: int
    sha256: str

    def __post_init__(self) -> None:
        require_stable_id(self.artifact_id, "artifact_id")
        if self.root_kind not in {"repository", "legacy"}:
            raise AuthoritativeIntakeError("unsupported artifact root_kind")
        if type(self.relative_path) is not str or not self.relative_path:
            raise AuthoritativeIntakeError("artifact relative_path must not be empty")
        if type(self.role) is not str or not self.role:
            raise AuthoritativeIntakeError("artifact role must not be empty")
        if type(self.byte_count) is not int or self.byte_count < 0:
            raise AuthoritativeIntakeError("artifact byte_count must be non-negative")
        require_sha256(self.sha256, "artifact sha256")

    def to_data(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "root_kind": self.root_kind,
            "relative_path": self.relative_path,
            "role": self.role,
            "byte_count": self.byte_count,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class IntakeBlocker:
    stage: str
    code: str
    subject: str
    evidence_required: str
    restart_condition: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.stage, "blocker stage"),
            (self.code, "blocker code"),
            (self.subject, "blocker subject"),
        ):
            require_stable_id(value, label)
        for value, label in (
            (self.evidence_required, "evidence_required"),
            (self.restart_condition, "restart_condition"),
        ):
            if type(value) is not str or not value.strip():
                raise AuthoritativeIntakeError(f"{label} must not be empty")

    def to_data(self) -> dict[str, str]:
        return {
            "stage": self.stage,
            "code": self.code,
            "subject": self.subject,
            "evidence_required": self.evidence_required,
            "restart_condition": self.restart_condition,
        }


@dataclass(frozen=True, slots=True)
class AuthoritativeIntakeCompilation:
    plan_id: str
    plan_hash: str
    policy_registry_id: str
    policy_registry_hash: str
    source_lock_hash: str
    regulation_id: str
    regulation_revision: str
    target_pool_hash: str
    target_source_manifest_ids: tuple[str, ...]
    target_source_manifest_hash: str
    source_review: Mapping[str, Any]
    mapping_workbench: Mapping[str, Any]
    catalog_workbench: Mapping[str, Any]
    assessment: Mapping[str, Any]

    def __post_init__(self) -> None:
        for attribute in (
            "source_review",
            "mapping_workbench",
            "catalog_workbench",
            "assessment",
        ):
            value = getattr(self, attribute)
            if not isinstance(value, Mapping):
                raise AuthoritativeIntakeError(f"{attribute} must be a mapping")
            object.__setattr__(
                self,
                attribute,
                json.loads(canonical_json(value)),
            )
        for value, label in (
            (self.plan_id, "plan_id"),
            (self.policy_registry_id, "policy_registry_id"),
            (self.regulation_id, "regulation_id"),
            (self.regulation_revision, "regulation_revision"),
        ):
            require_stable_id(value, label)
        for value, label in (
            (self.plan_hash, "plan_hash"),
            (self.policy_registry_hash, "policy_registry_hash"),
            (self.source_lock_hash, "source_lock_hash"),
            (self.target_pool_hash, "target_pool_hash"),
            (self.target_source_manifest_hash, "target_source_manifest_hash"),
        ):
            require_sha256(value, label)
        if (
            not self.target_source_manifest_ids
            or tuple(sorted(self.target_source_manifest_ids))
            != self.target_source_manifest_ids
            or len(self.target_source_manifest_ids)
            != len(set(self.target_source_manifest_ids))
        ):
            raise AuthoritativeIntakeError(
                "target_source_manifest_ids must be non-empty, sorted, and unique"
            )
        for value in self.target_source_manifest_ids:
            require_stable_id(value, "target_source_manifest_id")
        documents = (
            (self.source_review, "review_hash", "source_review"),
            (
                self.mapping_workbench,
                "mapping_workbench_hash",
                "mapping_workbench",
            ),
            (
                self.catalog_workbench,
                "catalog_workbench_hash",
                "catalog_workbench",
            ),
            (self.assessment, "assessment_hash", "assessment"),
        )
        for document, hash_key, label in documents:
            if document.get("authorization_status") != "not_authorization":
                raise AuthoritativeIntakeError(
                    f"{label} must remain not_authorization"
                )
            claimed = document.get(hash_key)
            require_sha256(claimed, f"{label} {hash_key}")
            unsigned = {key: value for key, value in document.items() if key != hash_key}
            if claimed != canonical_sha256(unsigned):
                raise AuthoritativeIntakeError(f"{label} self-hash mismatch")
            if document.get("plan_id") != self.plan_id:
                raise AuthoritativeIntakeError(f"{label} plan binding mismatch")
        if self.source_review.get("plan_hash") != self.plan_hash:
            raise AuthoritativeIntakeError("source review plan hash mismatch")
        if (
            self.source_review.get("policy_registry_id") != self.policy_registry_id
            or self.source_review.get("policy_registry_hash")
            != self.policy_registry_hash
        ):
            raise AuthoritativeIntakeError("source review policy binding mismatch")
        for document, label in (
            (self.mapping_workbench, "mapping_workbench"),
            (self.catalog_workbench, "catalog_workbench"),
            (self.assessment, "assessment"),
        ):
            if (
                document.get("regulation_id") != self.regulation_id
                or document.get("regulation_revision") != self.regulation_revision
                or document.get("target_pool_hash") != self.target_pool_hash
                or document.get("target_source_manifest_hash")
                != self.target_source_manifest_hash
            ):
                raise AuthoritativeIntakeError(f"{label} target binding mismatch")
        if self.mapping_workbench.get("target_source_manifest_ids") != list(
            self.target_source_manifest_ids
        ):
            raise AuthoritativeIntakeError("mapping target source-manifest binding mismatch")
        if self.mapping_workbench.get("source_lock_hash") != self.source_lock_hash:
            raise AuthoritativeIntakeError("mapping source-lock binding mismatch")
        if self.catalog_workbench.get("source_review_hash") != self.source_review.get(
            "review_hash"
        ):
            raise AuthoritativeIntakeError("Catalog source review binding mismatch")
        if self.catalog_workbench.get(
            "mapping_workbench_hash"
        ) != self.mapping_workbench.get("mapping_workbench_hash"):
            raise AuthoritativeIntakeError("Catalog mapping binding mismatch")
        if (
            self.assessment.get("source_review_hash")
            != self.source_review.get("review_hash")
            or self.assessment.get("mapping_workbench_hash")
            != self.mapping_workbench.get("mapping_workbench_hash")
            or self.assessment.get("catalog_workbench_hash")
            != self.catalog_workbench.get("catalog_workbench_hash")
        ):
            raise AuthoritativeIntakeError("assessment component binding mismatch")
        assessment_summary = self.assessment.get("summary")
        if (
            not isinstance(assessment_summary, Mapping)
            or assessment_summary.get("decision") != "NO-GO"
            or assessment_summary.get("candidate_for_production_promotion") is not False
        ):
            raise AuthoritativeIntakeError(
                "authoritative intake workbench must not authorize promotion"
            )

    def validate(self) -> None:
        """Revalidate mutable nested documents immediately before materialization."""

        self.__post_init__()

    def validated_snapshot(self) -> "AuthoritativeIntakeCompilation":
        """Return a private defensive snapshot validated as one compilation."""

        return AuthoritativeIntakeCompilation(
            plan_id=self.plan_id,
            plan_hash=self.plan_hash,
            policy_registry_id=self.policy_registry_id,
            policy_registry_hash=self.policy_registry_hash,
            source_lock_hash=self.source_lock_hash,
            regulation_id=self.regulation_id,
            regulation_revision=self.regulation_revision,
            target_pool_hash=self.target_pool_hash,
            target_source_manifest_ids=tuple(self.target_source_manifest_ids),
            target_source_manifest_hash=self.target_source_manifest_hash,
            source_review=self.source_review,
            mapping_workbench=self.mapping_workbench,
            catalog_workbench=self.catalog_workbench,
            assessment=self.assessment,
        )

    @property
    def document_map(self) -> dict[str, Mapping[str, Any]]:
        return {
            "source-acquisition-review.json": self.source_review,
            "authoritative-mapping-workbench.json": self.mapping_workbench,
            "authoritative-catalog-v2-workbench.json": self.catalog_workbench,
            "authoritative-intake-assessment.json": self.assessment,
        }

    @property
    def document_digests(self) -> dict[str, str]:
        return {
            name: hashlib.sha256((canonical_json(value) + "\n").encode("utf-8")).hexdigest()
            for name, value in sorted(self.document_map.items())
        }

    @property
    def compilation_hash(self) -> str:
        return canonical_sha256(
            {
                "schema_version": AUTHORITATIVE_INTAKE_SCHEMA_VERSION,
                "compiler_version": AUTHORITATIVE_INTAKE_COMPILER_VERSION,
                "plan_id": self.plan_id,
                "plan_hash": self.plan_hash,
                "policy_registry_id": self.policy_registry_id,
                "policy_registry_hash": self.policy_registry_hash,
                "source_lock_hash": self.source_lock_hash,
                "regulation_id": self.regulation_id,
                "regulation_revision": self.regulation_revision,
                "target_pool_hash": self.target_pool_hash,
                "target_source_manifest_ids": list(self.target_source_manifest_ids),
                "target_source_manifest_hash": self.target_source_manifest_hash,
                "authorization_status": "not_authorization",
                "document_digests": self.document_digests,
            }
        )

    def summary_data(self) -> dict[str, Any]:
        return {
            "schema_version": AUTHORITATIVE_INTAKE_SCHEMA_VERSION,
            "compiler_version": AUTHORITATIVE_INTAKE_COMPILER_VERSION,
            "compilation_id": f"authoritative-intake:{self.compilation_hash[:24]}",
            "plan_id": self.plan_id,
            "plan_hash": self.plan_hash,
            "policy_registry_id": self.policy_registry_id,
            "policy_registry_hash": self.policy_registry_hash,
            "source_lock_hash": self.source_lock_hash,
            "regulation_id": self.regulation_id,
            "regulation_revision": self.regulation_revision,
            "target_pool_hash": self.target_pool_hash,
            "target_source_manifest_ids": list(self.target_source_manifest_ids),
            "target_source_manifest_hash": self.target_source_manifest_hash,
            "authorization_status": "not_authorization",
            "production_materialization_emitted": False,
            "document_digests": self.document_digests,
            "source_summary": dict(self.source_review["summary"]),
            "mapping_summary": dict(self.mapping_workbench["summary"]),
            "catalog_summary": dict(self.catalog_workbench["summary"]),
            "assessment_summary": dict(self.assessment["summary"]),
            "compilation_hash": self.compilation_hash,
        }

    def to_json(self) -> str:
        return canonical_json(self.summary_data())
