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
| `REQ-SIM02-008` | explicit mappingから合法到達capabilityを固定分母として閉包する | Target Mapping / Target Pool Manifest / Target Capability Schemas | `src/champions_sim/capabilities`、`src/champions_sim/compiler` | exact pool一致、same-signature dedupe＋origin refs、unresolved denominator fail-closed、公式235 missing拒否。実M-Bは0 resolved、219 unresolved、16 conflict、118 target rows、count/rate null | verified_local compiler integration; evidence promotion pending |
| `REQ-SIM02-009` | 6実行次元、grounding、silent fallback、holdoutをcaller入力なしで再計算する | Execution/Grounding/MechanicCoverage/Holdout Schemas | compiler semantic/execution/probe registry、capability coverage/grounding/holdout builders | 6次元各欠落、`rng:none`、explicit unsupported、silent mutation、resolver rejection、holdout overlap/new/unknown。実M-Bはexecution gap 118、個別executor未取得118、silent fallback 0 | verified_local compiler integration; positive executors/actual evidence pending |
| `REQ-SIM02-010` | sealed source lockから理由付きNO-GOを一コマンド・content-addressed生成する | Source-to-Capability Report / intake-only Production Catalog Input Schemas | `scripts/build_source_to_capability_bundle.py`、`src/champions_sim/compiler` v1 | 同入力のreport/doc byte一致、report/artifact改変拒否、`--require-candidate`、Gitignored output制限。v1はverified/emit-eligibleと非空corpusを受理しないためpositive candidateは構造的に対象外 | verified_local diagnostic compiler; positive path not implemented |
| `REQ-SIM02-003` | 全TargetCapabilityを外部groundingへtraceする | GroundingTrace/Capture Schema、SIM-02 grounding contract | capture models/store、GroundingTrace、EnvObservation | local contract/schema tests。actual実機traceとcapability completenessは未取得 | verified_local contracts, blocked_external |
| `REQ-SIM02-004` | unknown・unsupported・unverifiedのsilent fallbackを0にする | SIM-02 silent fallback contract | coverage blocker、unknown legal mask、engine fail-closed、simultaneous mega fail-closed | regulation/grounding/mega mutation tests、synthetic report `silent_fallback_count: 0` | verified_local for implemented paths; full pool blocked |
| `REQ-SIM02-005` | sealed inputから48時間以内にcandidateまたは正しいNO-GOを出す | SIM-02、PD-008、RehearsalReport Schema v1 | v1はsynthetic_internal NO-GO専用。coverage/diffをsealed入力から再計算 | forgery/参照不一致/candidate/live拒否、operational success、deployable false。actual/sealed historical v2未定義 | provisional, verified_local NO-GO plumbing, blocked_external |
| `REQ-SIM02-006` | local evidenceとChampions外部最終gateを分離する | SIM-02 current evidence/final gate | reportの`rehearsal_kind`、outcome、operational/deployable flags | synthetic candidate昇格拒否tests、AUD-SIM02-001/002/005/006 | verified_local, blocked_external |
| `REQ-SIM02-007` | M-Bのメガシンカをmandatory capabilityとして扱う | 公式M-B page 776、Season M-4 page 795、SIM-02、Catalog/RuleSet/Replay Schema | generic単側mega state/action/event、1戦1回、永続、Replay、versioned standard stat formulaでbase/mega双方を照合 | formula tamper、schema、state、Replay tests。同時mega順、Champions formula一致、16形態groundingはfail-closed/未達 | implemented generic contract, blocked_external for M-B |
| `REQ-DATA-001` | RuleSetをversion/hash付きで固定する | RuleSet Schema | `RuleSetSnapshot/load_ruleset`、fixture | recursive Schema＋semantic bundle validation | provisional, verified_local |
| `REQ-DATA-002` | Catalogをversion/hash/source付きで固定する | Catalog / Production Catalog Input Schemas | `CatalogSnapshot/load_catalog`、source-bound runtime candidate | reference validation、manifest/evidence/artifact hash、未知priority/effect/ability/itemをfail-closed。現候補はspecies 213、moves 490、abilities 180、items 117 | restricted_local, blocked_external |
| `REQ-DATA-003` | Battle fixtureのID・team・stats・movesを固定する | Battle fixture Schema | `load_battle_fixture` | recursive Schema＋cross-reference validation | verified_local |
| `REQ-DATA-004` | Replayにbundle hash、RNG、初期化、全decision、結果を保存する | Replay v2 Schema | core replay、runner | generated Replay recursive Schema、roundtrip、verify | verified_local; bundle-bound |
| `REQ-DATA-005` | 外部sourceの出典、license、size、hashを追跡する | Source manifest Schema、Git policy | legacy manifestに6参照元＋Catalog fixtureを記録 | bundle validator | restricted_local, blocked_external |
| `REQ-DATA-006` | 旧PJをコピーせずM-B 235件のCatalog mapping候補とentity unionを再生成する | Catalog Intake / Source Lock / Mapping Evidence Schemas | `src/champions_sim/intake`、`src/champions_sim/compiler`、M-B source lock | 213 usage crosswalk、22 exact-name candidate、16 detail conflict隔離、9 artifact hash/count完全一致、88 intake blockers。昇格判定は0 resolved、219 unresolved、16 conflict | verified_local intake/bridge, restricted_local, promotion blocked |
| `REQ-GIT-001` | 大容量artifactをGitから除外する | Git Artifact Policy | `.gitignore`、compiler output-root guard | `git ls-files --cached --others --exclude-standard`、full compiler artifactを`data/processed`外へ書く要求を拒否 | verified_local |
| `REQ-GIT-002` | 2 MiB / 256 KiBの暫定上限を検査する | PD-001/002 | `scripts/check_repo_size.py` | governance size tests | provisional, verified_local |
| `REQ-TECH-001` | Python 3.10以上、原則stdlib＋pytestを使う | `pyproject.toml` | `src/champions_sim`、scripts | full pytest suite | verified_local |
| `REQ-GROUND-001` | 公開済みChampionsダメージ参照を再現する | SIM-01、PD-003/004 | damage calculator | `tests/test_golden_grounding.py` | verified_local reference, blocked_external for full conformance |
| `REQ-GROUND-002` | raw captureをGit外・content-addressed・read-only provenance付きで保存する | Capture Manifest Schema、Git policy | strict `CaptureStore` | content-derived capture ID、artifact bytes/manifest/path/unknown-key strict verify、manifest hash、tamper復旧、local-only/distribution拒否test | verified_local contract; no actual capture |
| `REQ-GROUND-003` | BlueStacksを起動・操作せず診断し、外部所有権が保証された場合だけread-only captureする | SIM-02、Capture contract | `discover_bluestacks`、`AdbObservationCapture`、diagnostic script | generic adbをBlueStacks daemon証拠にせず、daemon side-effect riskを常時block。外部ownership supervisor未実装 | verified_local diagnostics, capture blocked_external |
| `REQ-AIENV-001` | instant observation、public history、legal mask、grounding provenanceをAI境界で分離する | AI Env Observation Schema | `EnvObservation` draft、`ValidatedEnvObservation`、resolver-backed validation | field/event allowlist、実store/trace/evidence binding、unknown vs all-illegal、blocker/actionable排他、missing trace/capture拒否 | verified_local strict promotion gate; actual device adapter pending |
| `REQ-AIENV-002` | version/hash/seed付きのpolicy-free `reset`/`step`環境を提供する | AI Env adapter dataclass contract | `src/champions_sim/env` | 同seed/choice byte一致、hidden HP/stats非漏洩、policy/privileged lineage分離、非公開bench set・fixture ID・engine seed変更のpublic result byte非干渉、stale/cross-episode/illegal拒否、reset isolation、candidate evidence fail-closed | verified_local adapter; reward/policy absent by design |
| `REQ-AI01-001` | simulator fidelityとdecision qualityを別目的変数で測る | AI-01 Phase Contract、Arena Report Schema | `src/champions_sim/arena/models.py` | summary再計算、pair/seat/seed完全性、改変拒否、`rank1_equivalence_status: unmeasured`固定 | verified_local; external strength blocked |
| `REQ-AI01-002` | self-declared VERIFIEDでSIM-02 NO-GOを迂回させない | SIM-02/AI-01 readiness contract | `src/champions_sim/env/readiness.py`、sealed env binding | fake hash、candidate flag再署名、artifact欠落、SIM-01偽装、直接seal構築、fixture/record aliasを拒否。v1はintake-onlyなので正規seal発行なし | verified_local fail-closed resolver; positive issuance not implemented |
| `REQ-AI01-003` | 6体rosterから順序付き3体を双方同時に選ぶ | AI-01 Team Preview contract | `src/champions_sim/prebattle` | exact 6→3、commit/reveal、Catalog/RuleSet/nonce/order/roster/materialized-state、source/runtime/typed-initial-state/config identity、mapping順・alias topology・未申告state差・選出中state変化拒否、detached own-roster graph、private set非干渉、同一policy再利用・途中状態・Item Clause・種族非合法技拒否 | verified_local synthetic |
| `REQ-AI01-004` | 部分観測だけで両seatを公平に評価する | AI-01 Arena Plan/Report Schema | `run_paired_arena`、`runner.run_battle(policy_seed=...)` | paired engine/agent seed、role-fixed RNG、side swap、fresh/exact BoundAgent、private setからpublic battle IDへの非干渉、Replay再検証100%、default evidence manifest、byte-identical report | verified_local trusted-process synthetic; process isolation/external corpus blocked |
| `REQ-AI01-005` | 非自明な選出・行動baselineを持つ | AI-01 Phase Contract、PD-009 | `TypeCoverageTeamSelectionPolicy`、`TypeAwareDamagePolicy`、benchmark CLI | tactical type fixture、selection privacy、64 pair/128 match frozen golden、Random referenceへ正のutility | verified_local engineering baseline only |
| `REQ-SIM02B-001` | intake診断v1とpromotion v2を分離し、証拠付きscenario corpusからだけreadinessを発行する | SIM-02B Phase Contract | `src/champions_sim/promotion` v2 compiler、`src/champions_sim/env/readiness_v2.py`、V2 compilation/report/scenario/readiness schemas | exact Compilation再解決、test-authoritative engineering seal、将来production projectionの型検査、source/Catalog/RuleSet/grounding/scenario/partition/probe/document hash mutation拒否、portable manifest/schema、resolver-backed positive E2E、現M-B exact NO-GOをfocused testsで確認 | local engineering verified; production issuance disabled pending external trust anchor/evidence |
| `REQ-SIM02B-002` | local manifestのauthority/license/status自己申告でproduction候補を発行しない | SIM-02B trust-anchor clarification | `src/champions_sim/promotion/compiler.py`、production forgery E2E | source/license/Regulation/timingを整合再署名した完全local claimをartifact-root外trust anchor不足で拒否。assessmentへ専用blockerを追加 | verified fail-closed; external trust-anchor verifier not implemented |
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

