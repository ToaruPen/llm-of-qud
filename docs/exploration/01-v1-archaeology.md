# 01. v1 考古学レポート（Assignment A）

- 対象: `archives/llm-of-qud-v1`（以下 `v1/`）。30 commits、最終コミット `03ebe19`
- 調査日: 2026-09-25
- 調査範囲: `AGENTS.md`、`docs/AGENTS.md`、`docs/architecture-v5.md`（全 3400 行）、`docs/memo/*.md`（全 24 本）、`docs/adr/00*.md`（15 本）、`docs/adr/decision-log.md`、`mod/LLMOfQud/*.cs`（全 4116 行）、`brain/**/*.py`、`tests/*.py`、`harness/policy.yaml`、`git log --stat`。あわせて主要な CoQ 引用を現行の decompile で再確認した
- 読み取り専用で調査した。書き込んだのはこのファイルだけである

## 0. 引用の凡例

v1 は CoQ **BUILD_2_0_210** の decompile を根拠に書かれている（`v1/docs/memo/phase-0-a-exit-2026-04-23.md`）。現行の `/Users/sankenbisha/Dev/coq-decompiled_stable` は `AssemblyVersion("2.0.211.50")` である（`coq-decompiled_stable/Properties/AssemblyInfo.cs:8`）。scratchpad の `decomp-new` はさらに新しく、`2.0.211.56` である（`decomp-new/Properties/AssemblyInfo.cs:8`）。**行番号はほぼすべてずれている**ため、引用は次の 3 種類に分けて書く。

| 表記 | 意味 |
|---|---|
| `v1/<path>:N` | v1 リポジトリ内のファイルと行 |
| `[v1記録] decompiled/<path>.cs:N` | v1 が 2.0.210 について記録した行。**現行の行番号として使ってはいけない** |
| `[再確認] stable/<path>.cs:N` | `coq-decompiled_stable`（2.0.211.50）で今回 grep・目視して確認した行 |
| 「v1記録のみ・未再検証」 | 今回は再確認していない主張 |

推測には必ず **（推測）** と付ける。

---

## TL;DR

1. **v1 が実証したのは「観測」「コマンド発行」「判断境界」「外部プロセスとの同期ブリッジ」までである**。LLM は一度も呼ばれていない。Brain は `canned_decision`（`v1/brain/app.py` の `canned_no_llm`）しか返さず、auth はすべて `Phase2aAuthUnavailableError` を投げる（`v1/brain/auth/device_flow.py:17-38`）。
2. **v5.9 の 11 ツールは 1 つも実装されていない**。C# 側の `ToolRouter` は terminal ツール（`execute`/`navigate_to`/`choose`）を**ゲームに何もせず `accepted` と返す**（`v1/mod/LLMOfQud/ToolRouter.cs:105-112`、`:1079-1111`）。それ以外のツールは `unknown_tool` になる（`:115-121`）。PR-3 の冪等性層は、中身が no-op の関数を包んでいるだけである。
3. CoQ 内部についての実証知見は価値が高く、2.0.211.50 でも**仕組みとしては維持されている**。例として、tile モードでは `_Char` が空になり `BackupChar` にグリフが退避されること、`ConsoleChar.Copy` が `BackupChar` を落とすこと、AfterRenderCallback から読めば復元できること、`CommandEvent.Send("CmdMoveE")` が no-op であること、CTA フックと 3 層エネルギードレイン、`SkipPlayerTurn` と `KeyEvent.Set` による wake がある。ただし行番号は全面的に変わっている（§2.3）。
4. コストは明らかに偏っている。追加行数で比べると docs は 26,443 行、プロダクトコード（mod と brain）は 5,935 行で、約 **4.5:1** である。ADR は 15 本、decision record は 44 件、仕様レビューは Pro 6 回と Codex 5 回に及んだ。PR-3 は、ToolRouter の差分 236 行に対して計画書が 1,063 行ある。
5. 停止点は Phase 1 PR-3 の直後で、Phase 2a（LLM 統合）には着手していない。実作業は 2026-04-24〜04-30 に集中しており、PR-3 のコミット日は 2026-07-04 である。

---

## 1. v5.9 アーキテクチャ要約と、実装済みか仕様のみか

### 1.1 全体像

- 目的は「Claude Plays Pokemon」型の配信である。KPI は停止しない分数で、停止 15s が視聴者の許容限界、30s で致命的とされる（`v1/docs/architecture-v5.md:137-167`）。先行例の記事は https://michaelyliu6.github.io/posts/claude-plays-pokemon/ （v1 の `memory-architecture-research.md` が引用）。
- 構成は 3 層である。LLM（gpt-5.4 を想定）、Python Brain（`localhost:4040` の WebSocket サーバ）、C# MOD（CoQ が Roslyn で in-process コンパイルする）からなる（`v1/docs/architecture-v5.md:172-197`）。
- C# MOD はビルド済み DLL を使わず、`.cs` を CoQ 起動時に Roslyn でコンパイルする（`[v1記録] decompiled/XRL/ModManager.cs:417-464`、`decompiled/XRL/ModInfo.cs:757-823`、`v1/mod/AGENTS.md`）。

### 1.2 要素ごとの実装状況

