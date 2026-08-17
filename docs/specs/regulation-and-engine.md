# Regulation and engine binding

## Regulation facts

Official regulation notices define the intended private-match format, effective interval, team sizes, clauses, eligibility, and special mechanics. URLs, retrieval time, hashes, permission notes, and unresolved interpretation belong in the regulation Issue and external artifact store rather than copied source payloads or generated workbenches in Git.

Official facts and Showdown support are separate claims. A matching Showdown format name is a candidate mapping, not proof that its implementation matches the client.

## Tracked binding

The dependency manifest binds one or more exact Showdown format records to an immutable upstream commit and build. The active binding includes:

- format ID and display name;
- Showdown mod ID;
- human-readable regulation label;
- singles game type, ordered direct ruleset, and sorted expanded effective rule table;
- minimum/maximum registered team size, picked-team size, maximum move count,
  source generation, level bounds/default/adjustment, and EV limit;
- commit, tree, canonical Git-blob/LF-worktree source hashes, license, and build fingerprint.

There is no local Catalog, RuleSet, target-pool compiler, or copied upstream Pokédex. Species, form, item, move, ability, legality, and mechanics data are loaded from the verified Showdown build.

## Regulation change

For a new or revised regulation:

1. freeze official facts and authorized external actions in a GitHub Issue;
2. identify the candidate Showdown format and exact upstream commit;
3. inspect changes to format configuration, the relevant Champions mod, inherited simulator code, package lock, and license;
4. build outside the workspace and calculate a new manifest identity;
5. update bridge compatibility, minimal fixtures, schemas, specs, and deterministic tests;
6. run external policy evaluation and authorized private-match grounding;
7. issue a private-match candidate or reasoned `NO-GO`.

Within 48 hours of the frozen notice, produce an engineering candidate or reasoned `NO-GO`. Complete the private-match decision within seven days. Missing format support, unknown mechanics, failed build identity, regression, permission limits, or absent required grounding remains a blocker; deadlines do not permit guessing or an unpinned upstream dependency.

## Upstream update rules

- Never track or edit the upstream checkout inside this repository.
- Never float on a branch, tag, npm range, or latest build.
- Rebuild and re-fingerprint every pin change.
- Preserve the upstream MIT notice through the tracked license hash and documentation link.
- Do not patch Showdown behavior locally in the bridge to make a fixture pass. A required mechanics correction belongs upstream or in a separately reviewed fork decision.