`source-to-capability-bundle-v1`はintake診断identityとして次を同じreport hashへ束ねる。v1の`ProductionCatalogInput`はverified promotion、final denominator、emit eligibilityを拒否し、compilerは空development corpusを固定するため、このlineageだけではcandidate/readinessを発行できない。

```text
catalog_intake_hash
+ mapping_evidence_hash
+ production_catalog_input_hash
+ runtime_catalog_hash
+ semantic_compilation_hash
+ target_pool_manifest_hash
+ target_capability_set_hash
+ execution_compilation_hash
+ probe_plan_hash + probe_report_hash
+ grounding_resolution_hash
+ mechanic_coverage_matrix_hash
```

SIM-02B v2はpositive promotionを次の一体的なportable identityへ束ねる。`test_authoritative`と`production_champions`はresolverがsource/licenseから導出し、同じCompilation内でscopeを混在させない。全documentのUTF-8 byte digestを`document_set_hash`へ、下記projectionを`compilation_hash`へ、さらにreadiness projectionへ結合する。

```text
source_resolution_set_hash + artifact_binding_hash
+ regulation_hash + target_pool_hash
+ catalog_hash + ruleset_hash + mapping_evidence_hash
+ target_pool_manifest_hash + target_capability_set_hash
+ semantic_compilation_hash + execution_compilation_hash
+ development construction/scenario corpus hash
+ external holdout scenario/verification hash
+ partition_manifest_hash
+ grounding_resolution_hash + engine_probe_report_hash
+ mechanic_coverage_matrix_hash + timing_evidence_hash
+ promotion_report_hash + document_set_hash
-> production promotion compilation_hash
-> scope-bound Champions readiness v2 seal_hash
```

