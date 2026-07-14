# SIM-02B Validation Report

## 結論

SIM-02Bの **local engineering gateはGO / ENGINEERING COMPLETE** である。test-authoritative scopeでは、source・license・artifactを実bytesへ再解決し、3 capability、development 3 scenario、lineage分離済みexternal holdout 1 scenarioをcompileして、engine/Replay probe、grounding、holdout、可搬Compilation、readiness sealまで正規のpositive経路を通せる。再コンパイルは決定論的で、保持済みCompilationの再検証とartifact改変拒否も成立する。

一方、これとは独立した **現行M-B data gateはNO-GO** である。test-authoritative fixtureはcompilerとresolverの実装正当性を示すが、Pokémon Championsの正本データ、実機挙動、実M-Bのcoverageまたは対戦AIの強さを示さない。現行M-Bからproduction readiness sealは発行せず、ランク1位相当は **UNMEASURED / CLAIM FORBIDDEN** とする。

敵対的統合監査では、artifact root内のsource authority、license verification、Regulation statusを整合的に自己申告するだけでproduction候補を偽装できる経路を検出した。修正後のSIM-02B V2はproduction verifierを意図的に持たず、production Compilationを常にfail-closedで拒否する。後続SIM-02C V3には外部trust/enrollment verifierを別型で実装したが、V2の拒否は緩和していない。したがってlocal engineeringの`GO`はtest-authoritative positive pathの完成を意味し、actual production issuance capabilityの完成は意味しない。

本レポートと`data/golden/sim02b-m-b-no-go-v2.json`はfrozen V2 completion snapshotである。goldenの`production_trust_anchor_status: not_implemented`はV2発行経路だけを指す。現在の3層状態、すなわちV2 fail-closed、V3 engineering verifier local verified、actual M-B enrollment未設定/NO-GOは`docs/validation-report-sim02c.md`を参照する。

| Gate | 判定 | 証明したこと | 証明していないこと |
|---|---|---|---|
| SIM-02B local engineering gate | `GO / ENGINEERING COMPLETE` | v2 promotion/readinessのpositive経路、再計算、hash binding、改変拒否 | Champions準拠、実M-Bのdata completeness、private-match投入可能性 |
| test-authoritative readiness | `GO / engineering_sealed` | 小さい検証用fixtureを正規経路でsealできる | `champions_candidate`、公式データの真正性、実戦汎化 |
| actual M-B data gate | `NO-GO` | 不足証拠をexact assessmentとして固定できる | production candidateまたはproduction readiness |
| rank-1 equivalence | `UNMEASURED / CLAIM FORBIDDEN` | 未測定状態を出力契約で維持する | ランク1位相当の勝率、Elo、順位到達確率 |

## Local engineering gate

### Test-authoritative positive end-to-end

検証用source setはcore、development、external holdoutの3 manifestを持ち、resolverが各source/license/use-policy recordとartifactのbyte size・SHA-256を実体から照合する。fixtureのexact TargetCapabilitySetは次の3 capabilityである。

- `move.damage`
- `ability.rough_skin`
- `item.leftovers`

各capabilityに1件ずつ、合計3件のdevelopment scenarioを割り当てる。external holdoutはdevelopmentとsource・collection・authoring lineageを分離した1件を持つ。caller suppliedの成功フラグは使わず、Catalog/RuleSetへ結合したReplayをengineで再実行し、capability witness、grounding requirement、期待eventを照合する。

この入力から次を一工程で生成・再検証できる。

- resolver-backed source resolution set
- validated mapping、Catalog、RuleSet、TargetCapabilitySet
- development scenario corpusとexternal holdout corpus
- engine-backed primary probeとsupplemental probe
- grounding resolution、mechanic coverage matrix、promotion report
- portable `ProductionPromotionCompilationV2`
- `ResolvedChampionsReadinessV2`とreadiness seal

