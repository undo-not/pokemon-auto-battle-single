# AI evaluation specification

## Separation from the environment

Decision policies consume the policy adapter; they do not access complete battle state, sealed fixtures, source lineage, holdout labels, or evaluator internals. The simulator, rule evidence, and readiness verifier remain independent of the policy implementation.

No search, reinforcement-learning, or LLM result can promote an unready environment.

## Team preview

When the regulation uses 6→3 selection, a `TeamPreviewRun` binds both six-member rosters, public preview information, ordered three-member selections, policy identities, regulation/Catalog/RuleSet hashes, and seed lineage.

The selected order determines initial active Pokémon and bench order. Selection legality rejects duplicates, non-roster members, wrong cardinality, hidden-information access, and invalid forms/items under the regulation.

## Public-information policy contract

At each decision window the policy receives:

- its own legal actions and permitted private team information;
- public opponent and field observations;
- publicly revealed history;
- stable policy-visible identifiers required for learning or search.

It must not receive exact opponent hidden sets, full HP when the client only exposes a quantized value, future RNG, evaluation labels, or source/trust metadata.

Policy actions are validated by the environment. Invalid output does not become a fallback action unless the evaluation plan explicitly defines and counts an error policy.

## Evaluation arena

Competitive comparison uses paired seeds and side swaps. Each pair runs both policies from equivalent inputs in both seats. The arena records:

- plan, roster, policy, engine, and environment identities;
- prebattle selections and battle Replays;
- wins, losses, draws, errors, and illegal actions by seat;
- Replay re-verification rate;
- public/private information violations;
- paired utility and uncertainty intervals appropriate to the experiment.

Every saved match must be replay-verifiable. A summary without its resolvable plan, policies, inputs, and Replay evidence is diagnostic only.

## Baselines

Deterministic heuristic baselines are used to validate selection, action, observation, paired-seat, and report wiring. Synthetic fixture results are regression evidence, not estimates of real metagame performance.

Policy identities bind normalized source fingerprints and live runtime fingerprints. Because the runtime fingerprint deliberately includes interpreter bytecode, exact policy, plan, proof, report, and evidence hashes are interpreter-specific. A golden benchmark declares its reference interpreter: the same interpreter must reproduce exact hashes, while other supported interpreters must reproduce the semantic result and pass the identity/hash integrity checks. CI covers the Python 3.10 reference runtime and a newer supported runtime.

Legacy serialized budget ID `PD-009` remains an artifact compatibility label; ADR-0004 defines its meaning and claim boundary.

## Hybrid policy architecture

Regulation-neutral components may learn or search over stable public state, legal actions, transition outcomes, belief features, and value estimates. Regulation-specific team composition, metagame hypotheses, matchup plans, and explanation may use an LLM as a proposal or reasoning component.

LLM output must be converted to typed proposals and checked against current Regulation, Catalog, legal-action, evidence, and time-budget contracts. It cannot author verified rule values, expected engine events, source permissions, ground-truth holdout labels, or readiness decisions.

Policy comparisons must include reproducible non-LLM baselines and resource accounting. Prompt, model, tool, temperature, cache, and external-information identities are part of an LLM policy's experiment manifest.

## Competitive-strength gate

`rank1_equivalence_status` remains `unmeasured` unless a dedicated external evaluation plan defines and satisfies:

- a private-match environment that passes readiness for the named regulation;
- a sealed, representative, lineage-independent opponent and team distribution;
- calibration against strong human or otherwise justified top-level play;
- adequate paired sample size and uncertainty bounds;
- no hidden-information or environment-privilege leakage;
- repeatability across seeds, seats, relevant archetypes, and regulation changes;
- explicit compute, latency, and decision-time constraints.

Self-play Elo, synthetic win rate, evaluator LLM preference, or one favorable matchup cannot establish rank-1 equivalence.

## Experiment storage

Plans and small schemas may be tracked. Replays, trajectories, models, checkpoints, LLM caches, embeddings, expanded reports, and private-match captures remain in the external artifact store and are referenced through manifests and hashes.
