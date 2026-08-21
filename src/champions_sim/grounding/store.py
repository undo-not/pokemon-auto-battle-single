"""Gitignored, content-addressed local store for raw capture artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from champions_sim.core import canonical_json

from .adb import AdbServerIdentity
from .android_client import AndroidClientBuild
from .bluestacks import CapturePayload
from .models import (
    AnnotationSource,
    ArtifactKind,
    BoundingBox,
    CaptureAnnotation,
    CaptureArtifact,
    CaptureManifest,
    ConformanceCheck,
    ConformanceVerdict,
    GroundedField,
    GroundingFrame,
    GroundingSource,
    GroundingStatus,
    GroundingTrace,
    GroundingTraceStatus,
    RedactionRegion,
    RedactionStatus,
)


_CAPTURE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_STORE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_MAX_MANIFEST_BYTES = 2 * 1024 * 1024
_MAX_ARTIFACT_BYTES = {
    "screenshot": 32 * 1024 * 1024,
    "ui-hierarchy-before": 8 * 1024 * 1024,
    "ui-hierarchy": 8 * 1024 * 1024,
}
_MAX_TRACE_BYTES = 8 * 1024 * 1024
_TRACE_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_STORE_PARTITIONS = {"development", "holdout"}
_STORE_MANIFEST_NAME = "store.json"
_STORE_MANIFEST_KEYS = {
    "schema_version",
    "store_id",
    "partition",
    "store_nonce",
    "local_research_only",
    "distribution_allowed",
}
_MANIFEST_KEYS = {
    "schema_version",
    "capture_id",
    "captured_at",
    "ui_hierarchy_before_captured_at",
    "screenshot_captured_at",
    "ui_hierarchy_captured_at",
    "ui_state_sha256",
    "instance_name",
    "adb_serial",
    "format_id",
    "plan_id",
    "plan_hash",
    "lineage_receipt_sha256",
    "plan_seal_comment_url",
    "plan_seal_receipt_sha256",
    "partition",
    "target_package",
    "client_build",
    "capture_store_id",
    "capture_store_identity_sha256",
    "authorization_id",
    "authorization_sha256",
    "game_input_performed",
    "adb_server_ownership_verified",
    "adb_server",
    "artifacts",
    "redaction_status",
    "redaction_regions",
    "annotations",
    "contains_sensitive_content",
    "local_research_only",
    "distribution_allowed",
}
_TRACE_KEYS = {
    "schema_version",
    "trace_id",
    "plan_id",
    "plan_hash",
    "lineage_receipt_sha256",
    "partition",
    "requirement_id",
    "capture_store_id",
    "format_id",
    "viewer",
    "reference_replay_hash",
    "frames",
    "status",
    "blockers",
    "local_research_only",
    "distribution_allowed",
}


def _digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class ResolvedCapture:
    """A capture whose manifest identity and every artifact were revalidated."""

    manifest: CaptureManifest
    manifest_hash: str
    artifact_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class CaptureStoreIdentity:
    schema_version: str
    store_id: str
    partition: str
    store_nonce: str
    local_research_only: bool
    distribution_allowed: bool

    def __post_init__(self) -> None:
        if self.schema_version != "1.0.0":
            raise ValueError("only capture store schema 1.0.0 is supported")
        if (
            len(self.store_id) > 240
            or _STORE_ID_RE.fullmatch(self.store_id) is None
        ):
            raise ValueError("capture store_id must be a stable ID")
        if self.partition not in _STORE_PARTITIONS:
            raise ValueError("capture store partition is invalid")
        if re.fullmatch(r"[0-9a-f]{32}", self.store_nonce) is None:
            raise ValueError("capture store nonce is invalid")
        if self.local_research_only is not True or self.distribution_allowed is not False:
            raise ValueError("capture stores are local research only")

    @property
    def identity_hash(self) -> str:
        return _digest(canonical_json(self).encode("utf-8"))


@dataclass(frozen=True, slots=True)
class ResolvedGroundingTraceArtifact:
    """A canonical trace re-resolved from its exact external bytes."""

    trace: GroundingTrace
    trace_hash: str
    source_path: Path


class CaptureStore:
    """Store unreviewed captures outside the repository by content identity."""

    def __init__(
        self,
        root: Path | str | None = None,
        *,
        store_id: str | None = None,
        partition: str = "development",
        initialize: bool = True,
    ) -> None:
        if partition not in _STORE_PARTITIONS:
            raise ValueError("capture store partition is invalid")
        if root is None and partition == "holdout":
            raise ValueError("holdout capture store root must be explicit")
        store_id = store_id or f"{partition}-captures"
        if (
            not isinstance(store_id, str)
            or len(store_id) > 240
            or _STORE_ID_RE.fullmatch(store_id) is None
        ):
            raise ValueError("capture store_id must be a stable ID")
        if not isinstance(initialize, bool):
            raise TypeError("capture store initialize flag must be boolean")
        candidate = Path(root) if root is not None else default_capture_store_root()
        if not candidate.is_absolute():
            raise ValueError("capture store root must be an absolute path")
        resolved = candidate.resolve(strict=False)
        try:
            resolved.relative_to(_REPOSITORY_ROOT.resolve(strict=True))
        except ValueError:
            pass
        else:
            raise ValueError("capture store root must stay outside the repository")
        self.root = resolved
        self.store_id = store_id
        self.partition = partition
        self._identity = self._initialize_or_load_identity(initialize=initialize)

    @property
    def identity(self) -> CaptureStoreIdentity:
        return self._identity

    @property
    def identity_hash(self) -> str:
        return self._identity.identity_hash

    def save(
        self,
        payload: CapturePayload,
        *,
        capture_id: str | None = None,
    ) -> CaptureManifest:
        self._assert_store_identity()
        expected_capture_id = self.content_capture_id(payload)
        if payload.capture_store_id != self.store_id:
            raise ValueError("capture payload is bound to a different capture store")
        if payload.capture_store_identity_sha256 != self.identity_hash:
            raise ValueError(
                "capture payload is bound to a different physical capture store"
            )
        if payload.partition != self.partition:
            raise ValueError("capture payload is bound to a different store partition")
        capture_id = capture_id or expected_capture_id
        if _CAPTURE_ID_RE.fullmatch(capture_id) is None:
            raise ValueError("capture_id must be a stable ID without path separators")
        if capture_id != expected_capture_id:
            raise ValueError("capture_id must equal the content-addressed capture identity")

        screenshot = payload.screenshot_png
        hierarchy_before = payload.ui_hierarchy_before_xml
        hierarchy = payload.ui_hierarchy_xml
        artifacts = (
            CaptureArtifact(
                artifact_id="screenshot",
                kind=ArtifactKind.SCREENSHOT,
                relative_path="screenshot.png",
                media_type="image/png",
                byte_size=len(screenshot),
                sha256=_digest(screenshot),
            ),
            CaptureArtifact(
                artifact_id="ui-hierarchy-before",
                kind=ArtifactKind.UI_HIERARCHY,
                relative_path="ui-hierarchy-before.xml",
                media_type="application/xml",
                byte_size=len(hierarchy_before),
                sha256=_digest(hierarchy_before),
            ),
            CaptureArtifact(
                artifact_id="ui-hierarchy",
                kind=ArtifactKind.UI_HIERARCHY,
                relative_path="ui-hierarchy.xml",
                media_type="application/xml",
                byte_size=len(hierarchy),
                sha256=_digest(hierarchy),
            ),
        )
        manifest = CaptureManifest(
            schema_version="2.0.0",
            capture_id=capture_id,
            captured_at=payload.captured_at,
            ui_hierarchy_before_captured_at=(
                payload.ui_hierarchy_before_captured_at
            ),
            screenshot_captured_at=payload.screenshot_captured_at,
            ui_hierarchy_captured_at=payload.ui_hierarchy_captured_at,
            ui_state_sha256=payload.ui_state_sha256,
            instance_name=payload.instance_name,
            adb_serial=payload.adb_serial,
            format_id=payload.format_id,
            plan_id=payload.plan_id,
            plan_hash=payload.plan_hash,
            lineage_receipt_sha256=payload.lineage_receipt_sha256,
            plan_seal_comment_url=payload.plan_seal_comment_url,
            plan_seal_receipt_sha256=payload.plan_seal_receipt_sha256,
            partition=payload.partition,
            target_package=payload.target_package,
            client_build=payload.client_build,
            capture_store_id=payload.capture_store_id,
            capture_store_identity_sha256=payload.capture_store_identity_sha256,
            authorization_id=payload.authorization_id,
            authorization_sha256=payload.authorization_sha256,
            game_input_performed=False,
            adb_server_ownership_verified=payload.adb_server_ownership_verified,
            adb_server=payload.adb_server,
            artifacts=artifacts,
            redaction_status=RedactionStatus.UNREVIEWED,
            redaction_regions=(),
            annotations=(),
            contains_sensitive_content=None,
            local_research_only=True,
            distribution_allowed=False,
        )

        self.root.mkdir(parents=True, exist_ok=True)
        final_dir = self.root / capture_id
        if final_dir.exists():
            raise FileExistsError(f"capture already exists: {capture_id}")
        partial_dir = self.root / f".{capture_id}.partial.{uuid.uuid4().hex}"
        partial_dir.mkdir()
        try:
            (partial_dir / "screenshot.png").write_bytes(screenshot)
            (partial_dir / "ui-hierarchy-before.xml").write_bytes(hierarchy_before)
            (partial_dir / "ui-hierarchy.xml").write_bytes(hierarchy)
            (partial_dir / "manifest.json").write_text(
                canonical_json(manifest) + "\n",
                encoding="utf-8",
            )
            partial_dir.rename(final_dir)
        except BaseException:
            if partial_dir.exists():
                shutil.rmtree(partial_dir)
            raise
        return manifest

    @staticmethod
    def content_capture_id(payload: CapturePayload) -> str:
        digest = hashlib.sha256()
        metadata = canonical_json(
            {
                "instance_name": payload.instance_name,
                "adb_serial": payload.adb_serial,
                "captured_at": payload.captured_at,
                "ui_hierarchy_before_captured_at": (
                    payload.ui_hierarchy_before_captured_at
                ),
                "screenshot_captured_at": payload.screenshot_captured_at,
                "ui_hierarchy_captured_at": payload.ui_hierarchy_captured_at,
                "ui_state_sha256": payload.ui_state_sha256,
                "format_id": payload.format_id,
                "plan_id": payload.plan_id,
                "plan_hash": payload.plan_hash,
                "lineage_receipt_sha256": payload.lineage_receipt_sha256,
                "plan_seal_comment_url": payload.plan_seal_comment_url,
                "plan_seal_receipt_sha256": payload.plan_seal_receipt_sha256,
                "partition": payload.partition,
                "target_package": payload.target_package,
                "client_build": payload.client_build,
                "capture_store_id": payload.capture_store_id,
                "capture_store_identity_sha256": (
                    payload.capture_store_identity_sha256
                ),
                "authorization_id": payload.authorization_id,
                "authorization_sha256": payload.authorization_sha256,
                "adb_server_ownership_verified": payload.adb_server_ownership_verified,
                "adb_server": payload.adb_server,
            }
        ).encode("utf-8")
        for label, value in (
            (b"metadata", metadata),
            (b"screenshot.png", payload.screenshot_png),
            (b"ui-hierarchy-before.xml", payload.ui_hierarchy_before_xml),
            (b"ui-hierarchy.xml", payload.ui_hierarchy_xml),
        ):
            digest.update(len(label).to_bytes(4, "big"))
            digest.update(label)
            digest.update(len(value).to_bytes(8, "big"))
            digest.update(value)
        return "capture-" + digest.hexdigest()

    def verify(self, capture_id: str) -> bool:
        try:
            self.resolve(capture_id)
            return True
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return False

    def resolve(self, capture_id: str) -> ResolvedCapture:
        """Resolve a capture only after schema/domain/identity/hash verification."""

        self._assert_store_identity()
        if _CAPTURE_ID_RE.fullmatch(capture_id) is None:
            raise ValueError("capture_id must be a stable ID without path separators")
        root = self.root.resolve(strict=True)
        candidate_dir = self.root / capture_id
        if candidate_dir.is_symlink():
            raise ValueError("capture directory must not be a symbolic link")
        capture_dir = candidate_dir.resolve(strict=True)
        capture_dir.relative_to(root)
        if not capture_dir.is_dir():
            raise ValueError("capture path is not a directory")
        manifest_path = capture_dir / "manifest.json"
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise ValueError("capture manifest is not a regular local file")
        manifest_bytes = manifest_path.read_bytes()
        if len(manifest_bytes) > _MAX_MANIFEST_BYTES:
            raise ValueError("capture manifest exceeds the configured limit")
        raw = json.loads(
            manifest_bytes.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
        manifest = _load_manifest(raw)
        if manifest.capture_id != capture_id:
            raise ValueError("manifest capture_id does not match the requested capture")
        if manifest.capture_store_identity_sha256 != self.identity_hash:
            raise ValueError("manifest physical capture-store identity mismatch")

        payloads: dict[str, bytes] = {}
        for artifact in manifest.artifacts:
            candidate = capture_dir / artifact.relative_path
            if candidate.is_symlink():
                raise ValueError("capture artifact must not be a symbolic link")
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(capture_dir)
            if not resolved.is_file():
                raise ValueError("capture artifact is not a regular file")
            if artifact.byte_size > _MAX_ARTIFACT_BYTES[artifact.artifact_id]:
                raise ValueError("capture artifact exceeds the configured limit")
            if resolved.stat().st_size != artifact.byte_size:
                raise ValueError("capture artifact size mismatch")
            payload = resolved.read_bytes()
            if len(payload) != artifact.byte_size or _digest(payload) != artifact.sha256:
                raise ValueError("capture artifact size or hash mismatch")
            payloads[artifact.artifact_id] = payload

        capture = CapturePayload(
            instance_name=manifest.instance_name,
            adb_serial=manifest.adb_serial,
            captured_at=manifest.captured_at,
            ui_hierarchy_before_captured_at=(
                manifest.ui_hierarchy_before_captured_at
            ),
            screenshot_captured_at=manifest.screenshot_captured_at,
            ui_hierarchy_captured_at=manifest.ui_hierarchy_captured_at,
            format_id=manifest.format_id,
            plan_id=manifest.plan_id,
            plan_hash=manifest.plan_hash,
            lineage_receipt_sha256=manifest.lineage_receipt_sha256,
            plan_seal_comment_url=manifest.plan_seal_comment_url,
            plan_seal_receipt_sha256=manifest.plan_seal_receipt_sha256,
            partition=manifest.partition,
            target_package=manifest.target_package,
            client_build=manifest.client_build,
            capture_store_id=manifest.capture_store_id,
            capture_store_identity_sha256=(
                manifest.capture_store_identity_sha256
            ),
            authorization_id=manifest.authorization_id,
            authorization_sha256=manifest.authorization_sha256,
            adb_server_ownership_verified=manifest.adb_server_ownership_verified,
            adb_server=manifest.adb_server,
            screenshot_png=payloads["screenshot"],
            ui_hierarchy_before_xml=payloads["ui-hierarchy-before"],
            ui_hierarchy_xml=payloads["ui-hierarchy"],
        )
        if capture.ui_state_sha256 != manifest.ui_state_sha256:
            raise ValueError("capture UI state identity mismatch")
        if self.content_capture_id(capture) != capture_id:
            raise ValueError("capture content identity mismatch")
        return ResolvedCapture(
            manifest=manifest,
            manifest_hash=_digest(canonical_json(manifest).encode("utf-8")),
            artifact_ids=frozenset(payloads),
        )

    def manifest_hash(self, capture_id: str) -> str:
        """Return the semantic manifest hash only for a fully verified capture."""

        return self.resolve(capture_id).manifest_hash

    def save_trace(self, trace: GroundingTrace) -> ResolvedGroundingTraceArtifact:
        """Persist one canonical trace by byte hash in this external store."""

        self._assert_store_identity()
        if trace.capture_store_id != self.store_id:
            raise ValueError("grounding trace is bound to a different capture store")
        if trace.partition != self.partition:
            raise ValueError("grounding trace is bound to a different store partition")
        payload = canonical_json(trace).encode("utf-8")
        if len(payload) > _MAX_TRACE_BYTES:
            raise ValueError("grounding trace exceeds the configured limit")
        trace_hash = _digest(payload)
        self.root.mkdir(parents=True, exist_ok=True)
        root = self.root.resolve(strict=True)
        trace_dir_candidate = root / "_traces"
        if trace_dir_candidate.exists():
            if trace_dir_candidate.is_symlink():
                raise ValueError("grounding trace directory must not be a symbolic link")
            trace_dir = trace_dir_candidate.resolve(strict=True)
            trace_dir.relative_to(root)
            if not trace_dir.is_dir():
                raise ValueError("grounding trace path is not a directory")
        else:
            trace_dir_candidate.mkdir()
            trace_dir = trace_dir_candidate.resolve(strict=True)
        final_path = trace_dir / f"{trace_hash.removeprefix('sha256:')}.json"
        if final_path.exists():
            raise FileExistsError(f"grounding trace already exists: {trace_hash}")
        partial_path = trace_dir / f".{final_path.name}.partial.{uuid.uuid4().hex}"
        try:
            partial_path.write_bytes(payload)
            partial_path.rename(final_path)
        except BaseException:
            if partial_path.exists():
                partial_path.unlink()
            raise
        return ResolvedGroundingTraceArtifact(
            trace=trace,
            trace_hash=trace_hash,
            source_path=final_path,
        )

    def resolve_trace(self, trace_hash: str) -> ResolvedGroundingTraceArtifact:
        """Resolve a trace from exact canonical bytes and its logical store."""

        self._assert_store_identity()
        if _TRACE_HASH_RE.fullmatch(trace_hash) is None:
            raise ValueError("trace_hash must be a sha256-prefixed lowercase digest")
        root = self.root.resolve(strict=True)
        trace_dir_candidate = root / "_traces"
        if trace_dir_candidate.is_symlink():
            raise ValueError("grounding trace directory must not be a symbolic link")
        trace_dir = trace_dir_candidate.resolve(strict=True)
        trace_dir.relative_to(root)
        candidate = trace_dir / f"{trace_hash.removeprefix('sha256:')}.json"
        if candidate.is_symlink() or not candidate.is_file():
            raise ValueError("grounding trace is not a regular local file")
        source_path = candidate.resolve(strict=True)
        source_path.relative_to(trace_dir)
        payload = source_path.read_bytes()
        if len(payload) > _MAX_TRACE_BYTES:
            raise ValueError("grounding trace exceeds the configured limit")
        if _digest(payload) != trace_hash:
            raise ValueError("grounding trace byte identity mismatch")
        raw = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
        trace = _load_grounding_trace(raw)
        if canonical_json(trace).encode("utf-8") != payload:
            raise ValueError("grounding trace bytes are not canonical JSON")
        if trace.capture_store_id != self.store_id:
            raise ValueError("grounding trace is bound to a different capture store")
        return ResolvedGroundingTraceArtifact(
            trace=trace,
            trace_hash=trace_hash,
            source_path=source_path,
        )

    def _initialize_or_load_identity(
        self, *, initialize: bool
    ) -> CaptureStoreIdentity:
        if not initialize:
            if not self.root.is_dir():
                raise ValueError("capture store must be initialized before use")
            identity = _load_store_identity(self.root / _STORE_MANIFEST_NAME)
            if identity.store_id != self.store_id or identity.partition != self.partition:
                raise ValueError("capture store manifest does not match requested identity")
            return identity
        self.root.mkdir(parents=True, exist_ok=True)
        manifest_path = self.root / _STORE_MANIFEST_NAME
        if manifest_path.exists():
            identity = _load_store_identity(manifest_path)
        else:
            if any(self.root.iterdir()):
                raise ValueError(
                    "capture store is non-empty but has no persistent store manifest"
                )
            identity = CaptureStoreIdentity(
                schema_version="1.0.0",
                store_id=self.store_id,
                partition=self.partition,
                store_nonce=uuid.uuid4().hex,
                local_research_only=True,
                distribution_allowed=False,
            )
            payload = canonical_json(identity).encode("utf-8")
            try:
                with manifest_path.open("xb") as stream:
                    stream.write(payload)
            except FileExistsError:
                identity = _load_store_identity(manifest_path)
        if identity.store_id != self.store_id or identity.partition != self.partition:
            raise ValueError("capture store manifest does not match requested identity")
        return identity

    def _assert_store_identity(self) -> None:
        observed = _load_store_identity(self.root / _STORE_MANIFEST_NAME)
        if observed != self._identity:
            raise ValueError("capture store manifest changed after opening")


def _require_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ValueError(f"{label} has missing or unexpected fields")


def _load_store_identity(path: Path) -> CaptureStoreIdentity:
    if path.is_symlink() or not path.is_file():
        raise ValueError("capture store manifest is not a regular local file")
    payload = path.read_bytes()
    if len(payload) > 64 * 1024:
        raise ValueError("capture store manifest exceeds the configured limit")
    raw = json.loads(
        payload.decode("utf-8"),
        object_pairs_hook=_strict_object,
        parse_constant=_reject_constant,
    )
    value = _mapping(raw, "capture store manifest")
    _require_keys(value, _STORE_MANIFEST_KEYS, "capture store manifest")
    identity = CaptureStoreIdentity(
        schema_version=_string(value["schema_version"], "schema_version"),
        store_id=_string(value["store_id"], "store_id"),
        partition=_string(value["partition"], "partition"),
        store_nonce=_string(value["store_nonce"], "store_nonce"),
        local_research_only=_boolean(
            value["local_research_only"], "local_research_only"
        ),
        distribution_allowed=_boolean(
            value["distribution_allowed"], "distribution_allowed"
        ),
    )
    if canonical_json(identity).encode("utf-8") != payload:
        raise ValueError("capture store manifest is not canonical JSON")
    return identity


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON value is not allowed: {value}")


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be an object")
    return value


def _array(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise TypeError(f"{label} must be an array")
    return value


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    return value


def _integer(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{label} must be an integer")
    return value


def _boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{label} must be a boolean")
    return value


def _box(value: Any) -> BoundingBox:
    raw = _mapping(value, "bounding box")
    _require_keys(raw, {"x", "y", "width", "height"}, "bounding box")
    return BoundingBox(
        x=_integer(raw["x"], "box.x"),
        y=_integer(raw["y"], "box.y"),
        width=_integer(raw["width"], "box.width"),
        height=_integer(raw["height"], "box.height"),
    )


def _client_build(value: Any) -> AndroidClientBuild:
    raw = _mapping(value, "client_build")
    _require_keys(
        raw,
        {"version_code", "version_name", "apk_count", "apk_set_sha256"},
        "client_build",
    )
    return AndroidClientBuild(
        version_code=_integer(raw["version_code"], "client_build.version_code"),
        version_name=_string(raw["version_name"], "client_build.version_name"),
        apk_count=_integer(raw["apk_count"], "client_build.apk_count"),
        apk_set_sha256=_string(
            raw["apk_set_sha256"], "client_build.apk_set_sha256"
        ),
    )


def _load_manifest(value: Any) -> CaptureManifest:
    raw = _mapping(value, "capture manifest")
    _require_keys(raw, _MANIFEST_KEYS, "capture manifest")

    artifacts: list[CaptureArtifact] = []
    artifact_keys = {"artifact_id", "kind", "relative_path", "media_type", "byte_size", "sha256"}
    for index, value in enumerate(_array(raw["artifacts"], "artifacts")):
        artifact = _mapping(value, f"artifacts[{index}]")
        _require_keys(artifact, artifact_keys, f"artifacts[{index}]")
        artifacts.append(
            CaptureArtifact(
                artifact_id=_string(artifact["artifact_id"], "artifact_id"),
                kind=ArtifactKind(_string(artifact["kind"], "artifact kind")),
                relative_path=_string(artifact["relative_path"], "relative_path"),
                media_type=_string(artifact["media_type"], "media_type"),
                byte_size=_integer(artifact["byte_size"], "byte_size"),
                sha256=_string(artifact["sha256"], "sha256"),
            )
        )

    regions: list[RedactionRegion] = []
    for index, value in enumerate(_array(raw["redaction_regions"], "redaction_regions")):
        region = _mapping(value, f"redaction_regions[{index}]")
        _require_keys(region, {"region_id", "box", "reason"}, f"redaction_regions[{index}]")
        regions.append(
            RedactionRegion(
                region_id=_string(region["region_id"], "region_id"),
                box=_box(region["box"]),
                reason=_string(region["reason"], "redaction reason"),
            )
        )

    annotations: list[CaptureAnnotation] = []
    annotation_keys = {
        "annotation_id",
        "label",
        "source",
        "confidence_ppm",
        "artifact_id",
        "box",
        "value",
    }
    for index, value in enumerate(_array(raw["annotations"], "annotations")):
        annotation = _mapping(value, f"annotations[{index}]")
        _require_keys(annotation, annotation_keys, f"annotations[{index}]")
        box_value = annotation["box"]
        annotations.append(
            CaptureAnnotation(
                annotation_id=_string(annotation["annotation_id"], "annotation_id"),
                label=_string(annotation["label"], "annotation label"),
                source=AnnotationSource(_string(annotation["source"], "annotation source")),
                confidence_ppm=_integer(annotation["confidence_ppm"], "confidence_ppm"),
                artifact_id=_string(annotation["artifact_id"], "artifact_id"),
                box=None if box_value is None else _box(box_value),
                value=annotation["value"],
            )
        )

    sensitive = raw["contains_sensitive_content"]
    if sensitive is not None and not isinstance(sensitive, bool):
        raise TypeError("contains_sensitive_content must be boolean or null")
    server_raw = _mapping(raw["adb_server"], "adb_server")
    _require_keys(
        server_raw,
        {
            "host",
            "port",
            "process_id",
            "process_started_at",
            "executable_sha256",
            "transport",
        },
        "adb_server",
    )
    server = AdbServerIdentity(
        host=_string(server_raw["host"], "adb_server.host"),
        port=_integer(server_raw["port"], "adb_server.port"),
        process_id=_integer(server_raw["process_id"], "adb_server.process_id"),
        process_started_at=_string(
            server_raw["process_started_at"], "adb_server.process_started_at"
        ),
        executable_sha256=_string(
            server_raw["executable_sha256"], "adb_server.executable_sha256"
        ),
        transport=_string(server_raw["transport"], "adb_server.transport"),
    )
    return CaptureManifest(
        schema_version=_string(raw["schema_version"], "schema_version"),
        capture_id=_string(raw["capture_id"], "capture_id"),
        captured_at=_string(raw["captured_at"], "captured_at"),
        ui_hierarchy_before_captured_at=_string(
            raw["ui_hierarchy_before_captured_at"],
            "ui_hierarchy_before_captured_at",
        ),
        screenshot_captured_at=_string(
            raw["screenshot_captured_at"], "screenshot_captured_at"
        ),
        ui_hierarchy_captured_at=_string(
            raw["ui_hierarchy_captured_at"], "ui_hierarchy_captured_at"
        ),
        ui_state_sha256=_string(raw["ui_state_sha256"], "ui_state_sha256"),
        instance_name=_string(raw["instance_name"], "instance_name"),
        adb_serial=_string(raw["adb_serial"], "adb_serial"),
        format_id=_string(raw["format_id"], "format_id"),
        plan_id=_string(raw["plan_id"], "plan_id"),
        plan_hash=_string(raw["plan_hash"], "plan_hash"),
        lineage_receipt_sha256=_string(
            raw["lineage_receipt_sha256"], "lineage_receipt_sha256"
        ),
        plan_seal_comment_url=_string(
            raw["plan_seal_comment_url"], "plan_seal_comment_url"
        ),
        plan_seal_receipt_sha256=_string(
            raw["plan_seal_receipt_sha256"], "plan_seal_receipt_sha256"
        ),
        partition=_string(raw["partition"], "partition"),
        target_package=_string(raw["target_package"], "target_package"),
        client_build=_client_build(raw["client_build"]),
        capture_store_id=_string(raw["capture_store_id"], "capture_store_id"),
        capture_store_identity_sha256=_string(
            raw["capture_store_identity_sha256"],
            "capture_store_identity_sha256",
        ),
        authorization_id=_string(raw["authorization_id"], "authorization_id"),
        authorization_sha256=_string(
            raw["authorization_sha256"], "authorization_sha256"
        ),
        game_input_performed=_boolean(raw["game_input_performed"], "game_input_performed"),
        adb_server_ownership_verified=_boolean(
            raw["adb_server_ownership_verified"], "adb_server_ownership_verified"
        ),
        adb_server=server,
        artifacts=tuple(artifacts),
        redaction_status=RedactionStatus(_string(raw["redaction_status"], "redaction_status")),
        redaction_regions=tuple(regions),
        annotations=tuple(annotations),
        contains_sensitive_content=sensitive,
        local_research_only=_boolean(raw["local_research_only"], "local_research_only"),
        distribution_allowed=_boolean(raw["distribution_allowed"], "distribution_allowed"),
    )


def _load_grounding_trace(value: Any) -> GroundingTrace:
    raw = _mapping(value, "grounding trace")
    _require_keys(raw, _TRACE_KEYS, "grounding trace")
    frames: list[GroundingFrame] = []
    frame_keys = {
        "frame_id",
        "capture_id",
        "capture_manifest_hash",
        "observed_at",
        "fields",
        "conformance",
    }
    field_keys = {
        "path",
        "status",
        "source",
        "value",
        "confidence_ppm",
        "artifact_ids",
        "note",
    }
    check_keys = {
        "path",
        "verdict",
        "expected",
        "observed",
        "artifact_ids",
        "note",
    }
    for frame_index, frame_value in enumerate(_array(raw["frames"], "frames")):
        frame_raw = _mapping(frame_value, f"frames[{frame_index}]")
        _require_keys(frame_raw, frame_keys, f"frames[{frame_index}]")
        fields: list[GroundedField] = []
        for field_index, field_value in enumerate(
            _array(frame_raw["fields"], f"frames[{frame_index}].fields")
        ):
            field_raw = _mapping(
                field_value,
                f"frames[{frame_index}].fields[{field_index}]",
            )
            _require_keys(
                field_raw,
                field_keys,
                f"frames[{frame_index}].fields[{field_index}]",
            )
            fields.append(
                GroundedField(
                    path=_string(field_raw["path"], "grounded field path"),
                    status=GroundingStatus(
                        _string(field_raw["status"], "grounded field status")
                    ),
                    source=GroundingSource(
                        _string(field_raw["source"], "grounded field source")
                    ),
                    value=field_raw["value"],
                    confidence_ppm=_integer(
                        field_raw["confidence_ppm"], "grounded field confidence_ppm"
                    ),
                    artifact_ids=_string_tuple(
                        field_raw["artifact_ids"], "grounded field artifact_ids"
                    ),
                    note=_nullable_string(field_raw["note"], "grounded field note"),
                )
            )
        checks: list[ConformanceCheck] = []
        for check_index, check_value in enumerate(
            _array(frame_raw["conformance"], f"frames[{frame_index}].conformance")
        ):
            check_raw = _mapping(
                check_value,
                f"frames[{frame_index}].conformance[{check_index}]",
            )
            _require_keys(
                check_raw,
                check_keys,
                f"frames[{frame_index}].conformance[{check_index}]",
            )
            checks.append(
                ConformanceCheck(
                    path=_string(check_raw["path"], "conformance path"),
                    verdict=ConformanceVerdict(
                        _string(check_raw["verdict"], "conformance verdict")
                    ),
                    expected=check_raw["expected"],
                    observed=check_raw["observed"],
                    artifact_ids=_string_tuple(
                        check_raw["artifact_ids"], "conformance artifact_ids"
                    ),
                    note=_nullable_string(check_raw["note"], "conformance note"),
                )
            )
        frames.append(
            GroundingFrame(
                frame_id=_string(frame_raw["frame_id"], "frame_id"),
                capture_id=_string(frame_raw["capture_id"], "capture_id"),
                capture_manifest_hash=_string(
                    frame_raw["capture_manifest_hash"], "capture_manifest_hash"
                ),
                observed_at=_string(frame_raw["observed_at"], "observed_at"),
                fields=tuple(fields),
                conformance=tuple(checks),
            )
        )
    replay_hash = raw["reference_replay_hash"]
    return GroundingTrace(
        schema_version=_string(raw["schema_version"], "schema_version"),
        trace_id=_string(raw["trace_id"], "trace_id"),
        plan_id=_string(raw["plan_id"], "plan_id"),
        plan_hash=_string(raw["plan_hash"], "plan_hash"),
        lineage_receipt_sha256=_string(
            raw["lineage_receipt_sha256"], "lineage_receipt_sha256"
        ),
        partition=_string(raw["partition"], "partition"),
        requirement_id=_string(raw["requirement_id"], "requirement_id"),
        capture_store_id=_string(raw["capture_store_id"], "capture_store_id"),
        format_id=_string(raw["format_id"], "format_id"),
        viewer=_string(raw["viewer"], "viewer"),
        reference_replay_hash=_nullable_string(
            replay_hash, "reference_replay_hash"
        ),
        frames=tuple(frames),
        status=GroundingTraceStatus(_string(raw["status"], "status")),
        blockers=_string_tuple(raw["blockers"], "blockers"),
        local_research_only=_boolean(raw["local_research_only"], "local_research_only"),
        distribution_allowed=_boolean(raw["distribution_allowed"], "distribution_allowed"),
    )


def _nullable_string(value: Any, label: str) -> str | None:
    if value is None:
        return None
    return _string(value, label)


def _string_tuple(value: Any, label: str) -> tuple[str, ...]:
    return tuple(_string(item, label) for item in _array(value, label))


def default_capture_store_root() -> Path:
    """Return a canonical external development-capture root."""

    configured = os.environ.get("CHAMPIONS_SIM_CAPTURE_STORE")
    if configured:
        return Path(configured)
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / ".local" / "share"
    return base / "pokemon-auto-battle-single" / "captures" / "development"
