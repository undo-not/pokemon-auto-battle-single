# SIM-02B Phase Contract

## Status

- Phase Contract: **SPECIFIED / FROZEN FOR SIM-02B**
- Local engineering implementation: **GO / COMPLETE**
- Test-authoritative readiness seal: **GO / `champions_candidate: false`**
- Production source trust anchor: **NO-GO / NOT IMPLEMENTED / production発行を明示停止**
- 現行SIM-02B production candidate: **NO-GO**
- 現行M-B production readiness seal: **NO-GO / 発行不可**
- ランク1位相当: **NO-GO / 未測定・主張禁止**

## Phase Contract

| 項目 | 契約 |
|---|---|
| `phase_id` | `SIM-02B` |
| `phase_name` | Production Catalog Promotion + Evidence-backed Scenario Corpus |
| `purpose` | 診断用intakeを、証拠検証済みproduction Catalog、開発scenario corpus、lineage分離済みexternal holdout、grounding、engine実行結果へ昇格させる。SIM-01の決定論・Replay・fail-closed境界を維持し、readiness sealを下流へ渡せる唯一のpromotion経路を作る。 |
| `objective_variable` | `verified_target_mapping_rate = validated/verified mapping recordを持つexact TargetPool member数 / exact TargetPool member総数`とし、unmapped/conflictも分母に残してnumerator/denominatorを`target_pool_hash`へ結合する。capability系の分母は空でないexact `TargetCapabilitySet`とし、`development_scenario_coverage_rate = lineage適合development scenarioを1件以上持ち、かつそのcapabilityのpositive engine probeが1件以上verifiedになったdeclared capability数 / declared capability総数`、`verified_grounding_conformance_rate = verified grounding assertion数 / required grounding assertion総数`、`engine_probe_pass_rate = verified pass probe数 / required probe総数`とする。これらのnumerator/denominatorを`target_capability_set_hash`と`partition_manifest_hash`へ結合する。いずれも分母0・分母差替え・member/capability除外はundefinedかつ`NO-GO`。promotion候補では4 rateを`1.0`、`external_holdout_novel_gap_count`と`silent_fallback_count`を`0`とし、`decision_lead_time_hours <= 48`でcandidateまたは根拠付き`NO-GO`を発行する。勝率や人気度で代替しない。 |
| `input_data` | resolverが取得・照合するversioned source record、license/use-policy record、artifact bytes/hash、現行Regulation/TargetPool、Catalog/RuleSet、validated mapping evidence、grounding trace、開発scenario、lineageが独立したexternal holdout、SIM-01 frozen baseline。大容量raw artifact・映像・capture・corpus・ReplayはGit外へ置き、Gitにはschema、manifest、content hash、小fixture、集約結果だけを置く。 |
| `explanatory_variables` | source/issuer/license/artifact identity、取得時刻、entity/form mapping、effect/trigger/target/order/rounding/RNG signature、scenario初期状態・選択・期待event/終状態、Regulation/Catalog/RuleSet hash、partition/lineage、grounding assertion、engine probe結果、unsupported理由、未説明holdout差分。 |
| `provisional_coefficients` | 使用率threshold、top-N、記事数、推定mapping、LLM信頼度による昇格係数は置かない。運用上の暫定値は`decision_lead_time_hours <= 48`のみとし、1週間投入要件の前半SLAとして管理する。将来係数を導入する場合は`PD-*`へ先に登録し、coverage分母や証拠要件を後から縮小しない。 |
| `output_models` | `source-to-capability-bundle-v1`と現行`ResolvedChampionsReadiness`/resolverは診断・negative gate専用として凍結し、型も判定も緩和せずpositive promotion/readiness issuance入力にしない。v2はexact `ProductionPromotionCompilationV2`（resolver-backed source/license/artifact record、validated/verified mapping、production Catalog、capability-complete development scenario corpus、lineage分離済みexternal holdout manifest、validated grounding assertion、engine-backed probe result、content-addressed promotion report）を生成し、別API `resolve_champions_readiness_v2`がexact `ResolvedChampionsReadinessV2`とreadiness sealを出力する。v1/v2の暗黙変換は禁止する。 |
| `downstream_consumers` | AI-01 paired evaluation、情報集合探索、offline/online RL、LLM/RAG環境分析、構築・6→3選出、1週間regulation adaptation、将来のprivate-match adapter。下流はCatalog、scenario partition、holdout、grounding、readiness statusを上書きまたは自己申告しない。 |
| `uncertainty_rules` | resolverが実artifact・license・source provenanceを検証し、mapping、grounding、probeがすべて`verified`の場合だけpromotion可能とする。`provisional`、`unverified`、unknown effect、license不明、artifact欠落、lineage混入、holdout新規gapはfail-closedで`NO-GO`へ送る。LLMはsource・mapping・scenario候補を提案できるが、正本、期待結果、verified statusを決めない。現行SIM-02Bは推測昇格を一切行わず、解消証拠が揃うまでexact `NO-GO`とする。 |
| `done_conditions` | **Local engineering gate:** (1) v1型・resolverの診断専用挙動を不変にしたまま、exact `ProductionPromotionCompilationV2` schema/compilerと別API `resolve_champions_readiness_v2`、exact `ResolvedChampionsReadinessV2`を実装、(2) resolverがtest-only authoritative source/license/artifact fixtureを実bytesから検証するpositive end-to-end testでv2 readinessとsealを実際に発行、(3) source bytes、license、mapping、TargetPool分母、capability set、scenario corpus、partition、holdout、Catalog/RuleSet、全bound hashの個別mutationを拒否、(4) 同一入力からbyte-identical report/sealを再生成、(5) 現行M-B入力からは不足証拠と再開条件を列挙したexact `NO-GO`を再生成、(6) 全回帰・Schema・size gate合格。このgateは外部M-B evidence不足でも`ENGINEERING COMPLETE`になり得るが、production readinessを意味しない。 |
| `production_candidate_gate` | **現行M-B data gate:** (1) 全TargetPool memberのmappingがvalidated/verified、(2) 空でないexact `TargetCapabilitySet`の全capabilityがlineage適合development scenarioとverified positive engine probeを1件以上持つ、(3) 全required groundingがverifiedでcapabilityへtrace可能、(4) 全scenarioのengine probe・Replay再実行が一致しsilent fallback 0、(5) source/license/artifact recordを実bytesへ再解決可能、(6) external holdoutがsource・収集・作成lineageでdevelopmentと分離され昇格前に封印、novel gap 0、(7) 4 rateのnumerator/denominatorと`target_pool_hash`/set/partition hashが再計算一致し全rate 1.0、(8) readiness sealが`promotion_report_hash`、`catalog_hash`、`scenario_corpus_hash`、`partition_manifest_hash`、`external_holdout_hash`、`target_capability_set_hash`、`target_pool_hash`を結合、(9) 48時間以内にcandidateまたは根拠付き`NO-GO`、残る評価・包装を含め1週間以内にprivate-match投入可否を確定。 |
| `anti_patterns` | v1診断結果のpromotion利用、self-declared `verified`、source URLだけでartifactを検証済みとすること、license不明データの採用、推定ID/form mapping、LLM生成値の正本化、空のdevelopment corpus、train/dev/holdout間の重複・lineage漏洩、holdoutを見た後の調整、engineを通さない期待結果、report hashだけを認証とみなすこと、blocker除外による分母縮小、M-B `NO-GO`の推測解除、大容量artifactのGit登録。 |

