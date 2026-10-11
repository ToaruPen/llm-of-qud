# 03. CoQ エンジン表面調査: 非視覚的な観測と制御の経路

> Assignment C(探索フェーズ、証拠収集のみ)。設計判断は含めない。推論には **[推論]** と明記する。

## 0. 前提と引用規約

| 項目 | 内容 |
|---|---|
| 主な引用元 | `NEW/` = 一時作業領域（scratchpad）の `decomp-new`(`decompile.log` に `exit=0` があることを確認済み) |
| 比較用 | `STABLE/` = `~/Dev/coq-decompiled_stable`(AssemblyVersion 2.0.211.50) |
| NEW のバージョン | `NEW/Properties/AssemblyInfo.cs` は `AssemblyVersion("2.0.211.56")`。想定されていた 2.0.214.x ではなかった。`CoreVersion` は Assembly 名のバージョンそのもの(`NEW/XRL/XRLGame.cs:106`)で、Mod コンパイル時には `BUILD_{Major}_{Minor}_{Build}` シンボルになる(`NEW/XRL/ModManager.cs:127-134`)。そのため NEW でのシンボルは `BUILD_2_0_211`、`MarketingVersion` は `1.0.5`(`NEW/XRL/XRLGame.cs:104`)。インストール先の `Managed/Assembly-CSharp.dll` は 2026-09-25 17:06 に書き換えられている。ここから「今回の Steam 更新後の実体が 2.0.211.56 である」と見るのが自然 **[推論]**。ただし AssemblyVersion がストア上のビルド番号と一致する保証はない。 |
| v1 の引用 | v1 は `decompiled/...`(2.0.210 系)の行番号を使っていた。本書では NEW の行番号に読み替えたものを §7 にまとめる。 |
| 外部情報 | URL を併記する。 |
| ローカルの実行ログ | `Player-prev.log` = `~/Library/Logs/Freehold Games/CavesOfQud/Player-prev.log`(2026-08-14 の起動。ゲーム版 2.0.211.51。読むだけ)。Workshop 3718988020 = `~/Library/Application Support/Steam/steamapps/workshop/content/333640/3718988020/`(QudJP。読むだけ) |

v1 の既知事項(本書の出発点):

- tile モードでは `_Char=='\0'` になり、ASCII glyph は `BackupChar` に退避される。`ConsoleChar.Copy` は `BackupChar` をコピーしないため、`CurrentBuffer` / ScrapBuffer を読むと空白になる。解決策は `XRLCore.RegisterAfterRenderCallback` で source buffer を読むこと(`archives/llm-of-qud-v1/docs/memo/phase-0-b-tile-mode-finding-2026-04-25.md`)。
- 構造化状態(HP・位置・可視エンティティ)はゲームスレッドの `BeginTakeActionEvent` で JSON 化する(phase-0-c exit memo)。
- 行動は `CommandTakeActionEvent`(CTA)の中で `GameObject.Move` / `AttackDirection` を直接呼ぶ。`CommandEvent.Send("CmdMoveE")` は PlayerTurn の外では何もしない。`PreventAction` は異常時の防御にだけ使う(phase-0-f exit memo、`mod/LLMOfQud/LLMOfQudSystem.cs:441-707`)。
- 通信は Mod 側が `System.Net.WebSockets.ClientWebSocket` のクライアントになる構成だった(`mod/LLMOfQud/BrainClient.cs:6,28,259-305`)。JSON は手書きで組み立てていた(`SnapshotState.cs`)。

---

## 1. テキスト画面(ConsoleLib.Console)

### 1.1 データ構造

| 要素 | 事実 | 引用 |
|---|---|---|
| `ConsoleChar` のフィールド | `_Tile`(string)、`BackupChar`、`_Char`、色、`HFlip`/`VFlip`、`imposterExtra`/`soundExtra` | `NEW/ConsoleLib.Console/ConsoleChar.cs:55-73` |
| `ConsoleChar.Set(RenderEvent)` | `_Tile = Event.Tile`。`_Tile != null` のときは `_Char='\0'` として `BackupChar = RenderString[0]` を入れる。`_Tile == null` のときは `_Char = RenderString[0]` として `BackupChar='\0'` を入れる | `NEW/ConsoleLib.Console/ConsoleChar.cs:392-420` |
| `ConsoleChar.Copy` | `_Char`・`_Tile`・色・flip・backdrop・extras はコピーする。**`BackupChar` はコピーしない** | `NEW/ConsoleLib.Console/ConsoleChar.cs:360-375` |
| `Zone.Render` | 全セルに対して `Map[j][i].Render(renderEvent, Visibility, Light, Explored, ...)` を呼び、続けて `consoleChar.Set(renderEvent)` を呼ぶ。`WantsToPaint` の Paint も行う | `NEW/XRL.World/Zone.cs:5704-5762` |
| tile を付ける条件 | `Cell.Render` 内の `flag = Globals.RenderMode == RenderModeType.Tiles` が真のときだけ `E.Tile` を設定する(floor の PaintTile、オブジェクトの `render2.Tile`)。例外として `OverlayTile` 文字列プロパティは描画モードに関係なく Tile を設定する | `NEW/XRL.World/Cell.cs:547, 589-592, 681-705, 917-921` |
| `Options.UseTiles` | `Globals.RenderMode == RenderModeType.Tiles`。設定元は `OptionUseTiles`(既定は Yes) | `NEW/XRL.UI/Options.cs:606, 1288-1295`、`StreamingAssets/Base/Options.xml:22` |
| `ScreenBuffer.ToString()` | 全セルの `.Char` を行ごとに連結する組み込みのテキストダンプ。`BackupChar` は見ないので tile モードでは NUL だらけになる | `NEW/ConsoleLib.Console/ScreenBuffer.cs:207-219` |
| `ScreenBuffer.WithMap()` / `WithBase()` | 任意のバッファに `RenderMapToBuffer` / `RenderBaseToBuffer` を実行させる | `NEW/ConsoleLib.Console/ScreenBuffer.cs:163-173` |
| バッファサイズ | `_Buffer` は 80x25(`bExtended` のときは 80x33)。`TextConsole` 側は `CurrentBuffer` / `ScrapBuffer` / `ScrapBuffer2` を 80x25 で持つ | `NEW/XRL.Core/XRLCore.cs:3588-3601`、`NEW/ConsoleLib.Console/TextConsole.cs:89-95` |

v1 の発見は NEW でも有効。変わったのは実装位置で、v1 では `BackupChar` の書き込みが `Zone.cs` にインラインで書かれていたが、NEW では `ConsoleChar.Set` の中に移っている(STABLE でも同様に `Zone.cs:5743` が `consoleChar.Set(renderEvent)` を呼ぶ)。`BackupChar` を読む箇所は `PickTarget.cs:540,638`、`MissileWeapon.cs:459`、`ThinWorld.cs:729,772` の 3 ファイル。いずれもターゲット表示などで glyph を一時的に復元するためのもの。

### 1.2 描画パイプラインとバッファの流れ

```
[ゲームスレッド] XRLCore.RenderBase()  (NEW/XRL.Core/XRLCore.cs:2600-2665)
  ├─ CoreThread 上なら gameQueue.executeTasks()             :2602-2605
  ├─ AutoAct が休息・待機中("r","z",".N")なら早期 return   :2614-2618
  ├─ RenderBaseToBuffer(_Buffer)                            :2645
  │    ├─ Zone.Render(Buffer)                               :2460 / :2505
  │    ├─ AfterRenderCallbacks(this, _Buffer)               :2461-2465 / :2506-2509
  │    ├─ ParticleManager.Render / ConfusionShuffle         :2522-2526
  │    └─ Sidebar.Render(Buffer)                            :2474 / :2531
  └─ _Console.DrawBuffer(_Buffer, imposterFrame)            :2665
       └─ lock(BufferCS){ CurrentBuffer.Copy(Buffer) }      TextConsole.cs:149-161
            ※ bSkipIfOverlay && ModernUI のときはコピーしない
```

- **AfterRenderCallback の引数は常に静的な `_Buffer`**。`RenderBaseToBuffer(ScreenBuffer Buffer)` は引数の `Buffer` に描画するのに、コールバックに渡すのは `_Buffer` になっている(`NEW/XRL.Core/XRLCore.cs:2464, 2508`)。このため `_Buffer` 以外に描画する経路では、コールバックが古いバッファを受け取る。該当するのは `WaitNewPopupMessage` の `AllowRenderMapBehind` ループ(`NEW/XRL.UI/Popup.cs:898-904`)と `ScreenBuffer.WithBase()`。`RenderMapToBuffer` だけは正しく引数の `Buffer` を渡す(`NEW/XRL.Core/XRLCore.cs:2429-2433`)。
- **コールバックは Sidebar・パーティクル・混乱シャッフルより先に呼ばれる**。そのため legacy UI であっても、コールバック時点のバッファにはサイドバーもメッセージも入っていない(`:2506-2531`)。
- **コールバックが走るスレッド**。`RenderBase` は `Thread.CurrentThread == CoreThread` を判定している(`:2602`)。呼び出し元は `PlayerTurn` の末尾(`:2368, :2373`)、`ActionManager.RunSegment` の AutoAct 分岐(`NEW/XRL.Core/ActionManager.cs:809`)、プレイヤーのフォールバック(`:1618-1621`)で、いずれもゲームスレッド。v1 のコメントは「render thread(多くは UI スレッド)」と書いていたが、NEW のコードを見る限り**主にゲームスレッド**で走る **[推論]**。ゲーム本体の `PlayerStatusBar.AfterRender` も、このコールバックの中で `The.Player` や統計値を直接読んでいる(`NEW/Qud.UI/PlayerStatusBar.cs:281-302, 310-422`)。例外として APIDispatch 経由の `Task.Run`(スレッドプール)や `RenderDelay` からも呼ばれうる。
- **AfterRenderCallback の登録は Add だけで、解除 API はない**(`NEW/XRL.Core/XRLCore.cs:652-655`)。

