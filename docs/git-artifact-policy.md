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

元データや旧`champions` PJ全体をこのリポジトリへコピーしない。必要な資産は出典ごとにライセンスを確認し、最小限のコード、Schema、fixtureとして独立に移植する。

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

## 自動検査

```powershell
python scripts/check_repo_size.py
python scripts/validate_sim01_bundle.py --usage-scope local_research
```

`check_repo_size.py`はGitのtracked＋untracked非ignore候補を検査し、パスに`fixtures`または`golden`を含むファイルへ256 KiB上限を適用する。`validate_sim01_bundle.py`はCatalog/golden artifactのsize/hash、manifest ID、license制約を検査し、`--usage-scope distribution`では未確認licenseを拒否する。
