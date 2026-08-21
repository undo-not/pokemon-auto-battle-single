from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from champions_sim.core import canonical_json

from champions_sim.grounding import (
    AdbServerIdentity,
    AndroidClientBuild,
    CapturePayload,
    CaptureStore,
    ConformanceCheck,
    ConformanceVerdict,
    ExpectedSource,
    GroundedField,
    GroundingCategory,
    GroundingCoverageError,
    GroundingEvidenceMethod,
    GroundingExpectationError,
    GroundingExpectedLocator,
    GroundingFrame,
    GroundingLineageReceipt,
    GroundingPartition,
    GroundingPlan,
    GroundingPlanError,
    GroundingRequirement,
    GroundingSource,
    GroundingStatus,
    GroundingTrace,
    GroundingTraceStatus,
    ResolvedGroundingPlan,
    load_grounding_plan,
    load_grounding_lineage_receipt,
    grounding_plan_seal_marker,
    resolve_grounding_expectations,
    resolve_material_behavior_catalog,
    validate_complete_grounding_coverage,
    validate_complete_grounding_environment,
    validate_grounding_plan_pair,
    validate_grounding_trace_against_store,
)
from champions_sim.grounding.seal import _verify_grounding_plan_seal_payload
from champions_sim.showdown import ShowdownClient, ShowdownReplay


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
CLIENT_BUILD = AndroidClientBuild(
    version_code=2026082101,
    version_name="1.0.0-test",
    apk_count=1,
    apk_set_sha256="sha256:" + "9" * 64,
)
_UNSET = object()
PUBLIC_LOG = [
    "|turn|1",
    "|-mega|p1a: Charizard|Charizard-Mega-X|Charizardite X",
    "|move|p1a: Charizard|Dragon Pulse|p2a: Gengar",
    "|-damage|p2a: Gengar|57/100",
    "|move|p2a: Gengar|Hypnosis|p1a: Charizard",
    "|-miss|p2a: Gengar|p1a: Charizard",
]
ROUNDING_VISIBLE_LOG = [
    "|turn|2",
    "|move|p2a: Raticate|Super Fang|p1a: Target",
    "|-damage|p1a: Target|61/121",
]


def _replay(partition: GroundingPartition) -> ShowdownReplay:
    seed_digit = "1" if partition is GroundingPartition.DEVELOPMENT else "2"
    return ShowdownReplay.from_mapping(
        {
            "schema_version": "1.0.0",
            "format_id": "gen9championsbssregmb",
            "seed": "sodium," + seed_digit * 64,
            "input_log": [],
            "public_log": PUBLIC_LOG,
            "ended": False,
            "winner": None,
            "turns": 0,
            "score": None,
        },
        engine={
            "artifact_id": "test-showdown",
            "repository_url": "https://example.invalid/showdown.git",
            "commit": "1" * 40,
            "tree": "2" * 40,
            "build_fingerprint_sha256": "3" * 64,
            "manifest_sha256": "a" * 64,
            "node_version": "v24.0.0",
            "license": "MIT",
            "bridge_protocol_version": "1.0.0",
            "bridge_sha256": "4" * 64,
        },
    )


class _ReplayClient(ShowdownClient):
    def __init__(
        self,
        replay: ShowdownReplay,
        *,
        rounding_visible_log: list[str] | None = None,
    ) -> None:
        self._test_replay = replay
        self._rounding_visible_log = (
            ROUNDING_VISIBLE_LOG
            if rounding_visible_log is None
            else rounding_visible_log
        )

    def resolve_replay_expectations(self, replay, selectors):
        assert replay == self._test_replay.to_dict()
        values = {}
        for selector in selectors:
            pointer = selector["pointer"]
            if pointer == "/request/maxChosenTeamSize":
                value = 3
            elif pointer == "/legal_actions":
                value = ["move 1", "move 2"]
            elif pointer.endswith("/condition"):
                value = "61/121"
            elif pointer.endswith("/ident"):
                value = "p1: Target"
            elif pointer == "/visible_log":
                value = self._rounding_visible_log
            else:
                raise AssertionError(f"unexpected selector pointer: {pointer}")
            values[selector["selector_id"]] = value
        return self._test_replay, values


