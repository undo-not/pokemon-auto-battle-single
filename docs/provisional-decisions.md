# Provisional Decisions

仮置き値は実装上必要でも、検証済みの正本ではない。各値には利用範囲、リスク、review triggerを持たせ、RuleSet、Replay、評価レポートへIDを伝播する。

## PD-001: Git追跡ファイル上限

- `status`: provisional
- `scope`: repository governance
- `current_value`: 単一のGit追跡ファイルを2 MiB（2,097,152 bytes）以下とする。
- `reason`: 初期リポジトリの肥大化と大容量生成物の履歴固定を防ぐ。
- `risk`: 将来の最小再現fixtureやSchema bundleが上限を超える可能性がある。
- `review_trigger`: 初めて上限を超える必要性が発生した時、またはsize guard運用3か月後。
- `owner`: repository maintainer
- `implementation_evidence`: `scripts/check_repo_size.py`と`tests/test_governance_validation.py`でGit候補ファイルを検査する。

## PD-002: Fixture上限

- `status`: provisional
- `scope`: tests and validation data
- `current_value`: 単一fixtureを256 KiB（262,144 bytes）以下とする。
- `reason`: golden fixtureを目的に必要な最小例へ保つ。
- `risk`: 長いReplayや複数効果の相互作用を1件で再現できない可能性がある。
- `review_trigger`: 分割しても再現性を損なう実機由来fixtureが得られた時。
- `owner`: simulator maintainer
- `implementation_evidence`: `scripts/check_repo_size.py`はパス中に`fixtures`または`golden`を含むファイルへ256 KiB上限を適用する。

## PD-003: 急所率と急所倍率

- `status`: provisional
- `scope`: SIM-01 fixture and provisional RuleSet only
- `current_value`:
  - 通常の急所発生確率: `1 / 24`
  - 急所ダメージ倍率: `1.5`
- `reason`: 初期fixtureを記述するための仮置き。Champions固有の一次情報・実機照合は未完了。
- `risk`: 作品固有の変更、急所ランク、特性、技、状態による例外を誤る可能性がある。
- `uncertainty_rule`: 仮置きを使ったReplayへ`PD-003`を記録する。例外効果は確認されるまでunsupportedとする。
- `review_trigger`: 実機で乱数を固定または十分な反復観測ができた時、公式説明が確認できた時、急所ランクを持つ技・特性を実装する前。
- `owner`: ruleset maintainer
- `implementation_status`: SIM-01 RuleSetとエンジンへ実装し、Replayへ`PD-003`を伝播する。実機検証は未完了。

## PD-004: 定数割合の残余ダメージ・回復の端数

- `status`: provisional
- `scope`: SIM-01 fixture and provisional RuleSet only
- `current_value`:
  - やけど: `floor(max_hp / 16)`、効果が発生する場合の最小値1
  - 通常のどく: `floor(max_hp / 8)`、効果が発生する場合の最小値1
  - もうどく: `floor(max_hp * toxic_stage / 16)`、効果が発生する場合の最小値1
  - たべのこし: `floor(max_hp / 16)`、回復が発生する場合の最小値1、最大HPを上限とする
- `reason`: 境界HP fixtureを定義するための仮置き。
- `risk`: Championsでの演算順、内部固定小数点、最小値、もうどくstage更新順が異なる可能性がある。
- `uncertainty_rule`: 上記以外の定数割合効果を「等」として自動一般化しない。個別登録がない効果はunsupportedとする。
- `review_trigger`: 実機で最大HPが15、16、17および分母前後になる個体を用いて各効果を確認した時、複合回復・複合ダメージの実機ログが得られた時。
- `owner`: ruleset maintainer
- `implementation_status`: 現SIM-01はやけど、通常どく、たべのこしを実装する。もうどくは現RuleSetのunsupported範囲であり、登録値を未検証のまま一般化しない。

## PD-005: SIM-01 seeded smoke件数

- `status`: provisional
- `scope`: SIM-01 validation
- `current_value`: 1候補bundleの昇格前に10,000件のseeded smoke caseを実行する。
- `reason`: 非決定、例外、状態不変条件違反を初期段階で広く検出する。
- `risk`: 件数は状態空間の網羅性を保証せず、同質な生成ケースでは欠陥を見逃す。
- `review_trigger`: 実機検証済みfixtureを用いた最初のsmoke完了時に、実行時間、重複率、欠陥検出率を評価する。状態生成器または対応効果集合が大きく変わった時も再評価する。
- `owner`: validation maintainer
- `latest_evidence`: 2026-07-13に最終bundleのseed 0〜9,999を完走。10,000 battles、P1 3,240勝、P2 6,760勝、0 draws、195,319 decision windows、2,462,659 events、例外0、unique final hashes 10,000。所要188.4秒。Catalog hash `764a75146a017aca77453110fc8e19903ddc11e64e1df03c92791aa367703141`、RuleSet hash `f87b077b1ba598865a9e21ef84decbf273ca73806a9412fd5d2520589ff34215`。
- `completion_relation`: ローカル参照実装の安定性ゲートは満たすが、実機正確性は証明しない。

## PD-006: Git LFSを既定で使わない

- `status`: provisional
- `scope`: repository governance
- `current_value`: Git LFSを既定の保存先にせず、大容量artifactはGit外に置いてmanifestだけを追跡する。
- `reason`: clone時の外部依存と履歴上の大容量ポインタ乱立を避ける。
- `risk`: 複数PC間のartifact共有方式が未選定である。
- `review_trigger`: 再現実験を複数環境で共有する必要が生じ、artifact store要件が定義された時。
- `owner`: repository maintainer

## PD-007: 複合効果と同時処理の解決順

