"""Third-party timestamp receipt for an external grounding denominator plan."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from champions_sim.core import canonical_json

from .plan import ResolvedGroundingPlan


_COMMENT_URL_RE = re.compile(
    r"^https://github\.com/(?P<owner>[A-Za-z0-9_.-]+)/"
    r"(?P<repo>[A-Za-z0-9_.-]+)/issues/(?P<issue>[1-9][0-9]*)"
    r"#issuecomment-(?P<comment>[1-9][0-9]*)$"
)
_MAX_COMMENT_BYTES = 512 * 1024
_TRUSTED_ASSOCIATIONS = {"OWNER", "MEMBER", "COLLABORATOR"}


class GroundingPlanSealError(ValueError):
    """Raised when a live GitHub plan-seal receipt cannot be trusted."""


_SEAL_TOKEN = object()


@dataclass(frozen=True, slots=True, init=False)
class VerifiedGroundingPlanSeal:
    plan_id: str
    plan_hash: str
    partition: str
    issue_url: str
    comment_url: str
    comment_id: int
    actor: str
    created_at: str
    receipt_sha256: str

    def __init__(
        self,
        *,
        plan_id: str,
        plan_hash: str,
        partition: str,
        issue_url: str,
        comment_url: str,
        comment_id: int,
        actor: str,
        created_at: str,
        receipt_sha256: str,
        _token: object | None = None,
    ) -> None:
        if _token is not _SEAL_TOKEN:
            raise GroundingPlanSealError(
                "verified plan seals must resolve from the live GitHub receipt"
            )
        object.__setattr__(self, "plan_id", plan_id)
        object.__setattr__(self, "plan_hash", plan_hash)
        object.__setattr__(self, "partition", partition)
        object.__setattr__(self, "issue_url", issue_url)
        object.__setattr__(self, "comment_url", comment_url)
        object.__setattr__(self, "comment_id", comment_id)
        object.__setattr__(self, "actor", actor)
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "receipt_sha256", receipt_sha256)


def grounding_plan_seal_marker(resolved_plan: ResolvedGroundingPlan) -> str:
    plan = resolved_plan.plan
    return "grounding-plan-seal-v1 " + canonical_json(
        {
            "partition": plan.partition.value,
            "plan_hash": resolved_plan.plan_hash,
            "plan_id": plan.plan_id,
        }
    )


def verify_grounding_plan_seal(
    resolved_plan: ResolvedGroundingPlan,
    *,
    issue_url: str,
    comment_url: str,
    authorized_actor: str,
) -> VerifiedGroundingPlanSeal:
    """Fetch and verify one unedited GitHub Issue comment as the plan seal."""

    if (
        issue_url != resolved_plan.plan.issue_url
        or authorized_actor != resolved_plan.plan.seal_actor
    ):
        raise GroundingPlanSealError(
            "plan-seal Issue or actor differs from the external plan"
        )
    match = _COMMENT_URL_RE.fullmatch(comment_url)
    if match is None:
        raise GroundingPlanSealError("plan seal must be a GitHub Issue comment URL")
    expected_issue_url = (
        f"https://github.com/{match.group('owner')}/{match.group('repo')}"
        f"/issues/{match.group('issue')}"
    )
    if issue_url != expected_issue_url:
        raise GroundingPlanSealError("plan seal comment does not belong to the Issue")
    if (
        not authorized_actor
        or len(authorized_actor) > 240
        or re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})", authorized_actor)
        is None
    ):
        raise GroundingPlanSealError("authorized_actor is not a GitHub login")
    api_url = (
        f"https://api.github.com/repos/{match.group('owner')}/{match.group('repo')}"
        f"/issues/comments/{match.group('comment')}"
    )
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "pokemon-auto-battle-single-grounding-seal/1",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(api_url, headers=headers, method="GET")
    try:
        with urlopen(request, timeout=10) as response:
            if response.status != 200 or response.geturl() != api_url:
                raise GroundingPlanSealError(
                    "GitHub plan-seal response identity is invalid"
                )
            payload = response.read(_MAX_COMMENT_BYTES + 1)
    except GroundingPlanSealError:
        raise
    except (HTTPError, URLError, OSError) as error:
        raise GroundingPlanSealError(
            f"cannot resolve live GitHub plan seal: {error}"
        ) from error
    if len(payload) > _MAX_COMMENT_BYTES:
        raise GroundingPlanSealError("GitHub plan-seal response is too large")
    try:
        raw = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_float=_reject_number,
            parse_constant=_reject_number,
        )
    except (UnicodeError, json.JSONDecodeError) as error:
        raise GroundingPlanSealError("GitHub plan-seal response is invalid JSON") from error
    return _verify_grounding_plan_seal_payload(
        resolved_plan,
        raw,
        issue_url=issue_url,
        comment_url=comment_url,
        authorized_actor=authorized_actor,
    )


def _verify_grounding_plan_seal_payload(
    resolved_plan: ResolvedGroundingPlan,
    raw: Any,
    *,
    issue_url: str,
    comment_url: str,
    authorized_actor: str,
) -> VerifiedGroundingPlanSeal:
    if not isinstance(raw, Mapping):
        raise GroundingPlanSealError("GitHub plan-seal response must be an object")
    if (
        issue_url != resolved_plan.plan.issue_url
        or authorized_actor != resolved_plan.plan.seal_actor
    ):
        raise GroundingPlanSealError(
            "plan-seal Issue or actor differs from the external plan"
        )
    match = _COMMENT_URL_RE.fullmatch(comment_url)
    if match is None:
        raise GroundingPlanSealError("plan seal must be a GitHub Issue comment URL")
    expected_issue_url = (
        f"https://github.com/{match.group('owner')}/{match.group('repo')}"
        f"/issues/{match.group('issue')}"
    )
    if issue_url != expected_issue_url:
        raise GroundingPlanSealError("plan seal comment does not belong to the Issue")
    if (
        not authorized_actor
        or len(authorized_actor) > 240
        or re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})", authorized_actor)
        is None
    ):
        raise GroundingPlanSealError("authorized_actor is not a GitHub login")
    comment_id = raw.get("id")
    user = raw.get("user")
    if not isinstance(comment_id, int) or isinstance(comment_id, bool):
        raise GroundingPlanSealError("GitHub plan-seal comment ID is invalid")
    if comment_id != int(match.group("comment")):
        raise GroundingPlanSealError("GitHub plan-seal comment ID differs from its URL")
    expected_api_issue = (
        f"https://api.github.com/repos/{match.group('owner')}/{match.group('repo')}"
        f"/issues/{match.group('issue')}"
    )
    if raw.get("html_url") != comment_url or raw.get("issue_url") != expected_api_issue:
        raise GroundingPlanSealError("GitHub plan-seal locator identity is invalid")
    if not isinstance(user, Mapping) or user.get("login") != authorized_actor:
        raise GroundingPlanSealError("GitHub plan seal was not posted by the authorized actor")
    if raw.get("author_association") not in _TRUSTED_ASSOCIATIONS:
        raise GroundingPlanSealError("GitHub plan-seal author is not trusted for the Issue")
    created_at = raw.get("created_at")
    updated_at = raw.get("updated_at")
    body = raw.get("body")
    if not all(isinstance(value, str) for value in (created_at, updated_at, body)):
        raise GroundingPlanSealError("GitHub plan-seal fields are invalid")
    if created_at != updated_at:
        raise GroundingPlanSealError("edited GitHub comments cannot seal a grounding plan")
    created = _instant(created_at)
    if created < _instant(resolved_plan.plan.sealed_at):
        raise GroundingPlanSealError("GitHub plan seal predates the external plan")
    marker = grounding_plan_seal_marker(resolved_plan)
    if body.strip() != marker:
        raise GroundingPlanSealError("GitHub comment body is not the exact plan seal")
    receipt = {
        "actor": authorized_actor,
        "author_association": raw["author_association"],
        "comment_id": comment_id,
        "comment_url": comment_url,
        "created_at": created_at,
        "issue_url": issue_url,
        "marker": marker,
        "updated_at": updated_at,
    }
    return VerifiedGroundingPlanSeal(
        plan_id=resolved_plan.plan.plan_id,
        plan_hash=resolved_plan.plan_hash,
        partition=resolved_plan.plan.partition.value,
        issue_url=issue_url,
        comment_url=comment_url,
        comment_id=comment_id,
        actor=authorized_actor,
        created_at=created_at,
        receipt_sha256="sha256:"
        + hashlib.sha256(canonical_json(receipt).encode("utf-8")).hexdigest(),
        _token=_SEAL_TOKEN,
    )


def _instant(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise GroundingPlanSealError("plan-seal timestamp is invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise GroundingPlanSealError("plan-seal timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise GroundingPlanSealError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_number(value: str) -> None:
    raise GroundingPlanSealError(f"non-canonical JSON number is not allowed: {value}")


__all__ = [
    "GroundingPlanSealError",
    "VerifiedGroundingPlanSeal",
    "grounding_plan_seal_marker",
    "verify_grounding_plan_seal",
]