| 要素 | v5.9 仕様（行） | v1 実装 | 状態 |
|---|---|---|---|
| ブートストラップ（`[PlayerMutator]` から `RequireSystem`） | 1710-1804 | `v1/mod/LLMOfQud/LLMOfQudBootstrap.cs:6-12` | **実装済・実証済** |
| `IPlayerSystem` と BTA 購読 | 1710-1804 | `LLMOfQudSystem.cs:134-166` | **実装済** |
| ターンパイプライン（BTA で観測、CTA で行動） | 199-221 | `LLMOfQudSystem.cs:174-283`（BTA）、`:441-707`（CTA） | **実装済**（仕様の Path A/B/C とは異なる形） |
| Path A/B/C（通常、AutoAct、Modal） | 223-253 | なし | **仕様のみ** |
| フォールバックチェーンと State×Fallback 表 | 255-316 | CTA 内の 3 層ドレイン、timeout 時の explore、disconnect 時の pause のみ | **部分的・別物** |
| AutoAct による bounded autonomy | 318-323 | なし | **仕様のみ** |
| 11 ツール（inspect_surroundings … cancel_or_back） | 329-346 | なし（`ToolRouter` は terminal 3 種を no-op で accept し、他は `unknown_tool`） | **仕様のみ** |
| 状況別の `allowed_tools` | 350-362 | なし | **仕様のみ** |
| `inspect_surroundings` の 21×21 ASCII と可視フィルタ | 399-441 | `[screen]` に全画面 ASCII をログ出力（`LLMOfQudSystem.cs:716-806`）。`[state]` に可視エンティティ（`SnapshotState.cs:208-275`）。**ツールではなくログ** | **観測の土台のみ** |
| navigate_to（AutoAct の "M"/"P" と `TryToMove` の Harmony prefix） | 550-613 | なし。Harmony パッチは 0 件 | **仕様のみ** |
| Modal スキーマと `fallback_choice_id` | 715-790 | なし | **仕様のみ** |
| request_candidates / execute（candidate_set_id、hidden score） | 791-903 | なし（`snapshot_hash` の照合だけが実装済） | **仕様のみ** |
| CONFIRM 契約と SafetyGate（BLOCK/CONFIRM/WARN/PASS） | 905-943、1806-1827 | `safety_decision` は `"pass"`/`"block"` の**文字列リテラル**（`ToolRouter.cs:1108`） | **仕様のみ** |
| Notes（固定 7 キー）と Active memory（約 400 tok） | 945-1020、1389-1706 | なし | **仕様のみ** |
| 品質シグナル（net_value、risk_delta、死亡分類） | 1161-1385 | なし | **仕様のみ** |
| FTS5 archive、goal ledger、admission control | 1389-1706 | なし | **仕様のみ** |
| SQLite DDL（death_events、build_runs、encounter_log、tool_calls、action_outcomes、notes_history、note_evidence） | 1389-1706 | 実在するのは transport 系 9 テーブルだけ（`connection_lifecycle`、`decision_request`、`decision_response`、`disconnect_pause`、`reconnect_wake`、`tool_call_sent`、`tool_call_received`、`supervisor_request`、`supervisor_response`。`v1/brain/db/schema.py:17-115`）。しかも `app.py` から import されておらず**未配線**（`grep "db\|Telemetry" brain/app.py` の結果は 0 件） | **ゲームプレイ系は仕様のみ** |
| tool_loop（MAX_TOOL_CALLS=8、TIMEOUT=10s、FORCE_ACTION_AFTER=6、previous_response_id） | 1885-2201 | なし | **仕様のみ** |
| Loop breaker、モデル選択、レイテンシ予算 | 2203-2245 | なし | **仕様のみ** |
| 配信 overlay（localhost:8080） | 2249-2358 | なし（`brain/overlay/` は存在しない） | **仕様のみ** |
| プロトコル: session_start/ack/end | 2362-2733 | なし。`session_epoch` は **1 に固定**（`ToolRouter.cs:21`、`app.py:47`） | **仕様のみ** |
| プロトコル: tool_call/tool_result の envelope | 2399-2505 | 実装済（`brain/protocol.py:77-112`、`ToolRouter.cs:218-345`）。`call_id` を正とする（ADR 0016） | **実装済（envelope のみ）** |
| プロトコル: terminal 冪等性 | 2634-2677 | 実装済（`ToolRouter.cs:51-113`、ADR 0017） | **実装済（中身は no-op）** |
| supervisor_request/response | 2362-2733 | Python→C# の `resume` 応答ヘルパだけ（`ToolRouter.cs:253-293`）。C# が受信すると `DisconnectedException` になる（`BrainClient.cs:323-330`） | **骨格のみ** |
| turn_start、`game_state` 優先度（Modal > Combat > Navigation > Idle） | 2362-2733 | なし。代わりに独自の `decision_input.v1` を使う | **仕様のみ** |
| AutoAct の割り込み分類 | 2362-2733 | なし | **仕様のみ** |
| Codex 認証（device flow） | 3165-3181 | スキャフォールドのみ。すべて `Phase2aAuthUnavailableError` を投げる | **仕様のみ** |

### 1.3 実際に動いていたターンループ（v1 最終形）

1. **BTA（ゲームスレッド）**: `HandleEvent(BeginTakeActionEvent)` が `[state]`、`[caps]`、`[build]` の JSON を作り、`PendingSnapshot` に 1 オブジェクトとしてまとめる。これを `Interlocked.Exchange` で公開する（`v1/mod/LLMOfQud/LLMOfQudSystem.cs:174-283`）。
2. **レンダースレッド**: `AfterRenderCallback` がスナップショットを取り出して null にし、`[screen]`（ASCII 全画面）、`[state]`、`[caps]`、`[build]` を `Player.log` に書く（`:774-854`）。
3. **CTA（ゲームスレッド）**: `HandleEvent(CommandTakeActionEvent)` の流れは次の通り（`:441-707`）。
   1. `BuildDecisionInput` が HP、位置、隣接する敵、セルごとの blocked dirs、直前の行動を集める。
   2. `WebSocketPolicy.Decide` が、ワーカースレッドに要求を積んで最大 500ms ブロックする（`WebSocketPolicy.cs:25,49-81`）。
   3. `[decision]` を出力する。
   4. `Move` か `AttackDirection` を実行する。失敗したら `PassTurn`、それでも駄目なら `Energy.BaseValue=0` にする（3 層ドレイン）。
   5. `[cmd]` を出力する。
4. **Brain の往復**: ワーカースレッド上の `ReceiveDecision` が `tool_call` を受けるたびに `ToolRouter.Dispatch` で `tool_result` を返し、最終的な decision を受けたところで戻る（`BrainClient.cs:316-342`）。
5. **障害時の方針**:
   - 切断すると `DisconnectedException` になり、`[disconnect_pause]` だけを出して行動しない。エネルギーは 1000 以上のままなので、ネイティブの `PlayerTurn` の idle wait に入る（`LLMOfQudSystem.cs:632-648`、ADR 0011 Q3）。
   - 再接続すると `SkipPlayerTurn` と `Keyboard.KeyEvent.Set()` で起こす（`:76-120`）。
   - **timeout（500ms）では pause せず、heuristic の explore Move を返す**（`WebSocketPolicy.cs:60-63,83-93`）。これは PR-1 の Probe 2/3a で意図的に決めた設計である（`v1/docs/superpowers/plans/2026-04-27-phase-1-pr-1-websocket-bridge.md:211-226`）。

### 1.4 判断境界の実物（`decision_input.v1` / `decision.v1`）

- 入力は `Turn`、`Player{Hp,MaxHp,Pos{X,Y,Zone}}`、`Adjacent{HostileDir,HostileId,BlockedDirs}`、`Recent{LastActionTurn,LastAction,LastDir,LastResult}` だけである（`v1/mod/LLMOfQud/IDecisionPolicy.cs:5-41`）。
- 出力の `Action` は `Move` か `AttackDirection` に限られ、`Intent` は `attack`、`escape`、`explore` のいずれかである（`:43-56`）。`PassTurn`、待機、アイテム、アビリティ、会話は**スキーマ上で表現できない**。
- `Decide` は CoQ API に触れてはならない。これは grep によるプローブで強制されている（`:58-60`）。
- **（推測）** この境界は LLM に何を見せるかを決めるものではない。v1 自身が認めているように、heuristic bot に合わせた暫定境界である（ADR 0009 と ADR 0010）。

### 1.5 Phase 計画と到達点

- v5.9 は Phase 0-A〜0-I、0b、1、2a、2b、3、4、5 の順で計画していた（`v1/docs/architecture-v5.md:2736-3055`）。
  - 0-H は「TurnSnapshot DTO + snapshot_hash prototype」、0-I は「snapshot fixture + one replay smoke」とされていた（`:2821-2825`）。
- 実際には 0-A から 0-G まで進み、そのあと Phase 1 の PR-1/2/3 に移った。
  - **0-H と 0-I は独立した ADR なしに飛ばされている**。`snapshot_hash` は PR-3 で SHA-256 over decision-input bytes として部分的に実現した（`BrainClient.cs:349-361`）。
  - C# テストハーネスは ADR 0004 で Phase 2a/2b に先送りされた（`v1/docs/adr/0004-phase-0-c-csharp-test-infra-deferral.md:89`）。
  - replay smoke は存在しない。
