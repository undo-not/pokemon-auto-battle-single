"""Core-domain errors."""

from __future__ import annotations

from .ids import RuleSetId


class UnsupportedMechanic(RuntimeError):
    """Raised when a transition would otherwise guess at unknown mechanics."""

    def __init__(
        self,
        mechanic_id: str,
        *,
        ruleset_id: RuleSetId | None = None,
        context: str | None = None,
    ) -> None:
        self.mechanic_id = mechanic_id
        self.ruleset_id = ruleset_id
        self.context = context
        parts = [f"unsupported mechanic: {mechanic_id}"]
        if ruleset_id is not None:
            parts.append(f"ruleset={ruleset_id}")
        if context is not None:
            parts.append(f"context={context}")
        super().__init__("; ".join(parts))
