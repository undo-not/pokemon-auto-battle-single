# SIM-02 Validation Report

## 判定

SIM-02のローカル準備基盤は実装済みであり、規制snapshot、公式eligible target pool、coverage gap、regulation diff、synthetic rehearsal、read-only grounding、AI観測、generic mega contractを機械検査できる。

ただし、現行M-Bを実行可能なcandidateとして昇格する条件は満たしていない。

| Scope | Result | Meaning |
|---|---|---|
| SIM-02 local infrastructure | `GO / VERIFIED LOCALLY` | Schema、models、pipeline、fail-closed contractをローカルfixtureで検証できる |
| M-B member readiness | `NO-GO` | explicit mappingは235フォーム中0。旧intakeから213 crosswalk＋22 name candidateを生成したが、正式昇格前 |
| Capability-level execution coverage | `NO-GO` | Pipelineはsynthetic検証済み。実M-B intake、production registry/probe、actual grounding/holdout未接続 |
| Synthetic 48h rehearsal | `OPERATIONAL SUCCESS` | 理由付き`NO-GO`をSLA内に出す配線を検証した |
| Deployable 48h rehearsal | `NO-GO` | Synthetic fixtureは実測wall-clock、sealed historical、live regulationの証拠ではない |
| BlueStacks read-only grounding | `NO-GO` | 診断/capture/store契約は実装済みだがactual capture/traceは0件 |
| M-B mega evolution | `NO-GO` | Generic単側contractのみ。M-B 16形態・同時発動順・実機groundingが未完了 |
| Champions external final gate | `NO-GO` | 外部holdout、actual conformance、fully verified dataが未完了 |

## 実装済みローカル基盤

### Regulation and target pool

- M-A archived、M-B current、synthetic deltaを別status/verification statusで扱う。
- M-Bの期間、形式、item clause、timer、`mega_evolution` requirementをsource manifestとcontent hashへ結び付ける。
- 公式eligible listを235 unique `national_dex_no + form_code + variant_code` keyとして固定する。
- 使用率、top-N、記事数、勝率でtarget denominatorを縮小しない。
- `pokemon_id`未mappingを除外せず、235件を個別`unmapped_target` blockerとして残す。外部Catalog IDを全国図鑑番号から暗黙推定しない。

### Source-bound Catalog intake

- 旧PJのraw/processedをコピーせず、公式M-B 235 target keyとローカルのsource artifactを読み取るstdlib-only intakeを実装した。
- 旧M-A usage listingから213件のcrosswalk候補（名前一致181、明示form map 32）を保持し、残り22件はexact-name candidateとして正式mappingと分離した。
- 旧usage detailの16 ID conflictは診断専用とし、listing側のcandidateを上書きさせない。
- 9 artifactすべてにbyte size、SHA-256、record count、`unverified / local_only / redistribution prohibited`を固定し、tracked source lockの完全一致なしでは再生成を拒否できる。
- 生成bundleは`data/processed/sim02/`へ置きGit管理外とする。実データ結果は235 target、213 detail available、22 detail missing、88 blocker、promotion ready falseである。

### Coverage and regulation diff

- Regulation、TargetPool、Catalog、RuleSetのidentity/hash不一致を拒否する。
- member mapping、Catalog coverage、required/unsupported mechanics、source/restricted sourceを`CoverageGapReport`へ保存する。
- period、format、team size、level、item clause、timer、mechanics、target keys、blocker差分を決定論的な`RegulationDiffBundle`へ保存する。
- 現coverage reportはmember-level readinessであり、capability-level execution coverageまたは実環境採用率ではない。

### TargetCapability and promotion matrix

- `TargetPoolManifest`は公式eligible key全件、explicit mapping evidence、Catalog/RuleSet/corpus identity、人気度filterなしを検査する。公式235件から1件欠けても拒否する。
- 合法move・ability・item・mandatory mechanicとsemantic tokenからfixed-point closureを作り、同一signatureをdedupeしながらspecies/entity origin referenceを保持する。
- 未mapping・unknown effectがあれば`denominator_final: false`とし、coverage count/rateを`null`にする。
- legality、transition、RNG、event、observation、Replayの6次元を要求し、乱数非使用も`rng:none`として省略しない。
- `silent_fallback_count`は実行probeから、grounding分子はresolver-backed assertionから、holdout差分はdevelopmentと分離したrecord hashから再計算する。caller supplied rate/countを受け取らない。
- Small synthetic Catalogではexecution/grounding 1,000,000 ppm、silent fallback 0、clean holdoutでcandidate-readyになるpositive pathと、各fail-closed mutationを検証した。実M-B candidate bundleは未生成である。

