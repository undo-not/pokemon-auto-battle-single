# SIM-02 Phase Contract

## 現在の状態

- Phase Contract: **SPECIFIED**
- ローカル準備基盤: **IMPLEMENTED / VERIFIED LOCALLY**
- 現行M-B target pool: **235フォームで固定**
- 現行SIM-01 Catalog readiness: **explicit mapping/covered 0、unmapped 235**
- Source-to-Capability compile: **OPERATIONAL SUCCESS / REASONED NO-GO** — resolved/verified 0、unresolved 219、conflict 16、execution gap/個別executor未取得 118、silent fallback 0、理由718件
- Synthetic 48h rehearsal: **OPERATIONAL SUCCESS / DEPLOYABLE SUCCESSではない**
- BlueStacks grounding基盤: **read-only診断・capture store・GroundingTrace・AI Envを実装。actual traceは未取得**
- P1 hardening: **IMPLEMENTED / VERIFIED LOCALLY** — rehearsal再計算、capture/evidence binding、ADB ownership gate、standard mega stat検証、strict Replay decode
- Champions実機準拠の最終ゲート: **NO-GO**
- 主なblocker: 235フォームのauthoritative mapping evidence、技・特性・道具・base stats・Mega relationの構造化意味とpositive executor、外部holdout、実機grounding corpusが未取得
- 現行M-B mandatory gap: generic mega contractは実装済みだが、現M-B RuleSetでは`mega_evolution`がunsupported。同時メガシンカの解決順もgrounding不足でfail-closed

## Phase Contract

| 項目 | 契約 |
|---|---|
| `phase_id` | `SIM-02` |
| `phase_name` | Target-Pool Coverage and Grounded Mechanics Expansion |
| `purpose` | version固定された現行レギュレーションと対象対戦集合から、実装対象のポケモン・技・特性・道具・到達可能メカニクスを機械的に確定し、SIM-01の決定論・Replay・fail-closed境界を壊さずに対応範囲を拡張する。48時間rehearsalで、検証済みcandidateまたは根拠付き`NO-GO`を再現可能に出す。 |
| `objective_variable` | 主目的は`target_pool_execution_coverage_rate`、`verified_grounding_conformance_rate`、`silent_fallback_count`、`regulation_rehearsal_decision_lead_time_hours`の4変数。定義は下記。勝率、使用率、実装件数、LLM説明品質を代替指標にしない。 |
| `input_data` | source manifest付き`RegulationSnapshot`、公式eligible list全件から作る`TargetPoolSnapshot`、version/hash付きCatalog/RuleSet、SIM-01 frozen baseline、一次情報または実機観測に結び付く`GroundingTrace`、外部holdout corpus。raw対戦データや映像はGit外とし、Gitにはmanifest、hash、小fixture、集約結果だけを置く。 |
| `explanatory_variables` | legal pool差分、species/move/ability/item ID、effect/trigger/target/order/rounding/RNG signature、構築・選出集合、公開/非公開状態、source/evidence status、到達可能interaction、unsupported理由、実行時間、bundle identity。人気度は実装可否の説明変数にしない。 |
| `provisional_coefficients` | 人気度下限、top-N、累積使用率、最低対戦件数を置かない。48時間SLAだけを`PD-008`として暫定運用する。source集合、取得時点、規制期間は係数ではなくmanifestへ固定する入力であり、後からcoverage分母を縮小しない。 |
| `output_models` | 実装済み: `RegulationSnapshot`、`TargetPoolSnapshot`、`CoverageGapReport`、`RegulationDiffBundle`、`RegulationRehearsalReport`、`CaptureManifest`、`GroundingTrace`、`EnvObservation`、policy-free `EnvironmentBundleIdentity` / `SealedEnvironmentInput` / `EnvironmentSnapshot` / `ResetResult` / `StepResult`、Replay互換generic mega state/action/event、source-bound `CatalogIntakeBundle`、`TargetPoolManifest`、`TargetCapabilitySet`、`MechanicCoverageMatrix`、`HoldoutGapReport`、source lockから全13 documentと理由付きNO-GO reportを生成するintake診断専用`source-to-capability-bundle-v1` compiler、v1 substanceを再検証して偽装を拒否するfail-closed readiness gate。未達: positive readiness issuance、resolver-backed production promotion v2、verified evidenceで全gateを通過したdeployable M-B candidate bundle、全target capabilityのpositive executor/actual grounding/external holdout。 |
| `downstream_consumers` | deterministic search、belief更新、RL環境、LLM/RAG環境分析、構築・選出評価、BlueStacks adapter。下流はtarget pool、RuleSet、Catalog、grounding statusを上書きしない。 |
| `uncertainty_rules` | `verified` assertionだけを外部grounding分子へ数える。`provisional`はReplay/reportへ`PD-*`を伝播し、`unverified`・unknown effect・未実装interactionはfail-closedとcoverage gapへ送る。LLMはsource候補・fixture候補を提案できるが、ルール値、event順、期待結果の正本にならない。証拠不足時に48時間を守る正しい出力は`NO-GO`であり、推定実装ではない。 |
| `done_conditions` | ローカル準備ゲートと外部最終ゲートを分離し、下記条件を満たすこと。 |
| `anti_patterns` | 使用率X%以上、top-N、記事で有名等による分母選別、実装後のtarget pool縮小、unsupportedを通常damage/no-opへ落とすこと、LLM生成値の正本化、local fixture成功の実機準拠への読み替え、平均勝率による遷移誤りの隠蔽、48時間達成のための証拠省略。 |

