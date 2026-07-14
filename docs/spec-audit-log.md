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
- `status`: superseded
- `resolution`: `AUD-SIM02B-001`が別型v2のtest-authoritative positive pathを実装し、本項の到達不能問題を後続契約で置換した。actual M-B production issuanceの不足は`AUD-SIM02B-003`と`AUD-SIM02B-006`で独立に追跡する。

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
- Champions readiness positive issuance: v1は **NO-GO / DIAGNOSTIC ONLY**、後続SIM-02B v2のtest-authoritative positive pathは **RESOLVED / ENGINEERING ONLY** — `AUD-AI01-007`、`AUD-SIM02B-001`
- 6→3 sealed team preview: **IMPLEMENTED / VERIFIED LOCALLY**
- Paired-seat arena、report、Replay verification: **IMPLEMENTED / VERIFIED LOCALLY**
- Public-information selection/battle baseline: **IMPLEMENTED / SYNTHETIC GOLDEN PASS**
- AI-01 trusted-local evaluation foundation: **GO / ENGINEERING COMPLETE**
- Policy process isolation: **NO-GO / NOT IMPLEMENTED**
- SIM-02 M-B candidate: **NO-GOのまま**
- Rank-1 equivalence: **UNMEASURED / CLAIM FORBIDDEN** — `AUD-AI01-004/005`
- RL/LLM/searchの強度昇格: 実M-B executable bundleとpartitioned scenario corpusまで **NO-GO**
- 次の大目的: **SIM-02C Production Trust Anchor + Authoritative M-B Evidence + Executable Scenario Corpus** — SIM-02B local engineering完了後もactual M-B data gateはNO-GO

## SIM-02B実装完了監査 — 2026-07-14

### AUD-SIM02B-001

- `opened_on`: 2026-07-14
- `severity`: critical
- `phase`: SIM-02B / CHAMPIONS-READINESS
- `category`: unreachable_positive_path
- `problem`: `AUD-AI01-007`で、v1診断compilerから正規readiness sealを発行するpositive経路が構造的に到達不能と判明した。
- `expected`: v1を診断専用のまま維持し、source/license/artifact、mapping、Catalog/RuleSet、development scenario、external holdout、grounding、engine-backed probeを実体から再解決する別型v2でpositive E2Eを閉じる。
- `impact`: refusal-only contractをproduction readiness実装済みと誤読し、未検証環境をAI評価へ渡す。
- `evidence`: `src/champions_sim/promotion`、`src/champions_sim/env/readiness_v2.py`、`tests/_sim02b_fixture.py`、`tests/test_promotion_compiler_e2e_v2.py`、`tests/test_champions_readiness_v2.py`
- `status`: resolved
- `resolution`: test-authoritativeな3 source manifestから3 capability、development 3 scenario、lineage分離済みexternal holdout 1 scenarioを実bytesへ結合し、positive engine/Replay probe、grounding、promotion report、可搬Compilation、readiness sealを発行する別型v2を実装した。同一入力の再コンパイルと保持済みCompilation再検証を行い、artifact byte drift、再署名後scenario drift、synthetic regulationのproduction claimをfail-closedで拒否する。test scopeは`champions_candidate: false`と`rank1_equivalence_status: unmeasured`を固定する。本項のresolutionを`AUD-AI01-007`の後続解決記録とする。

### AUD-SIM02B-002

- `opened_on`: 2026-07-14
- `severity`: critical
- `phase`: SIM-02B / M-B DATA GATE
- `category`: scope_conflation
- `problem`: test-authoritative positive E2Eの成功を、現行M-Bのproduction readinessまたはChampions fidelityへ読み替える余地があった。
- `expected`: local engineering gateとactual M-B data gateを別判定にし、source scopeから`champions_candidate`をresolverが導出する。
- `impact`: synthetic fixture成功だけでprivate-match candidateを発行し、誤ったCatalog/RuleSetをAIへ渡す。
- `evidence`: `specs/sim-02b-phase-contract.md`、`data/golden/sim02b-m-b-no-go-v2.json`、`docs/validation-report-sim02b.md`
- `status`: resolved
- `resolution`: local gateは`GO / ENGINEERING COMPLETE`、test readinessは`engineering_sealed`かつ`champions_candidate: false`、actual M-Bは独立した`NO-GO`と固定した。現M-B assessmentはmapping 0/235、unresolved 219、conflict 16、target capability row 118、execution gap 118、diagnostic blocker 718、promotion assessment blocker 720を返す。