### 1.3 モードごとのバッファ内容

| バッファ \ モード | text モード + Modern UI | tile モード + Modern UI(既定) | text モード + Legacy UI(`OptionModernUI=No`) | tile モード + Legacy UI |
|---|---|---|---|---|
| AfterRender 時点の `_Buffer`(source) | マップ glyph は `_Char` に入る | `_Char='\0'`、glyph は `BackupChar` に入る | マップのみ(サイドバーはまだ描かれていない) | マップのみ(`BackupChar` 経由) |
| `CurrentBuffer` | マップ glyph のみ。Modern UI の `Sidebar.Render` は何も書かない(`NEW/XRL.UI/Sidebar.cs:793-833`) | マップセルは `_Char='\0'`、`BackupChar` は失われている → **v1 が見た空白** | マップ + **サイドバー(HP・メッセージ等)+ legacy ポップアップ本文** | サイドバー文字はあるがマップは NUL |
| メッセージログ | 入らない(UGUI の `MessageLogWindow`) | 同左 | `Sidebar.Render` の legacy 分岐で書き込まれる(`Sidebar.cs:885-1030` 付近) | 同左 |
| ポップアップ本文 | 入らない。`DrawBuffer(bSkipIfOverlay:true)` はコピーされない(`TextConsole.cs:151`、`Popup.cs:1155`) | 同左 | `Popup.ShowBlock` の legacy 経路が `RenderBlock` → `DrawBuffer` で書く(`NEW/XRL.UI/Popup.cs:1143-1188`) | 同左 |

v1 の turn=5 で 1 行だけ見えた文字列(`The beauty! My stomach is in stirs.`)と、turn=13 で見えた CP437 ブロック文字は、tile を持たないセルや別経路で書かれた要素だったと考えられる **[推論]**。

**Modern UI の HUD は ScreenBuffer に入らない**。HP、食事・水分、重量、温度、時刻、ゾーン名は `PlayerStatusBar` がゲーム状態から直接組み立てる(`NEW/Qud.UI/PlayerStatusBar.cs:310-422`)。メッセージは `XRLCore.RegisterNewMessageLogEntryCallback` 経由で `MessageLogWindow` に流れる(`NEW/Qud.UI/MessageLogWindow.cs:97`)。

### 1.4 組み込みの「画面テキスト化」とスクリーンリーダー機能

- `UAP_AccessibilityManager` などの UAP プラグイン(`AccessibleLabel.cs`、`MacOSTTS.cs`、`WindowsTTS.cs` ほか)は root namespace に同梱されている。しかし `XRL*`・`Qud*`・`ConsoleLib*`・`GameManager.cs` からの参照は **0 件**だった(grep 結果)。参照元は UAP 付属のサンプル MonoBehaviour(`NEW/mainmenu.cs:16,29`、`NEW/gameover.cs:46-80`、`NEW/gameplay.cs`、`NEW/gridpanel.cs:163`)に限られる。つまり**ゲーム UI はスクリーンリーダーに接続されていない**。
- `Options.xml` の Accessibility カテゴリは、色覚補助とアニメーション抑制(`OptionDisableTextAnimationEffects`、`OptionDisableAllIdleTileAnimations` ほか)だけで、スクリーンリーダー関連の項目はない(`StreamingAssets/Base/Options.xml:45-50`)。
- テキスト化の手段として使えるのは次の 3 つ。
  1. `ScreenBuffer.ToString()`(`.Char` のみ、§1.1)
  2. legacy ポップアップの Copy ボタン(`Popup.ShowBlockWithCopy` → `ClipboardHelper.SetClipboardData`、`NEW/XRL.UI/Popup.cs:673-730`)
  3. Look のツールチップ文字列生成 `Look.GenerateTooltipContent(GameObject)`(§2.3)

### 1.5 オンデマンド描画(副次的な経路)

`new ScreenBuffer` を作り、ゲームスレッド上で `XRLCore.Core.RenderMapToBuffer(buf)` を呼ぶ方法もある。`Zone.Render` がこのバッファに `BackupChar` を書き込むので、自前のバッファから tile モードの glyph を回収できる(`NEW/XRL.Core/XRLCore.cs:2407-2434`)。ただし副作用がある: 全 AfterRenderCallback が発火し、`PlayerStatusBar` などの状態も更新される。可視・光マップは直前の `RenderBaseToBuffer` の計算結果をそのまま使う **[推論]**。

---

## 2. 構造化ワールドモデル

**原則**: 以下はすべてゲーム状態を直接参照する API である。読む場所は **ゲームスレッド** が安全。候補は IGameSystem の HandleEvent、AfterRenderCallback(§1.2 で述べたとおり主にゲームスレッド)、`gameQueue` タスクの 3 つ。ゲーム本体の UI も、状態を読む必要があるときは `gameQueue.executeAsync(() => ...)` でゲームスレッドに投げている(`NEW/XRL.UI/Look.cs:284, 317`)。

### 2.1 ルートアクセサ

| API | 内容 | 引用 |
|---|---|---|
| `The.Core` / `The.Game` / `The.Player` / `The.PlayerCell` / `The.ActiveZone` / `The.ZoneManager` / `The.ActionManager` | 静的アクセサ。`The.Player` は `Game.Player.Body` を返す | `NEW/XRL/The.cs:16-33` |
| `The.Speaker` / `The.Listener` / `The.Conversation` | 会話中の参加者と会話オブジェクト | `NEW/XRL/The.cs:45-49` |
| `The.UiContext` / `The.GameContext` | UI スレッドとゲームスレッドの SynchronizationContext。`await The.UiContext` は `XRL/Extensions.cs:171` の Awaiter で実現されている | `NEW/XRL/The.cs:41-43` |
| `XRLGame.Turns` / `Segments` / `Running` / `Player` / `PlayerReputation` / `ActionManager` / `ZoneManager` / `Quests` / `FinishedQuests` | ゲーム全体の状態 | `NEW/XRL/XRLGame.cs:50, 58, 66, 127-136, 145-148` |

### 2.2 マップ(Zone / Cell)

| API | 内容 | 引用 |
|---|---|---|
| `Zone.GetVisibility(x,y)` / `GetExplored(x,y)` | 可視・探索済みフラグ | `NEW/XRL.World/Zone.cs:7245, 7255` |
| `Cell.IsVisible()` / `IsExplored()` / `IsLit()` | Cell 単位のラッパー。`IsVisible` はゾーンが非アクティブだと false | `NEW/XRL.World/Cell.cs:3469-3497` |
| `Cell.GetObjects()`、`IsPassable`、`IsSolid*` | セル内のオブジェクトと通行可否 | `NEW/XRL.World/Cell.cs:4854, 5920, 6123-6209` |
| `Cell.GetCellFromDirection(dir, BuiltOnly)` | 隣接セルの取得 | `NEW/XRL.World/Cell.cs:8006` |
| `Cell.Render(RenderEvent, ...)` | glyph・色・tile を計算する(描画と同じ計算を任意のセルに適用できる) | `NEW/XRL.World/Cell.cs:540-, 992-1005` |
| `Zone.IsWorldMap()`、`Zone.DisplayName` | ワールドマップ判定とゾーン表示名 | `NEW/XRL.World/Zone.cs:7127, 453` |
| 可視性の再計算 | `RenderBaseToBuffer` が毎フレーム `ClearLightMap` → `ClearVisiblityMap` → `AddVisibility(player, radius)` を実行する。ワールドマップでは `ExploreAll/LightAll/VisAll` を実行する | `NEW/XRL.Core/XRLCore.cs:2454-2458, 2486-2499` |
| ミニマップ | `ActionManager.UpdateMinimap` は各 Cell の `minimapCacheColor` を 4000 要素の Color32 にコピーするだけで、テキスト情報は持たない | `NEW/XRL.Core/ActionManager.cs:367-408` |

**注意**: 可視マップは描画時に作り直される。したがって「描画前」のタイミングで `IsVisible` を読むと 1 フレーム前の視界になる可能性がある **[推論]**。v1 は BTA で `IsVisible()` を使って entity を列挙していた。

### 2.3 オブジェクト(GameObject)とテキスト記述

| API | 内容 | 引用 |
|---|---|---|
| `GetDisplayName(...)`(多数のフラグ付き)、`DisplayName`、`ShortDisplayName`、`ShortDisplayNameStripped`、`DisplayNameOnlyStripped` | 表示名。Stripped は色コードを除去する | `NEW/XRL.World/GameObject.cs:669-753, 6911, 7004` |
| `hitpoints` / `baseHitpoints` | 現在 HP / 最大 HP | `NEW/XRL.World/GameObject.cs:1176-` |
| `IsVisible()`、`IsPlayer()`、`IsHostileTowards(o)` | 可視・プレイヤー・敵対の判定 | `NEW/XRL.World/GameObject.cs:10458, 10969, 11424` |
| `Description.GetShortDescription` / `GetLongDescription(SB)` / `GetFeelingDescription` | Look 画面の本文 | `NEW/XRL.World.Parts/Description.cs:73, 168, 265` |
| **`Look.GenerateTooltipContent(GameObject)`** | 表示名 + 長文記述 + SubHeader + 負傷度を 1 つの文字列にして返す。Look 画面・ツールチップと同じ文面 | `NEW/XRL.UI/Look.cs:239-251`(`GenerateTooltipInformation` は `:256-270`) |
| `_Effects`(EffectRack) | 状態異常の一覧 | `NEW/XRL.World/GameObject.cs:146` |

### 2.4 プレイヤー能力(v1 Phase 0-D/E で既に利用)

