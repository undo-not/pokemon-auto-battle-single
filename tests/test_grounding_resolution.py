from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from champions_sim.grounding import (
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
PNG = b"\x89PNG\r\n\x1a\nresolver-test"
XML = b'<?xml version="1.0"?><hierarchy></hierarchy>'


def _store(tmp_path: Path) -> tuple[CaptureStore, str, str]:
    store = CaptureStore(tmp_path / "artifacts" / "bluestacks")
    manifest = store.save(
        CapturePayload(
            instance_name="Pie64",
            adb_serial="127.0.0.1:5555",
            captured_at="2026-07-13T00:00:00Z",
            adb_server_ownership_verified=True,
            screenshot_png=PNG,
            ui_hierarchy_xml=XML,
        )
    )
    return store, manifest.capture_id, store.manifest_hash(manifest.capture_id)


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
        schema_version="1.0.0",
        trace_id="trace-resolved",
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


def test_resolver_promotes_only_store_bound_trace(tmp_path: Path) -> None:
    store, capture_id, manifest_hash = _store(tmp_path)
    trace = _trace(capture_id, manifest_hash)

    grounded = validate_grounding_trace_against_store(trace, store)

    assert grounded.promotable
    assert grounded.capture_bindings[0].capture_id == capture_id
    with pytest.raises(GroundingValidationError, match="resolver gate"):
        ValidatedGroundingTrace(trace, grounded.capture_bindings)


def test_trace_resolver_rejects_wrong_hash_missing_capture_and_tampered_artifact(
    tmp_path: Path,
) -> None:
    store, capture_id, manifest_hash = _store(tmp_path)

    with pytest.raises(GroundingValidationError, match="manifest hash mismatch"):
        validate_grounding_trace_against_store(
            _trace(capture_id, "sha256:" + "0" * 64), store
        )

    missing_capture_id = "capture-" + "f" * 64
    with pytest.raises(GroundingValidationError, match="does not resolve"):
        validate_grounding_trace_against_store(
            _trace(missing_capture_id, "sha256:" + "0" * 64), store
        )

    (store.root / capture_id / "ui-hierarchy.xml").write_bytes(b"tampered")
    with pytest.raises(GroundingValidationError, match="does not resolve"):
        validate_grounding_trace_against_store(_trace(capture_id, manifest_hash), store)


def test_incomplete_trace_is_resolved_but_not_promotable(tmp_path: Path) -> None:
    store, capture_id, manifest_hash = _store(tmp_path)
    trace = _trace(
        capture_id,
        manifest_hash,
        status=GroundingTraceStatus.INCOMPLETE,
    )

    assert not validate_grounding_trace_against_store(trace, store).promotable


def test_grounding_trace_matches_current_schema(tmp_path: Path) -> None:
    _store_value, capture_id, manifest_hash = _store(tmp_path)
    schema = json.loads(
        (ROOT / "data/schemas/grounding-trace.schema.json").read_text(encoding="utf-8")
    )

    Draft202012Validator(schema).validate(_trace(capture_id, manifest_hash).to_dict())
