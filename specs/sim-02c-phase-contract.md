# SIM-02C Phase Contract

## Status

- Phase Contract: **SPECIFIED / IMPLEMENTATION GATE OPEN**
- SIM-02B V2 test-authoritative path: **FROZEN / LOCAL ENGINEERING ONLY**
- SIM-02B V2 production issuance: **NO-GO / FAIL-CLOSEDを維持**
- SIM-02C trust and partition-integrity engineering gate: **GO / VERIFIED LOCALLY WITH EPHEMERAL FIXTURE**
- Production trust policy/key enrollment: **NO-GO / NOT CONFIGURED**
- 現行M-B authoritative data gate: **NO-GO**
- 現行M-B production readiness: **NO-GO / 発行不可**
- Rank-1 equivalence: **UNMEASURED / CLAIM FORBIDDEN**

## Phase Contract

| 項目 | 契約 |
|---|---|
| `phase_id` | `SIM-02C` |
| `phase_name` | Production Trust Anchor + Authoritative M-B Evidence + Executable Scenario Corpus |
| `purpose` | SIM-02Bの証拠再計算経路を維持したまま、artifact自身のauthority文字列では偽造できない外部trust anchor、意味的に重複しないdevelopment/external-holdout、再供給可能な入力manifestを追加する。その後、現行M-B全235 memberのauthoritative mapping、Catalog/RuleSet、実行scenario、groundingを同一lineageへ収め、AI学習直前のprivate-match環境を発行可能にする。 |
| `objective_variable` | 工学trust gateは`production_trust_verification_rate = valid external signatureで承認されたrequired trust subject数 / required trust subject総数`、`lineage_attestation_coverage_rate = resolver-backedかつ外部署名対象へ含まれるrequired source/collection/authoring lineage数 / required lineage総数`、`cross_partition_execution_overlap_count`、`trust_policy_rollback_count`を測る。完了値は前二者`1.0`、後二者`0`。M-B data gateはSIM-02Bの4 rateすべて`1.0`、holdout novel gapとsilent fallbackを`0`、mapping `235/235`とする。hash件数や署名成功だけをChampions conformanceへ読み替えない。 |
| `input_data` | SIM-02B V2 source/license/artifact resolver、Regulation/TargetPool/Catalog/RuleSet、mapping/grounding/construction/scenario/Replay、artifact root外のversioned trust policy・公開鍵・revocation state・事前provision済みreplay ledger・非巻戻しtrusted clock、callerが選択できない固定外部enrollment registry、外部署名済みattestation envelope、SIM-01 frozen baseline。秘密鍵・credentialはcompiler PC、artifact root、Git、portable JSONへ置かない。 |
| `explanatory_variables` | trust enrollment registry ID/hash、enrollment ID/binding hash/status/validity/minimum epoch、ledger instance ID/path binding、trust policy ID/epoch/hash、issuer/key IDと公開鍵fingerprint、signature algorithm/namespace、attestation ID・validity、subject hash、source manifest/license/artifact/binding hash、ledger state、Regulation/TargetPool identity、execution fingerprint、source/collection/authoring lineage、partition、mapping/effect/trigger/target/order/rounding/RNG、grounding・probe・holdout差分、検証時刻と失効理由。 |
| `provisional_coefficients` | coverage・mapping・署名にthresholdを置かない。署名は1件でも不足・期限外・失効・policy rollbackならproduction `NO-GO`。48時間SLAだけを`PD-008`で維持する。OpenSSH Ed25519 verifier backendは係数でなく`PD-010`の暫定実装選択として追跡する。 |
| `output_models` | V2を緩和せず、新しい`ProductionTrustSubjectV1`、`ProductionTrustAttestationV1`、`ProductionTrustPolicyV1`、`ResolvedProductionTrustV1`、artifact-root非依存の`ProductionPromotionInputManifestV3`、trust bindingを持つ`AttestedProductionPromotionCompilationV3`、`ResolvedChampionsReadinessV3`を別型で出力する。V3 portable summary単体はauthorizationではなく、外部artifact root、current trust policy/revocation/ledger、必要なruntime evidenceを再供給して再検証した場合だけactionableとする。 |
| `downstream_consumers` | SIM-02 actual/sealed-historical rehearsal、AI-01 paired evaluation、情報集合探索、RL/LLM/RAG、構築・選出、private-match adapter。production下流はV2 report/readiness、署名JSON、hash summary単体を受理せず、current trust contextで再検証済みV3 sealだけを受理する。 |
| `uncertainty_rules` | local manifestの`official`/`verified`、任意の公開鍵・policy path、自己署名、期限切れ・失効key、policy epoch rollback、artifact root内trust material、署名subjectとsource/bindingの差、ledger上の同一attestation ID別subject、意味的Replay重複、自己申告lineageをfail-closedにする。LLMは候補抽出だけを行い、issuer enrollment、署名、license verification、mapping verification、期待event、holdout合否を決めない。 |
| `done_conditions` | 下記のEngineering GateとM-B Data Gateを別々に満たす。Engineering完了だけでproduction policy configured、Champions fidelity、M-B readiness、rank-1 equivalenceを宣言しない。 |
| `anti_patterns` | V2のunconditional production拒否を削除してcaller flagで通す、HMAC共有secretをChampions authenticityと呼ぶ、自作暗号、compiler PCへproduction秘密鍵を置く、caller supplied public key/policyを無条件にroot trustとする、signatureだけをlicense/grounding証拠にする、replay/scenario/battle/request IDの変更でholdout重複を隠す、lineage labelだけで独立性を宣言する、portable JSON単体を再検証可能と呼ぶ、旧PJの禁止された自動取得routeやlicense不明raw dataをproductionへ昇格する。 |

