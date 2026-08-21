from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from champions_sim.grounding import (
    GroundingPlanError,
    load_grounding_plan,
    load_grounding_lineage_receipt,
    resolve_material_behavior_catalog,
    validate_grounding_plan_pair,
)
from champions_sim.core import canonical_json


ROOT = Path(__file__).resolve().parents[1]


def _lineage_document(*, partition: str) -> dict[str, object]:
    suffix = "dev" if partition == "development" else "holdout"
    return {
        "schema_version": "1.0.0",
        "lineage_id": f"lineage-{suffix}",
        "issue_url": "https://github.com/undo-not/pokemon-auto-battle-single/issues/3",
        "regulation_id": "champions-m-b",
        "format_id": "gen9championsbssregmb",
        "partition": partition,
        "capture_store_id": f"{suffix}-captures",
        "capture_store_identity_sha256": "sha256:"
        + ("1" if partition == "development" else "2") * 64,
        "source_artifact_sha256": [
            "sha256:" + ("3" if partition == "development" else "4") * 64
        ],
        "source_store_identity_sha256": "sha256:"
        + ("5" if partition == "development" else "6") * 64,
        "collected_at": "2026-08-21T07:50:00Z",
        "collection_method": "private-friend-match-manual-observation",
        "collector_id": f"collector-{suffix}",
        "author_id": f"author-{suffix}",
        "executor_id": f"executor-{suffix}",
        "independence_attested": True,
        "local_research_only": True,
        "distribution_allowed": False,
    }


def _lineage_hash(partition: str) -> str:
    payload = canonical_json(_lineage_document(partition=partition)).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _lineage(tmp_path: Path, partition: str, *, name: str | None = None):
    path = tmp_path / (name or f"{partition}-lineage.json")
    path.write_text(
        canonical_json(_lineage_document(partition=partition)), encoding="utf-8"
    )
    return load_grounding_lineage_receipt(path)


def _document(*, partition: str) -> dict[str, object]:
    suffix = "dev" if partition == "development" else "holdout"
    replay_hash = ("b" if partition == "development" else "d") * 64
    catalog = resolve_material_behavior_catalog(
        "champions-m-b", "gen9championsbssregmb"
    )
    public_log = [
        "|turn|1",
        "|-mega|p1a: Charizard|Charizard-Mega-X|Charizardite X",
        "|move|p1a: Charizard|Dragon Pulse|p2a: Gengar",
        "|-damage|p2a: Gengar|57/100",
        "|move|p2a: Gengar|Hypnosis|p1a: Charizard",
        "|-miss|p2a: Gengar|p1a: Charizard",
    ]
    public_requirements = (
        (
            "event-order-public-sequence",
            "event_order",
            "/battle/event_order",
            public_log,
            "/public_log",
        ),
        (
            "mega-evolution-order",
            "mega_evolution",
            "/battle/mega_evolution",
            public_log,
            "/public_log",
        ),
        (
            "rng-boundary-public-outcome",
            "rng_boundary",
            "/battle/rng_boundary",
            public_log,
            "/public_log",
        ),
        (
            "simultaneous-interaction-order",
            "simultaneous_interaction",
            "/battle/simultaneous_interaction",
            public_log,
            "/public_log",
        ),
    )
    requirements = [
        {
            "requirement_id": behavior_id,
            "category": category,
            "path": path,
            "evidence_method": "screenshot_and_ui_hierarchy",
            "expected_source": "showdown_public_log",
            "expected": expected,
            "reference_replay_hash": replay_hash,
            "expected_locator": {
                "pointer": pointer,
                "player": None,
                "revision": None,
            },
            "rationale": "The public event must match the pinned Replay.",
        }
        for behavior_id, category, path, expected, pointer in public_requirements
    ]
    requirements.extend(
        (
            {
                "requirement_id": "legal-action-player-request",
                "category": "legal_action",
                "path": "/battle/legal_actions",
                "evidence_method": "screenshot_and_ui_hierarchy",
                "expected_source": "showdown_request",
                "expected": ["move 1", "move 2"],
                "reference_replay_hash": replay_hash,
                "expected_locator": {
                    "pointer": "/legal_actions",
                    "player": "p1",
                    "revision": 2,
                },
                "rationale": "The player must see the same legal action surface.",
            },
            {
                "requirement_id": "team-preview-max-selected",
                "category": "team_preview",
                "path": "/battle/team_preview",
                "evidence_method": "screenshot_and_ui_hierarchy",
                "expected_source": "showdown_request",
                "expected": 3,
                "reference_replay_hash": replay_hash,
                "expected_locator": {
                    "pointer": "/request/maxChosenTeamSize",
                    "player": "p1",
                    "revision": 0,
                },
                "rationale": "M-B singles uses ordered 6-to-3 selection.",
            },
            {
                "requirement_id": "rounding-visible-hp",
                "category": "rounding",
                "path": "/battle/rounding",
                "evidence_method": "screenshot_and_ui_hierarchy",
                "expected_source": "showdown_request",
                "expected": "61/121",
                "reference_replay_hash": replay_hash,
                "expected_locator": {
                    "pointer": "/request/side/pokemon/0/condition",
                    "player": "p1",
                    "revision": 4,
                },
                "rationale": "Super Fang on odd maximum HP rounds damage down.",
            },
            {
                "requirement_id": "ui-private-friend-match",
                "category": "ui_observation",
                "path": "/client/match_kind",
                "evidence_method": "screenshot_and_ui_hierarchy",
                "expected_source": "manual_scope",
                "expected": "private_friend_match",
                "reference_replay_hash": None,
                "expected_locator": None,
                "rationale": "The capture must identify a private friend match.",
            },
        )
    )
    requirements.sort(key=lambda value: value["requirement_id"])
    return {
        "schema_version": "1.0.0",
        "plan_id": f"m-b-grounding-{suffix}",
        "issue_url": "https://github.com/undo-not/pokemon-auto-battle-single/issues/3",
        "seal_actor": "undo-not",
        "regulation_id": "champions-m-b",
        "format_id": "gen9championsbssregmb",
        "material_behavior_catalog_id": catalog.catalog_id,
        "material_behavior_catalog_sha256": catalog.catalog_hash,
        "target_package": "com.pokemon.champions",
        "client_build": {
            "version_code": 2026082101,
            "version_name": "1.0.0-test",
            "apk_count": 1,
            "apk_set_sha256": "sha256:" + "9" * 64,
        },
        "engine_manifest_sha256": "sha256:" + "a" * 64,
        "partition": partition,
        "capture_store_id": f"{suffix}-captures",
        "capture_store_identity_sha256": "sha256:"
        + ("1" if partition == "development" else "2") * 64,
        "sealed_at": "2026-08-21T08:00:00Z",
        "lineage_receipt_sha256": _lineage_hash(partition),
        "requirements": requirements,
        "exclusions": [],
        "local_research_only": True,
        "distribution_allowed": False,
    }


