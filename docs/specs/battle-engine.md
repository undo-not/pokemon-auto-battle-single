# Battle engine specification

## Inputs and outputs

The battle engine consumes:

- an immutable, hash-addressed `Catalog`;
- an immutable, hash-addressed `RuleSet`;
- a validated initial battle state;
- one legal decision per required player and decision window;
- a non-negative RNG seed.

It produces a terminal or non-terminal battle state, ordered events, decision-window records, RNG lineage, observations, and canonical Replay identity.

## Determinism

Equal Catalog bytes, RuleSet bytes, initial state, ordered decisions, engine-semantics version, and seed must produce equal:

- legal-action sets;
- RNG draws and draw positions;
- events and event order;
- observations at every window;
- final state and winner;
- canonical Replay bytes and SHA-256.

Do not use wall-clock time, process-global randomness, unordered collection iteration, environment locale, network input, or LLM output in battle transitions.

## State and legality

Complete state records both teams, active slots, HP, status, volatile state, stat ranks, moves and PP, field state, turn, once-per-battle resources, and RNG position required by supported mechanics.

The legal-action resolver is the only source of actions accepted by the engine. It validates at least:

- active Pokémon and forced-switch state;
- move availability and PP;
- target legality;
- switch target availability;
- regulation and once-per-battle resource constraints;
- decision-window ownership.

Illegal actions fail before state mutation and do not consume RNG.

## Turn execution

The engine resolves a turn through explicit stages:

1. validate the decision set against one immutable pre-turn snapshot;
2. apply supported pre-move transformations;
3. determine action order from action class, move priority, effective Speed, and declared tie RNG;
4. execute each still-valid action;
5. resolve fainting and forced switches;
6. resolve ordered end-of-turn effects;
7. emit the next observation and legal-action set or a terminal result.

Effect order, simultaneous-faint resolution, no-target behavior, and residual rounding are RuleSet semantics. ADR-0003 records the rationale and uncertainty boundary for legacy serialized decision IDs `PD-003`, `PD-004`, and `PD-007`.

## RNG

Every stochastic mechanic uses the battle RNG stream and records enough data to replay the draw. A mechanic that does not draw RNG records that fact rather than fabricating a draw. An action invalidated before a stochastic stage does not consume draws from later stages.

Tests must cover RNG range, draw count, tie behavior, no-target behavior, and replayed draw equivalence.

## Damage

Damage calculation is a pure function of validated inputs and RuleSet semantics. It explicitly represents level, offensive and defensive stats, power, category, ranks, STAB, type effectiveness, critical state, random roll, and supported modifiers.

Rounding and modifier order are part of the RuleSet. Unsupported weather, terrain, screen, spread, variable-power, item, ability, or other modifiers must be named and rejected by `UnsupportedDamageMechanic`; they must not be ignored.

## Structured effects

Moves, abilities, items, statuses, field effects, and transformations enter runtime only through registered structured-effect handlers. A handler declares triggers, targets, ordering stage, state mutation, RNG behavior, emitted events, and incompatibilities.

For each promoted capability, require:

- a source-bound structured meaning;
- a registered handler identity;
- at least one positive engine scenario;
- canonical Replay evidence;
- mutation tests for unsupported or malformed variants.

Unknown, missing, or conflicting effects remain unsupported. Generic “normal damage”, “no effect”, or similar fallback is forbidden.

## Mega Evolution

Mega Evolution, when enabled by a RuleSet, is a once-per-battle declared transformation bound to an eligible base form, required item, target form, stats, types, and ability. It occurs at the configured pre-move stage, persists for the battle, and appears in public observations and Replay.

The engine must reject ineligible species, missing or wrong items, repeated use, unknown form relations, and ungrounded simultaneous-order semantics. A generic engineering fixture does not establish regulation-specific Mega fidelity.

## Observations

Complete state and player observation are separate types. A player observation may contain only public team-preview information, public active state, revealed moves/items/abilities according to the RuleSet, public field state, public event history, own private information, and the player's legal actions.

The engine must not deliver opponent unrevealed sets, sealed fixtures, RNG state, source lineage, holdout labels, or evaluator-only metadata to a policy.

## Replay

Replay binds:

- schema and engine-semantics version;
- Catalog and RuleSet hashes;
- source and legacy decision identifiers required by the serialized version;
- initial state;
- every decision window and submitted decision;
- RNG lineage and ordered events;
- final state and winner;
- canonical self-hash.

Verification re-resolves the referenced Catalog and RuleSet, replays every transition, and rejects identity, legality, event, observation, RNG, or final-state drift.

## Validation

Engine changes require focused unit tests, integration Replay verification, frozen-baseline validation, deterministic repetition, and the full test suite. Claims about Pokémon Champions behavior additionally require the grounding contract in `evidence-and-readiness.md`.

For an external conformance corpus, define:

```text
verified_transition_conformance_rate
  = matching_verified_transitions / required_verified_transitions
```

Pokémon Champions transition conformance requires `verified_transition_conformance_rate == 1.0` over the frozen required assertion denominator. Missing or unsupported assertions remain in the denominator; deterministic local tests and synthetic smoke runs do not enter the verified numerator automatically.
