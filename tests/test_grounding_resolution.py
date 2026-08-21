from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from champions_sim.grounding import (
    AdbServerIdentity,
    AndroidClientBuild,
    CapturePayload,
    CaptureStore,
    ConformanceCheck,
    ConformanceVerdict,
    GroundedField,
    GroundingFrame,
    GroundingSource,
    GroundingStatus,
    GroundingTrace,
    GroundingTraceStatus,
    GroundingValidationError,
    ValidatedGroundingTrace,
    validate_grounding_trace_against_store,
)


ROOT = Path(__file__).resolve().parents[1]
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c63103209fb0f000294019c1d5b465f0000000049454e44"
    "ae426082"
)
TARGET_PACKAGE = "com.pokemon.champions"
XML = (
    b'<?xml version="1.0"?><hierarchy>'
    b'<node package="com.pokemon.champions"/></hierarchy>'
)
ISSUE_URL = "https://github.com/undo-not/pokemon-auto-battle-single/issues/3"
SEAL_COMMENT_URL = ISSUE_URL + "#issuecomment-123"
SEAL_RECEIPT_SHA256 = "sha256:" + "d" * 64
LINEAGE_RECEIPT_SHA256 = "sha256:" + "e" * 64
CLIENT_BUILD = AndroidClientBuild(
    version_code=2026082101,
    version_name="1.0.0-test",
    apk_count=1,
    apk_set_sha256="sha256:" + "9" * 64,
)


def _store(tmp_path: Path) -> tuple[CaptureStore, str, str, dict[str, Path]]:
    store = CaptureStore(tmp_path / "artifacts" / "bluestacks")
    authorization_path = tmp_path / "authorization.json"
    authorization_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "authorization_id": "authorization-issue-3-test",
                "issue_url": ISSUE_URL,
                "granted_by": "test-operator",
                "granted_at": "2026-07-12T23:00:00Z",
                "expires_at": "2026-07-13T01:00:00Z",
                "format_id": "gen9championsbssregmb",
                "plan_id": "m-b-grounding-development",
                "plan_hash": "sha256:" + "c" * 64,
                "lineage_receipt_sha256": LINEAGE_RECEIPT_SHA256,
                "plan_seal_comment_url": SEAL_COMMENT_URL,
                "plan_seal_receipt_sha256": SEAL_RECEIPT_SHA256,
                "partition": "development",
                "instance_name": "Pie64",
                "target_package": TARGET_PACKAGE,
                "client_build": CLIENT_BUILD.to_dict(),
                "capture_store_id": "development-captures",
                "capture_store_identity_sha256": store.identity_hash,
                "allowed_actions": [
                    "client_identity",
                    "screenshot",
                    "ui_hierarchy",
                ],
                "game_scope": "private_friend_match",
                "ranked_match_allowed": False,
                "input_automation_allowed": False,
            }
        ),
        encoding="utf-8",
    )
    authorization_hash = "sha256:" + hashlib.sha256(
        authorization_path.read_bytes()
    ).hexdigest()
    manifest = store.save(
        CapturePayload(
            instance_name="Pie64",
            adb_serial="127.0.0.1:5555",
            captured_at="2026-07-13T00:00:00Z",
            ui_hierarchy_before_captured_at="2026-07-13T00:00:00Z",
            screenshot_captured_at="2026-07-13T00:00:00Z",
            ui_hierarchy_captured_at="2026-07-13T00:00:00Z",
            format_id="gen9championsbssregmb",
            plan_id="m-b-grounding-development",
            plan_hash="sha256:" + "c" * 64,
            lineage_receipt_sha256=LINEAGE_RECEIPT_SHA256,
            plan_seal_comment_url=SEAL_COMMENT_URL,
            plan_seal_receipt_sha256=SEAL_RECEIPT_SHA256,
            partition="development",
            target_package=TARGET_PACKAGE,
            client_build=CLIENT_BUILD,
            capture_store_id="development-captures",
            capture_store_identity_sha256=store.identity_hash,
            authorization_id="authorization-issue-3-test",
            authorization_sha256=authorization_hash,
            adb_server_ownership_verified=True,
            adb_server=AdbServerIdentity(
                host="127.0.0.1",
                port=5037,
                process_id=4321,
                process_started_at="2026-07-13T00:00:00+00:00",
                executable_sha256="sha256:" + "a" * 64,
            ),
            screenshot_png=PNG,
            ui_hierarchy_before_xml=XML,
            ui_hierarchy_xml=XML,
        )
    )
    return (
        store,
        manifest.capture_id,
        store.manifest_hash(manifest.capture_id),
        {authorization_hash: authorization_path},
    )


