"""Resolve planned expectations from exact external Showdown Replay evidence."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from champions_sim.core import canonical_json, to_canonical_data
from champions_sim.showdown import ShowdownClient, ShowdownReplay

from .plan import (
    ExpectedSource,
    GroundingRequirement,
    ResolvedGroundingPlan,
)


_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_MAX_REPLAY_BYTES = 64 * 1024 * 1024
_ROUNDING_REQUIREMENT_ID = "rounding-visible-hp"
_ROUNDING_IDENT_SUFFIX = ":target-ident"
_ROUNDING_HISTORY_SUFFIX = ":visible-history"


class GroundingExpectationError(ValueError):
    """Raised when a plan expectation does not resolve from its declared source."""


@dataclass(frozen=True, slots=True)
class ResolvedGroundingExpectation:
    requirement_id: str
    expected_source: ExpectedSource
    expected: Any
    replay_hash: str | None
    replay_source_sha256: str | None


_RESOLUTION_TOKEN = object()


@dataclass(frozen=True, slots=True, init=False)
class ResolvedGroundingExpectations:
    plan_hash: str
    evidence: tuple[ResolvedGroundingExpectation, ...]

    def __init__(
        self,
        *,
        plan_hash: str,
        evidence: tuple[ResolvedGroundingExpectation, ...],
        _token: object | None = None,
    ) -> None:
        if _token is not _RESOLUTION_TOKEN:
            raise GroundingExpectationError(
                "grounding expectations must be created by the Replay resolver"
            )
        object.__setattr__(self, "plan_hash", plan_hash)
        object.__setattr__(self, "evidence", evidence)

    def for_requirement(self, requirement_id: str) -> ResolvedGroundingExpectation:
        for value in self.evidence:
            if value.requirement_id == requirement_id:
                return value
        raise GroundingExpectationError(
            f"grounding expectation is missing: {requirement_id}"
        )

    @property
    def replay_hashes(self) -> frozenset[str]:
        return frozenset(
            value.replay_hash
            for value in self.evidence
            if value.replay_hash is not None
        )


@dataclass(frozen=True, slots=True)
class _ExternalReplay:
    replay: ShowdownReplay
    source_sha256: str


def resolve_grounding_expectations(
    resolved_plan: ResolvedGroundingPlan,
    replay_paths: Mapping[str, Path | str],
    *,
    client: ShowdownClient | None = None,
) -> ResolvedGroundingExpectations:
    """Re-execute every declared Replay and compare each planned expected value."""

    plan = resolved_plan.plan
    required_hashes = {
        requirement.reference_replay_hash
        for requirement in plan.requirements
        if requirement.reference_replay_hash is not None
    }
    supplied_hashes = set(replay_paths)
    if any(not isinstance(value, str) for value in supplied_hashes):
        raise GroundingExpectationError("Replay evidence mapping keys must be hashes")
    if supplied_hashes != required_hashes:
        missing = sorted(required_hashes - supplied_hashes)
        unexpected = sorted(supplied_hashes - required_hashes)
        detail = []
        if missing:
            detail.append("missing=" + ",".join(missing))
        if unexpected:
            detail.append("unexpected=" + ",".join(unexpected))
        raise GroundingExpectationError(
            "Replay evidence mapping does not match the plan: " + "; ".join(detail)
        )
    if required_hashes and not isinstance(client, ShowdownClient):
        raise GroundingExpectationError(
            "Showdown-derived expectations require the active pinned Showdown client"
        )

    replays = {
        replay_hash: _load_external_replay(path, replay_hash=replay_hash)
        for replay_hash, path in replay_paths.items()
    }
    for replay_hash, external in replays.items():
        document = external.replay.document
        if document["format_id"] != plan.format_id:
            raise GroundingExpectationError(
                f"Replay format differs from the plan: {replay_hash}"
            )
        engine = document["engine"]
        assert isinstance(engine, Mapping)
        if "sha256:" + str(engine["manifest_sha256"]) != plan.engine_manifest_sha256:
            raise GroundingExpectationError(
                f"Replay engine manifest differs from the plan: {replay_hash}"
            )

    resolved_by_id: dict[str, ResolvedGroundingExpectation] = {}
    requirements_by_replay: dict[str, list[GroundingRequirement]] = {}
    for requirement in plan.requirements:
        if requirement.reference_replay_hash is None:
            resolved_by_id[requirement.requirement_id] = ResolvedGroundingExpectation(
                requirement_id=requirement.requirement_id,
                expected_source=requirement.expected_source,
                expected=to_canonical_data(requirement.expected),
                replay_hash=None,
                replay_source_sha256=None,
            )
        else:
            requirements_by_replay.setdefault(
                requirement.reference_replay_hash, []
            ).append(requirement)

    assert client is not None or not requirements_by_replay
    for replay_hash, requirements in requirements_by_replay.items():
        external = replays[replay_hash]
        selectors = []
        for requirement in requirements:
            locator = requirement.expected_locator
            assert locator is not None
            if requirement.expected_source is ExpectedSource.SHOWDOWN_REQUEST:
                assert locator.player is not None and locator.revision is not None
                selectors.append(
                    {
                        "selector_id": requirement.requirement_id,
                        "player": locator.player,
                        "revision": locator.revision,
                        "pointer": locator.pointer,
                    }
                )
                if requirement.requirement_id == _ROUNDING_REQUIREMENT_ID:
                    pokemon_pointer = locator.pointer.removesuffix("/condition")
                    selectors.extend(
                        (
                            {
                                "selector_id": requirement.requirement_id
                                + _ROUNDING_IDENT_SUFFIX,
                                "player": locator.player,
                                "revision": locator.revision,
                                "pointer": pokemon_pointer + "/ident",
                            },
                            {
                                "selector_id": requirement.requirement_id
                                + _ROUNDING_HISTORY_SUFFIX,
                                "player": locator.player,
                                "revision": locator.revision,
                                "pointer": "/visible_log",
                            },
                        )
                    )
        assert client is not None
        reproduced, request_values = client.resolve_replay_expectations(
            external.replay.to_dict(), selectors
        )
        replay_document = reproduced.to_dict()
        for requirement in requirements:
            locator = requirement.expected_locator
            assert locator is not None
            if requirement.expected_source is ExpectedSource.SHOWDOWN_REQUEST:
                observed = request_values[requirement.requirement_id]
            else:
                observed = _resolve_json_pointer(replay_document, locator.pointer)
            if canonical_json(observed) != canonical_json(requirement.expected):
                raise GroundingExpectationError(
                    "planned expected value differs from Replay evidence: "
                    + requirement.requirement_id
                )
            if requirement.requirement_id == _ROUNDING_REQUIREMENT_ID and not (
                _has_matching_super_fang_transition(
                    condition=observed,
                    target_ident=request_values[
                        requirement.requirement_id + _ROUNDING_IDENT_SUFFIX
                    ],
                    visible_history=request_values[
                        requirement.requirement_id + _ROUNDING_HISTORY_SUFFIX
                    ],
                )
            ):
                raise GroundingExpectationError(
                    "rounding expectation is not bound to an odd-HP Super Fang "
                    "transition: "
                    + requirement.requirement_id
                )
            resolved_by_id[requirement.requirement_id] = ResolvedGroundingExpectation(
                requirement_id=requirement.requirement_id,
                expected_source=requirement.expected_source,
                expected=to_canonical_data(observed),
                replay_hash=replay_hash,
                replay_source_sha256=external.source_sha256,
            )

    expected_ids = {value.requirement_id for value in plan.requirements}
    if set(resolved_by_id) != expected_ids:
        raise GroundingExpectationError("resolved grounding expectations are incomplete")
    return ResolvedGroundingExpectations(
        plan_hash=resolved_plan.plan_hash,
        evidence=tuple(resolved_by_id[key] for key in sorted(resolved_by_id)),
        _token=_RESOLUTION_TOKEN,
    )


def _load_external_replay(path: Path | str, *, replay_hash: str) -> _ExternalReplay:
    source_path = _outside_repository(Path(path))
    try:
        if source_path.stat().st_size > _MAX_REPLAY_BYTES:
            raise GroundingExpectationError("Replay evidence exceeds the configured limit")
        payload = source_path.read_bytes()
        raw = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_float=_reject_number,
            parse_constant=_reject_number,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise GroundingExpectationError(f"cannot read Replay evidence: {error}") from error
    if not isinstance(raw, Mapping):
        raise GroundingExpectationError("Replay evidence must be a JSON object")
    try:
        replay = ShowdownReplay.from_document(raw)
    except (TypeError, ValueError) as error:
        raise GroundingExpectationError("Replay evidence is invalid") from error
    if replay.replay_hash != replay_hash:
        raise GroundingExpectationError("Replay evidence hash differs from the plan")
    return _ExternalReplay(
        replay=replay,
        source_sha256="sha256:" + hashlib.sha256(payload).hexdigest(),
    )


def _outside_repository(path: Path) -> Path:
    if not path.is_absolute():
        raise GroundingExpectationError("Replay evidence path must be absolute")
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(_REPOSITORY_ROOT.resolve(strict=True))
    except ValueError:
        return resolved
    raise GroundingExpectationError("Replay evidence must stay outside the repository")


def _resolve_json_pointer(value: Any, pointer: str) -> Any:
    current = value
    for encoded in pointer[1:].split("/"):
        if re.search(r"~(?![01])", encoded) is not None:
            raise GroundingExpectationError("Replay locator contains an invalid escape")
        token = encoded.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            if not token.isdigit() or (len(token) > 1 and token.startswith("0")):
                raise GroundingExpectationError("Replay locator array index is invalid")
            index = int(token)
            if index >= len(current):
                raise GroundingExpectationError("Replay locator array index is absent")
            current = current[index]
        elif isinstance(current, Mapping) and token in current:
            current = current[token]
        else:
            raise GroundingExpectationError("Replay locator object key is absent")
    return to_canonical_data(current)


def _battle_identity(value: Any) -> tuple[str, str] | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"(p[12])(?:[a-z])?:\s*(\S(?:.*\S)?)", value)
    if match is None:
        return None
    return match.group(1), match.group(2)


def _has_matching_super_fang_transition(
    *,
    condition: Any,
    target_ident: Any,
    visible_history: Any,
) -> bool:
    target = _battle_identity(target_ident)
    if (
        target is None
        or not isinstance(condition, str)
        or not isinstance(visible_history, (list, tuple))
        or not visible_history
        or any(not isinstance(line, str) for line in visible_history)
    ):
        return False
    for index, line in enumerate(visible_history):
        move = line.split("|")
        if len(move) < 5 or move[1] != "move" or move[3] != "Super Fang":
            continue
        actor = _battle_identity(move[2])
        move_target = _battle_identity(move[4])
        if actor is None or move_target != target or actor[0] == target[0]:
            continue
        if index + 1 >= len(visible_history):
            continue
        event = visible_history[index + 1].split("|")
        if (
            len(event) == 4
            and event[1] == "-damage"
            and _battle_identity(event[2]) == target
            and event[3] == condition
        ):
            return True
    return False


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise GroundingExpectationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_number(value: str) -> None:
    raise GroundingExpectationError(f"non-canonical JSON number is not allowed: {value}")


__all__ = [
    "GroundingExpectationError",
    "ResolvedGroundingExpectation",
    "ResolvedGroundingExpectations",
    "resolve_grounding_expectations",
]