def _write(tmp_path: Path, name: str, document: dict[str, object]) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _pair(tmp_path: Path, development, holdout):
    return validate_grounding_plan_pair(
        development,
        holdout,
        development_lineage=_lineage(tmp_path, "development"),
        holdout_lineage=_lineage(tmp_path, "holdout"),
    )


def test_external_grounding_plans_freeze_equal_denominators_and_independent_lineage(
    tmp_path: Path,
) -> None:
    development_document = _document(partition="development")
    holdout_document = _document(partition="holdout")
    development = load_grounding_plan(
        _write(tmp_path, "development-plan.json", development_document)
    )
    holdout = load_grounding_plan(_write(tmp_path, "holdout-plan.json", holdout_document))

    pair = _pair(tmp_path, development, holdout)

    assert (
        pair.development.plan.requirements[0].expected
        == pair.holdout.plan.requirements[0].expected
    )
    assert (
        pair.development.plan.requirements[0].reference_replay_hash
        != pair.holdout.plan.requirements[0].reference_replay_hash
    )
    assert development.plan_hash.startswith("sha256:")
    assert holdout.plan_hash.startswith("sha256:")
    assert development.plan_hash != holdout.plan_hash
    schema = json.loads(
        (ROOT / "data/schemas/grounding-plan.schema.json").read_text(encoding="utf-8")
    )
    validator = Draft202012Validator(schema)
    validator.validate(development_document)
    validator.validate(holdout_document)
    invented = _document(partition="development")
    invented["requirements"][0]["requirement_id"] = "placeholder-event-order"
    assert not validator.is_valid(invented)


def test_plan_pair_requires_the_same_exact_client_build(tmp_path: Path) -> None:
    development = load_grounding_plan(
        _write(tmp_path, "development-plan.json", _document(partition="development"))
    )
    holdout_document = _document(partition="holdout")
    holdout_document["client_build"]["version_code"] += 1
    holdout = load_grounding_plan(
        _write(tmp_path, "holdout-plan.json", holdout_document)
    )

    with pytest.raises(GroundingPlanError, match="client_build"):
        _pair(tmp_path, development, holdout)