### AUD-SIM02B-003

- `opened_on`: 2026-07-14
- `severity`: critical
- `phase`: SIM-02C / M-B DATA GATE
- `category`: missing_authoritative_evidence
- `problem`: 現行M-Bのverified mappingは0/235で、resolver-backed production source/license、capability-complete development corpus、lineage分離済みsealed holdout、actual grounding、全必須capabilityのpositive engine probeがない。
- `expected`: 全235 memberと全declared capabilityをauthoritative source recordまたはactual private-match traceへ結合し、4 rate 1.0、holdout novel gap 0、silent fallback 0を再計算する。
- `impact`: production readiness sealを発行できず、MCTS/RL/LLMをChampions candidateとして評価できない。
- `mitigation`: 不足member/capabilityを分母から除外せず、exact assessmentと再開条件をcontent-addressed reportへ固定する。LLM推論、名前一致、使用率、旧Catalogの類似IDで解除しない。
- `suggested_action`: `SIM-02C Production Trust Anchor + Authoritative M-B Evidence + Executable Scenario Corpus`で720 blockerをtrust anchor、証拠取得、engine-backed scenarioにより解消する。
- `evidence`: `data/golden/sim02b-m-b-no-go-v2.json`、`specs/sim-02b-phase-contract.md`、`docs/validation-report-sim02b.md`
- `status`: open
- `resolution`:

### AUD-SIM02B-004

- `opened_on`: 2026-07-14
- `severity`: high
- `phase`: SIM-02B / SIM-02C
- `category`: artifact_governance
- `problem`: 実M-Bのsource payload、corpus、Replay、capture、grounding添付、評価runは大容量化し、license未確認データや機微情報を含み得る。
- `expected`: 大容量・raw・機微artifactをcontent-addressedなGit外storeへ置き、GitにはSchema、小fixture、manifest、hash、license/use-policy、lineage、集約結果だけを置く。
- `impact`: repository肥大化、再配布権違反、captureからの情報漏えい、再現lineageの喪失。
- `evidence`: `docs/git-artifact-policy.md`、`.gitignore`、`scripts/check_repo_size.py`
- `status`: resolved
- `resolution`: SIM-02B/SIM-02C専用のGit外artifact運用を追記し、test fixtureを実M-B corpusの格納先にしないこと、license未確認派生物も公開しないこと、1週間適応中もsize/license/source gateを迂回しないことを固定した。

### AUD-SIM02B-005

- `opened_on`: 2026-07-14
- `severity`: high
- `phase`: SIM-02C / REGULATION ADAPTATION
- `category`: operational_validation_gap
- `problem`: 48時間candidate/NO-GOと7日private-match投入判断は契約化されたが、actual/sealed-historical regulationでのend-to-end wall-clock実測がない。
- `expected`: `t0`を署名・hash固定済みRegulation/TargetPool受領時刻として記録し、48時間でexact candidate/NO-GO、7日でholdout・AI-01評価・回帰・包装までを実測する。
- `impact`: コードが正しくても新regulation投入SLAを満たせず、blocker発見と取得作業の優先順位が不明になる。
- `mitigation`: `NO-GO`を工程SLA達成と投入成功に分離し、時刻・外部待ち・手作業・compute時間をassessmentへ記録する。
- `suggested_action`: SIM-02Cの最初の現行またはsealed-historical M-B runを1週間adaptation rehearsalとして扱う。
- `evidence`: `specs/sim-02b-phase-contract.md`、`docs/validation-report-sim02b.md`
- `status`: open
- `resolution`:

### AUD-SIM02B-006

