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

## PD-010: SIM-02C production trust verifier backend

- `status`: provisional
- `scope`: SIM-02C private/local production-source authorization engineering
- `current_value`: 外部署名の初期検証backendをOpenSSH `ssh-keygen -Y verify`とEd25519鍵にする。専用namespaceとUTF-8 canonical JSONでdomain separationし、compiler側は公開鍵policyだけを持つ。
- `reason`: Python stdlibにはEd25519 verifierがなく、共有HMAC secretはcompiler PCを署名者にもしてしまう。自作暗号を避け、Windows実行環境に存在する監査実績のある非対称署名backendで秘密鍵をcompiler PCから分離する。
- `risk`: OpenSSH binary/versionの可用性、platform差、allowed-signers semantics、外部policy/key provisioningに依存する。署名成功はsourceの内容・license・Champions conformanceを自動的に証明しない。
- `uncertainty_rule`: backend不在、binary hash/path未確認、policy hash不一致、key未登録・期限外・失効、revocation/ledger不可用時はproductionをfail-closedする。test keyはproduction keyとして登録しない。
- `review_trigger`: actual production policy/keyを初めてenrollする時、対象PC/OSを変更する時、OpenSSH backendのサポートが不安定になった時、または監査済みPython暗号backendを正式依存にできる時。
- `owner`: SIM-02 trust maintainer
- `completion_relation`: trust engineering gateのbackend選択であり、actual issuer enrollment、authoritative M-B evidence、production readinessの完了を意味しない。

## PD-011: SIM-02C fixed enrollment root and stable trust binding

- `status`: provisional
- `scope`: SIM-02C private/local production-source authorization engineering
- `current_value`: callerが指定するpolicy path/hashだけをroot trustにせず、`%USERPROFILE%\.champions_sim\production-trust\enrollment-registry-v1.json`という起動時固定per-user pathの外部registryへ明示登録されたpolicyだけを受理する。registry ID/hash、enrollment ID/binding hash、policy ID/hash、OpenSSH executable hash、minimum policy epoch、status、有効期間に加え、事前provision済みSQLite ledgerのinstance IDと正規化path bindingをcurrent trusted timeで検査する。portable V3 bindingから検証実行時刻と生pathを除外し、同一有効入力のbyte identityを保つ一方、`authorization_status: not_authorization`とcurrent-context再検証要求を固定する。
- `reason`: callerが任意Ed25519鍵、policy、expected policy hashを一式生成すると、署名検証自体は成功しても「そのpolicyを誰が信頼へ登録したか」を証明できないことが敵対的監査で判明した。compile callerから独立した固定registryを明示的なenrollment操作の境界にする。
- `risk`: 同一OS user権限でregistry、ledgerまたはPython実装を改変・rollbackできる攻撃、同一processでのmonkeypatch、起動時`HOME`/`USERPROFILE`、trusted clock provenance、workspace/実行binaryのcode integrity、OS ACL/監査ログはこのローカル実装だけでは保護しない。固定registryは運用上のtrust rootであり、署名sourceの内容、license、Champions fidelity、運用者の正当性を自動証明しない。
- `uncertainty_rule`: registry不存在・artifact root内配置・hash不一致・unknown/duplicate field・未登録policy・revoked/期限外enrollment・minimum epoch未達・ledger不存在/instance/path不一致・pre/post enrollment drift・current再検証不能時はfail-closedする。既定registryとledgerをworkspace外のACL保護・耐rollback運用stateとして維持し、workspace移設やsymlinkで重なる構成は許可しない。actual運用では非巻戻しのtrusted clockを外部供給する。compilerはregistry、ledger identityや秘密鍵を暗黙作成せず、private key、ledger、actual registryをGitまたはportable JSONへ保存しない。
- `review_trigger`: actual policy/key/enrollmentを初めて登録する時、OS user/process分離やACLを導入する時、packaged binary/code signingへ移行する時、registry pathまたはOpenSSH backendを変更する時、実運用のrevocation/rotation手順を定義する時。
- `owner`: SIM-02 trust maintainer
- `implementation_evidence`: `src/champions_sim/promotion/trust_enrollment.py`、V3 compiler/readinessのpre/post/current-context再検証、enrollment negative E2E。test registry/key/policyは一時directoryだけに生成する。
- `completion_relation`: 任意policy差替えをcompile caller境界で閉じるローカル工学判断である。actual enrollment、authoritative M-B source/license、Champions実機準拠、private-match投入、ランク1相当を証明しない。