| 領域 | API | 引用 |
|---|---|---|
| インベントリ | `Inventory.Objects` / `GetObjects()` | `NEW/XRL.World.Parts/Inventory.cs:21, 524` |
| 装備 | `Body.GetEquippedParts()` / `GetParts()` | `NEW/XRL.World.Parts/Body.cs:883, 919` |
| 変異 | `Mutations.MutationList` | `NEW/XRL.World.Parts/Mutations.cs:90` |
| スキル | `Skills.SkillList` | `NEW/XRL.World.Parts/Skills.cs:19` |
| 起動アビリティ | `ActivatedAbilities.AbilityByGuid`、`ActivatedAbilityEntry.Command` / `DisplayName` / `Cooldown` / `CooldownRounds` / `IsUsable` | `NEW/XRL.World.Parts/ActivatedAbilities.cs:183`、`NEW/XRL.World.Parts/ActivatedAbilityEntry.cs:40, 42, 259, 286, 290` |
| 空腹・渇き | `Stomach.FoodStatus()` / `WaterStatus()` | `NEW/XRL.World.Parts/Stomach.cs:87, 104` |
| 派閥評判 | `The.Game.PlayerReputation.Get(string faction)` | `NEW/XRL.World/Reputation.cs:182` |
| クエスト | `XRLGame.Quests` / `FinishedQuests`(`StringMap<Quest>`)。`Quest.Name` / `StepsByID` / `Finished` など。`QuestsAPI.allQuests()` もある | `NEW/XRL/XRLGame.cs:145-148`、`NEW/XRL.World/Quest.cs:11-113`、`NEW/Qud.API/QuestsAPI.cs:18` |
| ジャーナル | `JournalAPI.GetKnownNotes()`、`MapNotes` / `Observations` / `GeneralNotes` など | `NEW/Qud.API/JournalAPI.cs:27-41, 233` |
| インベントリ操作の候補 | `EquipmentAPI.GetInventoryActions(GO, Actor)` → `List<InventoryAction>` | `NEW/Qud.API/EquipmentAPI.cs:378` |

**サイドバー相当のデータ**: `PlayerStatusBar.BeginEndTurn` が参照元の一覧として使える。ゾーン名、全 Statistics、`Stomach`、重量と所持ドラム、温度、`Calendar`、HP を読んでいる(`NEW/Qud.UI/PlayerStatusBar.cs:310-422`)。legacy の `Sidebar.Update` / `Render` も HP・重量を文字列化している(`NEW/XRL.UI/Sidebar.cs:598-641, 787-`)。

### 2.5 メッセージログ

| API | 内容 | 引用 |
|---|---|---|
| `The.Game.Player.Messages.Messages`(`List<string>`) | ログ本体。`Markup.Transform` 後の `&`/`^` 色コード付き文字列。2000 件を超えると 100 件ずつ削除される | `NEW/XRL.Messages/MessageQueue.cs:18, 94-104, 138-150`、`NEW/XRL.World/GamePlayer.cs:18` |
| `PreviousMessage` / `LastMessage` | ターン境界のインデックス。`BeginPlayerTurn` で更新される | `NEW/XRL.Messages/MessageQueue.cs:20-22, 94-97` |
| **`XRLCore.RegisterNewMessageLogEntryCallback(Action<string>)`** | 新しいエントリが追加されるたびに push 通知される。重複登録は防止される | `NEW/XRL.Core/XRLCore.cs:657-680`、`NEW/XRL.Messages/MessageQueue.cs:148` |
| ポップアップ本文もログに入る | `Popup.Show` / `ShowBlock` は `LogMessage=true` が既定で、`MessageQueue.AddPlayerMessage` を呼ぶ | `NEW/XRL.UI/Popup.cs:1134-1137, 660-666` |

### 2.6 経路探索・AutoAct

| API | 内容 | 引用 |
|---|---|---|
| `new FindPath(Cell start, Cell end, ..., Looker, ExploredOnly, ...)`、`.Directions` / `.Steps` / `.Usable` | A* 経路探索 | `NEW/XRL.World.AI.Pathfinding/FindPath.cs:57-71, 112-167` |
| `AutoAct.TryFindPathStep(Cell, out step)`、`FindAutoexploreStep(out step, out blackout)` | 自動移動・自動探索の 1 ステップを計算する | `NEW/XRL.World.Capabilities/AutoAct.cs:627-700` |
| `AutoAct.GetDescription()`、`IsActive()`、`IsExploration()` など | 実行中の自動行動の状態 | `NEW/XRL.World.Capabilities/AutoAct.cs:105-412` |

### 2.7 会話(XRL.World.Conversations / ConversationUI)

- 会話ループはゲームスレッドで同期的に回る: `HaveConversation` の `while (CurrentNode != null) { Prepare(); Render() or RenderClassic(); }`(`NEW/XRL.UI/ConversationUI.cs:418-429`)。
- **データとして読めるもの**(静的フィールド): `ConversationUI.CurrentConversation`、`CurrentNode`、`CurrentChoices`(`List<Choice>`)、`Speaker`、`Listener`、`LastChoice`(`:135-157`)。本文は `CurrentNode.GetDisplayText(WithColor:true)`、選択肢は `Choice.GetDisplayText`(`:517-521`)。
- Modern UI の `Render()` は `Popup.ShowConversation(Title, Icon, 本文, options, Trade.Visible, AllowEscape, ...)` を呼び、返り値で分岐する: -1 は Escape、-2 は Trade、-3 は Look、0 以上は `Select(num)`(`:514-537`)。`ShowConversation` は選択肢を `command="option:i"` の `QudMenuItem` に変換し、`WaitNewPopupMessage` に渡す(`NEW/XRL.UI/Popup.cs:1571-1615`)。
- `Select(int)` は `Choice.Enter` → `CurrentNode.Leave` → 遷移 → `Entered` の順に進める(`ConversationUI.cs:539-571`)。

### 2.8 ポップアップ API と Modern UI の画面

**振り分けの鍵**: `UIManager.UseNewPopups => Options.ModernUI`(`NEW/Qud.UI/UIManager.cs:55`)。

| API | Modern UI での経路 | Legacy での経路 | データとして取れるもの | 引用 |
|---|---|---|---|---|
| `Popup.Show` / `ShowBlock` | `Suppress` なら MessageQueue に流して終わり。それ以外は `WaitNewPopupMessage` | `RenderBlock` → `DrawBuffer` → `Keyboard.getvk` ループ | Message、Title | `NEW/XRL.UI/Popup.cs:658-671, 1118-1189` |
| `Popup.ShowAsync` | `NewPopupMessageAsync`(`copyWindow`) | `Show` | 同上 | `:639-656` |
| `Popup.PickOption` / `ShowOptionList` | `QudMenuItem` のリスト(`option:N`)+ ボタンを `WaitNewPopupMessage` に渡す | テキストの選択ループ | Title、Intro、Options[]、Hotkeys | `:1645-1760` |
| `Popup.ShowYesNo` / `ShowYesNoCancel` | `WaitNewPopupMessage(YesNoButton)`。**`Suppress` は効かない** | legacy ループ | Message | `:2251-2275, 2365` |
| `Popup.AskString` / `AskNumber` | `AskStringAsync(...).Result`(ゲームスレッドがブロックする) | legacy 入力ループ(`Popup:AskString`) | Message、Default | `:1433-1450, 1191, 1320, 1371` |
| `Popup.PickGameObject` | 表示名の配列に変換して PickOption と同じ経路へ | 同左 | 名前一覧 | `:1520-` |
| `Popup.ShowConversation` | §2.7 のとおり | — | Title、Intro、Options | `:1571-1615` |
| `Popup.Suppress`(静的 bool) | `Show` / `ShowBlock` 系だけを抑制し、ログに流す | 同左 | — | `:132, 641, 660, 1120` |