def _lineage_receipt(
    tmp_path: Path,
    partition: GroundingPartition,
    store: CaptureStore,
    *,
    replay_source_sha256: str,
):
    suffix = partition.value
    receipt = GroundingLineageReceipt(
        schema_version="1.0.0",
        lineage_id=f"lineage-{suffix}",
        issue_url=ISSUE_URL,
        regulation_id="champions-m-b",
        format_id="gen9championsbssregmb",
        partition=suffix,
        capture_store_id=store.store_id,
        capture_store_identity_sha256=store.identity_hash,
        source_artifact_sha256=(replay_source_sha256,),
        source_store_identity_sha256="sha256:"
        + ("3" if partition is GroundingPartition.DEVELOPMENT else "4") * 64,
        collected_at="2026-08-21T07:50:00Z",
        collection_method="private-friend-match-manual-observation",
        collector_id=f"collector-{suffix}",
        author_id=f"author-{suffix}",
        executor_id=f"executor-{suffix}",
        independence_attested=True,
        local_research_only=True,
        distribution_allowed=False,
    )
    path = tmp_path / f"{suffix}-lineage.json"
    path.write_text(canonical_json(receipt), encoding="utf-8")
    return load_grounding_lineage_receipt(path)


def _plan(
    tmp_path: Path,
    partition: GroundingPartition,
) -> ResolvedGroundingPlan:
    suffix = partition.value
    replay = _replay(partition)
    replay_path = tmp_path / f"{suffix}-replay.json"
    replay_bytes = canonical_json(replay.to_dict()).encode("utf-8")
    replay_path.write_bytes(replay_bytes)
    catalog = resolve_material_behavior_catalog(
        "champions-m-b", "gen9championsbssregmb"
    )
    expected_by_id = {
        "event-order-public-sequence": PUBLIC_LOG,
        "legal-action-player-request": ["move 1", "move 2"],
        "mega-evolution-order": PUBLIC_LOG,
        "rng-boundary-public-outcome": PUBLIC_LOG,
        "rounding-visible-hp": "61/121",
        "simultaneous-interaction-order": PUBLIC_LOG,
        "team-preview-max-selected": 3,
        "ui-private-friend-match": "private_friend_match",
    }
    pointer_by_id = {
        "event-order-public-sequence": "/public_log",
        "legal-action-player-request": "/legal_actions",
        "mega-evolution-order": "/public_log",
        "rng-boundary-public-outcome": "/public_log",
        "rounding-visible-hp": "/request/side/pokemon/0/condition",
        "simultaneous-interaction-order": "/public_log",
        "team-preview-max-selected": "/request/maxChosenTeamSize",
    }
    store = CaptureStore(
        tmp_path / suffix,
        store_id=f"{suffix}-captures",
        partition=suffix,
    )
    lineage = _lineage_receipt(
        tmp_path,
        partition,
        store,
        replay_source_sha256="sha256:" + hashlib.sha256(replay_bytes).hexdigest(),
    )
    plan = GroundingPlan(
        schema_version="1.0.0",
        plan_id=f"m-b-{suffix}-plan",
        issue_url=ISSUE_URL,
        seal_actor="undo-not",
        regulation_id="champions-m-b",
        format_id="gen9championsbssregmb",
        material_behavior_catalog_id=catalog.catalog_id,
        material_behavior_catalog_sha256=catalog.catalog_hash,
        target_package=TARGET_PACKAGE,
        client_build=CLIENT_BUILD,
        engine_manifest_sha256="sha256:" + "a" * 64,
        partition=partition,
        capture_store_id=f"{suffix}-captures",
        capture_store_identity_sha256=store.identity_hash,
        sealed_at="2026-08-21T08:00:00Z",
        lineage_receipt_sha256=lineage.receipt_sha256,
        requirements=tuple(
            GroundingRequirement(
                requirement_id=behavior.behavior_id,
                category=GroundingCategory(behavior.category),
                path=behavior.path,
                evidence_method=GroundingEvidenceMethod(behavior.evidence_method),
                expected_source=ExpectedSource(behavior.expected_source),
                expected=expected_by_id[behavior.behavior_id],
                reference_replay_hash=(
                    None
                    if behavior.behavior_id == "ui-private-friend-match"
                    else replay.replay_hash
                ),
                expected_locator=(
                    None
                    if behavior.behavior_id == "ui-private-friend-match"
                    else GroundingExpectedLocator(
                        pointer=pointer_by_id[behavior.behavior_id],
                        player=(
                            "p1"
                            if behavior.expected_source == "showdown_request"
                            else None
                        ),
                        revision=(
                            0
                            if behavior.behavior_id == "team-preview-max-selected"
                            else (
                                2
                                if behavior.behavior_id
                                == "legal-action-player-request"
                                else (
                                    4
                                    if behavior.behavior_id
                                    == "rounding-visible-hp"
                                    else None
                                )
                            )
                        ),
                    )
                ),
                rationale="Required material behavior from the active catalog.",
            )
            for behavior in catalog.behaviors
        ),
        exclusions=(),
        local_research_only=True,
        distribution_allowed=False,
    )
    path = tmp_path / f"{suffix}-plan.json"
    path.write_text(canonical_json(plan), encoding="utf-8")
    return load_grounding_plan(path)