- `status`: provisional
- `scope`: SIM-01 fixture and transition engine
- `current_value`:
  - 通常turnは交代をpriority 6として扱い、技priority、実効素早さ、同速RNGの順で行動順を決める。
  - ダメージ技はダメージ算出、きあいのタスキ、HP減少、オボンのみ、吸収または追加効果、接触特性の順で処理する。
  - turn終了時は実効素早さの高い側から、状態異常残余、オボンのみ、たべのこしの順で処理する。同速時の残余処理順は`p1`、`p2`とする。
  - 両者の強制交代は`p1`、`p2`の順でswitch-in効果を処理する。
  - 先行actionで対象が瀕死になった後のtarget-directed moveはPPを消費するが、命中・急所・ダメージ等のRNGを消費せず`no_target`で失敗する。
  - 接触技とさめはだで双方の最後のポケモンが瀕死になった場合は、さめはだ保持側をwinnerとして記録する。
  - 残余ダメージで双方の最後のポケモンが瀕死になった場合は、記録された瀕死eventの最後のsubject側をwinnerとする。現在の素早さ順処理では遅い側が後に記録される。
- `reason`: 決定論的な参照実装とReplayを成立させるための仮置き。Championsの複合効果順を実機で網羅確認していない。
- `risk`: 同時瀕死、木の実、吸収、接触特性、交代時特性の結果と乱数消費位置が実機と異なる可能性がある。
- `uncertainty_rule`: 全Replayと各stepへ`PD-007`を記録する。公式準拠評価ではverified値として扱わない。
- `review_trigger`: 上記の2効果以上が同一action/turnで発生する実機ログを取得した時、または効果順に関する一次情報が確認できた時。
- `owner`: ruleset maintainer
- `SIM-02 boundary`: 双方が同一decision windowでメガシンカを選ぶ順序はPD-007へ推定追加せず、実機groundingが得られるまで`UnsupportedMechanic`でfail-closedする。

## PD-008: SIM-02 regulation rehearsal SLA

- `status`: provisional
- `scope`: SIM-02 regulation adaptation rehearsal
- `current_value`: 署名済みRegulationSnapshot、利用可能source一覧、sealed input bundleを受領した`t0`から、検証済みcandidate bundleまたは根拠付き`NO-GO` reportの発行まで48時間以内とする。
- `reason`: 2〜3週間単位のレギュレーション変化に対し、1週間の運用準備期間を残すための初期SLA。
- `risk`: 外部sourceや実機証拠の公開待ちを実装速度と混同すること、時間達成を優先して未検証値を採用すること、計算資源と手作業を記録せず再現不能な達成を主張すること。
- `uncertainty_rule`: 証拠不足または新semantics未確認時は、48時間内の`NO-GO`を安全運用上のrehearsal成功とするが、deployable candidate成功には数えない。人気度threshold、top-N、最低件数をSLA達成のために導入しない。
- `review_trigger`: sealed historical diffまたは実レギュレーションで最初のrehearsalを完了した時、2回連続で外部待ちを除いて48時間を超えた時、実際のレギュレーション告知から適用までの期間が変わった時。
- `owner`: SIM-02 release maintainer
- `implementation_evidence`: Rehearsal Schema/Model v1を`synthetic_internal`かつ`NO-GO`専用とし、candidate hashを許可しない。Builderはsealed bundleからbefore/after coverageとdiffを再計算し、caller supplied参照の不一致・forgeryを拒否する。Synthetic fixtureは48時間内に理由付き`NO-GO`を返し、`operational_rehearsal_success: true`、`deployable_candidate_success: false`を記録する。
- `current_limitation`: fixtureの`t0`、`t_decision`、resource値はsynthetic inputであり、実測wall-clock、外部待ち、actual regulation対応の証拠ではない。Candidate、`sealed_historical`、`live`はv1の対象外で、別version未定義である。PD-008はprovisionalのまま維持する。

## PD-009: AI-01 synthetic frozen benchmark件数

- `status`: provisional
- `scope`: AI-01 synthetic regression only
- `current_value`: 64 engine seed-pairを各2 seatで実行し、合計128戦をfrozen regressionとする。
- `reason`: paired/side-swap、Replay再検証、report identity、公開情報baselineの非自明性を短時間で継続検査する初期工学予算である。
- `risk`: 単一のSIM-01 synthetic rosterと64 seedは、対戦分布、レギュレーション、上位人間、ランク順位を代表しない。128戦全勝でも外部強度を示さない。
- `uncertainty_rule`: 適用reportの`ArenaPlan.provisional_decision_ids`へ`PD-009`を保存し、`scope: synthetic_local`、`champions_candidate: false`、`rank1_equivalence_status: unmeasured`を同時に固定する。
- `review_trigger`: 複数の証拠付きscenario corpus、developmentから隔離した外部holdout、または人間上位層との盲検評価が利用可能になった時。件数だけを増やして外部昇格しない。
- `owner`: competitive evaluation maintainer
- `latest_evidence`: 2026-07-14に64 pair / 128 matches、candidate 126勝0分2敗、net utility 124/128 = 968,750 ppm、Replay verification 1,000,000 ppm、illegal/error/private-state-delivery violation 0。report hash `5fe3ac9d5fda0957fc0f4d1d61e17d1994e10959d5f5b40f997d0fd5c76dc2ac`とArena evidence hash `7a7c9bba506f4545f5f48ed5c76eef30c476efc681cd3847c23e7d8d4254b8e2`を`data/golden/ai01-synthetic-benchmark-v1.json`へ固定した。
- `completion_relation`: AI-01の配線・決定性・回帰ゲートは満たすが、Champions fidelity、汎化、ランク1相当は証明しない。