このidentityは同一性と完全性を検査するもので、source真正性、Champions実機準拠、ランク1相当をhash単体で証明しない。resolver再解決、engine/Replay再実行、grounding、sealed holdoutを再検証できることが昇格条件である。

target poolのversionが変わった場合、旧coverage reportを新しい分母へ流用しない。

AI-01 Arena reportは次のidentityを追加で保存する。

```text
candidate agent ID/version/implementation hash/source hash/live-runtime hash/config hash
+ opponent agent ID/version/implementation hash/source hash/live-runtime hash/config hash
+ observation contract
+ Catalog/RuleSet/initial-state hash
+ prebattle Catalog/RuleSet + selection source/live-runtime/initial-state/config + complete-session hash + proof hash
+ partition + paired engine seed + independent agent seed
+ candidate seat/terminal outcome/utility
+ Replay hash + final-state hash + verification result
+ provisional_decision_ids
+ scope blockers + rank1 equivalence status
```

通常CLIはreport、全Replay、各file SHA-256を持つevidence manifestをGitignored `runs/`へ置き、GitにはSchema、小さなgolden summary、hashだけを残す。保存Replayはstrict load後にengine再実行できる。一方、manifestは6体prebattle run本体を含まず`prebattle_evidence_mode: regeneration_required`なので、standalone Arena認証bundleではない。完全な`verify_arena_run`には同一prebattle入力とexact BoundAgentの再生成が必要である。evidence hashは認証ではない。`PD-009`の64 pairは回帰予算であり昇格閾値ではない。

現M-B snapshotのreadinessは次のように分離して報告する。

```text
eligible target members: 235
Catalog explicitly mapped / covered members: 0
mapping resolved / unresolved / conflict: 0 / 219 / 16
Catalog-wide semantic selectors: 788
target capability rows / execution gaps: 118 / 118
capability-specific executors: 0 (unexpected/not executed: 118)
published capability coverage counts/rates: null (denominator non-final)
silent fallback count: 0
required mega_evolution in current M-B RuleSet: unsupported
actual BlueStacks GroundingTrace: 0
SIM-02B diagnostic blocking reasons / promotion blockers: 718 / 720
production source trust anchor: not implemented; issuance disabled
SIM-02B rank1 equivalence status: unmeasured
```

これはmember-level readinessであり、capability-level execution coverageまたは実環境採用率ではない。
