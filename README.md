# champions_sim

`champions_sim`は、Pokémon Championsのシングルバトルを対象とする、再現可能な対戦シミュレータとAI研究基盤です。最終的にはフレンド戦で使う強い意思決定系を目指します。SIM-01の決定論的3対3参照実装、SIM-02のRegulation/TargetPool/Coverage/Diffとsource-to-capability compiler、AI-01の6→3選出・paired arena・公開情報baselineまでローカル実装済みです。現行M-B全体の検証済みCatalog/メカニクスcoverage、actual実機grounding、学習済み/search方策、BlueStacks入力操作は未完成です。

## 現在のスコープ

- 最初の実装フェーズは`SIM-01`の決定論的な対戦状態遷移です。
- 次の`SIM-02`は、version固定されたRegulation/TargetPoolManifestから対応範囲を拡張するフェーズです。使用率thresholdやtop-Nで対象を選ばず、固定manifestに対するexecution coverage、外部grounding conformance、silent fallback 0、48時間rehearsalを別々に測ります。
- M-Bの公式eligible listは235 unique dex/form/variant keyで固定済みです。旧IDを全国図鑑番号から暗黙推定する処理を廃止し、現在のsource-to-capability compileでは0件をresolved/verified、219件をunresolved/unverified、16件をconflict/unverifiedとして保持します。候補件数をcapability coverageや環境採用率へ読み替えません。
- Source-bound Catalog intakeは旧PJをコピーせず、235 targetに対して213 usage crosswalk候補、22 exact-name candidate、16 detail-ID conflict、22 detail不足を再生成します。生成bundleはGit管理外で、license未確認・ローカル研究限定・再配布禁止を強制します。
- TargetCapability pipelineは実M-B intakeまで接続済みです。Catalog-wide semantic inventory 788、現時点のtarget capability row 118を生成し、6実行次元と実行probeを再計算します。全候補の意味・優先度・効果順が未検証で235件のmapping分母も確定していないため、coverage count/rateは`null`、execution gap 118、capability別executor未取得118、silent fallback 0、理由718件の決定論的`NO-GO`になります。`silent fallback 0`はpositive execution証拠とは扱いません。
- 現在のエンジンは`sim01_catalog.json`と`sim01_ruleset.json`に列挙された対応効果だけを扱い、未知効果はfail-closedにします。
- Generic mega fixtureでは単側の1戦1回、pre-move変身、永続状態、観測、Replayを実装しました。現M-B RuleSetでは`mega_evolution`を引き続きunsupportedとし、16形態と同時メガシンカ順のgrounding完了までM-B対応を主張しません。
- 10,000戦seeded smokeは完走済みですが、これはローカル参照実装の安定性であり、公式Champions準拠の証明ではありません。
- Replay v2は初期状態、decision、RNG、eventsを持つbundle-bound形式です。検証には記録hashと一致する外部Catalog/RuleSetが必要です。
- Synthetic regulation rehearsalは、sealed inputから理由付き`NO-GO`を48時間SLA内で生成する配線を検証しました。`operational_rehearsal_success`であり、実測wall-clockまたは`deployable_candidate_success`ではありません。
- BlueStacks read-only診断は5.22.51.1038と4 instanceを検出しました。player/HD-Adb停止に加え、ADB clientのdaemon side effectを排除するownership supervisorが未実装のためcaptureは実行せず、actual GroundingTraceはまだありません。CaptureStore、resolver-backed GroundingTrace、AI Envはsynthetic payloadと改竄攻撃で契約検証済みです。
- 正確なルール、合法手、乱数、リプレイをAIやUIから分離します。
- 強化学習、LLM、探索、構築生成は、検証済みシミュレータの下流に置きます。
- Policy-free AI adapterは内部ではsealed fixture、bundle hash、seed/RNG lineageへ結合した`reset`/`step`を提供しますが、policy-facing resultには公開identity、観測、公開履歴、合法手だけを返し、privileged lineageはReplayへ分離します。報酬と方策は定義せず、Champions candidateはcapability/grounding evidenceがverifiedになるまでactionableにしません。
- AI-01は自己申告`VERIFIED`による迂回を再計算型readiness resolverで閉じ、6体roster→順序付き3体のsealed team preview、paired seed/side-swap arena、公開情報だけを使うtype-coverage選出＋type-aware行動baselineを実装しました。現v1 compilerはintake診断専用でcandidateを構造的に発行できないため、readinessの正経路は未実装のままfail-closedです。
- AI-01 frozen synthetic benchmarkは64 pair / 128戦、Replay verification 100%、candidate 126勝0分2敗です。単一SIM-01 fixtureの工学回帰に限り、reportは常に`champions_candidate=false`、`rank1_equivalence_status=unmeasured`です。
- 実ゲームの操作対象はプライベートマッチのフレンド戦に限定します。
- ランクマッチ自動操作、BlueStacks入力操作、学習実験は現在の対象外です。read-only診断/captureもフレンド戦のgrounding用途に限定します。

