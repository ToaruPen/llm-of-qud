# P1. In-process MCP サーバー案（"RimMolt for Qud"）

- 立場: アーキテクチャ提案 1 本（探索フェーズ）。比較のための叩き台であり、採用決定ではない。
- 作成: Opus 5.5 worker、2026-09-25。
- 根拠: `docs/exploration/01`〜`04`、および `~/Dev/coq-decompiled_stable` の再確認。引用形式は `path:line` で、パスは decompile ルートからの相対パスとする。

## 0. 引用の基準と今回の再確認（spot-check）

**decompile の版が変わっている。** `coq-decompiled_stable/Properties/AssemblyInfo.cs:8` は `AssemblyVersion("2.0.211.56")` である。01 と 02 は stable を 2.0.211.50 と記述しているが、現在は Steam の現行ビルドと一致している。そのため 03 が `NEW/` として挙げた行番号は、stable にそのまま当てはまる。本書の行番号はすべてこの stable ツリーのものである。

自分で開いて確認した引用を下の表にまとめる。

| 引用 | 内容 | 結果 |
|---|---|---|
| `XRL.Core/XRLCore.cs:734` | `PlayerTurn` 冒頭の `Keyboard.ClearMouseEvents(LeaveMovementEvents: true)` | 一致 |
| `XRL.Core/XRLCore.cs:737-740` | `while (!GameManager.focused && Game.Running) Thread.Sleep(200)` | 一致 |
| `XRL.Core/XRLCore.cs:1167` | `case "CmdMoveE"` | 一致 |
| `XRL.Core/XRLCore.cs:2390-2396` | `IdleWait` の後の `SkipPlayerTurn` break | 一致（2393） |
| `XRL.Core/XRLCore.cs:2600-2605` | `RenderBase` が CoreThread 上なら `gameQueue.executeTasks()` を呼ぶ | 一致（2604） |
| `XRL.Core/ActionManager.cs:743, 789, 1602/1611, 1640` | BTA、CTA の `Check` → `continue`、`PlayerTurn`、`EndActionEvent` | 一致 |
| `XRL.UI/Popup.cs:801, 824-829, 901, 908` | `WaitNewPopupMessage`。`uiQueue.awaitTask` 内で `PushGameView("PopupMessage")` → `ShowPopup` を実行し、ゲームスレッドは `complete.Task.Wait()` で止まる | 一致 |
| `XRL.UI/Popup.cs:1571-1614, 2251-2275, 1433-1442, 658-671` | `ShowConversation`（`option:i`）、`ShowYesNo`、`AskString`（`.Result`）、`Show`（`Suppress`） | 一致 |
| `Qud.UI/PopupMessage.cs:926-933` | `OnActivateCommand` が `commandCallback(command)` を呼んでから `Hide()` する | 一致 |
| `XRL.World/GameObject.cs:16234, 18397, 11424, 18058` | `Move`、`AttackDirection`、`IsHostileTowards`、`PassTurn` | 一致 |
| `XRL.World/GameObject.cs:3677` | `UseEnergy` | **ずれあり**。03 §3.5 の記述は `:3645` |
| `GameManager.cs:148, 150, 404-425, 1920-1924` | `uiQueue`、`gameQueue`、`focused`、`OnApplicationFocus` | 一致 |
| `ConsoleLib.Console/Keyboard.cs:938-954` | `kbhit`。非フォーカス時は `KeyEvent.WaitOne(200)` | 一致 |
| `XRL/ModManager.cs:389-416`、`XRL/ModInfo.cs:845-862` | 参照アセンブリの述語、`ApplyHarmonyPatches` | 一致 |
| `Managed/` の実物 | `System.dll` に `HttpListenerContext`、`HttpListenerPrefixCollection`、`HttpListenerWebSocketContext`、`TcpListener` の型名がある。`Newtonsoft.Json.dll` は 13.0.2、`0Harmony.dll` も同梱されている | 一致 |

本書で新たに調べた箇所: `EndGame`（`XRL.World.Conversations.Parts/EndGame.cs`）、`TradeUI.PerformOffer`、`StatusScreen.BuyStat`、`MutationsAPI.BuyRandomMutation`、`EmbarkBuilder.exitWithInfo`、`CmdTalk` と `CmdAutoExplore` の実装、`PickDirection`/`PickTarget` のビュー名。

---

## 1. 概要と狙い

**一文で言うと**: C# mod がゲームプロセスの中で MCP サーバーを開く。プレイヤーの `CommandTakeActionEvent`（CTA）の中でゲームスレッドを止め、「エージェントの手番」として待たせる。Claude Code や Codex CLI をそのまま MCP クライアントにして、LLM に CoQ を遊ばせる。Harmony も Rosetta も使わない。

### 1.1 最適化する対象

1. **最初の自律ターンまでの距離を最短にする。** brain のコードはゼロから始める。v1 は LLM を一度も呼ばないまま止まった（01 §5）。この案では、mod の MCP ツールが 1 つ動いた時点で Claude Code がそれを叩ける。プロトコルの機構（envelope、冪等層、epoch）を先に育てる余地がない。
2. **ハーネスを透明にする。** LLM が見るものと行うことは、すべて MCP の 1 本の口を通る。mod 側がその全往復を JSONL に記録する。「LLM は何を見て、何をしたか」が 1 ファイルで監査できるので、クリアの主張の証拠の中心になる（§8）。
3. **Apple Silicon のネイティブ実行で動かす。** モーダル UI への応答は、Harmony ではなく UI スレッドの公開メソッド `PopupMessage.OnActivateCommand` で行う（§4）。これで 03 の U1（Harmony 2.2.2 の EACCES）と QudJP の Rosetta 起動という前提をまとめて外せる。
4. **brain を差し替えられるようにする。** MCP のツール面を安定した契約とし、後から Python の自作 brain に換えても mod は変えない（§6.4）。

### 1.2 意図的に捨てるもの

- **ツールで表せない操作。** RimMolt と同じく、ツールにない操作は存在しないのと同じになる。キー入力の汎用注入（「任意のキーを押す」）は公開しない。例外はピッカーへの方向キーと Enter だけである。
- **Legacy UI（`OptionModernUI=No`）での動作。** Modern UI の `PopupMessage` 経路に特化する。Legacy の `getvk` ループは、ピッカー以外では対象外とする。
- **Modern のフルスクリーン UI（ステータス画面、Modern Trade、Modern のキャラクター作成）の操作。** これらは開かせない。同じ効果をゲームスレッドの直接 API で実現する（§3、§4）。
- **LLM の思考の中身を mod 側で持つこと。** 推論のテキストはクライアント（Claude Code）のトランスクリプトにしか残らない。mod が確実に持つのは、ツールの往復と `narrate` の文字列だけである。
- **初期段階での文脈管理の制御。** 圧縮のタイミングもモデルの選び分けも Claude Code に任せる。これは後で自作 brain に置き換える部分である（§6.4）。

---

## 2. 観測

### 2.1 使う表面

| 用途 | 表面 | 引用 | 読むスレッド |
|---|---|---|---|
| プレイヤー状態 | `hitpoints`/`baseHitpoints`、Statistics、`Stomach.FoodStatus/WaterStatus`、Effects、重量、ドラム | `XRL.World/GameObject.cs:1176`、`XRL.World.Parts/Stomach.cs:87,104`、`Qud.UI/PlayerStatusBar.cs:310-422`（参照元の一覧として） | ゲーム（CTA で待機中） |
| 周囲 | `Cell.IsVisible/IsExplored`、`Cell.GetObjects`、`Zone.GetObjects()` を可視でふるう、`IsHostileTowards`、`DistanceTo`、方角 | `XRL.World/Cell.cs:3469-3497,4854`、`XRL.World/Zone.cs:3612`、`XRL.World/GameObject.cs:11424,3718` | ゲーム |
| 地図のグリフ | `XRLCore.RegisterAfterRenderCallback` で源バッファの `_Char`、なければ `BackupChar` を読む（v1 K7 で実証済み） | `XRL.Core/XRLCore.cs:652-655,2464,2508`、`ConsoleLib.Console/ConsoleChar.cs:392-420` | ゲーム（コールバック） |
| 記述テキスト | `Look.GenerateTooltipContent(GameObject)` | `XRL.UI/Look.cs:239` | ゲーム |
| メッセージ | `RegisterNewMessageLogEntryCallback` で push を受け、ターン区切りでまとめる | `XRL.Core/XRLCore.cs:657`、`XRL.Messages/MessageQueue.cs:138-148` | 追加元のスレッド（lock 付きのリングに積む） |
| 出来事 | `IGameSystem` の `QuestStarted`/`QuestCompleted`/`AwardingXP`/`ZoneActivated`/`PlayerEnteredCell` | `XRL/IGameSystem.cs:2975,2980,3051,3046,3000` | ゲーム |
| クエストとジャーナル | `XRLGame.Quests`/`FinishedQuests`、`JournalAPI.GetKnownNotes()` | `XRL/XRLGame.cs:145-148`、`Qud.API/JournalAPI.cs:27-41` | ゲーム |
| 能力 | `ActivatedAbilities`、`ActivatedAbilityEntry.Command/Cooldown/IsUsable` | `XRL.World.Parts/ActivatedAbilities.cs:183`、`XRL.World.Parts/ActivatedAbilityEntry.cs:40-290` | ゲーム |
| 自動行動の状態 | `AutoAct.IsActive()`、`AutoAct.GetDescription()`、`GameObject.AutomoveInterruptBecause` | `XRL.World.Capabilities/AutoAct.cs:114,405,419-421`、`XRL.World/GameObject.cs:74` | ゲーム |
| いま開いている UI | `GameManager.Instance.CurrentGameView` | `GameManager.cs:469`（`PushGameView` は `:1493`） | どこからでも読める（参照の読み取り） |
| モーダルの中身 | `PopupMessage` の `Title.text`、`Message.text`、`controller.menuData`、`controller.bottomContextOptions`、`inputBox.text`、`PopupID` | `Qud.UI/PopupMessage.cs:20-42,247,779-782`、`XRL.UI/UITextSkin.cs:54` | **UI スレッド**（`uiQueue` 経由） |
| 会話の意味情報 | `ConversationUI.CurrentConversation/CurrentNode/CurrentChoices` | `XRL.UI/ConversationUI.cs:145-153` | ゲーム（会話中はゲームスレッドが止まっているので読める。§5.4） |

