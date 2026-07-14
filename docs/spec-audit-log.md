# Specification Audit Log

## P0 / SIM-01監査 — 2026-07-13

### AUD-P0-001

- `severity`: critical
- `phase`: SIM-01-CHAMPIONS-VERIFIED
- `category`: missing_input
- `problem`: 現行Pokémon ChampionsのRuleSet値と全対応効果に、一次情報または実機観測を結び付けたverified snapshotがない。
- `expected`: 合法性、行動順、乱数、端数、急所、効果順についてsource manifest IDと実機golden fixtureを持ち、`verified_transition_conformance_rate == 1.0`である。
- `impact`: ローカル参照仕様を公式Champions仕様として誤認する。
- `mitigation`: published Champions damage referenceの通常ダメージ1例を`tests/test_golden_grounding.py`で再現し、source manifest IDをRuleSetとReplayへ伝播している。この例は急所、残余ダメージ、効果順を検証しないため、これらは`PD-003/004/007`のままである。未知効果はfail-closedである。
- `local_completion_effect`: SIM-01ローカル参照bundleの工学完了はブロックしない。公式準拠の主張と実機adapter昇格をブロックする。
- `suggested_action`: 境界HP、急所、同速、効果順、交代、特性・道具について実機golden fixtureと一次情報manifestを追加する。
- `evidence`: `specs/sim-01-phase-contract.md`、`docs/provisional-decisions.md`、`tests/test_golden_grounding.py`
- `status`: open
- `resolution`:

### AUD-P0-002

- `severity`: critical
- `phase`: DISTRIBUTION / SIM-01-CHAMPIONS-VERIFIED
- `category`: data_governance
- `problem`: 旧`champions` PJ由来Catalogと6参照元のlicenseがsource単位で確認されていない。
- `expected`: 再配布または公式準拠bundleへ使う全sourceが`license_status: verified`で、許可範囲を明記している。
- `impact`: 再配布権が不明なデータまたは派生物を公開する可能性がある。
- `mitigation`: manifestへ6参照元のlogical path、size、SHA-256を記録し、`local_research_only: true`、`redistribution: prohibited`とした。bundle validatorはローカル研究を許可し、distribution modeを拒否する。
- `local_completion_effect`: 制約をvalidatorで強制する限りローカル参照bundleをブロックしない。データ・Catalog・派生物の再配布をブロックする。
- `suggested_action`: 元データの取得元ごとに利用条件を確認し、確認できないsourceは置換または除去する。
- `evidence`: `data/manifests/legacy-champions-59bf57c-sim01.json`、`scripts/validate_sim01_bundle.py`
- `status`: open
- `resolution`:

### AUD-P0-003

- `severity`: high
- `phase`: SIM-01
- `category`: contract_gap
- `problem`: 初回監査時は`BattleState`、`LegalActionSet`、`BattleEvent`、観測、Replayの実装・機械検査契約が不足していた。
- `expected`: 完全状態と観測の分離、合法手ID、イベント順、状態hash、RNG境界を機械検査できる。
- `impact`: Replayに隠れた実装依存や非公開情報漏洩が入る。
- `suggested_action`: 完了。今後field変更時はReplay Schemaとtraceabilityを同時更新する。
- `evidence`: `src/champions_sim/core/model.py`、`data/schemas/replay.schema.json`、core/replay/observation/decision tests
- `status`: resolved
- `resolution`: Replay v2は完全初期状態、初期化イベント、decision window、RNG、state hashを保持し、roundtrip、別process CLI保存/読込、`verify_replay`を通過する。Replayはbundle-boundであり、再実行時にCatalog/RuleSet hash一致を要求する。P1 hardeningで全階層のunknown keyとduplicate keyをstrict decoderで拒否し、観測漏洩と合法手契約も検証した。

### AUD-P0-004

- `severity`: medium
- `phase`: P0
- `category`: missing_tests
- `problem`: 初回監査時はSchema、manifest hash/license、Git容量上限を自動検査するguardがなかった。
- `expected`: stdlib＋pytestで継続検査できる。
- `suggested_action`: 完了。CI導入時に同じコマンドを必須化する。
- `evidence`: `scripts/validate_sim01_bundle.py`、`scripts/check_repo_size.py`、`tests/test_governance_validation.py`
- `status`: resolved
- `resolution`: Recursive Schema/semantic loader/Replay/license検査とtracked＋untracked非ignore候補の容量検査を追加した。

### AUD-P0-005

- `severity`: low
- `phase`: P0 / SIM-01
- `category`: provisional_hidden
- `problem`: Git容量、fixture容量、急所、端数、smoke件数は初期値であり、検証済み正本ではない。
- `expected`: すべての仮置きにID、リスク、review trigger、利用証拠がある。
- `suggested_action`: 実機証拠と運用コストを得るたびに台帳を再監査する。
- `evidence`: `docs/provisional-decisions.md`
- `status`: resolved
- `resolution`: SIM-01判断を`PD-001`〜`PD-007`、SIM-02 rehearsal SLAを`PD-008`へ登録し、RuleSet、Replay、validator、smoke/rehearsal evidenceへscope別に伝播した。

