# SIM-02C-A Authoritative Intake Validation Report

## 判定

- Engineering workbench: **GO / VERIFIED LOCALLY**
- Actual M-B production promotion: **NO-GO**
- Network reacquisition: **NOT PERFORMED**
- Production materialization: **NOT EMITTED**
- Rank-1 equivalence: **UNMEASURED / CLAIM FORBIDDEN**

本成果は、レギュレーション変更後にsource、権利、ID対応、Catalog field、mechanics証拠の不足を固定分母で再生成する基盤である。実M-Bの不足を解消したものではなく、全出力は`authorization_status: not_authorization`である。

## 実装範囲

- 5 source groupのacquisition planとprecautionary policy register
- duplicate key、path escape、symlink、hash/byte/count/source driftを拒否するstrict loader
- Git外raw/processed corpusの読み取り専用inventoryとmanifest audit
- authority別acquisition profile、closed evidence role、raw-manifest/payload-inventory binding
- M-B 235件を縮小しないnamespace/form mapping workbench
- species、move、ability、item、type、Mega relationのfield-level Catalog V2 workbench
- source/policy/mapping/Catalog/mechanics/scenario/grounding/holdout/trust/rehearsalの全件assessment
- plan/policy/source-lock/TargetPool/4 document digestを束ねるcontent-addressed compilation
- `data/processed`配下だけへ書くCLI。production inputやruntime Catalogは出力しない

## Actual M-B結果

| 指標 | 結果 |
|---|---:|
| source routes | 5 |
| raw inventory | 2,050 files / 405,018,864 bytes |
| derived artifacts | 23 |
| acquisition complete / partial | 1 / 4 |
| production policy resolved | 0 / 5 |
| target denominator | 235 |
| mapping candidate / conflict / verified | 219 / 16 / 0 |
| promotion unresolved | 235 |
| species / moves / abilities / items / types | 235 / 490 / 180 / 117 / 18 |
| Mega relation candidates | 70 |
| Catalog required fields | 8,024 |
| candidate / missing / unknown / verified fields | 5,577 / 1,066 / 1,381 / 0 |
| runtime-lowerable entities | 0 |
| acquisition / policy / mapping / Catalog blockers | 2,024 / 35 / 705 / 8,024 |
| mechanics/scenario/grounding/holdout/trust/rehearsal blockers | 6 |
| total blockers | 10,794 |

主要な取得不足は旧raw manifestのunsealed 2,020件、saved payload missing 3件、byte mismatch 1件である。`n<number>`、全国図鑑番号、名前、usage crosswalkはreviewed mappingとして数えていない。base stats、技priority、structured effect、特性・道具のtrigger/target/effect、Mega Stone relationを既定値またはno-opで埋めていない。

## Identity

- plan hash: `740db609476684f6772f08da120faef8534855d851e851731167195a5209d75a`
- policy registry hash: `bbf3ee3afc70ed49ebeef7d196bf7324379341dd78e421da400512511dbd1277`
- source-lock byte hash: `68dc5041fa52c3ccc63f8b588cc8e52f8f6814d79203e64b0d8686b86675a8e8`
- TargetPool byte hash: `205e1772031ba78e6f790ef4bad0782ed85364618f2c007aa3a9996b171ce92d`
- target source-manifest aggregate hash: `088b43fd02b825a141c55d2ebf83b3886d50a84e5b7b92010553012ce6c99894`
- regulation revision: `official-2026-06-17`
- compilation hash: `bdb90c2d3128f336e09addcfc19a1cf9a13a3a073cf0cf8aad61c0f12b9f90d5`

M-B専用CLIは上記plan/policy/source-lock identityをpinする。TargetPoolはtracked official source manifestのpath/hash/byte count/235 record/regulation revisionへ結合される。source policyはrouteのexact source IDsとprivate-match/trainingを含む全用途へ結合され、writerは書込み直前に全documentを再検証し、stagingからatomic publishする。

同じactual inputsを別processでdry-runとwrite runへ通し、同じcompilation hashと4 document digestを得た。初回cold runは約77秒、後続warm runは約9秒だった。これは同一PC上の参考実測であり、48時間rehearsal達成または外部source待ち時間の測定ではない。

## Git外成果物

`data/processed/sim02c/authoritative-intake/bdb90c2d3128f336e09addcfc19a1cf9a13a3a073cf0cf8aad61c0f12b9f90d5/`へ次を保存し、`.gitignore`適用を確認した。

| 文書 | bytes |
|---|---:|
| `source-acquisition-review.json` | 1,149,480 |
| `authoritative-mapping-workbench.json` | 178,808 |
| `authoritative-catalog-v2-workbench.json` | 2,082,792 |
| `authoritative-intake-assessment.json` | 2,967,278 |
| `authoritative-intake-compilation.json` | 3,774 |

raw/processed corpus、展開済みworkbench、assessmentをGitへ追加しない。Gitにはコード、7 Schema、2 manifest、仕様、tests、本集約レポートだけを置く。

## 検証

```text
python -m pytest -q tests/test_authoritative_intake.py
28 passed

python -m pytest -q tests/test_authoritative_intake.py tests/test_governance_validation.py
41 passed

python -m pytest -q
552 passed in 78.67s

python scripts/check_repo_size.py
249 candidates / 0 violations

python scripts/validate_sim01_frozen.py
PASS / frozen Catalog, RuleSet, Replay, final state unchanged

python scripts/build_m_b_authoritative_intake.py --legacy-root <legacy> --dry-run
exit 0 / operational_success=true / status=NO-GO / written=false

python scripts/build_m_b_authoritative_intake.py --legacy-root <legacy>
exit 0 / same compilation hash / written=true / 5 Gitignored documents
```

合成fixtureは決定性、source-manifest固定分母、regulation revision、自己hash、duplicate key、path/ADS escape、symlink、snapshot drift、source-bound policy全用途、Catalog field gap、7 Schema、atomic content-addressed writerを検査する。actual 5出力もtyped/unknown-key Schema検査と線形一意性検査へ適合した。stdlib validatorの`uniqueItems`をactual 10,794 blockerへ直接適用する経路は二乗時間になるため、actualでは同じ一意性をcanonical key setで線形検査した。

## 未達と次目的

未達は明確である。source permission 0/5、verified mapping 0/235、verified Catalog field 0/8,024、runtime lowerable 0、actual grounding 0、external holdoutなし、actual enrollmentなしである。

次の大目的を`SIM-02C-B Reviewed Evidence Promotion + Mechanics Coverage Factory`とする。reviewed source-policy/mapping/field overlayを追加し、approved structured effectだけをhandlerへlowerし、development scenario、positive Replay、probeを生成する。権利・意味・実機証拠が不足するfieldはblockerのまま維持し、MCTS/RL/LLMへChampions environmentとして渡さない。
