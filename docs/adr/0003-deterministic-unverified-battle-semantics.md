# ADR-0003: Isolate deterministic but unverified battle semantics in RuleSet data

- Status: Superseded by ADR-0007
- Date: 2026-08-17
- Legacy aliases: `PD-003`, `PD-004`, `PD-007`

## Context

A deterministic reference engine needs exact critical-hit, rounding, effect-order, no-target, and simultaneous-faint rules. Some values match established Pokémon behavior but lack Pokémon Champions-specific primary evidence or actual-client grounding. Omitting every uncertain value would prevent local engineering; treating them as verified would create a false fidelity claim.

## Decision

Keep uncertain semantics as explicit, versioned RuleSet data and propagate their stable legacy IDs through Replay. They are valid only for the named RuleSet and cannot be generalized as Pokémon Champions truth.

The reference RuleSet uses:

- ordinary critical chance `1/24` and critical multiplier `1.5`;
- burn `floor(max_hp / 16)`, ordinary poison `floor(max_hp / 8)`, toxic `floor(max_hp * stage / 16)`, and Leftovers `floor(max_hp / 16)`, with minimum one when an effect occurs;
- explicit action, damage sub-effect, residual, forced-switch, no-target RNG, and simultaneous-faint ordering encoded by the engine and tests.

Unknown exceptions and interactions fail closed. Simultaneous Mega Evolution order is not inferred from the ordinary ordering decision and requires its own grounding.

## Consequences

- Local regression is deterministic before external grounding exists.
- Replay discloses which uncertain decision set governed a run.
- A passing regression proves internal consistency, not client fidelity.
- New actual evidence changes a new RuleSet or superseding ADR; it does not silently alter an existing frozen Replay.