- `opened_on`: 2026-07-14
- `severity`: critical
- `phase`: SIM-02B / PRODUCTION TRUST BOUNDARY
- `category`: self_attested_production_scope
- `problem`: source manifestのauthority/source kind、license verification、Regulation status、timing measurementをartifact root内で整合的に書き換えると、外部真正性検証なしで`production_champions`、`production_candidate`、`champions_candidate: true`を発行できた。
- `expected`: production scopeはartifact rootと別の信頼境界にあるtrust anchorがtrusted issuer/authorityとapproved manifest/license identityを固定した場合だけ発行する。local JSONの`official`/`verified`文字列を信頼しない。
- `impact`: synthetic fixtureまたは任意local dataをChampions準拠candidateへ自己昇格でき、SIM-02B全gateと下流AI評価を迂回する。
- `mitigation`: artifact-root外trust-anchor verifierが未実装（`trust_anchor_status: not_implemented`）の間、current/verifiedを含むproduction claimをcompilerで常にfail-closed拒否する。現M-B assessmentへ`production_trust_anchor_missing`を追加し、production blockerを720へ更新した。test-authoritative engineering pathは維持する。
- `evidence`: `tests/test_promotion_compiler_e2e_v2.py::test_untrusted_local_claims_cannot_issue_production_candidate`、`src/champions_sim/promotion/compiler.py::_validate_scope`
- `status`: resolved
- `resolution`: SIM-02B V2はproduction発行をunconditional fail-closedのまま凍結し、local JSONだけでcandidateを発行する脆弱経路を閉じた。positive trust verificationはV2を緩和せず、SIM-02C V3の外部policy/attestation/enrollment型へ分離した。SIM-02B goldenの`production_trust_anchor_status: not_implemented`はこのV2発行経路のfrozen fieldであり、V3工学verifierの有無を表さない。actual M-B enrollment未設定のNO-GOは`AUD-SIM02C-003`で追跡する。

### AUD-SIM02B-007

- `opened_on`: 2026-07-14
- `severity`: high
- `phase`: SIM-02B / SOURCE RESOLUTION
- `category`: split_resolution_snapshot
- `problem`: compile前半でmanifest/artifactを解決してbound bytesを読み、mapping/construction reference取得後に同じmanifest集合をもう一度解決していた。途中でsource treeが変化すると、前半のCatalog等と後半のsource resolution setが別snapshotになり得た。
- `expected`: 1 compileにつき各source manifestを1回だけ解決し、後から判明するrecord referenceは最初のresolved artifact snapshotへattachして検証する。
- `impact`: 一時的に異なるsource identityとcomponent bytesを同じpromotion reportへ束ね、compile単体のcontent lineageを曖昧にする。
- `evidence`: `src/champions_sim/promotion/compiler.py::_attach_record_references_to_source_set`、`tests/test_promotion_compiler_e2e_v2.py::test_compile_resolves_each_source_manifest_once`
- `status`: resolved
- `resolution`: manifest/artifact snapshotを再利用してrecord JSON pointer/hashだけを追加検証する経路へ変更した。E2Eで3 manifestが各1回だけ解決されることを固定し、artifact再読時のsize/hash検査は維持した。

## SIM-02B Gate判定（frozen V2 completion snapshot）

- Phase Contract: **SPECIFIED / FROZEN FOR SIM-02B**
- v2 local engineering implementation: **GO / ENGINEERING COMPLETE**
- test-authoritative positive E2E: **GO** — 3 capability、development 3 scenario、external holdout 1 scenario、再コンパイル・再検証・改変拒否
- test-authoritative readiness seal: **GO / `champions_candidate: false`**
- actual M-B data gate: **NO-GO** — 0/235 verified mapping、118/118 target row/execution gap、718 diagnostic blockers、720 promotion blockers
- V2 production verifier: **INTENTIONALLY ABSENT / unconditional fail-closed / issuance disabled** — `AUD-SIM02B-006`
- actual M-B production readiness seal: **NO-GO / 発行不可** — `AUD-SIM02B-003`
- one-week actual adaptation rehearsal: **NO-GO / UNMEASURED** — `AUD-SIM02B-005`
- Rank-1 equivalence: **UNMEASURED / CLAIM FORBIDDEN** — `AUD-AI01-004/005`
- Full regression: **454 passed in 43.17s**
- 次の大目的: **SIM-02C Production Trust Anchor + Authoritative M-B Evidence + Executable Scenario Corpus**

## SIM-02C事前監査 — 2026-07-14

### AUD-SIM02C-001

