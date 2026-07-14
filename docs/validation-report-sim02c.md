# SIM-02C Validation Report

## 結論

SIM-02Cの **trust/partition engineering gateはGO / VERIFIED LOCALLY WITH EPHEMERAL FIXTURE** である。SIM-02B V2のproduction拒否を緩和せず、別型V3として、意味的Replay execution fingerprint、artifact-root非依存input manifest、OpenSSH Ed25519 attestation、callerが選択できない固定外部enrollment registry、pre/post/current-context再検証、trust-bound Compilation/readinessを接続した。

この判定は暗号・resolver・partition・portable identityの工学配線だけを対象とする。test key、policy、enrollment registryは一時directoryに生成した検証用であり、actual issuer/source/license、M-B 235 member、Champions実機挙動、private-match投入、対戦AIの強さを証明しない。**actual M-B data/enrollment gateはNO-GO**、ランク1相当は **UNMEASURED / CLAIM FORBIDDEN** である。

## Trust状態の3層

| 層 | 現在の判定 | 意味 |
|---|---|---|
| SIM-02B V2 production path | `FAIL-CLOSED / issuance disabled` | production verifierを意図的に持たず、local JSONを再署名してもproduction発行しない |
| SIM-02C V3 engineering verifier | `GO / VERIFIED LOCALLY` | ephemeral key/policy/enrollmentで署名・固定登録・再解決・再検証の配線を確認した |
| actual M-B policy/key/enrollment | `NO-GO / NOT CONFIGURED` | 実運用registry、approved issuer/key/policy、authoritative M-B evidenceを登録していない |

`data/golden/sim02b-m-b-no-go-v2.json`の`production_trust_anchor_status: not_implemented`は、SIM-02B完了時点のfrozen V2 assessment fieldである。V3 verifierが後続実装されたことと矛盾しない一方、actual enrollment済みを意味するfieldでもない。goldenはV2のexact NO-GO再現用として変更せず、3層の現在状態は本レポートとSIM-02C Phase Contractを正本とする。

## Engineering evidence

最小のproduction-shaped fixtureは、次の限定入力を一つのV3 Compilation/readinessへ束ねる。

| 指標 | Fixture値 | 解釈 |
|---|---:|---|
| active trust enrollment / required | 1 / 1 | test専用の固定外部registry entry |
| valid attestation subject / required | 1 / 1 | test専用Ed25519署名 |
| signed source manifests | 3 / 3 | core、development、external holdout |
| subject-bound source artifacts | 19 / 19 | 16 source-data artifactと3 license record |
| source lineage separation | 2 / 2 | developmentとholdoutの宣言lineageを分離 |
| collection lineage separation | 2 / 2 | developmentとholdoutの宣言lineageを分離 |
| authoring lineage separation | 2 / 2 | developmentとholdoutの宣言lineageを分離 |
| combined lineage checks | 6 / 6 | 上記3次元×2 partition。文字列差だけではなくbound artifactを検査 |
| cross-partition execution overlap | 0 | cosmetic ID全変更でも同一executionを拒否 |
| accepted policy rollback / ledger conflict | 0 | 攻撃入力はfail-closed。試行回数を強度指標にしない |
| portable authorization status | `not_authorization` | current trust contextなしではactionableにしない |

これらはfixtureの件数であり、actual M-B coverage率、署名sourceの正しさ、公開データの利用許諾、外部強度を表さない。

## Snapshot and TOCTOU contract

V3は単純な「resolverを一度だけ呼ぶ」契約ではない。次の二つを同時に要求する。

1. pre/post resolutionは同じcontent-addressed `ProductionPromotionInputManifestV3`へ収束し、manifest、artifact、Replay、trust subject、enrollment bindingのdriftを拒否する。
2. その間のV2 core compileは、各source manifestを一度解決して得た1つのresolved source snapshotだけを消費し、compile前半と後半で異なるsnapshotを混在させない。

pre/postの複数resolutionはTOCTOU検出のためであり、core compileの単一snapshot契約と矛盾しない。保持済みV3 Compilation/readinessを使用する時も、current policy、revocation、trusted clock、ledger、固定enrollment registry、artifact rootを再供給して同じ収束を確認する。

## Trust and adversarial boundary

- 専用namespaceとcanonical JSONでEd25519署名messageをdomain separationする。
- policy、OpenSSH executable、issuer/key、subject、Regulation/TargetPool、source/license/artifact、request/Replay bindingをhash固定する。
- fixed per-user enrollment registryのregistry/enrollment binding、policy hash、binary hash、minimum epoch、status、有効期間、provision済みledger instance/path bindingを再検証する。
- wrong key/issuer/namespace/signature/subject、期限前後、revocation、policy rollback、ledger ID conflict・削除・別instance差替え、artifact drift、未登録の自己作成policy、V2 bypassを拒否する。
- stable portable bindingから検証時刻と外部pathを除外するが、current-context再検証を省略しない。
- private key、credential、actual registry、SQLite ledgerをrepository、artifact root、portable JSONへ保存しない。