`production_candidate_gate`の前提条件0として、artifact rootと別の信頼境界にあるproduction trust anchorが、trusted issuer/authority、approved source manifest hash、license identityを検証することを要求する。これが未実装または不一致なら、他の9条件が揃っていてもproduction Compilation/readinessを発行しない。

## Promotion chain

```text
resolver-backed source/license/artifact
  -> validated and verified mapping
  -> production Catalog / RuleSet binding
  -> capability-complete development scenario corpus + positive probes
  -> validated grounding + engine-backed probe + Replay verification
  -> lineage-separated sealed external holdout
  -> content-addressed promotion report
  -> readiness seal
```

途中の段階を飛ばしたpromotionは許可しない。readiness sealは少なくとも次を一体で結合し、いずれかが変われば無効化する。

- `promotion_report_hash`
- `catalog_hash`
- `scenario_corpus_hash`
- `partition_manifest_hash`
- `external_holdout_hash`
- `target_capability_set_hash`
- `target_pool_hash`

hashは同一性・完全性の識別子であり、それ単独ではsourceの真正性、license適合、Champions準拠を証明しない。resolver検証、grounding、engine probe、sealed holdout検証を再実行できることを信頼境界とする。

## Normative v2 clarifications

実装開始前の仕様監査で、test fixtureの成功をproduction readinessへ誤昇格させないため、以下をv2の必須契約として固定する。これはcoverage閾値や暫定係数の追加ではない。