- Phase 0 の exit 基準は「Warden で 50 ターン、5 回中 3 回」と「観測一致」であり、0-G で達成した（`v1/docs/memo/phase-0-g-exit-2026-04-27.md`）。First Demo の条件（30 分、`agency_share_llm` > 50%）は未達で、未着手である。

---

## 2. CoQ 内部について v1 が確立した実証知見

### 2.1 知見の一覧

「実証手段」のうち「in-game」は、手動で起動して `Player.log` を解析した実測を指す。

| # | 知見 | 実証手段 | v1 が記録した根拠 | 2.0.211.50 での状態 |
|---|---|---|---|---|
| K1 | Mod は Roslyn でソースからコンパイルされる。DLL はどの経路でもロードされない。manifest には entry assembly のフィールドがない | decompile 読解と in-game のビルドログ（`^Compiling \d+ files?\.\.\.$`） | `[v1記録] decompiled/XRL/ModManager.cs:417-464`、`ModInfo.cs:478-481,757-823`、`ModManifest.cs` | `[再確認] stable/XRL/ModManager.cs:115-135`。`GetCompilerService` は `MainAssemblyPredicate` を満たすロード済みアセンブリをすべて参照に加え、`BUILD_x_y_z` シンボルを define する。`:389-410` |
| K2 | `[PlayerMutator]` と `IPlayerMutator.mutate` から `RequireSystem<T>()` を呼ぶのが最小の起動方法 | in-game（0-A） | `[v1記録] PlayerMutator.cs:5-6`、`IPlayerMutator.cs:5-7`、`XRLGame.cs:311-322` | v1記録のみ・未再検証 |
| K3 | BTA はオブジェクトレベルのイベントである。`IPlayerSystem.RegisterPlayer` で `Registrar.Register(SingletonEvent<BeginTakeActionEvent>.ID)` を明示しないと届かない | decompile と in-game | `[v1記録] BeginTakeActionEvent.cs:37-52`、`WanderSystem.cs:57-60` | v1記録のみ・未再検証 |
| K4 | ログの行き先。`MetricsManager.LogInfo` は `~/Library/Logs/Freehold Games/CavesOfQud/Player.log`、`Logger.buildLog` は `$COQ_SAVE_DIR/build_log.txt` に書かれる。Kitfox 時代のパスは解決しない。複数行の `LogInfo` では `INFO - ` が先頭行にしか付かない | in-game | `[v1記録] MetricsManager.cs:407-409`、`Logger.cs:16,32`、`XRLCore.cs:430,436,3514` | v1記録のみ・未再検証 |
| K5 | **tile モードでは描画元のバッファで `_Char` が `'\0'` になり、グリフは `BackupChar` に退避される** | 0-B で tile モードのログが空白になったことから逆算し、decompile で特定 | `[v1記録] decompiled/XRL.World/Zone.cs:5411-5418`（唯一の writer は `:5414`） | **場所が移った**。`[再確認] stable/XRL.World/Zone.cs:5743` が `consoleChar.Set(renderEvent)` を呼び、`stable/ConsoleLib.Console/ConsoleChar.cs:400-418` で `_Tile != null` なら `_Char='\0'; BackupChar=RenderString[0]` となる。仕組みは同じ |
| K6 | **`ConsoleChar.Copy` は `BackupChar` をコピーしない**。したがって `DrawBuffer` 後の `CurrentBuffer` や scrap buffer からはグリフを復元できない | decompile と in-game | `[v1記録] ConsoleChar.cs:385-400`、`TextConsole.cs:149-153`、`ScreenBuffer.cs:291-308` | `[再確認] stable/ConsoleLib.Console/ConsoleChar.cs:360-375`（`BackupChar` の代入がない）、`TextConsole.cs:142,153`（`DrawBuffer` → `CurrentBuffer.Copy(Buffer)`）、`ScreenBuffer.cs:303-314`（セル単位の `Copy`） |
| K7 | **`XRLCore.RegisterAfterRenderCallback` で描画元バッファを受け取れば、`_Char`、`BackupChar`、空白の順にフォールバックして全グリフを復元できる**。95 ターンで BEGIN/END/ERROR が 95/95/0、1 スナップショット約 2KB、ターン 1〜4 は chargen 境界で空白 | in-game（0-B）、ADR 0002 | `[v1記録] XRLCore.cs:624-626`、呼び出し箇所は `:2347-2351,2380-2383,2423-2426` | `[再確認] stable/XRL.Core/XRLCore.cs:652-654`（Register）、呼び出し箇所は `:2430-2432,2462-2464,2506-2508` |
| K8 | スレッドの規則。CoQ の状態はゲームスレッドで読み、レンダースレッドは文字列を出力するだけにする。受け渡しは 1 オブジェクトの `Interlocked.Exchange` で行う。`display_mode` もゲームスレッド側で取得する（0-C で不一致を修正） | in-game（0-C、110 ターン） | `v1/docs/architecture-v5.md:1787-1794`、`LLMOfQudSystem.cs:24-30,184-189` | 設計上の規則なので、decompile の再確認は対象外 |
| K9 | 内部 API から得られる状態。`hitpoints`/`baseHitpoints`、`ZoneID`、`GetObjects()` は**全オブジェクトを返す**ので `IsVisible()` でふるいにかける必要がある。エンティティのゲート（`Brain != null`、`Combat` を持つ、`baseHitpoints > 0` のいずれか）は緩く、watervine のような植物も通る。1 ターン目は 130 体、通常は 56 体で約 5KB、全チャネル合計で約 18.7KB/ターン | in-game（0-C） | `[v1記録] Zone.cs:388-398,1982-2010`、`GameObject.cs:766,1177-1213,2972-2986,10887-10894` | `[再確認] stable/XRL.World/Zone.cs:3612`（`GetObjects`）、`GameObject.cs:3718`（`DistanceTo`）、`:11413`（`IsHostileTowards`） |
| K10 | 能力の観測。`BaseMutation.DisplayName` は `[Obsolete]` で CS0618 が出るので `GetDisplayName(WithAnnotations:false)` を使う。`ActivatedAbilityEntry.Visible` は実測では常に false。`BodyPart.ID` の getter は遅延採番するので、`HasID()` を確認してから読む。クールダウンは実測で一度も動かなかった | in-game（0-D、112 ターン） | `[v1記録] BaseMutation.cs:71-83,166-185`、`ActivatedAbilityEntry.cs:195,259-308`、`BodyPart.cs:365-381,438-440` | `[再確認] stable/XRL.World.Parts/ActivatedAbilityEntry.cs:195`（`Visible => Flags.HasBit(2)`）。他は未再検証 |
| K11 | ビルドの観測。`IsTrueKin`/`IsMutant`、`GetGenotype`/`GetSubtype`、`Statistic.Value`（補正込み）、`Stomach.FoodStatus`/`WaterStatus` は `{{C\|..}}` マークアップを除去して正規化する。**`_beginTurnCount` はキャラクターごとに 0 に戻る**（chargen 時と、ロード後の再登録時） | in-game（0-E、True Kin と Mutant で 160 ターン） | `[v1記録] GameObject.cs:642,4373-4383,10019-10036`、`Statistic.cs:51-53,238-252`、`Stomach.cs:87-143` | v1記録のみ・未再検証。セーブ/ロードは**未テスト** |
| K12 | **`CommandEvent.Send("CmdMoveE")` は何もしない**。移動は `XRLCore.PlayerTurn` 内の switch が直接 `AutoAct.ClearAutoMoveStop()` と `The.Player.Move("E")` を呼んでいる | in-game（0-F Step A で失敗）、ADR 0006 | `[v1記録] XRLCore.cs:1107-1109,1270-1271` | `[再確認] stable/XRL.Core/XRLCore.cs:1167-1169`（`case "CmdMoveE": AutoAct.ClearAutoMoveStop(); The.Player.Move("E");`） |
| K13 | 行動は `GameObject.Move(dir, DoConfirmations:false)` と `AttackDirection(dir)` を直接呼ぶ。戻り値 false でもエネルギーが消費されない場合があるので、`PassTurn` → `Energy.BaseValue=0` の 3 層でドレインする。エネルギーは負にもなる。505 件の `[cmd]` のうち東への連続移動 79 回、攻撃 15 回で命中 11 回 | in-game（0-F） | `[v1記録] GameObject.cs:15719,17882`、`Combat.cs:794-798,877-889` | `[再確認] stable/XRL.World/GameObject.cs:16223`（`Move`）、`:18386`（`AttackDirection`）、`:18047`（`PassTurn`） |
| K14 | **行動のフックは CTA が正しい**。BTA でドレインすると内側ループのゲートを通らず、EndAction、敵の割り込み、AutoAct、描画のフォールバックが飛ばされる。CTA で `PreventAction=true` にすると `CTA.Check` が false になって `continue` し、**描画のフォールバックも飛ぶ**（488 ターンで描画チャネルが 0 件）。そのため `PreventAction` は異常なエネルギーの保険に限定した | in-game（0-F）、ADR 0006/0007 | `[v1記録] ActionManager.cs:786-800,829-832,838,1797-1799,1806-1808`、`CommandTakeActionEvent.cs:37-39` | `[再確認] stable/XRL.Core/ActionManager.cs:741-743`（BTA の Check）、`:755`（内側 while）、`:789-791`（CTA → continue）、`:798`（プレイヤーのエネルギーゲート）、`:1593,1602`（`PlayerTurn`）、`:1609-1611`（`RenderBase` のフォールバック）、`stable/XRL.World/CommandTakeActionEvent.cs:37-38` |
| K15 | 自動でコマンドを出すとエンジン速度で進み、数秒で 4 ゾーンを横断する。観測も配信も追いつかない（**配信には throttle が必須**） | in-game（0-F） | `v1/docs/memo/phase-0-f-exit-2026-04-26.md` | 実測知見なので decompile の再確認は対象外 |
| K16 | 隣接する敵の走査には `Cell.GetCellFromDirection(dir, BuiltOnly:false)` と `GetCombatTarget(Phase:5, AllowInanimate:false, Filter: IsHostileTowards)` を使う。これは `Combat.AttackCell` のフィルタに倣っている | in-game（0-F/0-G） | `[v1記録] Cell.cs:7322,8511-8557`、`Combat.cs:877-889` | `[再確認] stable/XRL.World/Cell.cs:8007`（`GetCellFromDirection`）、`:9196`（`GetCombatTarget`） |
| K17 | heuristic の結果。5 回中 4 回 PASS し、Run 2 の失敗はセル単位の blocked-dir 記憶で解消した。U 字の袋小路で振動し、Run 5 ではターンの 96.4% を消費した。ベースラインは 9,919 ターン中 pass_turn が 98.7% | in-game（0-G） | `v1/docs/memo/phase-0-g-exit-2026-04-27.md`、ADR 0009 | 対象外 |
| K18 | `IGameSystem` は `[Serializable]` で、セーブ時に保存され、ロード時に `AfterLoad` が呼ばれる。そのためソケットやスレッドは `[NonSerialized]` にして `AfterLoad` で作り直す | decompile（**in-game のセーブ/ロード実測はない**） | `[v1記録] IGameSystem.cs:11-12`、`XRLGame.cs:1573-1582,1818-1821` | `[再確認] stable/XRL/IGameSystem.cs:11-12` |
| K19 | **外部プロセスとの同期ブリッジが成立する**。専用スレッドの `ClientWebSocket` で `ws://localhost:4040` に繋ぎ、CTA がブロッキングで待つ。往復の中央値 0ms、p95 1ms、最大 78ms。受け入れ試験は 4 本（137、2834、2399、2399 ターン）で、各 1 回ずつ切断から pause、wake まで確認した | in-game（PR-1） | `v1/docs/memo/phase-1-pr-1-acceptance-progress-2026-04-29.md`、`BrainClient.cs:145-213` | `ClientWebSocket` が Roslyn でのコンパイル時に参照できることは in-game で実証済み |
| K20 | **wake は `Keyboard.PushKey` ではなく、`ActionManager.SkipPlayerTurn = true` と `Keyboard.KeyEvent.Set()` の組み合わせにする**（キー入力を注入せずに `IdleWait` を抜けられる） | in-game（PR-1） | `[v1記録] XRLCore.cs:2307-2315`、`Keyboard.cs:911-939`、`ThreadTaskQueue.cs:102-103` | `[再確認] stable/XRL.Core/XRLCore.cs:2390-2396`（`IdleWait` → `SkipPlayerTurn` なら break）、`stable/ConsoleLib.Console/Keyboard.cs:110`（`KeyEvent`）、`stable/GameManager.cs:148,150`（`uiQueue`/`gameQueue`） |
| K21 | `awaitTask` は相手のキューが pump できない状態で呼ぶとデッドロックする | decompile | `[v1記録] ThreadTaskQueue.cs:135-155` | `[再確認] stable/QupKit/ThreadTaskQueue.cs:135`（`awaitTask`） |
| K22 | 終了時に `ThreadAbortException` が出て、`[state]` の ERROR が記録される | in-game（0-G） | `phase-0-g-exit` | **（推測）** `[再確認] stable/ConsoleLib.Console/TextConsole.cs:144-147` にある `Keyboard.Closed` 時の `Thread.CurrentThread.Abort()` が原因と思われる |
| K23 | modal 系の仕様上の知見（**実装も実測もない**）。旧来の `Popup:*` は `Keyboard.PushKey`、新しい `PopupMessage` は `uiQueue` 経由で操作する。`ConversationUI.CurrentChoices`/`Select(int)` がある。`Popup.Suppress` は `ShowYesNo` には効かない | decompile と Codex レビューのみ | `[v1記録] Popup.cs:823-909`、`PopupMessage.cs:876-879` | v1記録のみ・未再検証 |
| K24 | `ArePerceptibleHostilesNearby` が AutoAct の割り込み判定の中心であり、AutoAct の中断理由は空になることが多い | decompile のみ | `[v1記録] GameObject.cs:11138`、`AutoAct.cs:130-135`、`ActionManager.cs:850-857,949-957` | `[再確認] stable/XRL.World/GameObject.cs:11643`、`stable/XRL.Core/ActionManager.cs:794-796`（CTA 直後の `AutoAct.CheckHostileInterrupt`） |
| K25 | `navigate_to` 用の `AutoAct.TryToMove`（10 引数）に Harmony prefix を当てて `AllowDigging=false` を強制する（**仕様のみ**） | decompile のみ | `[v1記録] AutoAct.cs:465` | `[再確認] stable/XRL.World.Capabilities/AutoAct.cs:815`（`ref LastDoor` 付きの 10 引数）、`:963`（9 引数）。**シグネチャが変わった**ので、prefix の対象を選び直す必要がある |
| K26 | ヘッドレスモードはない。CLI 引数はあるが、自動 E2E は困難である。NUnit のテストファイルが 11 本 decompile に含まれ、`Assembly-CSharp.dll` は参照できる | 調査のみ | `[v1記録] GameManager.cs:785`、`XRLCore.cs:3515`、`v1/docs/memo/test-strategy-codex-research-2026-04-23.md` | `stable/XRL.Tests/` が存在することを確認（`VersionTests.cs` など） |
| K27 | 戦闘の RNG は `GetWorldSeed` とは別系統なので、seed を固定しても再現できない | v1 の主張。v1 の文書に decompile の行の引用はない | `v1/docs/architecture-v5.md:3059-3161`、`v3.2-revision-plan.md` | **部分的に確認**。`[再確認] stable/XRL.Rules/Stat.cs:26-36` にシードなしの `new Random()` による静的 RNG（`Rand`、`_Rnd`、`Rnd2`、`Rnd4`、`Rnd5` など）がある。一方、`:101-109` の `ReseedFrom` は `GetWorldSeed` から再シードする（`stable/XRL/XRLGame.cs:1505`）。戦闘がどの RNG を使い、いつ再シードされるかは未検証 |