### AUD-P0-006

- `severity`: critical
- `phase`: SIM-01
- `category`: contract_gap
- `problem`: 初回のRuleSet/Catalog fixtureはP0 Schemaと同じversionを名乗りながら構造が一致しなかった。
- `expected`: fixture、Schema、loader、Replay bundleが同じ契約を使う。
- `suggested_action`: 完了。契約変更時はrecursive bundle validationを先に更新する。
- `evidence`: RuleSet/Catalog/Battle/Replay Schema、`scripts/validate_sim01_bundle.py`、`tests/test_governance_validation.py`
- `status`: resolved
- `resolution`: Schemaを現loader契約へ同期し、fixtureと生成Replay v2を再帰Schema検査とsemantic loaderへ通した。

### AUD-SIM01-007

- `severity`: medium
- `phase`: SIM-01-LOCAL
- `category`: validation_gap
- `problem`: 初回監査時は`PD-005`の10,000件seeded smokeが未実行だった。
- `expected`: 例外、非決定、状態不変条件違反0で10,000件を完走する。
- `suggested_action`: 完了。対応効果集合または状態生成器変更時に再実行する。
- `evidence`: 2026-07-13 final smoke result。Catalog `764a75...03141`、RuleSet `f87b07...34215`
- `status`: resolved
- `resolution`: 10,000 battles、195,319 decision windows、2,462,659 events、unique final hashes 10,000、例外0、188.4秒で完走した。

## Gate判定

- P0統治: **COMPLETE**
- SIM-01ローカル参照bundle: **GO / ENGINEERING COMPLETE**
- 公式Champions準拠としての昇格: **NO-GO** — `AUD-P0-001`
- Catalog・データ・派生物の再配布: **NO-GO** — `AUD-P0-002`
- AI、LLM、BlueStacks adapter: SIM-01の次フェーズであり、この完了判定には含めない

## SIM-02事前監査 — 2026-07-13

### AUD-SIM02-001

- `severity`: critical
- `phase`: SIM-02-CHAMPIONS-VERIFIED
- `category`: missing_input
- `problem`: 公式source route、期間、item clause、timer、required mechanicを持つM-B `RegulationSnapshot`は実装済みだが、`verification_status`は`partially_verified`であり、外部最終ゲート用のfully verified snapshotではない。
- `expected`: source manifest、取得時刻、content hash、適用期間、legal entity/rule diffを持つsnapshotがあり、TargetPoolManifestの上流正本として凍結されている。
- `impact`: 旧レギュレーションや推測した合法poolを対象にcoverage 1.0を主張する。
- `mitigation`: 公式ページとeligible listをsource manifestへ結び、235 target key、period、format、timer、mega requirementをhash固定した。Synthetic/archived regulationとcurrentをverification statusで分離する。
- `suggested_action`: published timestampを含む一次artifact保存、eligible list parserの独立照合、actual game rule screenとの照合を行い、fully verifiedへ昇格する。LLM抽出は正本にしない。
- `evidence`: M-B Regulation/TargetPool fixture、`pokemon-home-regulation-m-b-current` manifest、regulation loader tests、`AUD-P0-001`
- `status`: open
- `resolution`:

### AUD-SIM02-002

- `severity`: critical
- `phase`: SIM-02-CHAMPIONS-VERIFIED
- `category`: missing_input
- `problem`: 公式eligible list全235フォームをTargetPoolSnapshotへ固定したが、source record evidenceへ結合したexplicit mappingは0件で、235件すべてがunmappedである。以前の6件は`n<全国図鑑番号>`と表示名suffixによる暗黙推定だったためmapping実績から除外した。全TargetCapabilityの実機grounding assertionと、開発から分離した外部holdoutも未取得である。
- `expected`: source IDs、取得時点、期間、artifact hash、全件包含、dedupe、除外reasonを持つTargetPoolManifestと、全TargetCapabilityへtraceできるverified grounding/holdoutがある。
- `impact`: 恣意的に狭い対象集合、記事の印象、使用率thresholdをcoverage分母として採用し、未知interactionを見落とす。
- `mitigation`: popularity thresholdを使わず235件を分母に残し、source-to-capability compilerで0 resolved/verified、219 unresolved/unverified、16 conflict/unverifiedをsource record hash付きで機械出力する。外部Catalog IDを全国図鑑番号から推定せず、source-bound mapping evidenceが検証されるまで候補昇格をfail-closedする。実M-B intakeからもfixed-point closure、6実行次元、probe-derived fallback、resolver-backed grounding、holdout matrixまで接続済みで、denominator non-final時はcoverage count/rateを`null`にする。
- `suggested_action`: 235件の候補をauthoritative evidenceで正式mappingへ昇格し、技priority/structured effect、特性・道具handler、base stats、Mega relation、capability別positive executorを追加する。mapping不能項目を分母から除外しない。
- `evidence`: TargetPool/Coverage/Mapping/Capability/MechanicCoverage/Holdout/Compiler Report Schema、`build_coverage_gap_report`、`src/champions_sim/intake`、`src/champions_sim/compiler`、`src/champions_sim/capabilities`、regulation/intake/compiler/capability pipeline tests、`specs/sim-02-phase-contract.md`
- `status`: open
- `resolution`:

