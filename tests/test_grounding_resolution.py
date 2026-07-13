from __future__ import annotations

from pathlib import Path

import pytest

from champions_sim.grounding import (
    CapturePayload,
    CaptureStore,
    ConformanceCheck,
    ConformanceVerdict,
    EnvObservation,
    GroundedField,
    GroundingFrame,
    GroundingSource,
    GroundingStatus,
    GroundingTrace,
    GroundingTraceStatus,
    GroundingValidationError,
    LegalActionMask,
    MaskStatus,
    ObservationProvenance,
    ObservationSource,
    ValidatedEnvObservation,
    validate_env_observation_against_trace_and_store,
    validate_grounding_trace_against_store,
)


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
    trace_id: str = "trace-resolved",
    status: GroundingTraceStatus = GroundingTraceStatus.CONFORMANT,
) -> GroundingTrace:
    fields = (
        GroundedField(
            path="/turn",
            status=GroundingStatus.OBSERVED,
            source=GroundingSource.UI_METADATA,
            value=1,
            confidence_ppm=1_000_000,
            artifact_ids=("ui-hierarchy",),
        ),
        GroundedField(
            path="/phase",
            status=GroundingStatus.OBSERVED,
            source=GroundingSource.UI_METADATA,
            value="awaiting_decisions",
            confidence_ppm=1_000_000,
            artifact_ids=("ui-hierarchy",),
        ),
    )
    return GroundingTrace(
        schema_version="1.0.0",
        trace_id=trace_id,
        ruleset_id="ruleset-1",
        viewer="p1",
        reference_replay_hash=None,
        frames=(
            GroundingFrame(
                frame_id="frame-resolved",
                capture_id=capture_id,
                capture_manifest_hash=manifest_hash,
                observed_at="2026-07-13T00:00:00Z",
                fields=fields,
                conformance=(
                    ConformanceCheck(
                        path="/turn",
                        verdict=ConformanceVerdict.MATCH,
                        expected=1,
                        observed=1,
                        artifact_ids=("ui-hierarchy",),
                    ),
                ),
            ),
        ),
        status=status,
        blockers=("trace_incomplete",) if status is GroundingTraceStatus.INCOMPLETE else (),
        local_research_only=True,
        distribution_allowed=False,
    )


def _env(
    capture_id: str,
    *,
    trace_id: str = "trace-resolved",
    actionable: bool,
) -> EnvObservation:
    reference = f"{capture_id}/ui-hierarchy"
    mask = (
        LegalActionMask(
            status=MaskStatus.KNOWN,
            request_id="request-1",
            action_ids=("move-1",),
            legal=(True,),
            source=ObservationSource.GROUNDED_CAPTURE,
            evidence_artifact_ids=(reference,),
        )
        if actionable
        else LegalActionMask.unknown("decision controls not grounded")
    )
    return EnvObservation(
        schema_version="1.0.0",
        observation_id="observation-resolved",
        battle_id="battle-1",
        ruleset_id="ruleset-1",
        viewer="p1",
        turn=1,
        phase="awaiting_decisions",
        instant_fields=(
            GroundedField(
                path="/turn",
                status=GroundingStatus.OBSERVED,
                source=GroundingSource.UI_METADATA,
                value=1,
                confidence_ppm=1_000_000,
                artifact_ids=(reference,),
            ),
            GroundedField(
                path="/phase",
                status=GroundingStatus.OBSERVED,
                source=GroundingSource.UI_METADATA,
                value="awaiting_decisions",
                confidence_ppm=1_000_000,
                artifact_ids=(reference,),
            ),
        ),
        public_history=(),
        legal_action_mask=mask,
        provenance=ObservationProvenance(
            source=ObservationSource.GROUNDED_CAPTURE,
            capture_ids=(capture_id,),
            artifact_refs=(reference,),
            grounding_trace_id=trace_id,
        ),
        blockers=() if actionable else ("legal_action_mask_unknown",),
    )


def test_resolver_promotes_only_store_bound_trace_and_env(tmp_path: Path) -> None:
    store, capture_id, manifest_hash = _store(tmp_path)
    trace = _trace(capture_id, manifest_hash)
    draft = _env(capture_id, actionable=True)

    assert draft.actionable is False
    grounded = validate_grounding_trace_against_store(trace, store)
    validated = validate_env_observation_against_trace_and_store(draft, trace, store)

    assert grounded.promotable
    assert isinstance(validated, ValidatedEnvObservation)
    assert validated.actionable
    with pytest.raises(GroundingValidationError, match="resolver gate"):
        ValidatedEnvObservation(draft, grounded)


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
        validate_grounding_trace_against_store(
            _trace(capture_id, manifest_hash), store
        )


def test_env_resolver_rejects_nonexistent_trace_and_incomplete_actionability(
    tmp_path: Path,
) -> None:
    store, capture_id, manifest_hash = _store(tmp_path)
    trace = _trace(capture_id, manifest_hash)
    wrong_trace_draft = _env(
        capture_id,
        trace_id="trace-does-not-exist",
        actionable=True,
    )
    with pytest.raises(GroundingValidationError, match="nonexistent trace"):
        validate_env_observation_against_trace_and_store(
            wrong_trace_draft, trace, store
        )

    incomplete = _trace(
        capture_id,
        manifest_hash,
        status=GroundingTraceStatus.INCOMPLETE,
    )
    with pytest.raises(GroundingValidationError, match="blocked, non-actionable"):
        validate_env_observation_against_trace_and_store(
            _env(capture_id, actionable=True), incomplete, store
        )

    blocked = validate_env_observation_against_trace_and_store(
        _env(capture_id, actionable=False), incomplete, store
    )
    assert not blocked.actionable