def _lineage_for(plan: ResolvedGroundingPlan):
    return load_grounding_lineage_receipt(
        plan.source_path.parent / f"{plan.plan.partition.value}-lineage.json"
    )


def _validated_trace(
    tmp_path: Path,
    plan: ResolvedGroundingPlan,
    *,
    requirement_index: int = 0,
    expected: Any = _UNSET,
    captured_at: str | None = None,
    authorization_granted_at: str = "2026-08-21T08:05:00Z",
    check_path: str | None = None,
    shared_artifacts: bool = False,
    split_check_artifacts: bool = False,
):
    requirement = plan.plan.requirements[requirement_index]
    expected_value = requirement.expected if expected is _UNSET else expected
    asserted_path = requirement.path if check_path is None else check_path
    captured_at = captured_at or f"2026-08-21T08:30:{requirement_index:02d}Z"
    plan_seal = _seal(plan)
    authorization_path = tmp_path / f"authorization-{plan.plan.partition.value}.json"
    authorization_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "authorization_id": f"authorization-{plan.plan.partition.value}",
                "issue_url": ISSUE_URL,
                "granted_by": "test-operator",
                "granted_at": authorization_granted_at,
                "expires_at": "2026-08-21T09:00:00Z",
                "format_id": plan.plan.format_id,
                "plan_id": plan.plan.plan_id,
                "plan_hash": plan.plan_hash,
                "lineage_receipt_sha256": plan.plan.lineage_receipt_sha256,
                "plan_seal_comment_url": plan_seal.comment_url,
                "plan_seal_receipt_sha256": plan_seal.receipt_sha256,
                "partition": plan.plan.partition.value,
                "instance_name": "Pie64",
                "target_package": TARGET_PACKAGE,
                "client_build": CLIENT_BUILD.to_dict(),
                "capture_store_id": plan.plan.capture_store_id,
                "capture_store_identity_sha256": (
                    plan.plan.capture_store_identity_sha256
                ),
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
    store = CaptureStore(
        tmp_path / plan.plan.partition.value,
        store_id=plan.plan.capture_store_id,
        partition=plan.plan.partition.value,
    )
    manifest = store.save(
        CapturePayload(
            instance_name="Pie64",
            adb_serial="127.0.0.1:5555",
            captured_at=captured_at,
            ui_hierarchy_before_captured_at=captured_at,
            screenshot_captured_at=captured_at,
            ui_hierarchy_captured_at=captured_at,
            format_id=plan.plan.format_id,
            plan_id=plan.plan.plan_id,
            plan_hash=plan.plan_hash,
            lineage_receipt_sha256=plan.plan.lineage_receipt_sha256,
            plan_seal_comment_url=plan_seal.comment_url,
            plan_seal_receipt_sha256=plan_seal.receipt_sha256,
            partition=plan.plan.partition.value,
            target_package=TARGET_PACKAGE,
            client_build=CLIENT_BUILD,
            capture_store_id=plan.plan.capture_store_id,
            capture_store_identity_sha256=(
                plan.plan.capture_store_identity_sha256
            ),
            authorization_id=f"authorization-{plan.plan.partition.value}",
            authorization_sha256=authorization_hash,
            adb_server_ownership_verified=True,
            adb_server=AdbServerIdentity(
                host="127.0.0.1",
                port=5037,
                process_id=4321,
                process_started_at="2026-08-21T08:15:00Z",
                executable_sha256="sha256:" + "c" * 64,
            ),
            screenshot_png=PNG,
            ui_hierarchy_before_xml=(
                XML
                if shared_artifacts
                else (
                    f'<?xml version="1.0"?><hierarchy partition="{plan.plan.partition.value}">'
                    f'<node package="{TARGET_PACKAGE}" resource-id="{requirement.requirement_id}"/>'
                    "</hierarchy>"
                ).encode("utf-8")
            ),
            ui_hierarchy_xml=(
                XML
                if shared_artifacts
                else (
                    f'<?xml version="1.0"?><hierarchy partition="{plan.plan.partition.value}">'
                    f'<node package="{TARGET_PACKAGE}" resource-id="{requirement.requirement_id}"/>'
                    "</hierarchy>"
                ).encode("utf-8")
            ),
        )
    )
    evidence_method = requirement.evidence_method
    combined_artifacts = {
        GroundingEvidenceMethod.SCREENSHOT: ("screenshot",),
        GroundingEvidenceMethod.UI_HIERARCHY: (
            "ui-hierarchy-before",
            "ui-hierarchy",
        ),
        GroundingEvidenceMethod.BOTH: (
            "screenshot",
            "ui-hierarchy-before",
            "ui-hierarchy",
        ),
    }[evidence_method]
    check_artifacts = (
        (("screenshot",), ("ui-hierarchy-before", "ui-hierarchy"))
        if split_check_artifacts
        else (combined_artifacts,)
    )
    frames = tuple(
        GroundingFrame(
            frame_id=f"frame-{plan.plan.partition.value}-{index}",
            capture_id=manifest.capture_id,
            capture_manifest_hash=store.manifest_hash(manifest.capture_id),
            observed_at=captured_at,
            fields=(
                GroundedField(
                    path=asserted_path,
                    status=GroundingStatus.OBSERVED,
                    source=GroundingSource.UI_METADATA,
                    value=expected_value,
                    confidence_ppm=1_000_000,
                    artifact_ids=artifacts,
                ),
            ),
            conformance=(
                ConformanceCheck(
                    path=asserted_path,
                    verdict=ConformanceVerdict.MATCH,
                    expected=expected_value,
                    observed=expected_value,
                    artifact_ids=artifacts,
                ),
            ),
        )
        for index, artifacts in enumerate(check_artifacts)
    )
    trace = GroundingTrace(
        schema_version="2.0.0",
        trace_id=f"trace-{plan.plan.partition.value}-{requirement.requirement_id}",
        plan_id=plan.plan.plan_id,
        plan_hash=plan.plan_hash,
        lineage_receipt_sha256=plan.plan.lineage_receipt_sha256,
        partition=plan.plan.partition.value,
        requirement_id=requirement.requirement_id,
        capture_store_id=plan.plan.capture_store_id,
        format_id=plan.plan.format_id,
        viewer="p1",
        reference_replay_hash=requirement.reference_replay_hash,
        frames=frames,
        status=GroundingTraceStatus.CONFORMANT,
        blockers=(),
        local_research_only=True,
        distribution_allowed=False,
    )
    return validate_grounding_trace_against_store(
        store.save_trace(trace),
        store,
        issue_url=ISSUE_URL,
        authorization_paths={authorization_hash: authorization_path},
    )


