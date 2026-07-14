# SIM-02C-A V2 Authoritative Intake Validation Report

## 判定

- Engineering workbench: **GO / VERIFIED LOCALLY**
- Actual M-B production promotion: **NO-GO**
- Network reacquisition: **NOT PERFORMED**
- Production materialization: **NOT EMITTED**
- Rank-1 equivalence: **UNMEASURED / CLAIM FORBIDDEN**

本成果は、レギュレーション変更後にsource、権利、ID対応、Catalog field、mechanics証拠の不足を固定分母で再生成する基盤である。実M-Bの不足を解消したものではなく、全出力は`authorization_status: not_authorization`である。

旧V1 runの`acquisition complete 1 / partial 4`は、保存済みsnapshotへのhash結合を取得処理の再現と同一視していたため撤回した。V2は概念上の`reproduced`と`snapshot_bound`を分離するが、因果的な取得実行証跡の型を持たないためV2 Schemaが表現できるroute statusを`snapshot_bound / partial`へ閉じ、`reproduced`の虚偽claimを拒否する。実データでは全5 routeを`partial`と判定する。V1 Schemaとplanは旧文書の再検証用に凍結保存し、V2 loaderはV1 planを拒否する。

## V2実装範囲

- 5 source groupのacquisition plan V2とprecautionary policy register
- duplicate key、path/ADS escape、symlink、hash/byte/count/source driftを拒否するstrict loader
- 全route共通のpath、open-handle file key、role/hash claim
- raw manifestとinventoryのexactly-one binding、canonical `saved_to`一意性、payload projection再照合
- raw payloadをderived出力として再利用する循環、hardlink、異なるroleへの同一bytes流用の拒否
- cross-route parent、derived parent、未登録transform/intermediate/runtime依存を持つ構造化`lineage_gap_hint`
- M-B 235件を縮小しないnamespace/form mapping workbench
- species、move、ability、item、type、Mega relationのfield-level Catalog V2 workbench
- source/policy/mapping/Catalog/mechanics/scenario/grounding/holdout/trust/rehearsalについて、宣言済みworkbench surfaceと既知gap hintを全件列挙するassessment
- plan/policy/source-lock/TargetPool/4 document digestを束ねるcontent-addressed compilation
- `data/processed`配下だけへ書くCLI。production inputやruntime Catalogは出力しない

## Actual M-B V2結果

| 指標 | 結果 |
|---|---:|
| source routes | 5 |
| raw payload inventory | 2,025 files / 404,113,376 bytes |
| raw manifest metadata excluded from payload count | 25 files |
| derived artifacts | 23 |
| acquisition reproduced / snapshot_bound / partial | 0 / 0 / 5 |
| production policy resolved | 0 / 5 |
| target denominator | 235 |
| mapping candidate / conflict / verified | 219 / 16 / 0 |
| promotion unresolved | 235 |
| species / moves / abilities / items / types | 235 / 490 / 180 / 117 / 18 |
| Mega relation candidates | 70 |
| Catalog required fields | 8,024 |
| candidate / missing / unknown / verified fields | 5,577 / 1,066 / 1,381 / 0 |
| runtime-lowerable entities | 0 |
| acquisition / policy / mapping / Catalog blockers | 2,104 / 35 / 705 / 8,024 |
| mechanics/scenario/grounding/holdout/trust/rehearsal blockers | 6 |
| total blockers | 10,874 |
| blocker enumeration scope | declared surfaces + known gap hints |
| undeclared dependency enumeration complete | false |

acquisition 2,104件の内訳は、raw result未封印2,020、saved payload欠落3、byte不一致1、manifest側inventory binding欠落25、inventory側manifest binding欠落25、payload不足inventory 2、derived lineage graph表現不能15、lineage requirement未宣言8、source coverage不足5である。

`n<number>`、全国図鑑番号、名前、usage crosswalkはreviewed mappingとして数えていない。base stats、技priority、structured effect、特性・道具のtrigger/target/effect、Mega Stone relationを既定値またはno-opで埋めていない。旧PJの多くはM-A時点の候補であり、M-B意味証拠として扱わない。

## Identity

