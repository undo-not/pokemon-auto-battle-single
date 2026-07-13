# Traceability

Statusは次を使う。

- `specified`: 契約のみ
- `implemented`: 実装済みだが検証が不足
- `verified_local`: 現在の限定fixture・ローカル研究scopeで検証済み
- `provisional`: 仮置き値を含む
- `restricted_local`: licenseまたは出典制約によりローカル研究限定
- `blocked_external`: 実機・一次情報・license等の外部確認待ち

| Requirement | Purpose | Specification / Schema | Implementation | Tests / Evidence | Status |
|---|---|---|---|---|---|
| `REQ-P0-001` | 目的、非目的、scope別GO/NO-GOを固定する | Requirement Contract | governance docs | spec audit log | verified_local |
| `REQ-P0-002` | Phaseの目的変数と完了条件を固定する | SIM-01 Phase Contract | local/official/distribution gate分離 | AUD-P0-001/002 | verified_local, blocked_external |
| `REQ-P0-003` | SIM-02のtarget coverage、grounding、fallback、48時間gateを固定する | SIM-02 Phase Contract | scope別gateとTarget-pool選定契約を実装状態へ同期 | AUD-SIM02-001〜006 | verified_local, blocked_external |
| `REQ-SIM-001` | 同一bundle・状態・seedから同一遷移を返す | SIM-01、Replay v2 Schema | `core/rng.py`、`canonical.py`、`engine.py`、`runner.py` | 同seed 100回のbyte一致、deterministic engine/replay tests、10k smoke | verified_local |
| `REQ-SIM-002` | 合法手を生成し、illegal/stale choiceを拒否する | SIM-01、Replay decision definitions | `BattleEngine.required_decisions/advance`、core decision models | core decisions、engine integration | verified_local |
| `REQ-SIM-003` | 未確認・未実装効果をfail-closedにする | RuleSet/Catalog Schema、SIM-01 | `UnsupportedMechanic`、Catalog effect validation、damage fail-closed | catalog validation、engine unsupported-state/effect tests | verified_local for listed mechanics |
| `REQ-SIM-004` | 完全状態とプレイヤー観測を分離する | SIM-01、core model contract | `BattleState.observation_for` | opponentは`hp`/`max_hp`/`hp_fraction_millionths`/statsを全て`None`、bench/move/item/ability漏洩拒否 | verified_local |
| `REQ-SIM-005` | 仮置き値と出典をReplayへ伝播する | PD-003/004/007、Replay v2 Schema | RuleSet loader、runner、Replay v2 | replay runner contract、bundle validator | provisional, verified_local transport |
| `REQ-SIM-006` | 10,000件seeded smokeを昇格ゲートにする | PD-005、SIM-01 | CLI、`run_random_batch` | 10,000 battles / 195,319 windows / 2,462,659 events / exception 0 | verified_local |
| `REQ-SIM-007` | Replayからexact bundleで遷移を再実行して改変を検知する | Replay v2 Schema | `ReplayRecord`、strict JSON decoder、`verify_replay` | 全階層unknown/duplicate key拒否、roundtrip、bundle/init/action/transition drift、別process CLI test | verified_local |
| `REQ-SIM02-001` | 人気度thresholdを使わずtarget poolを固定する | SIM-02 Target-pool選定契約、Regulation/TargetPool Schema | M-B公式eligible listを235 unique dex/form/variant keyへ固定 | loader/schema tests、source manifest record count | verified_local |
| `REQ-SIM02-002` | 固定分母に対する実行coverageを測る | SIM-02 objective variables、CoverageGap Schema | `build_coverage_gap_report` | 235 denominator、explicit mapped/covered 0、unmapped 235、mega unsupportedをblocker化。`n<dex>`暗黙mappingを廃止 | implemented, blocked_external |
| `REQ-SIM02-008` | explicit mappingから合法到達capabilityを固定分母として閉包する | Target Mapping / Target Pool Manifest / Target Capability Schemas | `src/champions_sim/capabilities` | exact pool一致、same-signature dedupe＋origin refs、unresolved denominator fail-closed、公式235 missing拒否 | verified_local synthetic pipeline; M-B integration pending |
| `REQ-SIM02-009` | 6実行次元、grounding、silent fallback、holdoutをcaller入力なしで再計算する | Execution/Grounding/MechanicCoverage/Holdout Schemas | capability coverage/probes/grounding/holdout builders | 6次元各欠落、`rng:none`、explicit unsupported、silent mutation、resolver rejection、holdout overlap/new/unknown | verified_local synthetic pipeline; production registries/actual evidence pending |
| `REQ-SIM02-003` | 全TargetCapabilityを外部groundingへtraceする | GroundingTrace/Capture Schema、SIM-02 grounding contract | capture models/store、GroundingTrace、EnvObservation | local contract/schema tests。actual実機traceとcapability completenessは未取得 | verified_local contracts, blocked_external |
| `REQ-SIM02-004` | unknown・unsupported・unverifiedのsilent fallbackを0にする | SIM-02 silent fallback contract | coverage blocker、unknown legal mask、engine fail-closed、simultaneous mega fail-closed | regulation/grounding/mega mutation tests、synthetic report `silent_fallback_count: 0` | verified_local for implemented paths; full pool blocked |
| `REQ-SIM02-005` | sealed inputから48時間以内にcandidateまたは正しいNO-GOを出す | SIM-02、PD-008、RehearsalReport Schema v1 | v1はsynthetic_internal NO-GO専用。coverage/diffをsealed入力から再計算 | forgery/参照不一致/candidate/live拒否、operational success、deployable false。actual/sealed historical v2未定義 | provisional, verified_local NO-GO plumbing, blocked_external |
| `REQ-SIM02-006` | local evidenceとChampions外部最終gateを分離する | SIM-02 current evidence/final gate | reportの`rehearsal_kind`、outcome、operational/deployable flags | synthetic candidate昇格拒否tests、AUD-SIM02-001/002/005/006 | verified_local, blocked_external |
| `REQ-SIM02-007` | M-Bのメガシンカをmandatory capabilityとして扱う | 公式M-B page 776、Season M-4 page 795、SIM-02、Catalog/RuleSet/Replay Schema | generic単側mega state/action/event、1戦1回、永続、Replay、versioned standard stat formulaでbase/mega双方を照合 | formula tamper、schema、state、Replay tests。同時mega順、Champions formula一致、16形態groundingはfail-closed/未達 | implemented generic contract, blocked_external for M-B |
| `REQ-DATA-001` | RuleSetをversion/hash付きで固定する | RuleSet Schema | `RuleSetSnapshot/load_ruleset`、fixture | recursive Schema＋semantic bundle validation | provisional, verified_local |
| `REQ-DATA-002` | Catalogをversion/hash/source付きで固定する | Catalog Schema | `CatalogSnapshot/load_catalog`、fixture | reference validation、manifest artifact hash | restricted_local, blocked_external |
| `REQ-DATA-003` | Battle fixtureのID・team・stats・movesを固定する | Battle fixture Schema | `load_battle_fixture` | recursive Schema＋cross-reference validation | verified_local |
| `REQ-DATA-004` | Replayにbundle hash、RNG、初期化、全decision、結果を保存する | Replay v2 Schema | core replay、runner | generated Replay recursive Schema、roundtrip、verify | verified_local; bundle-bound |
| `REQ-DATA-005` | 外部sourceの出典、license、size、hashを追跡する | Source manifest Schema、Git policy | legacy manifestに6参照元＋Catalog fixtureを記録 | bundle validator | restricted_local, blocked_external |
| `REQ-DATA-006` | 旧PJをコピーせずM-B 235件のCatalog mapping候補とentity unionを再生成する | Catalog Intake / Source Lock Schema | `src/champions_sim/intake`、`scripts/build_catalog_intake.py`、M-B source lock | 213 usage crosswalk、22 exact-name candidate、16 detail conflict隔離、9 artifact hash/count完全一致、88 blockers、intake attack tests | verified_local intake, restricted_local, promotion blocked |
| `REQ-GIT-001` | 大容量artifactをGitから除外する | Git Artifact Policy | `.gitignore` | `git ls-files --cached --others --exclude-standard` | verified_local |
| `REQ-GIT-002` | 2 MiB / 256 KiBの暫定上限を検査する | PD-001/002 | `scripts/check_repo_size.py` | governance size tests | provisional, verified_local |
| `REQ-TECH-001` | Python 3.10以上、原則stdlib＋pytestを使う | `pyproject.toml` | `src/champions_sim`、scripts | full pytest suite | verified_local |
| `REQ-GROUND-001` | 公開済みChampionsダメージ参照を再現する | SIM-01、PD-003/004 | damage calculator | `tests/test_golden_grounding.py` | verified_local reference, blocked_external for full conformance |
| `REQ-GROUND-002` | raw captureをGit外・content-addressed・read-only provenance付きで保存する | Capture Manifest Schema、Git policy | strict `CaptureStore` | content-derived capture ID、artifact bytes/manifest/path/unknown-key strict verify、manifest hash、tamper復旧、local-only/distribution拒否test | verified_local contract; no actual capture |
| `REQ-GROUND-003` | BlueStacksを起動・操作せず診断し、外部所有権が保証された場合だけread-only captureする | SIM-02、Capture contract | `discover_bluestacks`、`AdbObservationCapture`、diagnostic script | generic adbをBlueStacks daemon証拠にせず、daemon side-effect riskを常時block。外部ownership supervisor未実装 | verified_local diagnostics, capture blocked_external |
| `REQ-AIENV-001` | instant observation、public history、legal mask、grounding provenanceをAI境界で分離する | AI Env Observation Schema | `EnvObservation` draft、`ValidatedEnvObservation`、resolver-backed validation | field/event allowlist、実store/trace/evidence binding、unknown vs all-illegal、blocker/actionable排他、missing trace/capture拒否 | verified_local strict promotion gate; actual device adapter pending |
| `REQ-AIENV-002` | version/hash/seed付きのpolicy-free `reset`/`step`環境を提供する | AI Env adapter dataclass contract | `src/champions_sim/env` | 同seed/choice byte一致、hidden HP/stats非漏洩、stale/cross-episode/illegal拒否、reset isolation、candidate evidence fail-closed | verified_local adapter; reward/policy absent by design |
| `REQ-GROUND-004` | GroundingFrameをcapture contentとmanifest identityへ結合する | GroundingTrace/Capture Schema | `capture_id + capture_manifest_hash`、`validate_grounding_trace_against_store` | conflicting/wrong manifest hash、missing capture、artifact改竄、evidenceなしconformant traceを拒否 | verified_local resolver contract; no actual trace |
| `REQ-OBS-001` | 瞬間観測とUI量子化・履歴memoryを分離する | SIM-01 observation contract | `BattleState.observation_for` | opponentのhp/max_hp/exact fractionを`None`、observation leakage tests。UI adapterは未実装 | verified_local snapshot, adapter pending |
| `REQ-TYPE-001` | sparse type chartの省略pairを倍率1とする | Catalog Schema、SIM-01 type chart contract | `CatalogSnapshot.type_effectiveness` | Catalog semantic validation、engine tests | verified_local |
| `REQ-LIC-001` | license不明データをローカル研究に限定する | Source manifest Schema、Requirement Contract | usage policy、bundle validator | local mode pass、distribution mode rejection | restricted_local |
| `REQ-OPS-001` | 実ゲーム運用をフレンド戦へ限定する | Requirement Contract、README | read-only diagnostics/capture contractのみ実装。入力adapterは未実装 | local diagnosticsはplayer/ADB停止でfail-closed。actual operational review未実施 | verified_local safety boundary, input phase pending |