def _validated_traces(
    tmp_path: Path,
    plan: ResolvedGroundingPlan,
    *,
    shared_artifacts: bool = False,
):
    return [
        _validated_trace(
            tmp_path,
            plan,
            requirement_index=index,
            shared_artifacts=shared_artifacts,
        )
        for index in range(len(plan.plan.requirements))
    ]


def _expectations(plan: ResolvedGroundingPlan):
    replay = _replay(plan.plan.partition)
    replay_path = plan.source_path.parent / f"{plan.plan.partition.value}-replay.json"
    return resolve_grounding_expectations(
        plan,
        {replay.replay_hash: replay_path},
        client=_ReplayClient(replay),
    )


def _seal(plan: ResolvedGroundingPlan):
    comment_id = (
        1001
        if plan.plan.partition is GroundingPartition.DEVELOPMENT
        else 1002
    )
    comment_url = f"{ISSUE_URL}#issuecomment-{comment_id}"
    return _verify_grounding_plan_seal_payload(
        plan,
        {
            "id": comment_id,
            "html_url": comment_url,
            "issue_url": (
                "https://api.github.com/repos/undo-not/"
                "pokemon-auto-battle-single/issues/3"
            ),
            "user": {"login": "undo-not"},
            "author_association": "OWNER",
            "created_at": "2026-08-21T08:01:00Z",
            "updated_at": "2026-08-21T08:01:00Z",
            "body": grounding_plan_seal_marker(plan),
        },
        issue_url=ISSUE_URL,
        comment_url=comment_url,
        authorized_actor="undo-not",
    )


