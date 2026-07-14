# SIM-02C-A Authoritative Evidence Intake + Catalog V2 Workbench Contract

## Gate decision

- Work type: specification-led implementation
- Engineering decision: **GO**
- Actual M-B promotion: **NO-GO**
- Official/third-party automated reacquisition: **NO-GO pending source-specific permission review**
- Existing SIM-02 intake v1 and promotion V2/V3: **FROZEN / MUST NOT BE RELAXED**

## Purpose

現行M-Bのボトルネックは推論器ではなく、235 target memberと技・特性・道具・Mega relationを、権利・出典・namespace・form・field-level provenance付きで既存promotion V2/V3へ供給できないことである。本workbenchは旧`champions` PJ、公式一次情報、第三者参照、private-match観測の候補を同じ台帳へ入れる。ただし候補抽出とproduction昇格を分離し、権利または意味上の権威が不足するsourceを`verified`へ変換しない。

## Phase contract

| 項目 | 契約 |
|---|---|
| `phase_id` | `SIM-02C-A` |
| `phase_name` | Authoritative Evidence Intake + Catalog V2 Workbench |
| `objective_variable` | `acquisition_route_integrity_rate`、`source_policy_resolution_rate`、`authoritative_mapping_rate`、`catalog_required_field_evidence_rate`、`assessment_blocker_enumeration_rate`を測る。最初の4値はpromotion条件ではすべて`1.0`、最後は固定分母上の不足を漏れなく列挙して`1.0`とする。現実入力では不足を分母から除外しない。 |
| `input_data` | Git管理する取得plan・policy register・Schema、Git外の旧PJ/raw/processed artifact、公式Regulation/TargetPoolの小さいmanifest/fixture、既存Catalog intake bundle。外部rootの絶対pathは実行時入力でありportable report identityへ入れない。 |
| `explanatory_variables` | semantic authority、usage permission、source namespace/entity/form、raw/manifest/parser/derived artifact hash、取得時刻、HTTP metadata、mapping basis/review status、Catalog field status/source refs、conflict、missing evidence、mechanics lowering status。 |
| `output_models` | `SourceAcquisitionReviewV1`、`AuthoritativeMappingWorkbenchV1`、`AuthoritativeCatalogV2Workbench`、`AuthoritativeIntakeAssessmentV1`、content-addressed `AuthoritativeIntakeCompilationV1`。これらは常に`authorization_status: not_authorization`で、既存V2/V3 production inputへ暗黙変換しない。 |
| `downstream_consumers` | source/licenseの人手review、235 mapping review、Catalog V2編集、mechanics backlog、将来の明示的V2 source/license/mapping materializer。RL/LLM/searchは本workbenchをChampions environmentとして受理しない。 |
| `uncertainty_rules` | semantic authorityとusage permissionを別変数にする。公式sourceでもopen licenseまたは明示許諾がなければusage permissionを推定しない。第三者sourceの名前・全国図鑑番号・site ID一致はcandidateでありverifiedではない。LLMは候補を提案できるがreview decision、license、mapping、Catalog field、expected mechanicsをverifiedにしない。 |
| `done_conditions` | 下記Engineering Gateを満たし、actual旧PJ dry-runから固定235分母、候補件数、conflict、rights/lineage/field/mechanics blockerを決定論的に生成する。 |
| `anti_patterns` | 公式であることを利用許諾と同一視する、旧fetch scriptを無審査で再実行する、`n<number>`を全国図鑑番号とみなす、名前一致をverified mappingにする、missing fieldを既定値で埋める、最初の例外でassessmentを中断する、raw/processed corpusをGitへコピーする、workbench hashをproduction authorizationと呼ぶ。 |

## Source boundary

各routeは少なくとも次を分離する。

1. `semantic_authority`: そのsourceがChampions固有規則、一般ポケモン情報、第三者参照、観測、local modelのどれを説明できるか。
2. `usage_permission`: collection、local candidate use、private-match use、training、redistribution、production promotionの各状態。
3. `acquisition_integrity`: source config、fetcher、raw manifest、payload、parser、derived artifactを相互にhash結合できるか。
4. `namespace`: `champions_target`、`national_dex`、`yakkun`、`pokedb`等を値と別に保持する。

`semantic_authority=champions_official`でも`usage_permission=promotion_blocked`は正常な組合せである。逆にopen licenseの一般データでもChampions固有event順の権威にはならない。

## Mapping contract

- 分母はexact M-B TargetPool 235件で固定する。
- 各rowはtarget key、target source record hash、source namespace、source entity ID、form ID、variant ID、mapping basis、candidate IDs、review status、evidence refsを持つ。
- `verified`にはnamespace付きrecord、form/variant一致、source record hash、review decision、利用可能性が必要である。
- 名前一致、全国図鑑番号だけの一致、`n<number>`変換、transitive crosswalk、usage listingは`candidate`以下とする。
- unresolved、conflict、candidateを分母から除外しない。

