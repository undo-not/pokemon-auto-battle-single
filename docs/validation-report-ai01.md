# AI-01 Validation Report

## 結論

AI-01 / Competitive Readiness Foundationのうち、信頼済み同一process・ローカルsynthetic scopeでの選出／対戦／Replay評価配線は **ENGINEERING COMPLETE** である。

これまでの「誤ったルールを学習しない」SIM-02方針は正しかった。一方、235 mappingや118 execution gapだけを追っても、AIの意思決定品質は測れなかった。AI-01では環境正確性gateを維持したまま、戦略品質を別の閉ループで測るための選出・方策・評価基盤を追加した。

ただし、現M-B compilerはNO-GO、actual groundingは0、scenarioは単一SIM-01 syntheticである。さらにv1 compilerはintake-only入力、空development corpus、`catalog_emit_eligible=false`を強制するため、readiness sealの正規発行経路は構造的に未実装である。したがって、Pokémon Champions準拠、実戦汎化、process-isolated privacy、ランク1相当は **UNMEASURED / CLAIM FORBIDDEN** のままである。

## 実装した大きな成果

### 1. Fail-closed readiness resolver

- `EnvironmentBundleIdentity`を説明データとし、attestationとして信頼しない。
- callerがcapability/groundingを`VERIFIED`にし、任意64桁hashを入れてもChampions環境をactionableにしない。
- `resolve_champions_readiness`がsource-to-capability v1 compilationの全13 document、report/artifact digest、stage間hash lineage、counts、blockers、candidate gate、bundle binding、exact fixtureと明示development-record参照を実体から再検証する。
- private tokenを信頼境界にせず、seal attachment時とadapter reset時に同じcompilation substanceを再計算する。直接構築または構築後に差し込んだreadiness-shaped objectも利用時に拒否する。
- fixtureは初期team-preview状態、全HP/PP、状態異常・能力変化・揮発状態・消費・公開・既メガ状態なし、verified species/capability closureを要求する。
- resolver発行sealがないself-declared VERIFIEDは`compiler_readiness_not_resolved`でall-illegalになる。
- 現v1はintake診断専用でdevelopment recordsを生成せず、`ProductionCatalogInput`もverified promotionを拒否する。したがって正規sealを発行できず、ここで検証済みなのは偽装を拒否するfail-closed経路である。positive issuanceはSIM-02B v2の完了条件とする。

### 2. Versioned 6→3 team preview

- 完全setを持つ6体private rosterと、相手に公開するspecies/level/types/slotだけのpreview observationを分離した。
- 双方が相手の選出を知る前にcommitし、両commit後にだけrevealする。
- commitmentはcontract/session/battle/Catalog/RuleSet/player/full-roster hash/ordered selection/128-bit以上nonceへ結合する。
- 順序付き3体を既存の3体`BattleEngine`へ決定論的にmaterializeする。先頭がleadになる。
- 相手のinstance ID、stats、moves、item、ability、HP、選出順はpolicy observationに存在しない。自分のprivate rosterもsession所有graphの参照ではなくdeep-detached copyとして渡し、方策内の強制書換えをcommit/materializeへ伝播させない。
- rosterは全HP/PP、runtime status/stage/volatile/consumed/reveal/mega flagの初期値を強制し、途中状態をteam previewへ混入させない。
- `TeamPreviewProof`はCatalog/RuleSet、complete session、両private roster、materialized state、seed、両selection policyの実クラスsource・live runtime code・型付き初期instance state・設定を結合する。state fingerprintはmapping iteration順とshared-reference alias topologyも保持し、設定に未申告のfield差や選出中のstate変化を拒否する。arena投入前には同じ方策とseedで選出全体を再実行し、選出結果まで照合する。

### 3. Partial-observation competitive baselines

- `TypeCoverageTeamSelectionPolicy`: 相手の公開typesに対し、super-effective coverage数、best multiplier合計、own Speedをlexicographicに比較する。任意重みは置かない。
- `TypeAwareDamagePolicy`: `DecisionRequest`と`PlayerObservation`だけから、power × accuracy × public type effectiveness × STABをexact rationalで比較する。
- ルール、合法手、報酬をLLMへ決めさせず、将来のsearch/RL/LLMと比較する透明なreference baselineに限定する。

### 4. Paired-seat arena and report

