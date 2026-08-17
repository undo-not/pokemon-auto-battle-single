# Battle engine

## Dependency identity

The engine is the external Pokémon Showdown checkout resolved from `data/manifests/pokemon-showdown-champions.json`. Before starting a bridge, the resolver verifies:

- repository URL, exact commit, and Git tree;
- MIT license bytes and selected source-file SHA-256 values;
- Node minimum version;
- compiled JavaScript and runtime-dependency file set, count, and aggregate fingerprint;
- exact format ID, display name, mod, direct ruleset, expanded effective rule
  table, singles game type, and team-size, selection-size, move-count, source
  generation, level, adjustment-level, and EV constraints;
- absence of local custom-format files that Showdown would otherwise load at runtime.

The checkout, `node_modules`, configuration copy, and `dist/` remain outside the repository. Runtime battle execution performs no network access.

## Bridge protocol

Python starts one persistent Node process and communicates through protocol `1.0.0`, one JSON object per line. Requests and responses carry a monotonically increasing request ID. The startup handshake binds the normalized SHA-256 of the executed bridge source. Both sides reject duplicate keys, non-finite numbers, excessive input, unknown envelope fields, protocol drift, and malformed values. A malformed Showdown output poisons that battle session; it cannot be observed, advanced, sampled, or exported afterward, but can still be closed.

One process may host multiple named sessions. Session IDs are unique, battle state is not shared, and commands are serialized by the Python transport. Process exit, timeout, mismatched response identity, invalid format, invalid team, or invalid choice is an error. A timeout terminates the transport so a late response cannot be consumed by a later request. `FORMAT_DRIFT` means a runtime preview differs from the bound effective constraints; `SESSION_POISONED` means malformed output or a failed isolation invariant made that session unusable; `REPLAY_INCOMPLETE` requires the caller to make diagnostic export explicit. No request may invoke a Python mechanics fallback.

## Battle session

Session creation requires:

- the bound format ID;
- one explicit 32-byte lowercase hexadecimal `sodium` seed, selecting the pinned
  Showdown ChaCha20 PRNG rather than the legacy four-integer generator;
- two player names;
- two structured teams accepted by Showdown's `TeamValidator`.

Team set fields are closed by the bridge contract before they reach `Teams.pack`. The engine owns species, item, ability, move, stat-point, clause, and preview legality.

At each decision window, `observe(player)` returns only that player's latest request, legal Showdown choice strings, and player-visible protocol log. Team preview enumerates ordered legal selections using the active format's verified minimum/maximum team size and picked-team size, with an explicit bound on enumeration size; move, switch, and engine-advertised transformation choices are derived from the request. Showdown remains the final legality authority when public information such as possible trapping makes a mask conditional.

`choose(player, choice)` passes one bounded Showdown choice string to strict-choice mode. A rejected choice does not become a default action.

## Damage

Damage is not reimplemented in Python. `damage_sample` serializes the current Showdown battle through JSON to break mutable aliases, constructs a clone, applies Showdown's `ModifyType` and `ModifyMove` event sequence to the named move, and asks the pinned engine for one damage result. It compares the complete serialized live state before and after inspection and poisons the session if anything changed. It returns the resolved move type/category, the state revision, HP context, clone PRNG lineage, and live PRNG values before and after inspection. It neither changes the live battle nor omits current field, status, item, ability, or transformation state.

`damage_status` distinguishes `value` (including numeric zero), `blocked` (Showdown returned `false`), `silent_failure` (Showdown returned `null`), and `non_damaging` (Showdown returned no numeric result). A changed target or cancelled move is unavailable rather than approximated.

A damage sample is one seeded engine result, not a complete probability distribution and not client-grounding evidence.

## Determinism and Replay

For equal manifest identity, build fingerprint, Node version, format, teams, names, ordered choices, and seed, the canonical Replay and its SHA-256 must be equal. Wall-clock protocol lines are normalized and do not enter identity with their actual time. Empty channel lines are omitted from the canonical public and player-visible logs.

Replay `1.0.0` binds:

- exact engine, tree, build, runtime, license, and bridge identity;
- format and seed;
- normalized Showdown input log;
- normalized public battle log;
- terminal state, winner, turns, and score when available;
- canonical self-hash.

The input log contains packed private teams and is an external research artifact, not a policy observation or a Git fixture. Replay export requires a terminal battle unless the caller explicitly opts into an incomplete diagnostic artifact. Replay verification rejects a changed self-hash or engine/bridge identity, permits only the bound start format, two validated player teams, and player-choice commands, then re-executes the log and requires the complete canonical Replay to match. A Replay proves reproducibility for its pinned engine; it does not prove official client conformance.

## Failure and privacy invariants

- Unknown fields and malformed teams fail before session creation.
- Opponent private requests never appear in the other player's observation.
- Omniscient input logs are returned only through explicit Replay export.
- Damage inspection operates on a clone and preserves the live PRNG state.
- Closing one session does not affect another.
- Missing or changed external engine identity prevents startup.
