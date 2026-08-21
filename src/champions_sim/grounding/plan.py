"""External grounding denominator and holdout-lineage contracts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from champions_sim.core import canonical_hash, canonical_json, to_canonical_data

from .android_client import AndroidClientBuild
from .catalog import (
    MaterialBehavior,
    MaterialBehaviorCatalogError,
    resolve_material_behavior_catalog,
)
from .lineage import ResolvedGroundingLineageReceipt


_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_STABLE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_REPLAY_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_ANDROID_PACKAGE_RE = re.compile(
    r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+$"
)
_ISSUE_URL_RE = re.compile(r"^https://github\.com/[^/]+/[^/]+/issues/[1-9][0-9]*$")
_GITHUB_LOGIN_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
_MAX_PLAN_BYTES = 2 * 1024 * 1024
_PLAN_KEYS = {
    "schema_version",
    "plan_id",
    "issue_url",
    "seal_actor",
    "regulation_id",
    "format_id",
    "material_behavior_catalog_id",
    "material_behavior_catalog_sha256",
    "target_package",
    "client_build",
    "engine_manifest_sha256",
    "partition",
    "capture_store_id",
    "capture_store_identity_sha256",
    "sealed_at",
    "lineage_receipt_sha256",
    "requirements",
    "exclusions",
    "local_research_only",
    "distribution_allowed",
}


class GroundingPlanError(ValueError):
    """Raised for an invalid denominator or non-independent holdout."""


class GroundingPartition(str, Enum):
    DEVELOPMENT = "development"
    HOLDOUT = "holdout"


class GroundingCategory(str, Enum):
    UI_OBSERVATION = "ui_observation"
    TEAM_PREVIEW = "team_preview"
    LEGAL_ACTION = "legal_action"
    EVENT_ORDER = "event_order"
    ROUNDING = "rounding"
    RNG_BOUNDARY = "rng_boundary"
    MEGA_EVOLUTION = "mega_evolution"
    SIMULTANEOUS_INTERACTION = "simultaneous_interaction"


class GroundingEvidenceMethod(str, Enum):
    SCREENSHOT = "screenshot"
    UI_HIERARCHY = "ui_hierarchy"
    BOTH = "screenshot_and_ui_hierarchy"


class ExpectedSource(str, Enum):
    PINNED_REPLAY = "pinned_replay"
    SHOWDOWN_REQUEST = "showdown_request"
    SHOWDOWN_PUBLIC_LOG = "showdown_public_log"
    MANUAL_SCOPE = "manual_scope"


class ExclusionBasis(str, Enum):
    OUT_OF_SCOPE = "out_of_scope"
    UNOBSERVABLE = "unobservable"
    NOT_MATERIAL = "not_material"


@dataclass(frozen=True, slots=True)
class GroundingExpectedLocator:
    pointer: str
    player: str | None
    revision: int | None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.pointer, str)
            or not self.pointer.startswith("/")
            or len(self.pointer) > 1024
            or re.search(r"~(?![01])", self.pointer) is not None
        ):
            raise GroundingPlanError("expected locator pointer must be a JSON pointer")
        if (self.player is None) != (self.revision is None):
            raise GroundingPlanError(
                "expected locator player and revision must be present together"
            )
        if self.player is not None and self.player not in {"p1", "p2"}:
            raise GroundingPlanError("expected locator player must be p1 or p2")
        if self.revision is not None and (
            not isinstance(self.revision, int)
            or isinstance(self.revision, bool)
            or not 0 <= self.revision <= 9999
        ):
            raise GroundingPlanError(
                "expected locator revision must be between 0 and 9999"
            )


def _stable_id(value: str, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) > 240
        or _STABLE_ID_RE.fullmatch(value) is None
    ):
        raise GroundingPlanError(f"{field_name} must be a stable ID")


def _timestamp(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise GroundingPlanError(f"{field_name} must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise GroundingPlanError(f"{field_name} must include a timezone")
    return parsed


def _public_log_sequence(value: Any) -> tuple[str, ...] | None:
    if (
        not isinstance(value, (list, tuple))
        or not value
        or any(not isinstance(item, str) or not item for item in value)
    ):
        return None
    return tuple(value)


def _freeze_expected(value: Any) -> Any:
    canonical = to_canonical_data(value)

    def freeze(item: Any) -> Any:
        if isinstance(item, list):
            return tuple(freeze(value) for value in item)
        if isinstance(item, dict):
            return MappingProxyType(
                {key: freeze(value) for key, value in item.items()}
            )
        return item

    return freeze(canonical)


def _turn_segments(lines: tuple[str, ...]) -> tuple[tuple[str, ...], ...] | None:
    segments: list[list[str]] = []
    turn_numbers: list[int] = []
    current: list[str] | None = None
    for line in lines:
        if line.startswith("|turn|"):
            try:
                turn = int(line.removeprefix("|turn|"))
            except ValueError:
                return None
            if turn <= 0 or (turn_numbers and turn <= turn_numbers[-1]):
                return None
            turn_numbers.append(turn)
            current = [line]
            segments.append(current)
        elif current is not None:
            current.append(line)
        elif line.startswith("|move|"):
            return None
    if not segments:
        return None
    return tuple(tuple(segment) for segment in segments)


def _move_sides(segment: tuple[str, ...]) -> set[str]:
    sides: set[str] = set()
    for line in segment:
        parts = line.split("|")
        if len(parts) >= 4 and parts[1] == "move":
            match = re.match(r"^(p[12])[a-z]?:", parts[2])
            if match is not None:
                sides.add(match.group(1))
    return sides


def _has_mega_before_same_actor_move(segments: tuple[tuple[str, ...], ...]) -> bool:
    for segment in segments:
        for index, line in enumerate(segment):
            parts = line.split("|")
            if len(parts) < 4 or parts[1] != "-mega":
                continue
            actor = parts[2]
            if any(
                len(candidate := later.split("|")) >= 4
                and candidate[1] == "move"
                and candidate[2] == actor
                for later in segment[index + 1 :]
            ):
                return True
    return False


def _has_hypnosis_miss(segments: tuple[tuple[str, ...], ...]) -> bool:
    for segment in segments:
        for index, line in enumerate(segment):
            parts = line.split("|")
            if len(parts) < 5 or parts[1] != "move" or parts[3] != "Hypnosis":
                continue
            actor, target = parts[2], parts[4]
            for later in segment[index + 1 :]:
                candidate = later.split("|")
                if len(candidate) >= 2 and candidate[1] == "move":
                    break
                if (
                    len(candidate) >= 4
                    and candidate[1] == "-miss"
                    and candidate[2] == actor
                    and candidate[3] == target
                ):
                    return True
    return False


def _is_odd_hp_super_fang_result(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    match = re.fullmatch(r"([0-9]+)/([1-9][0-9]*)(?: [^|]+)?", value)
    if match is None:
        return False
    current, maximum = (int(item) for item in match.groups())
    return maximum % 2 == 1 and current == (maximum + 1) // 2 and current < maximum


def _validate_catalog_expectation(
    behavior: MaterialBehavior,
    requirement: "GroundingRequirement",
) -> None:
    constraint = behavior.expected_constraint
    locator = requirement.expected_locator
    exact_locators = {
        "ordered_public_battle_sequence": "/public_log",
        "nonempty_canonical_legal_actions": "/legal_actions",
        "mega_before_same_actor_move": "/public_log",
        "explicit_rng_outcome_sequence": "/public_log",
        "same_turn_multiple_actions": "/public_log",
        "team_preview_three": "/request/maxChosenTeamSize",
    }
    if constraint in exact_locators and (
        locator is None or locator.pointer != exact_locators[constraint]
    ):
        raise GroundingPlanError(
            f"material behavior requires its exact Replay locator: {behavior.behavior_id}"
        )
    if constraint == "odd_hp_super_fang_rounding" and (
        locator is None
        or re.fullmatch(
            r"/request/side/pokemon/(?:0|[1-9][0-9]*)/condition",
            locator.pointer,
        )
        is None
        or locator.revision is None
        or locator.revision < 4
    ):
        raise GroundingPlanError(
            f"material behavior requires a post-turn own-HP request locator: {behavior.behavior_id}"
        )

    value = requirement.expected
    if constraint == "private_friend_match":
        valid = value == "private_friend_match"
    elif constraint == "team_preview_three":
        valid = isinstance(value, int) and not isinstance(value, bool) and value == 3
    elif constraint == "nonempty_canonical_legal_actions":
        valid = (
            isinstance(value, (list, tuple))
            and bool(value)
            and all(
                isinstance(action, str)
                and re.fullmatch(
                    r"(?:team [1-6]+|move [1-4](?: mega)?|switch [1-6]|pass)",
                    action,
                )
                is not None
                for action in value
            )
            and len(value) == len(set(value))
        )
    elif constraint == "odd_hp_super_fang_rounding":
        valid = _is_odd_hp_super_fang_result(value)
    else:
        lines = _public_log_sequence(value)
        segments = _turn_segments(lines) if lines is not None else None
        if constraint == "ordered_public_battle_sequence":
            valid = segments is not None and any(
                any(line.startswith("|move|") for line in segment)
                for segment in segments
            )
        elif constraint == "mega_before_same_actor_move":
            valid = segments is not None and _has_mega_before_same_actor_move(
                segments
            )
        elif constraint == "explicit_rng_outcome_sequence":
            valid = segments is not None and _has_hypnosis_miss(segments)
        elif constraint == "same_turn_multiple_actions":
            valid = segments is not None and any(
                _move_sides(segment) == {"p1", "p2"} for segment in segments
            )
        else:
            raise GroundingPlanError(
                f"material behavior expectation constraint is unknown: {constraint}"
            )
    if not valid:
        raise GroundingPlanError(
            f"material behavior expected value lacks its required witness: {behavior.behavior_id}"
        )


@dataclass(frozen=True, slots=True)
class GroundingRequirement:
    requirement_id: str
    category: GroundingCategory
    path: str
    evidence_method: GroundingEvidenceMethod
    expected_source: ExpectedSource
    expected: Any
    reference_replay_hash: str | None
    expected_locator: GroundingExpectedLocator | None
    rationale: str

    def __post_init__(self) -> None:
        _stable_id(self.requirement_id, "requirement_id")
        if not isinstance(self.category, GroundingCategory):
            raise GroundingPlanError("grounding requirement category is invalid")
        if not isinstance(self.evidence_method, GroundingEvidenceMethod):
            raise GroundingPlanError("grounding evidence method is invalid")
        if not isinstance(self.expected_source, ExpectedSource):
            raise GroundingPlanError("grounding expected source is invalid")
        if not self.path.startswith("/"):
            raise GroundingPlanError("grounding requirement path must be a JSON pointer")
        if not self.rationale:
            raise GroundingPlanError("grounding requirement rationale is required")
        try:
            frozen_expected = _freeze_expected(self.expected)
        except TypeError as error:
            raise GroundingPlanError("grounding expected value is not canonical") from error
        object.__setattr__(self, "expected", frozen_expected)
        if self.reference_replay_hash is not None:
            if _REPLAY_HASH_RE.fullmatch(self.reference_replay_hash) is None:
                raise GroundingPlanError("reference_replay_hash is invalid")
        if (
            self.expected_source is not ExpectedSource.MANUAL_SCOPE
            and self.reference_replay_hash is None
        ):
            raise GroundingPlanError(
                "Showdown-derived expectations require a Replay hash"
            )
        if (
            self.expected_source is not ExpectedSource.MANUAL_SCOPE
            and self.expected_locator is None
        ):
            raise GroundingPlanError(
                "Showdown-derived expectations require a Replay locator"
            )
        if (
            self.expected_source is ExpectedSource.MANUAL_SCOPE
            and self.category is not GroundingCategory.UI_OBSERVATION
        ):
            raise GroundingPlanError(
                "manual scope cannot establish battle-rule expectations"
            )
        if self.expected_source is ExpectedSource.MANUAL_SCOPE and (
            self.reference_replay_hash is not None or self.expected_locator is not None
        ):
            raise GroundingPlanError(
                "manual scope must not claim Replay evidence"
            )
        if self.expected_locator is not None:
            locator = self.expected_locator
            if not isinstance(locator, GroundingExpectedLocator):
                raise GroundingPlanError("grounding expected locator is invalid")
            if self.expected_source is ExpectedSource.SHOWDOWN_REQUEST:
                if locator.player is None or not locator.pointer.startswith(
                    ("/request", "/legal_actions", "/turn", "/ended", "/winner")
                ):
                    raise GroundingPlanError(
                        "Showdown request expectations require a player-view locator"
                    )
            elif locator.player is not None:
                raise GroundingPlanError(
                    "Replay/public-log expectations must not select a player revision"
                )
            if (
                self.expected_source is ExpectedSource.SHOWDOWN_PUBLIC_LOG
                and locator.pointer != "/public_log"
                and not locator.pointer.startswith("/public_log/")
            ):
                raise GroundingPlanError(
                    "Showdown public-log expectations must point into public_log"
                )


@dataclass(frozen=True, slots=True)
class GroundingExclusion:
    behavior_id: str
    category: GroundingCategory
    basis: ExclusionBasis
    reason: str

    def __post_init__(self) -> None:
        _stable_id(self.behavior_id, "behavior_id")
        if not isinstance(self.category, GroundingCategory):
            raise GroundingPlanError("grounding exclusion category is invalid")
        if not isinstance(self.basis, ExclusionBasis):
            raise GroundingPlanError("grounding exclusion basis is invalid")
        if not self.reason:
            raise GroundingPlanError("grounding exclusion reason is required")


@dataclass(frozen=True, slots=True)
class GroundingPlan:
    schema_version: str
    plan_id: str
    issue_url: str
    seal_actor: str
    regulation_id: str
    format_id: str
    material_behavior_catalog_id: str
    material_behavior_catalog_sha256: str
    target_package: str
    client_build: AndroidClientBuild
    engine_manifest_sha256: str
    partition: GroundingPartition
    capture_store_id: str
    capture_store_identity_sha256: str
    sealed_at: str
    lineage_receipt_sha256: str
    requirements: tuple[GroundingRequirement, ...]
    exclusions: tuple[GroundingExclusion, ...]
    local_research_only: bool
    distribution_allowed: bool

    def __post_init__(self) -> None:
        if self.schema_version != "1.0.0":
            raise GroundingPlanError("only grounding plan schema 1.0.0 is supported")
        for field_name in (
            "plan_id",
            "regulation_id",
            "format_id",
            "material_behavior_catalog_id",
            "capture_store_id",
        ):
            _stable_id(getattr(self, field_name), field_name)
        if _ISSUE_URL_RE.fullmatch(self.issue_url) is None:
            raise GroundingPlanError("issue_url must identify a GitHub Issue")
        if _GITHUB_LOGIN_RE.fullmatch(self.seal_actor) is None:
            raise GroundingPlanError("seal_actor must be a GitHub login")
        if (
            len(self.target_package) > 240
            or _ANDROID_PACKAGE_RE.fullmatch(self.target_package) is None
        ):
            raise GroundingPlanError(
                "target_package must be a fully qualified Android package"
            )
        if not isinstance(self.client_build, AndroidClientBuild):
            raise GroundingPlanError("grounding plan client_build is invalid")
        if not isinstance(self.partition, GroundingPartition):
            raise GroundingPlanError("grounding plan partition is invalid")
        if _SHA256_RE.fullmatch(self.lineage_receipt_sha256) is None:
            raise GroundingPlanError("lineage_receipt_sha256 is invalid")
        if any(not isinstance(value, GroundingRequirement) for value in self.requirements):
            raise GroundingPlanError("grounding plan requirements are invalid")
        if any(not isinstance(value, GroundingExclusion) for value in self.exclusions):
            raise GroundingPlanError("grounding plan exclusions are invalid")
        if _SHA256_RE.fullmatch(self.engine_manifest_sha256) is None:
            raise GroundingPlanError("engine_manifest_sha256 is invalid")
        if _SHA256_RE.fullmatch(self.material_behavior_catalog_sha256) is None:
            raise GroundingPlanError("material_behavior_catalog_sha256 is invalid")
        if _SHA256_RE.fullmatch(self.capture_store_identity_sha256) is None:
            raise GroundingPlanError("capture_store_identity_sha256 is invalid")
        _timestamp(self.sealed_at, "sealed_at")
        if not self.requirements:
            raise GroundingPlanError("grounding plan requires a non-empty denominator")
        requirement_ids = tuple(value.requirement_id for value in self.requirements)
        if len(requirement_ids) != len(set(requirement_ids)):
            raise GroundingPlanError("grounding requirement IDs must be unique")
        exclusion_ids = tuple(value.behavior_id for value in self.exclusions)
        if len(exclusion_ids) != len(set(exclusion_ids)):
            raise GroundingPlanError("grounding exclusion IDs must be unique")
        if set(requirement_ids) & set(exclusion_ids):
            raise GroundingPlanError("a behavior cannot be both required and excluded")
        if tuple(sorted(requirement_ids)) != requirement_ids:
            raise GroundingPlanError("grounding requirements must be sorted by ID")
        if tuple(sorted(exclusion_ids)) != exclusion_ids:
            raise GroundingPlanError("grounding exclusions must be sorted by ID")
        covered_categories = {
            value.category for value in (*self.requirements, *self.exclusions)
        }
        missing_categories = sorted(
            value.value for value in set(GroundingCategory) - covered_categories
        )
        if missing_categories:
            raise GroundingPlanError(
                "grounding plan omits required material categories: "
                + ", ".join(missing_categories)
            )
        requirement_categories = {value.category for value in self.requirements}
        if GroundingCategory.UI_OBSERVATION not in requirement_categories:
            raise GroundingPlanError(
                "the private-friend-match client state requires affirmative UI observation"
            )
        try:
            catalog = resolve_material_behavior_catalog(
                self.regulation_id,
                self.format_id,
            )
        except MaterialBehaviorCatalogError as error:
            raise GroundingPlanError(str(error)) from error
        if (
            self.material_behavior_catalog_id != catalog.catalog_id
            or self.material_behavior_catalog_sha256 != catalog.catalog_hash
        ):
            raise GroundingPlanError(
                "grounding plan material-behavior catalog identity is invalid"
            )
        requirements_by_id = {
            value.requirement_id: value for value in self.requirements
        }
        exclusions_by_id = {value.behavior_id: value for value in self.exclusions}
        catalog_ids = {value.behavior_id for value in catalog.behaviors}
        if set(requirements_by_id) | set(exclusions_by_id) != catalog_ids:
            raise GroundingPlanError(
                "grounding denominator does not exactly match the material-behavior catalog"
            )
        for behavior in catalog.behaviors:
            if behavior.required and behavior.behavior_id in exclusions_by_id:
                raise GroundingPlanError(
                    f"material behavior cannot be excluded: {behavior.behavior_id}"
                )
            requirement = requirements_by_id.get(behavior.behavior_id)
            if requirement is None:
                continue
            if (
                requirement.category.value != behavior.category
                or requirement.path != behavior.path
                or requirement.evidence_method.value != behavior.evidence_method
                or requirement.expected_source.value != behavior.expected_source
            ):
                raise GroundingPlanError(
                    f"material behavior contract differs from the catalog: {behavior.behavior_id}"
                )
            locator = requirement.expected_locator
            if behavior.locator_prefix is None:
                if locator is not None:
                    raise GroundingPlanError(
                        f"material behavior must not declare a Replay locator: {behavior.behavior_id}"
                    )
            elif locator is None or not locator.pointer.startswith(
                behavior.locator_prefix
            ):
                raise GroundingPlanError(
                    f"material behavior locator differs from the catalog: {behavior.behavior_id}"
                )
            _validate_catalog_expectation(behavior, requirement)
        replay_hashes = {
            requirement.reference_replay_hash
            for requirement in self.requirements
            if requirement.expected_source is not ExpectedSource.MANUAL_SCOPE
        }
        if len(replay_hashes) != 1:
            raise GroundingPlanError(
                "all Showdown-derived requirements must use one scenario Replay"
            )
        if self.local_research_only is not True or self.distribution_allowed is not False:
            raise GroundingPlanError("grounding plans are local research only")

    def to_dict(self) -> dict[str, Any]:
        value = to_canonical_data(self)
        assert isinstance(value, dict)
        return value

    @property
    def plan_hash(self) -> str:
        return "sha256:" + canonical_hash(self)


_RESOLUTION_TOKEN = object()


@dataclass(frozen=True, slots=True, init=False)
class ResolvedGroundingPlan:
    plan: GroundingPlan
    plan_hash: str
    source_path: Path

    def __init__(
        self,
        plan: GroundingPlan,
        plan_hash: str,
        source_path: Path,
        *,
        _token: object | None = None,
    ) -> None:
        if _token is not _RESOLUTION_TOKEN:
            raise GroundingPlanError(
                "resolved grounding plans must be created by the external loader"
            )
        object.__setattr__(self, "plan", plan)
        object.__setattr__(self, "plan_hash", plan_hash)
        object.__setattr__(self, "source_path", source_path)


_PAIR_TOKEN = object()


@dataclass(frozen=True, slots=True, init=False)
class ValidatedGroundingPlanPair:
    development: ResolvedGroundingPlan
    holdout: ResolvedGroundingPlan
    development_lineage: ResolvedGroundingLineageReceipt
    holdout_lineage: ResolvedGroundingLineageReceipt

    def __init__(
        self,
        development: ResolvedGroundingPlan,
        holdout: ResolvedGroundingPlan,
        development_lineage: ResolvedGroundingLineageReceipt,
        holdout_lineage: ResolvedGroundingLineageReceipt,
        *,
        _token: object | None = None,
    ) -> None:
        if _token is not _PAIR_TOKEN:
            raise GroundingPlanError("grounding plan pair must be created by the validator")
        object.__setattr__(self, "development", development)
        object.__setattr__(self, "holdout", holdout)
        object.__setattr__(self, "development_lineage", development_lineage)
        object.__setattr__(self, "holdout_lineage", holdout_lineage)


def validate_grounding_plan_pair(
    development: ResolvedGroundingPlan,
    holdout: ResolvedGroundingPlan,
    *,
    development_lineage: ResolvedGroundingLineageReceipt,
    holdout_lineage: ResolvedGroundingLineageReceipt,
) -> ValidatedGroundingPlanPair:
    dev = development.plan
    test = holdout.plan
    if dev.partition is not GroundingPartition.DEVELOPMENT:
        raise GroundingPlanError("development plan has the wrong partition")
    if test.partition is not GroundingPartition.HOLDOUT:
        raise GroundingPlanError("holdout plan has the wrong partition")
    for field_name in (
        "issue_url",
        "regulation_id",
        "format_id",
        "material_behavior_catalog_id",
        "material_behavior_catalog_sha256",
        "target_package",
        "client_build",
        "engine_manifest_sha256",
    ):
        if getattr(dev, field_name) != getattr(test, field_name):
            raise GroundingPlanError(f"grounding plans disagree on {field_name}")
    if dev.plan_id == test.plan_id:
        raise GroundingPlanError("development and holdout plan IDs must differ")
    if dev.capture_store_id == test.capture_store_id:
        raise GroundingPlanError("development and holdout capture stores must differ")
    if dev.capture_store_identity_sha256 == test.capture_store_identity_sha256:
        raise GroundingPlanError(
            "development and holdout physical capture stores must differ"
        )
    _validate_plan_lineage(development, development_lineage)
    _validate_plan_lineage(holdout, holdout_lineage)
    dev_lineage = development_lineage.receipt
    test_lineage = holdout_lineage.receipt
    if development_lineage.receipt_sha256 == holdout_lineage.receipt_sha256:
        raise GroundingPlanError("development and holdout reuse the same lineage receipt")
    if dev_lineage.lineage_id == test_lineage.lineage_id:
        raise GroundingPlanError("development and holdout lineage IDs overlap")
    if dev_lineage.source_store_identity_sha256 == test_lineage.source_store_identity_sha256:
        raise GroundingPlanError("development and holdout source stores overlap")
    if set(dev_lineage.source_artifact_sha256) & set(
        test_lineage.source_artifact_sha256
    ):
        raise GroundingPlanError("development and holdout source artifacts overlap")
    if dev_lineage.collection_method != test_lineage.collection_method:
        raise GroundingPlanError("development and holdout collection methods differ")
    development_people = {
        dev_lineage.collector_id,
        dev_lineage.author_id,
        dev_lineage.executor_id,
    }
    holdout_people = {
        test_lineage.collector_id,
        test_lineage.author_id,
        test_lineage.executor_id,
    }
    if development_people & holdout_people:
        raise GroundingPlanError(
            "development and holdout collector/author/executor identities overlap"
        )
    if (
        _denominator_shape(dev.requirements) != _denominator_shape(test.requirements)
        or canonical_json(dev.exclusions) != canonical_json(test.exclusions)
    ):
        raise GroundingPlanError("development and holdout denominators must be identical")
    development_replays = {
        value.reference_replay_hash
        for value in dev.requirements
        if value.reference_replay_hash is not None
    }
    holdout_replays = {
        value.reference_replay_hash
        for value in test.requirements
        if value.reference_replay_hash is not None
    }
    if development_replays & holdout_replays:
        raise GroundingPlanError("development and holdout reuse Replay evidence")
    return ValidatedGroundingPlanPair(
        development=development,
        holdout=holdout,
        development_lineage=development_lineage,
        holdout_lineage=holdout_lineage,
        _token=_PAIR_TOKEN,
    )


def validate_grounding_plan_lineage(
    plan: ResolvedGroundingPlan,
    lineage: ResolvedGroundingLineageReceipt,
) -> None:
    _validate_plan_lineage(plan, lineage)


def _validate_plan_lineage(
    resolved_plan: ResolvedGroundingPlan,
    resolved_lineage: ResolvedGroundingLineageReceipt,
) -> None:
    plan = resolved_plan.plan
    receipt = resolved_lineage.receipt
    if resolved_lineage.receipt_sha256 != plan.lineage_receipt_sha256:
        raise GroundingPlanError("lineage receipt hash differs from the plan")
    expected = {
        "issue_url": plan.issue_url,
        "regulation_id": plan.regulation_id,
        "format_id": plan.format_id,
        "partition": plan.partition.value,
        "capture_store_id": plan.capture_store_id,
        "capture_store_identity_sha256": plan.capture_store_identity_sha256,
    }
    for field_name, value in expected.items():
        if getattr(receipt, field_name) != value:
            raise GroundingPlanError(f"lineage receipt {field_name} differs from the plan")
    if _timestamp(receipt.collected_at, "lineage collected_at") > _timestamp(
        plan.sealed_at, "sealed_at"
    ):
        raise GroundingPlanError("lineage receipt was collected after the plan was sealed")


def _denominator_shape(requirements: tuple[GroundingRequirement, ...]) -> str:
    values = []
    for requirement in requirements:
        value = to_canonical_data(requirement)
        assert isinstance(value, dict)
        value["reference_replay_hash"] = None
        values.append(value)
    return canonical_json(values)


def load_grounding_plan(path: Path | str) -> ResolvedGroundingPlan:
    source_path = _outside_repository(Path(path))
    try:
        if source_path.stat().st_size > _MAX_PLAN_BYTES:
            raise GroundingPlanError("grounding plan exceeds the configured limit")
        raw = json.loads(
            source_path.read_text(encoding="utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise GroundingPlanError(f"cannot read grounding plan: {error}") from error
    if not isinstance(raw, Mapping) or set(raw) != _PLAN_KEYS:
        raise GroundingPlanError("grounding plan has missing or unexpected fields")
    try:
        plan = _plan_from_mapping(raw)
    except GroundingPlanError:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise GroundingPlanError(f"grounding plan domain value is invalid: {error}") from error
    return ResolvedGroundingPlan(
        plan=plan,
        plan_hash=plan.plan_hash,
        source_path=source_path,
        _token=_RESOLUTION_TOKEN,
    )


def _plan_from_mapping(raw: Mapping[str, Any]) -> GroundingPlan:
    requirements: list[GroundingRequirement] = []
    requirement_keys = {
        "requirement_id",
        "category",
        "path",
        "evidence_method",
        "expected_source",
        "expected",
        "reference_replay_hash",
        "expected_locator",
        "rationale",
    }
    for index, value in enumerate(_array(raw["requirements"], "requirements")):
        item = _object(value, f"requirements[{index}]")
        _keys(item, requirement_keys, f"requirements[{index}]")
        replay_hash = item["reference_replay_hash"]
        if replay_hash is not None and not isinstance(replay_hash, str):
            raise GroundingPlanError("reference_replay_hash must be a string or null")
        locator_raw = item["expected_locator"]
        locator = None
        if locator_raw is not None:
            locator_value = _object(locator_raw, "expected_locator")
            _keys(
                locator_value,
                {"pointer", "player", "revision"},
                "expected_locator",
            )
            player = locator_value["player"]
            revision = locator_value["revision"]
            if player is not None and not isinstance(player, str):
                raise GroundingPlanError("expected locator player must be a string or null")
            if revision is not None and not isinstance(revision, int):
                raise GroundingPlanError("expected locator revision must be an integer or null")
            locator = GroundingExpectedLocator(
                pointer=_string(locator_value["pointer"], "expected locator pointer"),
                player=player,
                revision=revision,
            )
        requirements.append(
            GroundingRequirement(
                requirement_id=_string(item["requirement_id"], "requirement_id"),
                category=GroundingCategory(_string(item["category"], "category")),
                path=_string(item["path"], "path"),
                evidence_method=GroundingEvidenceMethod(
                    _string(item["evidence_method"], "evidence_method")
                ),
                expected_source=ExpectedSource(
                    _string(item["expected_source"], "expected_source")
                ),
                expected=item["expected"],
                reference_replay_hash=replay_hash,
                expected_locator=locator,
                rationale=_string(item["rationale"], "rationale"),
            )
        )
    exclusions: list[GroundingExclusion] = []
    exclusion_keys = {"behavior_id", "category", "basis", "reason"}
    for index, value in enumerate(_array(raw["exclusions"], "exclusions")):
        item = _object(value, f"exclusions[{index}]")
        _keys(item, exclusion_keys, f"exclusions[{index}]")
        exclusions.append(
            GroundingExclusion(
                behavior_id=_string(item["behavior_id"], "behavior_id"),
                category=GroundingCategory(_string(item["category"], "category")),
                basis=ExclusionBasis(_string(item["basis"], "basis")),
                reason=_string(item["reason"], "reason"),
            )
        )
    return GroundingPlan(
        schema_version=_string(raw["schema_version"], "schema_version"),
        plan_id=_string(raw["plan_id"], "plan_id"),
        issue_url=_string(raw["issue_url"], "issue_url"),
        seal_actor=_string(raw["seal_actor"], "seal_actor"),
        regulation_id=_string(raw["regulation_id"], "regulation_id"),
        format_id=_string(raw["format_id"], "format_id"),
        material_behavior_catalog_id=_string(
            raw["material_behavior_catalog_id"],
            "material_behavior_catalog_id",
        ),
        material_behavior_catalog_sha256=_string(
            raw["material_behavior_catalog_sha256"],
            "material_behavior_catalog_sha256",
        ),
        target_package=_string(raw["target_package"], "target_package"),
        client_build=_client_build(raw["client_build"]),
        engine_manifest_sha256=_string(
            raw["engine_manifest_sha256"], "engine_manifest_sha256"
        ),
        partition=GroundingPartition(_string(raw["partition"], "partition")),
        capture_store_id=_string(raw["capture_store_id"], "capture_store_id"),
        capture_store_identity_sha256=_string(
            raw["capture_store_identity_sha256"],
            "capture_store_identity_sha256",
        ),
        sealed_at=_string(raw["sealed_at"], "sealed_at"),
        lineage_receipt_sha256=_string(
            raw["lineage_receipt_sha256"], "lineage_receipt_sha256"
        ),
        requirements=tuple(requirements),
        exclusions=tuple(exclusions),
        local_research_only=_boolean(raw["local_research_only"], "local_research_only"),
        distribution_allowed=_boolean(
            raw["distribution_allowed"], "distribution_allowed"
        ),
    )


def _client_build(value: Any) -> AndroidClientBuild:
    raw = _object(value, "client_build")
    _keys(
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


def _outside_repository(path: Path) -> Path:
    if not path.is_absolute():
        raise GroundingPlanError("grounding plan path must be absolute")
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(_REPOSITORY_ROOT.resolve(strict=True))
    except ValueError:
        return resolved
    raise GroundingPlanError("grounding plan must stay outside the repository")


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise GroundingPlanError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise GroundingPlanError(f"non-finite JSON value is not allowed: {value}")


def _object(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise GroundingPlanError(f"{label} must be an object")
    return value


def _array(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise GroundingPlanError(f"{label} must be an array")
    return value


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise GroundingPlanError(f"{label} must be a string")
    return value


def _boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise GroundingPlanError(f"{label} must be a boolean")
    return value


def _integer(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise GroundingPlanError(f"{label} must be an integer")
    return value


def _keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise GroundingPlanError(f"{label} has missing or unexpected fields")


__all__ = [
    "ExclusionBasis",
    "ExpectedSource",
    "GroundingExpectedLocator",
    "GroundingCategory",
    "GroundingEvidenceMethod",
    "GroundingExclusion",
    "GroundingPartition",
    "GroundingPlan",
    "GroundingPlanError",
    "GroundingRequirement",
    "ResolvedGroundingPlan",
    "ValidatedGroundingPlanPair",
    "load_grounding_plan",
    "validate_grounding_plan_pair",
    "validate_grounding_plan_lineage",
]