- 各engine seedをcandidate P1とcandidate P2の2 legで実行する。
- 第2 legではcandidateの同じteamをP2へremapし、teamとseatの効果を分離する。
- engine RNGとagent RNGを別rootにし、candidate/opponentのrole名で分岐するためseatを交換しても各roleのpolicy RNG streamは同じになる。各legではfresh policy instanceを要求する。
- caller由来のbattle/team instance IDは各legでopaque IDへ正規化する。battle IDはplan/scenarioの公開namespace、pair、legだけから導出し、相手の非公開item/move/statsをhash入力にしない。
- `BoundAgent`はplan上のidentityを実行policyのexact class、class source hash、live runtime code hash、初期policy state、Catalog等の設定へ結合する。表示identity、factory、binding後のmethod差し替えを受理しない。
- runtime identityはMRO上の実効method、class constant、function default/closure/attributeのcanonical内容と、それらを横断するshared-reference topologyを結合し、factory実行後にも再検証する。instance stateはsubject定義`__getattribute__`を通さず実`__dict__`/owner slot descriptorから読む。非canonicalなbehavioral stateは黙認せずbindingを拒否する。
- Arena/Replay/plan/report/state/engineはexact contract型を要求し、多相`__eq__`、subclass observation override、Replay subclassで再実行照合を迂回できない。
- 全battleのReplayをengineで再実行検証した後、同じ`BoundAgent`とplanned agent seedでもう一度方策実行し、selectionを含むReplay全体の一致からreportを再導出する。
- win/draw/loss、terminal utility、seat、seed、Replay/final-state hash、decision/event countからsummaryを再計算する。caller supplied summaryは拒否する。
- reportは常に`scope: synthetic_local`、`champions_candidate: false`、`rank1_equivalence_status: unmeasured`、`rank1_equivalence_claim_allowed: false`を保持する。
- report JSON単体はverified実行証明ではない。完全な再検証には、同じTeamPreviewRun/policiesを再生成し、exact `BoundAgent`、engine、initial state、Replay一式を組み立てた`ArenaRun`を`verify_arena_run`へ渡す。
- policyは同一processで動くため、arenaが完全状態を引数として渡さないことは検証できてもglobal/closure経由の読取までは証明しない。reportは必須blocker `policy_process_isolation_not_implemented`を保持する。
- AI environmentのpolicy-facing snapshot/reset/stepからfull-state、private event、sealed input、engine seed/algorithm、RNG state、fixture identityを除き、privileged Replay lineageと分離した。相手benchのitem/stats/move順、fixture ID、engine seedを同時に変えても、公開観測が同じreset結果はbyte-identicalである。

## 目的変数

```text
paired_net_utility_ppm
  = sign(net utility)
    * floor(abs(candidate wins - candidate losses) * 1,000,000
            / completed matches)
```

Terminal utilityはwin=`+1`、draw=`0`、loss=`-1`、shapingなしである。reportは丸め前の`net_utility_numerator`と`net_utility_denominator`も保存し、ppmは正負で対称に0方向へ切り捨てる。補助変数はpair completeness、legal action、Replay verification、private-state delivery violation、execution error、seat別outcomeである。delivery violationはpolicy process isolationの代替指標ではない。

この値は指定scenario corpus内のexact comparisonであり、母集団勝率、Elo、順位、ランク1到達確率ではない。64 pairという回帰予算は`PD-009`として明示した。

## Frozen synthetic benchmark

- date: `2026-07-14`
- plan: type-coverage selection + type-aware battle versus first-three selection + random legal battle
- pairs / matches: `64 / 128`
- candidate wins / draws / losses: `126 / 0 / 2`
- paired net utility numerator / denominator: `124 / 128`
- paired net utility: `968,750 ppm`
- pair completeness: `1,000,000 ppm`
- legal action rate: `1,000,000 ppm`
- Replay verification: `1,000,000 ppm`
- private-state delivery violations: `0`
- execution errors: `0`
- plan hash: `c1d3e0b303aa109d30cc480b0ddd0f9148a52dcae061613e23ea26fd3c4c82b9`
- prebattle session hash: `1246f8f46aef536125cbfc9508ca3504d9bb9fa9ca3a625a339e7491eb7a6250`
- prebattle proof hash: `943cafe7e65d6ef87e29a426d8ba577ce583019f01f998f4b5bb8f591d0b52fd`
- report hash: `5fe3ac9d5fda0957fc0f4d1d61e17d1994e10959d5f5b40f997d0fd5c76dc2ac`
- Arena evidence hash: `7a7c9bba506f4545f5f48ed5c76eef30c476efc681cd3847c23e7d8d4254b8e2`
- frozen summary: `data/golden/ai01-synthetic-benchmark-v1.json`
- local battle-Replay archive: `runs/ai01/5fe3ac9d5fda0957fc0f4d1d61e17d1994e10959d5f5b40f997d0fd5c76dc2ac/`

126勝2敗と正のutilityはbaselineがRandomではない選択を行い、証明付き配線が機能することのgolden evidenceである。単一fixtureのteam差と相性を含むため、強さの外部証拠としては使用禁止である。

## 検証

