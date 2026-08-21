from __future__ import annotations

import json
from pathlib import Path

import pytest

import champions_sim.grounding.seal as seal_module
from champions_sim.core import canonical_json
from champions_sim.grounding import (
    AndroidClientBuild,
    ExpectedSource,
    GroundingCategory,
    GroundingEvidenceMethod,
    GroundingExpectedLocator,
    GroundingPartition,
    GroundingPlan,
    GroundingPlanSealError,
    GroundingRequirement,
    VerifiedGroundingPlanSeal,
    grounding_plan_seal_marker,
    load_grounding_plan,
    resolve_material_behavior_catalog,
    verify_grounding_plan_seal,
)


ISSUE_URL = "https://github.com/undo-not/pokemon-auto-battle-single/issues/3"
COMMENT_URL = ISSUE_URL + "#issuecomment-123"
API_URL = (
    "https://api.github.com/repos/undo-not/"
    "pokemon-auto-battle-single/issues/comments/123"
)


def _plan(tmp_path: Path):
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
    expected_by_id = {
        "event-order-public-sequence": public_log,
        "legal-action-player-request": ["move 1"],
        "mega-evolution-order": public_log,
        "rng-boundary-public-outcome": public_log,
        "rounding-visible-hp": "61/121",
        "simultaneous-interaction-order": public_log,
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
    plan = GroundingPlan(
        schema_version="1.0.0",
        plan_id="seal-development-plan",
        issue_url=ISSUE_URL,
        seal_actor="undo-not",
        regulation_id="champions-m-b",
        format_id="gen9championsbssregmb",
        material_behavior_catalog_id=catalog.catalog_id,
        material_behavior_catalog_sha256=catalog.catalog_hash,
        target_package="com.pokemon.champions",
        client_build=AndroidClientBuild(
            version_code=2026082101,
            version_name="1.0.0-test",
            apk_count=1,
            apk_set_sha256="sha256:" + "9" * 64,
        ),
        engine_manifest_sha256="sha256:" + "a" * 64,
        partition=GroundingPartition.DEVELOPMENT,
        capture_store_id="seal-development-captures",
        capture_store_identity_sha256="sha256:" + "b" * 64,
        sealed_at="2026-08-21T08:00:00Z",
        lineage_receipt_sha256="sha256:" + "d" * 64,
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
                    else "c" * 64
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
                                4
                                if behavior.behavior_id == "rounding-visible-hp"
                                else 2
                                if behavior.behavior_id
                                == "legal-action-player-request"
                                else None
                            )
                        ),
                    )
                ),
                rationale="Affirmatively identify the private friend match.",
            )
            for behavior in catalog.behaviors
        ),
        exclusions=(),
        local_research_only=True,
        distribution_allowed=False,
    )
    path = tmp_path / "seal-plan.json"
    path.write_text(canonical_json(plan), encoding="utf-8")
    return load_grounding_plan(path)


def _comment(plan, **overrides):
    value = {
        "id": 123,
        "html_url": COMMENT_URL,
        "issue_url": (
            "https://api.github.com/repos/undo-not/"
            "pokemon-auto-battle-single/issues/3"
        ),
        "user": {"login": "undo-not"},
        "author_association": "OWNER",
        "created_at": "2026-08-21T08:01:00Z",
        "updated_at": "2026-08-21T08:01:00Z",
        "body": grounding_plan_seal_marker(plan),
    }
    value.update(overrides)
    return value


class _Response:
    status = 200

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, _type, _value, _traceback) -> None:
        return None

    def geturl(self) -> str:
        return API_URL

    def read(self, _maximum: int) -> bytes:
        return self._payload


def test_live_unedited_github_comment_seals_exact_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(tmp_path)
    payload = json.dumps(_comment(plan)).encode("utf-8")

    def fake_urlopen(request, *, timeout):
        assert request.full_url == API_URL
        assert timeout == 10
        return _Response(payload)

    monkeypatch.setattr(seal_module, "urlopen", fake_urlopen)
    seal = verify_grounding_plan_seal(
        plan,
        issue_url=ISSUE_URL,
        comment_url=COMMENT_URL,
        authorized_actor="undo-not",
    )

    assert seal.plan_hash == plan.plan_hash
    assert seal.comment_id == 123
    assert seal.receipt_sha256.startswith("sha256:")


@pytest.mark.parametrize(
    "overrides",
    [
        {"updated_at": "2026-08-21T08:02:00Z"},
        {"body": "grounding-plan-seal-v1 forged"},
        {"user": {"login": "another-user"}},
        {"created_at": "2026-08-21T07:59:59Z", "updated_at": "2026-08-21T07:59:59Z"},
    ],
)
def test_plan_seal_rejects_edited_forged_or_backdated_comment(
    tmp_path: Path,
    overrides: dict[str, object],
) -> None:
    plan = _plan(tmp_path)

    with pytest.raises(GroundingPlanSealError):
        seal_module._verify_grounding_plan_seal_payload(
            plan,
            _comment(plan, **overrides),
            issue_url=ISSUE_URL,
            comment_url=COMMENT_URL,
            authorized_actor="undo-not",
        )


def test_plan_seal_rejects_a_comment_with_any_second_marker(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    body = grounding_plan_seal_marker(plan) + "\ngrounding-plan-seal-v1 second"

    with pytest.raises(GroundingPlanSealError, match="exact plan seal"):
        seal_module._verify_grounding_plan_seal_payload(
            plan,
            _comment(plan, body=body),
            issue_url=ISSUE_URL,
            comment_url=COMMENT_URL,
            authorized_actor="undo-not",
        )


def test_verified_plan_seal_cannot_be_constructed_directly() -> None:
    with pytest.raises(GroundingPlanSealError, match="live GitHub receipt"):
        VerifiedGroundingPlanSeal(
            plan_id="forged",
            plan_hash="sha256:" + "a" * 64,
            partition="development",
            issue_url=ISSUE_URL,
            comment_url=COMMENT_URL,
            comment_id=123,
            actor="undo-not",
            created_at="2026-08-21T08:01:00Z",
            receipt_sha256="sha256:" + "b" * 64,
        )