使わないもの: `ScreenBuffer.ToString()`（タイルモードでは NUL だらけになる）、ミニマップ、UAP。

### 2.2 LLM に渡す形

観測は 3 つの粒度に分ける。dcss-ai が free な操作と turn を消費する操作を分けた考え方と、rimagent が変化の大きい情報を先に並べた考え方を取り入れている。

1. **行動結果に自動で付く差分**（`delta`。毎回、目安 300〜600 tokens）: 経過ターン、HP の変化、新しいメッセージ、視界に出入りした敵、出来事、モーダルの有無。
2. **`get_state(detail="brief")`**（目安 700〜1,000 tokens）: 下の例の全体から `map` を除いたもの。
3. **`get_state(detail="full")`**（目安 1,800〜2,500 tokens）: 21×11 の ASCII 窓とその凡例を加える。

**表現の原則**

- **並べ方**: 先頭から「モーダル → 危険 → 差分 → 自分 → 周囲 → 目標」の順にする（P1/P5）。
- **座標**: LLM に生の座標を計算させない。対象は短いハンドル（`e3`）、方角（`NE`）、歩数で表す。ハンドルは mod 側の参照表で管理し、ゾーンが変わるとリセットする。`GameObject.ID` のように遅延採番される値には触れない（v1 K10）。
- **色マークアップ**: 除去する（qud-accessibility と同じ `ColorUtility.StripFormatting`）。
- **言語**: 英語にする（隔離プロファイルで QudJP を入れない。§10）。

**1 ターン分の観測の例**（`get_state(detail="full")` の結果。内容は例示で、実測ではない）

```json
{
  "seq": 5121, "turn": 1843, "gate": "agent_turn",
  "modal": null,
  "danger": [
    {"h": "e3", "name": "snapjaw scavenger", "dir": "NE", "dist": 2, "health": "wounded", "hostile": true, "note": "adjacent next turn"}
  ],
  "since_last": {
    "turns": 1, "hp": "-3",
    "messages": ["The snapjaw scavenger hits you with a bronze dagger for 3 damage."],
    "events": []
  },
  "self": {
    "hp": "15/24", "lvl": 3, "xp": "1120/1500", "av": 4, "dv": 7,
    "food": "Sated", "water": "Quenched", "effects": ["bleeding"],
    "weight": "112/210", "drams": 34, "points": {"attr": 0, "skill": 40, "mut": 4}
  },
  "where": {"zone": "Joppa", "world_map": false, "depth": 10, "light": "day"},
  "nearby": [
    {"h": "e1", "name": "Mehmet", "kind": "npc", "dir": "W", "dist": 6, "talk": true},
    {"h": "e7", "name": "chest", "kind": "container", "dir": "S", "dist": 3},
    {"h": "x1", "name": "stairs down", "kind": "exit", "dir": "SE", "dist": 9}
  ],
  "abilities": [
    {"cmd": "CommandSprint", "name": "Sprint", "ready": true},
    {"cmd": "CommandFreezingRay", "name": "Freezing Ray", "ready": false, "cooldown": 7}
  ],
  "goal_hint": {"quest": "What's Eating the Watervine?", "step": "Travel to Red Rock"},
  "map": {
    "window": "21x11（抜粋）", "you": "@",
    "rows": [
      "#####...............",
      "#...#....~~~........",
      "#.+.#....~~~....3...",
      "#####................",
      ".........1.....@.....",
      "...................>.",
      "..........7..........",
      "....................."
    ],
    "legend": {"3": "e3 snapjaw scavenger", "1": "e1 Mehmet", "7": "e7 chest", "~": "fresh water", "+": "door", ">": "stairs down"}
  }
}
```

**トークン量の見積もり**（推定）

- 上の full 観測は約 2,000 tokens になる。
- LLM の 1 判断あたりの典型は、行動結果の差分 1 回と、ときどきの `get_state(brief)` を合わせた 800〜1,500 tokens に、モデル自身の思考を加えたもの。
- Claude Code の文脈 100k の場合、圧縮までに約 50〜80 判断と見込む。
- クリアまでの LLM 判断数は、自動探索・移動・休息のマクロを使っても数千〜1 万数千になると推定する。この試算から、**文脈の外に置く記憶**（§7）が必須になる。

### 2.3 タイルモードと Modern UI への依存

- 主要な観測（§2.1 の構造化 API）は**描画モードに依存しない**（03 §6.1 の C/D/E/F/K）。
- 地図の窓だけは AfterRender のグリフに依存する。タイルモードでは `BackupChar` から補う必要がある（`ConsoleChar.cs:392-420`）。このコールバックは Sidebar より前に呼ばれ、引数は常に static `_Buffer` である（03 §1.2）。
- グリフが取れなかったセルは、構造化 API（通行可否、液体、オブジェクト種別）から合成した文字で埋める。これにより、**タイルモードのまま配信しても観測の質は落ちない**。
- 地図が古くならない工夫がある。CTA で待機に入るときに `The.Core.RenderBase()` を 1 回呼び（`XRLCore.cs:2600`）、敵が動いた後の状態を描画し直してから取得する。このとき同時に `gameQueue` も捌かれる（`:2604`）。
  - 呼ぶ理由: 最後の描画は、プレイヤーが行動した直後の fallback 描画（`ActionManager.cs:1618-1621`）である。そのため、敵の手番の後の状態がまだ画面にない。
  - この再描画は、配信で視聴者が現在の局面を見るためにも必要である。
- **モーダルの読み取りは Modern UI に依存する**（`UIManager.UseNewPopups => Options.ModernUI`、`Qud.UI/UIManager.cs:55`）。この依存は受け入れる。

---

## 3. 操作

### 3.1 ツールの一覧

分類は 3 つ: **Free** はターンを消費せず状態を変えない。**Act** はターンを消費しうる。**Modal** はモーダルへの応答である。