### Regulation rehearsal

- sealed input hash、coverage hash、diff hash、resource fields、silent fallback、candidate/NO-GO理由を`RegulationRehearsalReport`へ保存する。
- Synthetic internal rehearsalは`operational_rehearsal_success: true`、`deployable_candidate_success: false`である。
- Fixtureの`t0`、`t_decision`、compute/manual/external-wait値はsynthetic inputであり、実測時間として扱わない。
- 証拠不足時に48時間内で正しい`NO-GO`を出すことは安全運用上の成功だが、candidate昇格ではない。

### Generic mega evolution contract

- Synthetic Catalog/RuleSet上で、単側のメガシンカをmove actionへ明示的に結合する。
- 対象個体・required itemを検証し、version固定した標準能力値式でCatalogのbase/mega基礎値、level、IV、EV、性格から変身前後statsを再計算する。
- 1戦1回resource、pre-move event、変身後の種族・stats・type・ability、交代後の永続、観測、Replay v2 roundtripを扱う。
- Wrong item、missing stats、unknown relation、unmarked target formをfail-closedする。
- 双方が同一decision windowでメガシンカを選ぶ解決順は、grounding不足のためfail-closedする。
- 現M-B RuleSetは`mega_evolution`をunsupportedのまま維持する。Generic fixture成功をM-B対応へ読み替えない。
- 標準能力値式がChampions固有実装と一致するかは未groundingであり、実機証拠なしにM-Bへ昇格しない。

### Read-only BlueStacks grounding

- 診断はregistry、config、process状態だけを読み、ADBを呼び出さない。
- Capture planは既知instanceとallowlisted screenshot/UI hierarchy commandだけを生成する。ADB clientがdaemonを起動し得るraceをローカル診断だけでは排除できないため、外部ownership supervisorが実証されるまでは実行をfail-closedする。
- Raw screenshot/XMLはGit外のcontent-addressed `CaptureStore`へ保存し、SHA-256、byte size、read-only、local-research-only、distribution禁止をmanifestへ記録する。
- `GroundingTrace`はobserved/inferred/unknown/conflict、capture identity、manifest hash、annotation source、conformance verdict、blockerを保持する。
- `CaptureStore.resolve()`はmanifestのexact shape、content-derived capture ID、artifact存在・size・hashを再検証する。Trace/Envの昇格はresolver-backed validationを通過したwrapperだけに許可する。
- 現地診断ではBlueStacks `5.22.51.1038`と4 instanceを検出した。player processとADB processが停止中だったためcapture preflightは拒否し、ADBは呼び出していない。
- Actual capture、機密性review、annotation、GroundingTrace、simulator conformanceは未実施である。

### AI environment contract

- Instant fields、public event history、legal action mask、capture/trace provenance、blockerを分離する。
- `unknown` legal maskと「全actionがillegal」を別状態として扱う。
- Blockerを持つobservationはactionable maskを公開できない。
- Simulator observationがcapture provenanceを偽装すること、grounded observationがevidence IDを欠くことを拒否する。
- Field path、public event kind/detail key、qualified artifact referenceをallowlistし、実store・trace・manifest hashへ解決できないdraftはactionableにしない。
- 相手の`hp`、`max_hp`、`hp_fraction_millionths`はsimulatorのprivate stateから公開せず、grounded captureでは観測可能なHP-bar範囲だけを扱う。
- これはAIのI/O契約であり、探索・RL・LLM方策の強さを証明しない。
- Policy-free adapterは、sealed fixtureとCatalog/RuleSet/engine identity、seed/RNG lineageを固定し、`reset`/`step`、partial observation、public history、legal mask、Replay-compatible transition metadataを返す。報酬は未定義の`None`で、方策実装を混入しない。
- Champions candidate scopeはcapability/grounding evidenceがverifiedでない限り`all_illegal` maskとblockerを返し、pure simulator local scopeと区別する。

## 現在の外部blocker