def test_complete_environment_requires_full_development_and_holdout_coverage(
    tmp_path: Path,
) -> None:
    development = _plan(tmp_path, GroundingPartition.DEVELOPMENT)
    holdout = _plan(tmp_path, GroundingPartition.HOLDOUT)
    plans = validate_grounding_plan_pair(
        development,
        holdout,
        development_lineage=_lineage_for(development),
        holdout_lineage=_lineage_for(holdout),
    )
    development_coverage = validate_complete_grounding_coverage(
        development,
        _seal(development),
        _expectations(development),
        _validated_traces(tmp_path, development),
    )
    holdout_coverage = validate_complete_grounding_coverage(
        holdout,
        _seal(holdout),
        _expectations(holdout),
        _validated_traces(tmp_path, holdout),
    )

    evidence = validate_complete_grounding_environment(
        plans, development_coverage, holdout_coverage
    )

    assert (
        evidence.development.evidence[0].requirement_id
        == "event-order-public-sequence"
    )
    assert evidence.holdout.evidence[0].trace_hash.startswith("sha256:")


def test_coverage_rejects_missing_or_plan_drifted_evidence(tmp_path: Path) -> None:
    development = _plan(tmp_path, GroundingPartition.DEVELOPMENT)

    with pytest.raises(
        GroundingCoverageError, match="missing=event-order-public-sequence"
    ):
        validate_complete_grounding_coverage(
            development, _seal(development), _expectations(development), []
        )

    drifted = _validated_trace(tmp_path, development, expected=2)
    with pytest.raises(GroundingCoverageError, match="expected value differs"):
        validate_complete_grounding_coverage(
            development, _seal(development), _expectations(development), [drifted]
        )

    presealed = _validated_trace(
        tmp_path,
        development,
        captured_at="2026-08-21T07:59:59Z",
        authorization_granted_at="2026-08-21T07:00:00Z",
    )
    with pytest.raises(GroundingCoverageError, match="predates the live GitHub"):
        validate_complete_grounding_coverage(
            development, _seal(development), _expectations(development), [presealed]
        )

    extra_path = _validated_trace(
        tmp_path,
        development,
        captured_at="2026-08-21T08:31:00Z",
        check_path="/other",
    )
    with pytest.raises(GroundingCoverageError, match="outside its planned requirement"):
        validate_complete_grounding_coverage(
            development, _seal(development), _expectations(development), [extra_path]
        )