| 名前 | 種別 | 引数 | 実装 |
|---|---|---|---|
| `status` | Free | – | ゲートの状態（§5.1）、待機している時間、処理中の op、直近のエラー、ゲーム版、表面の自己診断（§10.3） |
| `get_state` | Free | `detail`, `map_radius` | §2.2 |
| `look` | Free | `target`（ハンドルまたは方角） | `Look.GenerateTooltipContent`（`Look.cs:239`） |
| `inventory` | Free | – | 所持品のハンドル、装備中かどうか、各アイテムで取れる行動（`EquipmentAPI.GetInventoryActions`、`Qud.API/EquipmentAPI.cs:378`） |
| `character` | Free | – | 能力値、スキル、変異、能力、クールダウン、未使用ポイント |
| `quests` | Free | – | 進行中のクエストとステップ、ジャーナル（`JournalAPI`） |
| `messages` | Free | `since_seq` | メッセージログの差分 |
| `map` | Free | `scope`（`local`/`zone`/`world`） | 探索済みの地形の要約 |
| `notes_read` / `notes_write` | Free | `section`, `text` | mod 側の記憶ファイル（§7） |
| `narrate` | Free | `text`（240 字まで） | 配信のオーバーレイと証拠ログへ出す（§9） |
| `knowledge_search` | Free | `query` | 段階別の知識ベース（§7.3） |
| `move` | Act | `dir`（N..NW, U, D） | `GameObject.Move(dir)`（`GameObject.cs:16234`）。`DoConfirmations` は既定の true のままにする。確認ダイアログはモーダルとして LLM に見せる |
| `attack` | Act | `target` か `dir` | `AttackDirection`（`:18397`） |
| `wait` | Act | `turns`（1〜20） | `PassTurn()`（`:18058`）を CTA ごとに 1 回ずつ。途中で敵が見えたら打ち切る |
| `rest` | Act | `until`（`healed`/`morning`/N） | `AutoAct.Setting` を `"r"`/`"z"`/`".N"` にする（`ActionManager.cs:855-1441` の文字列規約） |
| `autoexplore` | Act | – | `CmdAutoExplore` と同じ処理（`FlushNavigationCaches(); AutoAct.Setting = "?"`、`XRLCore.cs:1920-1925`） |
| `travel` | Act | `target`（ハンドル、ランドマーク名、`"x,y"`） | `AutoAct.Setting = "M x,y"`（03 §3.4）。ワールドマップでは 1 手ずつ `move` する |
| `stairs` | Act | `up`/`down` | `AutoAct.Setting` を `"<"`/`">"` にするか、階段の上で `move U/D` |
| `pickup` / `open` / `use` | Act | `target`/`dir` | `CmdGet*`/`CmdOpen`/`CmdUse{Dir}` が呼んでいる内部処理を、方向ピッカーを経ずに呼ぶ（04 §1.5 の隠しコマンドの実装を移植する） |
| `talk` | Act | `target` | `CmdTalk` と同じ: `ConversationScript.AttemptConversation()`（`XRLCore.cs:2212-2236`）。すぐに会話モーダルになる |
| `use_ability` | Act | `command`, `target?` | `CommandEvent.Send(player, cmd, Target, TargetCell)`（`XRL.World/CommandEvent.cs:124`）。対象選択 UI が出たら §4 のピッカー経路。**`command` はプレイヤーの `ActivatedAbilities` に登録済みの `Command` だけを受け付ける**。任意の文字列を通すと、`WishMenu` の `CommandEvent`（`XRL.World.Parts/WishMenu.cs:180-185`）のような裏口に届くためである |
| `item` | Act | `item`, `action` | `InventoryActionEvent.Check(...)`（`XRL.World/InventoryActionEvent.cs:110`）。`action` は `inventory` が返した候補から選ぶ |
| `equip` / `unequip` / `drop` | Act | `item`, `slot?` | `EquipmentAPI.EquipObject/UnequipObject/DropObject`（`EquipmentAPI.cs:488,439,501`） |
| `spend_points` | Act | `kind`（`attr`/`skill`/`mutation`）, `name` | `StatusScreen.BuyStat(GO, stat)`（`XRL.UI/StatusScreen.cs:62`）。`SkillsAndPowersScreen.BuildNodes` と `SelectNode`（`XRL.UI/SkillsAndPowersScreen.cs:229,141`）。`MutationsAPI.BuyRandomMutation`（`Qud.API/MutationsAPI.cs:95`）、`StatusScreen.ShowMutationPopup`（`StatusScreen.cs:575`）。**Modern のステータス画面の操作が裏で呼んでいるのと同じ API** である（`Qud.UI/CharacterStatusScreen.cs:343-367,421-425`） |
| `trade` | Act | `merchant`, `buy[]`, `sell[]` | `TradeUI.GetObjects` → `SetNumberSelected` → `PerformOffer`（`XRL.UI/TradeUI.cs:150,276,1296`）。Modern の `TradeScreen.show(...).Result`（`:456-458`）は**開かない** |
| `fire` / `throw` | Act | `target`, `item?` | `CmdFire`/`CmdThrow` の後の `PickTarget` を §4 のピッカー経路で解決する（3 週目） |
| `answer_modal` | Modal | `choice`（index、ラベル、`Yes`/`No`/`Cancel`）, `text?` | §4 |
| `answer_picker` | Modal | `dir` か `target` | §4 |
| `wait_for_turn` | Free | `op_id`, `timeout_s`（最大 45） | §5.3 |

`wish` と汎用のキー入力は**公開しない**。エンディング直行の wish `goend`/`gocoda` が存在するため（`EndGame.cs:296-324`）、これを MCP から触れない構造にしておくことが主張の前提になる（§8）。

### 3.2 行動ファミリーごとの実行と結果

**共通規則: 実行はすべてゲームスレッドの CTA 待機ループ（§5.2）の中で行う。**

- 行動の後、`Energy < 1000` になった場合か、`AutoAct.IsActive()` になった場合に限り、CTA を抜ける。
- **v1 の 3 層ドレインはやめる。** 行動に失敗してエネルギーが残ったときに、`PassTurn` で黙ってターンを捨てることはしない。
  - その場合は `{"ok": false, "reason": "blocked: a wall"}` のように理由を返し、同じ手番のまま待機を続ける。
  - LLM が選び直す。黙って PassTurn すると、LLM が知らないうちにターンが進み、誤った学習の原因になる（A2/P4）。
- `Energy >= 1000` のまま CTA を抜けると、ゲームは `PlayerTurn`（キー入力待ち）に落ちる。そこにはフォーカス停止がある（`XRLCore.cs:737`）。そのため、**このゲートは「エネルギーが残っている間は抜けない」を不変条件として守る**。例外はゲームの終了と、人間への引き継ぎ（§5.5）だけである。

| ファミリー | 実行 | 結果として返すもの |
|---|---|---|
| 移動と攻撃 | 直接 API（v1 で実証済み） | `delta`（HP、メッセージ、敵の出入り）。塞がれていた場合は、塞いでいたものの名前 |
| 待機と休息 | `PassTurn` または `AutoAct.Setting` | 経過ターン、中断理由（`AutomoveInterruptBecause`、`GameObject.cs:74`） |
| 自動探索と移動 | `AutoAct.Setting` を設定して CTA を抜ける。AutoAct の各ステップでも CTA は発火する（`ActionManager.cs:789` は `:805` の AutoAct 分岐より前にある）。ハンドラは `AutoAct.IsActive()` のあいだ何もせず、すぐ `true` を返す | AutoAct が止まった後の最初の CTA で完了する。移動した歩数、中断理由、新しく見えたもの |
| 相互作用 | 内部処理を直接呼ぶ | 開いた、拾った、何も起きなかった。モーダルが開いた場合は `modal` |
| 能力 | `CommandEvent.Send`。`Target`/`TargetCell` を渡すと、ピッカーを経ない能力もある（**推論。能力ごとに要確認**） | 発動の有無、クールダウン、ピッカーが開いたかどうか |
| インベントリと装備 | `InventoryActionEvent`、`EquipmentAPI` | 装備箇所、AV/DV の変化 |
| 会話 | `talk` → 会話モーダル → `answer_modal` を繰り返す | ノードごとの本文と選択肢（§4） |
| 取引 | `trade` の一括実行 | 成立、不成立、差額、ドラムの変化 |
| レベルアップ | `Leveler` が出す `Popup.*`（`XRL.World.Parts/Leveler.cs:289-352`）は §4 のモーダル経路、ポイントの消費は `spend_points` | 能力値やスキルの変化 |
| キャラクター作成 | §4.3 | – |

**すべての Act の返り値は、戻り値ではなく「行動後の状態」とする**（P4、RM-022）。

- `ok` は補助の情報にすぎない。主体は、実行後に読み直した `delta` と `modal` である。
- 返り値には `seq`（観測の世代番号）を付ける。
- Act は任意の引数 `expect_seq` を受け取る。値が現在の世代と一致しなければ `stale` として拒否する。クライアントが再送したときに、同じ移動を二重に実行するのを防ぐためである。v1 の冪等層は、この 1 行分だけに縮めて残す。

---

## 4. モーダル UI

### 4.1 基本方針: Harmony を使わず、UI スレッドの公開メソッドで答える

Modern UI のポップアップは、どれも最終的に `Popup.WaitNewPopupMessage` を通る（`Popup.cs:801`）。

- ゲームスレッド側: `uiQueue.awaitTask` の中で `PushGameView("PopupMessage")` を呼び、共有インスタンス `getWindow("PopupMessage")` の `ShowPopup` を実行する（`:824-829`）。そのあと `complete.Task.Wait()` で止まる（`:908`）。
- 答えの受け渡し: `ShowPopup` に渡された `commandCallback` が `complete.SetResult(item)` を呼ぶ（`:834-850`）。
- UI スレッド側: `PopupMessage.OnActivateCommand(item)` は、`commandCallback(item)` を呼んでから `Hide()` する（`Qud.UI/PopupMessage.cs:926-933`）。

したがって次の手順で応答できる。

1. `CurrentGameView == "PopupMessage"` を検出する。
2. `uiQueue` に読み取りのタスクを積む。`uiQueue` はタスクを直列に処理するので、この時点で `ShowPopup` は完了している。
3. LLM に中身を見せる。
4. 応答を受けたら、`uiQueue` 上で**実物の** `QudMenuItem` を `controller.menuData[i]` または `bottomContextOptions[j]` から取り出し、`OnActivateCommand` に渡す。

この手順で `complete.Task.Wait()` が解け、ゲームスレッドが再開する。

**「応答待ち」の判定は `CurrentGameView` だけでは足りない。** `PopGameView` は、`Task.Wait` が返った後にゲームスレッド側で呼ばれる（`Popup.cs:910`）。そのため応答した直後の短い間、`CurrentGameView` はまだ `"PopupMessage"` を返し、同じモーダルを二重に報告してしまう。

判定は「`CurrentGameView=="PopupMessage"` かつ、UI スレッドで読んだ `window.commandCallback != null`」とする。`ShowPopup` がこのコールバックを設定し（`PopupMessage.cs:779`）、`OnActivateCommand` が null に戻す（`:931`）ので、応答済みかどうかをこれで区別できる。Harmony は不要なので、arm64 ネイティブで動く。これは 03 の制御経路 6 にあたり、実測は済んでいない（§11 の probe P4）。

