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
- SIM-02C trust/partition integrity: **GO / VERIFIED LOCALLY WITH EPHEMERAL FIXTURE** — V2 production拒否を維持したまま、OpenSSH Ed25519検証、固定外部enrollment registry、意味的Replay重複拒否、artifact-root非依存input manifest、trust-bound V3 Compilation/readinessを別型で実装した。portable outputは常に`not_authorization`で、current trust contextによる再検証を要求する
- SIM-02C-A authoritative intake workbench: **GO / LOCAL ENGINEERING COMPLETE** — semantic authorityとusage permissionを分離した5 route plan/policy、namespace-safe 235 mapping、field-level Catalog V2、全件assessment、content-addressed writerを実装した。実M-B runはcandidate 219 / conflict 16 / verified 0、required field 8,024 / verified 0、blocker 10,794の`NO-GO`であり、production materializationは行わない
- 現行M-B data/enrollment gate: **NO-GO** — verified mapping 0/235、unresolved 219、conflict 16、target capability row/execution gap 118/118、diagnostic blocker 718、promotion blocker 720。actual production policy/key/enrollmentは未登録で、actual source/license/grounding/holdoutも不足する。SIM-02B frozen V2 assessmentの`production_trust_anchor_status: not_implemented`はV2発行経路だけを指し、V3工学verifierの存在またはactual enrollmentを表さない
- AI-01 synthetic benchmark: **128戦完走 / ENGINEERING EVIDENCE ONLY** — candidate 126勝0分2敗、Replay verification 100%、`champions_candidate=false`、`rank1_equivalence_status=unmeasured`
- ランク1相当の強度: **UNMEASURED / CLAIM FORBIDDEN** — 実M-B executable bundle、partitioned scenario corpus、外部上位層較正がない
- 公式Champions準拠としての昇格: **NO-GO**
- Catalog・派生物の再配布: **NO-GO**
- 理由: SIM-01に加え、公式source-bound M-B snapshot、235フォームtarget pool、source-lock intakeからMechanicCoverageMatrixまでの一コマンドcompiler、再計算型coverage/diff/synthetic NO-GO rehearsal、strict read-only capture/evidence/AI Env、standard-formula検証付きgeneric mega、strict Replay decodeを実装した。さらにSIM-02B v2でsource/license/artifactを実bytesへ再解決し、scenario/Replay/grounding/probe/holdout/report/可搬Compilation/readiness sealを一体で再コンパイルするpositive engineering pathを閉じた。SIM-02C V3ではephemeral fixture上で固定外部enrollment、Ed25519 attestation、current-context再検証、意味的execution partition、path非依存input manifestを検証した。旧ID `n<全国図鑑番号>` の暗黙推定は廃止し、verified evidenceなしでは昇格させない。現M-B assessmentはdiagnostic reason 718件、promotion blocker 720件の`NO-GO`を正しく出す。mapping evidenceの昇格、actual policy/key/enrollment、構造化された技・特性・道具の意味と実行handler、外部grounding/holdout、actual/sealed-historical 48時間rehearsal、ADB ownership supervisor、M-B mega対応、旧PJ由来データのlicense確認は未完了である。ローカルengineering sealをdeployable candidate、公式準拠、環境coverage、再配布権へ読み替えない。

## Requirement Contract