## PD-012: SIM-02C-A source-use precautionary classification

- `status`: provisional
- `scope`: SIM-02C-A local evidence inventory and candidate workbench
- `current_value`: 公式Champions情報、Yakkun、ポケモンWiki、PokeDB、旧damage実装の5 source groupをすべて`review_required`とする。公式情報はChampions固有事実の`semantic_authority`を持ち得るが、open-data licenseまたはproject-specific permissionが確認できるまで、collectionは`manual_reference_only`または`disabled_pending_review`、candidate useは`restricted_local`、redistributionは`prohibited`、production promotionは`blocked`とする。
- `reason`: 公開ページであること、公式であること、ローカルに既存bytesがあること、content hashが一致することは、保存・変換・学習・再配布・production利用の許諾を単独では示さない。旧PJにはsource別license decision、payload hash、parser lineageが不足する。
- `risk`: 過度に保守的な分類により利用可能な情報まで停止する可能性と、逆に一般的なサイト規約を個別データの法的結論と誤読する可能性がある。本判断は法的助言または権利者の許諾ではない。
- `uncertainty_rule`: source-specific reviewが完了するまでworkbenchは候補抽出とinventoryに限定し、`authorization_status: not_authorization`、production materialization 0を固定する。LLM、名前一致、全国図鑑番号、site ID、hash一致でpolicyを解除しない。
- `review_trigger`: 権利者からの明示許諾、適用可能なopen licenseと遵守手順、利用規約の更新、法務・権利レビュー、またはsourceを使用しない独立生成データへの置換が確認された時。
- `owner`: source/license review owner
- `implementation_evidence`: `data/manifests/sim02c-source-policy-register-v1.json`、`data/manifests/sim02c-m-b-source-acquisition-plan-v2.json`、凍結V1と分離したSIM-02C-A V2 compiler/Schema/tests、実M-B assessment compilation `050640f2da1374831fd34d096c9d49a811e1a67ec9f912a02f8303e575660eb4`。旧V1 compilation `bdb90c2d...`は監査でsupersededされ、現行判定に使わない。
- `completion_relation`: source policyを誤って自己承認しないための暫定gateであり、authoritative mapping、Champions fidelity、private-match投入、rank-1 equivalenceを証明しない。

## PD-013: SIM-02C-A legacy inventory and record anomaly floors

- `status`: provisional
- `scope`: SIM-02C-A local legacy evidence inventory diagnostics only
- `current_value`: `data/manifests/sim02c-m-b-source-acquisition-plan-v2.json`のplan hash `f4d0fbc5290ade0bec9079073082860f86f1fdb9805e3d6248f65cc4a15cd1f9`に封印した各raw inventoryの`expected_min_files`と各derived artifactの`expected_min_records`をroute-local anomaly floorとして使う。値の正本はこのhash付きplanであり、変更時は新plan ID/hashと本decisionのreviewを必要とする。
- `reason`: 旧PJの既知snapshotからファイルまたはrecordsが欠落した退行を、巨大payloadをGitへ入れずに検出するため。
- `risk`: 既知snapshotの件数はsourceの完全性、現行M-Bとの一致、field正確性、利用許諾を証明しない。sourceの正当な再編・重複除去でfalse blockerを出す一方、同件数の誤内容を見逃し得る。
- `uncertainty_rule`: minima到達を`complete`、`verified`、`reproduced`、promotion可能の根拠にしない。固定235 target denominator、8,024 required field denominator、hash/lineage/policy/grounding gateを縮小せず、minima未達はblocker、到達は単なる件数退行なしとして扱う。
- `review_trigger`: sourceのreview済み再取得、parser変更、deduplication、レギュレーション変更、または各routeのauthoritative manifest/record denominatorが確定した時。
- `owner`: SIM-02 data provenance maintainer
- `implementation_evidence`: plan V2、`load_source_acquisition_plan`のpositive-minimum検査、raw inventory/derived record blocker、実M-B compilation `050640f2da1374831fd34d096c9d49a811e1a67ec9f912a02f8303e575660eb4`。
- `completion_relation`: 旧snapshotの欠落検知用係数を明示するだけで、authoritative evidence、Champions fidelity、private-match投入、rank-1 equivalenceを証明しない。