## Artifact lineage

Replay v2は次のidentityを保存する。

```text
simulator_version
+ engine_semantics_version
+ ruleset_id + ruleset_content_hash
+ catalog_id + catalog_content_hash
+ initial_state_hash
+ initial/after-initialization/final RNG
+ provisional_decision_ids
+ source_manifest_ids
```

現在のCatalog source manifestは旧PJ commit `59bf57c...`の6参照元と、ローカルfixtureのsize/SHA-256を記録する。元ファイル本体はこのリポジトリへコピーしない。

Replay v2は初期状態、decision、RNG、eventsを内包するが、Catalog/RuleSet内容そのものは内包しない。`verify_replay`には、記録されたcontent hashと一致する外部bundleが必要である。

SIM-02 candidateはReplay identityに加えて、次のtupleを保存する。

```text
regulation_snapshot_hash
+ target_pool_manifest_hash
+ target_capability_set_hash
+ grounding_assertion_set_hash
+ external_holdout_id
+ rehearsal_report_hash
```

target poolのversionが変わった場合、旧coverage reportを新しい分母へ流用しない。

現M-B snapshotのreadinessは次のように分離して報告する。

```text
eligible target members: 235
Catalog explicitly mapped / covered members: 0
unmapped target members: 235
required mega_evolution in current M-B RuleSet: unsupported
actual BlueStacks GroundingTrace: 0
```

これはmember-level readinessであり、capability-level execution coverageまたは実環境採用率ではない。
