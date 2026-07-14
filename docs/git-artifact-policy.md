# Git and Artifact Size Policy

## 目的

学習軌跡、対戦ログ、モデル、映像、取得データによるリポジトリ肥大化を防ぎながら、出典と再現性を失わないようにする。

## Gitへ追跡するもの

- ソースコード、仕様、Schema、設定
- 小さく目的が明確なgolden fixture
- 出典・ライセンス・hashを記録したmanifest
- 集約された監査・評価レポート
- 再生成方法とartifact ID

## Gitへ追跡しないもの

`.gitignore`により、次をGit管理外とする。

- `data/raw/`
- `data/processed/`
- `replays/`
- `runs/`
- `checkpoints/`
- `embeddings/`
- `llm_cache/`
- `videos/`
- `screenshots/`
- `wandb/`、`mlruns/`、`tensorboard/`、`lightning_logs/`、`tb_logs/`
- `*.tfevents.*`
- `*.ckpt`、`*.safetensors`、`*.pt`、`*.pth`、`*.onnx`
- `*.npy`、`*.npz`
- `**/artifacts/bluestacks/`

元データや旧`champions` PJ全体をこのリポジトリへコピーしない。必要な資産は出典ごとにライセンスを確認し、最小限のコード、Schema、fixtureとして独立に移植する。

## Retentionと昇格

Gitには実験本体を置かず、再現に必要な小さなmanifest、SHA-256、生成器version、入力identity、seed、集約結果だけを追跡する。content-addressed bundleはhashが同じなら同一内容として扱い、次の方針でローカル容量を管理する。

- `runs/`: 実験中のログと中間出力はローカルに保持する。集約結果を検証し、manifestから再生成できる古いrunはローカルからpruneする。
- `replays/`: reportの検証に使うReplay一式は検証完了まで保持する。入力、seed、engine/policy identityから決定論的に再生成できる古いbundleは、対応manifestとhashを残してローカルからpruneする。
- model/checkpoint: 中間checkpointとweightはGitへ追加しない。非昇格候補は実験終了後にpruneし、昇格候補だけを外部artifact storeへ保存する。
- capture: BlueStacksの画像、動画、UI hierarchy等は機微情報を含み得るためGitへ追加しない。必要最小期間だけローカルに保持し、昇格候補の再検証に不可欠なcaptureだけをアクセス制御された外部artifact storeへ保存する。

外部artifact storeへ保存するのは、比較・再検証・昇格の対象になった候補に限る。保存時はGit上のmanifestから外部locator、content hash、byte size、生成器version、入力lineage、ライセンス・機微情報の取扱いへ追跡できるようにする。再生成できないartifactを削除する前には、再現要件と昇格要否を明示的に確認する。

## 暫定容量上限

- 追跡する単一ファイル: 2 MiB（2,097,152 bytes）以下
- fixtureとgolden reference: 256 KiB（262,144 bytes）以下

これらは`PD-001`、`PD-002`の仮置きであり、仕様上の真理ではない。上限を超える必要がある場合、分割、集約、圧縮ではなくmanifest参照への置換を先に検討し、暫定判断を再監査する。

## Artifact manifest

Git外artifactは少なくとも次をmanifestへ記録する。

- 論理artifact ID
- 出典locatorと取得日
- ライセンス状態
- media type、byte size、SHA-256
- 対象レギュレーションとデータ範囲
- parserまたは生成器version
- 派生元manifest ID

ライセンスが確認できない旧PJ由来データは`license_status: unverified`、`local_research_only: true`、`redistribution: prohibited`とする。ローカル研究用に参照できても、元データ・Catalog・Replay以外の派生データを配布可能とは解釈しない。

## 追加前の確認

1. Git indexへ追加されるファイル一覧とbyte sizeを確認する。
2. fixtureが再現に必要な最小レコードだけか確認する。
3. 個人情報、認証情報、画面映像が含まれないことを確認する。
4. 大容量artifactは除外ディレクトリまたは外部artifact storeへ置く。
5. Gitにはmanifest、checksum、集約結果だけを追加する。
6. 再生成可能な古いcontent-addressed bundleをローカルからpruneし、昇格候補だけを外部artifact storeへ残す。

## 自動検査

```powershell
python scripts/check_repo_size.py
python scripts/validate_sim01_bundle.py --usage-scope local_research
```

`check_repo_size.py`はGitのtracked＋untracked非ignore候補を検査し、パスに`fixtures`または`golden`を含むファイルへ256 KiB上限を適用する。`validate_sim01_bundle.py`はCatalog/golden artifactのsize/hash、manifest ID、license制約を検査し、`--usage-scope distribution`では未確認licenseを拒否する。