- schema version: `2.0.0`
- compiler version: `2.0.0`
- plan ID: `sim02c-m-b-source-acquisition-plan-v2`
- plan hash: `f4d0fbc5290ade0bec9079073082860f86f1fdb9805e3d6248f65cc4a15cd1f9`
- policy registry hash: `bbf3ee3afc70ed49ebeef7d196bf7324379341dd78e421da400512511dbd1277`
- source-lock byte hash: `68dc5041fa52c3ccc63f8b588cc8e52f8f6814d79203e64b0d8686b86675a8e8`
- TargetPool byte hash: `205e1772031ba78e6f790ef4bad0782ed85364618f2c007aa3a9996b171ce92d`
- target source-manifest aggregate hash: `088b43fd02b825a141c55d2ebf83b3886d50a84e5b7b92010553012ce6c99894`
- regulation revision: `official-2026-06-17`
- compilation hash: `050640f2da1374831fd34d096c9d49a811e1a67ec9f912a02f8303e575660eb4`

旧V1 compilation `bdb90c2d3128f336e09addcfc19a1cf9a13a3a073cf0cf8aad61c0f12b9f90d5`と、V2版境界確定前の中間run `ac9afe2a...`、`e63b5049...`はsupersededであり、現行判定またはpromotion根拠に使わない。

## Git外成果物

`data/processed/sim02c/authoritative-intake/050640f2da1374831fd34d096c9d49a811e1a67ec9f912a02f8303e575660eb4/`へ次を保存し、`.gitignore`適用を確認した。

| 文書 | bytes |
|---|---:|
| `source-acquisition-review.json` | 1,226,457 |
| `authoritative-mapping-workbench.json` | 178,808 |
| `authoritative-catalog-v2-workbench.json` | 2,082,792 |
| `authoritative-intake-assessment.json` | 2,997,817 |
| `authoritative-intake-compilation.json` | 4,159 |

5文書合計は6,490,033 bytes。raw/processed corpus、展開済みworkbench、assessmentをGitへ追加しない。Gitにはコード、凍結V1と現行V2 Schema、小さいmanifest、仕様、tests、本集約レポートだけを置く。

## 検証

```text
python -m pytest -q tests/test_authoritative_intake.py
57 passed in 3.98s

python -m pytest -q tests/test_authoritative_intake.py tests/test_governance_validation.py
70 passed in 7.28s

python -m pytest -q
581 passed in 78.77s

python scripts/check_repo_size.py
256 candidates / 0 violations

python scripts/validate_sim01_frozen.py
PASS / frozen Catalog, RuleSet, Replay, final state unchanged

python scripts/validate_sim01_bundle.py --usage-scope local_research
PASS / local research allowed / redistribution false

python scripts/build_m_b_authoritative_intake.py --legacy-root <legacy> --dry-run
exit 0 / operational_success=true / status=NO-GO / written=false

python scripts/build_m_b_authoritative_intake.py --legacy-root <legacy>
exit 0 / same compilation hash / written=true / 5 Gitignored documents

python scripts/build_m_b_authoritative_intake.py --legacy-root <legacy> --dry-run --require-candidate
exit 3 / reasoned NO-GO
```

plan/policyと5生成文書の7契約はstrict unknown-key Schema検査へ適合した。actual 10,874 blockerは`(code, subject)` canonical key setで10,874件すべて一意である。大規模`uniqueItems`の二乗比較を避けるためactualは同じ一意性を線形検査し、合成fixtureではSchema本体の`uniqueItems`も実行する。`blocker_enumeration_complete`は`declared_workbench_surfaces_and_known_gap_hints`という明示scope内だけの主張であり、未宣言依存の完全列挙は`false`である。

敵対テストは、同一path、cross-route path、evidence/derived ID衝突、hardlink、byte-identical role reuse、raw↔derived循環、duplicate `saved_to`、manifest/inventory間の途中変更、source IDすり替え、制御文字を含むraw source ID、非文字列derived source、declared/actual source不一致を含むlineage再封印、source labelだけの偽lineage、transform mutation、偽`snapshot_bound / reproduced` Schema claim、locator制御文字、無効RFC 6901 pointer、V1 plan混入、gapとproofの同時指定、Schema/CLI identity drift、writer mutation、partial publishを拒否する。

## 未達と次目的

未達は明確である。source permission 0/5、verified mapping 0/235、verified Catalog field 0/8,024、runtime lowerable 0、actual grounding 0、external holdoutなし、actual enrollmentなしである。`snapshot_bound`は取得再現でもChampions準拠でもない。

次の大目的を`SIM-02C-B Reviewed Evidence Promotion + Mechanics Coverage Factory`とする。reviewed source-policy/mapping/field overlayを追加し、route-qualified lineage DAGで親artifactとtransformを結合し、approved structured effectだけをhandlerへlowerし、development scenario、positive Replay、probeを生成する。権利・意味・実機証拠が不足するfieldはblockerのまま維持し、MCTS/RL/LLMへChampions environmentとして渡さない。
