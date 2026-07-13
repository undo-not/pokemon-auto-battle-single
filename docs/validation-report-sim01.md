# SIM-01 Validation Report

## Result

`sim-core 0.1`のローカル研究用SIM-01 fixtureは、2026-07-13時点のengineering gateを通過した。
これは完全なPokémon Champions公式準拠、全図鑑対応、または再配布許可を意味しない。

## Exact bundle

- simulator version: `0.1.0`
- engine semantics: `sim-core-0.1`
- Replay Schema: `2.0.0`
- Catalog SHA-256: `764a75146a017aca77453110fc8e19903ddc11e64e1df03c92791aa367703141`
- RuleSet SHA-256: `f87b077b1ba598865a9e21ef84decbf273ca73806a9412fd5d2520589ff34215`
- provisional decisions: `PD-003`, `PD-004`, `PD-007`
- source manifests: `legacy-champions-59bf57c-sim01`, `champions-wiki-damage-reference`
- license scope: `local_research_only`; redistribution and commercial use are prohibited while source licenses remain unverified

## Automated verification

### Test suite

- command: `python -m pytest -q`
- result: `66 passed`
- includes:
  - same state/actions/seed replayed 100 times with byte-identical Replay JSON
  - legal/illegal/stale decision handling
  - branch immutability and explicit RNG
  - player observation redaction and consumed-item public knowledge
  - one-sided and two-sided forced switches
  - priority, speed, no-target, faint and simultaneous-faint boundaries
  - representative move, status, item and ability effects
  - malformed/unsupported catalog and state fail-closed behavior
  - Replay v2 roundtrip, drift detection, recursive Schema validation and re-execution
  - separate-process Replay write/read/verification
  - source manifest, license scope and repository-size gates

### 10,000 seeded battles

- command: `python -m champions_sim smoke --battles 10000 --seed-start 0`
- wall time: `188.4 s`
- result: `10,000 / 10,000` terminal
- P1 wins: `3,240`
- P2 wins: `6,760`
- draws: `0`
- decision windows: `195,319`
- events: `2,462,659`
- final state hashes: `10,000`
- crash / unsupported transition / decision-window guard failure: `0`

### Saved Replay reprocessing

- seed: `20260713`
- terminal: turn `15`, P2 win, `19` decision windows, `254` events
- final state hash: `4f59a78f7bb5b8e771d6dd4a4dffd8ed69c5dfead55b7f96ac6c924fea6b4267`
- Replay hash: `26af0e4d16f742892ca90c97bc7621380b97fe624c6ec784943ce25f8ad07546`
- serialized Replay file SHA-256: `d1d2235326b4ecb98b9864d554b3a6d84715e71a2ba7bc87d069dd14949cd907`
- verification command: `python -m champions_sim verify-replay --replay <path>`
- result: a separate process loaded the serialized record and re-executed every initialization, decision, event, RNG and state-hash boundary successfully

### Bundle and repository gates

- `python scripts/validate_sim01_bundle.py`: pass for `local_research`; distribution scope is rejected
- `python scripts/check_repo_size.py`: pass; no candidate exceeds `PD-001` / `PD-002`
- published Champions-specific damage reference: expected rolls `37..44` reproduced exactly

## Remaining external validation gates

- The single published damage example is reference grounding, not a BlueStacks/device capture.
- Critical odds/multiplier, residual rounding and compound-effect ordering remain provisional.
- The Catalog is a deliberately small 3v3 fixture, not the full Champions catalog.
- `PlayerObservation` is an instantaneous simulator snapshot. Exact UI HP-bar quantization and public event-history accumulation belong to the future BlueStacks adapter/agent observation layer.
- Official-source and device-observation bundles, source-by-source redistribution rights, full mechanics, AI/RL/LLM, and emulator control remain later phases.