## SIM-02B / SIM-02C運用追記

SIM-02Bのtest-authoritative positive E2Eと、SIM-02Cで取得するactual M-B evidenceを同じ保存scopeとして扱わない。

### Git追跡可能なSIM-02B資産

- v2のSchema、compiler/resolver、テストコード
- 3 capability、development 3 scenario、external holdout 1 scenarioに限定した最小test-authoritative fixture
- artifact本体を含まないportable source/license/use-policy manifestとcontent hash
- 再生成可能な小さいgolden assessment、gate summary、監査report

test-authoritative fixtureはpromotion経路の正当性を検証するための資産であり、実M-B Catalog/corpusの縮小コピーまたは配布経路にしない。fixture/goldenは256 KiB、その他の追跡単一ファイルは2 MiBの暫定上限を引き続き適用する。

### 必ずGit外へ置くactual M-B資産

- raw source payload、web/API取得結果、旧PJ由来data、生成途中のCatalog/RuleSet
- development/external-holdout construction corpus、engine scenario corpus、Replayとprobe出力
- BlueStacks screenshot、UI hierarchy、video、actual grounding traceの添付artifact
- assessmentの全展開、評価run、trajectory、LLM cache、embedding、model、checkpoint

これらはrepositoryのignored pathまたはアクセス制御された外部artifact storeへ置き、content-addressed keyで保存する。Git上のmanifestから、外部locator、media type、byte size、SHA-256、取得時刻、source issuer、license/use-policy、local-research/distribution制約、対象Regulation/TargetPool、parser/compiler version、親artifactとpartition lineageへ追跡できなければpromotion入力にしない。

SIM-02C-A authoritative intakeの展開済みsource review、235-row mapping、Catalog V2 field workbench、全件assessment、compilation summaryも`data/processed/sim02c/authoritative-intake/<compilation_hash>/`へ置く。実M-B初回runでは最大文書が約2.96MB、5文書合計が約6.37MBであり、集約値だけをvalidation reportへ転記する。tracked plan/policy/source lock/Schemaから外部payloadへhashで辿れるようにし、raw 2,050 files / 405,018,864 bytesや旧PJ本体をworkspaceへコピーしない。`not_authorization`文書をproduction Catalogまたは許諾証跡として扱わない。

license未確認のartifactは`license_status: unverified`、`local_research_only: true`、`redistribution: prohibited`を固定する。この制約はraw dataだけでなく、当該dataを復元可能または再配布不可な派生Catalog、corpus、Replay、grounding添付にも継承する。hash一致は同一性・完全性の検査であり、source真正性や再配布権の証明には使わない。

### 1週間regulation adaptation時の運用

1. `t0`でRegulation/TargetPool、source manifest、license/use-policy、外部artifact locatorを凍結する。
2. 取得artifactは直接Gitへ置かず、まずGit外storeへ保存してbyte size/hashをmanifestへ記録する。
3. `t0 + 48h`のcandidate/NO-GO reportには入力manifest set hash、assessment hash、残存blocker、再開条件だけを集約する。
4. developmentとexternal holdoutはsource・collection・authoring lineageを分離し、別content-addressed namespaceとaccess controlを使う。holdout raw artifactを開発側へ複製しない。
5. `t0 + 7d`の投入判断前に`check_repo_size.py`、license/use-policy resolver、artifact再解決、Replay再検証を実行する。SLAを理由にsize、license、source、holdout gateを迂回しない。

actual evidenceを削除またはpruneする場合は、対応するpromotion/readiness sealの再検証に必要かを先に確認する。昇格候補と、その候補を否定した再生成不能な反証artifactは外部storeに残し、Gitにはlocatorとhashを保持する。

production trust anchorは検証対象のartifact root内へ置かない。公開検証鍵、trusted issuer ID、approved manifest/license hashのような秘密でないreview済みdescriptorだけを小さいGit管理manifestとして置ける。秘密鍵、credential、署名用tokenはGitへ置かず、OS secret storeまたはアクセス制御された外部設定から供給する。入力source manifest自身が宣言する`official`/`verified`値や同じroot内のallowlistをtrust anchorとして扱わない。

SIM-02Cのactual enrollment registryとSQLite ledgerはworkspace/artifact root外のACL保護stateとして扱い、Gitへ入れない。誤配置時も追跡されないよう`/.local/trust/`、`*.sqlite3`、`*.sqlite3-wal`、`*.sqlite3-shm`をignoreする。ledger backupもGitではなく、容量上限・retention・rollback protectionを持つ外部運用領域へ置く。