## Catalog V2 workbench contract

各speciesは少なくともname、types、base stats 6値、abilities、legal moves、form relationをrequired fieldとする。各fieldは値とは別にstatusとsource refsを持つ。moveはtype/category/power/accuracy/PP/priority/target/contact/structured effect、ability/itemはtrigger/target/structured effectまたは明示`unknown`、Megaはbase/mega form、required item、base/mega stats、types、abilityを持つ。

このworkbenchは候補値を保持できるが、次を満たさないfieldはruntime Catalogへlowerしない。

- source policyが対象用途を許す
- mappingがreview済み
- field evidenceがrecord hashへ結合される
- structured effectがengine handlerへ明示対応する
- unknown、conflict、missingを通常damage/no-op/defaultへ落とさない

## Assessment contract

assessmentはsource、policy、mapping、Catalog field、effect/handler、scenario、grounding、holdout、trustの不足を、最初の失敗で停止せずソート済み全件として返す。blockerは`stage`、`code`、`subject`、`evidence_required`、`restart_condition`を必須とする。同じ入力bytesとplanからbyte-identical report hashを再生成する。

## Engineering Gate

1. plan/policy/report/mapping/Catalog/assessment Schemaとstrict loaderを実装する。
2. path escape、symlink、duplicate JSON key、hash/size/count drift、source ID不一致をfail-closedにする。
3. 旧PJ raw/processedをコピーせずroute単位でhash集約し、parser/derived lineageを固定する。
4. source policyが未審査・restrictedなら、候補抽出は許してもproduction materializationを行わない。
5. 235 mapping rowを必ず出力し、candidate、conflict、unresolved、verifiedを別集計する。
6. Catalog required fieldをfield-levelに監査し、missing/conflict/unknown mechanicsを全件列挙する。
7. synthetic positive-integrity/negative-permission fixtureと敵対的mutation testを通す。
8. actual旧PJ dry-run、全回帰、SIM-01 frozen、repository size gateを通す。

## Current expected decision and hardening

### Hardening invariants

- evidence `role` はclosed enumとし、任意名の既存ファイルを取得証拠として受理しない。
- `champions_official` / `general_official` / `third_party_reference` はrequired `source_config`・required `raw_manifest`・1件以上のraw inventory・1件以上のderived artifactを必須とする。`private_observation`はrequired `raw_manifest`・inventory・derived artifact、`local_implementation`はrequired `implementation`・`review_record`・`validator`・derived review artifactを必須とする。
- source coverageに数えるevidenceはprofileごとに限定する。外部／観測routeはidentity一致したrequired raw manifest、local routeはimplementation、全routeはsource一致したderived artifactだけをcoverageに数える。parser、fetcher、source config単独では代替できない。
- raw manifestの各`payload.saved_to`は宣言済みraw inventoryのpath/suffix内になければならず、存在・byte count・SHA-256が一致して初めてacquisition chainを満たす。
- M-B専用CLIはreview済みplan、policy register、source lockの既知SHA-256だけを受理する。
- TargetPoolの`source_manifest_ids`はplanのbindingと完全一致し、manifest path/hash、artifact path/hash/byte count/record count、regulation ID/revisionを同一Compilationへ結合する。これを満たさない分母は`denominator_final`にしない。
- policyはrouteの全`source_ids`へ完全結合し、review、collection、candidate、private-match、training、redistribution、promotionの全次元が`allowed`でなければresolvedに数えない。
- evidence identityとJSON解析は同じ一回のbyte snapshotから作る。duplicate key、非有限数、symlink、path escape、NTFS ADS、Windows予約名を拒否する。
- `AuthoritativeIntakeCompilation`は書込み直前にself-hash、cross-binding、`not_authorization`、`candidate=false`を再検証する。
- 最終content-addressed directoryはstaging directoryの全ファイルをfsync・検査した後にatomic renameで公開し、失敗時にpartial final directoryを残さない。

### Current decision
旧PJはraw約405MB、processed約28MBの取得・正規化候補を持つが、payload hash付き取得manifest、source別license review、namespace-safe mapping、M-B更新、Mega Stone relation、actual groundingが不足する。従ってrestricted-local candidate intakeは`GO`、verified M-B promotionは`NO-GO`である。公式M-Bページも意味上は一次情報だが、公開API/open-data licenseは確認できず、project policyでは`restricted_local / no_open_license / promotion_blocked`とする。これは法的結論ではなく、許諾を推定しない保守的な実装gateである。
