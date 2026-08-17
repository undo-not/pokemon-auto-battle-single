# ADR-0007: Use a pinned external Showdown Champions engine

- Status: Accepted
- Date: 2026-08-17
- Supersedes: ADR-0003, ADR-0004, and ADR-0005

## Context

The custom Python battle engine duplicated damage, legality, turn resolution, Replay, Catalog, RuleSet, and source-compilation work already maintained by the Pokémon Showdown project. Keeping that stack correct across mechanics and frequent regulation changes imposed more maintenance and false-confidence risk than this project could justify. Pokémon Showdown now contains a Champions mod and named Champions BSS formats, but those community-maintained semantics are not official client evidence.

Large upstream source trees, Node dependencies, builds, battle runs, and machine-learning artifacts also conflict with the repository's small-reviewable-source boundary.

## Decision

Use the Pokémon Showdown Champions mod as the only battle-transition, team-validation, legal-choice, and damage engine. Pin one upstream commit and Git tree in a tracked manifest. The manifest also binds the canonical Git-blob and LF-normalized worktree hashes for the MIT license and selected sources, relevant format identity, Node minimum, compiled/runtime-dependency file count, and deterministic build fingerprint.

Keep the Showdown checkout, `node_modules`, and compiled output outside the repository. A strict versioned JSON-lines bridge runs as one persistent Node process and hosts multiple isolated battles. Its normalized source hash is part of engine identity. Python exposes player-scoped observations, Showdown choice strings, cloned-state damage samples, and content-addressed, re-executable Replays. Any identity, protocol, format, validation, process, or action error fails closed; there is no Python mechanics fallback.

Remove the custom engine and the Catalog, RuleSet, intake, compiler, capability, promotion, production-trust, and synthetic-arena implementations dedicated to it. Git history is the recovery mechanism for deleted code. Any future deployment-authorization boundary requires a new decision designed for the Showdown-based architecture.

Regulation changes update a named Showdown format and, when required, the pinned upstream commit. Each pin update recomputes the source, runtime-dependency, build, effective-rule, and license identities and reruns deterministic, privacy, Replay, and relevant client-grounding comparisons before replacing the prior usable pin. Local bridge patches must not alter battle semantics. If upstream behavior is insufficient, use a separately reviewed pinned fork or return `NO-GO`; never fall back to the deleted Python engine.

The verified upstream checkout retains its MIT license file outside this repository. If its license, maintainability, security, or Champions suitability becomes unacceptable, stop promotion and choose a replacement through a new ADR. Within 48 hours of a frozen regulation notice, produce an engineering candidate or reasoned `NO-GO`; complete authorized private-match grounding and the deployment decision within seven days. Equal engine/build/runtime identity, teams, choices, and seed must produce equal canonical Replay identity.

## Consequences

- Upstream Showdown maintenance replaces local mechanics maintenance, including damage ordering and special interactions.
- Node and the external Showdown build are explicit runtime dependencies permitted alongside the standard-library Python adapter.
- Upstream changes are deliberate manifest updates with rebuild and integration review, not floating package upgrades.
- A passing regression proves the pinned integration is deterministic; it does not prove exact Pokémon Champions fidelity or rank-1 strength.
- Captures, Replays, training runs, and models remain outside Git. The repository retains only small fixtures and contracts needed to verify the integration.
