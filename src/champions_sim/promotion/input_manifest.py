"""Path-independent SIM-02C input manifest for promotion request replay.

The manifest in this module is an integrity-bound recipe for reconstructing a
``ProductionPromotionRequestV2`` against an artifact root supplied by the
caller.  It deliberately does not contain an artifact-root path, credentials,
private keys, Replay objects, scenario objects, validated grounding traces, or
authorization.  Production use still requires those runtime values and a
current external trust context.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
from typing import Any, Mapping

from champions_sim.core import canonical_hash, canonical_json

from .compiler import (
    ProductionPromotionRequestV2,
    PromotionArtifactBindingsV2,
    PromotionArtifactLocatorV2,
    PromotionCompilationError,
    ReplayArtifactBindingV2,
    resolve_promotion_source_set_v2,
)
from .sources import (
    PromotionArtifactRoleV2,
    PromotionRecordReferenceV2,
    PromotionSourceError,
    PromotionSourceScopeV2,
    ResolvedArtifactV2,
    read_resolved_artifact,
)


PRODUCTION_PROMOTION_INPUT_MANIFEST_V3_SCHEMA_VERSION = "3.0.0"
PRODUCTION_PROMOTION_INPUT_MANIFEST_V3_PURPOSE = (
    "production_promotion_request_rehydration"
)
PRODUCTION_PROMOTION_INPUT_MANIFEST_V3_AUTHORIZATION_STATUS = "not_authorization"

_MANIFEST_ID_PREFIX = "production-promotion-input-manifest-"
_RUNTIME_EVIDENCE_STATUS = "references_only_not_embedded"
_RUNTIME_ARGUMENTS = (
    "current_trust_context",
    "development_scenario_corpus",
    "external_holdout_scenario_corpus",
    "replays",
    "validated_traces",
)
_ARTIFACT_BINDING_ROLES = (
    "regulation",
    "target_pool",
    "catalog",
    "ruleset",
    "mapping_evidence",
    "development_construction_corpus",
    "external_holdout_construction_corpus",
    "grounding_assertions",
    "development_scenario_corpus",
    "external_holdout_scenario_corpus",
    "timing_evidence",
)
_STABLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,239}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ProductionPromotionInputManifestError(ValueError):
    """The portable input recipe is malformed, stale, or path-unsafe."""


@dataclass(frozen=True, slots=True)
class SourceManifestInputV3:
    """Exact source-manifest file identity without a host filesystem root."""

    relative_path: str
    source_manifest_id: str
    byte_count: int
    sha256: str
    manifest_hash: str
    resolution_hash: str

    def __post_init__(self) -> None:
        _relative_posix_path(self.relative_path, "source manifest relative_path")
        _stable_id(self.source_manifest_id, "source_manifest_id")
        _nonnegative_int(self.byte_count, "source manifest byte_count")
        _sha256(self.sha256, "source manifest sha256")
        _sha256(self.manifest_hash, "source manifest manifest_hash")
        _sha256(self.resolution_hash, "source manifest resolution_hash")

    def to_data(self) -> dict[str, Any]:
        return {
            "relative_path": self.relative_path,
            "source_manifest_id": self.source_manifest_id,
            "byte_count": self.byte_count,
            "sha256": self.sha256,
            "manifest_hash": self.manifest_hash,
            "resolution_hash": self.resolution_hash,
        }

    @classmethod
    def from_data(cls, value: Any) -> SourceManifestInputV3:
        raw = _object(value, "source manifest input")
        _exact_keys(
            raw,
            {
                "relative_path",
                "source_manifest_id",
                "byte_count",
                "sha256",
                "manifest_hash",
                "resolution_hash",
            },
            "source manifest input",
        )
        return cls(
            relative_path=_string(raw["relative_path"], "relative_path"),
            source_manifest_id=_string(
                raw["source_manifest_id"], "source_manifest_id"
            ),
            byte_count=_integer(raw["byte_count"], "byte_count"),
            sha256=_string(raw["sha256"], "sha256"),
            manifest_hash=_string(raw["manifest_hash"], "manifest_hash"),
            resolution_hash=_string(raw["resolution_hash"], "resolution_hash"),
        )


@dataclass(frozen=True, slots=True)
class ArtifactContentIdentityV3:
    """Resolver-issued identity of one artifact named by a request binding."""

    source_manifest_id: str
    artifact_id: str
    artifact_role: PromotionArtifactRoleV2
    relative_path: str
    media_type: str
    byte_count: int
    sha256: str

    def __post_init__(self) -> None:
        _stable_id(self.source_manifest_id, "artifact source_manifest_id")
        _stable_id(self.artifact_id, "artifact_id")
        if self.artifact_role is not PromotionArtifactRoleV2.SOURCE_DATA:
            raise ProductionPromotionInputManifestError(
                "promotion input bindings must name source_data artifacts"
            )
        _relative_posix_path(self.relative_path, "artifact relative_path")
        if type(self.media_type) is not str or not self.media_type.strip():
            raise ProductionPromotionInputManifestError(
                "artifact media_type must be a non-empty exact string"
            )
        _nonnegative_int(self.byte_count, "artifact byte_count")
        _sha256(self.sha256, "artifact sha256")

    @classmethod
    def from_resolved(cls, artifact: ResolvedArtifactV2) -> ArtifactContentIdentityV3:
        if type(artifact) is not ResolvedArtifactV2:
            raise ProductionPromotionInputManifestError(
                "artifact identity requires an exact resolved V2 artifact"
            )
        artifact.__post_init__()
        return cls(
            source_manifest_id=artifact.source_manifest_id,
            artifact_id=artifact.artifact_id,
            artifact_role=artifact.role,
            relative_path=artifact.relative_path,
            media_type=artifact.media_type,
            byte_count=artifact.byte_count,
            sha256=artifact.sha256,
        )

    @property
    def locator(self) -> PromotionArtifactLocatorV2:
        return PromotionArtifactLocatorV2(
            source_manifest_id=self.source_manifest_id,
            artifact_id=self.artifact_id,
        )

    def to_data(self) -> dict[str, Any]:
        return {
            "source_manifest_id": self.source_manifest_id,
            "artifact_id": self.artifact_id,
            "artifact_role": self.artifact_role.value,
            "relative_path": self.relative_path,
            "media_type": self.media_type,
            "byte_count": self.byte_count,
            "sha256": self.sha256,
        }

    @classmethod
    def from_data(cls, value: Any) -> ArtifactContentIdentityV3:
        raw = _object(value, "artifact content identity")
        _exact_keys(
            raw,
            {
                "source_manifest_id",
                "artifact_id",
                "artifact_role",
                "relative_path",
                "media_type",
                "byte_count",
                "sha256",
            },
            "artifact content identity",
        )
        role_value = _string(raw["artifact_role"], "artifact_role")
        try:
            role = PromotionArtifactRoleV2(role_value)
        except ValueError as error:
            raise ProductionPromotionInputManifestError(
                "unsupported artifact_role"
            ) from error
        return cls(
            source_manifest_id=_string(
                raw["source_manifest_id"], "source_manifest_id"
            ),
            artifact_id=_string(raw["artifact_id"], "artifact_id"),
            artifact_role=role,
            relative_path=_string(raw["relative_path"], "relative_path"),
            media_type=_string(raw["media_type"], "media_type"),
            byte_count=_integer(raw["byte_count"], "byte_count"),
            sha256=_string(raw["sha256"], "sha256"),
        )


@dataclass(frozen=True, slots=True)
class PromotionArtifactInputBindingV3:
    binding_role: str
    artifact: ArtifactContentIdentityV3

    def __post_init__(self) -> None:
        if type(self.binding_role) is not str or self.binding_role not in set(
            _ARTIFACT_BINDING_ROLES
        ):
            raise ProductionPromotionInputManifestError(
                "unsupported promotion artifact binding_role"
            )
        if type(self.artifact) is not ArtifactContentIdentityV3:
            raise ProductionPromotionInputManifestError(
                "promotion binding requires an exact artifact identity"
            )
        self.artifact.__post_init__()

    def to_data(self) -> dict[str, Any]:
        return {
            "binding_role": self.binding_role,
            "artifact": self.artifact.to_data(),
        }

    @classmethod
    def from_data(cls, value: Any) -> PromotionArtifactInputBindingV3:
        raw = _object(value, "promotion artifact binding")
        _exact_keys(raw, {"binding_role", "artifact"}, "promotion artifact binding")
        return cls(
            binding_role=_string(raw["binding_role"], "binding_role"),
            artifact=ArtifactContentIdentityV3.from_data(raw["artifact"]),
        )


@dataclass(frozen=True, slots=True)
class ReplayArtifactInputBindingV3:
    scenario_id: str
    artifact: ArtifactContentIdentityV3

    def __post_init__(self) -> None:
        _stable_id(self.scenario_id, "Replay scenario_id")
        if type(self.artifact) is not ArtifactContentIdentityV3:
            raise ProductionPromotionInputManifestError(
                "Replay binding requires an exact artifact identity"
            )
        self.artifact.__post_init__()

    def to_data(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "artifact": self.artifact.to_data(),
        }

    @classmethod
    def from_data(cls, value: Any) -> ReplayArtifactInputBindingV3:
        raw = _object(value, "Replay artifact binding")
        _exact_keys(raw, {"scenario_id", "artifact"}, "Replay artifact binding")
        return cls(
            scenario_id=_string(raw["scenario_id"], "scenario_id"),
            artifact=ArtifactContentIdentityV3.from_data(raw["artifact"]),
        )


@dataclass(frozen=True, slots=True)
class RuntimeEvidenceReferencesV3:
    """References to objects that remain external to the portable manifest."""

    evidence_status: str
    required_arguments: tuple[str, ...]
    current_trust_context_required: bool
    development_scenario_corpus: PromotionArtifactLocatorV2
    external_holdout_scenario_corpus: PromotionArtifactLocatorV2
    replay_scenario_ids: tuple[str, ...]
    validated_grounding_trace_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.evidence_status != _RUNTIME_EVIDENCE_STATUS:
            raise ProductionPromotionInputManifestError(
                "runtime evidence status must remain references-only"
            )
        if self.required_arguments != _RUNTIME_ARGUMENTS:
            raise ProductionPromotionInputManifestError(
                "runtime evidence required_arguments differ from the V3 contract"
            )
        if self.current_trust_context_required is not True:
            raise ProductionPromotionInputManifestError(
                "current trust context must remain explicitly required"
            )
        for value, label in (
            (self.development_scenario_corpus, "development scenario locator"),
            (
                self.external_holdout_scenario_corpus,
                "external holdout scenario locator",
            ),
        ):
            if type(value) is not PromotionArtifactLocatorV2:
                raise ProductionPromotionInputManifestError(
                    f"{label} must use the exact V2 locator"
                )
            value.__post_init__()
        _sorted_unique_ids(self.replay_scenario_ids, "runtime Replay scenario IDs")
        _sorted_unique_ids(
            self.validated_grounding_trace_ids,
            "runtime validated grounding trace IDs",
        )

    def to_data(self) -> dict[str, Any]:
        return {
            "evidence_status": self.evidence_status,
            "required_arguments": list(self.required_arguments),
            "current_trust_context_required": self.current_trust_context_required,
            "development_scenario_corpus": _locator_data(
                self.development_scenario_corpus
            ),
            "external_holdout_scenario_corpus": _locator_data(
                self.external_holdout_scenario_corpus
            ),
            "replay_scenario_ids": list(self.replay_scenario_ids),
            "validated_grounding_trace_ids": list(
                self.validated_grounding_trace_ids
            ),
        }

    @classmethod
    def from_data(cls, value: Any) -> RuntimeEvidenceReferencesV3:
        raw = _object(value, "runtime evidence references")
        _exact_keys(
            raw,
            {
                "evidence_status",
                "required_arguments",
                "current_trust_context_required",
                "development_scenario_corpus",
                "external_holdout_scenario_corpus",
                "replay_scenario_ids",
                "validated_grounding_trace_ids",
            },
            "runtime evidence references",
        )
        return cls(
            evidence_status=_string(raw["evidence_status"], "evidence_status"),
            required_arguments=_string_list(
                raw["required_arguments"], "required_arguments"
            ),
            current_trust_context_required=_boolean(
                raw["current_trust_context_required"],
                "current_trust_context_required",
            ),
            development_scenario_corpus=_locator_from_data(
                raw["development_scenario_corpus"],
                "development_scenario_corpus",
            ),
            external_holdout_scenario_corpus=_locator_from_data(
                raw["external_holdout_scenario_corpus"],
                "external_holdout_scenario_corpus",
            ),
            replay_scenario_ids=_string_list(
                raw["replay_scenario_ids"], "replay_scenario_ids"
            ),
            validated_grounding_trace_ids=_string_list(
                raw["validated_grounding_trace_ids"],
                "validated_grounding_trace_ids",
            ),
        )


@dataclass(frozen=True, slots=True)
class ProductionPromotionInputManifestV3:
    """Portable, content-addressed recipe for one exact V2 request."""

    schema_version: str
    manifest_id: str
    purpose: str
    authorization_status: str
    source_scope: PromotionSourceScopeV2
    source_resolution_set_hash: str
    source_manifests: tuple[SourceManifestInputV3, ...]
    artifact_bindings: tuple[PromotionArtifactInputBindingV3, ...]
    replay_artifact_bindings: tuple[ReplayArtifactInputBindingV3, ...]
    grounding_evidence_refs: tuple[PromotionRecordReferenceV2, ...]
    runtime_evidence: RuntimeEvidenceReferencesV3
    request_binding_hash: str
    input_content_hash: str

    def __post_init__(self) -> None:
        if self.schema_version != PRODUCTION_PROMOTION_INPUT_MANIFEST_V3_SCHEMA_VERSION:
            raise ProductionPromotionInputManifestError(
                "unsupported production input manifest schema_version"
            )
        if self.purpose != PRODUCTION_PROMOTION_INPUT_MANIFEST_V3_PURPOSE:
            raise ProductionPromotionInputManifestError(
                "production input manifest purpose differs"
            )
        if (
            self.authorization_status
            != PRODUCTION_PROMOTION_INPUT_MANIFEST_V3_AUTHORIZATION_STATUS
        ):
            raise ProductionPromotionInputManifestError(
                "portable input manifest cannot claim authorization"
            )
        if type(self.source_scope) is not PromotionSourceScopeV2:
            raise ProductionPromotionInputManifestError(
                "source_scope must use the exact V2 enum"
            )
        _sha256(self.source_resolution_set_hash, "source_resolution_set_hash")

        if type(self.source_manifests) is not tuple or not self.source_manifests:
            raise ProductionPromotionInputManifestError(
                "portable input manifest requires source manifests"
            )
        if any(type(value) is not SourceManifestInputV3 for value in self.source_manifests):
            raise ProductionPromotionInputManifestError(
                "source manifests require exact V3 entries"
            )
        for value in self.source_manifests:
            value.__post_init__()
        source_ids = tuple(value.source_manifest_id for value in self.source_manifests)
        if source_ids != tuple(sorted(source_ids)) or len(source_ids) != len(set(source_ids)):
            raise ProductionPromotionInputManifestError(
                "source manifest IDs must be unique and sorted"
            )
        source_paths = tuple(value.relative_path for value in self.source_manifests)
        if len(source_paths) != len({value.casefold() for value in source_paths}):
            raise ProductionPromotionInputManifestError(
                "source manifest paths must be case-insensitively unique"
            )

        if type(self.artifact_bindings) is not tuple:
            raise ProductionPromotionInputManifestError(
                "artifact bindings must be an exact tuple"
            )
        if any(
            type(value) is not PromotionArtifactInputBindingV3
            for value in self.artifact_bindings
        ):
            raise ProductionPromotionInputManifestError(
                "artifact bindings require exact V3 entries"
            )
        for value in self.artifact_bindings:
            value.__post_init__()
        roles = tuple(value.binding_role for value in self.artifact_bindings)
        if roles != _ARTIFACT_BINDING_ROLES:
            raise ProductionPromotionInputManifestError(
                "artifact binding roles must be complete, unique, and ordered"
            )

        if type(self.replay_artifact_bindings) is not tuple or not self.replay_artifact_bindings:
            raise ProductionPromotionInputManifestError(
                "portable input manifest requires Replay artifact bindings"
            )
        if any(
            type(value) is not ReplayArtifactInputBindingV3
            for value in self.replay_artifact_bindings
        ):
            raise ProductionPromotionInputManifestError(
                "Replay bindings require exact V3 entries"
            )
        for value in self.replay_artifact_bindings:
            value.__post_init__()
        replay_ids = tuple(value.scenario_id for value in self.replay_artifact_bindings)
        if replay_ids != tuple(sorted(replay_ids)) or len(replay_ids) != len(set(replay_ids)):
            raise ProductionPromotionInputManifestError(
                "Replay scenario IDs must be unique and sorted"
            )

        if type(self.grounding_evidence_refs) is not tuple:
            raise ProductionPromotionInputManifestError(
                "grounding evidence references must be an exact tuple"
            )
        if any(
            type(value) is not PromotionRecordReferenceV2
            for value in self.grounding_evidence_refs
        ):
            raise ProductionPromotionInputManifestError(
                "grounding evidence references require exact V2 entries"
            )
        for value in self.grounding_evidence_refs:
            try:
                value.__post_init__()
            except ValueError as error:
                raise ProductionPromotionInputManifestError(
                    "invalid grounding evidence reference"
                ) from error
        evidence_ids = tuple(
            value.evidence_ref_id for value in self.grounding_evidence_refs
        )
        if evidence_ids != tuple(sorted(evidence_ids)) or len(evidence_ids) != len(
            set(evidence_ids)
        ):
            raise ProductionPromotionInputManifestError(
                "grounding evidence reference IDs must be unique and sorted"
            )

        if type(self.runtime_evidence) is not RuntimeEvidenceReferencesV3:
            raise ProductionPromotionInputManifestError(
                "runtime evidence requires the exact V3 references contract"
            )
        self.runtime_evidence.__post_init__()
        if self.runtime_evidence.replay_scenario_ids != replay_ids:
            raise ProductionPromotionInputManifestError(
                "runtime Replay references differ from Replay artifact bindings"
            )
        by_role = {value.binding_role: value.artifact.locator for value in self.artifact_bindings}
        if (
            self.runtime_evidence.development_scenario_corpus
            != by_role["development_scenario_corpus"]
            or self.runtime_evidence.external_holdout_scenario_corpus
            != by_role["external_holdout_scenario_corpus"]
        ):
            raise ProductionPromotionInputManifestError(
                "runtime scenario references differ from artifact bindings"
            )

        _validate_artifact_identity_aliases(
            self.source_manifests,
            self.artifact_bindings,
            self.replay_artifact_bindings,
        )
        _sha256(self.request_binding_hash, "request_binding_hash")
        _sha256(self.input_content_hash, "input_content_hash")
        expected_content_hash = canonical_hash(self._input_content_data())
        if self.input_content_hash != expected_content_hash:
            raise ProductionPromotionInputManifestError(
                "input_content_hash differs from portable input substance"
            )
        expected_id = _MANIFEST_ID_PREFIX + canonical_hash(self._unsigned_data())
        if self.manifest_id != expected_id:
            raise ProductionPromotionInputManifestError(
                "manifest_id is not content-derived"
            )

    def _input_content_data(self) -> dict[str, Any]:
        return _input_content_data(
            source_scope=self.source_scope,
            source_resolution_set_hash=self.source_resolution_set_hash,
            source_manifests=self.source_manifests,
            artifact_bindings=self.artifact_bindings,
            replay_artifact_bindings=self.replay_artifact_bindings,
            grounding_evidence_refs=self.grounding_evidence_refs,
            runtime_evidence=self.runtime_evidence,
        )

    def _unsigned_data(self) -> dict[str, Any]:
        return _unsigned_manifest_data(
            schema_version=self.schema_version,
            purpose=self.purpose,
            authorization_status=self.authorization_status,
            input_content_data=self._input_content_data(),
            request_binding_hash=self.request_binding_hash,
            input_content_hash=self.input_content_hash,
        )

    @property
    def manifest_hash(self) -> str:
        return canonical_hash(self.to_data())

    def to_data(self) -> dict[str, Any]:
        return {**self._unsigned_data(), "manifest_id": self.manifest_id}

    def to_json(self) -> str:
        return canonical_json(self.to_data())

    @classmethod
    def from_data(cls, value: Any) -> ProductionPromotionInputManifestV3:
        raw = _object(value, "production promotion input manifest V3")
        _exact_keys(
            raw,
            {
                "schema_version",
                "manifest_id",
                "purpose",
                "authorization_status",
                "source_scope",
                "source_resolution_set_hash",
                "source_manifests",
                "artifact_bindings",
                "replay_artifact_bindings",
                "grounding_evidence_refs",
                "runtime_evidence",
                "request_binding_hash",
                "input_content_hash",
            },
            "production promotion input manifest V3",
        )
        scope_value = _string(raw["source_scope"], "source_scope")
        try:
            scope = PromotionSourceScopeV2(scope_value)
        except ValueError as error:
            raise ProductionPromotionInputManifestError(
                "unsupported source_scope"
            ) from error
        source_manifests = tuple(
            SourceManifestInputV3.from_data(item)
            for item in _list(raw["source_manifests"], "source_manifests")
        )
        artifact_bindings = tuple(
            PromotionArtifactInputBindingV3.from_data(item)
            for item in _list(raw["artifact_bindings"], "artifact_bindings")
        )
        replay_bindings = tuple(
            ReplayArtifactInputBindingV3.from_data(item)
            for item in _list(
                raw["replay_artifact_bindings"], "replay_artifact_bindings"
            )
        )
        grounding_refs = tuple(
            _record_reference_from_data(item)
            for item in _list(
                raw["grounding_evidence_refs"], "grounding_evidence_refs"
            )
        )
        return cls(
            schema_version=_string(raw["schema_version"], "schema_version"),
            manifest_id=_string(raw["manifest_id"], "manifest_id"),
            purpose=_string(raw["purpose"], "purpose"),
            authorization_status=_string(
                raw["authorization_status"], "authorization_status"
            ),
            source_scope=scope,
            source_resolution_set_hash=_string(
                raw["source_resolution_set_hash"], "source_resolution_set_hash"
            ),
            source_manifests=source_manifests,
            artifact_bindings=artifact_bindings,
            replay_artifact_bindings=replay_bindings,
            grounding_evidence_refs=grounding_refs,
            runtime_evidence=RuntimeEvidenceReferencesV3.from_data(
                raw["runtime_evidence"]
            ),
            request_binding_hash=_string(
                raw["request_binding_hash"], "request_binding_hash"
            ),
            input_content_hash=_string(
                raw["input_content_hash"], "input_content_hash"
            ),
        )

    @classmethod
    def from_json(
        cls, payload: str | bytes
    ) -> ProductionPromotionInputManifestV3:
        text, raw = _parse_json(payload, "production promotion input manifest V3")
        result = cls.from_data(raw)
        if result.to_json() != text:
            raise ProductionPromotionInputManifestError(
                "production input manifest JSON must use exact canonical encoding"
            )
        return result

    def rehydrate(self, *, artifact_root: Path) -> ProductionPromotionRequestV2:
        return rehydrate_production_promotion_request_v2(
            self,
            artifact_root=artifact_root,
        )


def production_promotion_request_binding_hash_v3(
    request: ProductionPromotionRequestV2,
) -> str:
    """Hash the path-independent locator/reference projection of a V2 request."""

    if type(request) is not ProductionPromotionRequestV2:
        raise ProductionPromotionInputManifestError(
            "request binding hash requires an exact V2 request"
        )
    try:
        request.__post_init__()
    except ValueError as error:
        raise ProductionPromotionInputManifestError(
            "invalid V2 request for portable binding"
        ) from error
    return canonical_hash(_request_binding_data(request))


def build_production_promotion_input_manifest_v3(
    request: ProductionPromotionRequestV2,
) -> ProductionPromotionInputManifestV3:
    """Resolve exact input bytes and produce a root-free portable recipe."""

    if type(request) is not ProductionPromotionRequestV2:
        raise ProductionPromotionInputManifestError(
            "portable input builder requires an exact V2 request"
        )
    try:
        request.__post_init__()
        source_set = resolve_promotion_source_set_v2(request)
    except (PromotionCompilationError, PromotionSourceError, OSError) as error:
        raise ProductionPromotionInputManifestError(
            "cannot resolve V2 request inputs for portable manifest"
        ) from error

    root = request.artifact_root.resolve(strict=True)
    source_inputs: list[SourceManifestInputV3] = []
    seen_manifest_ids: set[str] = set()
    for relative_path in request.manifest_relative_paths:
        path = _contained_file(root, relative_path, "source manifest")
        try:
            payload = path.read_bytes()
        except OSError as error:
            raise ProductionPromotionInputManifestError(
                "source manifest cannot be read"
            ) from error
        _, raw = _parse_json(payload, f"source manifest {relative_path}")
        raw_object = _object(raw, f"source manifest {relative_path}")
        manifest_id = _string(
            raw_object.get("manifest_id"),
            f"source manifest {relative_path} manifest_id",
        )
        if manifest_id in seen_manifest_ids:
            raise ProductionPromotionInputManifestError(
                "source manifest IDs must be unique"
            )
        seen_manifest_ids.add(manifest_id)
        try:
            resolved = source_set.manifest(manifest_id)
        except PromotionCompilationError as error:
            raise ProductionPromotionInputManifestError(
                "source manifest file identity differs from resolved source set"
            ) from error
        if resolved.manifest_hash != canonical_hash(raw_object):
            raise ProductionPromotionInputManifestError(
                "source manifest changed during portable snapshot"
            )
        source_inputs.append(
            SourceManifestInputV3(
                relative_path=relative_path,
                source_manifest_id=manifest_id,
                byte_count=len(payload),
                sha256=hashlib.sha256(payload).hexdigest(),
                manifest_hash=resolved.manifest_hash,
                resolution_hash=resolved.resolution_hash,
            )
        )
    source_manifests = tuple(
        sorted(source_inputs, key=lambda value: value.source_manifest_id)
    )

    artifact_bindings: list[PromotionArtifactInputBindingV3] = []
    for binding_role in _ARTIFACT_BINDING_ROLES:
        locator = getattr(request.artifacts, binding_role)
        try:
            artifact = source_set.artifact(locator)
            read_resolved_artifact(root, artifact)
        except (PromotionCompilationError, PromotionSourceError) as error:
            raise ProductionPromotionInputManifestError(
                f"cannot resolve bound artifact: {binding_role}"
            ) from error
        artifact_bindings.append(
            PromotionArtifactInputBindingV3(
                binding_role=binding_role,
                artifact=ArtifactContentIdentityV3.from_resolved(artifact),
            )
        )

    replay_bindings: list[ReplayArtifactInputBindingV3] = []
    for binding in request.replay_artifacts:
        try:
            artifact = source_set.artifact(binding.artifact)
            read_resolved_artifact(root, artifact)
        except (PromotionCompilationError, PromotionSourceError) as error:
            raise ProductionPromotionInputManifestError(
                f"cannot resolve Replay artifact: {binding.scenario_id}"
            ) from error
        replay_bindings.append(
            ReplayArtifactInputBindingV3(
                scenario_id=binding.scenario_id,
                artifact=ArtifactContentIdentityV3.from_resolved(artifact),
            )
        )

    artifact_bindings_tuple = tuple(artifact_bindings)
    replay_bindings_tuple = tuple(replay_bindings)
    _validate_resolved_file_aliases(
        root,
        source_manifests,
        artifact_bindings_tuple,
        replay_bindings_tuple,
    )
    grounding_locator = request.artifacts.grounding_assertions
    try:
        grounding_payload = read_resolved_artifact(
            root, source_set.artifact(grounding_locator)
        )
    except (PromotionCompilationError, PromotionSourceError) as error:
        raise ProductionPromotionInputManifestError(
            "cannot read grounding assertion artifact"
        ) from error
    trace_ids = _grounding_trace_ids(grounding_payload)
    runtime_evidence = RuntimeEvidenceReferencesV3(
        evidence_status=_RUNTIME_EVIDENCE_STATUS,
        required_arguments=_RUNTIME_ARGUMENTS,
        current_trust_context_required=True,
        development_scenario_corpus=request.artifacts.development_scenario_corpus,
        external_holdout_scenario_corpus=(
            request.artifacts.external_holdout_scenario_corpus
        ),
        replay_scenario_ids=tuple(
            value.scenario_id for value in replay_bindings_tuple
        ),
        validated_grounding_trace_ids=trace_ids,
    )
    request_binding_hash = production_promotion_request_binding_hash_v3(request)
    input_content_data = _input_content_data(
        source_scope=source_set.scope,
        source_resolution_set_hash=source_set.resolution_set_hash,
        source_manifests=source_manifests,
        artifact_bindings=artifact_bindings_tuple,
        replay_artifact_bindings=replay_bindings_tuple,
        grounding_evidence_refs=request.grounding_evidence_refs,
        runtime_evidence=runtime_evidence,
    )
    input_content_hash = canonical_hash(input_content_data)
    unsigned = _unsigned_manifest_data(
        schema_version=PRODUCTION_PROMOTION_INPUT_MANIFEST_V3_SCHEMA_VERSION,
        purpose=PRODUCTION_PROMOTION_INPUT_MANIFEST_V3_PURPOSE,
        authorization_status=(
            PRODUCTION_PROMOTION_INPUT_MANIFEST_V3_AUTHORIZATION_STATUS
        ),
        input_content_data=input_content_data,
        request_binding_hash=request_binding_hash,
        input_content_hash=input_content_hash,
    )
    return ProductionPromotionInputManifestV3(
        schema_version=PRODUCTION_PROMOTION_INPUT_MANIFEST_V3_SCHEMA_VERSION,
        manifest_id=_MANIFEST_ID_PREFIX + canonical_hash(unsigned),
        purpose=PRODUCTION_PROMOTION_INPUT_MANIFEST_V3_PURPOSE,
        authorization_status=(
            PRODUCTION_PROMOTION_INPUT_MANIFEST_V3_AUTHORIZATION_STATUS
        ),
        source_scope=source_set.scope,
        source_resolution_set_hash=source_set.resolution_set_hash,
        source_manifests=source_manifests,
        artifact_bindings=artifact_bindings_tuple,
        replay_artifact_bindings=replay_bindings_tuple,
        grounding_evidence_refs=request.grounding_evidence_refs,
        runtime_evidence=runtime_evidence,
        request_binding_hash=request_binding_hash,
        input_content_hash=input_content_hash,
    )


def rehydrate_production_promotion_request_v2(
    manifest: ProductionPromotionInputManifestV3,
    *,
    artifact_root: Path,
) -> ProductionPromotionRequestV2:
    """Rebuild and fully re-resolve one V2 request against an external root."""

    if type(manifest) is not ProductionPromotionInputManifestV3:
        raise ProductionPromotionInputManifestError(
            "rehydration requires an exact V3 input manifest"
        )
    manifest.__post_init__()
    if not isinstance(artifact_root, Path):
        raise ProductionPromotionInputManifestError(
            "artifact_root must be supplied externally as a Path"
        )
    try:
        root = artifact_root.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise ProductionPromotionInputManifestError(
            "external artifact_root does not resolve"
        ) from error
    if not root.is_dir():
        raise ProductionPromotionInputManifestError(
            "external artifact_root must be a directory"
        )

    for source_input in manifest.source_manifests:
        path = _contained_file(root, source_input.relative_path, "source manifest")
        try:
            payload = path.read_bytes()
        except OSError as error:
            raise ProductionPromotionInputManifestError(
                "source manifest cannot be read during rehydration"
            ) from error
        if len(payload) != source_input.byte_count:
            raise ProductionPromotionInputManifestError(
                "source manifest byte_count differs during rehydration"
            )
        if hashlib.sha256(payload).hexdigest() != source_input.sha256:
            raise ProductionPromotionInputManifestError(
                "source manifest sha256 differs during rehydration"
            )
        _, raw = _parse_json(payload, f"source manifest {source_input.relative_path}")
        raw_object = _object(raw, "source manifest")
        if raw_object.get("manifest_id") != source_input.source_manifest_id:
            raise ProductionPromotionInputManifestError(
                "source manifest ID differs during rehydration"
            )
        if canonical_hash(raw_object) != source_input.manifest_hash:
            raise ProductionPromotionInputManifestError(
                "source manifest canonical identity differs during rehydration"
            )
    _validate_resolved_file_aliases(
        root,
        manifest.source_manifests,
        manifest.artifact_bindings,
        manifest.replay_artifact_bindings,
    )

    by_role = {value.binding_role: value.artifact.locator for value in manifest.artifact_bindings}
    try:
        artifact_bindings = PromotionArtifactBindingsV2(
            **{role: by_role[role] for role in _ARTIFACT_BINDING_ROLES}
        )
        replay_bindings = tuple(
            ReplayArtifactBindingV2(
                scenario_id=value.scenario_id,
                artifact=value.artifact.locator,
            )
            for value in manifest.replay_artifact_bindings
        )
        request = ProductionPromotionRequestV2(
            artifact_root=root,
            manifest_relative_paths=tuple(
                sorted(value.relative_path for value in manifest.source_manifests)
            ),
            artifacts=artifact_bindings,
            replay_artifacts=replay_bindings,
            grounding_evidence_refs=manifest.grounding_evidence_refs,
        )
    except (PromotionCompilationError, PromotionSourceError) as error:
        raise ProductionPromotionInputManifestError(
            "portable bindings cannot reconstruct an exact V2 request"
        ) from error
    if production_promotion_request_binding_hash_v3(request) != manifest.request_binding_hash:
        raise ProductionPromotionInputManifestError(
            "rehydrated request binding hash differs"
        )

    try:
        source_set = resolve_promotion_source_set_v2(request)
    except (PromotionCompilationError, PromotionSourceError, OSError) as error:
        raise ProductionPromotionInputManifestError(
            "rehydrated request inputs do not resolve"
        ) from error
    if source_set.scope is not manifest.source_scope:
        raise ProductionPromotionInputManifestError(
            "rehydrated source scope differs"
        )
    if source_set.resolution_set_hash != manifest.source_resolution_set_hash:
        raise ProductionPromotionInputManifestError(
            "rehydrated source resolution set differs"
        )
    for source_input in manifest.source_manifests:
        try:
            actual = source_set.manifest(source_input.source_manifest_id)
        except PromotionCompilationError as error:
            raise ProductionPromotionInputManifestError(
                "rehydrated source manifest is missing"
            ) from error
        if (
            actual.manifest_hash != source_input.manifest_hash
            or actual.resolution_hash != source_input.resolution_hash
        ):
            raise ProductionPromotionInputManifestError(
                "rehydrated source manifest resolution differs"
            )

    for binding in manifest.artifact_bindings:
        _verify_resolved_artifact_identity(root, source_set, binding.artifact)
    for binding in manifest.replay_artifact_bindings:
        _verify_resolved_artifact_identity(root, source_set, binding.artifact)

    grounding_artifact = source_set.artifact(request.artifacts.grounding_assertions)
    grounding_payload = read_resolved_artifact(root, grounding_artifact)
    if _grounding_trace_ids(grounding_payload) != (
        manifest.runtime_evidence.validated_grounding_trace_ids
    ):
        raise ProductionPromotionInputManifestError(
            "runtime grounding trace references differ from bound artifact"
        )
    return request


def load_production_promotion_input_manifest_v3(
    path: Path | str,
) -> ProductionPromotionInputManifestV3:
    """Load an exact canonical V3 manifest from a regular UTF-8 JSON file."""

    candidate = Path(path)
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise ProductionPromotionInputManifestError(
            "production input manifest path does not resolve"
        ) from error
    if not resolved.is_file():
        raise ProductionPromotionInputManifestError(
            "production input manifest path is not a regular file"
        )
    try:
        payload = resolved.read_bytes()
    except OSError as error:
        raise ProductionPromotionInputManifestError(
            "production input manifest cannot be read"
        ) from error
    return ProductionPromotionInputManifestV3.from_json(payload)


def _verify_resolved_artifact_identity(root, source_set, expected) -> None:
    try:
        artifact = source_set.artifact(expected.locator)
        read_resolved_artifact(root, artifact)
    except (PromotionCompilationError, PromotionSourceError) as error:
        raise ProductionPromotionInputManifestError(
            "bound artifact cannot be resolved during rehydration"
        ) from error
    if ArtifactContentIdentityV3.from_resolved(artifact) != expected:
        raise ProductionPromotionInputManifestError(
            "bound artifact content identity differs during rehydration"
        )


def _request_binding_data(request: ProductionPromotionRequestV2) -> dict[str, Any]:
    return {
        "manifest_relative_paths": list(request.manifest_relative_paths),
        "artifact_bindings": [
            {
                "binding_role": role,
                "source_manifest_id": getattr(request.artifacts, role).source_manifest_id,
                "artifact_id": getattr(request.artifacts, role).artifact_id,
            }
            for role in _ARTIFACT_BINDING_ROLES
        ],
        "replay_artifact_bindings": [
            {
                "scenario_id": value.scenario_id,
                "source_manifest_id": value.artifact.source_manifest_id,
                "artifact_id": value.artifact.artifact_id,
            }
            for value in request.replay_artifacts
        ],
        "grounding_evidence_refs": [
            _record_reference_data(value) for value in request.grounding_evidence_refs
        ],
    }


def _input_content_data(
    *,
    source_scope,
    source_resolution_set_hash,
    source_manifests,
    artifact_bindings,
    replay_artifact_bindings,
    grounding_evidence_refs,
    runtime_evidence,
) -> dict[str, Any]:
    return {
        "source_scope": source_scope.value,
        "source_resolution_set_hash": source_resolution_set_hash,
        "source_manifests": [value.to_data() for value in source_manifests],
        "artifact_bindings": [value.to_data() for value in artifact_bindings],
        "replay_artifact_bindings": [
            value.to_data() for value in replay_artifact_bindings
        ],
        "grounding_evidence_refs": [
            _record_reference_data(value) for value in grounding_evidence_refs
        ],
        "runtime_evidence": runtime_evidence.to_data(),
    }


def _unsigned_manifest_data(
    *,
    schema_version,
    purpose,
    authorization_status,
    input_content_data,
    request_binding_hash,
    input_content_hash,
) -> dict[str, Any]:
    return {
        "schema_version": schema_version,
        "purpose": purpose,
        "authorization_status": authorization_status,
        **input_content_data,
        "request_binding_hash": request_binding_hash,
        "input_content_hash": input_content_hash,
    }


def _validate_artifact_identity_aliases(
    source_manifests,
    artifact_bindings,
    replay_bindings,
) -> None:
    manifest_paths = {value.relative_path for value in source_manifests}
    by_identity: dict[tuple[str, str], ArtifactContentIdentityV3] = {}
    by_path: dict[str, tuple[str, str]] = {}
    for binding in (*artifact_bindings, *replay_bindings):
        artifact = binding.artifact
        identity = (artifact.source_manifest_id, artifact.artifact_id)
        previous = by_identity.get(identity)
        if previous is not None and previous != artifact:
            raise ProductionPromotionInputManifestError(
                "one artifact ID has conflicting content identities"
            )
        by_identity[identity] = artifact
        folded_path = artifact.relative_path.casefold()
        previous_identity = by_path.get(folded_path)
        if previous_identity is not None and previous_identity != identity:
            raise ProductionPromotionInputManifestError(
                "distinct artifact IDs cannot alias one case-insensitive relative path"
            )
        by_path[folded_path] = identity
        if folded_path in {value.casefold() for value in manifest_paths}:
            raise ProductionPromotionInputManifestError(
                "source manifest and artifact paths must not alias"
            )


def _validate_resolved_file_aliases(
    root: Path,
    source_manifests,
    artifact_bindings,
    replay_bindings,
) -> None:
    """Reject different logical inputs resolving to one host filesystem file."""

    resolved_claims: dict[Path, tuple[str, ...]] = {}
    for value in source_manifests:
        resolved = _contained_file(root, value.relative_path, "source manifest")
        claim = ("source_manifest", value.source_manifest_id)
        previous = resolved_claims.get(resolved)
        if previous is not None and previous != claim:
            raise ProductionPromotionInputManifestError(
                "distinct source inputs resolve to one filesystem path"
            )
        resolved_claims[resolved] = claim
    for binding in (*artifact_bindings, *replay_bindings):
        artifact = binding.artifact
        resolved = _contained_file(root, artifact.relative_path, "bound artifact")
        claim = (
            "artifact",
            artifact.source_manifest_id,
            artifact.artifact_id,
        )
        previous = resolved_claims.get(resolved)
        if previous is not None and previous != claim:
            raise ProductionPromotionInputManifestError(
                "distinct source inputs resolve to one filesystem path"
            )
        resolved_claims[resolved] = claim


def _grounding_trace_ids(payload: bytes) -> tuple[str, ...]:
    _, raw = _parse_json(payload, "grounding assertion artifact")
    document = _object(raw, "grounding assertion artifact")
    assertions = _list(document.get("assertions"), "grounding assertions")
    values: set[str] = set()
    for index, value in enumerate(assertions):
        assertion = _object(value, f"grounding assertions[{index}]")
        if "trace_id" not in assertion:
            raise ProductionPromotionInputManifestError(
                "grounding assertion lacks trace_id"
            )
        trace_id = assertion["trace_id"]
        if trace_id is None:
            continue
        trace_id = _string(trace_id, f"grounding assertions[{index}].trace_id")
        _stable_id(trace_id, f"grounding assertions[{index}].trace_id")
        values.add(trace_id)
    return tuple(sorted(values))


def _record_reference_data(value: PromotionRecordReferenceV2) -> dict[str, Any]:
    return {
        "evidence_ref_id": value.evidence_ref_id,
        "source_manifest_id": value.source_manifest_id,
        "artifact_id": value.artifact_id,
        "json_pointer": value.json_pointer,
        "record_sha256": value.record_sha256,
    }


def _record_reference_from_data(value: Any) -> PromotionRecordReferenceV2:
    raw = _object(value, "grounding evidence reference")
    _exact_keys(
        raw,
        {
            "evidence_ref_id",
            "source_manifest_id",
            "artifact_id",
            "json_pointer",
            "record_sha256",
        },
        "grounding evidence reference",
    )
    try:
        return PromotionRecordReferenceV2(
            evidence_ref_id=_string(raw["evidence_ref_id"], "evidence_ref_id"),
            source_manifest_id=_string(
                raw["source_manifest_id"], "source_manifest_id"
            ),
            artifact_id=_string(raw["artifact_id"], "artifact_id"),
            json_pointer=_string(raw["json_pointer"], "json_pointer"),
            record_sha256=_string(raw["record_sha256"], "record_sha256"),
        )
    except PromotionSourceError as error:
        raise ProductionPromotionInputManifestError(
            "invalid grounding evidence reference"
        ) from error


def _locator_data(value: PromotionArtifactLocatorV2) -> dict[str, str]:
    return {
        "source_manifest_id": value.source_manifest_id,
        "artifact_id": value.artifact_id,
    }


def _locator_from_data(value: Any, label: str) -> PromotionArtifactLocatorV2:
    raw = _object(value, label)
    _exact_keys(raw, {"source_manifest_id", "artifact_id"}, label)
    try:
        return PromotionArtifactLocatorV2(
            source_manifest_id=_string(
                raw["source_manifest_id"], f"{label}.source_manifest_id"
            ),
            artifact_id=_string(raw["artifact_id"], f"{label}.artifact_id"),
        )
    except PromotionCompilationError as error:
        raise ProductionPromotionInputManifestError(
            f"invalid {label} locator"
        ) from error


def _contained_file(root: Path, relative: str, label: str) -> Path:
    _relative_posix_path(relative, f"{label} relative path")
    try:
        candidate = root.joinpath(*PurePosixPath(relative).parts).resolve(strict=True)
        candidate.relative_to(root)
    except (OSError, RuntimeError, ValueError) as error:
        raise ProductionPromotionInputManifestError(
            f"{label} escapes or is missing from artifact_root"
        ) from error
    if not candidate.is_file():
        raise ProductionPromotionInputManifestError(
            f"{label} must resolve to a regular file"
        )
    return candidate


def _relative_posix_path(value: Any, label: str) -> None:
    if type(value) is not str:
        raise ProductionPromotionInputManifestError(f"{label} must be a string")
    path = PurePosixPath(value)
    if (
        not value
        or value.startswith("/")
        or value.startswith("//")
        or "\\" in value
        or ":" in value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
        or any(part in {"", ".", ".."} for part in path.parts)
        or any(part != part.strip() or part.endswith(".") for part in path.parts)
        or path.as_posix() != value
    ):
        raise ProductionPromotionInputManifestError(
            f"{label} must be a normalized relative POSIX path"
        )


def _stable_id(value: Any, label: str) -> None:
    if type(value) is not str or _STABLE_ID.fullmatch(value) is None:
        raise ProductionPromotionInputManifestError(f"invalid {label}")


def _sha256(value: Any, label: str) -> None:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ProductionPromotionInputManifestError(
            f"{label} must be a lowercase SHA-256"
        )


def _nonnegative_int(value: Any, label: str) -> None:
    if type(value) is not int or value < 0:
        raise ProductionPromotionInputManifestError(
            f"{label} must be a non-negative exact integer"
        )


def _sorted_unique_ids(values: Any, label: str) -> None:
    if type(values) is not tuple:
        raise ProductionPromotionInputManifestError(f"{label} must be an exact tuple")
    for value in values:
        _stable_id(value, label)
    if values != tuple(sorted(values)) or len(values) != len(set(values)):
        raise ProductionPromotionInputManifestError(
            f"{label} must be unique and sorted"
        )


def _parse_json(payload: str | bytes, label: str) -> tuple[str, Any]:
    if type(payload) is bytes:
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ProductionPromotionInputManifestError(
                f"{label} must be UTF-8 JSON"
            ) from error
    elif type(payload) is str:
        text = payload
    else:
        raise ProductionPromotionInputManifestError(
            f"{label} payload must be exact text or bytes"
        )
    try:
        raw = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_float=_finite_float,
            parse_constant=_reject_nonfinite,
        )
    except ProductionPromotionInputManifestError:
        raise
    except ValueError as error:
        raise ProductionPromotionInputManifestError(
            f"invalid JSON for {label}"
        ) from error
    return text, raw


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProductionPromotionInputManifestError(
                f"duplicate JSON key: {key}"
            )
        result[key] = value
    return result


def _finite_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ProductionPromotionInputManifestError(
            "non-finite JSON numbers are prohibited"
        )
    return result


def _reject_nonfinite(value: str) -> None:
    raise ProductionPromotionInputManifestError(
        f"non-finite JSON numbers are prohibited: {value}"
    )


def _object(value: Any, label: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise ProductionPromotionInputManifestError(f"{label} must be an object")
    if any(type(key) is not str for key in value):
        raise ProductionPromotionInputManifestError(
            f"{label} keys must be exact strings"
        )
    return value


def _list(value: Any, label: str) -> list[Any]:
    if type(value) is not list:
        raise ProductionPromotionInputManifestError(f"{label} must be an array")
    return value


def _string_list(value: Any, label: str) -> tuple[str, ...]:
    values = _list(value, label)
    return tuple(_string(item, f"{label}[]") for item in values)


def _string(value: Any, label: str) -> str:
    if type(value) is not str:
        raise ProductionPromotionInputManifestError(
            f"{label} must be an exact string"
        )
    return value


def _integer(value: Any, label: str) -> int:
    if type(value) is not int:
        raise ProductionPromotionInputManifestError(
            f"{label} must be an exact integer"
        )
    return value


def _boolean(value: Any, label: str) -> bool:
    if type(value) is not bool:
        raise ProductionPromotionInputManifestError(
            f"{label} must be an exact boolean"
        )
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        raise ProductionPromotionInputManifestError(
            f"{label} fields differ; missing={sorted(expected - actual)}, "
            f"unexpected={sorted(actual - expected)}"
        )


__all__ = [
    "ArtifactContentIdentityV3",
    "PRODUCTION_PROMOTION_INPUT_MANIFEST_V3_AUTHORIZATION_STATUS",
    "PRODUCTION_PROMOTION_INPUT_MANIFEST_V3_PURPOSE",
    "PRODUCTION_PROMOTION_INPUT_MANIFEST_V3_SCHEMA_VERSION",
    "ProductionPromotionInputManifestError",
    "ProductionPromotionInputManifestV3",
    "PromotionArtifactInputBindingV3",
    "ReplayArtifactInputBindingV3",
    "RuntimeEvidenceReferencesV3",
    "SourceManifestInputV3",
    "build_production_promotion_input_manifest_v3",
    "load_production_promotion_input_manifest_v3",
    "production_promotion_request_binding_hash_v3",
    "rehydrate_production_promotion_request_v2",
]