- `opened_on`: 2026-07-14
- `severity`: critical
- `phase`: SIM-02C / EXTERNAL HOLDOUT INTEGRITY
- `category`: semantic_identity_gap
- `problem`: scenario hashはscenario ID/partition/lineage labelを除外するがfull `ReplayRecord.replay_hash`を含む。Replay hashは`replay_id`を含むため、development Replayの`replay_id`だけを変更し、別source/collection/authoring labelを付けると同一executionをexternal holdoutとしてcompileできた。
- `expected`: bound Replayの実行内容からrecord/battle/request/action/lineageのcosmetic IDに依存しないexecution fingerprintを再計算し、development/holdout間の意味的重複を0にする。宣言hashはbound Replayと一致させる。
- `impact`: 開発に使用した対戦をID変更だけでblind holdoutに見せ、novel gap 0とproduction昇格根拠を偽装できる。
- `mitigation`: production trust導入前はactual M-B production発行を停止したまま維持する。
- `suggested_action`: `replay_execution_hash`をscenario/partition/Compilationへ結合し、relabel duplicateのnegative E2Eを追加する。
- `evidence`: `src/champions_sim/promotion/scenarios.py`、`src/champions_sim/core/replay.py`、現HEAD 1ce04c2での敵対的再現
- `status`: resolved
- `resolution`: Replayのsimulator/engine/Catalog/RuleSet、private initial state、RNG境界、decision/action substance、events、terminal resultから`replay_execution_hash_v2`を再計算する。replay/battle/request/action/instance/source/provisional IDを全置換してfull Replay hashとchoice hashが変わってもexecution hashは同一になること、battle substance変更では変わることを固定した。scenario/partition/compilerが宣言hash一致とdevelopment/holdout execution overlap 0を要求し、unitおよびcompiler E2Eでrelabel attackを拒否する。

### AUD-SIM02C-002

- `opened_on`: 2026-07-14
- `severity`: critical
- `phase`: SIM-02C / PRODUCTION TRUST AND PORTABILITY
- `category`: missing_spec
- `problem`: V2はproduction trust verifierを持たず意図的に全production claimを拒否する。またCompilation JSONはhash-bound summaryだが、再検証に必要なrequest/replays/tracesをprivate runtime fieldへ保持し、fresh processでJSON単体から再構築できない。
- `expected`: V2を緩和せず、artifact-root外のpinned public-key policy、revocation、trusted clock、replay ledgerで署名subjectを検証するV3と、絶対path/secretを含まないinput manifestを別契約にする。portable summary単体をauthorizationにしない。
- `impact`: V2拒否を雑に解除すると任意local JSONをChampions candidateへ昇格でき、反対にsummaryだけをportable再検証可能と誤認すると必要なruntime evidenceを失う。
- `mitigation`: V2 production issuanceをunconditional fail-closedのまま維持し、actual key enrollment前はproduction policyを未構成とする。
- `suggested_action`: `specs/sim-02c-phase-contract.md`に従い、trust policy/attestation/receipt、V3 Compilation/readiness、input manifest、敵対的E2Eを実装する。
- `evidence`: `src/champions_sim/promotion/compiler.py`、`src/champions_sim/env/readiness_v2.py`、`PD-010`
- `status`: resolved
- `resolution`: V2の拒否を維持したまま、artifact-root非依存`ProductionPromotionInputManifestV3`、OpenSSH Ed25519 policy/attestation/receipt、trust-bound `AttestedProductionPromotionCompilationV3`、current-context再検証型`ResolvedChampionsReadinessV3`を別型で実装した。portable documentは絶対path・secret・検証実行時刻を含めず、常に`authorization_status: not_authorization`とcurrent-context要求を持つ。pre/post resolverは同一content-addressed manifestへ収束し、その間のV2 core compileは1 resolved source snapshotだけを消費する。ephemeral fixtureで配線を検証するが、actual issuer/source/license/M-B readinessを証明しない。

### AUD-SIM02C-003

- `opened_on`: 2026-07-14
- `severity`: critical
- `phase`: SIM-02C / PRODUCTION TRUST ROOT
- `category`: arbitrary_policy_substitution
- `problem`: 初期V3案はcaller supplied `ProductionTrustContextV1`のpolicy pathとexpected policy hashを相互照合するだけで、caller自身がEd25519 key、policy、attestationを一式作れば暗号検証に成功した。policy hash pinは内容同一性を示すが、そのpolicyが事前に信頼登録されたことを示さない。
- `expected`: compile callerがpathを選べないartifact root/workspace外の固定enrollment stateをrootとし、登録済みpolicy/verification binary/minimum epoch/status/validityだけを受理する。pre/post/current再検証でenrollment driftを拒否する。
- `impact`: 任意local actorが自分をissuerとして登録したように見せ、署名subjectを自己承認してproduction V3経路を迂回できる。
- `mitigation`: actual enrollmentが構成されるまでactual M-B production発行を停止し、portable summaryをauthorizationにしない。
- `suggested_action`: 固定per-user enrollment registryを追加し、registry/enrollment bindingをV3 Compilation/readinessへ結合する。missing/unregistered/revoked/expired/driftをnegative E2Eで拒否する。
- `evidence`: `src/champions_sim/promotion/trust_enrollment.py`、`src/champions_sim/promotion/compiler_v3.py`、SIM-02C enrollment/compiler tests、`PD-011`
- `status`: resolved
- `resolution`: `%USERPROFILE%\.champions_sim\production-trust\enrollment-registry-v1.json`をcaller非選択の起動時固定rootとして読み取り専用利用し、registry ID/hash、enrollment ID/binding、policy ID/hash、OpenSSH executable hash、minimum policy epoch、status、有効期間、provision済みledger instance ID/path bindingを検査する。registry/ledger identityを作成・更新するproduction APIは持たず、testでは一時directoryへの明示monkeypatch/provisionだけを使う。同一process monkeypatch、起動環境、同一OS userによるregistry/ledger/code改変はcode integrityとOS保護を信頼する脅威境界として`PD-011`へ明示した。actual registry/key/policy/ledger/clockは未登録である。