同一入力を再コンパイルしたreport、document set、source setはbyte-identicalである。保持済みCompilationもsource artifactを再解決して再検証する。test-authoritative reportは`engineering_candidate`、readinessは`engineering_sealed`となるが、`champions_candidate: false`、`champions_fidelity_status: not_attested`、`rank1_equivalence_status: unmeasured`を固定する。

1回のcompileでは各source manifestを1回だけ解決する。mapping/construction referenceは最初のresolved artifact snapshotへ後付け検証し、前半component bytesと後半source identityが別snapshotになる二重解決を行わない。artifact本体を再読する場合は毎回byte sizeとSHA-256を照合する。

### Fail-closed mutation

- seal後にCatalog artifactへ1 byteでも差分があれば、再compileと保持済みCompilation再検証の双方でbyte count/hash不一致として拒否する。
- scenario artifactを変更してmanifestを再署名しても、runtime objectのexact canonical bytesと異なれば拒否する。
- test fixtureのsource recordだけをproduction claimへ変更しても、現行verified Regulationではないためproduction scopeへ昇格しない。
- source/license/Regulation/timingのlocal JSONをすべて整合的にproduction claimへ再署名しても、SIM-02B V2は外部trust verifierを持たない意図的fail-closed経路なのでproduction Compilationを明示的に拒否する。
- Compilationまたはreadinessに結合したsource、mapping、Catalog/RuleSet、capability set、scenario、partition、grounding、probe、holdout、report hashの差分を再計算で拒否する。

主要なpositive E2Eは`tests/test_promotion_compiler_e2e_v2.py`、可搬Compilation/readiness round-tripは`tests/test_champions_readiness_v2.py`、fixture substanceは`tests/_sim02b_fixture.py`にある。

## Actual M-B data gate

現行M-B assessmentは次を返す。

| 指標 | 現在値 | Gate上の意味 |
|---|---:|---|
| TargetPool members | 235 | 分母を人気度、記事数、使用率で縮小しない |
| verified mapping | 0 / 235 | production mappingは1件も昇格していない |
| unresolved mapping | 219 | authoritative mapping evidence待ち |
| conflict mapping | 16 | 候補IDを推測で選択しない |
| target capability rows | 118 | 現診断Catalogから得た暫定対象行 |
| execution gaps | 118 | capability別positive executor/probeが未実証 |
| diagnostic blockers | 718 | v1 diagnostic compilerが列挙する不足理由 |
| promotion assessment blockers | 720 | frozen V2 production assessmentが列挙する昇格blocker。1件はV2 production trust anchor不足 |

`development_scenario_coverage_rate`、`verified_grounding_conformance_rate`、`engine_probe_pass_rate`、external holdout評価は、実M-Bの正本入力が揃うまで測定済み1.0として扱わない。`silent_fallback_count: 0`もpositive execution証拠へ読み替えない。actual M-Bではresolver-backed production source/license、capability-complete development corpus、lineage分離済みsealed holdout、actual grounding、全必須capabilityのpositive engine probeが未達である。

718と720は別gate層の件数であり、相互に上書きしない。前者は診断compilerの理由数、後者はfrozen V2 production promotion assessmentのblocker数として、対応するsource report hashとassessment hashへ固定する。追加された1件は、local artifactが`official`/`verified`を自己申告してもV2から昇格させないartifact-root外trust anchorである。後続V3 verifierの存在はこのhistorical countを変更せず、actual enrollment未設定のため現在のNO-GOも解除しない。判定は`promotion_candidate: false`、`champions_candidate: false`、`rank1_equivalence_status: unmeasured`である。

- source report hash: `2c443ea3d196efaad9c99b3f5012ffa800f093595fa87d0afdcde332914632c8`
- promotion assessment hash: `2522c71c2e0a65649f7a133bf03f9f223c6a74e8db45bd06ea45c868be438980`

## Git外artifact運用

実M-Bのraw source、取得payload、Catalog生成中間物、scenario corpus、Replay、BlueStacks screenshot/UI hierarchy/video、grounding trace添付、評価run、trajectory、model/checkpointはGitへ追加しない。content-addressedなGit外artifact storeへ保存し、GitにはSchema、小さいsynthetic fixture、再生成コード、portable manifest、SHA-256・byte size・license/use-policy・入力lineage、集約assessmentだけを置く。