**注意点**

- 項目は自分で合成せず、実物を渡す。`hotkey` などのフィールドを落とさないためである。`QudMenuItem` は struct である（`Qud.UI/QudMenuItem.cs:8`）。
- `OnActivateCommand` は `"CmdOptions"` を拒否する（`:928`）。入力欄のある popup では、`inputBox.text` に値を入れてから `OnInputSubmit` → `OnSelect` を呼ぶ（`:946-958`）。`commandCallback` は `inputBox.text` を読む（`Popup.cs:834-840`）ので、これも UI スレッド上で行う。
- `TutorialManager.AllowSelectedPopupCommand` のゲートがある（`:928`）。チュートリアルモードでは運用しない。
- `NewPopupMessageAsync` の経路は `copyWindow("PopupMessage")` を使う（`Popup.cs:760`）。これは `getWindow` では見つからない。`AskString` は `AskStringAsync(...).Result`（`:1442`）を通るので、この経路に当たるかどうかを実測で確かめる。見つからない場合の代替は §4.4 に書く。

### 4.2 ファミリー別の対応表

| ファミリー | 検出 | 読むもの | 答え方 | Harmony | Rosetta |
|---|---|---|---|---|---|
| `Popup.Show`/`ShowBlock`（情報だけ） | `CurrentGameView=="PopupMessage"`、`menuData` が空、ボタン 1 つ | `Title.text`、`Message.text` | ボタン 1 つを `OnActivateCommand` に渡す。あるいは `Popup.Suppress=true` にしてログへ流す（`Popup.cs:658-671`。§4.5） | 不要 | 不要 |
| `PickOption`/`ShowOptionList` | 同上で `menuData` が 1 件以上 | `menuData[i].text`、Intro | `OnActivateCommand(menuData[i])`（`Popup.cs:1740-1756` が `option:N` を解釈する） | 不要 | 不要 |
| `ShowYesNo`/`ShowYesNoCancel` | ボタンが Yes/No(/Cancel) | `Message.text` | Yes/No のボタンの実物を渡す（`:2260-2275`） | 不要 | 不要 |
| `AskString`/`AskNumber` | `inputBox` が有効 | `Message.text`、既定値 | `inputBox.text` を設定してから `OnInputSubmit`。インスタンスの特定は実測する | 不要 | 不要 |
| 会話（`ShowConversation`） | `PopupID` が `"Conversation:"` で始まる（`Popup.cs:1613`）。かつ `ConversationUI.CurrentNode != null` | `CurrentNode.GetDisplayText`、`CurrentChoices[i]`（`ConversationUI.cs:149-153,517-521`）。表示文と突き合わせる | `menuData[i]` を渡す。**trade ボタン（-2）と Look ボタン（-3）は LLM に見せない**。trade を選ぶと Modern の `TradeScreen` が `.Result` でブロックするためである。取引は会話を閉じてから `trade` ツールで行う | 不要 | 不要 |
| レベルアップや変異の選択 | `Leveler` と `BaseMutation` の `Popup.*`（`Leveler.cs:289-352`、`XRL.World.Parts.Mutation/BaseMutation.cs:1017`） | 上の行と同じ | 上の行と同じ | 不要 | 不要 |
| `PickDirection` / `PickTarget` | `CurrentGameView=="PickTarget"`（`XRL.UI/PickDirection.cs:31`、`XRL.UI/PickTarget.cs:87,381`）。どのツールが開いたかは mod 側でわかっている | どのツールの文脈か。`PickTarget` なら候補の敵一覧（§2 の `danger` と同じ） | legacy の `getvk` ループ（`PickDirection.cs:54`）なので `Keyboard.PushKey`（`Keyboard.cs:777`）が効く。方向はテンキー、対象はカーソル移動と Enter。**なるべくピッカーを開かないようにする**: 攻撃は `AttackDirection`、能力は `CommandEvent.Send` の `Target` 引数を使う | 不要 | 不要 |
| ステータス画面（Modern） | `CurrentGameView=="StatusScreensScreen"` | – | **開かない**。開いてしまったときは、`NavigationController` による Cancel を試す（推論、03 §3.6） | 不要 | 不要 |
| 取引（Modern） | `"ModernTrade"` | – | **開かない**。`trade` ツールは `TradeUI.PerformOffer` を直接呼び、その中の確認は Popup の経路で答える | 不要 | 不要 |
| キャラクター作成 | ゲートの状態 `NoGame`、`CurrentGameView=="EmbarkBuilder"`（`EmbarkBuilder.cs:68`） | – | §4.3 | 不要 | 不要 |
| 本・端末・その他の画面 | `"Book"`、`CyberneticsTerminalScreen` など | – | 3 週目にポップアップの出現を集計してから決める。暫定は Cancel | 未定 | 未定 |
| 死亡・ゲームサマリー | `Game.Running == false`、`XRLGame.DeathReason`（`XRL/XRLGame.cs:50,54`） | 死因 | ランナーが次の周回を始める（§6.3） | 不要 | 不要 |

### 4.3 キャラクター作成

- **M1〜M2**: 人間が選んだビルドコードを使う。コードと選んだ理由は `manifest.json` に**ハーネスへの入力として明記する**。
- **M3 の probe**: `EmbarkBuilder.Begin` は、UI コンテキスト上に `EmbarkBuilder` コンポーネントを作る（`XRL.CharacterBuilds/EmbarkBuilder.cs:61-72`）。UI スレッドでそのコンポーネントを取り出し、`InitModulesFromCode(code)`（`:512`）→ `exitWithInfo()`（`:262-294`）の順に呼べば、`finishedEvent` が完了してゲームスレッドの `.Result`（`XRL.Core/XRLCore.cs:2853`）が解ける見込みである（**推論**）。
- **その後の段階**: LLM に生成済みのキャラクターからの選択（Pregen）、あるいは genotype・calling・変異の選択肢を `PickOption` と同じ形で見せ、mod 側でビルドコードを組み立てる。

### 4.4 Harmony が必要になる場合（主線ではない）

- `AskString` のインスタンスが特定できないとき、または `OnActivateCommand` の経路が実測で失敗したときに限る。
- 対処は、Rosetta（x86_64）起動を前提に、`Popup.ShowYesNo`/`PickOption`/`ShowConversation`/`AskString` に prefix を当てる経路 B（03 の制御経路 5）である。
- これは arm64 での EACCES（04 §4.6）を抱え込むので、**主線には入れない**。
- 代替の順序: まず直接 API で AskString 自体を避ける（`wait` は自前のループ、数量は API 引数で渡す）。次に `Options.ModernUI` を切り替える（`XRL.UI/Options.cs:34` は public static のフィールド）。これはグローバルに効き、実測もしていない。最後に経路 B を使う。

### 4.5 情報だけの popup の扱い

- M1 では `Popup.Suppress=false` にして、全 popup を LLM に見せる。そのうえで**出現を集計する**（種類、頻度、情報量）。
- 3 週目にその集計を見て、`Suppress=true` にするかを決める。
  - `Suppress=true` にすると `Show`/`ShowBlock` は `MessageQueue.AddPlayerMessage` へ流れる（`Popup.cs:660-665`）。本文はログに残り、LLM は `since_last.messages` で読める。
  - 効くのは `Show`/`ShowBlock` 系だけである（03 §2.8）。
- 設定の値は `manifest.json` に記録する。
- **YesNo と PickOption を自動で答えることはしない。**

---

## 5. スレッドと同期

### 5.1 状態機械（ゲート）

```
NoGame ──(embark / load)──▶ AgentTurn ◀──────────────┐
                              │ Act 実行 → Energy<1000 │ 次の CTA（AutoAct 非アクティブ）
                              │   または AutoAct 開始  │
                              ▼                        │
                            Running ───────────────────┘
                              │  CurrentGameView がモーダル
                              ▼
                     Modal / Picker ──(answer)──▶ Running
                            │ answer 後、ターンが進まずに同じ待機ループへ戻った
                            ▼
                         AgentTurn（制御が戻ったとして op を完了させる）
Running/AgentTurn ──(Game.Running=false)──▶ Dead/Ended
```

モーダルが CTA の中の Act から開いた場合は注意が要る。例えば `move` が泳ぎの確認を開き、LLM が No と答えた場合、エネルギーは消費されない。そのためゲームスレッドは新しい CTA を経ずに、同じ `queue.Take` に戻る。この戻りも「制御が戻った」として扱い、`AgentTurn` に戻して処理中の op を完了させる。

- `AgentTurn`: ゲームスレッドが CTA ハンドラの中で待っている状態。Free と Act の両方を受け付ける。
- `Running`: ゲームスレッドが世界を進めている状態。敵の手番や AutoAct の最中がこれにあたる。
  - Free な観測は、直前のスナップショットに `stale:true` を付けて返す。
  - Act は `busy` で拒否する。
- `Modal`/`Picker`: ゲームスレッドが `Task.Wait` または `getvk` で止まっている状態。受け付けるのは `answer_*` と Free だけである。
- 監視: サーバー側の監視スレッドが 50 ms ごとに `CurrentGameView` と `Game.Running` を見て、状態の遷移を検出する。
  - 例: CTA の中で実行した `move` が泳ぎの確認（`ShowYesNo`）を開いた場合、ゲームスレッドは**自分のハンドラの中で**止まる。監視スレッドがこれを `Modal` として検出する。