def _trace(
    capture_id: str,
    manifest_hash: str,
    *,
    status: GroundingTraceStatus = GroundingTraceStatus.CONFORMANT,
) -> GroundingTrace:
    check = ConformanceCheck(
        path="/turn",
        verdict=ConformanceVerdict.MATCH,
        expected=1,
        observed=1,
        artifact_ids=("ui-hierarchy",),
    )
    return GroundingTrace(
        schema_version="2.0.0",
        trace_id="trace-resolved",
        plan_id="m-b-grounding-development",
        plan_hash="sha256:" + "c" * 64,
        lineage_receipt_sha256=LINEAGE_RECEIPT_SHA256,
        partition="development",
        requirement_id="turn-visible",
        capture_store_id="development-captures",
        format_id="gen9championsbssregmb",
        viewer="p1",
        reference_replay_hash=None,
        frames=(
            GroundingFrame(
                frame_id="frame-resolved",
                capture_id=capture_id,
                capture_manifest_hash=manifest_hash,
                observed_at="2026-07-13T00:00:00Z",
                fields=(
                    GroundedField(
                        path="/turn",
                        status=GroundingStatus.OBSERVED,
                        source=GroundingSource.UI_METADATA,
                        value=1,
                        confidence_ppm=1_000_000,
                        artifact_ids=("ui-hierarchy",),
                    ),
                ),
                conformance=(check,),
            ),
        ),
        status=status,
        blockers=("capture_incomplete",) if status is GroundingTraceStatus.INCOMPLETE else (),
        local_research_only=True,
        distribution_allowed=False,
    )


def _stored(store: CaptureStore, trace: GroundingTrace):
    return store.save_trace(trace)


def _validate(stored, store: CaptureStore, authorization_paths: dict[str, Path]):
    return validate_grounding_trace_against_store(
        stored,
        store,
        issue_url=ISSUE_URL,
        authorization_paths=authorization_paths,
    )


def test_resolver_promotes_only_store_bound_trace(tmp_path: Path) -> None:
    store, capture_id, manifest_hash, authorization_paths = _store(tmp_path)
    trace = _trace(capture_id, manifest_hash)

    stored = _stored(store, trace)
    grounded = _validate(stored, store, authorization_paths)

    assert grounded.promotable
    assert grounded.source_trace_hash.startswith("sha256:")
    assert grounded.capture_bindings[0].capture_id == capture_id
    assert grounded.capture_bindings[0].capture_store_id == "development-captures"
    with pytest.raises(GroundingValidationError, match="resolver gate"):
        ValidatedGroundingTrace(
            trace,
            grounded.source_trace_hash,
            grounded.capture_bindings,
        )

    with pytest.raises(GroundingValidationError, match="external trace store"):
        _validate(trace, store, authorization_paths)
    with pytest.raises(GroundingValidationError, match="authorization is unavailable"):
        _validate(stored, store, {})

    authorization_path = next(iter(authorization_paths.values()))
    authorization_path.write_text(
        json.dumps(json.loads(authorization_path.read_text(encoding="utf-8")), indent=2),
        encoding="utf-8",
    )
    with pytest.raises(GroundingValidationError, match="authorization identity mismatch"):
        _validate(stored, store, authorization_paths)


def test_external_trace_store_re_resolves_exact_bytes_and_rejects_tampering(
    tmp_path: Path,
) -> None:
    store, capture_id, manifest_hash, authorization_paths = _store(tmp_path)
    stored = store.save_trace(_trace(capture_id, manifest_hash))

    assert store.resolve_trace(stored.trace_hash) == stored
    stored.source_path.write_bytes(b"{}")

    with pytest.raises(GroundingValidationError, match="bytes do not re-resolve"):
        _validate(stored, store, authorization_paths)


def test_trace_resolver_rejects_wrong_hash_missing_capture_and_tampered_artifact(
    tmp_path: Path,
) -> None:
    store, capture_id, manifest_hash, authorization_paths = _store(tmp_path)

    with pytest.raises(GroundingValidationError, match="manifest hash mismatch"):
        _validate(
            _stored(store, _trace(capture_id, "sha256:" + "0" * 64)),
            store,
            authorization_paths,
        )

    missing_capture_id = "capture-" + "f" * 64
    with pytest.raises(GroundingValidationError, match="does not resolve"):
        _validate(
            _stored(store, _trace(missing_capture_id, "sha256:" + "0" * 64)),
            store,
            authorization_paths,
        )

    (store.root / capture_id / "ui-hierarchy.xml").write_bytes(b"tampered")
    with pytest.raises(GroundingValidationError, match="does not resolve"):
        _validate(
            _stored(store, _trace(capture_id, manifest_hash)),
            store,
            authorization_paths,
        )


