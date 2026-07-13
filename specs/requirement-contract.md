# Requirement Contract

## 目的

Pokémon Championsシングルバトルについて、AI、LLM、BlueStacks操作から独立した、正確で再現可能な対戦シミュレータを段階的に構築する。SIM-01の決定論的な限定参照実装を基盤に、SIM-02ではversion固定されたtarget poolと外部grounding evidenceに基づいて対応範囲を拡張する。

## 現在の判定

- P0統治ファイル: **COMPLETE**
- SIM-01ローカル参照bundle: **GO / ENGINEERING COMPLETE**
- SIM-02 Phase Contract: **SPECIFIED / IMPLEMENTATION SYNCHRONIZED**
- SIM-02ローカル基盤: **IMPLEMENTED / VERIFIED LOCALLY** — regulation、target pool、coverage、diff、synthetic rehearsal、read-only grounding、AI Env、generic mega
- SIM-02ローカルcoverage gate: **NO-GO** — TargetCapability/MechanicCoverage pipelineはsynthetic検証済みだが、M-B 235フォーム中explicit mapping/covered 0、intake未接続、production semantic/execution registry未完成
- SIM-02 Champions外部最終ゲート: **NO-GO**
- SIM-02 M-B candidate: **NO-GO** — 現M-B RuleSetでメガシンカunsupported、16形態未mapping/grounding、actual traceなし
- 公式Champions準拠としての昇格: **NO-GO**
- Catalog・派生物の再配布: **NO-GO**
- 理由: SIM-01に加え、公式source-bound M-B snapshot、235フォームtarget pool、再計算型coverage/diff/synthetic NO-GO rehearsal、strict read-only capture/evidence/AI Env、standard-formula検証付きgeneric mega、strict Replay decodeを実装した。旧ID `n<全国図鑑番号>` の暗黙推定は誤衝突し得るため廃止し、明示証拠がない235フォームをすべて未mappingへ戻した。source-bound mapping、capability-level coverage、外部grounding/holdout、actual/sealed-historical 48時間rehearsal、ADB ownership supervisor、M-B mega対応、旧PJ由来データのlicense確認は未完了である。ローカル基盤をdeployable candidate、公式準拠、環境coverage、再配布権へ読み替えない。

## Requirement Contract

| 項目 | 契約 |
|---|---|
| `purpose` | 決定論的なChampionsシングル対戦状態遷移と、その後のAI研究が依存できる再現基盤を作る。 |
| `success_metric` | P0/SIM-01は既存の工学ゲートを維持する。SIM-02は固定manifestに対する`target_pool_execution_coverage_rate == 1.0`、外部assertionの`verified_grounding_conformance_rate == 1.0`、`silent_fallback_count == 0`、sealed inputからcandidateまたは根拠付き`NO-GO`まで48時間以内を別々に測定する。 |
| `non_goals` | SIM-02では、target manifest外を対応済みと主張しない。RL/LLM/MCTSの勝率、構築最適化、BlueStacks操作、ランクマッチ操作、元データや旧PJ全体のコピーは対象外。人気度thresholdで対象を切り捨てない。 |
| `inputs_available` | SIM-01全基盤、source-bound M-B/M-A RegulationSnapshot、M-B 235フォームTargetPoolSnapshot、recomputed coverage/diffとsynthetic-NO-GO-only rehearsal v1、strict content-addressed CaptureStore、manifest-bound GroundingTrace、allowlist/evidence-bound AI Env、version/hash/seed付きpolicy-free `reset`/`step` adapter、source-bound Catalog intake、explicit mapping/fixed-point closure/6次元/probe/grounding/holdoutを持つTargetCapability pipeline、standard-stat-formula検証付きReplay互換generic mega、全階層strict Replay decoder。 |
| `inputs_missing` | M-B 235フォームの明示的なsource-bound Catalog mapping昇格とproduction capability bundle、全実effectのsemantic/execution registryとprobe factory、verified grounding assertion、開発から分離した実external holdout、candidate/live/sealed-historical用Rehearsal v2、actual 48時間evidence、外部ADB ownership supervisor、M-B 16メガ形態と同時発動順・stat formulaのChampions grounding、actual BlueStacks capture/trace、license確認済みCatalog snapshot。 |
| `assumptions` | AIの強さ、ローカル参照安定性、宣言target pool coverage、公式準拠、再配布権を別の目的変数とする。TargetPoolは人気度ではなくversion固定source corpusとRuleSet差分から作る。旧PJ由来データは`unverified`、ローカル研究限定、再配布不可として扱う。 |
| `constraints` | Python 3.10以上、原則stdlib＋pytest、seed付き決定論、完全状態と観測の分離、未知効果はfail-closed、出典追跡、大容量成果物のGit除外、実ゲーム運用はフレンド戦のみ。 |
| `risks` | Showdownや旧世代の仕様をChampionsへ誤適用すること、LLMの推測をルールへ混入すること、平均勝率で遷移誤りを隠すこと、未確認ライセンスのデータ再配布、生成物によるGit肥大化。 |
| `validation_plan` | SIM-01回帰とstrict Replay decodeに加え、TargetPoolの分母固定、coverage/diff再計算とforgery拒否、capture content identity/manifest hash、Env field/evidence allowlist、opponent exact-HP非漏洩、mega standard-formula照合、silent fallback mutationを継続検査する。外部holdoutとactual rehearsal/groundingは別gateとする。 |
| `go_no_go` | SIM-02ローカル基盤の継続利用はGO。Synthetic rehearsalはoperational successだがdeployable successではない。M-B candidate、actual device grounding、Champions準拠昇格はcoverageと外部証拠が揃うまでNO-GO。Catalog・capture・派生物の配布はlicense/contents reviewまでNO-GO。 |

## 公式準拠への昇格に必要な確認

1. RuleSetの各値に一次情報または実機観測の根拠があること。
2. 使用するCatalogデータについて、利用・保存・派生物のライセンス状態が記録されていること。
3. SIM-01で対応する効果と、未対応として拒否する効果の境界が列挙されていること。
4. 現行Schema・観測契約を実機イベント、HP表示、公開情報履歴へ照合し、差分をgolden fixtureへ固定すること。
5. `specs/sim-02-phase-contract.md`のTarget-pool選定契約に従い、execution coverage、grounding conformance、silent fallback、外部holdout、48時間rehearsalの最終ゲートを満たすこと。

## 次にやること

次は235フォームのstable target keyをCatalogへ順次mappingし、entityからeffect/trigger/RuleSet branchへのcapability closureを実装する。BlueStacks captureは、player/process検出だけでは実行せず、ADB daemon ownershipとlifecycleを外部supervisorが保証する契約を先に作る。その後にread-only actual captureをGroundingTraceへ変換してholdoutを作る。Generic mega contractはM-B 16形態へ拡張する前に、standard stat formulaと同時順を実機groundingする。Synthetic Rehearsal v1の結果だけでdeployable candidateを主張せず、candidate/live/sealed historicalには別versionを定義する。旧PJ由来データのlicenseが確認できない限り、元データ・Catalog・capture・派生データを再配布しない。