### 2.2 v1 が引用を管理した方法

- AGENTS の筆頭命令は「Verify, never guess」で、`decompiled/<path>.cs:<line>` の形で引用することを義務づけていた（`v1/AGENTS.md` Imperatives 1）。コード中のコメントにも逐一 `decompiled/...:N` が書かれている（例: `LLMOfQudSystem.cs:155-156`、`SnapshotState.cs:142-146`）。
- decompile の実体（`decompiled/`、519 エントリ）は gitignore されていた。CodeRabbit にもこの規約を教えていた（`59978dd`）。
- **（推測）** この方式は、ゲームがアップデートされると引用がすべて腐る。2.0.210 から 2.0.211.50 への更新で、確認した引用のほぼ全部の行番号がずれた（§2.3）。新プロジェクトでは、行番号よりもシンボル名と短いシグネチャを主キーにして引用した方がよい。

### 2.3 行番号ドリフト表（2.0.210 → 2.0.211.50）

| シンボル | v1 記録 | 2.0.211.50 |
|---|---|---|
| BTA の Check とエネルギーゲート | `ActionManager.cs:786-800` | `ActionManager.cs:741-743` |
| CTA の Check から continue | `ActionManager.cs:829-832` | `ActionManager.cs:789-791` |
| プレイヤーのエネルギーゲート | `ActionManager.cs:838` | `ActionManager.cs:798` |
| `PlayerTurn` の呼び出し | `ActionManager.cs:1797-1799` | `ActionManager.cs:1593,1602` |
| 描画フォールバック `RenderBase` | `ActionManager.cs:1806-1808` | `ActionManager.cs:1609-1611` |
| `RegisterAfterRenderCallback` | `XRLCore.cs:624-626` | `XRLCore.cs:652-654` |
| AfterRender の呼び出し箇所 | `XRLCore.cs:2347-2351,2380-2383,2423-2426` | `XRLCore.cs:2430-2432,2462-2464,2506-2508` |
| `IdleWait` から `SkipPlayerTurn` | `XRLCore.cs:2307-2315` | `XRLCore.cs:2390-2396` |
| `CmdMoveE` の switch | `XRLCore.cs:1107-1109` | `XRLCore.cs:1167-1169` |
| tile 時の `_Char` 消去と `BackupChar` 退避 | `Zone.cs:5411-5418` | `Zone.cs:5743` → `ConsoleChar.cs:400-418`（**移動**） |
| `ConsoleChar.Copy` | `ConsoleChar.cs:385-400` | `ConsoleChar.cs:360-375` |
| `ScreenBuffer.Copy` | `ScreenBuffer.cs:291-308` | `ScreenBuffer.cs:303-314` |
| `GameObject.Move` | `GameObject.cs:15719` | `GameObject.cs:16223` |
| `GameObject.AttackDirection` | `GameObject.cs:17882` | `GameObject.cs:18386` |
| `IsHostileTowards` | `GameObject.cs:10887-10894` | `GameObject.cs:11413` |
| `DistanceTo(GameObject)` | `GameObject.cs:2972-2986` | `GameObject.cs:3718` |
| `ArePerceptibleHostilesNearby` | `GameObject.cs:11138` | `GameObject.cs:11643` |
| `Cell.GetCellFromDirection` | `Cell.cs:7322` | `Cell.cs:8007` |
| `Cell.GetCombatTarget` | `Cell.cs:8511` | `Cell.cs:9196` |
| `Zone.GetObjects()` | `Zone.cs:1982` | `Zone.cs:3612` |
| `AutoAct.TryToMove`（10 引数） | `AutoAct.cs:465` | `AutoAct.cs:815`（シグネチャ変更） |
| `gameQueue`/`uiQueue` | `GameManager.cs:142-144` | `GameManager.cs:148,150` |
| `IGameSystem` の `[Serializable]` | `IGameSystem.cs:11-12` | 同じ |
| `ActivatedAbilityEntry.Visible` | `ActivatedAbilityEntry.cs:195` | 同じ |
| `CommandTakeActionEvent.PreventAction` の判定 | `CommandTakeActionEvent.cs:37-39` | `CommandTakeActionEvent.cs:37-38` |