### 5.2 どこで止めるか: CTA の中で止め、gameQueue も捌く

`AgentSystem : IPlayerSystem` は `RegisterPlayer` で CTA を購読する（`XRL/IPlayerSystem.cs:7-54`、v1 K3）。`HandleEvent(CommandTakeActionEvent)`（`XRL/IGameSystem.cs:907`）の処理は次のとおり。

```
if (!AgentEnabled || AutoAct.IsActive()) return true;   // 人間の操作中、または AutoAct の最中
The.Core.RenderBase();                                  // 最新の局面を描画し、地図のグリフを取得する（§2.3）
Gate.PublishSnapshot(); Gate.CompletePendingAct();      // 処理中の Act に「制御が戻った」ことを返す
while (Game.Running && AgentEnabled) {
    var w = queue.Take(100ms);                          // 100 ms ごとに区切る
    if (w == null) { GameManager.Instance.gameQueue.executeTasks(); Heartbeat(); continue; }
    w.Run();                                            // Free はここで完結する。Act の中でモーダルが開けばここで止まる
    if (Player.Energy.Value < 1000 || AutoAct.IsActive()) break;   // ターンが進んだので抜ける
    Gate.State = AgentTurn; Gate.PublishSnapshot(); Gate.CompletePendingAct();  // 失敗したか、モーダルの後にターンが進まなかった
    if (Operator.HandoverRequested()) { AgentEnabled = false; Log.Intervention("handover"); }  // §5.5
}
Gate.State = Running; return true;
```

**`gameQueue.executeTasks()` を自分で呼ぶ理由**: 待機中は `RenderBase` が走らないので、`gameQueue` が捌かれない（`XRLCore.cs:2604`）。UI 側で `gameQueue.executeAsync` を待つ処理（例: `Look.cs:284,317`）が止まってしまう。

**`gameQueue` 経由ではなく CTA の中で止める理由**

1. `PlayerTurn` に入らないので、**フォーカス停止（`XRLCore.cs:737-740`）と `ClearMouseEvents` による消去（`:734`）を構造的に避けられる**。
2. v1 で CTA からの直接行動が実証されている（K13/K14）。
3. ゲームはターン制なので、待機がそのまま自然な一時停止になる。RimMolt の Pause Hook に相当する機構は要らない。

### 5.3 HTTP 側の待ち方とタイムアウト

- **Act の HTTP 応答が返るタイミング**は、次のどれかが起きたときである。
  - 次の `AgentTurn` に入った。これには、ターンが進まずに同じ待機ループへ戻った場合（行動の失敗、モーダルへの応答後）も含む。`answer_modal` の応答も同じ規則で返す
  - `Modal`/`Picker` に入った
  - `Dead`/`Ended` になった
  - 45 秒が経った。この場合は `{"status":"pending","op_id":…,"gate":"running"}` を返し、クライアントは `wait_for_turn(op_id)` で続きを待つ。
- 45 秒にする根拠: Claude Code は HTTP の MCP サーバーへの 1 リクエストに既定で 60 秒のタイムアウトを持つ（`MCP_TOOL_TIMEOUT` の説明。https://code.claude.com/docs/en/env-vars ）。その内側に収めるためである。
- Codex CLI では `[mcp_servers.<name>].tool_timeout_sec` で上書きできる。既定値は今回確認できなかったので、設定ファイルで明示する。
- **サーバーは Act を再送しない。** 接続が切れても、ゲーム内の Act は完了する。結果は `status.last_op` に残る。
- **ゲーム側にタイムアウトはない。** クライアントが来なければ、ゲームは永久に待つ。v1 の「500 ms で explore に倒れる」挙動は、LLM と両立しないので捨てる（01 §5.2-4）。

### 5.4 モーダル中の読み取り

- `Modal` の間、ゲームスレッドは `Task.Wait` で止まっていて世界を変更しない。そのため HTTP スレッドから `ConversationUI` の static な状態や `The.Player` を**直接読む**。
- 読み取りには `racy_read:true` を付ける。UI スレッドの `PlayerStatusBar` も同時に読んでいるが、どちらも読むだけである。
- `PopupMessage` の UI オブジェクトは、必ず `uiQueue` 経由で読む。

### 5.5 切断、一時停止、人間への引き継ぎ、起床

| 事象 | 挙動 |
|---|---|
| クライアントの切断や再起動 | ゲームは `AgentTurn` のまま待ち続ける。再接続したら `status` と `get_state` から再開する |
| 一時停止 | ターン制なので不要。配信の都合で止めたいときは、ランナー側で LLM を止めればよい |
| 人間への引き継ぎ | **ゲームの外から要求する。** エージェントが操作している間は `PlayerTurn` に入らないので、キー入力も wish（`CmdWish` は `PlayerTurn` の switch の中にある。`XRLCore.cs:1883`）も読まれない。そのため、wish で `llm_off` を出すことはできない。<br>代わりに、`$PROFILE/llmofqud/HANDOVER` というフラグファイルか、別トークンの `POST /operator/agent` を使い、待機ループが 100 ms ごとに確認する。<br>`AgentEnabled=false` にして待機ループを抜けると、エネルギーが 1000 以上のまま `PlayerTurn` に入るので、人間が操作できる。**証拠ログには「人間の介入」として記録する** |
| 自律への復帰 | 人間は `PlayerTurn` にいるので wish が使える。wish `llm_on` の後、v1 K20 の `ActionManager.SkipPlayerTurn=true` と `Keyboard.KeyEvent.Set()` で `IdleWait` を抜けさせる（`XRLCore.cs:2390-2396`、`Keyboard.cs:110`）。次の CTA から待機に入る |
| 検出されない人間の入力 | `AgentEnabled` のときに `PlayerTurn` に入った、あるいは MCP の応答なしにモーダルが解決した場合は、`intervention_suspected` としてログに残す |

### 5.6 フォーカスの問題

- エージェントの経路は `PlayerTurn` を通らないので、`:737` の停止には当たらない。
- 残る影響は 2 つある。
  1. **AutoAct の各ステップの `kbhit()`**。非フォーカス時は `KeyEvent.WaitOne(200)` で待つ（`Keyboard.cs:940-948`）ので、約 5 歩/秒に抑えられる。配信のペースとしてはむしろ好都合である。消したい場合は、UI スレッドのタスクで `XRLCore.bThreadFocus=true`（`XRLCore.cs:223`）を維持すればよい。
  2. **Unity のメインスレッドが止まる問題**。非フォーカス時に Unity の `Update` が止まると、`uiQueue.executeTasks()`（`GameManager.cs:2963`）も止まり、**モーダルに答えられなくなる**。これを防ぐため、`OptionMusicBackground=Yes`（`Application.runInBackground` に連動する。`XRL.UI/Options.cs:1445-1454`）を隔離プロファイルで既定にし、mod も UI スレッドで `Application.runInBackground=true` を設定する。実測は probe P5。

---

## 6. 通信と配置

### 6.1 通信路

- **MCP の Streamable HTTP を、POST のみ、応答は `application/json` だけ**という形で実装する。SSE は使わず、状態も持たない。
  - GET と DELETE には `405` を返す。
  - `Mcp-Session-Id` は無視し、発行もしない。
  - `initialize` では、クライアントが要求した `protocolVersion` が 2025-06-18 か 2025-11-25 ならそのまま返す。M1 ではこの 2 つだけを名乗る。
  - 2026-07-28 の stateless 形（仕様: https://github.com/modelcontextprotocol/modelcontextprotocol の `specification/2026-07-28/basic/transports/streamable-http.mdx`）は、全体を実装するまで名乗らない。Claude Code は既定で HTTP サーバーにこの版を問い合わせ、応答がなければ旧版に落ちる（`MCP_PROTOCOL_NEGOTIATION`、https://code.claude.com/docs/en/env-vars ）。一部しか話せない版を名乗ると、クライアントがその版に確定してしまうおそれがある。
  - notification には `202` を返す。
  - 実装するメソッドは `initialize`、`tools/list`、`tools/call`、`ping` の 4 つだけである。
- **待ち受け**: `System.Net.HttpListener` で `http://127.0.0.1:8787/mcp/` を開く。ポートはオプションで変えられる。
  - 認証は `Authorization: Bearer <random>`。トークンは起動時に `$PROFILE/llmofqud/token` へ書く。RimMolt が 9/15 に同様のキー認証を入れた（02 §1.1）。
  - 受け付けは専用スレッドで同期の `GetContext()` を回す。処理は固定の 4 本のワーカーで行う。`wait_for_turn` が長く待っている間にも `status` に答えられるようにするためである。
  - 応答には `Content-Length` を必ず付ける。chunked は使わない。
- **代替**: `HttpListener` が動かない場合は `TcpListener`（`System.dll` にあることを確認済み）の上に、HTTP/1.1 の最小限の実装（POST、Content-Length、keep-alive）を約 150 行で書く。
- **シリアライズ**: Newtonsoft.Json 13.0.2（`Managed/`。ゲーム本体の `XRL/ModManager.cs:10` も `using` している）。
  - DTO はゲームスレッドで組み立てる。`GameObject` への参照は持たせず、プリミティブだけにする。
  - JSON への変換は HTTP スレッドで行う。