- `attestation_scope`はexactに`test_authoritative`または`production_champions`とする。`test_authoritative`はresolverがartifact bytesとtest-only source/license属性から導出する。`production_champions`はそれらに加え、artifact root外のtrusted issuer/authority attestationがapproved manifest/license identityを固定した場合だけ許可する。local manifestの`official`、`verified`、Regulationの`current`文字列はtrust anchorではなく、それだけではproduction発行しない。
- `test_authoritative`でもlocal engineering用readiness sealは発行できる。ただし`champions_candidate: false`を固定し、production adapterや実運用入力として受理しない。
- 現行M-Bのように必須artifactが不足する入力は`ProductionPromotionAssessmentV2`としてexact `NO-GO`を返す。blockerは少なくとも`stage`、`code`、`subject`、`evidence_required`、`restart_condition`を持つ。
- 全promotion gateを通過した入力だけがexact `ProductionPromotionCompilationV2`を生成できる。`resolve_champions_readiness_v2`はこのCompilationだけを受理し、Assessmentやv1 bundleの暗黙変換を許可しない。
- `ConstructionSelectionCorpus`は構築・選出の観測証拠として再利用するが、engine scenario正本にはしない。v2 scenarioは初期状態、exact choice sequence、期待event/終状態、Replay、capability witnessを結合する別型とする。
- positive probeはcaller supplied successを採用せず、Catalog/RuleSetへ結合したReplayをengineで再実行し、各declared capabilityのcanonical primary probeとwitnessを照合して導出する。required probe分母はexact TargetCapabilitySetのdeclared capability数と一致させる。
- `verified_grounding_conformance_rate`はassertion行数ではなく、exact TargetCapabilitySetが宣言するuniqueなrequired grounding requirement ID数を分母、resolver-validated assertionで満たされたunique requirement ID数を分子とする。
- developmentとexternal holdoutはrecord hashだけでなく、source、collection、authoringの3 lineage集合をすべて分離し、scenario membership/hashをpartition manifestへ固定する。
- rateのnumerator/denominatorは元snapshot hashを書き換えず、`target_pool_hash`、`target_capability_set_hash`、`partition_manifest_hash`と並べてpromotion reportへ結合する。probe結果やrateを上流snapshot hashへ逆流させない。
- sealは上記7 hashに加え、`source_resolution_set_hash`、`ruleset_hash`、`grounding_resolution_hash`、`engine_probe_report_hash`、`attestation_scope`を結合する。

## One-week regulation adaptation gate

- `t0`: 署名・hash固定済みRegulation/TargetPoolと利用可能source集合を受領した時刻。
- `t0 + 48h`: v2 candidateまたは、未解決record・不足証拠・unsupported capabilityを列挙したexact `NO-GO`を発行する。48時間の`NO-GO`は工程SLA達成であり、投入成功ではない。
- `t0 + 7d`: candidateの場合はsealed holdout、AI-01評価、回帰、artifact包装まで終え、private-match投入可否を確定する。`NO-GO`の場合はblockerと再開条件をcontent-addressed reportへ固定する。

## Current gate decision

Local engineering gateは **GO / COMPLETE**。test-authoritativeな3 source manifestから3 capability（`move.damage`、`ability.rough_skin`、`item.leftovers`）、development 3 scenario、external holdout 1 scenarioをresolverで実bytesへ結合し、完全compile、engine/Replay再実行、grounding、holdout、可搬Compilation JSON、readiness seal、再コンパイルのbyte一致を確認した。source bytes、再署名後のscenario drift、source scope誤主張などのmutationはfail-closedで拒否する。test scopeは常に`champions_candidate: false`、`champions_fidelity_status: not_attested`、`rank1_equivalence_status: unmeasured`であり、production入力にはならない。

これとは独立に、現行M-B data gateは **NO-GO**。exact assessmentはTargetPool 235に対してverified mapping 0、unresolved 219、conflict 16、target capability row 118、execution gap 118、diagnostic blocking reason 718、promotion blocker 720を返す。追加blockerはartifact-root外production trust anchor未実装である。resolver-backed production source/license、capability-completeなdevelopment corpus、lineage分離済みexternal holdout、十分なgrounding、全必須capabilityのpositive engine probeも揃っていないため、Champions readinessとproduction candidateを発行しない。engineering completeでも、このM-B `NO-GO`は外部証拠とtrust anchorが揃うまで解除されない。この判断を、使用率、記事、LLM推論、名前一致、旧Catalogの類似ID、local JSONのauthority文字列で解除してはならない。

次の大目的は`SIM-02C Production Trust Anchor + Authoritative M-B Evidence + Executable Scenario Corpus`とする。SIM-02Bの型とgateを維持したまま、artifact-root外trust anchorを実装し、実M-B blockerをauthoritative sourceまたはactual private-match traceで解消する。48時間でcandidate/NO-GO、7日でholdout・AI-01評価・包装までの投入可否を確定する。

本Phaseの完了は対戦AIの強さを示さない。ランク1位相当は、SIM-02B readinessを前提に別途、固定外部benchmarkと競争的評価で測定するまで **NO-GO / 主張禁止** とする。