### AUD-SIM02C-004

- `opened_on`: 2026-07-14
- `severity`: critical
- `phase`: SIM-02C / SOURCE SNAPSHOT TOCTOU
- `category`: change_compile_restore
- `problem`: pre trust検証後にsource artifactと宣言manifestを一時変更し、V2 core compile後に元へ戻すと、post resolverは元の署名subjectへ収束してもbase Compilationだけが一時snapshotを保持できた。
- `expected`: post filesystem再読だけでなく、coreが実際に消費した初期resolved source snapshotとbase requestを署名subject/input manifestへ照合する。
- `status`: resolved
- `resolution`: baseの保持source setからcore入口時のgrounding-only recordsを復元し、manifest/license/artifact digestを含むsource authority hashとinput resolution hashを署名対象へexact比較した。request bindingもbase retained requestから再計算する。change-compile-restore negative E2Eは修正前に再現し、修正後にfail-closedした。

### AUD-SIM02C-005

- `opened_on`: 2026-07-14
- `severity`: high
- `phase`: SIM-02C / TRUST LEDGER CONTINUITY
- `category`: external_state_rollback
- `problem`: caller選択ledgerを削除するとtrust core単体は新規SQLiteを作成でき、同一attestation IDの履歴を失う。`trusted_time`もprivileged context入力であり、OS保護なしでは巻戻せる。
- `expected`: public V3は固定enrollmentに登録した既存ledger installationだけを受理し、消失/別instanceを拒否する。actual運用はledger snapshot rollbackとclock rollbackを外部で防止する。
- `status`: resolved_local / blocked_external_actual
- `resolution`: enrollmentへledger instance IDとdomain-separated normalized path bindingを追加し、既存SQLite identityをread-only解決してからV3検証する。ledger消失・空置換・別path/instanceをnegative E2Eで拒否した。同一OS userによるregistry/ledger snapshot改変とtrusted clock provenanceはACL、backup/耐rollback、非巻戻しclockというactual authorization前提として`PD-011`へ残す。

### AUD-SIM02C-006

- `opened_on`: 2026-07-14
- `severity`: critical
- `phase`: SIM-02C-A / AUTHORITATIVE EVIDENCE INTAKE
- `category`: unstructured_source_and_catalog_gap
- `problem`: 既存intake/promotion compilerはsource bytesのhashとnegative mappingを保持するが、旧PJの取得config/parser/raw manifest/derived artifactをsource route単位で監査せず、semantic authorityとusage permissionを分離したreview、namespace/form-aware 235-row workbench、全required Catalog fieldの状態、最初の例外で止まらない全件blocker assessmentがなかった。次レギュレーションで何を再取得・審査・実装すべきかを1週間単位で機械再生成できなかった。
- `expected`: tracked acquisition plan/policy/source lockとGit外payloadから、path/symlink/duplicate key/hash/size/count/source driftをfail-closed検査する。235件を縮小せず、name/dex/site-ID一致をcandidate以下に留め、Catalog required fieldをcandidate/missing/unknown/conflict/verifiedへ分け、source/policy/mapping/Catalog/mechanics/scenario/grounding/holdout/trust/rehearsal blockerを全件返す。全出力を`not_authorization`としproduction materializationを行わない。
- `impact`: 旧ID衝突、欠落base stats、自由文effect、利用許諾不明、raw manifest未封印を隠したままV2/V3入力または学習環境へ誤昇格し、戦略探索が誤った遷移を最適化する。
- `mitigation`: SIM-02B/V3を凍結したまま、独立`src/champions_sim/authoritative` workbench、7 Schema、5-route plan/policy、Gitignored content-addressed writer、CLI、合成敵対テストを追加した。source planはネットワーク取得を行わず既存local bytesだけをinventoryする。
- `evidence`: `specs/sim-02c-authoritative-intake-contract.md`、`scripts/build_m_b_authoritative_intake.py`、`src/champions_sim/authoritative`、`tests/test_authoritative_intake.py`、plan/policy/7 Schema、compilation `bdb90c2d3128f336e09addcfc19a1cf9a13a3a073cf0cf8aad61c0f12b9f90d5`
- `status`: resolved_local_workbench / blocked_external_promotion
- `resolution`: synthetic 28 testsで決定性、公式source-manifest固定分母、regulation revision、自己hash、duplicate key、path/ADS escape、opened-handle confinement、symlink、snapshot/CLI identity drift、source-bound policy全用途、authority別acquisition profile、closed evidence role、manifest/inventory binding、declared/runtime source coverage、Catalog gap、Schema、atomic writerを検証した。実M-Bは5 route、raw 2,050 files / 405,018,864 bytes、derived 23、acquisition complete/partial 1/4、policy resolved 0/5、mapping candidate/conflict/verified 219/16/0、Catalog required/verified/lowerable 8,024/0/0、合計10,794 blockerの`NO-GO`を再現した。raw/processed payloadと全展開文書はGit外で、production materialization 0。次はreview overlayとapproved fieldだけをmechanicsへlowerするSIM-02C-Bで解消する。