## Trust subject and verification contract

OpenSSH `ssh-keygen -Y verify`のEd25519署名を初期backendとし、署名messageはUTF-8 canonical JSONと専用namespaceでdomain separationする。署名対象にはheaderを含む全unsigned envelopeを入れ、少なくとも次を固定する。

- schema/canonicalization/domain version
- randomで一意な`attestation_id`
- `issuer_id`、`key_id`、algorithm、namespace
- `issued_at`、`not_before`、`expires_at`
- trust `policy_id`、`policy_epoch`
- project/purpose=`production_source_approval`/environment=`private_match`
- compiler contract、`attestation_scope=production_champions`
- Regulation ID/revision/hash、TargetPool hash
- sorted manifest ID/hash、license hash、全artifact ID/role/size/SHA-256から導くsource authority subject hash
- artifact role bindingとReplay bindingから導くrequest binding hash

検証contextは入力artifact rootの外に置き、exact policy hashをpinする。さらに、callerがpathを選択できない固定のper-user enrollment registryをartifact rootとworkspaceの外から解決し、registry hash、enrollment ID/binding、policy ID/hash、OpenSSH executable hash、minimum policy epoch、status、validity、事前provision済みSQLite ledgerのinstance ID/path bindingを一致させる。policyはissuer/key/public key、key validity/status、minimum epochを持つ。署名のcryptographic verificationだけでなく、current trusted clock、policy/key/enrollment validity、revocation、subject exact一致、policy epoch rollback、外部ledger上の`(issuer,key,attestation_id)->subject_hash`一意性を検査する。同じID・同じsubjectの再検証はidempotent、別subjectは拒否し、ledger消失または別instance差替えもV3入口で拒否する。

秘密鍵は外部署名工程だけが保持し、compiler/repositoryへ供給しない。公開鍵、signature、fingerprint、policy descriptor、enrollment descriptorは非秘密だが、任意policy、enrollment registry pathまたは履歴のない別ledgerをcallerが差し替えられる構成はproduction root trustとしない。実運用policy/key/ledger identityのenrollmentはユーザーが明示的に行う別の外部状態変更であり、test keyの成功で代替しない。現在のthreat modelはprivate helper直呼び、同一process内の悪意あるmonkeypatch、起動環境の`HOME`/`USERPROFILE`改変、同一OS user権限による実装・固定registry・ledger snapshotの改変/rollback、trusted clock偽装を防ぐものではなく、code integrity、非巻戻し時計、OS file protection/backupを信頼境界に置く。

## Semantic partition integrity contract

`ReplayRecord.replay_hash`は完全記録identityであり`replay_id`等の記録metadataを含むため、それだけをdevelopment/holdout重複判定へ使わない。V3 engineering gateでは、verified Replayから次のexecution substanceを正規化した`replay_execution_hash`を導出する。

- simulator/engine semanticsとCatalog/RuleSet content hash
- private initial battle state。ただしbattle/request/action/record IDは位置に基づくcanonical labelへ正規化する
- RNG algorithmと全RNG境界
- ordered decision kindと選択したaction substance
- ordered events、terminal outcome/result

