# AI-01 Phase Contract

## Status

> 履歴注記（2026-07-14）: 本文はAI-01完了時点のphase snapshotであり、`v2未実装`や`次の大目的はSIM-02B`という記述は当時の判断を示す。SIM-02B後の現行状態と次目的は`specs/sim-02b-phase-contract.md`を正本とする。

- Trusted-local evaluation contract: **IMPLEMENTED / VERIFIED LOCAL**
- Champions readiness positive issuance: **NO-GO / NOT IMPLEMENTED**
- Policy process isolation: **NO-GO / NOT IMPLEMENTED**
- Strategic strength on the current synthetic simulator: **UNMEASURED**
- Pokémon Champions fidelity: **NO-GO** (SIM-02 external gates remain authoritative)
- Rank-1 equivalence: **UNMEASURED / CLAIM FORBIDDEN**

## Phase Contract

| Field | Contract |
|---|---|
| `phase_id` | `AI-01` |
| `phase_name` | Competitive Readiness Foundation |
| `purpose` | シミュレータ正確性と戦略的意思決定品質を別々に測れるようにする。SIM-02の証拠不足を隠さず、6体から3体を選ぶ選出、部分観測だけを受ける方策、paired評価、Replay検証、fail-closed readiness resolverと将来のseal契約を一つの再現可能な競技評価基盤へ統合する。 |
| `objective_variable` | 主目的変数は、候補視点の `net_utility_numerator = wins - losses` と `net_utility_denominator = completed_matches`、および符号対称に0方向へ切り捨てる `paired_net_utility_ppm`。terminal utilityはwin=`+1`、draw=`0`、loss=`-1`、shapingなし。report内の補助変数は`legal_action_rate_ppm`、`replay_verification_rate_ppm`、`private_state_delivery_violation_count`、`pair_completeness_rate_ppm`、`execution_error_count`、seat別outcome。選出fixture合格とreport再現性はreport値ではなくdone-condition test evidenceとする。これらはsynthetic corpus内の比較値であり、ランク順位の推定値ではない。 |
| `input_data` | 凍結SIM-01 Catalog/RuleSet/Battle fixture、version/hash付き6体synthetic roster fixture、実クラスのsource・MRO実効code/class constants/defaults/closuresとそのalias topology・mapping順/alias topologyを保持する型付き初期instance state・設定に結合したselection policy identityと`TeamPreviewProof`、同じ境界へ結合した`BoundAgent`、engine seedとagent seed、宣言済みevaluation partition identity（現goldenはdevelopmentのみ）、SIM-02 source-to-capability v1 compilation一式。実M-Bの未検証入力はactionable candidateとして受け取らない。 |
| `explanatory_variables` | agent/policy version、team/roster identity、選出順、対戦相手、seat、paired seed、engine RNG lineage、agent RNG lineage、Catalog/RuleSet hash、scenario partition、terminal outcome、decision count、Replay hash、evidence/readiness blockers。相手の非公開set、未公開技、完全状態は説明変数にも入力にも含めない。 |
| `provisional_coefficients` | 学習率、探索回数、LLM重み、人気度閾値、勝率昇格閾値、Elo換算係数は置かない。terminal utilityは比較のための固定契約であり調整しない。synthetic corpusを母集団と見なさないため信頼区間による外部一般化は行わず、exact countとpartition identityを出す。64 seed-pairのfrozen regression件数だけを`PD-009`として明示し、強度昇格閾値には使わない。将来係数を導入する場合は先に`PD-*`へ登録する。 |
| `output_models` | 自己申告VERIFIEDを拒否するreadiness resolverと将来用`ResolvedChampionsReadiness`契約（現v1からの正規発行は不可）、初期状態制約付き`TeamPreviewRoster` / public observation / commit / reveal / ordered selection / `TeamPreviewProof` / materialized battle、`AgentIdentity` / `BoundAgent`、`ArenaPlan` / Replay evidence / paired match record / aggregate report / evidence manifest / candidate-NO-GO decision、公開情報だけを使うselection baselineとtype-aware battle baseline。 |
| `downstream_consumers` | information-set search、offline/online RL、LLMによる環境分析と構築仮説、構築・選出最適化、regulation別benchmark、将来のprivate-match adapter。下流は`scope`、`rank1_equivalence_status`、readiness blockersを上書きしてはならない。 |
| `uncertainty_rules` | `synthetic_local`と`champions_candidate`を分離する。callerが`VERIFIED`や任意hashを自己申告してもcandidateにしない。現v1はintake-only、空development corpus、`catalog_emit_eligible=false`を型とSchemaで強制するためreadiness sealの正規発行は構造的に到達不能であり、fail-closed検証器としてのみ扱う。v2がresolver-backed promotion、exact scenario membership、external holdoutまで再計算できるようになるまでは発行可能と記述しない。Arena report JSONまたはevidence hash単体は実行証明・認証ではない。通常CLIの保存物はprebattle run本体を含まないbattle-Replay archiveであり、完全な`verify_arena_run`には同じ選出入力の再生成が必要である。`private_state_delivery_violation_count`はarenaが渡したpayloadの境界指標であり、同一processのglobal読取を証明しないため`policy_process_isolation_not_implemented`を必須blockerとする。policy-facing env resultからfull-state/sealed-input/private-event/engine-seed/RNG-state/fixture identityを除外し、privileged lineageはReplayへ限定する。外部証拠、M-B coverage、grounding、holdoutのいずれかが不足すればChampions側は理由付きNO-GO。reportは常に`rank1_equivalence_status: unmeasured`、`rank1_equivalence_claim_allowed: false`を保持する。 |
| `done_conditions` | (1) forged VERIFIED/hash/fixture alias/SIM-01-as-M-Bを再計算で拒否し、現v1からsealを発行しない、(2) 6→順序付き3の双方commit/reveal、全HP/PP・runtime flag初期値、Catalog/RuleSet/source/live-runtime/initial-state/config/seed/roster/materialized-state結合proof、mapping順/alias topology/未申告state差・選出中state変化拒否、policyへdetached roster graphだけを渡しcommit前leakage 0、(3) 全seedをcandidateの両seatで実行しpair completeness 100%、(4) engine RNGとagent RNGを分離しcandidate/opponent role streamをseat間固定、(5) 完走reportのlegal action 100%、execution error 0、private-state delivery violation 0、(6) ReplayをengineとBoundAgentで再実行照合し100%、多相report/Replay/state/engineとfactory内code差替えを拒否、(7) 同一入力からbyte-identical report/evidence hash、(8) 公開情報baselineが選出・戦術goldenを全件通過しRandom referenceよりsynthetic paired net utilityが正、(9) policy-facing env resultが非公開bench set・fixture ID・engine seed変更にbyte-identical、reportが外部未測定とprocess-isolation不足を明示、(10) 通常CLIがreport・全Replay・manifestをGit外へ保存し、disk Replayをengine検証する。非永続は明示`--summary-only`だけ。prebattle非内包をstandalone認証と呼ばない、(11) 全既存回帰とsize gate合格。 |
| `anti_patterns` | SIM-01の勝率をChampionsまたはランク1相当へ読み替える、方策へ完全BattleStateや相手DecisionRequestを渡す、plan identityと異なるfactoryを実行する、任意のprebattle hashを受理する、report JSONだけをverified evidenceとして昇格する、同じpolicy instanceを複数legで再利用する、agent RNGをseat名だけで分岐する、engine RNGをagentへ渡す、holdoutで調整する、LLMに合法手・ルール・rewardを決めさせる、self-declared VERIFIEDを信頼する、人気度で対象分母を縮小する、大容量run/model/replayをGitへ登録する。 |

## Gate decision

AI-01のうち、信頼済み同一process・単一synthetic fixtureでの選出／対戦／Replay評価配線は **ENGINEERING COMPLETE / LOCAL GO** とする。readiness正経路、process-isolated policy、実M-B scenario corpus、実RL/LLM学習、BlueStacks入力、実機conformance、戦略強度昇格、ランク1相当の宣言は完了条件に含めず **NO-GO** のままである。AI-01完了時点の次の大目的は`SIM-02B Production Catalog Promotion + Evidence-backed Scenario Corpus`とした。現行の次目的は`specs/sim-02b-phase-contract.md`を参照する。

## Rank-1 readiness model

ランク1相当への昇格は、少なくとも次の独立gateをすべて必要とする。

1. **Environment fidelity** — SIM-02のM-B coverage、grounding、holdout、silent-fallback gate。
2. **Decision quality** — AI-01以降のpartition-bound competitive evaluation。
3. **Construction and selection** — 6体構築と3体選出を含む規則変更耐性。
4. **External calibration** — 人間上位層または同等の固定外部benchmarkに対する盲検評価。

本Phaseが直接満たすのは2と3の測定配線だけであり、達成強度そのものではない。