- full pytest: `248 passed in 37.13s`
- AI-01 focused suite: `90 passed in 27.28s`
- same sealed inputからbyte-identical Arena report/hash
- plan Catalog/RuleSet/initial-state hash改変拒否
- plan identityと実行policy class/source/state/configの不一致、および未申告selection state・選出中state変化を拒否
- `BoundAgent`の`object.__setattr__`改変・subclass偽装、binding後のbattle/prebattle method monkeypatch、偽`__getattribute__`、class constantのcontainer/scalar alias差替え、scalar subclass、method descriptor/class metadata差替えを拒否
- summary/winner/outcome/pair/seat/seed欠落・改変、およびreport/Replay不一致拒否
- policy instance reuse拒否
- opponent exact HP/max HP/fraction/stats leakage 0
- team-preview commit前後のopponent private set/selection noninterference、detached own-roster graph、途中状態roster拒否、proof改変・別方策・別seed拒否
- selection stateのmapping iteration順・alias topology衝突、未申告field差、選出中state変化を拒否
- team previewの同一policy instance再利用、duplicate held item、Catalog上は存在するが種族非合法な技を拒否
- forged VERIFIED、fake report/artifact hash、candidate flag再署名、missing artifact、SIM-01 disguise、直接または後挿入readiness拒否
- role-fixed policy RNGと既定seat RNGの後方互換
- 負utilityのppm丸めが正値と符号対称
- Arena report recursive Schema validation合格
- frozen 64-pair benchmark再生成合格

## Data and Git policy

- report Schema、小さなgolden summary、testsだけをGit追跡候補にする。
- full Arena report、Replay、将来のtrajectory/model/checkpointは`runs/`、`replays/`等のGitignored pathへ置く。
- CLIはAI-01 outputをrepositoryの`runs/`外へ書かない。
- 通常CLIはreport、全Replay、file SHA-256付きevidence manifestをcontent-addressed `runs/`へ保存する。`--summary-only`だけが非永続サマリである。保存Replayはdiskからstrict loadしてengine再実行する。
- frozen runのローカルarchiveはreport 1、Replay 128、manifest 1の計130 file、約4.83 MBであり、すべて`runs/`配下でGitignoredである。
- 現manifestは`prebattle_evidence_mode: regeneration_required`であり、6体session/commit/reveal/proof本体を内包しない。したがってbattle-Replay archiveであってstandalone Arena認証bundleではない。完全な`verify_arena_run`には同じ選出fixture/policy/seedからprebattle runを再生成する必要があり、この欠落をreport blockerで明示する。
- evidence hashとmanifestは改変検出用のidentityであって認証ではない。process-isolated実行とself-contained prebattle evidenceは未実装である。

## 研究知見との整合

- [Human-Level Competitive Pokémon via Scalable Offline Reinforcement Learning with Transformers](https://rlj.cs.umass.edu/2025/papers/Paper340.html)はfirst-person trajectory、offline RL、self-play fine-tuningを段階化しており、完全状態を方策へ渡さない境界と評価基盤を先に置く方針に整合する。
- [The PokeAgent Challenge](https://arxiv.org/abs/2603.15563)は標準化された評価、trajectory、heuristic/RL/LLM baseline、partial observabilityを中心課題にしており、model実装前にArenaを作る判断を支持する。
- [Evaluating Effectiveness of UCT Algorithms for Pokemon Battles](https://cir.nii.ac.jp/crid/1050292572147120640)ではUCTの単純な優位が示されていないため、次段でもvanilla UCTを既定解にせず、同じArena上で比較する。

これらはアーキテクチャ選択の参考であり、Pokémon Champions固有ルールの正本ではない。

## 残るblocker

1. 実M-B mappingは0 verified、denominator non-final、execution/grounding/holdout未達である。加えてv1自体がintake-onlyなので、証拠を外付けしてreadiness sealへ昇格する正経路がない。
2. 6体roster corpusは単一synthetic fixtureで、実構築分布とregulation変更を代表しない。
3. opponent model、belief state、search、RL、LLM policyは未実装である。
4. 上位人間または同等の固定外部benchmarkによる盲検較正がない。
5. Actual BlueStacks capture/trace、Champions event/rounding conformance、license確認が未完了である。
6. policy process isolationが未実装であり、同一processのglobal/closureを完全には監査できない。

## 次の大きな目的

`SIM-02B Production Catalog Promotion + Evidence-backed Scenario Corpus`を次段とする。

v1を診断専用として凍結し、235 mapping、788 semantic selector、118 execution gapをauthoritative sourceまたはactual traceから再検証するv2 promotion compilerを別型で作る。その同じversion/hash identityから非空development corpusと系譜分離したexternal-holdout scenario corpusを生成し、engine-backed positive probe、grounding、promotion/catalog/scenario/partition/holdout hashまでreadinessへ結合する。resolver sealが発行できるまでは、MCTS/RL/LLMへChampions candidateを渡さない。
