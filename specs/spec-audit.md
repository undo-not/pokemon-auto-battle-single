# Specification Audit Policy

## 目的

仕様、実装、テスト、生成物のずれと、仮置き値の正本化を防ぐ。すべての実装フェーズはPhase ContractとRequirement Contractを先に持ち、重大な欠落がある場合は進行しない。

## 必須読了順

1. `specs/requirement-contract.md`
2. 対象Phase Contract
3. `docs/provisional-decisions.md`
4. `docs/spec-audit-log.md`
5. `docs/traceability.md`

## Phase Contract必須項目

- `phase_id`
- `phase_name`
- `purpose`
- `objective_variable`
- `input_data`
- `explanatory_variables`
- `provisional_coefficients`
- `output_models`
- `downstream_consumers`
- `uncertainty_rules`
- `done_conditions`
- `anti_patterns`

欠けた項目があるPhaseは実装`NO-GO`とする。

## SpecAuditIssue

監査上の指摘は次を持つ。

| Field | Meaning |
|---|---|
| `id` | 一意な監査ID |
| `opened_on` | 記録日 |
| `severity` | `critical` / `high` / `medium` / `low` |
| `phase` | 対象Phase |
| `category` | `missing_input`、`objective_drift`、`provisional_hidden`、`contract_gap`、`uncertainty_gap`、`missing_spec`、`missing_tests`、`traceability_gap`、`data_governance`等 |
| `problem` | 現状の欠落または矛盾 |
| `expected` | 満たすべき状態 |
| `impact` | 未解決時の影響 |
| `suggested_action` | 最小の解消行動 |
| `evidence` | ファイル、一次情報、実機記録への参照 |
| `status` | `open` / `accepted_risk` / `resolved` / `superseded` |
| `resolution` | 解消根拠。未解決時は空欄 |

## ゲート規則

- `critical`は常に対象Phaseをブロックする。
- `phase`は`SIM-01-LOCAL`、`SIM-01-CHAMPIONS-VERIFIED`、`DISTRIBUTION`のように判定scopeを明示する。一つのscopeのblocking issueを別scopeへ自動拡張または縮小しない。
- `high`はRequirement Contractまたは入出力正確性に関係する場合、対象Phaseをブロックする。
- `accepted_risk`はルール正確性、ライセンス、情報漏洩、不可逆な外部操作には使用しない。
- licenseが`unverified`のartifactは、manifestと実行時validatorでローカル研究限定・再配布禁止を強制できる場合だけ`SIM-01-LOCAL`で使用できる。`DISTRIBUTION`では常にblockingとする。
- 仮置き値は実装前に`docs/provisional-decisions.md`へ登録する。
- 不確実性は出力、Replay、下流評価まで伝播させる。
- 仕様のない実装は`missing_spec`、重要挙動を検証しない仕様は`missing_tests`として記録する。
- 生成文章や勝率が良くても、正確性・出典・契約欠落を解消したことにはならない。

## 監査手順

1. 目的変数が目的と一致するか確認する。
2. 入力の正本、version、hash、license状態を確認する。
3. 説明変数と出力の欠落を確認する。
4. 仮置き値とreview triggerを照合する。
5. 未確実情報がfail-closedまたは明示伝播されるか確認する。
6. spec、Schema、実装、テスト、生成物の追跡行を更新する。
7. blocking issueが0件の場合だけGOを記録する。