## 設計原則

1. シミュレータは同じ初期状態、選択列、seedから同じイベント列を生成する。
2. 正確なルールはLLMに推測させず、版管理された`RuleSet`と`Catalog`を正本とする。
3. 未検証・未実装の効果は近似せず、fail-closedで停止または不支持を返す。
4. 完全状態と各プレイヤーから見える瞬間観測を分離する。UI HP量子化や履歴memoryは将来のadapter/agent側で扱う。
5. 外部情報には出典、取得日、ライセンス状態、ハッシュを持たせる。
6. 大容量データ、リプレイ、モデル、映像はGitへ入れない。

## 仕様・検証成果物

- [Requirement Contract](specs/requirement-contract.md)
- [SIM-01 Phase Contract](specs/sim-01-phase-contract.md)
- [SIM-02 Phase Contract](specs/sim-02-phase-contract.md)
- [AI-01 Phase Contract](specs/ai-01-phase-contract.md)
- [SIM-02B Phase Contract](specs/sim-02b-phase-contract.md)
- [仕様監査規則](specs/spec-audit.md)
- [暫定判断台帳](docs/provisional-decisions.md)
- [仕様監査ログ](docs/spec-audit-log.md)
- [追跡表](docs/traceability.md)
- [Git・成果物容量方針](docs/git-artifact-policy.md)
- [SIM-01検証レポート](docs/validation-report-sim01.md)
- [SIM-02検証レポート](docs/validation-report-sim02.md)
- [AI-01検証レポート](docs/validation-report-ai01.md)
- `data/schemas/`: RuleSet、Catalog、Battle fixture、Replay v2、source manifest、production Catalog input、source-to-capability report、AI-01 Arena report/evidence manifestのJSON Schema
- `data/manifests/`: 小さな出典manifest例。元データ本体は含めない
- `scripts/validate_sim01_bundle.py`: Schema、loader、Replay、manifest hash、license scopeの統合検査
- `scripts/check_repo_size.py`: `PD-001/002`のGit候補ファイル容量検査

## 開発制約

- Python 3.10以上
- ランタイムは原則として標準ライブラリのみ
- テスト依存は`pytest`

JSONファイルの構文だけを標準ライブラリで確認する場合は、次のように実行できます。

```powershell
python -m json.tool data/schemas/ruleset.schema.json
python -m json.tool data/manifests/legacy-champions-reference.example.json
```

ローカル研究用bundleと容量方針は次で検査できます。

```powershell
python scripts/validate_sim01_bundle.py --usage-scope local_research
python scripts/validate_sim01_frozen.py
python scripts/check_repo_size.py
python scripts/build_regulation_diff.py
python scripts/diagnose_bluestacks.py
python scripts/build_catalog_intake.py --legacy-root "C:\Users\hogeh\Desktop\Git\Pokemon\champions" --source-lock data/manifests/catalog-intake-m-b-source-lock.json --dry-run
python scripts/build_source_to_capability_bundle.py --legacy-root "C:\Users\hogeh\Desktop\Git\Pokemon\champions" --dry-run
python scripts/run_ai01_benchmark.py --pairs 64 --summary-only
$env:PYTHONPATH="src"
python -m champions_sim battle --seed 20260713
python -m champions_sim verify-replay --replay replays/example.json
python -m champions_sim smoke --battles 10000 --seed-start 0
python -m pytest -q
```