`decomp-new`（2.0.211.56）とのドリフトは確認していない（§6 の Q1）。

---

## 3. 摩擦とコスト（定量）

### 3.1 期間と速度

| 指標 | 値 | 根拠 |
|---|---|---|
| コミット数 | 30 | `git log` |
| 最初のコミット | 2026-03-19 `d3ba763`（architecture v3.4 の docs） | `git log` |
| 実装コミットの期間 | **2026-04-24〜04-29 の 6 日間**（0-A から PR-2 まで） | `git log --date=short` |
| PR-3 の日付 | E2E メモは 2026-04-30、ADR 0017 の Accepted は 2026-05-21、コミットは **2026-07-04**（author date と commit date が同じ）。assignment の記述にある「2026-05-21」は ADR 0017 の Accepted 日付で、最終コミット日ではない | `v1/docs/memo/phase-1-pr-3-e2e-acceptance-2026-04-30.md`、`v1/docs/adr/0017-...md:3`、`git log --format=%ad/%cd` |
| 機能コミット | 10 本（0-A〜0-G、PR-1〜3） | `git log` |
| 準備だけの docs PR | 7 本（#7、#11、#13、#15、#16、#18、#19） | `git log` |
| CI/chore コミット | 12 本 | `git log` |

### 3.2 追加行数（`git log --numstat` の合計）