- **`WaitNewPopupMessage` の仕組み**: ゲームスレッドから呼ばれた場合、`uiQueue.awaitTask` で UI スレッドに `UIManager.getWindow("PopupMessage").ShowPopup(...)` を実行させ、ゲームスレッドは `complete.Task.Wait()` で止まる(`NEW/XRL.UI/Popup.cs:801-921`)。この間、ゲームスレッドは `gameQueue` タスクを処理しない。例外は `AllowRenderMapBehind` のループ(`:896-905`)。
- **ウィンドウインスタンスは経路によって異なる**。`WaitNewPopupMessage` は共有インスタンス `getWindow("PopupMessage")` を使う(`:826`)。`NewPopupMessageAsync` はコピー `copyWindow("PopupMessage")` を使う(`:760`)。後者の popup を `getWindow` で探しても見つからない。
- **`PopupMessage` の公開状態**: `Message`(UITextSkin)、`Title`、`controller.menuData`(選択肢の `QudMenuItem` 一覧)、`controller.bottomContextOptions`(ボタン)、`inputBox`、`commandCallback` / `selectCallback`、`PopupID`、`lastPopupID`(`NEW/Qud.UI/PopupMessage.cs:18-249`、`NEW/Qud.UI/QudBaseMenuController.cs:50, 65`)。`ShowPopup` の引数(message、buttons、items、title、PopupID)がそのまま全情報になっている(`PopupMessage.cs:721-780`)。
- **Modern のステータス画面**(インベントリ・装備・キャラクター・スキル・クエスト・ジャーナル・派閥・Tinkering): `Screens.Show` → `StatusScreensScreen.show(startingScreen, GO).Result` でゲームスレッドがブロックする(`NEW/XRL.UI/Screens.cs:88-127`、`NEW/Qud.UI/StatusScreensScreen.cs:128`)。画面内の操作(落とす・装備する・食べるなど)は `APIDispatch.RunAndWaitAsync` → `Task.Run` で **スレッドプール上** で実行される(`NEW/XRL.UI.Framework/APIDispatch.cs:10-80`、`NEW/Qud.UI/InventoryAndEquipmentStatusScreen.cs:222-426`)。画面の表示内容はゲーム状態から直接導けるので、UI を開かずに §2.4 の API で同じ情報を得られる。
- **取引**: 取引一覧は `TradeUI.GetObjects(Trader, list, Other, CostMultiple)`、価格は `TradeUI.GetValue` / `ItemValueEach`、ゲームビューは `ModernTrade` / `ConsoleTrade`(`NEW/XRL.UI/TradeUI.cs:150, 218-245`、`NEW/Qud.UI/TradeScreen.cs:528`)。
- **キャラクター作成**: `XRLCore.NewGame` → `EmbarkBuilder.Begin().Result`。`Begin` はゲームスレッドから呼ぶことが前提で、UI コンテキスト上に `EmbarkBuilder` コンポーネントを作る(`NEW/XRL.Core/XRLCore.cs:2837-2869`、`NEW/XRL.CharacterBuilds/EmbarkBuilder.cs:61-87`)。ビルドコード文字列からモジュールを復元する `EmbarkBuilder.FromCode(code)` / `InitModulesFromCode` があり(`:505-519`)、完了は `finishedEvent.TrySetResult(embarkInfo)` で通知される(`:263-295`)。
- **レベルアップ**: `Leveler` は `Popup.Show` / `ShowYesNo` / `PickOption` を直接呼ぶ(`NEW/XRL.World.Parts/Leveler.cs:289, 325, 341`)。変異のバリアント選択も `Popup.PickOption` を使う(`NEW/XRL.World.Parts.Mutation/BaseMutation.cs:1017`)。したがってポップアップの傍受でまとめて扱える **[推論]**。
- **ゲームビュー名**: `GameManager.CurrentGameView` と `PushGameView(...)` のスタックで、どのモーダルが開いているかを識別できる(`NEW/GameManager.cs:469-480, 1493-1510`)。ビュー名はクラスの `[UIView(...)]` 属性に書かれている。例: `PopupMessage` / `DynamicPopupMessage`(ともに NavCategory は `"Conversation"`。`NEW/Qud.UI/PopupMessage.cs:16-17`)、`ModernTrade`(`NEW/Qud.UI/TradeScreen.cs:17`)、`ConsoleTrade`(`NEW/XRL.UI/TradeUI.cs:15, 465`)、`StatusScreensScreen`(`NEW/Qud.UI/StatusScreensScreen.cs:14`)、`MainMenu`(`NEW/Qud.UI/MainMenu.cs:17`)、`EmbarkBuilder:Overlay`(`NEW/XRL.CharacterBuilds.UI/EmbarkBuilderOverlayWindow.cs:11`)。ほかに grep で見つかった `PushGameView` の文字列は `Popup:MessageBox`、`Popup:Choice`、`Popup:AskString`、`ModernPopup:AskString`、`PickTarget`、`Looker`、`Book`、`Tinkering`、`ModernPopupTwiddleObject` など。会話専用のビュー名はなく、会話は PopupMessage として表示される **[推論: ShowConversation の実装から]**。


---

## 3. 制御面

### 3.1 スレッドとキュー

| 要素 | 実体 | 引用 |
|---|---|---|
| ゲームスレッド | `XRLCore.CoreThread`(`GameManager.StartGameThread` で起動)。`ActionManager.RunSegment` と `PlayerTurn` が同期ループで回る | `NEW/XRL.Core/XRLCore.cs:3540-3571`、`NEW/GameManager.cs:1668-1678` |
| UI スレッド | Unity のメインスレッド。`GameManager.Update` で `uiQueue.executeTasks()` を実行する | `NEW/GameManager.cs:2963` |
| `gameQueue` | ゲームスレッド側で処理されるのは 2 か所: `RenderBase` の先頭(`CoreThread` 上のとき)と `Keyboard.GetNextKey(pumpActions)` の待機中 | `NEW/XRL.Core/XRLCore.cs:2602-2605`、`NEW/ConsoleLib.Console/Keyboard.cs:1040` |
| `ThreadTaskQueue` API | `queueTask` / `queueSingletonTask`(同じキーの重複を排除)/ `executeAsync<T>`(Task を返す)/ `awaitTask`(呼び出し側で待つ) | `NEW/QupKit/ThreadTaskQueue.cs:77-157` |
| `SynchronizationContext` | `await The.UiContext` / `await The.GameContext` でスレッドを切り替えられる | `NEW/XRL/The.cs:41-43`、`NEW/XRL/Extensions.cs:171` |

**帰結**: ゲームスレッドが Modern UI のモーダルで `Task.Wait()` / `.Result` によってブロックしている間、`gameQueue` は処理されない(`NEW/XRL.UI/Popup.cs:908`、`NEW/XRL.UI/Screens.cs:88-127`)。したがって **モーダル中の外部操作は UI スレッド(`uiQueue`)経由で行うしかない**。v1 の再接続処理は `gameQueue.queueSingletonTask` + `Keyboard.KeyEvent.Set()` だった(`archives/llm-of-qud-v1/mod/LLMOfQud/LLMOfQudSystem.cs:76-120`)。これは PlayerTurn の待機中にしか効かない **[推論]**。

### 3.2 Keyboard キュー(legacy 入力経路)

| API | 挙動 | 引用 |
|---|---|---|
| `Keyboard.PushKey(KeyEvent)` / `PushKey(Keys)` | `KeyQueue` に積んで `KeyEvent.Set()` する。`TutorialManager.AllowPushKey` のゲートがある。`bCapInputBuffer`(`OptionCapInputBuffer`)が有効だとキューは約 3 件に制限される | `NEW/ConsoleLib.Console/Keyboard.cs:772-796`、`NEW/GameManager.cs:152` |
| `Keyboard.PushMouseEvent(string Event, int x, int y)` | `MouseEvent` を積む。`GetNextKey` はキーより先にマウスイベントを返す | `NEW/ConsoleLib.Console/Keyboard.cs:820-849, 956-1000` |
| `Keyboard.PushCommand(string cmd)` | `PushMouseEvent("Command:" + cmd)` の糖衣。実入力(ControlManager)も同じ経路で入ってくる | `NEW/ConsoleLib.Console/Keyboard.cs:723-726, 128`、`NEW/GameManager.cs:2187, 2433, 2444` |
| `Keyboard.ClearMouseEvents(LeaveMovementEvents)` | `LeaveMovementEvents=true` のときは `Meta:Navigate*` / `CmdMove*` / `CmdAutoMove*` だけを残して消す | `NEW/ConsoleLib.Console/Keyboard.cs:893-924` |
| `kbhit()` / `GetNextKey` | ウィンドウが非フォーカス(`bThreadFocus==false`)だと 200 ms / 1000 ms 待つ | `NEW/ConsoleLib.Console/Keyboard.cs:938-954, 1031` |

**注意点**:
1. `PlayerTurn` は冒頭で `Keyboard.ClearMouseEvents(LeaveMovementEvents: true)` を呼ぶ(`NEW/XRL.Core/XRLCore.cs:734`)。そのため、PlayerTurn の開始より前に積んだ `PushCommand("CmdInventory")` などの **非移動コマンドは消える**。移動系コマンドは残る。PlayerTurn の入力待ち中(`GetNextKey` のブロック中)に積めば消えない **[推論]**。
2. PlayerTurn は `while (!GameManager.focused) Thread.Sleep(200)` で停止する(`NEW/XRL.Core/XRLCore.cs:737-740`)。`focused` は `OnApplicationFocus` で書き換わる。public static のセッターがあり、再フォーカス時には入力をクリアする(`NEW/GameManager.cs:404-425, 1920-1924`)。**バックグラウンドで無人運転するときの最大の停止要因**になる。対策の候補は、`runInBackground` を `OptionMusicBackground` と連動させること(`NEW/XRL.UI/Options.cs:1445-1454`)、または mod から `GameManager.focused=true` を維持すること **[推論: 要実測]**。
3. AutoAct の実行中は、1 ステップごとに `Keyboard.kbhit()` が呼ばれる。true なら `AutoAct.Interrupt()` になる(`NEW/XRL.Core/ActionManager.cs:810-814`)。**AutoAct 中にキーを積むと中断として扱われる**。さらに `kbhit` は、非フォーカス時(`bThreadFocus==false`)に `KeyEvent.WaitOne(200)` で待つ(`NEW/ConsoleLib.Console/Keyboard.cs:938-950`)。そのため、**バックグラウンドでの自動探索・自動移動は 1 ステップあたり約 200 ms(約 5 歩/秒)に絞られる**。PlayerTurn のフォーカス停止とは別の要因になる。
4. `ControlManager.CommandFramePressed` は書き込み(`NEW/ControlManager.cs:715-718`)とクリア(`:637, 727`)はあるが、読み出し箇所がない(dead code)。

### 3.3 PlayerTurn のコマンド処理

- 入力の解決順: マウスイベント `"Command:X"` → コマンドへの変換(`NEW/XRL.Core/XRLCore.cs:776-780`)。マウス由来の移動・使用は `AutoAct.Setting = "M x,y"` / `"!id"` に変換される(`:782-891`)。それ以外は `CommandBindingManager.GetNextCommand` を経て巨大な switch に入る(`:902, 981`)。
- `Commands.xml` には 201 コマンドが定義されている(`NEW/StreamingAssets/Base/Commands.xml`)。主要な case の行: `CmdMoveE` 1167、`CmdMoveTo` 1232、`CmdAttackE` 1358、`CmdWait` 1517、`CmdUse` 1679、`CmdLook` 1682、`CmdSave` 1784、`CmdAbilities` 1806、`CmdThrow` 1837、`CmdFire` 1840、`CmdWish` 1883、`CmdCharacter` 1902、`CmdInventory` 1906、`CmdAutoExplore` 1920、`CmdGet` 2144、`CmdOpen` 2174、`CmdTalk` 2212、`CmdMessageHistory` 2296(すべて `NEW/XRL.Core/XRLCore.cs`)。
- **switch の default では `CommandEvent.Send(The.Player, cmd)` が呼ばれる**(`:2322-2334`)。これで能力コマンド(`ActivatedAbilityEntry.Command`)を名前で直接発火できる。`CommandEvent.Send` は `HasRegisteredEvent` / `WantEvent` を満たす場合にだけ発火する(`NEW/XRL.World/CommandEvent.cs:44-124`)。
- `CmdAbilities` はアビリティ選択 UI を開き、選ばれた `Command` を `CommandEvent.Send` に渡す(`:1806-1821`)。UI を通さずに同じ結果を得るには、`CommandEvent.Send(player, entry.Command)` を呼べばよい **[推論]**。