def test_environment_rejects_lineage_source_that_differs_from_replay_bytes(
    tmp_path: Path,
) -> None:
    development = _plan(tmp_path, GroundingPartition.DEVELOPMENT)
    holdout = _plan(tmp_path, GroundingPartition.HOLDOUT)
    plans = validate_grounding_plan_pair(
        development,
        holdout,
        development_lineage=_lineage_for(development),
        holdout_lineage=_lineage_for(holdout),
    )
    replay_path = development.source_path.parent / "development-replay.json"
    replay_path.write_bytes(replay_path.read_bytes() + b"\n")
    development_coverage = validate_complete_grounding_coverage(
        development,
        _seal(development),
        _expectations(development),
        _validated_traces(tmp_path, development),
    )
    holdout_coverage = validate_complete_grounding_coverage(
        holdout,
        _seal(holdout),
        _expectations(holdout),
        _validated_traces(tmp_path, holdout),
    )

    with pytest.raises(GroundingPlanError, match="do not match resolved Replay bytes"):
        validate_complete_grounding_environment(
            plans,
            development_coverage,
            holdout_coverage,
        )


@pytest.mark.parametrize(
    "unrelated_history",
    (
        [
            "|turn|2",
            "|move|p2a: Raticate|Hyper Fang|p1a: Target",
            "|-damage|p1a: Target|61/121",
        ],
        [
            "|turn|2",
            "|move|p2a: Raticate|Super Fang|p1a: Target",
            "|-miss|p2a: Raticate|p1a: Target",
            "|-damage|p1a: Target|61/121|[from] psn",
        ],
    ),
)
def test_rounding_expectation_requires_direct_super_fang_target_damage(
    tmp_path: Path,
    unrelated_history: list[str],
) -> None:
    development = _plan(tmp_path, GroundingPartition.DEVELOPMENT)
    replay = _replay(GroundingPartition.DEVELOPMENT)
    replay_path = development.source_path.parent / "development-replay.json"
    with pytest.raises(GroundingExpectationError, match="Super Fang transition"):
        resolve_grounding_expectations(
            development,
            {replay.replay_hash: replay_path},
            client=_ReplayClient(
                replay,
                rounding_visible_log=unrelated_history,
            ),
        )


def test_environment_allows_equal_static_ui_bytes_with_independent_provenance(
    tmp_path: Path,
) -> None:
    development = _plan(tmp_path, GroundingPartition.DEVELOPMENT)
    holdout = _plan(tmp_path, GroundingPartition.HOLDOUT)
    plans = validate_grounding_plan_pair(
        development,
        holdout,
        development_lineage=_lineage_for(development),
        holdout_lineage=_lineage_for(holdout),
    )
    development_coverage = validate_complete_grounding_coverage(
        development,
        _seal(development),
        _expectations(development),
        _validated_traces(tmp_path, development, shared_artifacts=True),
    )
    holdout_coverage = validate_complete_grounding_coverage(
        holdout,
        _seal(holdout),
        _expectations(holdout),
        _validated_traces(tmp_path, holdout, shared_artifacts=True),
    )

    evidence = validate_complete_grounding_environment(
        plans,
        development_coverage,
        holdout_coverage,
    )

    assert evidence.development.artifact_sha256 & evidence.holdout.artifact_sha256
    assert not (
        evidence.development.capture_ids & evidence.holdout.capture_ids
    )
    assert not (
        evidence.development.capture_manifest_sha256
        & evidence.holdout.capture_manifest_sha256
    )


def test_both_evidence_method_cannot_be_assembled_across_checks(
    tmp_path: Path,
) -> None:
    development = _plan(tmp_path, GroundingPartition.DEVELOPMENT)
    split = _validated_trace(
        tmp_path,
        development,
        split_check_artifacts=True,
    )

    with pytest.raises(GroundingCoverageError, match="planned evidence method"):
        validate_complete_grounding_coverage(
            development, _seal(development), _expectations(development), [split]
        )