### AUD-SIM02-003

- `severity`: high
- `phase`: SIM-02-LOCAL-PREPARATION
- `category`: contract_gap
- `problem`: 事前監査時はRegulation、TargetPool、Coverage、Diff、Grounding、RehearsalのSchema、実装、検査がなかった。
- `expected`: 同じ入力からbyte-identicalなmanifestとcoverage分母を再生成し、分母縮小、silent fallback、grounding欠落、48時間計測を機械検査できる。
- `impact`: Phase Contractがあっても実装・テスト・生成reportが異なる定義を使う。
- `suggested_action`: 完了。今後field変更時はSchema、models、validator、tests、validation reportを同時更新する。Capability-level closureはAUD-SIM02-002の未達として分離する。
- `evidence`: regulation/target-pool/coverage/diff/rehearsal/capture/grounding/AI Env Schema、`src/champions_sim/regulations`、`src/champions_sim/grounding`、関連tests
- `status`: resolved
- `resolution`: source/hash-bound snapshot、235 target denominator、coverage blocker、deterministic diff、synthetic NO-GO rehearsal、read-only capture provenance、GroundingTrace、AI Envを機械検査できるローカル基盤を実装した。P1 hardeningでrehearsal再計算/forgery拒否、strict capture identity、manifest-bound frame、Env allowlist/evidence bindingを追加した。

### AUD-SIM02-004

- `severity`: medium
- `phase`: SIM-02
- `category`: objective_drift
- `problem`: 48時間目標が、証拠不足時の推定実装やtarget pool縮小を誘発し得る。
- `expected`: 時間内の正しい`NO-GO`を安全なrehearsal成果として区別し、deployable candidate成功と混同しない。
- `impact`: SLAは満たすが遷移正確性を失う。
- `suggested_action`: `PD-008`とRehearsalReportにcandidate/NO-GO種別、外部待ち、計算資源、手作業、coverage/grounding/silent fallbackを必須化する。
- `evidence`: `docs/provisional-decisions.md`の`PD-008`
- `status`: resolved
- `resolution`: Phase ContractとPD-008で、証拠不足時の`NO-GO`、人気度threshold禁止、deployable成功との分離を明文化した。Rehearsal v1は`synthetic_internal`の`NO-GO`だけを表現し、coverage/diffをsealed入力から再計算する。Candidate/live/sealed historicalは別version未定義として拒否する。

### AUD-SIM02-005

