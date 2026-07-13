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