`build_source_to_capability_bundle.py`は同じsealed sourceから同じreport hashを生成します。成果物はcontent-addressedな`data/processed/sim02/source-to-capability/<report_hash>/`へだけ書き出し、Git管理外に置きます。`--require-candidate`は現証拠で理由付き`NO-GO`となるため終了コード3を返します。`--usage-scope distribution`も、旧PJ由来データのlicenseが未確認な間は意図的に失敗します。

`run_ai01_benchmark.py`はsynthetic 6→3選出後に全seedを両seatで実行し、各Replayを再実行検証してからArena reportを作ります。通常はGitignored `runs/ai01/<report_hash>/`へreport、全Replay、evidence manifestを保存します。`--summary-only`だけが非永続・非検証サマリです。旧`--dry-run`と`--write-replays`は互換オプションとして残しています。この保存物はprebattle runを含まないbattle-Replay archiveであり、evidence hash単体は認証ではありません。完全な再検証には、同じTeamPreviewRun/policiesを再生成し、exact `BoundAgent`、engine、initial state、保存Replayを組み立てた`ArenaRun`を`verify_arena_run`へ渡します。

## データ管理

`data/raw/`、`data/processed/`、`replays/`、`runs/`、`checkpoints/`、`embeddings/`、`llm_cache/`、`videos/`、`screenshots/`はGit管理外です。Gitにはスキーマ、小さなfixture、manifest、集約結果だけを残します。詳細と暫定上限は[Git・成果物容量方針](docs/git-artifact-policy.md)を参照してください。

## 次のゲート

- P0統治: 完了
- SIM-01ローカル参照bundle: 工学ゲート完了。ローカル研究に限り`GO`
- SIM-02ローカル基盤: regulation/target/coverage/diff/rehearsal/grounding/AI Env/generic mega、Catalog intake、source-to-capability compilerを実装・ローカル検証済み
- SIM-02 target coverage: 実M-Bを一コマンドでcompile済み。resolved/verified mapping 0、unresolved 219、conflict 16、execution gap/未実証probe 118、分母未確定のためcoverage値`null`、silent fallback 0の理由付き`NO-GO`
- SIM-02 synthetic rehearsal: operational success、deployable successではない
- SIM-02 BlueStacks actual grounding: player/HD-Adb停止、ADB ownership未検証、actual traceなしのため`NO-GO`
- SIM-02 M-B candidate: メガ16形態、同時順、Catalog coverage、groundingが未完了のため`NO-GO`
- SIM-02 Champions外部最終ゲート: 外部holdout、actual/sealed historical rehearsal、実機conformanceが揃うまで`NO-GO`
- AI-01 trusted-local evaluation foundation: 6→3選出、paired arena、公開情報baseline、Replay evidenceを実装・ローカル検証済み。process isolationとreadiness正経路は未達
- AI-01 synthetic strength: frozen regressionは成功。ただし実M-B/scenario holdout/上位層較正がないため`UNMEASURED`
- 次の大目的 SIM-02B: production Catalog promotionとevidence-backed development/external-holdout scenario corpus。v2 resolver/compiler完成までは`SPECIFIED / NO-GO`
- ランク1相当の主張: `NO-GO`。synthetic勝率、self-play Elo、LLM評価を代替証拠にしない
- 公式Champions準拠としての昇格: 実機照合が終わるまで`NO-GO`
- データ・派生物の再配布: license確認が終わるまで`NO-GO`

具体的な境界は[Requirement Contract](specs/requirement-contract.md)と[仕様監査ログ](docs/spec-audit-log.md)に記録します。