| 区分 | 追加 | 削除 |
|---|---:|---:|
| `docs/superpowers`（plans と specs） | 12,845 | 1,581 |
| `docs/` のその他（主に architecture） | 5,726 | 1,840 |
| `docs/memo` | 4,684 | 18 |
| `docs/adr` | 3,188 | 12 |
| **docs 小計** | **26,443** | |
| `mod/`（C#） | 4,354 | 133 |
| `brain/`（Python） | 1,581 | 23 |
| **プロダクトコード小計** | **5,935** | |
| `tests/` | 2,351 | 19 |
| CI とガバナンス（`.github`、`scripts`、`harness`、`agents`、lint 設定） | 2,606 | 77 |

- docs とプロダクトコードの比は約 **4.5:1** である。
- 現在のファイルの行数は、architecture 3,400、plans と specs 11,264（13 本）、memo 4,666（24 本）、ADR 2,579（15 本）である。decision record は 44 件で、`adr_required=true` が 18 件、`false` が 26 件ある（`v1/docs/adr/decision-log.md`）。
- フェーズごとの計画書の行数は次の通り。
  - 0-D: 1,452 行。同じコミットでの C# 追加は +440 行（`git show --numstat 9a9a3cf`）
  - 0-F: 1,856 行（`715caf5` で追加）。実装コミット `9ab3036` での C# 追加は +362 行
  - PR-3: **1,063 行**に対して `ToolRouter.cs` の差分は +236 行（`git show --stat 03ebe19`）

### 3.3 レビューとガバナンスの負荷

- 仕様の段階で ChatGPT Pro のレビューを 6 回、Codex のレビューを 5 回（v5.4〜v5.8）行った。must-fix の件数は 6、3、2、2、1 と推移した（`v1/docs/memo/v5.4〜v5.8-codex-review-*.md`）。v5.4 のきっかけは、Cavendish 経由の Pro レビュー 2 回が約 90 分後に「Thinking failed」で落ちたことである。
- ADR トリガーは pre-commit と pre-push フックで機械的に強制されていた。`scripts/`、`harness/`、`docs/adr/`、`pyproject.toml`、`package.json` を変更するたびに decision record が必要だった（`v1/docs/AGENTS.md`）。
- decision record 44 件のうち 26 件（59%）が `adr_required=false` である。その内訳は次の通り（`v1/docs/adr/decision-log.md` の件名で分類）。
  - CI やリポジトリの初期整備、push の集約: 5 件
  - **CodeRabbit、Codex、Devin、markdownlint の指摘への文書修正**: 19 件。節の順序、引用表記の正規化、MD lint、契約文言の厳密化などで、44 件全体の **43%** を占める
  - コードの修正（Devin の指摘で `HeuristicPolicy` に `[Serializable]` を付けた）: 1 件
  - exit memo のプレースホルダ解消: 1 件
- PR-G1.5 だけで Codex のフォローアップが 5 巡した（round 1 から round-6 まで）。
- **仕様凍結が硬直していた**。`architecture-v5.md` と plans は ADR なしに変更できなかった（`v1/AGENTS.md` Imperatives 2）。15 本の ADR のうち、少なくとも 0002、0005、0006、0007、0009 の 5 本は凍結した仕様を実測結果に合わせて**覆すか再解釈する**ためのものだった。
  - 0002: `GetScrapBuffer1` から AfterRender への転換
  - 0005: BirthBuild から current build への転換
  - 0006: `CommandEvent.Send` から直接呼び出しへの転換
  - 0007: `PreventAction` の範囲限定
  - 0009: heuristic bot から判断境界への rescope
- 0013 と 0014 は番号を予約したまま**書かれなかった**（ADR 0012 が予約）。
- 0010 は「探索の質は non-goal」とする ADR で、ユーザーの発言「LLMが操作するハーネスの基盤作りをしているのであって、自動で探索する bot を作成しているわけではない」を引用している。Status は **Proposed のまま**である。
- CI は 6 ワークフローを持ち、required-checks-gate、semgrep、secretlint、CodeRabbit を含んでいた。一方で、**C# の CI は csproj がないので常に skip される**（`v1/.github/workflows/ci-cs.yml:23-31`）。C# のコンパイルは、ゲームを起動したときにしか検証されない。
- C# のテスト 36 件はすべて **grep ベースの静的契約テスト**で、ソース文字列を検査するだけである（`v1/tests/test_mod_static_contracts.py`）。C# のロジックを実行するテストは 0 件である（ADR 0004 で先送り）。pytest の関数は合計 100 件ある。

### 3.4 実測・受け入れのコスト

- 受け入れはすべて**手動の in-game 実行と `Player.log` の解析**で行っていた。ヘッドレスモードがないためである。0-G では 5 run を実行し、うち Run 5 は 3,691 行だった。PR-1 は 4 run、PR-2.1 は 520 サイクル、PR-3 は 330 サイクルだった。
- キー入力は Computer Use で送っていた。ディスプレイがオフになると止まる問題も記録されている（`phase-1-pr-1-acceptance-progress-2026-04-29.md`）。
- 受け入れの設計が脆かった。PR-1 の Run 2 は、ゾーン遷移でパリティが崩れたため却下された。その後、acceptance では E と W の往復移動を使うことにした。
- PR-3 の敵対的なケース（stale、duplicate、epoch 不一致）は **in-game では一度も検証されていない**。単体テストと静的テストだけである（ADR 0017 Consequences）。

### 3.5 痛点のまとめ

| 痛点 | 定量・根拠 |
|---|---|
| 文書が過剰で、行動に対して記録が重い | docs とコードが 4.5:1。PR-3 の計画書は差分の約 4.5 倍 |
| 仕様凍結と ADR の強制による硬直 | 15 ADR のうち 5 本が凍結仕様の修正。decision record の 43%（19/44）がレビュー指摘への文書修正の記録 |
| レビューを重ねても収束しない | 仕様レビュー 11 回、PR-G1.5 で 5 巡 |
| 実測のループが遅い | 受け入れはすべて手動の in-game。Computer Use に依存。C# の CI はない |
| LLM に到達する前にプロトコル機構だけが先に育った | envelope、冪等性、epoch、supervisor を実装した一方、ツールは 0 件で LLM 呼び出しも 0 件 |

---

## 4. 再利用できる資産

判定は「そのまま」「修正して」「捨てる」の 3 種類で示す。

### 4.1 C# MOD（`v1/mod/LLMOfQud/`）