def test_plan_pair_rejects_each_lineage_overlap_and_denominator_drift(
    tmp_path: Path,
) -> None:
    development = load_grounding_plan(
        _write(tmp_path, "development-plan.json", _document(partition="development"))
    )

    development_lineage = _lineage(tmp_path, "development")
    for field_name in ("collector_id", "author_id", "executor_id"):
        lineage_document = _lineage_document(partition="holdout")
        lineage_document[field_name] = getattr(
            development_lineage.receipt, field_name
        )
        lineage_path = tmp_path / f"holdout-{field_name}-lineage.json"
        lineage_path.write_text(canonical_json(lineage_document), encoding="utf-8")
        holdout_lineage = load_grounding_lineage_receipt(lineage_path)
        holdout_document = _document(partition="holdout")
        holdout_document["lineage_receipt_sha256"] = (
            holdout_lineage.receipt_sha256
        )
        holdout = load_grounding_plan(
            _write(tmp_path, f"holdout-{field_name}.json", holdout_document)
        )
        with pytest.raises(GroundingPlanError, match="identities overlap"):
            validate_grounding_plan_pair(
                development,
                holdout,
                development_lineage=development_lineage,
                holdout_lineage=holdout_lineage,
            )

    source_overlap_document = _lineage_document(partition="holdout")
    source_overlap_document["source_artifact_sha256"] = list(
        development_lineage.receipt.source_artifact_sha256
    )
    source_overlap_path = tmp_path / "holdout-source-overlap-lineage.json"
    source_overlap_path.write_text(
        canonical_json(source_overlap_document), encoding="utf-8"
    )
    source_overlap_lineage = load_grounding_lineage_receipt(source_overlap_path)
    source_overlap_plan = _document(partition="holdout")
    source_overlap_plan["lineage_receipt_sha256"] = (
        source_overlap_lineage.receipt_sha256
    )
    holdout = load_grounding_plan(
        _write(tmp_path, "holdout-source-overlap.json", source_overlap_plan)
    )
    with pytest.raises(GroundingPlanError, match="source artifacts overlap"):
        validate_grounding_plan_pair(
            development,
            holdout,
            development_lineage=development_lineage,
            holdout_lineage=source_overlap_lineage,
        )

    drifted = _document(partition="holdout")
    drifted["requirements"][0]["expected"] = [
        "|turn|2",
        "|move|p1a: Charizard|Protect|p1a: Charizard",
    ]
    holdout = load_grounding_plan(_write(tmp_path, "holdout-drift.json", drifted))
    with pytest.raises(GroundingPlanError, match="denominators must be identical"):
        _pair(tmp_path, development, holdout)

    one_action_document = _document(partition="development")
    one_action_document["requirements"][1]["expected"] = ["move 1"]
    one_action_development = load_grounding_plan(
        _write(tmp_path, "development-one-action.json", one_action_document)
    )
    action_drift = _document(partition="holdout")
    action_drift["requirements"][1]["expected"] = ["move 1", "move 2"]
    holdout = load_grounding_plan(
        _write(tmp_path, "holdout-action-drift.json", action_drift)
    )
    with pytest.raises(GroundingPlanError, match="denominators must be identical"):
        _pair(tmp_path, one_action_development, holdout)

    replay_overlap = _document(partition="holdout")
    for requirement in replay_overlap["requirements"]:
        if requirement["reference_replay_hash"] is not None:
            requirement["reference_replay_hash"] = (
                development.plan.requirements[0].reference_replay_hash
            )
    holdout = load_grounding_plan(
        _write(tmp_path, "holdout-replay-overlap.json", replay_overlap)
    )
    with pytest.raises(GroundingPlanError, match="reuse Replay evidence"):
        _pair(tmp_path, development, holdout)

    physical_overlap = _document(partition="holdout")
    physical_overlap["capture_store_identity_sha256"] = (
        development.plan.capture_store_identity_sha256
    )
    holdout = load_grounding_plan(
        _write(tmp_path, "holdout-physical-overlap.json", physical_overlap)
    )
    with pytest.raises(GroundingPlanError, match="physical capture stores"):
        _pair(tmp_path, development, holdout)


