# Requirement Contract

## 目的

Pokémon Championsシングルバトルについて、AI、LLM、BlueStacks操作から独立した、正確で再現可能な対戦シミュレータを段階的に構築する。SIM-01の決定論的な限定参照実装を基盤に、SIM-02ではversion固定されたtarget poolと外部grounding evidenceに基づいて対応範囲を拡張する。AI-01ではシミュレータ正確性と戦略的意思決定品質を別gateにし、6→3選出、部分観測方策、paired評価を実装する。

## 現在の判定

- P0統治ファイル: **COMPLETE**
- SIM-01ローカル参照bundle: **GO / ENGINEERING COMPLETE**
- SIM-02 Phase Contract: **SPECIFIED / IMPLEMENTATION SYNCHRONIZED**
- SIM-02ローカル基盤: **IMPLEMENTED / VERIFIED LOCALLY** — regulation、target pool、coverage、diff、source-to-capability compiler、synthetic rehearsal、read-only grounding、AI Env、generic mega
- SIM-02ローカルcoverage gate: **OPERATIONAL SUCCESS / REASONED NO-GO** — 実M-B intakeから一コマンドでcompileし、235フォーム中resolved/verified mapping 0、unresolved 219、conflict 16、target capability row 118、execution gap/個別executor未取得 118、silent fallback 0を再現した。分母未確定のためcoverage count/rateは`null`で、fallback 0をpositive execution証拠へ読み替えない
- SIM-02 Champions外部最終ゲート: **NO-GO**
- SIM-02 M-B candidate: **NO-GO** — 現M-B RuleSetでメガシンカunsupported、16形態未mapping/grounding、actual traceなし
- AI-01 Trusted-local Competitive Evaluation: **GO / ENGINEERING COMPLETE WITHIN SYNTHETIC SCOPE** — 6→3 sealed team preview、paired-seat arena、公開情報selection/battle baseline、Replay再実行検証、既定のGit外battle-Replay archive保存を実装。process isolation、self-contained prebattle evidence、Champions readiness正経路は含まない
- SIM-02B promotion/readiness v2: **GO / LOCAL ENGINEERING COMPLETE** — v1をnegative-onlyのまま凍結し、resolver-backed source/license/artifact、executable scenario、grounding、engine probe、lineage分離holdout、可搬Compilationを再検証する別型を実装。test-authoritative sealは`champions_candidate=false`
- 現行M-B SIM-02B data gate: **NO-GO** — verified mapping 0/235、unresolved 219、conflict 16、target capability row/execution gap 118/118、promotion blocker 720。artifact-root外trust anchorも未実装で、production sealは発行しない
- AI-01 synthetic benchmark: **128戦完走 / ENGINEERING EVIDENCE ONLY** — candidate 126勝0分2敗、Replay verification 100%、`champions_candidate=false`、`rank1_equivalence_status=unmeasured`
- ランク1相当の強度: **UNMEASURED / CLAIM FORBIDDEN** — 実M-B executable bundle、partitioned scenario corpus、外部上位層較正がない
- 公式Champions準拠としての昇格: **NO-GO**
- Catalog・派生物の再配布: **NO-GO**
- 理由: SIM-01に加え、公式source-bound M-B snapshot、235フォームtarget pool、source-lock intakeからMechanicCoverageMatrixまでの一コマンドcompiler、再計算型coverage/diff/synthetic NO-GO rehearsal、strict read-only capture/evidence/AI Env、standard-formula検証付きgeneric mega、strict Replay decodeを実装した。さらにSIM-02B v2でsource/license/artifactを実bytesへ再解決し、scenario/Replay/grounding/probe/holdout/report/可搬Compilation/readiness sealを一体で再コンパイルするpositive engineering pathを閉じた。旧ID `n<全国図鑑番号>` の暗黙推定は廃止し、verified evidenceなしでは昇格させない。現M-B assessmentはdiagnostic reason 718件、promotion blocker 720件の`NO-GO`を正しく出す。追加blockerは、local manifestのauthority/license文字列だけではproductionへ昇格できないようにするartifact-root外trust anchorである。mapping evidenceの昇格、構造化された技・特性・道具の意味と実行handler、外部grounding/holdout、actual/sealed-historical 48時間rehearsal、ADB ownership supervisor、M-B mega対応、旧PJ由来データのlicense確認は未完了である。ローカルengineering sealをdeployable candidate、公式準拠、環境coverage、再配布権へ読み替えない。

## Requirement Contract