### 3.4 ActionManager と CTA フック(v1 の中核)

- `RunSegment` の順序: `BeginTakeActionEvent`(`NEW/XRL.Core/ActionManager.cs:743-746`)→ `CommandTakeActionEvent.Check`(`:789`、false なら continue)→ 敵対による中断判定(`:794-797`)→ `Energy>=1000 && IsPlayer` のときに AutoAct 分岐(`:798-1575`)→ AutoAct が非アクティブなら `PlayerTurn()`(`:1611`)→ `EndActionEvent`(`:1640`)。
- **CTA ハンドラ内で直接行動する方式**(v1 の Phase 0-F で確立): `Move(dir)` や `AttackDirection(dir)` を呼んで Energy を消費すれば、`Energy>=1000` の条件が偽になり PlayerTurn(キー待ち)を回避できる。失敗したときは `PassTurn` を fallback にする。v1 は Energy が異常な場合にだけ `PreventAction` を使った(`archives/llm-of-qud-v1/mod/LLMOfQud/LLMOfQudSystem.cs:441-707`)。`CommandTakeActionEvent.PreventAction` / `Check`: `NEW/XRL.World/CommandTakeActionEvent.cs:8, 28-38`。
- **CTA から `AutoAct.Setting` を設定する方式**: CTA の直後、同じセグメントの `:805` で `AutoAct.IsActive()` が評価される。そのため CTA で `AutoAct.Setting = "?"`(自動探索)、`"M x,y"`(座標への移動)、`"<"` / `">"`(階段)、`"g"`(拾う)、`"z"` / `"r"`(休む)、`".N"`(N ターン待つ)などを設定すれば、エンジン内蔵の自動行動に委ねられる **[推論: 構造上可能。要実測]**。Setting の文字列プロトコルは `NEW/XRL.Core/ActionManager.cs:855-1441` の switch で定義されている。停止理由は `AutoAct.GetDescription` / `Interrupt` 周辺から取得できる(`NEW/XRL.World.Capabilities/AutoAct.cs:374-419`)。
- `ActionManager.SkipPlayerTurn`(static bool)を立てると、PlayerTurn の代わりに `SkipPlayerTurn` の分岐を通る(`NEW/XRL.Core/ActionManager.cs:25, 1584-1588`)。v1 は再接続時の起床処理にこれを使った。

### 3.5 直接呼べる API(UI を経由しない)

| 行為 | API | 引用 |
|---|---|---|
| 移動・攻撃・待機 | `GameObject.Move(dir, ...)`、`AttackDirection(dir)`、`PassTurn()`、`UseEnergy(n)` | `NEW/XRL.World/GameObject.cs:16234, 18397, 18058, 3645` |
| 経路に沿った移動 | `FindPath` で求めた方向列を CTA ごとに 1 手ずつ `Move`。または `AutoAct.Setting = "M x,y"` | `NEW/XRL.World.AI.Pathfinding/FindPath.cs:154`、`NEW/XRL.Core/ActionManager.cs:857-905` |
| インベントリ操作 | `InventoryActionEvent.Check(Actor, Actor, Item, Command)`(食べる・飲む・読むなど)。候補は `EquipmentAPI.GetInventoryActions` で得る | `NEW/XRL.World/InventoryActionEvent.cs:110`、`NEW/Qud.API/EquipmentAPI.cs:378` |
| 装備 | `EquipmentAPI.EquipObjectToPlayer` / `EquipObject` / `UnequipObject` / `DropObject` | `NEW/Qud.API/EquipmentAPI.cs:439-501` |
| 能力 | `CommandEvent.Send(player, entry.Command)` | `NEW/XRL.World/CommandEvent.cs:44` |
| 会話の開始 | `ConversationUI.HaveConversation(...)`(内部で `Popup.ShowConversation` をブロック呼び出しする) | `NEW/XRL.UI/ConversationUI.cs:361-434` |
| ウィッシュ | `WishManager.HandleWish` / `Wishing.HandleWish`(デバッグ用: `conv:`, `startquest:` など) | `NEW/XRL.Wish/WishManager.cs:131-165`、`NEW/XRL.World.Capabilities/Wishing.cs:45` |

**注意**: 「直接呼べる」API の多くは内部で `Popup.*` を呼ぶことがある。例として、`InventoryActionEvent` の結果として確認ダイアログや本の表示が出る。したがって直接呼び出しでもモーダル対策は必要になる **[推論]**。

### 3.6 モーダルごとの入力の消費方法と、最も壊れにくい注入経路

| UI 系統 | 入力の読み手 | Keyboard.Push* は効くか | 最も壊れにくい注入経路 | 引用 |
|---|---|---|---|---|
| PlayerTurn(通常のマップ) | ゲームスレッドの `GetNextKey` | 効く(`PushCommand`、`PushKey`) | CTA 内で直接 API を呼ぶ > `PushCommand`(PlayerTurn 開始後に積む) | `NEW/XRL.Core/XRLCore.cs:734, 902` |
| PickDirection | legacy の `getvk` ループ(ModernUI でも同じ) | 効く(NumPad キー、`LeftClick` x,y) | `PushKey(NumPadN)` | `NEW/XRL.UI/PickDirection.cs:28-123` |
| PickTarget(射撃・投擲・Look) | legacy の `getvk` + `PointerOver` / `LeftClick` | 効く | `PushMouseEvent("PointerOver", x, y)` → `PushKey(Enter)` または `PushCommand("CmdFire")` **[推論: 要実測]** | `NEW/XRL.UI/PickTarget.cs:378, 791-808, 322, 965` |
| Popup(Modern: Show / PickOption / YesNo / Conversation / AskString) | UI スレッドの `PopupMessage.Update`(Unity `Input` と `ControlManager`)。ゲームスレッドは `Task.Wait` | **効かない** | (a) Harmony prefix でゲームスレッド側の `Popup.*` を置き換え、答えを直接返す。(b) `uiQueue` 経由で `PopupMessage.OnActivateCommand(item)` を呼ぶ(`item.command` は `"option:N"` / `"Yes"` / `"No"` / `"Cancel"`)。`WaitNewPopupMessage` の場合は `getWindow("PopupMessage")`、Async の場合は `copyWindow` のインスタンスになる | `NEW/XRL.UI/Popup.cs:801-921, 1740-1760, 2260-2275`、`NEW/Qud.UI/PopupMessage.cs:926-944, 968-1065`、`NEW/Qud.UI/UIManager.cs:277-282, 323` |
| Popup(Legacy: `OptionModernUI=No`) | ゲームスレッドの `getvk` ループ | 効く | `PushKey`(a-z のホットキー / Enter / Esc) | `NEW/XRL.UI/Popup.cs:1143-1188` |
| ステータス画面(Modern) | UI スレッドの `NavigationController` | 効かない | **UI を開かない**(§3.5 の API で代替する)。開いてしまった場合は `NavigationController.FireInputCommandEvent("Cancel")` を試す **[推論]** | `NEW/XRL.UI/Screens.cs:88-127`、`NEW/XRL.UI.Framework/NavigationController.cs:233-243` |
| 取引(Modern) | UI スレッドの `TradeScreen` | 効かない | `TradeUI` の静的データを読み、Harmony で取引を確定する(**要設計**)。または legacy の `ConsoleTrade` を使う | `NEW/Qud.UI/TradeScreen.cs:528`、`NEW/XRL.UI/TradeUI.cs:15, 465` |
| 会話 | ゲームスレッドのループ + `Popup.ShowConversation` | Modern では効かない | `ShowConversation` の答えを返す(Harmony、または `option:N`)。**v1 の設計書にある「外部から `ConversationUI.Select(int)` を呼ぶ」方式は、`Render()` 内の `Select(num)` と競合するので不可** | `NEW/XRL.UI/ConversationUI.cs:514-571`、`archives/llm-of-qud-v1/docs/architecture-v5.md:760-800` |
| キャラクター作成 | UI コンテキスト上の `EmbarkBuilder` | 効かない | ビルドコードを `EmbarkBuilder.FromCode` に渡す、または Harmony で `Begin` を差し替えて `embarkInfo` を即時に返す **[推論: 要設計]** | `NEW/XRL.CharacterBuilds/EmbarkBuilder.cs:61-87, 505-519` |
| メインメニュー | ゲームスレッドの `getvk` ループ。Modern の `MainMenu` もボタンの選択を `Keyboard.PushMouseEvent("Pick:...")` に変換してこのループに渡す | 効く(両モード) | `PushMouseEvent("Pick:Continue")`。**ただし Modern UI の Continue は `ModernSaveManagement`(`SaveManagement.ContinueMenu().Wait()`)を開き、これは Keyboard では操作できない [推論]**。セーブの選択を避けるなら、`XRLGame.LoadGame(path)` を直接呼ぶ方式を検討する | `NEW/XRL.Core/XRLCore.cs:3727-3800`(Continue の処理は 3778-3786)、`NEW/Qud.UI/MainMenu.cs:53-106, 347`、`NEW/XRL/XRLGame.cs:1677` |
| レベルアップ・変異選択 | `Popup.*` | Popup の行と同じ | Popup の行と同じ | `NEW/XRL.World.Parts/Leveler.cs:289-341` |