def test_grounding_plan_rejects_repository_paths_duplicates_and_floats(
    tmp_path: Path,
) -> None:
    with pytest.raises(GroundingPlanError, match="outside the repository"):
        load_grounding_plan(ROOT / "data/schemas/grounding-plan.schema.json")

    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(
        '{"schema_version":"1.0.0","schema_version":"1.0.0"}',
        encoding="utf-8",
    )
    with pytest.raises(GroundingPlanError, match="duplicate JSON key"):
        load_grounding_plan(duplicate)

    float_document = _document(partition="development")
    float_document["requirements"][0]["expected"] = 0.5
    with pytest.raises(GroundingPlanError, match="not canonical"):
        load_grounding_plan(_write(tmp_path, "float-plan.json", float_document))


def test_grounding_plan_requires_every_material_category_and_showdown_rule_source(
    tmp_path: Path,
) -> None:
    missing = _document(partition="development")
    missing["requirements"] = [
        value for value in missing["requirements"] if value["category"] != "event_order"
    ]
    with pytest.raises(GroundingPlanError, match="event_order"):
        load_grounding_plan(_write(tmp_path, "missing-category.json", missing))

    manual_rule = _document(partition="development")
    manual_rule["requirements"][0]["expected_source"] = "manual_scope"
    with pytest.raises(GroundingPlanError, match="cannot establish battle-rule"):
        load_grounding_plan(_write(tmp_path, "manual-rule.json", manual_rule))

    ui_excluded = _document(partition="development")
    ui_excluded["requirements"] = [
        value
        for value in ui_excluded["requirements"]
        if value["category"] != "ui_observation"
    ]
    ui_excluded["exclusions"].append(
        {
            "behavior_id": "ui-private-friend-match",
            "category": "ui_observation",
            "basis": "out_of_scope",
            "reason": "A private-match candidate cannot rely on this exclusion.",
        }
    )
    ui_excluded["exclusions"].sort(key=lambda value: value["behavior_id"])
    with pytest.raises(GroundingPlanError, match="affirmative UI observation"):
        load_grounding_plan(_write(tmp_path, "ui-excluded.json", ui_excluded))

    placeholders = _document(partition="development")
    ui_requirement = next(
        value
        for value in placeholders["requirements"]
        if value["category"] == "ui_observation"
    )
    placeholders["requirements"] = [ui_requirement]
    placeholders["exclusions"] = [
        {
            "behavior_id": behavior.behavior_id,
            "category": behavior.category,
            "basis": "not_material",
            "reason": "Placeholder exclusion is not admissible.",
        }
        for behavior in resolve_material_behavior_catalog(
            "champions-m-b", "gen9championsbssregmb"
        ).behaviors
        if behavior.category != "ui_observation"
    ]
    with pytest.raises(GroundingPlanError, match="cannot be excluded"):
        load_grounding_plan(_write(tmp_path, "placeholder-plan.json", placeholders))


def test_grounding_plan_requires_scenario_bound_material_witnesses(
    tmp_path: Path,
) -> None:
    ranked_ui = _document(partition="development")
    next(
        value
        for value in ranked_ui["requirements"]
        if value["requirement_id"] == "ui-private-friend-match"
    )["expected"] = "ranked_match"
    with pytest.raises(GroundingPlanError, match="required witness"):
        load_grounding_plan(_write(tmp_path, "ranked-ui.json", ranked_ui))

    arbitrary_mega = _document(partition="development")
    next(
        value
        for value in arbitrary_mega["requirements"]
        if value["requirement_id"] == "mega-evolution-order"
    )["expected"] = [
        "|turn|1",
        "|move|p1a: Charizard|Dragon Pulse|p2a: Gengar",
    ]
    with pytest.raises(GroundingPlanError, match="required witness"):
        load_grounding_plan(_write(tmp_path, "arbitrary-mega.json", arbitrary_mega))

    split_replays = _document(partition="development")
    next(
        value
        for value in split_replays["requirements"]
        if value["requirement_id"] == "legal-action-player-request"
    )["reference_replay_hash"] = "e" * 64
    with pytest.raises(GroundingPlanError, match="one scenario Replay"):
        load_grounding_plan(_write(tmp_path, "split-replays.json", split_replays))


def test_loaded_plan_expected_values_cannot_mutate_after_hashing(
    tmp_path: Path,
) -> None:
    plan = load_grounding_plan(
        _write(tmp_path, "immutable-plan.json", _document(partition="development"))
    )
    public_log = next(
        requirement.expected
        for requirement in plan.plan.requirements
        if requirement.requirement_id == "event-order-public-sequence"
    )

    assert isinstance(public_log, tuple)
    with pytest.raises(AttributeError):
        public_log.append("|turn|2")