現在のthreat modelはcompile callerが通常APIへ任意contextを渡す攻撃を固定registryと登録済みledger identityで閉じる。Python実装自体の改変、private helper直呼び、同一process monkeypatch、起動時`HOME`/`USERPROFILE`、同一OS user権限によるregistry/ledger rollback、trusted clock provenance、OpenSSH binaryまたはworkspaceのcode integrityは別の運用信頼境界であり、現engineering fixtureは耐タンパ性を証明しない。actual authorizationではACL・永続化/backup・非巻戻し時計が追加前提である。

## Actual M-B data/enrollment gate

frozen V2 goldenと対応するlarge assessmentから再確認できる値は次のとおりである。

| 指標 | 現在値 | Gate上の意味 |
|---|---:|---|
| TargetPool members | 235 | 分母を人気度や取得可能件数で縮小しない |
| verified mapping | 0 / 235 | authoritative mappingは未昇格 |
| unresolved / conflict mapping | 219 / 16 | ID推測で埋めない |
| target capability rows / execution gaps | 118 / 118 | 暫定行の全てでpositive execution証拠が不足 |
| actual BlueStacks GroundingTrace | 0 | Champions実機conformance未証明 |
| diagnostic / promotion blockers | 718 / 720 | 異なるgate層の件数であり相互に上書きしない |
| development/grounding/probe rates | `null` | 未測定を1.0として扱わない |
| external holdout novel gap | `null` | actual corpus未成立 |
| rank-1 equivalence | `unmeasured` | synthetic勝率や署名成功で代替しない |

この集約値はsource report hash `2c443ea3d196efaad9c99b3f5012ffa800f093595fa87d0afdcde332914632c8`、assessment hash `2522c71c2e0a65649f7a133bf03f9f223c6a74e8db45bd06ea45c868be438980`へ固定されている。

`silent_fallback_count: 0`もpositive executorの証拠ではない。actual policy/key/enrollment、authoritative source/license、235/235 mapping、構造化Catalog/RuleSet、capability-complete scenario/Replay/probe、lineage独立holdout、actual private-match grounding、actual/sealed-historical 48時間rehearsalが揃うまで、production candidate、Champions fidelity、private-match投入は`NO-GO`とする。

## Repository and artifact policy

GitにはSchema、最小fixtureを作るtest code、仕様、集約結果だけを置く。actual M-B raw source、取得payload、Catalog中間物、scenario corpus、Replay、capture、trajectory、model/checkpoint、private key、production registry、ledgerはGit外のcontent-addressedまたは明示管理された外部stateへ置く。fixtureの19 artifactという件数を実M-B corpusの縮小コピー理由にしない。

## 検証

SIM-02C focused verificationはtrust/enrollment、input manifest、V3 compiler/readiness、semantic partition、V2 fail-closed回帰、strict Schemaを対象とした。全回帰、SIM-01 frozen validation、repository size gate、`git diff --check`も最終統合で実行した。

- focused verification: **97 passed in 29.15s**
- full regression: **524 passed in 68.27s**
- trust enrollment + V3 compiler focused subset: **26 passed in 17.85s**
- repository size gate: **233 candidates / 0 violations**（通常2 MiB、fixture/golden 256 KiB上限）
- SIM-01 frozen validation: **`ok=true`**、Catalog/RuleSet/Replay/final-state hash不変

```powershell
python -m pytest -q tests/test_production_trust_v1.py tests/test_production_trust_enrollment_v1.py tests/test_promotion_input_manifest_v3.py tests/test_production_compiler_v3.py tests/test_promotion_scenarios_v2.py tests/test_promotion_compiler_e2e_v2.py
python -m pytest -q
python scripts/check_repo_size.py
python scripts/validate_sim01_frozen.py
git diff --check
```

## 次の大きな目的

次の大目的は、SIM-02Cの工学verifierへ **actual production enrollment + authoritative M-B evidence + executable scenario corpus** を供給し、現M-Bのexact `NO-GO`を証拠で一件ずつ解消することである。

完了条件はactual M-B 235/235 mapping、全required capabilityのpositive executor/Replay/probe/grounding、source・collection・authoring・executionが独立したsealed holdout、current trust contextでのV3再検証、actualまたはsealed-historical regulationでの48時間candidate/正しいNO-GOと7日投入判断である。その後にだけAI-01上でsearch/RL/LLMを比較し、ランク1相当を別の外部較正gateで測定する。