| ファイル | 1 行説明 | 判定 | 理由 |
|---|---|---|---|
| `manifest.json` | Mod の manifest | **修正して** | `Description` が「Phase 0-A skeleton only」のまま古い。フィールドの仕様自体は正しい |
| `LLMOfQudBootstrap.cs`（14 行） | `[PlayerMutator]` から `RequireSystem<LLMOfQudSystem>()` を呼ぶ | **そのまま** | 最小で、実証済みの方法である（K2） |
| `LLMOfQudSystem.cs`（856 行） | BTA で観測、AfterRender で出力、CTA で判断と実行、3 層ドレイン、切断時の pause、wake | **修正して** | AfterRender での取得、`PendingSnapshot` の受け渡し、CTA フック、3 層ドレイン、`PreventAction` を保険に限定する方針、`SkipPlayerTurn` と `KeyEvent` による wake は、どれも**実証済みの核**である。一方で、セルごとの blocked-dir 記憶は heuristic 専用であり、`_beginTurnCount` をターン ID に使うとキャラクター切り替えで 0 に戻る。1 クラスに役割を詰め込みすぎてもいる |
| `SnapshotState.cs`（1,015 行） | `[state]`、`[caps]`、`[build]`、`[cmd]`、`[decision]` の JSON を手書きで組み立てる | **修正して** | どのフィールドを、どの API から、どんな副作用の注意（`HasID`、Obsolete、マークアップの除去）付きで取るかという**知識**は価値が高い。`StringBuilder` による手書き JSON は置き換えられる。**（推測）** `ModManager.GetCompilerService` はロード済みアセンブリをすべて参照に加え（`[再確認] stable/XRL/ModManager.cs:123-126,389-410`）、ModManager 自身が `using Newtonsoft.Json` している（`stable/XRL/ModManager.cs:10`）。ゲームの `Managed/` にも `Newtonsoft.Json.dll` がある。したがって Mod から Newtonsoft を使える可能性が高い（コンパイルでは未検証）。エンティティのゲートは緩すぎる |
| `IDecisionPolicy.cs`（65 行） | `decision_input.v1`/`decision.v1` の DTO とインターフェース | **捨てる**（考え方だけ残す） | 入力が HP、位置、隣接、直前の行動だけで、行動も Move と Attack だけである。LLM が遊ぶには狭すぎる。「判断は入力だけに依存し、CoQ API を触らない」という境界の考え方は残すとよい |
| `HeuristicPolicy.cs`（117 行） | 低 HP なら逃げ、隣接敵がいれば攻撃し、それ以外は固定順で探索する | **捨てる**（テスト用の fixture としてなら可） | ADR 0010 で探索の質は non-goal とされた。U 字の袋小路で振動する |
| `WebSocketPolicy.cs`（453 行） | `Decide` を Brain に中継する。500ms の timeout で explore にフォールバックし、手書きの JSON パーサを持つ | **修正して**（大幅に） | 500ms の同期待ちは LLM の遅延と両立しない（§5）。timeout と切断で方針が分かれている。パーサはトップレベルしか読めない自作品で、`ToolRouter` 側と重複している。`DisconnectedException` の方針は流用できる |
| `BrainClient.cs`（484 行） | 専用スレッドの `ClientWebSocket` で、キュー、再接続、tool_call の往復を扱う | **修正して** | `ClientWebSocket` が Roslyn Mod から使えることは実証済みで、スレッドの分離も妥当である。ただし `Stop()` は**どこからも呼ばれていない**（`grep "\.Stop()" mod/` で当たるのは `stopwatch.Stop` だけ）。`EnsureRuntimePolicy` は `_policy` が null になると新しい `WebSocketPolicy` と `BrainClient` を作る（`LLMOfQudSystem.cs:64-74`）。**（推測）** 新規ゲームやロードのたびに古いワーカースレッドが止まらずに残る。`ToolRouter` がスレッドのローカル変数になっている点もある |
| `ToolRouter.cs`（1,112 行） | tool_call envelope の解析、terminal の冪等性、tool_result の組み立て | **捨てる**（冪等性の設計メモだけ残す） | 本物のツールが 0 件で、terminal は no-op の accept である。`session_epoch` は 1 に固定されている。JSON パーサも自作である。**（推測）** `state_version` にターン番号を使っているので、ターン番号がリセットされると `_completedTerminalStateVersions` と衝突する |

### 4.2 Python Brain（`v1/brain/`）

| ファイル | 1 行説明 | 判定 | 理由 |
|---|---|---|---|
| `app.py`（644 行） | probe 用の WebSocket サーバ（canned decision、sleep、disconnect、tool_call_probe の各フェーズ） | **捨てる**（テスト用の fake server として一部は流用可） | LLM も tool loop もない。フェーズを切り替える仕組みは E2E の probe には便利だった |
| `protocol.py`（144 行） | pydantic による `ToolCallMessage`、`ToolResultMessage`、`Supervisor*` の定義 | **修正して** | provider に依存しない envelope（`call_id`、`status/output/error_code/error_message`）は妥当である。ツールのスキーマ本体がない |
| `auth/device_flow.py`、`auth/broker.py`、`auth/token_store.py` | Codex の device flow のスキャフォールド | **捨てる** | 実装はすべて `Phase2aAuthUnavailableError` を投げるだけである。provider を選び直す前提になる |
| `db/schema.py`、`db/writer.py` | transport テレメトリ 9 テーブルと aiosqlite の writer | **修正して** | 未配線で、ゲームプレイ系のテーブルがない。telemetry writer の骨格は流用できる |

### 4.3 テスト、ガバナンス、文書

| 資産 | 判定 | 理由 |
|---|---|---|
| `tests/test_mod_static_contracts.py` | **捨てる** | ソース文字列への grep で契約を検査しているので、リファクタに脆い |
| `tests/test_brain_app.py`、`test_protocol_messages.py`、`test_brain_db.py` | **修正して** | 対応するモジュールと一緒に作り直す |
| `tests/test_adr_decision_scripts.py`、`scripts/*_adr*`、`.githooks` | **捨てる** | ADR を強制する仕組みは摩擦の主因だった（§3.3） |
| `harness/policy.yaml` | **捨てる** | 自身に「policy intent only; automated enforcement is not implemented yet」と書かれたテンプレートの残骸である |
| `pyproject.toml` の ruff、mypy、basedpyright、vulture の設定、`Directory.Build.props` | **修正して** | lint の設定そのものは良質である。ゲートの数を絞る |
| `.github/workflows/*`、`.coderabbit.yaml`、`semgrep.yml` | **修正して**（大幅に縮小） | C# のジョブが無意味である。required-checks-gate は重い |
| `docs/architecture-v5.md` | **参考資料としてのみ** | ツール、modal、メモリ、配信の設計案としては読む価値がある。凍結仕様として扱ってはいけない |
| `docs/memo/phase-*-exit-*.md` | **そのまま**（知識ベースとして） | 実測の記録として一次資料になる。ただし行番号は 2.0.210 のもの |
| `docs/memo/memory-architecture-research.md`、`phase-1-pr-2-readiness-precedent-survey-2026-04-29.md` | **そのまま**（参照用） | 外部の先行例の URL 集になっている（付録を参照） |
| `docs/superpowers/plans/*`、`specs/*` | **捨てる** | 過去のフェーズの実行計画で、再利用する価値は低い |

---

## 5. v1 がどこで止まったか、なぜ止まったか

### 5.1 停止点（事実）

- 最後の機能は Phase 1 PR-3（terminal の冪等性）である。`v1/docs/memo/phase-1-progress-2026-04-29.md` には「Phase 2a should not begin until PR-2 and PR-3 land」とある。PR-3 はマージされたが、**Phase 2a（LLM 統合、ツールの本実装、SafetyGate、modal、overlay）の痕跡は一切ない**。
- 実装が集中したのは 04-24〜04-29 である。PR-3 は 04-30 に E2E を終えたが、ADR の Accepted は 05-21、コミットは 07-04 だった。**（推測）** 5 月以降の作業は、ほぼ完成していた PR-3 を片づけるだけだった。

### 5.2 止まった理由（すべて推測）