**TutorialManager のゲート**: チュートリアル中は `AllowPushKey` / `AllowMouseEvent` / `AllowCommand` / `AllowSelectedPopupCommand` が入力を捨てることがある(`NEW/TutorialManager.cs:311, 361, 371`、`NEW/Qud.UI/PopupMessage.cs:928`)。LLM の運用ではチュートリアルを避ける。


---

## 4. Mod 基盤

### 4.1 コンパイルとロード

| 項目 | 内容 | 引用 |
|---|---|---|
| コンパイラ | `RoslynCSharp` によるインメモリコンパイル。`OptionOutputModAssembly` のときだけディスクに出力する | `NEW/XRL/ModManager.cs:116-136`、`NEW/StreamingAssets/Base/Options.xml:161` |
| 参照アセンブリ | `MainAssemblyPredicate` を通る全ロード済みアセンブリ: 非 dynamic、Location があり、ModAssemblies / UIElements / UnityEditor / ExCSS を除く。したがって Managed フォルダの `System.dll`、`System.Net.Http.dll`、`Newtonsoft.Json.dll`、`0Harmony.dll` は **ロード済みなら** 参照可能 **[推論: ロード済みかどうかは要確認]** | `NEW/XRL/ModManager.cs:389-416` |
| バージョン判定用シンボル | `BUILD_{Major}_{Minor}_{Build}` などが定義される。MarketingVersion は "1.0.5" | `NEW/XRL/ModManager.cs:127-134`、`NEW/XRL/XRLGame.cs:104` |
| ビルド済み DLL | エンジンは mod の `.dll` を読み込まない。ただし mod のコードが `Assembly.LoadFrom` を呼べば読み込める(QudJP の `Bootstrap.cs` が実例: Workshop 3718988020、`Player-prev.log:140-142`) | — |
| ビルド | `ModInfo.TryBuildAssembly` → 成功後に `ApplyHarmonyPatches`(`[HarmonyAttribute]` を持つ型があれば `PatchAll`) | `NEW/XRL/ModInfo.cs:755-769, 845-862` |
| C# mod の承認 | `OptionAllowCSMods` の既定は No。C# を含む mod は `Options.AllowCSMods` が false だと `ModState.Disabled` になる。未設定のときは起動時に確認ダイアログが出る(`IsScriptingUndetermined`)。**無人運転の前に、オプションを 1 回手動で許可しておく必要がある** | `NEW/StreamingAssets/Base/Options.xml:160`、`NEW/XRL/ModInfo.cs:126-128`、`NEW/XRL/ModManager.cs:975-992` |
| manifest.json | `ID`, `LoadOrder`, `Title`, `Description`, `Tags`, `Version`, `Author`, `PreviewImage`, `Directories`, `Dependencies`, `LoadBefore`, `LoadAfter` | `NEW/XRL/ModManifest.cs:9-34` |
| ログ | コンパイル: `Logger.buildLog`(`build_log.txt`)。実行時: `MetricsManager.LogInfo` → `Debug.Log("INFO - ...")`(Player.log)。`LogWarning` は "WARN - " | `NEW/Logger.cs:17, 33`、`NEW/MetricsManager.cs:212-214, 411-419` |

### 4.2 Harmony と Apple Silicon

