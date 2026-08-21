"""Versioned material-behavior denominator for the active Champions format."""

from __future__ import annotations

from dataclasses import dataclass

from champions_sim.core import canonical_hash, to_canonical_data


class MaterialBehaviorCatalogError(ValueError):
    """Raised when no exact tracked denominator exists for a format."""


@dataclass(frozen=True, slots=True)
class MaterialBehavior:
    behavior_id: str
    category: str
    path: str
    evidence_method: str
    expected_source: str
    locator_prefix: str | None
    expected_constraint: str
    required: bool


@dataclass(frozen=True, slots=True)
class MaterialBehaviorCatalog:
    schema_version: str
    catalog_id: str
    regulation_id: str
    format_id: str
    behaviors: tuple[MaterialBehavior, ...]

    def to_dict(self) -> dict[str, object]:
        value = to_canonical_data(self)
        assert isinstance(value, dict)
        return value

    @property
    def catalog_hash(self) -> str:
        return "sha256:" + canonical_hash(self)


_M_B_CATALOG = MaterialBehaviorCatalog(
    schema_version="1.0.0",
    catalog_id="champions-m-b-gen9championsbssregmb-v1",
    regulation_id="champions-m-b",
    format_id="gen9championsbssregmb",
    behaviors=(
        MaterialBehavior(
            behavior_id="event-order-public-sequence",
            category="event_order",
            path="/battle/event_order",
            evidence_method="screenshot_and_ui_hierarchy",
            expected_source="showdown_public_log",
            locator_prefix="/public_log",
            expected_constraint="ordered_public_battle_sequence",
            required=True,
        ),
        MaterialBehavior(
            behavior_id="legal-action-player-request",
            category="legal_action",
            path="/battle/legal_actions",
            evidence_method="screenshot_and_ui_hierarchy",
            expected_source="showdown_request",
            locator_prefix="/legal_actions",
            expected_constraint="nonempty_canonical_legal_actions",
            required=True,
        ),
        MaterialBehavior(
            behavior_id="mega-evolution-order",
            category="mega_evolution",
            path="/battle/mega_evolution",
            evidence_method="screenshot_and_ui_hierarchy",
            expected_source="showdown_public_log",
            locator_prefix="/public_log",
            expected_constraint="mega_before_same_actor_move",
            required=True,
        ),
        MaterialBehavior(
            behavior_id="rng-boundary-public-outcome",
            category="rng_boundary",
            path="/battle/rng_boundary",
            evidence_method="screenshot_and_ui_hierarchy",
            expected_source="showdown_public_log",
            locator_prefix="/public_log",
            expected_constraint="explicit_rng_outcome_sequence",
            required=True,
        ),
        MaterialBehavior(
            behavior_id="rounding-visible-hp",
            category="rounding",
            path="/battle/rounding",
            evidence_method="screenshot_and_ui_hierarchy",
            expected_source="showdown_request",
            locator_prefix="/request/side/pokemon/",
            expected_constraint="odd_hp_super_fang_rounding",
            required=True,
        ),
        MaterialBehavior(
            behavior_id="simultaneous-interaction-order",
            category="simultaneous_interaction",
            path="/battle/simultaneous_interaction",
            evidence_method="screenshot_and_ui_hierarchy",
            expected_source="showdown_public_log",
            locator_prefix="/public_log",
            expected_constraint="same_turn_multiple_actions",
            required=True,
        ),
        MaterialBehavior(
            behavior_id="team-preview-max-selected",
            category="team_preview",
            path="/battle/team_preview",
            evidence_method="screenshot_and_ui_hierarchy",
            expected_source="showdown_request",
            locator_prefix="/request/maxChosenTeamSize",
            expected_constraint="team_preview_three",
            required=True,
        ),
        MaterialBehavior(
            behavior_id="ui-private-friend-match",
            category="ui_observation",
            path="/client/match_kind",
            evidence_method="screenshot_and_ui_hierarchy",
            expected_source="manual_scope",
            locator_prefix=None,
            expected_constraint="private_friend_match",
            required=True,
        ),
    ),
)

_CATALOGS = {
    (_M_B_CATALOG.regulation_id, _M_B_CATALOG.format_id): _M_B_CATALOG,
}


def resolve_material_behavior_catalog(
    regulation_id: str,
    format_id: str,
) -> MaterialBehaviorCatalog:
    try:
        return _CATALOGS[(regulation_id, format_id)]
    except KeyError as error:
        raise MaterialBehaviorCatalogError(
            "no tracked material-behavior catalog exists for regulation/format"
        ) from error


__all__ = [
    "MaterialBehavior",
    "MaterialBehaviorCatalog",
    "MaterialBehaviorCatalogError",
    "resolve_material_behavior_catalog",
]