## 目的変数

### 1. Target-pool execution coverage

```text
target_pool_execution_coverage_rate
  = fully_supported_target_capabilities
    / declared_target_capabilities
```

- `TargetCapability`は単なるentity IDではなく、`effect_id + trigger + target + resolution context + RuleSet branch`の到達可能な意味単位とする。
- 同じ効果実装を複数entityが共有してもよいが、各entityからそのcapabilityへの参照をmanifestへ残す。
- `fully_supported`は、合法性、状態遷移、RNG消費、event、観測、Replayがすべて契約化され、unknown/no-op fallbackを通らない場合だけ数える。
- 分母は実装開始前にhash固定する。未対応capabilityを除外して分母を減らしてはならない。
- ローカルcandidate gateは`1.0`。ただしこれは宣言済みtarget pool内の実行coverageであり、全合法ポケモンや実環境全体のcoverageを意味しない。
- `CoverageGapReport`はeligible member mapping、Catalog収録、required mechanic supportの前段readinessを測る。旧IDの暗黙推定を廃止したため、M-Bでは235フォーム中explicit mapping/covered 0件、unmapped 235件で、`mega_evolution`もunsupportedである。
- 現`source-to-capability-bundle-v1`はsource lockを再検証し、全235 memberを0 resolved/verified、219 unresolved/unverified、16 conflict/unverifiedとして明示する。Catalog-wide semantic selector 788とtarget capability row 118を生成するが、分母未確定のためdeclared/fully-supported countとcoverage rateを`null`にする。この値も実環境採用率へ読み替えない。

### 2. Verified grounding conformance

```text
verified_grounding_conformance_rate
  = passed_verified_grounding_assertions
    / required_verified_grounding_assertions
```

- 各TargetCapabilityは、少なくとも1つのverified assertionへtrace可能でなければ外部最終ゲートの分母を満たさない。1つのassertionが複数capabilityを根拠付けることは許す。
- assertionはsource manifest、初期状態、選択、RNG条件または観測条件、期待event/状態、適用RuleSetを持つ。
- 完了値は`1.0`。assertion不足を分母から除外せず、`missing_grounding`として残す。
- SIM-01の公開damage参照1例、local tests、10,000戦smokeは現時点の工学証拠であり、この外部grounding分子へ自動算入しない。

### 3. Silent fallback

```text
silent_fallback_count
  = unsupported / unknown / unverified branchに到達したのに
    明示的なunsupported・NO-GO・coverage gapを返さず継続した件数
```

- 完了値は常に`0`。
- 例外を投げた件数そのものは失敗ではない。対象capabilityを対応済みと表示しながらfallbackした場合が失敗である。
- static effect mapping監査、全TargetCapabilityの生成遷移、Replay再実行、mutation testのいずれでも検出対象とする。

### 4. 48時間regulation rehearsal

```text
regulation_rehearsal_decision_lead_time_hours = t_decision - t0
```

