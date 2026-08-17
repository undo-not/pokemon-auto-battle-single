# AI evaluation

## Policy interface

A policy consumes `ShowdownObservation`: its player ID, turn, latest own request, legal Showdown choice strings, and incremental player-visible log. It never receives the opponent's private request, omniscient battle object, Replay input log, future RNG, holdout labels, or external credentials.

The policy returns one listed choice string. Invalid output is an evaluation error unless an experiment explicitly defines and counts a fallback policy; it never changes engine legality.

## Team construction and hybrid reasoning

Team construction, ordered 6→3 selection, matchup planning, action choice, and explanation are distinct decisions. A useful hybrid architecture is:

- regulation-neutral learned components for public-state encoding, belief estimation, search guidance, policy, and value;
- regulation-specific retrieval and LLM reasoning for metagame hypotheses, team proposals, matchup plans, and explanations;
- deterministic validation through Showdown for every team and action that reaches execution.

LLM output is an untrusted proposal. It cannot define mechanics, declare a team legal, inspect opponent hidden state, create expected Replay events, or upgrade grounding and strength claims.

## Competitive experiments

Policy comparison uses paired seeds and seat swaps over a declared team/opponent distribution. An experiment records engine and format identity, policy/model identity, observation/action interface version, seeds, teams, decisions, errors, latency, compute, and resolvable Replays.

Training data, trajectories, expanded results, checkpoints, prompts/caches, and Replays live in the external artifact store. Git may contain a small deterministic fixture and code that reproduces an experiment, but not its bulk output. The ignored workspace may contain only the one promoted active model bundle permitted by the artifact policy.

## Regulation adaptation

Prefer learning representations and search machinery that remain stable across eligible-pool and item changes. Regulation-specific teams, priors, retrieval, and LLM context may change on each regulation. Before activating a new model or plan, verify the engine pin, format, feature/action compatibility, deterministic regression, evaluation manifest, and private-match grounding.

## Strength claim

`rank1_equivalence_status` is `unmeasured` unless an external plan provides:

- an authorized, grounded private-match environment for the named regulation;
- a sealed representative team and opponent distribution;
- calibration against justified top-level play;
- paired sample size and uncertainty bounds;
- no hidden-information or evaluator-privilege leakage;
- repeatability across seats, seeds, archetypes, and regulation changes;
- declared compute, latency, and decision-time limits.

Self-play rating, synthetic win rate, an evaluator LLM, deterministic execution, or one favorable matchup cannot establish rank-1 equivalence.