| 項目 | 契約 |
|---|---|
| `purpose` | 決定論的なChampionsシングル対戦状態遷移と、その後のAI研究が依存できる再現基盤を作る。環境正確性、戦略品質、構築・選出、外部順位較正を別目的変数として接続する。 |
| `success_metric` | P0/SIM-01は既存の工学ゲートを維持する。SIM-02は固定manifestに対する`target_pool_execution_coverage_rate == 1.0`、外部assertionの`verified_grounding_conformance_rate == 1.0`、`silent_fallback_count == 0`、sealed inputからcandidateまたは根拠付き`NO-GO`まで48時間以内を別々に測定する。AI-01は`paired_net_utility_ppm`、pair completeness、legal action、Replay verification、`private_state_delivery_violation_count`をpartition/hash付きで測るが、外部順位へ換算しない。このdelivery指標はprocess isolationの代替ではない。 |
| `non_goals` | SIM-02では、target manifest外を対応済みと主張しない。AI-01では実RL/LLM/MCTS学習、強度昇格、BlueStacks操作、ランクマッチ操作、ランク1相当の宣言を行わない。元データや旧PJ全体をコピーせず、人気度thresholdで対象を切り捨てない。 |
| `inputs_available` | SIM-01全基盤、source-bound M-B/M-A RegulationSnapshot、M-B 235フォームTargetPoolSnapshot、recomputed coverage/diffとsynthetic-NO-GO-only rehearsal v1、strict content-addressed CaptureStore、manifest-bound GroundingTrace、allowlist/evidence-bound AI Env、version/hash/seed/RNGへ結合したpolicy-free `reset`/`step` adapter、source-bound Catalog intake、explicit mapping/fixed-point closure/6次元/probe/grounding/holdoutを持つTargetCapability pipeline、理由付きNO-GOをcontent-addressed生成するv1 compiler、negative-only v1 readiness、resolver-backed source/license/artifact・executable scenario/Replay・grounding・engine probe・lineage分離holdout・可搬Compilationを再検証するSIM-02B v2 compiler/readiness、ephemeral fixtureで検証した固定外部enrollment/Ed25519/current-context V3 verifier、ID変更に不変なReplay execution fingerprint、artifact-root非依存promotion input manifest、semantic authority/usage permissionを分離したSIM-02C-A source plan/policy、raw/derived hash inventory、235 mapping workbench、技490・特性180・道具117・タイプ18・Mega relation候補70を含むfield-level Catalog V2 workbench、10,794 blockerの決定論的assessment、standard-stat-formula検証付きReplay互換generic mega、全階層strict Replay decoder、6→3 sealed team preview、partial-observation selection/battle baseline、paired-seat arena、battle-Replay archive/evidence manifest、frozen synthetic report。 |
| `inputs_missing` | actual運用のproduction policy/key/enrollment registry、ACL/backup付きledger installation、非巻戻しtrusted clock、OS/code-integrity運用、全5 routeのapproved usage policy、旧raw manifest 2,024 acquisition gapの再封印、M-B 235フォームのauthoritative mapping reviewとresolved/verified昇格、Catalog required field 8,024件のfield-level review、技priority・structured effect・trigger/target/resolution context、特性/道具handler、base stats、Mega Stone relation、各capabilityのpositive executor、verified grounding assertion、開発から分離した実external holdoutと複数構築scenario corpus、candidate/live/sealed-historical用Rehearsal v2、actual 48時間evidence、外部ADB ownership supervisor、M-Bメガ形態と同時発動順・stat formulaのChampions grounding、actual BlueStacks capture/trace、license確認済みCatalog snapshot、上位人間または同等固定benchmarkによる順位較正。 |
| `assumptions` | AIの強さ、ローカル参照安定性、宣言target pool coverage、公式準拠、再配布権を別の目的変数とする。TargetPoolは人気度ではなくversion固定source corpusとRuleSet差分から作る。旧PJ由来データは`unverified`、ローカル研究限定、再配布不可として扱う。 |
| `constraints` | Python 3.10以上、原則stdlib＋pytest、seed付き決定論、完全状態と観測の分離、未知効果はfail-closed、出典追跡、大容量成果物のGit除外、実ゲーム運用はフレンド戦のみ。 |
| `risks` | Showdownや旧世代の仕様をChampionsへ誤適用すること、LLMの推測をルールへ混入すること、平均勝率で遷移誤りを隠すこと、未確認ライセンスのデータ再配布、生成物によるGit肥大化。 |
| `validation_plan` | SIM-01回帰とstrict Replay decodeに加え、TargetPoolの分母固定、source lock/mapping evidence、Catalog candidateのunknown fail-closed、semantic inventoryと6次元execution gap、probe-derived silent fallback、report/artifact hash再現、coverage/diff再計算とforgery拒否、readiness sealの自己申告VERIFIED拒否、Replay ID全置換でも変わらないexecution overlap拒否、input manifestのrelocation/drift/path escape拒否、wrong key/namespace/subject・expiry/revocation/rollback/ledger conflict/ledger消失・未登録policy差替え・change-compile-restore拒否、V3 portable summaryの`not_authorization`固定、team-preview commitment/privacy、selection source/runtime/typed-state/config・mapping順・alias topology、detached policy observation、paired side swap、policy instance/RNG分離、Arena summary再計算、全Replay verify、capture content identity/manifest hash、Env field/evidence allowlist、opponent exact-HP非漏洩、fixture ID/engine seed非干渉、mega standard-formula照合を継続検査する。外部holdoutとactual rehearsal/groundingは別gateとする。 |
| `go_no_go` | SIM-02ローカル基盤、SIM-02C trust/partition工学基盤、AI-01 synthetic evaluation基盤の継続利用はGO。Ephemeral/synthetic結果はoperational/engineering successだがdeployableまたはrank-equivalent successではない。actual M-B enrollment/candidate、actual device grounding、Champions準拠、private-match投入、戦略強度昇格はcoverage、scenario corpus、外部証拠が揃うまでNO-GO。Catalog・capture・派生物の配布はlicense/contents reviewまでNO-GO。 |

## 公式準拠への昇格に必要な確認

1. RuleSetの各値に一次情報または実機観測の根拠があること。
2. 使用するCatalogデータについて、利用・保存・派生物のライセンス状態が記録されていること。
3. SIM-01で対応する効果と、未対応として拒否する効果の境界が列挙されていること。
4. 現行Schema・観測契約を実機イベント、HP表示、公開情報履歴へ照合し、差分をgolden fixtureへ固定すること。
5. `specs/sim-02-phase-contract.md`のTarget-pool選定契約に従い、execution coverage、grounding conformance、silent fallback、外部holdout、48時間rehearsalの最終ゲートを満たすこと。

## 次にやること

SIM-02C-Aは、現行M-Bのsource acquisition/policy/mapping/Catalog field不足を固定分母で列挙する大単位として完了した。次の大目的は`SIM-02C-B Reviewed Evidence Promotion + Mechanics Coverage Factory`とする。SIM-02B/V3のgateを緩めず、(1) source-specific permissionとreview decisionを署名可能overlayへする、(2) 235件のnamespace/form mappingと8,024 required fieldをfield-level evidenceへ結合する、(3) approved structured effectだけをhandlerへlowerする、(4) handlerごとにdevelopment scenario/positive Replay/probeを生成する、の一体成果とする。外部権利審査待ちはblockerとして残し、名前・全国図鑑番号・旧site ID・LLM推論で解除しない。その後にactual private-match grounding、lineage分離holdout、actual/sealed-historical rehearsalをSIM-02C-Cとして閉じる。最初の48時間でcandidateまたはexact `NO-GO`、7日でholdout・AI-01評価・包装までの投入可否を確定する。production readiness sealが出るまでMCTS/RL/LLMへChampions candidateを渡さず、licenseが確認できない元データ・Catalog・capture・派生データを再配布しない。