- `t0`は署名済みRegulationSnapshot、利用可能source一覧、sealed input bundleを受領した時刻。
- `t_decision`は、検証済みcandidate bundleまたは根拠付き`NO-GO` reportを発行した時刻。
- 完了値は`<= 48`時間。時刻、入力hash、計算資源、手作業、外部待ち時間をreportへ記録する。
- 既知semanticsだけの合法pool変更では、48時間内のdeployable candidateを要求する。
- 新semanticsまたは必要証拠が欠ける場合、48時間内の`NO-GO`は安全運用上のrehearsal成功だが、deployable bundle成功には数えない。
- 内部の過去レギュレーションrehearsalは工程検証に使えるが、外部最終ゲートには、実装時に未見だったsealed historical diffまたは将来の実レギュレーションを使う。
- 実装済みRehearsal Schema/Model v1は`synthetic_internal`かつ`NO-GO`だけを許す。candidate、`sealed_historical`、`live`をv1へ詰め込まず、deployable rehearsalには別versionの契約を先に定義する。
- Rehearsal builderはcaller suppliedのcoverage/diffを信用せず、sealed Regulation/TargetPool/Catalog/RuleSetからbefore/after coverageとdiffを再計算し、一致しない参照・forgeryを拒否する。

## Target-pool選定契約

1. `RegulationSnapshot`を先に固定し、合法pool、期間、RuleSet差分の正本を決める。
2. 公式eligible listの全dex/form/variant recordを順序付きで取得し、source manifestにartifact hashと件数を固定する。使用率、記事数、勝率は選定条件にしない。
3. 同一`national_dex_no + form_code + variant_code`の完全重複だけを決定論的に拒否し、公式list全件を分母へ含める。現M-B snapshotは235 unique target keyを持つ。
4. 各memberの`pokemon_id` mappingはnullableとし、未mappingを除外せず`unmapped_target` blockerとして残す。全国図鑑番号から外部Catalog IDを推定せず、namespace付きsource record hashとverification evidenceがない限りresolvedにしない。現compileは0 resolved/verified、219 unresolved/unverified、16 conflict/unverifiedである。
5. 公式`required_mechanics`をmandatory setに加える。現M-Bの`mega_evolution`は、人気度に関係なく分母から除外しない。
6. mapped entityからspecies、move、ability、item、effect、trigger、RuleSet branchを辿る到達可能closureを`TargetCapabilitySet`とする。mapping未確定時もmandatory mechanicを落とさず、分母をnon-finalとしてcount/rateを報告しない。
7. regulation hash、target-pool hash、Catalog/RuleSet hash、source IDs、restricted source IDs、member/mapping/coverage数、全blockerをreportへ固定する。
8. 公式listまたはmappingが変わればsnapshotをversion-upし、旧coverage reportを新しい分母へ流用しない。
9. 環境構築・選出データはtarget legality分母を狭める用途に使わず、後続のmeta分析と外部holdoutへ分離する。holdoutで新capabilityが見つかった場合はcandidateを昇格させない。

この契約は「実環境の何%を占めるか」を推定するものではない。target-pool coverageは、固定manifestに対する工学coverageである。

## ローカル準備ゲート

1. Regulation/TargetPool/Coverage/Diff/Rehearsal/Capture/Grounding/AI Envのversion、hash、source、PD契約を定義する。**実装済み**
2. SIM-01 bundleをfrozen baselineとして検査し、regulation/target/diff/reportを決定論的に生成する。**実装済み**
3. 宣言target poolについてcapability-level execution coverage `1.0`、silent fallback `0`を再現可能に測定する。**compiler実装済み / M-B未達** — synthetic Catalogでpositive pathを検証し、実M-B intakeからもmapping、Catalog candidate、semantic/execution registry、probe、matrix、理由付き`NO-GO`を一コマンド生成した。現実測はdenominator non-final、execution gap 118、silent fallback 0であり、coverage count/rateを`null`としてfail-closedする
4. Replay v2互換性、完全状態/観測分離、global RNG禁止、unknown fail-closedを維持する。Replay JSONは全階層でduplicate keyとunknown keyを拒否する。**ローカル検証済み**
5. synthetic sealed inputで48時間工程をrehearseし、再計算済みcoverage/diffから正しい`NO-GO`を出す。**operational success** — v1はsynthetic NO-GO専用で、fixture上の時間・資源は実測wall-clockまたはdeployable successではない
6. read-only BlueStacks診断、strict content-addressed capture store、manifest-bound GroundingTrace、allowlist/evidence-bound partial-observation AI Envを用意する。**実装済み** — actual emulator capture/traceは未取得
7. ADB daemonの外部side effectを防ぐownership supervisorを用意する。**未達** — discoveryは常に`adb_external_side_effect_risk_not_mitigated` blockerを付け、supervisorなしではcaptureを実行しない
8. AI学習器から独立したversion/hash/seed付き`reset`/`step`契約を用意し、partial observation、public history、legal mask、Replay lineageを返す。**ローカル実装済み** — 報酬・方策は未定義、Champions candidateはcapability/grounding evidence未検証時にfail-closed