### AUD-SIM02C-007

- `opened_on`: 2026-07-14
- `severity`: critical
- `phase`: SIM-02C-A / AUTHORITATIVE INTAKE HARDENING
- `category`: mutable_authorization_policy_binding_denominator_toctou
- `problem`: adversarial review reproduced post-construction authorization mutation, source-unbound permissive policy substitution, omitted private-match/training restrictions, evidence-empty completion, hash/parse split snapshots, unbound target denominator, partial final-directory publication, and Windows ADS path acceptance.
- `expected`: every materialized document remains non-authorizing after revalidation; source policy covers the exact intended source/use set; M-B denominator is bound to reviewed source-manifest bytes and regulation revision; evidence and parse share one snapshot; final output appears atomically.
- `status`: resolved_local_workbench / filesystem_race_residual_documented
- `resolution`: writer-side full revalidation and defensive copies, exact source-ID/all-use policy gates, non-empty evidence/raw-manifest gates, single-byte-snapshot parsing, plan-pinned official target manifest and M-B CLI identities, explicit regulation revision lineage, ADS/reserved-path rejection, and staging-to-atomic-rename output were added. 23 focused tests and the actual 10,794-blocker M-B NO-GO compilation pass. A hostile same-user process racing directory junction replacement remains outside this workbench's Python-level trust boundary; generated output is non-authorizing and rechecked on reuse.

## SIM-02C Gate判定

- Phase Contract: **SPECIFIED / IMPLEMENTATION SYNCHRONIZED**
- SIM-02B V2 production path: **FAIL-CLOSED / issuance disabled**
- semantic execution partition: **GO / VERIFIED LOCALLY** — cosmetic ID全変更でも重複拒否
- artifact-root independent input manifest: **GO / VERIFIED LOCALLY** — round-trip、relocation、path/drift拒否
- V3 trust/enrollment verifier: **GO / VERIFIED LOCALLY WITH EPHEMERAL FIXTURE** — test key/policy/registryだけ
- SIM-02C-A authoritative intake workbench: **GO / VERIFIED LOCALLY** — actual 5 route / 235 mapping / 8,024 Catalog field / 10,794 blockerをcontent-addressed再生成
- portable V3 output: **NOT AUTHORIZATION / current trust context required**
- actual M-B production policy/key/enrollment: **NO-GO / NOT CONFIGURED**
- actual M-B data gate: **NO-GO** — frozen V2 mapping 0/235・unresolved/conflict 219/16・target/execution 118/118・diagnostic/promotion 718/720に加え、SIM-02C-A promotion unresolved 235、Catalog verified 0/8,024、actual grounding 0
- Champions fidelity / private-match投入: **NO-GO / UNPROVEN**
- Rank-1 equivalence: **UNMEASURED / CLAIM FORBIDDEN**
- Focused SIM-02C verification: **97 passed in 29.15s**
- Focused SIM-02C-A authoritative intake verification: **28 passed in 2.22s**
- Full regression: **552 passed in 78.67s**
- Repository size gate: **249 candidates / 0 violations**
- SIM-01 frozen validation: **PASS / hash不変**