def test_incomplete_trace_is_resolved_but_not_promotable(tmp_path: Path) -> None:
    store, capture_id, manifest_hash, authorization_paths = _store(tmp_path)
    trace = _trace(
        capture_id,
        manifest_hash,
        status=GroundingTraceStatus.INCOMPLETE,
    )

    assert not _validate(
        _stored(store, trace), store, authorization_paths
    ).promotable


def test_trace_resolver_rejects_capture_timestamp_mismatch(tmp_path: Path) -> None:
    store, capture_id, manifest_hash, authorization_paths = _store(tmp_path)
    trace = _trace(capture_id, manifest_hash)
    frame = trace.frames[0]
    mismatched = GroundingTrace(
        schema_version=trace.schema_version,
        trace_id=trace.trace_id,
        plan_id=trace.plan_id,
        plan_hash=trace.plan_hash,
        lineage_receipt_sha256=trace.lineage_receipt_sha256,
        partition=trace.partition,
        requirement_id=trace.requirement_id,
        capture_store_id=trace.capture_store_id,
        format_id=trace.format_id,
        viewer=trace.viewer,
        reference_replay_hash=trace.reference_replay_hash,
        frames=(
            GroundingFrame(
                frame_id=frame.frame_id,
                capture_id=frame.capture_id,
                capture_manifest_hash=frame.capture_manifest_hash,
                observed_at="2026-07-13T00:00:01Z",
                fields=frame.fields,
                conformance=frame.conformance,
            ),
        ),
        status=trace.status,
        blockers=trace.blockers,
        local_research_only=True,
        distribution_allowed=False,
    )

    with pytest.raises(GroundingValidationError, match="timestamp mismatch"):
        _validate(_stored(store, mismatched), store, authorization_paths)


def test_grounding_frame_rejects_field_and_check_contradiction(
    tmp_path: Path,
) -> None:
    store, capture_id, manifest_hash, _authorization_paths = _store(tmp_path)
    with pytest.raises(ValueError, match="value differs"):
        GroundingFrame(
            frame_id="contradictory-frame",
            capture_id=capture_id,
            capture_manifest_hash=manifest_hash,
            observed_at="2026-07-13T00:00:00Z",
            fields=(
                GroundedField(
                    path="/turn",
                    status=GroundingStatus.OBSERVED,
                    source=GroundingSource.UI_METADATA,
                    value=2,
                    confidence_ppm=1_000_000,
                    artifact_ids=("ui-hierarchy",),
                ),
            ),
            conformance=(
                ConformanceCheck(
                    path="/turn",
                    verdict=ConformanceVerdict.MATCH,
                    expected=1,
                    observed=1,
                    artifact_ids=("ui-hierarchy",),
                ),
            ),
        )


def test_observed_field_cannot_claim_inference_as_its_source() -> None:
    with pytest.raises(ValueError, match="only inferred fields"):
        GroundedField(
            path="/turn",
            status=GroundingStatus.OBSERVED,
            source=GroundingSource.INFERENCE,
            value=1,
            confidence_ppm=1_000_000,
            artifact_ids=("ui-hierarchy",),
        )


def test_observed_field_requires_positive_confidence() -> None:
    with pytest.raises(ValueError, match="positive confidence"):
        GroundedField(
            path="/turn",
            status=GroundingStatus.OBSERVED,
            source=GroundingSource.UI_METADATA,
            value=1,
            confidence_ppm=0,
            artifact_ids=("ui-hierarchy",),
        )


def test_grounded_field_values_are_deeply_immutable() -> None:
    field = GroundedField(
        path="/turn",
        status=GroundingStatus.OBSERVED,
        source=GroundingSource.UI_METADATA,
        value={"history": [1]},
        confidence_ppm=1_000_000,
        artifact_ids=("ui-hierarchy",),
    )

    with pytest.raises(TypeError):
        field.value["history"] = (2,)
    with pytest.raises(AttributeError):
        field.value["history"].append(2)


def test_grounding_trace_matches_current_schema(tmp_path: Path) -> None:
    _store_value, capture_id, manifest_hash, _authorization_paths = _store(tmp_path)
    schema = json.loads(
        (ROOT / "data/schemas/grounding-trace.schema.json").read_text(encoding="utf-8")
    )
    validator = Draft202012Validator(schema)
    document = _trace(capture_id, manifest_hash).to_dict()

    validator.validate(document)
    document["frames"][0]["fields"][0]["source"] = "inference"
    assert not validator.is_valid(document)
    document["frames"][0]["fields"][0]["source"] = "ui_metadata"
    document["frames"][0]["fields"][0]["confidence_ppm"] = 0
    assert not validator.is_valid(document)