- 同梱の `0Harmony.dll` は **2.2.2.0**(MonoMod を内包)。Managed フォルダの実物で確認した。ゲーム本体の `ModManager` は `harmony` インスタンスを持つが、自身ではパッチを当てていない(`NEW/XRL/ModManager.cs:70`)。
- ゲームのバイナリ `CoQ.app/Contents/MacOS/CoQ` は **x86_64 と arm64 のユニバーサル** で、ランタイムは Mono(`Frameworks/libmonobdwgc-2.0.dylib`)。IL2CPP ではない。
- 上流の Harmony が arm64 を正式にサポートしたのは 2.4 から: "Full support for arm64 across all operating systems, including Apple Silicon"(https://github.com/pardeike/Harmony/releases)。Apple Silicon では mprotect が EACCES で失敗する問題が報告されている(https://github.com/pardeike/Harmony/issues/424)。CoQ の Mac 版で Harmony mod がクラッシュするというユーザー報告もある(https://www.reddit.com/r/cavesofqud/comments/1e10jk4/game_keeps_crashing_with_any_mod_that_has_harmony/ 。検索スニペットで確認しただけ)。CoQ 日本語化 mod は、Apple Silicon 向けに Harmony 2.4.2 のネイティブパッチを任意で提供すると説明している(https://steamcommunity.com/sharedfiles/filedetails/?id=3718988020)。CoQ Wiki: https://wiki.cavesofqud.com/wiki/Modding:Harmony 。
- **このマシンでの実績(ローカル証拠)**: 同じ Mac(Apple M4)の `~/Library/Logs/Freehold Games/CavesOfQud/Player-prev.log` から次のことがわかる。
  - ゲーム版 2.0.211.51 で、QudJP mod が Harmony パッチを適用している: "Harmony patching complete: 1693 method(s) patched."(`Player-prev.log:54, 161`)。
  - 適用には約 62 秒かかっている(`Player-prev.log:158`)。
  - ただし、そのときのプロセスのアーキテクチャ(Rosetta かネイティブか)と、`0Harmony.dll` が置き換えられていたかどうかはログからわからない。
  - QudJP には 2 つの補助スクリプトが同梱されている。`Launch CavesOfQud (Rosetta).command`(Rosetta で起動)と `Install Native Apple Silicon Harmony.command`(`Managed/0Harmony.dll` を Harmony 2.4.2 に置き換え、バックアップを取る)。どちらも Workshop の 3718988020 のフォルダにある。
  - 現在の Managed には 2.2.2.0 だけがあり、QudJP のバックアップファイルはない。つまり、置き換えが行われていないか、2026-09-25 の更新で戻されたかのどちらか **[推論]**。
- **mod は Harmony 2.4 を持ち込めない**。mod の `.cs` は Roslyn でコンパイルされるだけだが、QudJP の `Bootstrap.cs` は `[ModSensitiveCacheInit]` から `Assembly.LoadFrom("Assemblies/QudJP.dll")` を呼んで **ビルド済みの DLL を読み込んでいる**。したがって、v1 の `mod/CLAUDE.md` にある「DLL を読み込む経路はない」という記述は、エンジン側の経路についてのみ正しい。それでも、同じ AppDomain に `0Harmony` が 2 つのバージョンで共存するのは名前の衝突で困難と考えられる **[推論]**。arm64 で Harmony 2.4 を使うには、インストール先の `Managed/0Harmony.dll` を置き換えるしかない。これは mod の範囲を超え、ゲームの更新で元に戻る。
- **帰結**: arm64 ネイティブ起動 + 同梱の 2.2.2 では、Harmony のパッチが失敗する可能性が高い **[推論: 外部報告にもとづく。要実測]**。現実的な選択肢は 3 つ: (1) Rosetta(x86_64 スライス)で起動する。QudJP の起動スクリプトが実例になる。(2) Harmony を使わない設計にする。(3) `0Harmony.dll` の置き換えを運用手順に含める(更新のたびに再適用が必要)。v1 は Harmony を使わず、CTA + 直接 API + コールバックだけで Phase 1 の E2E に到達している(`archives/llm-of-qud-v1/docs/memo/phase-1-pr-3-e2e-acceptance-2026-04-30.md:5-10`)。
- Harmony が使えない場合、Modern UI のポップアップへの応答は §3.6 の (b) uiQueue 経路、または (c) `OptionModernUI=No` に頼ることになる。

### 4.3 ゲームシステムのライフサイクル

| フック | 用途 | 引用 |
|---|---|---|
| `[PlayerMutator]` + `IPlayerMutator.mutate(player)` | **新規ゲーム** のプレイヤー生成時に呼ばれる。v1 はここで `The.Game.RequireSystem<LLMOfQudSystem>()` を呼んでいた | `NEW/XRL.CharacterBuilds.Qud/QudGameBootModule.cs:303-307`、`NEW/XRL/PlayerMutator.cs`、`NEW/XRL/XRLGame.cs:304-334` |
| IGameSystem の永続化 | `XRLGame.Systems` はセーブに書き込まれる(`SaveSystems` / `LoadSystems`)。ロード後に `ApplyRegistrar` が再実行される。**セーブに mod の型が残るので、mod を外すとロードに影響が出る可能性がある [推論]** | `NEW/XRL/XRLGame.cs:157, 1580-1600, 1946-1948` |
| `IPlayerSystem.RegisterPlayer(Player, Registrar)` | プレイヤーオブジェクトのイベント(BTA / CTA など)を購読する | `NEW/XRL/IPlayerSystem.cs:7-54` |
| `HandleEvent(BeginTakeActionEvent / CommandTakeActionEvent / EndTurnEvent / BeforeRenderEvent / AfterGameLoadedEvent / ZoneActivatedEvent)` | ターンと描画のフック | `NEW/XRL/IGameSystem.cs:587, 907, 1032, 517, 207, 2857` |
| `BeforeSave` / `AfterSave` / `AfterLoad` / `OnAdded` / `OnRemoved` / `PlayerEmbarking` / `BeginSegment` / `EndTurn` / `QuestStarted` / `QuestCompleted` / `PlayerAfterConversation` / `PlayerEnteredCell` / `PlayerTook` / `PlayerEquipped` / `PlayerReputationChanged` / `ZoneActivated` / `AwardingXP` など | 高レベルのイベントを受ける仮想メソッド。**イベントログ(ナレーション)の素材として有用** | `NEW/XRL/IGameSystem.cs:2913-3068` |
| `[ModSensitiveCacheInit]` / `[HasModSensitiveStaticCache]` | mod のビルド直後と、ゲーム起動時の `ResetModSensitiveStaticCaches` で呼ばれる静的メソッド。**ゲーム開始前(メインメニュー)に処理を走らせる唯一の公式入口** **[推論]**。ブリッジサーバーの起動やメインメニューの自動操作に使える | `NEW/XRL/ModManager.cs:340-372, 661`、`NEW/XRL.Core/XRLCore.cs:577`、`NEW/XRL/ModSensitiveCacheInitAttribute.cs` |
| `XRLCore.Register*Callback` | BeginPlayerTurn / EndPlayerTurn / PassedTenPlayerTurn / AfterRender / NewMessageLogEntry。**static リストなので、ロードのたびに重複登録しないよう注意する** | `NEW/XRL.Core/XRLCore.cs:253-273, 604-680` |
| `ModManager.CallAfterGameLoaded` / `XRLGame.CallAfterGameLoaded` | ロード完了時に呼ばれる | `NEW/XRL/ModManager.cs:374`、`NEW/XRL/XRLGame.cs:1954` |

### 4.4 オプション、ウィッシュ、セーブ、早送り

- **mod オプション**: mod 同梱の Options XML を `Options.LoadModOptions` が読む(`NEW/XRL.UI/Options.cs:1490, 1524`)。値は `Options.GetOption(ID)` / `GetOptionBool(ID)` / `Options.Bag` で参照できる(`NEW/XRL.UI/Options.cs:530, 1100, 1122`)。
- **ウィッシュ**: `[HasWishCommand]` クラスの `[WishCommand("name")]` メソッドが自動で登録される(`NEW/XRL.Wish/WishManager.cs:40-85`、`NEW/XRL.Wish/WishCommand.cs:5-17`)。デバッグ操作チャネル(状態ダンプ、プローブの起動)に使える。
- **セーブ・ロード**: `XRLGame.SaveGame(name, ...)`(Task)、`QuickSave()`、`QuickLoad()`(async)、`LoadGame(path, ...)`(static async)、`SaveGameInfo()`(`NEW/XRL/XRLGame.cs:2028-2033, 1677, 2224, 2249`)。セーブ時の `CmdSave` の入口は `NEW/XRL.Core/XRLCore.cs:1784`。
- **早送り・スロットル**:
  - `OptionAutoexploreRate`(0 は無制限)→ `Options.AutoexploreRate`。AutoAct のレート制限の sleep に効く(`NEW/StreamingAssets/Base/Options.xml:126`、`NEW/XRL.UI/Options.cs:451`、`NEW/XRL.Core/ActionManager.cs:1567-1575`)。
  - `DisableAllIdleTileAnimations`(`NEW/XRL.UI/Options.cs:522`)と `ThrottleAnimationRate`(`:556-566`)。
  - 休息中は `RenderBase` が早期 return する(`NEW/XRL.Core/XRLCore.cs:2614-2618`)。
  - v1 Phase 0-F は、CTA から直接行動するとゲームスレッドの全速で進み、人間には追えない速度になると報告している(`archives/llm-of-qud-v1/docs/memo/phase-0-f-exit-2026-04-26.md:77`)。**LLM の応答待ちが自然なスロットルになる**が、配信用には明示的なペーシングが必要になる。

---

## 5. プロセス内ネットワーク

| 部品 | 証拠 | 備考 |
|---|---|---|
| `System.Net.WebSockets.ClientWebSocket` | Managed の `System.dll` に型名がある。**v1 で実動作済み**: 専用のバックグラウンドスレッドから Python Brain へ WebSocket 接続し、ゲームスレッドは `ResponseTask.Wait(TIMEOUT_MS)` で待つ(`archives/llm-of-qud-v1/mod/LLMOfQud/BrainClient.cs:6, 27-64, 259-305`、`archives/llm-of-qud-v1/mod/LLMOfQud/WebSocketPolicy.cs:60-64`)。E2E は PASS(`archives/llm-of-qud-v1/docs/memo/phase-1-pr-3-e2e-acceptance-2026-04-30.md:5-10`) | 最も実績がある。mod はクライアント、外部プロセスがサーバーという構成 |
| `System.Net.HttpListener` / `HttpListenerWebSocketContext` / `AcceptWebSocketAsync` | Managed の `System.dll` に型名が 14 件ある | mod をサーバーにする構成が可能 **[推論: Mono/macOS での bind・権限・ATS の挙動は要実測]** |
| `System.Net.Sockets.TcpListener` | `System.dll` にある | 最小依存のサーバー。独自のフレーミングが必要 |
| `System.Net.Http.HttpClient` | `System.Net.Http.dll` にある。ただしゲームのコードは使っていない(grep で 0 件) | 未ロードなら Roslyn の参照に入らない可能性がある **[推論]**。`System.dll` の型だけで済ませるほうが安全 |
| `UnityWebRequest` | `UnityEngine.UnityWebRequestModule.dll` にある | メインスレッド専用。ゲームスレッドから使うには不向き **[推論]** |
| JSON | `Newtonsoft.Json.dll` 13.0.2 が同梱されている。ゲーム本体の 37 ファイルが `using Newtonsoft.Json` している(例: `NEW/AchievementManager.cs`)ので、ロード済みである。v1 は手書きの JSON を使った | §4.1 の `MainAssemblyPredicate` を通るので、mod から参照できる可能性が高い **[推論: 要コンパイルプローブ]** |

**設計上の含意**: 観測(push)と制御(pull)は、どちらも「mod がクライアントになり、外部の Brain がサーバーになる」構成が最も実績がある。モーダル応答の経路を UI スレッドに持つ場合、応答は WebSocket 受信スレッド → `uiQueue.queueTask` の順で流すことになる **[推論]**。


---

## 6. 結論マトリクス

### 6.1 観測面マトリクス

評価の尺度: ◎ 非常に良い、○ 良い、△ 条件付き、× 不可。コストは 1 回あたりの目安 **[推論]**。

| 観測面 | 忠実度 | 網羅性 | コスト | スレッド制約 | タイルモード依存 | 主な引用 |
|---|---|---|---|---|---|---|
| A. `ScreenBuffer`(AfterRenderCallback / `ToString`) | △ 見た目どおりだが意味は持たない。タイルでは `Char=0` なので `BackupChar` の補完が必須 | △ Modern UI では **マップだけ**。HUD・ログ・ポップアップは UGUI 側にある。Legacy UI なら全部入る | 低(80x25 のコピー) | コールバックは主にゲームスレッド。引数は static `_Buffer` | **あり**(BackupChar 補完。OverlayTile は未検証) | `ConsoleChar.cs:392-420`、`XRLCore.cs:2432, 2464, 2508`、`Sidebar.cs:793-833` |
| B. `RenderMapToBuffer` をオンデマンドで呼ぶ | △ A と同じ | マップのみ | 低〜中 | ゲームスレッド | あり | `XRLCore.cs:2407-2434` |
| C. Zone / Cell / GameObject の構造化 API | ◎ 意味がそのまま取れる(名前、HP、敵対、可視性) | ◎ マップ、エンティティ、地形、探索状態 | 中(可視セルの走査) | ゲームスレッド | なし | `Zone.cs:7245-7255`、`Cell.cs:3469-3490, 4854`、`GameObject.cs:1176, 10458, 11424` |
| D. Look のテキスト(`GenerateTooltipContent`)、Description | ◎ 人間が読むのと同じ文面 | 1 オブジェクト単位 | 中 | ゲームスレッド(UI 側も `gameQueue` で呼んでいる) | なし | `Look.cs:239-251, 284`、`Description.cs:73-265` |
| E. MessageQueue + `NewMessageLogEntryCallback` | ◎ 色コード付きの原文 | ◎ ポップアップの本文も既定で入る | 極小(push) | Add を呼んだスレッド | なし | `MessageQueue.cs:106-150`、`XRLCore.cs:657-680`、`Popup.cs:664, 1136` |
| F. プレイヤーの内部状態(Stats、Inventory、Body、Mutations、Skills、Abilities、Effects、Stomach、Reputation、Quests、Journal) | ◎ | ◎ サイドバーやステータス画面が示す情報を上回る | 低 | ゲームスレッド | なし | §2.4、`PlayerStatusBar.cs:310-422` |
| G. `PopupMessage` のインスタンス状態(Title、Message、menuData、buttons) | ◎ 表示中モーダルの完全な内容 | Modern のポップアップ全般(会話、PickOption、YesNo、AskString) | 低 | **UI スレッドのみ**(uiQueue で読む) | なし | `PopupMessage.cs:18-249, 721-780` |
| H. ゲームスレッド側の `Popup.*` 引数(Harmony prefix) | ◎ 表示前の引数そのもの | ◎ Modern と Legacy の両方 | 極小 | ゲームスレッド | なし | `Popup.cs:658-2365` |
| I. `ConversationUI` の静的状態 | ◎ | 会話 | 極小 | ゲームスレッド(会話ループ中) | なし | `ConversationUI.cs:135-157` |
| J. `GameManager.CurrentGameView` | ○ いま開いているモーダルの種類 | ◎ | 極小 | どちらからでも読める | なし | `GameManager.cs:469-480` |
| K. IGameSystem の高レベルフック(QuestStarted、PlayerTook、ReputationChanged など) | ◎ | 出来事ベース | 極小 | ゲームスレッド | なし | `IGameSystem.cs:2913-3068` |
| L. ミニマップ | × 色だけ | — | — | — | — | `ActionManager.cs:367-408` |
| M. スクリーンリーダー(UAP) | × ゲームのコードから参照されていない | — | — | — | — | §1.4 |

**推奨** **[推論]**: C + E + F + K + J を主軸にし、モーダルは H(Harmony が使える場合)または G + I で補う。A はデバッグ用・配信表示用の補助にとどめる。

### 6.2 制御経路マトリクス

| 制御経路 | 信頼性 | モーダル対応 | スレッド | 主なリスク | 引用 |
|---|---|---|---|---|---|
| 1. CTA 内での直接 API(Move、AttackDirection、PassTurn、InventoryActionEvent、EquipmentAPI、`CommandEvent.Send`) | ◎(v1 で実証済み) | × 呼んだ API がポップアップを出すと、そのモーダルでブロックする | ゲームスレッド | 自動の早送り(ペーシングが必要)。副作用のポップアップ | `ActionManager.cs:789`、`LLMOfQudSystem.cs:441-707` |
| 2. CTA 内での `AutoAct.Setting` | ○ **[推論]** | × | ゲームスレッド | 中断条件(敵対、`kbhit`)。**非フォーカス時は `kbhit` の 200 ms 待ちで約 5 歩/秒に制限される**(`ActionManager.cs:810`、`Keyboard.cs:948`)。Setting の文字列仕様が変わる可能性 | `ActionManager.cs:805-1441` |
| 3. `Keyboard.PushCommand("CmdX")` | ○ 実入力と同じ経路 | △ legacy ループ(PlayerTurn、PickDirection、PickTarget、メインメニュー)だけ | 実入力は UI スレッドから積まれる(`GameManager.cs:2187, 2444`)。キューへの追加は `lock(KeyQueue)` / `lock(MouseEventQueue)` で保護されている(`Keyboard.cs:790, 831`)ので、WebSocket スレッドから積んでも破損はしないはず。ただし `ClearMouseEvents` との順序は競合しうる **[推論]** | `XRLCore.cs:734` の Clear で非移動コマンドが消える。フォーカス喪失で停止する。Tutorial のゲート | `Keyboard.cs:723-726` |
| 4. `Keyboard.PushKey` / `PushMouseEvent` | ○ | △ 3 と同じ。Legacy UI なら全ポップアップに効く | 3 と同じ(lock あり) | `bCapInputBuffer`。AutoAct 中は中断扱いになる | `Keyboard.cs:772-849` |
| 5. Harmony prefix で `Popup.*` を置き換える | ◎(x86_64 なら)**[推論]** | ◎ すべての `Popup.*` 系(会話、レベルアップ、確認、PickOption、AskString) | ゲームスレッド | **arm64 で Harmony 2.2.2 が動かない可能性**。ゲーム更新でシグネチャが変わる | `Popup.cs`、`0Harmony.dll 2.2.2.0` |
| 6. uiQueue 経由で `PopupMessage.OnActivateCommand(item)` を呼ぶ | ○ **[推論: 要実測]** | ○ Modern のポップアップ全般 | UI スレッド | インスタンスの特定(`getWindow` か `copyWindow` か)。表示完了前の競合。TutorialManager | `PopupMessage.cs:926-944`、`Popup.cs:760, 826` |
| 7. `OptionModernUI=No` にして Legacy だけで運用する | ○ **[推論]** | ◎ 全モーダルが `getvk` ループになる(3 と 4 が全面的に効く) | ゲームスレッド | Legacy UI の保守状況。配信の見た目 | `Options.xml:53`、`Popup.cs:1143-1188`、`Screens.cs:128-151` |
| 8. `NavigationController.FireInputCommandEvent` | △ **[推論]** | ○ Modern のフレームワーク画面(ステータス、取引、キャラクター作成) | UI スレッド | 画面ごとのコンテキスト構造に依存する | `NavigationController.cs:198-245` |
| 9. 外部から `ConversationUI.Select` を呼ぶ | × | × | — | `Render()` 内の `Select` と競合する(v1 の設計書は誤り) | `ConversationUI.cs:514-571` |

**推奨の組み合わせ** **[推論]**:
- 通常のターン: 1(+ 2)。
- ターゲット・方向の指定: 1 で代替する(`AttackDirection`、投擲・射撃は API で行う)か、4 を使う。
- モーダル: x86_64 なら 5、arm64 なら 6 または 7。
- キャラクター作成: ビルドコード + 5、または手動で済ませる。
- メインメニュー: 4 と `ModSensitiveCacheInit` からの起動を組み合わせる。

---

## 7. v1 → NEW の行番号の対応(v1 の資産を再利用するため)

| v1 で使っていた箇所 | NEW(2.0.211.56)での位置 |
|---|---|
| BTA の発火 | `NEW/XRL.Core/ActionManager.cs:743-746` |
| CTA の `Check` | `NEW/XRL.Core/ActionManager.cs:789` |
| `Energy>=1000 && IsPlayer` のガード | `NEW/XRL.Core/ActionManager.cs:798` |
| `PlayerTurn()` の呼び出し | `NEW/XRL.Core/ActionManager.cs:1611` |
| 描画の fallback | `NEW/XRL.Core/ActionManager.cs:1618-1621` |
| `RegisterAfterRenderCallback` | `NEW/XRL.Core/XRLCore.cs:652-655` |
| コールバックの呼び出し箇所 | `NEW/XRL.Core/XRLCore.cs:2432, 2464, 2508` |
| BackupChar の書き込み | `NEW/ConsoleLib.Console/ConsoleChar.cs:392-420`(`Set(RenderEvent)`) |
| `CmdMoveE` のラッパー | `NEW/XRL.Core/XRLCore.cs:1167-1173` |
| `CommandTakeActionEvent.Check` / `PreventAction` | `NEW/XRL.World/CommandTakeActionEvent.cs:8, 28-38` |
| `GameObject.Move` / `AttackDirection` / `hitpoints` / `IsHostileTowards` | `NEW/XRL.World/GameObject.cs:16234 / 18397 / 1176 / 11424` |
| `Cell.GetCellFromDirection` | `NEW/XRL.World/Cell.cs:8006` |
| `AutoAct.ClearAutoMoveStop` | `NEW/XRL.World.Capabilities/AutoAct.cs:414-417` |

---

## 8. 最もリスクの高い未知数(ランタイムプローブが必要)

| # | 未知数 | なぜ重要か | プローブ案 |
|---|---|---|---|
| U1 | arm64 ネイティブ起動の CoQ で Harmony 2.2.2 の `PatchAll` が成功するか。Rosetta で回避できるか。mod から 2.4 を持ち込めないので、選択肢は Rosetta、Harmony を使わない、`Managed/0Harmony.dll` の置き換えの 3 つ。QudJP の過去の成功ログ(`Player-prev.log:161`)がどの構成によるものか | 制御経路 5(モーダル全般)の可否を決める | 何もしない prefix を `Popup.ShowYesNo` に当てる最小 mod を作り、arm64 と Rosetta で起動して Player.log を確認する |
| U2 | ウィンドウが非フォーカスのとき、PlayerTurn の停止(`XRLCore.cs:737-740`)と GetNextKey の 1000 ms 待ちがどこまで効くか。`GameManager.focused=true` の強制や `runInBackground` で回避できるか | 無人運転・配信で最大の停止要因 | バックグラウンドのまま CTA 直接行動と PushCommand を行い、ターン速度を計測する |
| U3 | `PushCommand` を積むタイミング: `XRLCore.cs:734` の Clear をどう回避するか | 制御経路 3 の信頼性 | BTA / CTA / EndTurn の各時点で `PushCommand("CmdInventory")` を積み、実行されたかを記録する |
| U4 | uiQueue 経由で `PopupMessage.OnActivateCommand(new QudMenuItem{command="option:N"})` を呼んでモーダルを解決できるか。表示中かどうかの判定(`CurrentGameView`、`getWindow`)は信頼できるか | Harmony が使えない場合の主経路 | 会話・PickOption・YesNo の 3 種類で試す |
| U5 | `OptionModernUI=No` にしたとき、全モーダル(ステータス画面、取引、キャラクター作成、会話)が legacy のループで一貫して動くか。それが現行版でサポートされているか | 制御経路 7 の網羅性 | オプションを切り替えて主要画面を巡回し、PushKey で操作する |
| U6 | CTA 内で `AutoAct.Setting` を設定したとき、同じセグメントで実行されるか。中断理由を取得できるか | 自動探索・長距離移動のコストを下げる | `"?"` / `"M x,y"` / `".10"` を設定し、`AutoAct.GetDescription` とメッセージを記録する |
| U7 | PickTarget で `PushMouseEvent("PointerOver", x, y)` + Enter によって射撃・投擲の対象を指定できるか | 遠隔攻撃の制御 | 弓・投擲物を持って試す |
| U8 | AfterRenderCallback が常に CoreThread 上で呼ばれるか(UI スレッドから `RenderBase` が呼ばれる経路はないか)。static `_Buffer` を引数に渡すことの影響 | 観測 A のスレッド安全性 | コールバック内で `Thread.CurrentThread == XRLCore.CoreThread` を記録する |
| U9 | テキストモードとタイルモードでの `OverlayTile` / `BackupChar` の端のケース(壁、液体、複数オブジェクト) | 観測 A の忠実度 | 両モードで同じ地点をダンプして比較する |
| U10 | `HttpListener` が Mono/macOS で localhost に bind できるか。Newtonsoft と System.Net.Http を Roslyn の参照に含められるか | ブリッジの設計(サーバー / クライアント)と JSON 実装 | 最小のコンパイルプローブ + bind プローブ |
| U11 | `ModSensitiveCacheInit` からのメインメニュー自動操作(`"Pick:Continue"`)。Modern UI では Continue の後に `ModernSaveManagement` の選択画面が挟まる(`XRLCore.cs:3784-3786`)ので、`XRLGame.LoadGame` の直接呼び出しで代替できるか。キャラクター作成の自動化(`EmbarkBuilder.FromCode`) | 無人での再起動・再開 | 起動直後の自動ロードを試す |
| U12 | 直接 API(`InventoryActionEvent`、EquipmentAPI)の副作用で出るポップアップが Modern UI でゲームスレッドをブロックしたとき、外部からの解決経路(U1 または U4)が必要になる頻度 | 直接 API 方針の限界 | 食べる・読む・装備を繰り返してポップアップの出現を記録する |
