# SIM-01 Phase Contract

## 現在の状態

- ローカル参照実装: 工学ゲート完了
- 一次情報・実機検証済みChampions準拠: 未達
- データ再配布: license未確認のため禁止

## Phase Contract

| 項目 | 契約 |
|---|---|
| `phase_id` | `SIM-01` |
| `phase_name` | Deterministic Battle Transition Kernel |
| `purpose` | シングルバトルの完全状態、両者の合法な選択、明示的なseedを受け取り、再現可能なイベント列と次状態を返す。AI方策や画面操作には依存しない。 |
| `objective_variable` | 主目的は`verified_transition_conformance_rate`。実機golden fixtureの期待イベント・次状態assertion合格数/全assertion数で、完了条件は1.0。現在測定できる`local_reference_pass_rate`やsmoke完走率は工学ゲートであり、主目的の代替ではない。 |
| `input_data` | version/hash付き`RuleSetSnapshot`、`CatalogSnapshot`、完全な`BattleState`、各プレイヤーの合法な選択、明示RNG。ローカルbundleではRuleSet値とCatalog licenseがprovisional/unverifiedであることをmanifestとReplayへ伝播する。 |
| `explanatory_variables` | HP・最大HP、能力値・ランク、タイプ、特性、持ち物、技、状態異常、場・天候、優先度、素早さ、交代状態、残存チーム、公開・非公開情報、RuleSetの端数・乱数パラメータ。 |
| `provisional_coefficients` | カーネル内の戦略的重みは0件とする。急所、残余ダメージ端数、smoke件数およびGit容量閾値は`docs/provisional-decisions.md`の登録値を使い、正本として固定しない。 |
| `output_models` | `TransitionResult`（次状態、順序付き`BattleEvent`、次decision、RNG、terminal/winner）、各プレイヤー観測、exact-bundle/bundle-boundな`ReplayRecord v2`。Replayは初期化前状態・初期化イベント、全decision window、RNG境界、暫定判断ID、source manifest IDを内包するが、再実行には記録hashと一致する外部Catalog/RuleSet bundleが必須である。 |
| `downstream_consumers` | `verify_replay`、回帰・grounding test、seeded smoke、将来の探索、RL環境、LLM助言層、BlueStacks adapter。下流はカーネルを上書きしない。 |
| `uncertainty_rules` | 未確認値は`PD-*`とmanifestの`unverified`で明示する。未実装効果はfail-closed。ReplayへRuleSetの`PD-003/004/007`とCatalog/RuleSetのsource manifest IDを保存する。unverified Catalogはローカル研究に限り、配布validatorを通過させない。 |
| `done_conditions` | 下記の完了条件をすべて満たすこと。 |
| `anti_patterns` | ポケモン名や現行採用率へのハードコード、LLMによる状態遷移、グローバル乱数、seedなし試験、浮動小数点の暗黙丸め、未対応効果の無言無視、完全状態の方策への漏洩、勝率による正確性代替。 |

## 入出力境界

```text
RuleSetSnapshot + CatalogSnapshot + BattleState + JointChoice + RNG seed
                              |
                              v
                 deterministic transition kernel
                              |
                              v
BattleTransitionResult + player observations + ReplayRecord
```

- `RuleSet`は合法性とメカニクス値の正本である。
- `Catalog`は種族、技、特性、道具、タイプと効果IDの正本である。
- `BattleState`は完全情報を持つが、方策へ渡す観測は別に生成する。
- `JointChoice`は事前に生成された合法手IDだけを受け付ける。
- イベント順、乱数消費位置、各段階の状態hashを記録する。

## ローカル参照実装の工学完了条件

1. 同じbundle・初期状態・seedを100回実行し、Replay JSONと最終状態hashが全件一致する。**完了**
2. RuleSet/Catalog/Battle fixtureと生成Replay v2が再帰Schema契約、semantic loader、roundtrip、`verify_replay`を通過する。**完了**
3. 合法手外・stale choice・未知効果を拒否し、近似結果を返さない。**完了**
4. 完全状態から各プレイヤー観測への情報漏洩試験を通過する。**完了**
5. RuleSetの`PD-003/004/007`とCatalog/RuleSetのsource manifest IDがReplayへ伝播する。**完了**
6. 10,000件seeded smokeを例外0で完走する。**完了（2026-07-13、195,319 decision windows、2,462,659 events）**
7. source manifestのhash/sizeが一致し、license未確認bundleを配布モードで拒否する。**完了**
8. Git候補ファイルが`PD-001/002`の容量上限内である。**完了**

## 公式Champions準拠の完了条件

1. 急所、端数、同速、効果順、対応効果の実機golden fixtureで`verified_transition_conformance_rate == 1.0`。
2. RuleSetの各値に一次情報または実機証拠のmanifestがある。
3. Catalogの正確性とlicenseがsource単位で確認済みである。
4. `AUD-P0-001`が解消している。

現時点では未達であり、ローカル工学ゲートの完了を公式準拠へ読み替えない。

## 観測契約

`PlayerObservation`は、1時点の完全`BattleState`から生成するinstantaneous simulator snapshotである。相手ベンチ、未公開技、正確HP・能力値、未公開道具・特性を除外する。一方、BlueStacks画面のHPバー量子化、OCR誤差、過去に公開されたイベント列、相手型のbeliefは含めない。これらは将来のUI adapterまたはagent memoryが保持し、完全状態へ逆流させない。

## Type chart契約

Catalogの`type_chart`はsparse表現である。明示された攻撃タイプ・防御タイプpairだけが倍率を上書きし、省略pairは`type_chart_default_multiplier`の値、SIM-01では厳密に`1`として解決する。省略pairと未知タイプIDを区別し、未知IDは拒否する。

## フェーズ外

- 方策の勝率、Elo、構築性能
- LLMプロンプトの品質
- BlueStacksの画像認識と入力安定性
- ランクマッチまたは公開対戦への接続
- 未確認メカニクスの推定実装