ローカル準備ゲートはパイプラインの再現性を示すだけで、Champions準拠または現環境coverageを証明しない。

## Champions外部最終ゲート

1. 現行RegulationSnapshotが一次情報manifestとcontent hashを持つ。
2. TargetPoolManifestが選定契約に従い、恣意的な人気度thresholdを含まない。
3. `target_pool_execution_coverage_rate == 1.0`。
4. 全TargetCapabilityがverified assertionへtraceされ、`verified_grounding_conformance_rate == 1.0`。
5. `silent_fallback_count == 0`。
6. 外部holdoutで新capability、観測漏洩、Replay drift、未説明差分が0件。
7. 未見sealed diffまたは実レギュレーションで、48時間以内にdeployable candidateまたは正しい`NO-GO`を発行する。
8. actual BlueStacks/device captureと外部grounding traceで、UI observation・event・状態遷移を照合する。
9. `AUD-P0-001`とSIM-02のblocking issueが解消される。

## 現在の証拠と未達項目

現時点で利用できる証拠は、限定Catalog/RuleSet、公開damage参照1例、local unit/integration tests、Replay v2、10,000戦seeded smokeに加え、公式source-bound M-B snapshot、235フォームtarget pool、coverage/diff pipeline、source-to-capability compilerとcontent-addressed NO-GO bundle、synthetic rehearsal report、read-only BlueStacks/capture/GroundingTrace/AI Env契約、generic mega contractである。これはSIM-02ローカル基盤と証拠不足を決定論的に列挙する能力を示すが、次を証明しない。

一方、公式[Regulation Set M-B](https://champions-news.pokemon-home.com/en/page/776.html)は2026-06-17 02:00 UTCから2026-09-02 01:59 UTCまで有効で、メガシンカを1戦に1回許可し、新たに16のメガシンカを列挙する。公式[Season M-4](https://champions-news.pokemon-home.com/en/page/795.html)はM-Bを使用する。SIM-01 RuleSetは`mega_evolution`をunsupportedとしているため、メガシンカは人気度に関係なくSIM-02のmandatory TargetCapabilityである。

Generic mega fixtureでは、単側のメガシンカについて1戦1回resource、メガストーン/対象個体の合法性、move actionとの結合、形態・能力値・タイプ・特性変化、pre-move event、交代後の永続、観測、Replay roundtripを実装した。変身前後の実数値はversioned standard stat formulaから再計算し、Catalog base statsとmega statsの双方へ照合する。ただし、このformulaとChampions実機の一致は未groundedである。同時メガシンカの解決順はgrounding不足としてfail-closedする。現M-B RuleSetはなお`mega_evolution`をunsupportedとし、16形態も現Catalogへmapping/groundingされていないため、M-B target-pool coverage `1.0`を主張しない。

Grounding/AI境界ではCaptureStoreがartifact bytes、manifest、content-derived capture IDをstrict verifyし、`GroundingFrame`がcapture IDとcapture manifest hashを結合する。Draft dataclassの形式検証だけでは昇格せず、resolver-backed validationが実storeのmanifest hash・artifactとTrace/Env provenanceを照合して`ValidatedGroundingTrace`/`ValidatedEnvObservation`を発行した場合だけpromotable/actionableとする。同一capture IDに異なるmanifest hashを割り当てられず、存在しないcapture/traceも拒否する。`EnvObservation`はfield path allowlist、capture/trace evidence binding、public-event evidence IDを検証する。Opponent observationの正確HPは非公開とし、`hp`、`max_hp`だけでなく`hp_fraction_millionths`も`None`とする。

- 235フォームすべてのsource-bound mappingとCatalog内容
- 実環境の構築・選出集合と外部holdout
- 全TargetCapabilityのChampions固有event順・端数・RNG
- UI表示と実機状態の一致
- actualまたはsealed historicalな新レギュレーションへの48時間deployable対応能力
- M-B 16メガ形態のCatalog mapping、実機grounding、同時発動順
- 外部ownership supervisor下のBlueStacks actual capture、GroundingTrace、UI conformance

したがってSIM-02の外部最終ゲートは現時点で`NO-GO`とする。

## フェーズ外

- 探索、RL、LLMの勝率改善
- 構築の強さ、Elo、ランク1位相当評価
- BlueStacksへの入力・自動操作。read-only診断/capture契約はローカル基盤として実装済み
- 全合法entityを根拠なしに一括対応したと主張すること
- license未確認データ・大容量raw corpus・Replay・映像のGit保存または再配布