- **Claude Code への登録**: `claude mcp add --transport http qud http://127.0.0.1:8787/mcp --header "Authorization: Bearer $(cat …/token)"`。
- **Codex への登録**: `config.toml` の `[mcp_servers.qud] url=…, bearer_token_env_var=…, tool_timeout_sec=60`。

### 6.2 Mono のネットワークのリスクと確かめ方

| リスク | 確かめ方（probe） |
|---|---|
| Roslyn の参照に `System.dll` と `Newtonsoft.Json` が入るか。述語が参照に加えるのは、ロード済みで Location を持つアセンブリだけ（`ModManager.cs:389-416`） | P0: 両方を使う最小の mod で、`build_log.txt` に `Success :)` が出るか |
| Mono の managed 実装の `HttpListener` が macOS arm64 の Unity 内で 127.0.0.1 に bind できるか。ファイアウォールのダイアログは出るか | P1: `curl -X POST` で `initialize` と `tools/list` を送る。`claude mcp list` で connected になるか |
| keep-alive、長時間の接続、同時接続 | P1b: `ping` を 1,000 回送って p50/p95 を取る。`wait_for_turn` の 45 秒の long-poll と `status` を並行して送る。これを 2 時間連続で行う |
| スレッドプールの枯渇（Unity の Mono） | 専用スレッドだけを使い、`async` による ThreadPool 依存を避ける。P1b で遅延を監視する |
| 起動の多重化（`ModSensitiveCacheInit` は mod のビルド後と起動時の 2 回呼ばれうる。`XRL/ModManager.cs:340-372`） | static なガードと、`AppDomain.SetData` による一度きりの起動。P0 のログで起動が 1 回かを確認する |
| ポートの残留 | プロセスが終われば解放される。mod の再読み込みは起動時にしか起きないので、プロセスあたり 1 サーバーになる |

### 6.3 プロセスの配置

```
┌ CoQ.app（arm64 ネイティブ、-savepath $PROFILE） ───────────────┐
│ Unity main thread: uiQueue → PopupMessage.OnActivateCommand     │
│ Game thread: ActionManager → CTA → Gate の待機ループ            │
│ LLMOfQud mod: McpServer（HttpListener スレッドとワーカー 4 本） │
│              EvidenceLog（JSONL）、Overlay（GET /overlay）      │
└───────────▲──────────────────────────────────────────────────────┘
            │ HTTP 127.0.0.1:8787/mcp（Bearer）
┌───────────┴──────────────┐   ┌─────────────────────────┐
│ claude -p（または codex exec） │   │ OBS: ゲームの窓と       │
│ runner.sh（約 50 行）    │   │ /overlay の browser src │
└──────────────────────────┘   └─────────────────────────┘
```

- `runner.sh` はセッションが切れたら新しいセッションを始めるだけのループで、brain ではない。
- 起動フラグ: `--mcp-config qud.json --strict-mcp-config --allowedTools "mcp__qud__*" --append-system-prompt-file play.md --output-format stream-json`。
- 各セッションの最初の指示は「`status` → `notes_read` → `get_state` を呼んでから続けよ」とする。
- **Bash、ファイルの読み書き、WebSearch、WebFetch はすべて禁止する。** 記憶は MCP の `notes_*` だけを通す（§7）。

### 6.4 brain の言語と、後で差し替える部分

- **mod**: C# 9 で書き、Roslyn でコンパイルされるソースとして配置する。v1 と同じく DLL は置かない。
- **初期の brain**: なし（Claude Code または Codex CLI）。
- **後の brain**: Python（uv）を推す。オーナーの他のリポジトリが Python で、MCP の Python SDK も成熟している。MCP はただの HTTP JSON-RPC なので、SDK を使わなくても書ける。

自作 brain が置き換えるのは次の部分である（mod は変えない）。

1. **文脈の予算管理**: 観測のうち何を残すか、何ターンごとに要約するか（GPP の 100 ターン要約、Continual Harness）。
2. **モデルの選び分け**: 定型の手番は安いモデルに、危機と会話は強いモデルに任せる。
3. **危機のエッジトリガー**（P8）と、ループの検出。
4. **思考テキストの配信**: 思考のテキストをオーバーレイへ直接流す。
5. **コストとレート制限の制御**。

この順番で、必要が見えたものから差し替える。MCP のツール面は変えないので、同じ証拠ログの形式のまま比較できる。

---

## 7. 記憶と知識

### 7.1 何を残すか

**mod 側、周回ごと**（`$PROFILE/llmofqud/runs/<run_id>/`）

- `manifest.json`: 開始時に確定する内容。ゲーム版、mod のソースのハッシュ、オプション（`OptionAllowSaveLoad`、`OptionDisablePermadeath`、`Popup.Suppress` の方針など）、ゲームモード、ビルドコードとその出所、クライアントとモデル名、プロンプトファイルのハッシュ。
- `evidence.jsonl`: MCP の全往復。wall time、ゲームのターン、ゲートの状態、`sha256(prev_line)` による連鎖を含む。
- `events.jsonl`: `IGameSystem` のフック（クエスト、XP、ゾーン、死亡、wish の実行、人間介入の疑い）。
- `notes.md`: LLM が書く唯一の記憶（§7.2）。

**mod 側、周回をまたいで**

- `lessons_global.md`: 死亡したときに LLM 自身が書く振り返り。次の周回の最初に読む。規則は rimworld-ai-manager の POSTMORTEM に倣い、「センサー、ルール、閾値のどれが欠けていたか」を書かせる。

**クライアント側**

- Claude Code のトランスクリプトと `stream-json` の出力（ランナーが保存する）。思考テキストの監査に使う。

### 7.2 LLM が書くもの

`notes.md` は、RimMolt の配信者の `RIMWORLD_LEARNING.md` の構造（02 §1.1.2）に倣い、節を固定する。

| 節 | 上限 | 内容 |
|---|---|---|
| `RUN_STATE` | 600 tokens | いまどこで、何を目指していて、次に何をするか |
| `GOALS` | 400 tokens | 3 層: 主目標、中間目標、直近の目標 |
| `LESSONS` | 40 項目 | 学んだこと |
| `PLACES` | 800 tokens | 場所についての記録 |
| `PEOPLE` | 600 tokens | 人物についての記録 |

- `notes_write` は節ごとの置換にする。上限を超えた書き込みは拒否し、LLM に要約させる。
- 起動時に読むのは `RUN_STATE` と `GOALS` だけで、残りは必要なときに `notes_read(section)` で読む。

### 7.3 知識ベースとネタバレの方針

| 段 | 中身 | クリアを主張する周回 | 補助付きの周回 |
|---|---|---|---|
| T0 | `Manual.xml`（約 6k tokens、04 §3.1）。system prompt に同梱する | 可 | 可 |
| T1 | ゲーム内で見える説明文: `Skills.xml`、`Mutations.xml`、`ActivatedAbilities.xml` の description | 可（`knowledge_search` で引く） | 可 |
| T2 | `Quests.xml`、`Conversations.xml`（先のステップと分岐が書かれている＝ネタバレ） | **不可** | 可 |
| T3 | 公式 Wiki（CC BY-NC-SA 4.0。リポジトリに再配布しない。ローカルでの取得だけ） | **不可** | 可 |

- **消せないもの**: モデルが事前学習で持つ CoQ の知識は取り除けない。これは主張に明記する。
- ゲーム内のジャーナルやクエストの記述は、プレイヤーが正当に見られる情報なので、常に公開する。

---

## 8. 評価と証拠

### 8.1 クリアの判定基準（機械で確認できるもの）

- エンディングは会話パーツ `EndGame : IConversationPart` から始まる（`XRL.World.Conversations.Parts/EndGame.cs:28`）。
- `EndGame.Start()` は `UnlockAchievement()` で `Achievement.CAVES_OF_QUD` を解除し、クレジットと Coda に進む（`:247-294`）。
- 結末の種類はゲーム状態 `EndType` に入る（Brightsheol、Marooned、Return、Covenant、Accede、Launch。`:67-113`）。
- **判定**: `events.jsonl` に、`EndType` が空でない値になった記録と `EndGame.Start` への到達がある。そして同じ時刻帯の `evidence.jsonl` に、それを引き起こした `answer_modal`（会話の選択）がある。
- **最終段が会話で決まる**ので、会話モーダルの経路（§4）は、クリアに直結するクリティカルパスである。
- **wish による近道を塞ぐ**: `goend`/`gocoda`/`gocredits` の wish が存在する（`EndGame.cs:296-324`）。塞ぎ方は、実行を検出することではなく、**そもそも到達できない構造にする**ことである。
  - wish への入口を callers から調べると、次の 2 つしかない。
    - `PlayerTurn` の switch にある `CmdWish` → `WishManager.AskWish()` → `Wishing.HandleWish`（`XRLCore.cs:1883-1887`、`XRL.Wish/WishManager.cs:105-115`）と、`CmdWishMenu`
    - プレイヤーに付く `WishMenu` の `CommandEvent`（`XRL.World.Parts/WishMenu.cs:180-185`、`:153,167`）
  - 前者は、`AgentEnabled` の間は `PlayerTurn` に入らない（§5.2）ので届かない。後者は、`use_ability` が登録済みの能力コマンドしか通さない（§3.1）ので届かない。
  - したがって、wish が実行されうるのは、ログに残る引き継ぎ（§5.5）の後に人間が `PlayerTurn` を操作した場合だけである。
  - **主張する周回では、引き継ぎが 0 件であることを条件にする。** 補助的に、`AskWish` が出す `MetricsManager.LogEvent("Wish:"…)`（`WishManager.cs:113`）がログに残るかも確認する。
  - この「到達できない」という主張は grep による静的な確認なので、callers の網羅性はゲームの更新ごとに調べ直す。