`replay_id`、source manifest ID、provisional decision label、partition/collection/authoring label、derived state hashだけの変更ではexecution hashを変えない。developmentとexternal holdoutの`scenario_hash`、full Replay hash、execution hash、source/collection/authoring lineageのいずれかが重複すればfail-closedとする。scenarioが宣言するexecution hashはcompilerがbound Replayから再計算して一致を要求する。

collection/authoring lineageはtest-authoritative scopeではfixture contractの検査対象、production scopeではresolver-backed artifactに含まれ、さらに外部trust subjectがそのmanifest/artifact bytesを承認した場合だけattestedとする。ラベルの文字列差だけで独立とみなさない。

## Engineering Gate

1. SIM-02B V2のtest-authoritative positive pathとproduction unconditional fail-closedを回帰維持する。
2. replay/scenario/partition schemaへ`replay_execution_hash`を結合し、ID・lineageだけを変更した同一Replayをholdoutとして拒否する。
3. strict trust policy/attestation/enrollment parser、固定外部enrollment registry、OpenSSH signature verifier、trusted clock、expiry/revocation/policy epoch、外部ledgerを実装する。
4. V3のpre/post resolver結果は同一content-addressed input manifestへ収束しなければならず、その間のV2 core compileは1つのresolved source snapshotだけを消費する。複数回のpre/post resolutionはTOCTOU検出のためであり、core内部で異なるsnapshotを混在させない。署名subjectを再計算し、pre/postのsubject・trust・enrollment bindingが一致してからのみeffective production scopeを発行する。
5. V3 Compilation/readinessはattestation、policy、subject、trust receipt、V2 component/document hashを一体で結合し、current trust contextなしの再検証を拒否する。
6. artifact-root非依存input manifestをround-tripし、絶対path・secretをserialized formへ含めない。fresh process再構築に未対応のruntime evidenceがあれば明示blockerとして残し、portable summaryをstandalone authorizationと呼ばない。
7. wrong key/issuer/namespace/signature/subject、期限前後、revoked key/enrollment、policy rollback、ledger ID conflict・消失・別instance差替え、artifact drift、change-compile-restore race、固定registryに登録されない任意policy自己差替え、V2 bypassをnegative E2Eで拒否する。
8. 同一入力・同一trust policy/attestationからbyte-identical V3 summary/sealを再生成し、全回帰・strict Schema・size gateを通す。

Engineering Gateではtest用offline keyを一時directoryに生成してcryptographic plumbingを検証できる。ただしそのkey/policyをactual production trustとして保存・登録しない。

## Authoritative M-B Data Gate

1. 公式M-B Regulation/eligible artifactsの取得・保存・利用条件をreviewし、外部trust policyのapproved issuerがmanifest/license identityへ署名する。
2. 全235 target memberをnamespace付きauthoritative recordへ結合し、mapping `235/235`、unresolved/conflict `0`を再計算する。名前・全国図鑑番号・旧サイトIDの推測は使わない。
3. Catalog/RuleSetへ技priority/structured effect、特性・道具handler、base stats、Mega relationを入れ、exact TargetCapabilitySetの分母を確定する。
4. 全capabilityにlineage適合development scenario、verified positive Replay/probe、required groundingを持たせる。
5. 昇格前に封印し、developmentとsource/collection/authoring/executionで独立したexternal holdoutを開き、novel gapとoverlapを0にする。
6. actual BlueStacks/private-match captureからUI observation、event順、端数、RNG境界、M-B megaをgroundingする。
7. 4 rate `1.0`、silent fallback `0`、holdout novel gap `0`のV3 production readinessをcurrent trust contextで再検証する。
8. actualまたはsealed-historical regulationで48時間candidate/正しいNO-GOと7日投入判断をwall-clock実測する。

## Current decision

Engineering implementationはephemeralなtest key/policy/enrollment registryを使う限定fixtureで`GO / VERIFIED LOCALLY`。これは署名・再解決・意味的partition・portable input・current-context再検証の配線を証明するだけである。現行M-Bは0/235 verified mapping、unresolved 219、conflict 16、118/118 target row/execution gap、actual grounding 0、actual production policy/key/enrollment未登録のためData Gateは`NO-GO`。Champions fidelity、private-match投入可能性、ランク1相当は未証明であり、V3 engineering fixtureが成功してもこの判定を解除しない。