- `severity`: critical
- `phase`: SIM-02-M-B
- `category`: contract_gap
- `problem`: Generic fixtureでは単側メガシンカのstate/action/event、1戦1回resource、永続、観測、Replayを実装したが、現M-B RuleSetは`mega_evolution`をunsupportedとし、16形態は現Catalogへ未mapping/未groundingである。同時メガシンカの解決順もgrounding不足でfail-closedする。
- `expected`: メガシンカをmandatory TargetCapabilityとして分母へ含め、resource消費、合法性、action、形態/能力値/タイプ/特性変化、発動順、event、観測、Replay、16形態のCatalog参照、grounding assertionを契約・実装・検証する。
- `impact`: M-Bを定義するmechanicを人気度や未実装を理由に除外し、target-pool coverage 1.0を誤って報告する。
- `mitigation`: M-B required mechanicをcoverage blockerとして残し、generic mega contractでwrong item、missing stats、unmarked target form、二側同時発動をfail-closedする。Base/mega実数値はversioned standard stat formulaでCatalog双方と照合するが、Champions一致はverified扱いしない。
- `suggested_action`: 16形態のsource-bound Catalog mapping、各形態stats/type/ability、実機event順、双方同時選択順をgroundingし、M-B専用RuleSetで有効化する。対応完了までM-B candidateを昇格しない。
- `evidence`: 公式[Regulation Set M-B page 776](https://champions-news.pokemon-home.com/en/page/776.html)、公式[Season M-4 page 795](https://champions-news.pokemon-home.com/en/page/795.html)、mega contract implementation/tests、M-B coverage report
- `status`: open
- `resolution`:

### AUD-SIM02-006

- `severity`: critical
- `phase`: SIM-02-CHAMPIONS-VERIFIED / BLUESTACKS-GROUNDING
- `category`: missing_input
- `problem`: BlueStacks read-only診断、strict capture store、GroundingTrace、AI Env契約は実装済みだが、actual emulator captureとGroundingTraceは0件である。ADB clientがdaemonを起動し得るため、process検出だけではside effectを排除できない。現診断ではBlueStacks 5.22.51.1038と4 instanceを検出したが、player/HD-Adbが停止し、ADB server ownershipも未検証である。
- `expected`: 外部supervisorがBlueStacks HD-Adb daemonのownership/lifecycleを保証した対象instance上でread-only captureを取得し、strict verify済みCaptureManifest、GroundingTrace、simulator conformance、外部holdoutを持つ。
- `impact`: simulator observation、UI表示、event順、HP量子化、legal maskを実画面へ照合できず、BlueStacks adapterまたはChampions準拠を主張できない。
- `mitigation`: 診断はADBを呼ばず、常に`adb_external_side_effect_risk_not_mitigated`をblockerへ含める。Capture payload/manifestは外部ownership verificationを必須とし、raw captureはGit外、local research only、distribution禁止で保存する。
- `suggested_action`: 外部ownership supervisorのI/O・lifecycle・failure contractを先に定義する。その後にユーザーが準備したフレンド戦をread-only captureし、内容review・redaction・annotationを経てGroundingTraceへ昇格する。入力操作は別Phaseとする。
- `evidence`: `scripts/diagnose_bluestacks.py`、`src/champions_sim/grounding`、read-only/capture/AI Env tests、2026-07-13 local diagnostics
- `status`: open
- `resolution`:

### AUD-SIM02-007

- `severity`: medium
- `phase`: SIM-02-LOCAL-PREPARATION
- `category`: contract_gap
- `problem`: P1 hardening前はcapture ID、manifest、GroundingFrame、Env field/event evidenceの結合が弱く、同一IDへの異なる内容またはallowlist外情報を下流へ渡せる余地があった。
- `expected`: CaptureStoreがcontent identityと全artifact/manifestをstrict verifyし、GroundingFrameがmanifest hashへ結合され、Envがfield pathとevidence artifactをcapture/trace provenanceへ照合する。
- `suggested_action`: 完了。新しいfield/artifact種別を追加する時はallowlist、Schema、strict decoder、tamper testを同時更新する。
- `evidence`: CaptureStore/Grounding models/AI Env implementation、capture/grounding contract tests
- `status`: resolved
- `resolution`: content-derived capture ID、strict manifest verification、capture manifest hash binding、field/event evidence allowlistを実装した。Opponentのexact HPとfractionも観測から除外した。

### AUD-SIM02-008

- `severity`: critical
- `phase`: SIM-02-LOCAL-PREPARATION / SIM-02-M-B
- `category`: data_governance
- `problem`: `CoverageGapReport`の旧実装は、form `00`の対象について`legacy_pokemon_id == n<全国図鑑番号>`と表示名suffixが一致すれば明示証拠なしにCatalog mappingへ昇格していた。旧PJ監査ではYakkun Champions IDは全国図鑑番号namespaceではなく、特に第9世代で16件のdetail ID不一致と3件の別entityへの有効ID衝突を確認した。
- `expected`: canonical target keyと外部Catalog IDの対応は、namespace付きsource record、record hash、mapping method、verification statusへ結合し、名前または番号の推測だけではresolvedにしない。
- `impact`: 別ポケモンの技・特性・道具・メカニクスを合法closureへ混入し、coverageとsilent fallback判定を偽る。
- `suggested_action`: 完了。互換preflightから暗黙mappingを削除し、explicit `pokemon_id`だけを数える。旧PJのusage listing crosswalkとCatalog name matchは新しいintakeで候補として保持し、追加証拠なしに正式TargetPoolManifestへ昇格させない。
- `evidence`: `src/champions_sim/regulations/pipeline.py`、`tests/test_regulation_pipeline.py`、旧PJ commit `59bf57cc3cdcb2eaa93cbab19eb9851a6fb15c1b`のidentity audit
- `status`: resolved
- `resolution`: M-B preflightをexplicit mapped/covered 0、unmapped 235へ修正し、synthetic rehearsal goldenとartifact manifestを再生成した。

### AUD-SIM02-009

- `severity`: high
- `phase`: SIM-02-LOCAL-PREPARATION / SIM-02-M-B
- `category`: contract_gap
- `problem`: Catalog intake、mapping、semantic/execution registry、probe、MechanicCoverageMatrixが別々に存在し、実M-B source lockからcandidateまたは理由付き`NO-GO`までを同じidentityで再現する一コマンド経路がなかった。
- `expected`: source artifact hash、235件のmapping状態、Catalog candidate、semantic selector、6実行次元、probe、grounding、holdout、coverage matrixをcontent-addressed bundleへ固定し、全gateを満たす時だけcandidate、それ以外は決定論的`NO-GO`を返す。未知値の暗黙defaultとcaller supplied summaryを許さない。
- `impact`: synthetic pipelineの成功を実M-B readinessへ読み替える、または工程間で分母・証拠・blockerがdriftする。
- `suggested_action`: 完了。次はcompilerが固定したevidence backlogをauthoritative source/actual traceで昇格する。
- `evidence`: `scripts/build_source_to_capability_bundle.py`、`src/champions_sim/compiler`、production Catalog/compiler report Schema、compiler tests、content-addressed local bundle
- `status`: resolved
- `resolution`: Source lockから13文書を生成する`source-to-capability-bundle-v1`を実装した。現M-Bは0 resolved、219 unresolved、16 conflict、788 semantic selector、118 target capability/execution gap、capability別executor未取得118、silent fallback 0、理由付き`NO-GO`となる。全artifact digestとreport hashをwriter直前に再検証し、生成先をGitignored `data/processed`配下へ制限する。candidate schema分岐は空blocker/zero countと整合するが、現legacy intakeはunverified/local-onlyのためcandidateへ昇格しない。

## SIM-02 Gate判定

- Phase Contract・目的変数・scope分離: **GO / SPECIFIED**
- SIM-02ローカル基盤: **GO / IMPLEMENTED / VERIFIED LOCALLY** — regulation、target、coverage、diff、synthetic rehearsal、grounding/AI Env、generic mega
- SIM-02 source-to-capability compile: **OPERATIONAL SUCCESS / REASONED NO-GO** — `AUD-SIM02-009`は解決、evidence不足は`AUD-SIM02-002`で継続
- SIM-02 target coverage完了: **NO-GO** — `AUD-SIM02-002`
- SIM-02 M-B candidate: **NO-GO** — `AUD-SIM02-005`
- BlueStacks read-only actual grounding: **NO-GO** — `AUD-SIM02-006`
- Synthetic 48h rehearsal v1: **OPERATIONAL SUCCESS / NO-GO ONLY / DEPLOYABLE SUCCESSではない**
- SIM-02 Champions外部最終ゲート: **NO-GO** — `AUD-SIM02-001`、`AUD-SIM02-002`、`AUD-SIM02-005`、`AUD-SIM02-006`、`AUD-P0-001`
- TargetPoolManifest外の環境coverage主張: **禁止**
- 探索・RL・LLM・構築・BlueStacksへの昇格: SIM-02の該当gateを満たすまで別途判定する

## AI-01事前・完了監査 — 2026-07-14

### AUD-AI01-001

- `opened_on`: 2026-07-14
- `severity`: critical
- `phase`: AI-01 / RANK1-READINESS
- `category`: objective_drift
- `problem`: 最終目的はランク1相当だが、既存契約は遷移正確性だけを目的変数とし、勝敗utility、seat bias、方策比較、構築・選出品質を測れなかった。
- `expected`: simulator fidelityとdecision qualityを別gateにし、後者をversion/hash/partition付きの再計算可能な目的変数で測る。
- `impact`: evidence backlogの件数を減らしてもAIが強くなったか判断できず、RL/LLMを固定fixtureへ過適合させる。
- `suggested_action`: AI-01 Phase Contract、paired arena、terminal outcome、frozen benchmarkを実装する。
- `evidence`: `specs/ai-01-phase-contract.md`、`src/champions_sim/arena`、`data/schemas/ai01-arena-report.schema.json`、AI-01 tests
- `status`: resolved
- `resolution`: `paired_net_utility_ppm`とleg/seat/countを全match recordから再計算し、Replay verification、legality、privacy、scope blockerを同じreportへ固定した。外部強度とは分離している。

### AUD-AI01-002

- `opened_on`: 2026-07-14
- `severity`: high
- `phase`: AI-01
- `category`: contract_gap
- `problem`: `BattlePhase.TEAM_PREVIEW`は確定済み3体を即初期化するだけで、6体構築から順序付き3体を選ぶI/O、同時性、観測、commit、Replay前identityがなかった。
- `expected`: 既存3体kernelの外側に6→3選出を置き、双方が相手の選出を知る前にcommitし、完全setと公開previewを分離する。
- `impact`: 実戦で大きな比重を持つ選出を評価できず、後付け実装で隠れ情報漏洩または順序driftが起きる。
- `suggested_action`: versioned `TeamPreviewSession`とselection policy boundaryを実装する。
- `evidence`: `src/champions_sim/prebattle`、`tests/test_prebattle_team_preview.py`、`tests/test_ai01_team_selection.py`
- `status`: resolved
- `resolution`: exact 6-member roster、ordered 3-member selection、128-bit以上nonce付きcommit/reveal、constant-time digest照合、opponent-safe observation、deterministic materializeを実装した。complete session hashをArenaPlanへ固定する。

### AUD-AI01-003

- `opened_on`: 2026-07-14
- `severity`: critical
- `phase`: SIM-02-M-B / AI-01
- `category`: contract_gap
- `problem`: `EnvironmentBundleIdentity`の`EvidenceStatus.VERIFIED`と任意64桁hashをcallerが自己申告すると、compilerの実M-B NO-GOを解決せずChampions candidate環境をactionableにできた。
- `expected`: descriptive identityをattestationとして信頼せず、compiler report、全artifact、stage hash lineage、candidate gateを実体から再計算したresolverだけがactionable sealを発行する。
- `impact`: SIM-01 fixtureをM-B verified環境に偽装し、誤った環境で探索・学習・評価を開始できる。
- `suggested_action`: resolver-backed readiness sealとforgery testsを追加する。
- `evidence`: `src/champions_sim/env/readiness.py`、`tests/test_champions_readiness.py`
- `status`: resolved
- `resolution`: sealなしのself-declared VERIFIEDを`compiler_readiness_not_resolved`でall-illegalにした。resolverは全13 compiler document、report/artifact digest、counts、blockers、candidate-ready、Catalog/RuleSet/Regulation/Target/Capability/Grounding bindingを再検証する。現実NO-GOはsealを発行しない。

### AUD-AI01-004

- `opened_on`: 2026-07-14
- `severity`: critical
- `phase`: RANK1-EQUIVALENCE
- `category`: missing_input
- `problem`: 上位人間、実M-B、複数構築、未知regulationを含む開発外benchmarkと順位較正がない。
- `expected`: 証拠付きChampions環境上で、開発から隔離した外部opponent/scenario poolと事前登録した評価契約を用い、上位層相当を盲検評価する。
- `impact`: SIM-01 synthetic全勝や自己対戦Eloをランク1相当へ誤読する。
- `suggested_action`: SIM-02 evidence promotion後にexternal calibration Phaseを定義する。AI-01の勝率を昇格判定へ使わない。
- `evidence`: `data/golden/ai01-synthetic-benchmark-v1.json`、`AUD-SIM02-001/002/005/006`
- `status`: open
- `resolution`:

### AUD-AI01-005

- `opened_on`: 2026-07-14
- `severity`: high
- `phase`: AI-02 / STRATEGIC-PROMOTION
- `category`: missing_input
- `problem`: 現AI-01 corpusは凍結SIM-01の単一synthetic 6-member rosterで、実構築分布、選出多様性、未観測set belief、regulation変更を含まない。
- `expected`: provenance付きtrain/dev/external-holdout scenario corpusを作り、record hash重複とpartition leakageを0にする。
- `impact`: type-aware baseline、探索、RL、LLMが単一fixtureへ過適合する。
- `suggested_action`: evidence promotionと同じidentityを使うscenario corpus compilerを次段で作る。
- `evidence`: AI-01 Phase Contract、`PD-009`
- `status`: open
- `resolution`:

### AUD-AI01-006

- `opened_on`: 2026-07-14
- `severity`: medium
- `phase`: SIM-02 / AI-01
- `category`: traceability_gap
- `problem`: SIM-02 Phase Contractの`output_models`がsource-to-capability compiler統合後もproduction capability bundleを未実装と記載し、実装と仕様がdriftしていた。
- `expected`: operational compiler、deployable candidate未達、readiness sealを別々に記述する。
- `impact`: 実装済み配線を重複実装するか、NO-GOをcandidate完成と誤読する。
- `suggested_action`: SIM-02 Phase Contract、Requirement、Traceabilityを同期する。
- `evidence`: `specs/sim-02-phase-contract.md`、`src/champions_sim/compiler`、`src/champions_sim/env/readiness.py`
- `status`: resolved
- `resolution`: 後続`AUD-AI01-007`で再監査した結果、v1はproduction promotion compilerではなくintake診断compilerであり、fail-closed resolverは自己申告を拒否するがsealを正規発行できないと訂正した。positive issuanceはSIM-02B v2へ延期する。

### AUD-AI01-007

- `opened_on`: 2026-07-14
- `severity`: critical
- `phase`: SIM-02B / CHAMPIONS-READINESS
- `category`: unreachable_positive_path
- `problem`: `source-to-capability-bundle-v1`は`ProductionCatalogInput`のverified member/record、`denominator_final=true`、`catalog_emit_eligible=true`を型とSchemaで拒否し、compiler内部で空development corpus、空grounding、holdoutなし、probe executorなしを固定する。したがって`resolve_champions_readiness`の正規seal発行は外部証拠不足以前に構造的に到達不能だった。
- `expected`: intake診断v1を凍結し、source/license/artifact recordを実体から解決する別型v2へverified mapping、非空development corpus、系譜分離external holdout、grounding、engine-backed positive probeを入力し、synthetic authoritative fixtureでpositive E2Eを証明する。
- `impact`: fail-closed拒否経路をissuance-capable readiness完成と誤読し、RL/search開始条件を満たしたと誤判定する。
- `mitigation`: AI-01完了範囲をtrusted-local synthetic evaluationへ限定し、readiness positive issuanceを`NO-GO / NOT IMPLEMENTED`へ修正した。
- `suggested_action`: `SIM-02B Production Catalog Promotion + Evidence-backed Scenario Corpus`を次の大目的として実装する。
- `evidence`: `src/champions_sim/compiler/bridge_models.py`、`src/champions_sim/compiler/bundle.py`、`src/champions_sim/env/readiness.py`、`specs/sim-02b-phase-contract.md`
- `status`: open
- `resolution`:

### AUD-AI01-008

- `opened_on`: 2026-07-14
- `severity`: high
- `phase`: AI-01
- `category`: evidence_integrity
- `problem`: 当初のagent/prebattle identityはlive runtime code、Catalog/RuleSet内容、private-state非干渉battle ID、reportに対応する既定Replay永続化を十分に結合していなかった。
- `expected`: exact class/source/live-runtime/config/initial state、Catalog/RuleSet、selection proof、public-only arena namespace、Replay一式を再実行可能な同一evidenceへ束ねる。
- `impact`: binding後method差し替え、private set由来ID、report-only保存によって再現・privacy・検証境界を誤る。
- `suggested_action`: identity/proofを拡張し、通常CLIでReplay evidence manifestをGit外へ保存し、敵対的回帰を追加する。
- `evidence`: `src/champions_sim/core/implementation.py`、`src/champions_sim/arena`、`src/champions_sim/prebattle`、`scripts/run_ai01_benchmark.py`、AI-01 adversarial tests
- `status`: resolved
- `resolution`: BoundAgentとselection policyへsource/MRO-resolved runtime/class constants/config hashと、mapping順・alias topologyを保持する型付き初期instance stateを結合し、selection中のstate変化も拒否する。policy observationはsession所有rosterからdeep-detachし、session hashを実行前後に再検証する。proofへCatalog/RuleSet、arena IDへpublic namespaceだけを結合した。exact Arena/Replay/BattleState/BattleEngine型を要求し、factory実行後にもruntime identityを再検証する。通常CLIはreport・全Replay・file hash付きmanifestを保存するが、prebattle run本体は未保存なのでbattle-Replay archiveと明記し、完全再検証には選出fixtureの再生成が必要である。process globalsとprocess isolationは未解決なので必須blockerを維持する。

### AUD-AI01-009

- `opened_on`: 2026-07-14
- `severity`: high
- `phase`: AI-01
- `category`: validation_gap
- `problem`: stdlib JSON Schema validatorが`contains`と`dependentRequired`を無視し、必須scope blockerまたはprebattle hash片側欠落をSchema上で拒否できなかった。
- `expected`: repositoryが使用するSchema keywordを実際に評価し、dataclass契約とJSON境界を一致させる。
- `impact`: 検証済みと表示した外部reportが必須NO-GO条件を欠落できる。
- `evidence`: `scripts/validate_sim01_bundle.py`、`tests/test_ai01_arena.py`
- `status`: resolved
- `resolution`: array `contains`とmapping `dependentRequired`を実装し、必須blocker 3種とprebattle hash双方向欠落の負例を追加した。

### AUD-AI01-010

- `opened_on`: 2026-07-14
- `severity`: high
- `phase`: AI-01 / AI-ENV
- `category`: private_state_oracle
- `problem`: policy-facing `EnvironmentSnapshot`、`ResetInfo`、`TransitionInfo`がprivate initial/current state、private event、sealed input、RNG stateのhashを返し、公開観測が同じでも相手の非公開bench setを辞書照合できた。
- `expected`: policy-facing resultは公開観測、公開履歴、公開decision boundaryだけに依存し、full-state lineageはReplay/privileged channelだけへ置く。
- `impact`: HPや技名を直接渡さなくても、hashが低entropyの非公開setを識別するoracleになり、partial-observation評価を無効化する。
- `evidence`: `src/champions_sim/env/models.py`、`src/champions_sim/env/adapter.py`、`tests/test_ai_env_adapter.py`
- `status`: resolved
- `resolution`: privileged `EnvironmentVersionIdentity`とpolicy用`PolicyEnvironmentIdentity`、privileged audit型と`PublicResetInfo`/`PublicTransitionInfo`を分離した。公開episode/transition identityからfull-state hash、sealed hash、engine seed/algorithm、RNG state、fixture identityを除外し、公開済みbattle identityだけから導出する。相手benchのitem/stats/move順、fixture ID、engine seedを同時に変えたreset結果のbyte-identical noninterference testを追加した。full-state/RNG/event lineageは`export_replay`へ限定する。

### AUD-AI01-011

- `opened_on`: 2026-07-14
- `severity`: high
- `phase`: AI-01
- `category`: policy_identity_collision
- `problem`: 初期policy stateの旧normalizerはmappingをJSON objectへ変換して挿入順を失い、共有objectと同値別objectのalias topologyも失った。同一class/runtime/configで異なる選択を返すstateが同じidentityになった。
- `expected`: 方策から観測可能なcontainer型、mapping iteration順、shared-reference topologyを決定論的identityへ結合するか、表現不能stateをfail-closedで拒否する。
- `impact`: plan/proofが実行方策のbehavior-relevant初期stateを一意に表さず、別方策stateへの差替えを検知できない。
- `evidence`: `src/champions_sim/core/implementation.py`、`tests/test_prebattle_proof_and_initial_state.py`、`tests/test_ai01_arena.py`
- `status`: resolved
- `resolution`: mappingを順序付きkey/value列として正規化し、compound objectへ決定論的reference IDを割り当ててalias topologyを保持した。class runtime定数のmapping順も保持し、mapping順・shared list差・list/tuple差の負例を追加した。cycle・unordered・非canonical stateは拒否する。

### AUD-AI01-012

- `opened_on`: 2026-07-14
- `severity`: high
- `phase`: AI-01
- `category`: mutable_observation_alias
- `problem`: `TeamPreviewObservation.own_roster`がsession所有の`PokemonState`とnested stateを参照共有し、frozen dataclassでも`object.__setattr__`により方策がcommit前にfixtureを改変できた。
- `expected`: policy inputのobject graphをtrusted coordinator stateから分離し、方策実行の前後でsession substanceが不変であることを検証する。
- `impact`: 方策が選出観測を通じてstats等を書換え、改変後のmaterialized battleとproofを正規結果として生成できる。
- `evidence`: `src/champions_sim/prebattle/session.py`、`src/champions_sim/prebattle/runner.py`、`tests/test_prebattle_proof_and_initial_state.py`
- `status`: resolved
- `resolution`: caller sessionと各policy observationをdeep-detachし、exact session/roster contractとfresh session hashを各selectionの前後で再検証する。強制書換えがcaller session、run session、materialized battleのいずれにも伝播しない回帰を追加した。

### AUD-AI01-013

- `opened_on`: 2026-07-14
- `severity`: high
- `phase`: AI-01
- `category`: identity_introspection_bypass
- `problem`: instance state読取がpolicy定義`__getattribute__`を通るため実slot変更を隠せた。またclass runtimeの各属性を別々に正規化したため、等値class constants間のshared-reference topologyを失った。
- `expected`: instance storageをsubject codeを実行せず読み、method/default/closure/function attribute/class attribute全体で一つの決定論的reference graphを構成する。
- `impact`: state mutationまたは`LEFT is RIGHT`等でbehaviorが変わってもinitial/runtime/implementation hashが不変になり、proof bindingを迂回できる。
- `evidence`: `src/champions_sim/core/implementation.py`、`tests/test_prebattle_proof_and_initial_state.py`
- `status`: resolved
- `resolution`: `object.__getattribute__`と各ownerの実slot descriptorを直接使ってraw storageを読み、shadowed slotもowner別に保持する。runtime fingerprintはmethod function、code constant、default、kwdefault、closure、function attribute/annotation、behavioral class attributeを横断する単一reference tableを使う。偽`__getattribute__`によるmutation隠蔽とclass constant alias差の負例を追加した。

### AUD-AI01-014

- `opened_on`: 2026-07-14
- `severity`: high
- `phase`: AI-01
- `category`: policy_identity_collision
- `problem`: 初期stateとclass runtimeの正規化で、同値な`int`/`str`等の別objectとshared objectを区別できず、scalar subclassもbase valueへ縮約された。また、同じfunctionのdescriptor binding種別やdynamicに参照されるclass metadataがidentityへ入らなかった。
- `expected`: policyから観測可能なscalar reference topology、exact scalar/container type、method descriptor binding種別、wrapper alias、stable class metadataを決定論的identityへ結合し、未対応subclassはfail-closedで拒否する。
- `impact`: `left is right`、binding時の暗黙引数有無、dynamic `getattr`で選出が変わってもinitial/runtime/implementation hashが不変となり、proof bindingを迂回できた。
- `evidence`: `src/champions_sim/core/implementation.py`、`tests/test_prebattle_proof_and_initial_state.py`
- `status`: resolved
- `resolution`: component stateとruntime constantのexact scalarにreference IDと型tagを付与し、mapping keyを含むalias topologyを保持した。scalar/container subclassを拒否し、Fraction/Enumもreference graphへ含めた。method recordへexact `descriptor_kind`、`descriptor_reference_id`、`function_reference_id`を結合した。behavior-visibleなstable class/function metadataを常時結合し、code中のexact string constantもdynamic member参照候補として収集することで、未対応metadataは省略せずfail-closedにした。shared/distinct scalar、`int` subclass、instance-methodからstaticmethodへの差替え、dynamic class doc差替え、dynamic dataclass metadata拒否を回帰テストへ追加した。

## AI-01 Gate判定

- Requirement/Phase Contract: **GO / SPECIFIED**
- Fail-closed readiness forgery rejection: **IMPLEMENTED / VERIFIED LOCALLY**
- Champions readiness positive issuance: **NO-GO / NOT IMPLEMENTED** — `AUD-AI01-007`
- 6→3 sealed team preview: **IMPLEMENTED / VERIFIED LOCALLY**
- Paired-seat arena、report、Replay verification: **IMPLEMENTED / VERIFIED LOCALLY**
- Public-information selection/battle baseline: **IMPLEMENTED / SYNTHETIC GOLDEN PASS**
- AI-01 trusted-local evaluation foundation: **GO / ENGINEERING COMPLETE**
- Policy process isolation: **NO-GO / NOT IMPLEMENTED**
- SIM-02 M-B candidate: **NO-GOのまま**
- Rank-1 equivalence: **UNMEASURED / CLAIM FORBIDDEN** — `AUD-AI01-004/005`
- RL/LLM/searchの強度昇格: 実M-B executable bundleとpartitioned scenario corpusまで **NO-GO**
- 次の大目的: **SIM-02B SPECIFIED / NOT IMPLEMENTED** — `specs/sim-02b-phase-contract.md`