test-authoritative fixtureもGit追跡できるのは再現に必要な最小レコードだけであり、実M-B corpusの縮小コピー先にはしない。license未確認の旧PJ由来artifactは`local_research_only`かつ`redistribution: prohibited`を維持し、元データだけでなく再配布不可の派生Catalog/corpusも公開しない。サイズ上限と追跡候補は`docs/git-artifact-policy.md`を正本とする。

## 1週間regulation adaptation

既存のv2 contract/compiler/readinessをregulation非依存の固定基盤とし、1週間ではregulation依存のsource、mapping、Catalog/RuleSet、scenario、grounding、holdoutを入れ替える。

1. `t0`: 署名・hash固定済みRegulation/TargetPool、利用可能source集合、license/use-policy、外部artifact locatorを凍結する。
2. `t0 + 48h`: v2 compilerでproduction candidate、または全未解決record・unsupported capability・不足証拠と再開条件を持つexact `NO-GO`を発行する。`NO-GO`は工程SLA達成であって投入成功ではない。
3. `t0 + 3–5d`: source acquisition、235 mapping、Catalog/RuleSet、capability別development scenario/positive Replay、groundingを並列更新し、毎回同じgateを再計算する。
4. `t0 + 6d`: 開発からlineage分離して事前封印したexternal holdoutを開き、novel gap、Replay一致、silent fallbackを検査する。candidateだけをAI-01評価へ渡す。
5. `t0 + 7d`: 全回帰、artifact包装、readiness再検証を終え、private-match投入の`GO / NO-GO`を確定する。未解決の場合はassessmentと再開条件をcontent-addressedに固定する。

LLMはsource探索、mapping候補、scenario草案、blockerの優先順位付けを支援できるが、verified status、正本値、期待event、holdout合否を決定しない。RL/search/LLM方策の競技評価はproduction readiness seal後に行い、証拠不足を方策の強さで補わない。

## 検証

SIM-02B focused verificationでは、source resolver、scenario/partition、assessment/reporting、compiler E2E、readiness v2、Schema、size gateを確認した。最終統合では **454 tests passed in 43.17s**、現M-B assessmentの上記hash・件数再現、全SIM-02B schemaのstrict preflight、repository size gate、`git diff --check`に合格した。

```powershell
python -m pytest -q tests/test_promotion_sources_v2.py tests/test_promotion_scenarios_v2.py tests/test_promotion_assessment_v2.py tests/test_promotion_reporting_v2.py tests/test_promotion_compiler_unit_v2.py tests/test_promotion_compiler_e2e_v2.py tests/test_champions_readiness_v2.py
python scripts/check_repo_size.py
python -m pytest -q
```

## 次の大きな目的

このV2 snapshotから設定した次の大目的は **SIM-02C Production Trust Anchor + Authoritative M-B Evidence + Executable Scenario Corpus** である。trust/partition工学verifierの後続結果は`docs/validation-report-sim02c.md`へ記録する。

SIM-02Bのpromotion/readinessコードを拡張して不足を隠すのではなく、現行M-Bの0/235 verified mappingと720 promotion blockerをartifact-root外trust anchor、authoritative source record、actual private-match traceで解消する。全235 memberのexact mapping、構造化された技priority/effect・特性・道具・base stats・Mega relation、capabilityごとのdevelopment scenario/positive Replay、source・collection・authoring lineageを分離したsealed holdout、実機groundingを同一manifest lineageへ収める。

完了条件は、production sourceを再解決したv2 assessmentがproduction readiness sealを発行するか、残存blockerと再開条件を漏れなく再生成し、48時間candidate/NO-GOと7日投入判断を実測で満たすことである。その後にのみ、AI-01上でsearch/RL/LLMを比較し、ランク1位相当を別の競争的benchmarkで測定する。