### 8.2 進行の指標

- **主指標**: メインクエストの完了ステップ数（`XRLGame.FinishedQuests` と `Quest.StepsByID`。`XRL.World/Quest.cs:11-113`）。
  - 対象になるクエスト集合は、`Base/Quests.xml` にある 28 件から、**最初の主張周回より前に固定して公開する**（事前登録）。
  - 暫定の候補（順序は要検証）: What's Eating the Watervine? → Fetch Argyve a Knickknack → Fetch Argyve Another Knickknack → Weirdwire Conduit... Eureka! → A Canticle for Barathrum → More Than a Willing Spirit → Decoding the Signal → The Earl of Omonporch → A Call to Arms → … → Tomb of the Eaters → Reclamation → EndGame。
- **副指標**: レベル、到達した最深部、発見したゾーンの数、死亡回数と死因、1 判断あたりのトークン数、`intervention` の件数、ツールのエラー率（rimagent の 10.8% と比べる）。

### 8.3 再現性

- **完全な再現はできない**。戦闘は種を固定しない静的な RNG を使う（`XRL.Rules/Stat.cs:26-36`、01 K27）。
- 代わりに「条件の再現」を保証する。
  - ゲームを固定したコピーから起動する（§10）。
  - mod のハッシュ、プロンプトのハッシュ、オプションを `manifest.json` に記録する。
  - モデルの ID を記録する。
- 監査のために、200 ターンごとにセーブを複製する。
- 配信の録画は、第 3 者から見た証拠になる。

### 8.4 この設計が支えられる主張

| 強さ | 条件 |
|---|---|
| 強 | Classic（パーマデス）。ゲームプレイへの人間の入力ゼロ（引き継ぎ 0 件。ビルドコードの選択は宣言したうえで許す）。画素を一切使わないテキスト観測。T2/T3 の知識なし。Web アクセスなし。ハーネスを公開。`EndType` に到達 |
| 中 | Roleplay（チェックポイントあり）。チェックポイントからの復帰はすべて死亡として数え、回数を公開する |
| 弱 | Wander、補助付き（T2/T3）、人間の再指示が 1 回以上ある、など |

**インフラの再起動とゲームプレイへの介入を分けて記録する。** ゲームのクラッシュ、ランナーの再起動、MCP の再接続は「インフラ」として数える。セーブの状態には触れない。ゲームプレイへの入力は、人間がゲーム内で行った操作、再指示、wish である。

### 8.5 先行事例、主張できること、SOTA ならクリアできて当然か（ユーザーの質問への回答）

**既にクリアした人、LLM に挑戦させた人はいるか**

- 今回の検索では**見つからなかった**。検索した語は次の 5 つ（2026-09-25）。
  - `"Caves of Qud" LLM agent plays Claude OR GPT OR Gemini`（結果なし）
  - `Caves of Qud AI agent LLM autonomous play MCP mod`
  - `Claude plays "Caves of Qud"`
  - `Caves of Qud AIにプレイさせる LLM クリア`
  - 02 の否定検索（Brogue、Cogmind、ADOM）
- 見つかったのは、人間の攻略、日本語化 mod、LLM でのコード生成への注意喚起だけだった。
- これは**不在の証明ではない**。主張するときも「2026-09-25 時点で、公開された報告を上記の検索では確認できなかった」と書くのが限度である。

**SOTA モデルならクリアできて当然か**

**当然とは言えない**と考える。根拠は次のとおり。

1. **近いジャンルでも到達率が低い。** NetHack は BALROG の評価で進行度が低いままで（02 §1.5。o1-preview で 1.5%）、知っていても行動に移せない knowing-doing gap が報告されている。
2. **テキスト操作の先行事例でも補助があった。** Claude Plays Pokémon は長く行き詰まった。RimMolt のクリアは、スクリーンショットの併用と人間の 1 回の再指示の上に成り立っていた（02 §1.1.2）。
3. **CoQ はとにかく長い。** 人間でも Roleplay で約 60 時間かかるという目安がある（攻略サイトの記述で [C] 級。https://gemelog.jp/games/caves-of-qud/walkthrough/ ）。LLM の判断は数千〜1 万数千回と推定する（§2.2）。長い周回の途中で、要約による忘却やループが起きることは GPP で観察されている。
4. **Classic では 1 回のミスで終わる。**
5. **ハーネスの穴が詰みになる。** モーダルが見えない、または答えられない状態は、どれか 1 つでもあれば止まる。

逆に有利な点もある。

- クエストの導線があり、NetHack より目標が明示的である。
- ターン制なので、考える時間に制約がない。
- テキストの情報量が多い。

**主張としての価値**

- 「ハーネスが透明なまま、画素を使わない観測だけで、公開されている範囲では初めて CoQ のエンディングに到達した」という主張になりうる。
- 成功がモデルの力なのかハーネスの力なのかを分けるために、次のものを公開する。
  - ツールの一覧と、各ツールが何を自動化しているか
  - 介入の件数
  - ネタバレの段階
  - 失敗した周回の記録

---

## 9. 配信適性

- **視聴者が見るもの**: 通常のゲームの窓（タイルモード、Modern UI）。CTA で待つ前に `RenderBase` を呼ぶ（§2.3）ので、LLM が考えている間も現在の局面が映る。Modern のポップアップもそのまま画面に出て、LLM が答えると閉じる。
- **オーバーレイ**: 同じ `HttpListener` で `GET /overlay`（静的な HTML）と `GET /overlay/feed`（JSON のポーリング。認証なし、localhost のみ）を返す。OBS の browser source から読む。表示するものは次のとおり。
  - `narrate` の文字列。日本語で書かせてもよい。ゲームは英語のまま
  - 直近 5 件のツール呼び出し
  - ゲートの状態（`thinking…` と経過秒）
  - 目標（`GOALS`）
  - メインクエストの進行バー、ターン数、死亡回数
- **ペース**:
  - ゲート側に `min_act_interval_ms`（既定 300 ms）を置く。
  - AutoAct は `OptionAutoexploreRate`（04 §2.3）と、非フォーカス時の `kbhit` の 200 ms（§5.6）で抑える。
  - v1 K15 の「数秒で 4 ゾーンを横断する」暴走は、Act ごとに CTA へ戻る構造と、この 2 段のペーシングで防ぐ。
- **無音の時間**: LLM が考えている 5〜30 秒は、オーバーレイの `thinking` 表示と `narrate` で埋める。思考のテキストをそのまま流す機能は、自作 brain の段階で入れる（§6.4）。
- **視聴者のチャット**: 取り込まない（A9。プロンプトインジェクション対策）。

---

## 10. プラットフォームと更新耐性

### 10.1 Apple Silicon

- **arm64 ネイティブで起動する。Harmony は使わない（`[HarmonyAttribute]` の型を 1 つも定義しない）。** これで `ApplyHarmonyPatches` は何もしない（`XRL/ModInfo.cs:845-853`）。04 §4.6 の EACCES とも、Rosetta とも無関係になる。
- 起動の例: `SteamAppId=333640 SteamGameId=333640 "<pinned>/CoQ.app/Contents/MacOS/CoQ" -savepath "$PROFILE" -logFile "$PROFILE/Player.log"`（04 §4.9）。

### 10.2 隔離プロファイルと QudJP との共存

- `$PROFILE=~/Library/Application Support/Freehold Games/CavesOfQud-llm` を使う。
- 事前に書いておく設定:
  - `PlayerOptions.json`: `OptionAllowCSMods=Yes`、`OptionAllowSaveLoad` は主張の強さに合わせて決める、`OptionCapInputBuffer=No`、`OptionMusicBackground=Yes`（`runInBackground` のため）、`Language=en`
  - `ModSettings.json`: LLMOfQud だけを有効にする
- **QudJP は入れない。** QudJP は Harmony で 1,693 のメソッドをパッチする（03 §4.2）ので、Rosetta が要る。さらに観測するテキストが日本語になり、ハーネスの外にある変更が主張を汚す。
- 本番のプロファイル（QudJP、日本語）には手を付けない。

### 10.3 ゲームの更新への耐性

