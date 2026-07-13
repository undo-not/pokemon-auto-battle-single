"""Explicit, immutable pseudo-random state for reproducible transitions."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


_MASK_64 = (1 << 64) - 1
_RANGE_64 = 1 << 64
_SPLITMIX_GAMMA = 0x9E3779B97F4A7C15


@dataclass(frozen=True, slots=True)
class ExplicitRNG:
    """SplitMix64 state passed into and returned from every random operation.

    Methods never mutate this object. Reusing one instance therefore creates
    reproducible, independent simulation branches without copying global RNG
    state.
    """

    seed: int
    state: int
    cursor: int = 0

    def __post_init__(self) -> None:
        if not 0 <= self.seed <= _MASK_64:
            raise ValueError("seed must be an unsigned 64-bit integer")
        if not 0 <= self.state <= _MASK_64:
            raise ValueError("state must be an unsigned 64-bit integer")
        if self.cursor < 0:
            raise ValueError("cursor must be non-negative")

    @classmethod
    def seeded(cls, seed: int) -> "ExplicitRNG":
        normalized = seed & _MASK_64
        return cls(seed=normalized, state=normalized, cursor=0)

    def next_u64(self) -> tuple[int, "ExplicitRNG"]:
        next_state = (self.state + _SPLITMIX_GAMMA) & _MASK_64
        value = next_state
        value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & _MASK_64
        value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & _MASK_64
        value ^= value >> 31
        return value & _MASK_64, ExplicitRNG(
            seed=self.seed,
            state=next_state,
            cursor=self.cursor + 1,
        )

    def randbelow(self, upper: int) -> tuple[int, "ExplicitRNG"]:
        """Draw uniformly from ``range(upper)`` using rejection sampling."""

        if not 1 <= upper <= _RANGE_64:
            raise ValueError("upper must be between 1 and 2**64")
        limit = _RANGE_64 - (_RANGE_64 % upper)
        rng = self
        while True:
            value, rng = rng.next_u64()
            if value < limit:
                return value % upper, rng

    def chance(self, numerator: int, denominator: int) -> tuple[bool, "ExplicitRNG"]:
        if denominator <= 0:
            raise ValueError("denominator must be positive")
        if not 0 <= numerator <= denominator:
            raise ValueError("numerator must be in [0, denominator]")
        draw, next_rng = self.randbelow(denominator)
        return draw < numerator, next_rng

    def branch(self, label: str) -> "ExplicitRNG":
        """Derive a deterministic child stream without consuming the parent."""

        if not label:
            raise ValueError("branch label must be non-empty")
        material = (
            f"champions-sim-rng-v1:{self.seed:016x}:{self.state:016x}:"
            f"{self.cursor}:{label}"
        ).encode("utf-8")
        child_seed = int.from_bytes(hashlib.sha256(material).digest()[:8], "big")
        return ExplicitRNG.seeded(child_seed)
