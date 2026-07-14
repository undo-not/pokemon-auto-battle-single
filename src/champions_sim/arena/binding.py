"""Source- and state-bound battle policy factories for arena execution."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
from typing import Any

from champions_sim.core import canonical_json, component_state_sha256
from champions_sim.policies import Policy

from .identity import component_path, make_agent_identity, verify_agent_identity
from .models import AgentIdentity


PolicyFactory = Callable[[], Policy]


@dataclass(frozen=True, slots=True)
class BoundAgent:
    """Bind a reported identity to the exact policy class and initial state.

    This is an in-process integrity boundary, not a sandbox.  A policy can still
    read process globals, which is why AI-01 reports retain the mandatory
    ``policy_process_isolation_not_implemented`` blocker.
    """

    identity: AgentIdentity
    policy_type: type
    component_types: tuple[type, ...]
    factory: PolicyFactory
    identity_configuration_json: str
    expected_initial_policy_hash: str

    def __post_init__(self) -> None:
        if type(self.identity) is not AgentIdentity:
            raise ValueError("bound agent requires the exact AgentIdentity contract")
        self.identity.__post_init__()
        configuration = self._configuration()
        if configuration.get("battle_policy_component") != component_path(
            self.policy_type
        ):
            raise ValueError("bound agent configuration has the wrong policy component")
        if configuration.get("initial_policy_state_hash") != self.expected_initial_policy_hash:
            raise ValueError("bound agent configuration has the wrong policy state hash")
        if self.identity.configuration_json != self.identity_configuration_json:
            raise ValueError("bound agent configuration differs from reported identity")
        verify_agent_identity(
            self.identity,
            component_types=self.component_types,
            battle_policy_type=self.policy_type,
            configuration=configuration,
        )
        self._validate_policy(self.factory())
        # A caller-controlled factory executes code.  Recheck the live class
        # after it returns so it cannot install a transient policy method after
        # the pre-factory identity check.
        verify_agent_identity(
            self.identity,
            component_types=self.component_types,
            battle_policy_type=self.policy_type,
            configuration=configuration,
        )

    def validate_integrity(self) -> None:
        """Recompute the binding after construction-time mutation attempts."""

        self.__post_init__()

    def new_policy(self) -> Policy:
        policy = self.factory()
        self._validate_policy(policy)
        verify_agent_identity(
            self.identity,
            component_types=self.component_types,
            battle_policy_type=self.policy_type,
            configuration=self._configuration(),
        )
        return policy

    @property
    def identity_configuration(self) -> Mapping[str, Any]:
        return self._configuration()

    def _configuration(self) -> dict[str, Any]:
        try:
            value = json.loads(self.identity_configuration_json)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError("bound agent configuration must be canonical JSON") from exc
        if not isinstance(value, dict) or canonical_json(value) != self.identity_configuration_json:
            raise ValueError("bound agent configuration must be a canonical JSON object")
        return value

    def _validate_policy(self, policy: Policy) -> None:
        if type(policy) is not self.policy_type:
            raise ValueError(
                "policy factory returned a class different from the bound identity"
            )
        try:
            actual_hash = component_state_sha256(policy)
        except TypeError as exc:
            raise ValueError(
                "policy initial state must use canonical domain values"
            ) from exc
        if actual_hash != self.expected_initial_policy_hash:
            raise ValueError(
                "policy factory returned initial state different from the bound identity"
            )


def bind_agent(
    *,
    agent_id: str,
    version: str,
    policy_type: type,
    factory: PolicyFactory,
    component_types: tuple[type, ...] | None = None,
    configuration: Mapping[str, object] | None = None,
    observation_contract: str = "player-observation-v1",
) -> BoundAgent:
    """Create a binding whose identity includes code and initial policy state."""

    components = component_types or (policy_type,)
    if policy_type not in components:
        raise ValueError("battle policy type must be included in component types")
    specimen = factory()
    if type(specimen) is not policy_type:
        raise ValueError("policy factory returned a class different from policy_type")
    try:
        state_hash = component_state_sha256(specimen)
    except TypeError as exc:
        raise ValueError("policy initial state must use canonical domain values") from exc
    supplied = dict(configuration or {})
    reserved = {"battle_policy_component", "initial_policy_state_hash"}
    if reserved & set(supplied):
        raise ValueError("agent configuration uses a reserved binding field")
    bound_configuration: dict[str, object] = {
        **supplied,
        "battle_policy_component": component_path(policy_type),
        "initial_policy_state_hash": state_hash,
    }
    identity = make_agent_identity(
        agent_id=agent_id,
        version=version,
        component_types=components,
        battle_policy_type=policy_type,
        configuration=bound_configuration,
        observation_contract=observation_contract,
    )
    return BoundAgent(
        identity=identity,
        policy_type=policy_type,
        component_types=components,
        factory=factory,
        identity_configuration_json=canonical_json(bound_configuration),
        expected_initial_policy_hash=state_hash,
    )
