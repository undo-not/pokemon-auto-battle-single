"""Source-bound identity helpers for policies evaluated by AI-01."""

from __future__ import annotations

import hashlib
from typing import Mapping

from champions_sim.core import (
    canonical_hash,
    canonical_json,
    class_runtime_sha256,
    class_source_sha256,
)

from .models import AgentIdentity


def component_path(component: type) -> str:
    return f"{component.__module__}.{component.__qualname__}"


def make_agent_identity(
    *,
    agent_id: str,
    version: str,
    component_types: tuple[type, ...],
    battle_policy_type: type,
    configuration: Mapping[str, object],
    observation_contract: str = "player-observation-v1",
) -> AgentIdentity:
    paths = tuple(component_path(value) for value in component_types)
    if len(set(paths)) != len(paths):
        raise ValueError("agent identity component types must be unique")
    battle_path = component_path(battle_policy_type)
    if battle_path not in paths:
        raise ValueError("battle policy type must be included in component types")
    source_hashes = tuple(class_source_sha256(value) for value in component_types)
    runtime_hashes = tuple(class_runtime_sha256(value) for value in component_types)
    configuration_json = canonical_json(configuration)
    configuration_hash = hashlib.sha256(
        configuration_json.encode("utf-8")
    ).hexdigest()
    sources = tuple(
        {
            "component": path,
            "source_sha256": source_hash,
            "runtime_sha256": runtime_hash,
        }
        for path, source_hash, runtime_hash in zip(
            paths, source_hashes, runtime_hashes, strict=True
        )
    )
    implementation_hash = canonical_hash(
        {
            "agent_id": agent_id,
            "version": version,
            "components": sources,
            "configuration_json": configuration_json,
            "configuration_hash": configuration_hash,
            "observation_contract": observation_contract,
        }
    )
    return AgentIdentity(
        agent_id=agent_id,
        version=version,
        implementation_hash=implementation_hash,
        implementation_components=paths,
        component_source_hashes=tuple(
            zip(paths, source_hashes, strict=True)
        ),
        component_runtime_hashes=tuple(
            zip(paths, runtime_hashes, strict=True)
        ),
        battle_policy_component=battle_path,
        configuration_json=configuration_json,
        configuration_hash=configuration_hash,
        observation_contract=observation_contract,
    )


def verify_agent_identity(
    identity: AgentIdentity,
    *,
    component_types: tuple[type, ...],
    battle_policy_type: type,
    configuration: Mapping[str, object],
) -> None:
    expected = make_agent_identity(
        agent_id=identity.agent_id,
        version=identity.version,
        component_types=component_types,
        battle_policy_type=battle_policy_type,
        configuration=configuration,
        observation_contract=identity.observation_contract,
    )
    if identity != expected:
        raise ValueError("agent identity does not match policy source and configuration")
