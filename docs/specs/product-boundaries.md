# Product boundaries

## Purpose

`champions_sim` is a Pokémon Champions singles research environment for team selection, decision-policy development, offline evaluation, and explicitly authorized private friend-match testing.

The system has four independent layers:

1. a pinned external Pokémon Showdown Champions battle engine;
2. a Python policy and evaluation interface that exposes one player's view;
3. external machine-learning and experiment storage;
4. optional read-only BlueStacks observation and private-match grounding.

A result in one layer does not upgrade another. Exact upstream bytes do not prove client fidelity, deterministic battles do not prove competitive strength, and a strong model does not authorize game operation.

## Game-facing scope

- Format: singles, including 6→3 team preview when required by the bound Showdown format.
- Allowed target: private friend matches with explicit authorization.
- Ranked-match automation: prohibited.
- Unattended BlueStacks input automation: prohibited.
- Ordinary diagnostics: read-only and must not start ADB, the emulator, capture, or input as a side effect.
- Captures: local research only, stored outside Git, and handled as potentially sensitive.

## Engine boundary

Battle transitions, team validation, legal choices, damage, and RNG come only from the exact Showdown build in `data/manifests/pokemon-showdown-champions.json`. The repository does not maintain a second mechanics implementation or silently fall back when Showdown is unavailable.

The pinned Champions mod is an engineering dependency, not official Pokémon Champions truth. Material mechanics require authorized client grounding before a private-match fidelity claim.

## Policy boundary

A policy receives only its own Showdown request, legal choice strings, and its player-visible log. It must not receive the opponent's private request, omniscient battle state, future RNG, evaluator labels, external holdout data, or artifact-store credentials.

LLMs may propose teams, matchup plans, or actions. They cannot establish rule values, engine correctness, source permission, grounding, or competitive equivalence.

## Technology and data

- Python 3.10 or newer; standard-library Python runtime adapter.
- Node.js 22 or newer and the manifest-pinned external Showdown checkout allowed by ADR-0007.
- Strict versioned JSON contracts with duplicate-key and non-finite-number rejection.
- Replays, runs, models, upstream checkouts, builds, captures, and downloaded data outside Git.
- At most one explicitly activated model bundle may be materialized in the ignored workspace location defined by the artifact policy.

Behavioral changes update implementation, current specs, schemas, fixtures, and tests together. Backward-incompatible serialized changes receive a new schema or bridge protocol version.