1. **「LLM がゲームを遊ぶ」という価値の中心に到達するまでの距離が縮まらなかった（推測）**。
   - v1 は観測、コマンド発行、ブリッジ、envelope、冪等性と、外側の配管を順に固めた。
   - LLM が見る観測ツール（`inspect_surroundings` など）も、LLM を呼ぶループも最後まで作られなかった。
   - 6 日間で 0-A から PR-2 まで進んだあと、次の一歩（Phase 2a）の前提となる仕様があまりに大きかった。11 ツール、modal、Safety、memory、overlay がそれに当たる。そのため心理的にも工数的にも着手の壁が高かったと考えられる。
2. **プロセスの負荷が実装の速度を上回った（推測）**。docs とコードの比が 4.5:1 で、decision record の 43% がレビュー指摘への文書修正である。PR ごとに Codex、CodeRabbit、Devin のフォローアップが回っていた（§3）。個人開発の規模に対して、ガバナンスが企業並みの重さだった。
3. **仕様凍結と実測がぶつかり続けた（推測）**。実測のたびに凍結仕様が外れ、その都度 ADR が必要になった（15 本中 5 本）。仕様は 3,400 行の机上設計で、CoQ の実挙動を知らないまま凍結されていた。たとえば `CommandEvent.Send` を前提にしていた点や、BirthBuild の前提がそうである。
4. **判断境界と v5.9 のツールモデルが乖離していた（推測）**。実装された `decision_input.v1` は bot 向けの 1 手判断であり、v5.9 は LLM が複数のツールを呼んで判断する設計である。両者をつなぐ移行路は設計されていない。
   - PR-2 と PR-3 の tool_call は「decision の前に probe を 1 回はさむ」形にとどまった（`app.py:243-255`）。
   - C# の 500ms 同期待ちに、v5.9 が想定する 1 ターン最大 10s の tool loop（`architecture-v5.md:1885-2201`）はそのままでは載らない。
   - timeout 時には explore Move にフォールバックするので、**実際の LLM をつなぐと毎ターン timeout して東へ歩き続ける**おそれが高い（`WebSocketPolicy.cs:25,60-63,83-93`）。
5. **検証のループが遅く、手作業だった（推測）**。ヘッドレスがなく、Computer Use でキーを送り、ログを手で解析する必要があった。C# の CI もなく、1 回の反復が重かった。LLM を載せたあとの反復は非決定的でもっと重くなるため、先に進む動機を削いだ可能性がある。
6. **provider と認証の前提が揺れた（推測）**。仕様は Codex の OAuth で gpt-5.4 を使う前提だった（`architecture-v5.md:3165-3181`）。PR-2 の前に provider に依存しない設計へ転換した（ADR 0015）ものの、どの LLM を使うかは決まらないままだった。auth はプレースホルダのままである。

---

## 6. 新しい探索が答えるべき未解決の問い

1. **どの decompile を正とするか**。2.0.211.50（`coq-decompiled_stable`）と 2.0.211.56（`decomp-new`）がある。実際にインストールされているゲームのビルドとも照合して、行番号の基準を決める必要がある。
2. K5〜K7（tile モードのグリフ退避と AfterRender での復元）は、**インストール済みの現行ビルドで in-game 再実証できるか**。静的な仕組みは 2.0.211.50 で維持されているが、modern UI の overlay（`TextConsole.cs:151` の `bSkipIfOverlay`/`ModernUI`）の影響は未検証である。
3. modern UI の画面（インベントリ、会話、トレード、popup）は `ScreenBuffer` に描かれるのか。描かれない場合、**画面なしで modal の中身をどう観測するか**。v1 には modal の実装も実測もない（K23）。
4. LLM に見せる観測は何がよいか。候補は ASCII 全画面、21×21 の窓、構造化 JSON、自然言語の要約である。粒度とトークンコストの最適点を決める必要がある。v1 は約 18.7KB/ターンをログに出していたが、LLM への入力としては評価していない。
5. **LLM の遅延（秒単位）と CoQ のターンループをどう両立させるか**。CTA で同期的にブロックする方式を延長するのか、`PlayerTurn` の idle に委ねて非同期にするのかを決める必要がある。pause と timeout の方針を統一することも含まれる。
6. 行動の語彙をどう広げるか。Move と Attack 以外に、待機、アイテム、アビリティ、会話、ワープ、AutoAct（`M`/`P`）がある。`CommandEvent.Send` が効かないコマンドがほかにもあるか、direct API で網羅できるかを調べる必要がある。
7. `navigate_to` を AutoAct に委ねる場合、2.0.211 の `TryToMove` の新しいシグネチャ（`AutoAct.cs:815,963`）に Harmony を当てて安全に使えるか。AutoAct の中断理由を分類できるか（K24/K25）。
8. **セーブ/ロードと新規キャラクター作成をまたいでも、ブリッジは正しく動くか**。v1 では未テストである。`BrainClient.Stop()` が呼ばれずスレッドが残る疑い、ターン番号のリセット、`session_epoch` の固定がある。
9. Mod から `Newtonsoft.Json` を実際に参照してコンパイルできるか。自作パーサ 2 つを置き換えられるかがこれで決まる。
10. **ヘッドレスまたは自動の E2E 手段はあるか**。CLI 引数（`[v1記録] GameManager.cs:785`、`XRLCore.cs:3515`）、`XRL.Tests` の NUnit、Computer Use 以外のキー注入が候補になる。
11. 配信のペーシングをどうするか。エンジン速度の暴走（K15）を抑える throttle をどこに置くか。LLM 思考中の画面をどう見せるか。
12. 同時に導入されている Mod との共存のリスクをどう扱うか。v1 は QudJP を低リスクと判定していた（`v1/docs/memo/phase-0-a-exit-2026-04-23.md`）。
13. v1 の「凍結仕様と ADR の強制」に代わる軽いプロセスで、どこまで意思決定を記録するか。これはプロセスの問いであり、技術の問いではない。

---

## 付録: v1 が参照した外部資料（URL）

- 先行例と配信: https://michaelyliu6.github.io/posts/claude-plays-pokemon/ 、 https://www.zenml.io/llmops-database/building-and-deploying-a-pokemon-playing-llm-agent-at-anthropic
- ローグライクのエージェント: https://kenforthewin.github.io/blog/posts/nethack-agent/
- メモリ: https://allenai.github.io/clin/ （CLIN）、 https://github.com/AIRI-Institute/AriGraph 、 https://voyager.minedojo.org/ 、 https://research.memgpt.ai/ 、 https://blog.jetbrains.com/research/2025/12/efficient-context-management/
- コンテキスト設計: https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents 、 https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents
- Provider の tool-use: https://developers.openai.com/api/docs/guides/function-calling 、 https://developers.openai.com/api/docs/guides/prompt-caching 、 https://developers.openai.com/api/docs/guides/conversation-state 、 https://platform.claude.com/docs/en/agents-and-tools/tool-use/parallel-tool-use 、 https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching
- CoQ の Modding: https://wiki.cavesofqud.com/wiki/Modding%3AC_Sharp_Scripting

（以上の URL は v1 の `docs/memo/memory-architecture-research.md`、`phase-1-pr-2-readiness-precedent-survey-2026-04-29.md`、`test-strategy-codex-research-2026-04-23.md` から転記した。今回は内容を再取得していない。）