| 項目 | 契約 |
|---|---|
| `purpose` | 決定論的なChampionsシングル対戦状態遷移と、その後のAI研究が依存できる再現基盤を作る。環境正確性、戦略品質、構築・選出、外部順位較正を別目的変数として接続する。 |
| `success_metric` | P0/SIM-01は既存の工学ゲートを維持する。SIM-02は固定manifestに対する`target_pool_execution_coverage_rate == 1.0`、外部assertionの`verified_grounding_conformance_rate == 1.0`、`silent_fallback_count == 0`、sealed inputからcandidateまたは根拠付き`NO-GO`まで48時間以内を別々に測定する。AI-01は`paired_net_utility_ppm`、pair completeness、legal action、Replay verification、`private_state_delivery_violation_count`をpartition/hash付きで測るが、外部順位へ換算しない。このdelivery指標はprocess isolationの代替ではない。 |
| `non_goals` | SIM-02では、target manifest外を対応済みと主張しない。AI-01では実RL/LLM/MCTS学習、強度昇格、BlueStacks操作、ランクマッチ操作、ランク1相当の宣言を行わない。元データや旧PJ全体をコピーせず、人気度thresholdで対象を切り捨てない。 |
| `inputs_available` | SIM-01全基盤、source-bound M-B/M-A RegulationSnapshot、M-B 235フォームTargetPoolSnapshot、recomputed coverage/diffとsynthetic-NO-GO-only rehearsal v1、strict content-addressed CaptureStore、manifest-bound GroundingTrace、allowlist/evidence-bound AI Env、version/hash/seed/RNGへ結合したpolicy-free `reset`/`step` adapter、source-bound Catalog intake、explicit mapping/fixed-point closure/6次元/probe/grounding/holdoutを持つTargetCapability pipeline、理由付きNO-GOをcontent-addressed生成するv1 compiler、negative-only v1 readiness、resolver-backed source/license/artifact・executable scenario/Replay・grounding・engine probe・lineage分離holdout・可搬Compilationを再検証するSIM-02B v2 compiler/readiness、standard-stat-formula検証付きReplay互換generic mega、全階層strict Replay decoder、6→3 sealed team preview、partial-observation selection/battle baseline、paired-seat arena、battle-Replay archive/evidence manifest、frozen synthetic report。 |
| `inputs_missing` | artifact-root外でsource issuer/authorityとapproved manifest/license identityを固定するproduction trust anchor、M-B 235フォームのauthoritative mapping evidenceとresolved/verified昇格、技priority・structured effect・trigger/target/resolution context、特性/道具handler、base stats、66 Mega stone relation、各capabilityのpositive executor、verified grounding assertion、開発から分離した実external holdoutと複数構築scenario corpus、candidate/live/sealed-historical用Rehearsal v2、actual 48時間evidence、外部ADB ownership supervisor、M-B 16メガ形態と同時発動順・stat formulaのChampions grounding、actual BlueStacks capture/trace、license確認済みCatalog snapshot、上位人間または同等固定benchmarkによる順位較正。 |
| `assumptions` | AIの強さ、ローカル参照安定性、宣言target pool coverage、公式準拠、再配布権を別の目的変数とする。TargetPoolは人気度ではなくversion固定source corpusとRuleSet差分から作る。旧PJ由来データは`unverified`、ローカル研究限定、再配布不可として扱う。 |
| `constraints` | Python 3.10以上、原則stdlib＋pytest、seed付き決定論、完全状態と観測の分離、未知効果はfail-closed、出典追跡、大容量成果物のGit除外、実ゲーム運用はフレンド戦のみ。 |
| `risks` | Showdownや旧世代の仕様をChampionsへ誤適用すること、LLMの推測をルールへ混入すること、平均勝率で遷移誤りを隠すこと、未確認ライセンスのデータ再配布、生成物によるGit肥大化。 |
| `validation_plan` | SIM-01回帰とstrict Replay decodeに加え、TargetPoolの分母固定、source lock/mapping evidence、Catalog candidateのunknown fail-closed、semantic inventoryと6次元execution gap、probe-derived silent fallback、report/artifact hash再現、coverage/diff再計算とforgery拒否、readiness sealの自己申告VERIFIED拒否、team-preview commitment/privacy、selection source/runtime/typed-state/config・mapping順・alias topology、detached policy observation、paired side swap、policy instance/RNG分離、Arena summary再計算、全Replay verify、capture content identity/manifest hash、Env field/evidence allowlist、opponent exact-HP非漏洩、fixture ID/engine seed非干渉、mega standard-formula照合を継続検査する。外部holdoutとactual rehearsal/groundingは別gateとする。 |
| `go_no_go` | SIM-02ローカル基盤とAI-01 synthetic evaluation基盤の継続利用はGO。Synthetic結果はoperational/engineering successだがdeployableまたはrank-equivalent successではない。M-B candidate、actual device grounding、Champions準拠、戦略強度昇格はcoverage、scenario corpus、外部証拠が揃うまでNO-GO。Catalog・capture・派生物の配布はlicense/contents reviewまでNO-GO。 |

## 公式準拠への昇格に必要な確認

1. RuleSetの各値に一次情報または実機観測の根拠があること。
2. 使用するCatalogデータについて、利用・保存・派生物のライセンス状態が記録されていること。
3. SIM-01で対応する効果と、未対応として拒否する効果の境界が列挙されていること。
4. 現行Schema・観測契約を実機イベント、HP表示、公開情報履歴へ照合し、差分をgolden fixtureへ固定すること。
5. `specs/sim-02-phase-contract.md`のTarget-pool選定契約に従い、execution coverage、grounding conformance、silent fallback、外部holdout、48時間rehearsalの最終ゲートを満たすこと。

## 次にやること

次の大目的は`SIM-02C Production Trust Anchor + Authoritative M-B Evidence + Executable Scenario Corpus`とする。SIM-02Bのpromotion/readinessコードを広げるのではなく、現行M-B assessmentが列挙した0/235 mappingと720 blockerを、artifact-root外trust anchor、取得・利用可能性を検証したsource record、actual private-match traceで解消する。全235 memberのmapping、構造化された技priority/effect・特性・道具・base stats・Mega relation、capabilityごとのdevelopment scenario/positive Replay、開発とsource/collection/authoringが独立したsealed holdout、実機groundingを同一manifest lineageへ収める。最初の48時間でcandidateまたはexact `NO-GO`、7日でholdout・AI-01評価・包装までの投入可否を確定する。production readiness sealが出るまでMCTS/RL/LLMへChampions candidateを渡さず、licenseが確認できない元データ・Catalog・capture・派生データを再配布しない。詳細な昇格条件は`specs/sim-02b-phase-contract.md`を正本とする。