- **ゲームのバイナリを固定する**: 主張する周回は、`CoQ.app` の固定コピー（QudJP の `~/Games/CavesOfQud-stable-ref` と同じ考え方）から起動する。Steam の更新による版ずれを防ぐためである。
- **表面の自己診断**: 起動時に `SurfaceCheck` が、依存するメンバーをリフレクションで名前とシグネチャから引く。
  - 対象: `Popup.WaitNewPopupMessage`、`PopupMessage.OnActivateCommand/commandCallback/controller`、`ConversationUI.CurrentNode`、`TradeUI.PerformOffer`、`AutoAct.Setting`、`GameManager.CurrentGameView`、`StatusScreen.BuyStat` ほか。
  - 欠けているものがあれば、そのメンバーに依存するツールを無効にし、`status` で報告する。
- 引用は行番号よりもシンボル名を主キーにする（01 §2.2 の教訓）。
- 版の分岐には `BUILD_2_0_211` シンボル（`XRL/ModManager.cs:127-134`）を使う。

---

## 11. マイルストーン（最初の 3 週間）

### 11.1 最初に行う runtime probe（1 週目の前半）

| # | probe | 合格の条件 |
|---|---|---|
| P0 | コンパイルとロード: Newtonsoft と `System.Net` を使う最小の mod を、隔離プロファイルで arm64 ネイティブ起動して読み込む | `build_log` に `Success :)`。`Player.log` に `[LLMOfQud] server up` が 1 回だけ出る |
| P1 | bind と MCP: `curl` で `initialize`/`tools/list` を送る。`claude mcp add` と `claude mcp list` を実行する。Claude Code は、既定の版交渉と `MCP_PROTOCOL_NEGOTIATION=legacy` の 2 通りで試す。Codex でも接続する | 両方のクライアントで `ping` が往復する。p95 が 20 ms 以下。どちらの版交渉でも接続できる |
| P1b | 耐久: long-poll と `status` を並行して送り続ける。1,000 回と 2 時間 | エラーなし。ファイルディスクリプタが漏れない |
| P2 | CTA での待機: `AgentEnabled` の状態で 10 分待機する | UI が固まらない。Look のツールチップ（`gameQueue.executeAsync`）が応答する。窓を非フォーカスにしても待機と行動が続く |
| P3 | Act の往復: `move`/`attack`/`wait` を `curl` から実行する | エネルギーが消費され、次の CTA で結果が返る。塞がれた移動は `ok:false` になり、ターンが進まない |
| P4 | モーダル: `ShowYesNo`（泳ぎの確認、または mod の wish でテスト用の popup を出す）、`PickOption`、Joppa の Mehmet との会話 | `CurrentGameView` で検出でき、`uiQueue` で中身を読め、`OnActivateCommand` でゲームスレッドが再開する。**窓が非フォーカスでも成功する** |
| P5 | `runInBackground`: 非フォーカスのまま P4 を 20 回繰り返す | 20 回すべて成功する |
| P6 | AutoAct: CTA から `"?"`、`"M x,y"`、`".10"` を設定する | 同じセグメントで開始される。中断理由（`AutomoveInterruptBecause`）が取れる |

### 11.2 週ごとの計画

**1 週目: マイルストーン 1「最初の自律 LLM ターン」**

- P0〜P6 を実施する。
- 実装するもの: `status`、`get_state`、`move`、`attack`、`wait`、`answer_modal`（Popup と YesNo）、証拠ログ。
- 合格の条件:
  - 人間が宣言したビルドコードで Joppa から開始する。
  - Claude Code（`--allowedTools mcp__qud__*`）が、観測を読み、**自分で選んだ行動を 50 ターン連続で実行する**。人間の入力はゲームの起動とキャラクター作成だけ。
  - `evidence.jsonl` で、その 50 ターンすべてを追跡できる。

**2 週目: 探索の基本サイクルと会話**

- 実装するもの: Free ツールの全部、`autoexplore`/`travel`/`rest`/`stairs`、`talk` と会話モーダル、`item`/`equip`、`notes_*`、`narrate`、`runner.sh`。
- 合格の条件: Roleplay モードで「What's Eating the Watervine?」を自律で完了する。
- 同時に行うこと: ポップアップの出現を集計する（§4.5）。

**3 週目: モーダルの経路を一通り揃える**

- 実装するもの: `spend_points`（レベルアップ）、`trade`、`use_ability` とピッカー（`fire`/`throw` を含む）、オーバーレイ v0、キャラクター作成の probe（§4.3）、`SurfaceCheck`。
- 合格の条件:
  - 4 時間の無人運転ができる。
  - Argyve の 2 つのクエストを完了する。
  - 詰まりの分類（モーダル、ループ、死亡）が `status` と `events.jsonl` から出せる。

---

## 12. 最もリスクの高い前提（反証可能な形で）

| # | 主張 | なぜ重要か | 懐疑的な読み手が読むべき箇所 | 実測が必要か |
|---|---|---|---|---|
| R1 | CTA ハンドラの中でゲームスレッドを無期限に待たせても（100 ms ごとに区切り、`gameQueue.executeTasks()` を自分で呼ぶ）、UI スレッドは正常に動き続ける。そして「`Energy<1000` か `AutoAct` が始まるまで抜けない」を守れば、`PlayerTurn` に落ちることはない | 同期モデル全体の土台であり、フォーカス停止の回避もこれに依存する | `XRL.Core/ActionManager.cs:743-815,1580-1625`、`XRL.Core/XRLCore.cs:2600-2665`、`XRL.World/CommandTakeActionEvent.cs:28-38` | はい |
| R2 | Modern のポップアップは、`uiQueue` の上で `PopupMessage.OnActivateCommand(実物の QudMenuItem)` を呼べば解決する。そのとき `complete.Task.Wait()` が解けてゲームスレッドが再開する。Harmony は要らない | Harmony と Rosetta を捨てられるかどうかが、これで決まる | `XRL.UI/Popup.cs:801-921,1571-1614,1740-1756,2251-2275`、`Qud.UI/PopupMessage.cs:721-782,926-958` | はい |
| R3 | 「応答待ちのモーダルがある」は、`CurrentGameView=="PopupMessage"` と、UI スレッドで読む `PopupMessage.commandCallback != null` の組み合わせで確実に判定できる。`PickTarget` のビューも同様に信頼できる。`PopGameView` が `Task.Wait` の後で遅れて呼ばれても、二重に検出しない | Act の完了の判定と、モーダルの検出が崩れると、エージェントは「見えない停止」（A1）に陥るか、同じモーダルに二度答える | `GameManager.cs:469-480,1493-1530`、`XRL.UI/Popup.cs:824-829,908-910`、`Qud.UI/PopupMessage.cs:779,926-933`、`XRL.UI/PickDirection.cs:31`、`XRL.UI/PickTarget.cs:87,381` | はい |
| R4 | Mono の `HttpListener` は、macOS arm64 の Unity プロセスの中で 127.0.0.1 に bind でき、Claude Code や Codex の Streamable HTTP の POST を数時間安定して処理する（keep-alive と並行の long-poll を含む） | 通信路が成立するかどうか。成立しなければ TcpListener の自作実装に移る | `XRL/ModManager.cs:389-416`、`Managed/System.dll` の `HttpListener*` 型 | はい |
| R5 | `runInBackground` を有効にすれば、窓が非フォーカスでも Unity の `Update` が `uiQueue` を処理し続ける。エージェントの経路は `XRLCore.cs:737` の停止に当たらない | 配信と無人運転で、モーダルに答えられるかどうか | `XRL.Core/XRLCore.cs:734-740`、`GameManager.cs:404-425,1920-1929,2963`、`XRL.UI/Options.cs:1445-1454`、`ConsoleLib.Console/Keyboard.cs:938-954` | はい |
| R6 | Modern のフルスクリーン UI の中の操作（装備、スキル、能力値、変異、取引）は、すべてゲームスレッドの直接 API で置き換えられる。その副作用として出る確認は `Popup.*` の経路で答えられる | UI を開かない方針が成り立つかどうか | `Qud.API/EquipmentAPI.cs:378-501`、`XRL.World/InventoryActionEvent.cs:110`、`XRL.UI/StatusScreen.cs:62,575`、`Qud.API/MutationsAPI.cs:95`、`XRL.UI/SkillsAndPowersScreen.cs:141-229`、`XRL.UI/TradeUI.cs:150-308,1296`、`Qud.UI/CharacterStatusScreen.cs:343-425` | はい（静的には一部確認済み） |
| R7 | CTA で `AutoAct.Setting` を設定すると、同じセグメントの AutoAct 分岐で実行される。AutoAct のステップごとに発火する CTA ですぐ `true` を返せば、自動探索と移動が正しく進む。中断理由も取れる | LLM の呼び出し回数を 1 桁減らせるかどうか（P7） | `XRL.Core/ActionManager.cs:789-815,850-1441`、`XRL.Core/XRLCore.cs:1920-1925`、`XRL.World.Capabilities/AutoAct.cs:51,114,414-460`、`XRL.World/GameObject.cs:74` | はい |
| R8 | エンディングは通常の会話の選択（`EndGame` の会話パーツ）で到達できる。`EndType` のゲーム状態と `EndGame.Start` への到達は、クリアの信頼できる判定になる | 主張の判定基準であり、会話の経路がクリアに直結する | `XRL.World.Conversations.Parts/EndGame.cs:28,67-113,247-324` | はい（終盤のセーブでの確認が要る） |