1. `AUD-SIM02-001`: M-B snapshotは`partially_verified`であり、実機rule screenを含むfully verified evidenceではない。
2. `AUD-SIM02-002`: 235フォームすべての正式なsource-bound Catalog mappingが未昇格で、production TargetCapability bundle、外部grounding、holdoutがない。
3. `AUD-SIM02-005`: M-B 16メガ形態、同時メガシンカ順、実機event順が未groundingである。
4. `AUD-SIM02-006`: BlueStacks actual capture/GroundingTraceが0件である。
5. `AUD-P0-001`: Champions固有の急所、端数、複合効果順等の実機conformanceが未完了である。
6. `AUD-P0-002`: 旧PJ由来Catalogのsource別licenseが未確認であり、再配布できない。

## Validation commands

最終統合時に次を同一worktreeで実行する。

```powershell
python -m pytest -q
python scripts/validate_sim01_bundle.py --usage-scope local_research
python scripts/validate_sim01_frozen.py
python scripts/build_regulation_diff.py
python scripts/diagnose_bluestacks.py
python scripts/check_repo_size.py
```

`diagnose_bluestacks.py`はread-onlyであり、ADBを起動または呼び出さない。Actual captureはこの診断コマンドに含まれない。

## Final verification

- generated at: `2026-07-13T11:31:14+09:00`
- git revision / tree identity: local baseline commit on `codex/sim02-regulation-ready`（公開・pushなし。exact revisionはcurrent `HEAD`で解決）
- pytest result: `140 passed in 9.49s`
- SIM-01 bundle validator: `ok=true`、local research only、redistribution false
- frozen baseline validator: `ok=true`、turn 15、P2 win、19 decision windows
- 10,000 battle smoke (`seed-start 0`): P1 3,240、P2 6,760、draw 0、195,319 decision windows、2,462,659 events、10,000 unique final hashes
- regulation rehearsal: 235 eligible、explicit mapped 0、235 unmapped、`mega_evolution` gap、synthetic `NO-GO` in 21,600 seconds、operational true、deployable false、silent fallback 0、239 reason codes、9 sealed inputs
- Catalog intake: 235 target、213 usage crosswalk、22 exact-name candidate、16 diagnostic ID conflicts、22 detail missing、88 blockers、bundle hash `2943ab4b3f716427bff5d5ed379a102f95cc19f0200c8dbbe2ea326950f4b14f`、262,726 bytes、Gitignored
- BlueStacks diagnostics: `adb_invoked=false`、version `5.22.51.1038`、4 instances、player/HD-Adb停止、ownership未検証、side-effect risk blockerあり
- repository size guard: 144 candidate files、single-file/fixture limit違反0
- SIM-01 Catalog SHA-256: `764a75146a017aca77453110fc8e19903ddc11e64e1df03c92791aa367703141`
- SIM-01 RuleSet SHA-256: `f87b077b1ba598865a9e21ef84decbf273ca73806a9412fd5d2520589ff34215`
- SIM-01 Replay SHA-256: `26af0e4d16f742892ca90c97bc7621380b97fe624c6ec784943ce25f8ad07546`
- SIM-01 final state SHA-256: `4f59a78f7bb5b8e771d6dd4a4dffd8ed69c5dfead55b7f96ac6c924fea6b4267`
- M-B eligible fixture SHA-256: `205e1772031ba78e6f790ef4bad0782ed85364618f2c007aa3a9996b171ce92d`
- synthetic rehearsal input SHA-256: `4d4593cd40b9f440695d5e9baeef8a465b64fe6a48e047af8553576c25ac1a8a`
- rehearsal golden NO-GO SHA-256: `5ff663f6e50868f1281259fe2ce08d8331cbc54bf60709a4ae8d87a215a2e90e`

数値を追記しても、本reportのscope判定は変わらない。ローカルtest成功をM-B deployable successまたはChampions外部最終gateの通過へ読み替えない。

## 次の大きな目的

`SIM-02 / Regulation-ready Champions Environment`を一つの成果として完成させる。Catalog candidateをsource-bound mappingへ昇格し、235件から合法到達する全capabilityの固定分母、execution/grounding matrix、silent fallback probe、BlueStacks actual trace、policy-free AI Env、Replay/smoke、sealed-historical 48時間rehearsalを同じversion identityへ束ねる。途中成果の件数だけでは完了とせず、validated candidateまたは不足根拠を列挙した`NO-GO` bundleを最終出力とする。
