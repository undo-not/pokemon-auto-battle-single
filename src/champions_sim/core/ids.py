"""Opaque identifiers used by the simulator core.

The core deliberately stores catalog references as IDs.  Rule and catalog
payloads live outside this package and may change independently.
"""

from typing import NewType


RuleSetId = NewType("RuleSetId", str)
PokemonId = NewType("PokemonId", str)
PokemonInstanceId = NewType("PokemonInstanceId", str)
MoveId = NewType("MoveId", str)
ItemId = NewType("ItemId", str)
AbilityId = NewType("AbilityId", str)
