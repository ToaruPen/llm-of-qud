# F4: 全画面ステータス系画面（status screens family）の静的検証

- 対象ビルド: 2.0.211.56（ILSpy 逆コンパイル、`/Users/sankenbisha/Dev/coq-decompiled_stable`）
- 引用はすべてソースルートからの相対パス `path:line`。本タスクで `sed -n` / `grep -n` により表示した範囲だけを引用している。
- 作成日: 2026-09-25

## 1. 目的

Modern UI を画面に出したまま、ゲームスレッドを `.Result` で止める全画面の Modern 画面について、次の四点を静的に確定する。

1. ゲームスレッドがどう待つか（どの Task の `.Result` か、継続がどのスレッドで走るか）。
2. ブリッジスレッドまたは UI スレッドから、いま開いていると判定する述語。
3. 画面を安全に閉じる UI スレッド上の呼び出し列。エージェントは普段はこれらの画面を開かず直接 API を使うが、誤って開いたときに閉じられることと、画面内で出る確認ダイアログに答えられることが要る。
4. 画面を読む必要がある場合のデータモデル。

あわせて、人間のキー入力なしでは閉じられない画面があるか、Harmony が要る箇所があるかを示す。

## 2. 対象一覧

| # | 画面（Modern クラス） | ビュー名（`CurrentGameView`） | 入口（ゲームスレッド） | 待ち方 |
|---|---|---|---|---|
| 1 | `Qud.UI.StatusScreensScreen`（8 タブ） | `"StatusScreensScreen"` | `Screens.Show` / `Screens.ShowPopup` / `MessageQueue.Show` | `StatusScreensScreen.show(...).Result` |
| 2 | `Qud.UI.AbilityManagerScreen` | `"AbilityManagerScreen"` | `AbilityManager.Show`（`CmdAbilities`） | `OpenAbilityManager(GO).Result` |
| 3 | `Qud.UI.OptionsScreen` | `"ModernOptionsMenu"` | `OptionsUI.Show`（システムメニュー） | `OptionsMenu().Result` |
| 4 | `Qud.UI.KeybindsScreen` | `"Keybinds"` | `KeyMappingUI.Show`（システムメニュー） | `KeybindsMenu().Result` |
| 5 | `Qud.UI.HelpScreen`（範囲外だが同型なので記す） | `"ModernHelp"` | `XRLManual.ShowHelp`（`CmdHelp`） | `HelpMenu(...).Result` |
| 6 | キー割り当ての捕捉（KeybindsScreen / AbilityManagerScreen 内） | 変化なし（`ControlManager.mappingMode`） | 画面内の操作からのみ | `GetRebindAsync` の Task |
| 7 | レベルアップ・能力値/変異/スキル購入の確認 | `"PopupMessage"` / `"DynamicPopupMessage"` | `Leveler`、`StatusScreen.BuyStat` など | Popup 系（F1 の PopupMessage 系に合流） |
| 8 | 焚き火・料理 | Popup 系 | `Campfire` | 専用画面なし。`Popup.PickOption` / `AskNumber` / `Show` |
| 9 | Legacy の `XRL.UI.InventoryScreen` ほか `ScreenList` | `"Inventory"` など | `Screens.Show` の else 側 | getvk ループ。`ModernUI && ModernCharacterSheet` では到達しない |

StatusScreensScreen のタブは `BaseStatusScreen<T>` を継承する 8 クラスで、タブ文字列は Skills / Character / Inventory(&Equipment) / Tinkering / Journal / Quests / Factions / Message Log である（`Qud.UI/SkillsAndPowersStatusScreen.cs:19,68-71`、`Qud.UI/CharacterStatusScreen.cs:21,168`、`Qud.UI/InventoryAndEquipmentStatusScreen.cs:22,200`、`Qud.UI/TinkeringStatusScreen.cs:18,129-132`、`Qud.UI/JournalStatusScreen.cs:23,204-207`、`Qud.UI/QuestsStatusScreen.cs:18,45-48`、`Qud.UI/FactionsStatusScreen.cs:14,68`、`Qud.UI/MessageLogStatusScreen.cs:14,93`）。タブの並び（`Screens` リスト）は Unity のプレハブで決まり、ソースにはない。ただし次の手がかりから、index 0=Skills、1=Character、2=Inventory&Equipment、3=Tinkering、4=Journal、5=Quests、6=Factions、7=Message Log と推定できる。

- `Screens.Show` の対応表: 旧 CurrentScreen 0→0、1→1、2/3→2、4(Factions)→6、5(Quest)→5、6(Journal)→4、7(Tinkering)→3（`XRL.UI/Screens.cs:92-124`。旧 `ScreenList` の順序は `XRL.UI/Screens.cs:23-30`）。
- `STATUS_SCREEN_ORDINAL.TINKERING = 3`（`Qud.UI/StatusScreensScreen.cs:17-20`）と `SetPage(3)`（`Qud.UI/TinkeringStatusScreen.cs:114-118`）。
- メッセージログは `show(7, ...)`（`XRL.Messages/MessageQueue.cs:78-83`）。
- チュートリアルは `CurrentScreen == 2` をインベントリとして扱う（`JoppaTutorial/BattleRemains.cs:225-229`）。

## 3. 各モーダルの動作

### 3.1 共通の仕組み: `.Result`、`await The.UiContext`、`SuspendContextWhile`

- `The.UiContext` は `GameManager.uiSynchronizationContext` で（`XRL/The.cs:41`）、Unity メインスレッドの `SynchronizationContext.Current` を起動時に保存したものである（`GameManager.cs:869`）。`await The.UiContext` は独自の awaiter で、現在のコンテキストが UI でなければ `Post` で継続を UI スレッドへ送る（`XRL/SynchronizationContextAwaiter.cs:16-21`）。
- ゲームスレッドの `SynchronizationContext` は素の `new SynchronizationContext()` である（`XRL.Core/XRLCore.cs:3553-3559`）。ゲームスレッドで始まった `await` の継続はスレッドプールに `Post` される。だから `.Result` でゲームスレッドを止めてもデッドロックしない。
- `NavigationController.SuspendContextWhile<T>` は、呼ばれたスレッドで `activeContext` を `suspensionContext` に差し替え、Task の完了後に `finally` で戻す（`XRL.UI.Framework/NavigationController.cs:156-176`）。ゲームスレッドから呼ばれた場合、この `finally` はスレッドプールで走る。
- `NavigationContext.IsActive()` は `navigationController.activeContext` から親をたどって自分に着くかを見る（`XRL.UI.Framework/NavigationContext.cs:124-132`）。画面のルート context に対して `IsActive()` が真なら、その画面は入れ子の入力待ちがなく、操作を受け付ける状態にある。
- `GameManager.PushGameView` / `PopGameView` は `GameViewStack` を lock して `CurrentGameView` を書き換える（`GameManager.cs:1493-1510, 1523-1541`）。`CurrentGameView` の getter は lock を取らない（`GameManager.cs:469-481`）。参照の読み取りは原子的なので、どのスレッドから読んでもよい。ただしスナップショットにすぎない。
- `uiQueue.queueTask` は lock つきのキューに積む（`QupKit/ThreadTaskQueue.cs:157-170`）。積まれたタスクは `GameManager.Update` の `uiQueue.executeTasks()` で UI スレッドで実行される（`GameManager.cs:2963`）。

### 3.2 StatusScreensScreen

**入口。** `Screens.Show(GO)` は `Options.ModernUI && Options.ModernCharacterSheet` のとき `StatusScreensScreen.show(startingScreen, GO).Result` を呼ぶ（`XRL.UI/Screens.cs:88-127`）。`ShowPopup("Factions", ...)` も同様である（`XRL.UI/Screens.cs:39-86`）。呼び出し元は次のとおり。

- `XRLCore` のコマンド: `CmdJournal` / `CmdTinkering`（`XRL.Core/XRLCore.cs:1706-1712`）、`CmdFactions` / `CmdQuests` / `CmdLastStatusPage` / `CmdCharacter` / `CmdInventory` / `CmdEquipment` / `CmdSkillsPowers`（`XRL.Core/XRLCore.cs:1889-1918`）。
- 自分自身のコンテナを開いたとき（`XRL.World.Parts/Container.cs:100-103`）。
- `MessageQueue.Show()`（`XRL.Messages/MessageQueue.cs:78-83`）。呼び出し元は `CmdMessageHistory`（`XRL.Core/XRLCore.cs:2296-2297`）。

`OptionModernCharacterSheet` の既定は Yes である（プロジェクト資料 `docs/exploration/data/opt_table.md:47`）。

**待ち方。** `show()` は `CurrentScreen` と static `GO` を設定し、`SuspendContextWhile(() => showScreen(...))` を返す（`Qud.UI/StatusScreensScreen.cs:128-134`）。`showScreen` の流れは次のとおり（`Qud.UI/StatusScreensScreen.cs:136-187`）。

1. ゲームスレッドで `MinEvent.UIHold = true` と `PushGameView("StatusScreensScreen")` を実行する（:140-141）。
2. `await The.UiContext` で UI スレッドへ移る（:144）。
3. レイアウトを設定し、`UpdateViewFromData()`（:176）で `SetupContexts` → `UpdateActiveScreen` → サブ画面の `ShowScreen` と `navigationContext.ActivateAndEnable()` を行う（:283-292, :353-427, :429-434）。
4. `menucomplete = new TaskCompletionSource<ScreenReturn>()` を作り直して `await menucomplete.Task` する（:177-178）。
5. 完了後、UI スレッドの `finally` で `UIHold = false` と `PopGameView()` を実行する（:182-186）。

ゲームスレッドは `Screens.cs:80` / `:125` の `.Result` で止まる。ゲームスレッドへの復帰は、`menucomplete` の完了（UI）→ `showScreen` の `finally`（UI）→ `SuspendContextWhile` の `finally`（スレッドプール）→ `.Result` の解除、という順で起きる。

**閉じ方。** `Exit()` は public で、各サブ画面の `IStatusScreen.Exit()` を呼び、`menucomplete.TrySetResult(ScreenReturn.Exit)`、`freeTabs()`、`Hide()` の順に進む（`Qud.UI/StatusScreensScreen.cs:225-238`）。Cancel ボタンのハンドラも `Exit` である（:371-375）。`OnCloseButton` と `BackgroundClicked` は `navigationContext.IsActive()` を確かめてから `Exit()` を呼ぶ（:217-223, :444-450）。ゲーム自身も、アイテム操作で `bDone` が立つとプログラムから `statusScreensScreen.Exit()` を呼ぶ（`Qud.UI/InventoryAndEquipmentStatusScreen.cs:402-405`）。したがって UI スレッドから `Exit()` を呼ぶことは、正規の経路に当たる。Harmony は要らない。

**競合の注意（`menucomplete` の作り直し）。** `menucomplete` は UI スレッドの継続の中で :177 で作り直される。`CurrentGameView == "StatusScreensScreen"` になるのは、それより前のゲームスレッドの :141 である。その間に `Exit()` を呼ぶと、古い（完了済みの）TCS に結果を入れるだけで終わる。直後に :177 が新しい TCS を作るので、画面は開いたまま残る。そこで、:292 の `ActivateAndEnable` が済んで初めて真になる `navigationContext.IsActive()` を必須のガードにする。`navigationContext` → `screenGlobalContext` → `vertNav` → `horizNav` → サブ画面の context、という親子関係は :408-414 と :289-292 で張られる。`Update` と `menucomplete` の実行順は UnitySynchronizationContext と uiQueue の順序で決まり、静的には確定しない（実機項目 R1）。

**入れ子の処理（確認ダイアログの出どころ）。** サブ画面の操作は `APIDispatch.RunAndWaitAsync` を通る。これは `SuspendContextWhile` の中で `Task.Run` を呼び、ゲームロジックを**スレッドプール**で実行する（`XRL.UI.Framework/APIDispatch.cs:46-80`）。例は次のとおり。

- インベントリの選択: `EquipmentAPI.TwiddleObject`（`Qud.UI/InventoryAndEquipmentStatusScreen.cs:380-411`）。
- 装備スロット: `EquipmentScreen.ShowBodypartEquipUI` → `PickItem.ShowPicker`（`Qud.UI/InventoryAndEquipmentStatusScreen.cs:451-456`、`XRL.UI/EquipmentScreen.cs:26-45`）。
- 能力値の購入: `StatusScreen.BuyStat`（`Qud.UI/CharacterStatusScreen.cs:343-353`）。
- 変異の詳細: `ShowMutationPopup`（`Qud.UI/CharacterStatusScreen.cs:355-367`）。
- 変異の購入: `MutationsAPI.BuyRandomMutation`（`Qud.UI/CharacterStatusScreen.cs:418-425`）。
- スキルの購入: `SkillsAndPowersScreen.SelectNode`（`Qud.UI/SkillsAndPowersLine.cs:71-80`）。

これらの中の `Popup.ShowYesNo` / `Popup.Show` / `Popup.PickOption` は、スレッドプールのスレッドを `WaitNewPopupMessage` の非 UI 分岐で止める。この分岐では `uiQueue.awaitTask` で `PushGameView("PopupMessage")` した PopupMessage を出す（`XRL.UI/Popup.cs:823-829`）。確認の具体例は次のとおり。

- 能力値の確認: `StatusScreen.BuyStat` の `ShowYesNo`（`XRL.UI/StatusScreen.cs:62-80`）。
- 変異購入の確認: `MutationsAPI.cs:111`。
- 変異の選択: `StatusScreen.cs:699` の `PickOption`。
- スキル購入の確認: `SkillsAndPowersScreen.cs:159, 212`。

UI スレッドから直接出るポップアップもある。インベントリの Options（`Qud.UI/InventoryAndEquipmentStatusScreen.cs:643-649`）と派閥の Sort（`Qud.UI/FactionsStatusScreen.cs:188-190`）は `Popup.PickOptionAsync` を使う。`PickOptionAsync` は `activeContext` を `suspensionContext` に差し替え、callback つきの `PickOption(..., ForceNewPopup: true)` を呼んで待つ（`XRL.UI/Popup.cs:1624-1642`）。UI スレッドで `WaitNewPopupMessage` が呼ばれると `NewPopupMessageAsync` に分岐し（`XRL.UI/Popup.cs:804-822`）、`copyWindow` の複製がビュー名 `"DynamicPopupMessage"` で出る（`XRL.UI/Popup.cs:751-799`）。ただし `PickOption` から `WaitNewPopupMessage` に至る経路は、本書では追っていない（F1 の範囲）。

要するに、ステータス画面の中の確認は F1 の PopupMessage 系レシピでそのまま答えられる。ただし二点に注意する。

1. 待っているのはゲームスレッドではなく、スレッドプールのスレッドである。「ゲームスレッドが止まっている」ことを前提にした検出や、トークンの設計を持ち込まない。
2. この間、ゲームスレッドは `.Result` で止まっているので `gameQueue` は回らない。ブリッジがゲームスレッド向けに積んだ仕事は、画面を閉じるまで実行されない。

なお、ピッカーが開くと StatusScreensScreen は自分の canvas を隠し、`"StatusScreensScreen"` に戻ると再表示する。ピッカーのビュー名は `"PickDirection"` / `"PickTarget"` の場合（`Qud.UI/StatusScreensScreen.cs:96, 467-482`）と、`"PickGameObject"` の場合がある。`"PickGameObject"` のときは `UIManager._showWindow` がステータス画面を Hide しない例外がある（`Qud.UI/UIManager.cs:386-401`）。

**読むためのデータモデル。** 画面を読むより、同じソースを直接読むほうが確実である。

| タブ | 画面が使っているデータ |
|---|---|
| Character | `GO.Statistics`、`StatusScreen.GetMutationList(GO)`、`GO.Effects`（`Qud.UI/CharacterStatusScreen.cs:180-195`） |
| Inventory | `GO.Inventory.Objects`（`Qud.UI/InventoryAndEquipmentStatusScreen.cs:484-501`） |
| Skills | `SkillsAndPowersScreen.BuildNodes(GO)` / `SkillsAndPowersScreen.Nodes`（`Qud.UI/SkillsAndPowersStatusScreen.cs:264, 335`） |
| Quests | `QuestsAPI.allQuests()`（`Qud.UI/QuestsStatusScreen.cs:59, 111`） |
| Factions | `FactionsScreen.getFactionsByName()` と `Factions.Get`（`Qud.UI/FactionsStatusScreen.cs:159`） |
| Journal | `JournalScreen.GetRawEntriesFor(category)`（`Qud.UI/JournalStatusScreen.cs:238`） |
| Message Log | `The.Game.Player.Messages.Messages`（`Qud.UI/MessageLogStatusScreen.cs:115`） |
| Tinkering | `TinkerData.KnownRecipes`（`Qud.UI/TinkeringStatusScreen.cs:144`） |

いま表示中のタブは、public の `CurrentScreen` から `CurrentScreen % Screens.Count` で分かる（`Qud.UI/StatusScreensScreen.cs:54, 250`）。

### 3.3 AbilityManagerScreen

**入口。** `CmdAbilities` → `AbilityManager.Show(The.Player)` → Modern では `AbilityManagerScreen.OpenAbilityManager(GO).Result` と進み、結果の `ability?.Command` を返す（`XRL.UI/AbilityManager.cs:138-156`）。XRLCore はそのコマンドを `CommandEvent.Send(The.Player, text6)` で送る（`XRL.Core/XRLCore.cs:1806-1818`）。

**待ち方。** `OpenAbilityManager` は `SuspendContextWhile(() => showScreen(GO))` である（`Qud.UI/AbilityManagerScreen.cs:202-205`）。`showScreen` の流れは次のとおり。

1. ゲームスレッドで `menucomplete.TrySetCanceled()` の後に新しい TCS を作る（:168-169）。
2. `ActivatedAbilities` が null なら、`Hide()` して `Popup.ShowAsync("You have no activated abilities.")` を呼ぶ（:170-177）。このポップアップはビューを push する前、ゲームスレッドで出る。
3. `PushGameView("AbilityManagerScreen")`（:178）、`UIHold = true`（:181）、`await The.UiContext`（:182）と進む。
4. UI スレッドで `BeforeShow()` を呼び、項目が 0 件なら `Popup.ShowAsync` を出して戻る（:184-190）。
5. `Show()` と `leftSideScroller.scrollContext.ActivateAndEnable()` の後、`await menucomplete.Task`（:191-193）。
6. `finally` で `PopGameView(bHard: true)` を実行する（:195-199）。

**答え方と閉じ方。** どちらも public で、Harmony は要らない。

- 選択: `HandleSelectLeft(element)` に `filteredItems` の要素を渡す（`Qud.UI/AbilityManagerScreen.cs:439-460`）。`category != null` の行なら折りたたみの切り替えになる。`NotUsableDescription` が空でない行なら `Popup.Show` が出るだけで、完了しない。それ以外なら `menucomplete.TrySetResult(new Result{ability})` で完了する。
- キャンセル: `Cancel()`（:425-433）。`AbilityManagerLine.dragging` が真だと何もしない（`Qud.UI/AbilityManagerLine.cs:59`）。

ガードは `navigationContext.IsActive()` にする。context の親子関係は `leftSideScroller.scrollContext.parentContext = vertNav`、`vertNav.parentContext = navigationContext` である（:124, :160）。

**読む。** `filteredItems`（public。`Qud.UI/AbilityManagerScreen.cs:55`）の各 `AbilityManagerLineData` を読む。行の中身は `ability`（`ActivatedAbilityEntry`）、`category`、`hotkeyDescription` である（:228-283）。

**推奨。** エージェントはこの画面を開かない。`The.Player.ActivatedAbilities` を読み、`CommandEvent.Send(The.Player, command)` を直接呼ぶほうがよい。XRLCore がこの画面の結果でやっていることと同じである（`XRL.Core/XRLCore.cs:1809-1818`）。

### 3.4 OptionsScreen（`"ModernOptionsMenu"`）

- 入口: `OptionsUI.Show()` は Modern では `SingletonWindowBase<OptionsScreen>.instance.OptionsMenu().Result` を呼ぶ（`XRL.UI/OptionsUI.cs:67-73`）。システムメニューから呼ばれる（`XRL.Core/XRLCore.cs:1130-1135`）。
- 待ち方: `OptionsMenu()` は `SuspendContextWhile` を使わない（`Qud.UI/OptionsScreen.cs:120-170`）。次の順に進む。
  1. 呼び出したスレッドで `PushGameView("ModernOptionsMenu")`（:123）。
  2. `completionSource` を作り直す（:159-160）。
  3. `await The.UiContext` と `Show()`（:161-165）。
  4. `await completionSource.Task`（:166）。
  5. UI スレッドで `Hide()` と `PopGameView(bHard: true)`（:168-170）。
- 閉じ方: public の `Exit()` が `completionSource?.TrySetResult(false)` を行う（`Qud.UI/OptionsScreen.cs:214-217`）。Cancel ボタンと戻るボタンのハンドラも `Exit` である（:290, :436）。TCS はビューを push した直後、同じゲームスレッドで作られる。だから「ビュー名が見えたが、TCS はまだ古い」という窓は、StatusScreensScreen より狭い。ただしゼロではない（:123 と :160 の間）。述語には `completionSource != null && !completionSource.Task.IsCompleted` を加える。
- 読む必要はない。オプションは `Options.GetOption` / static フィールドで直接読む。

### 3.5 KeybindsScreen（`"Keybinds"`）

- 入口: `KeyMappingUI.Show()` は Modern では `PushGameView("Keybinds")` の後に `KeybindsMenu().Result` を呼び、終わると `PopGameView` する（`XRL.UI/KeyMappingUI.cs:73-87`）。
- 待ち方: `KeybindsMenu()` は、UI に移ってから `completionSource` を作り直し、`await completionSource.Task` する（`Qud.UI/KeybindsScreen.cs:129-145`）。
- 閉じ方: `Exit()` は `async void` である（`Qud.UI/KeybindsScreen.cs:147-166`）。`bChangesMade`（public。:83）が真なら、先に `Popup.ShowYesNoCancelAsync("Would you like to save your changes?")` を出す。これは DynamicPopupMessage 系で、F1 のレシピで答える。Cancel なら閉じない。偽なら即座に `TrySetResult(false)` する。
- キー捕捉の待ち: `HandleRebindAsync` は `SuspendContextWhile` の中で `ControlManager.SuspendControlsWhile(() => CommandBindingManager.GetRebindAsync(...))` を待つ（`Qud.UI/KeybindsScreen.cs:539-543, 555-561`）。`GetRebindAsync` は Unity InputSystem の `RebindingOperation` をローカル変数で持つ。完了の経路は三つしかない。
  - 本物の入力デバイスの操作。
  - Cancel に割り当てた keyboard コントロール（`WithCancelingThrough`）。
  - `WithTimeout(10f)`。

  該当箇所は `XRL.UI/CommandBindingManager.cs:1912-1920, 1950-1958, 2018-2019`。外から `RebindingOperation` を触る手段はない。捕捉中は `ControlManager.mappingMode = true` になる（`ControlManager.cs:339, 2250-2267`）。

### 3.6 HelpScreen（`"ModernHelp"`。範囲外だが同型）

`XRLManual.ShowHelp` は `PushGameView("ModernHelp")` の後に `HelpMenu(DefaultPage).Result` を呼ぶ（`XRL.Help/XRLManual.cs:190-208`）。`HelpMenu` の流れは OptionsScreen と同型で、`completionSource` を作り直し、UI に移って `Show()` し、`await completionSource.Task` する（`Qud.UI/HelpScreen.cs:57-86`）。閉じるには public の `Exit()` を呼ぶ（:93-96）。

### 3.7 レベルアップと購入の確認

レベルアップの処理 `Leveler` は、ゲームスレッドから `Popup.Show`（`XRL.World.Parts/Leveler.cs:289`）、`Popup.ShowYesNo(..., AllowEscape: false)`（:325）、`Popup.PickOption`（:341）を直接呼ぶ。専用の Modern 画面はない。変異の選択（`XRL.UI/StatusScreen.cs:699`）とスキル購入の確認（`XRL.UI/SkillsAndPowersScreen.cs:159, 212`）も Popup 系である。

ステータス画面の外で `StatusScreen.BuyStat` / `MutationsAPI.BuyRandomMutation` / `SkillsAndPowersScreen.SelectNode` をゲームスレッドから直接呼んでも、出てくるのは同じ Popup である（`XRL.UI/StatusScreen.cs:62-80`、`Qud.API/MutationsAPI.cs:95-118`、`XRL.UI/SkillsAndPowersScreen.cs:141-160`）。したがってレベルアップ系は F1 の PopupMessage 系で閉じる。スキル画面の選択（`HandleSelectItem`）は詳細表示を更新するだけで、購入はしない（`Qud.UI/SkillsAndPowersStatusScreen.cs:246-252`）。購入は行側の `Accept` から走る（`Qud.UI/SkillsAndPowersLine.cs:71-80`）。

### 3.8 焚き火と料理

`Campfire` は `Popup.Show` / `Popup.PickOption` / `Popup.AskNumber` だけを使う（`XRL.World.Parts/Campfire.cs:680, 693, 952, 1030`）。専用画面はなく、F1 の範囲である。

### 3.9 Legacy の InventoryScreen ほか

`XRL.UI.InventoryScreen` / `EquipmentScreen` / `StatusScreen` / `SkillsAndPowersScreen` / `FactionsScreen` / `QuestLog` / `JournalScreen` / `TinkeringScreen` の `Show` は、`Screens.Show` の Legacy 分岐（`ScreenList` の getvk ループ）からしか呼ばれない（`XRL.UI/Screens.cs:22-32, 128-151`。grep で `new InventoryScreen` などの呼び出しは `Screens.cs` 以外にない）。`ModernUI && ModernCharacterSheet` では到達しない。

`TinkeringScreen.Show` は両方が真なら即座に `Exit` を返す（`XRL.UI/TinkeringScreen.cs:21-26`）。Modern ではアイテムの "Mod" コマンドが `Physics` で `false` を返す（`XRL.World.Parts/Physics.cs:2725-2729`）。代わりに `TinkeringStatusScreen.StartupModItemWithTinkering` が Tinkering タブ（3）に切り替える（`Qud.UI/TinkeringStatusScreen.cs:114-118`、`Qud.UI/InventoryAndEquipmentStatusScreen.cs:398-401`）。

`ModernUI=Yes` かつ `ModernCharacterSheet=No` の混成では、Legacy のステータス画面が通過入力つきで動く（`Qud.UI/UIManager.cs:165-200`、`GameManager.cs:1828-1840`）。この構成は本書の範囲外で、未検証である。

## 4. レシピ表

表中の「UI」は `GameManager.Instance.uiQueue.queueTask(...)` の中、つまり UI スレッドを意味する。「任意」はどのスレッドから読んでもよいことを意味する。

| modal | wait_kind | trigger_for_probe（ゲームスレッドの wish） | detect | read | answer | cancel | Harmony |
|---|---|---|---|---|---|---|---|
| StatusScreensScreen | ゲームスレッドの `show(...).Result`。中の操作はスレッドプールの `Task.Run` | `Screens.CurrentScreen = 2; Screens.Show(The.Player);`（または `The.Game.Player.Messages.Show()`） | 任意: `CurrentGameView == "StatusScreensScreen"`。UI: `SingletonWindowBase<StatusScreensScreen>.instance.navigationContext.IsActive()` | 直接 API（3.2 の表）。表示中のタブは `instance.CurrentScreen % instance.Screens.Count` | 画面内の確認は F1 のレシピ（待っているのはスレッドプール） | UI: 二つのガードを確かめて `instance.Exit()` | 不要 |
| AbilityManagerScreen | ゲームスレッドの `OpenAbilityManager(GO).Result` | `AbilityManager.Show(The.Player)`。能力 0 件のキャラなら Popup になる | 任意: `CurrentGameView == "AbilityManagerScreen"`。UI: `instance.navigationContext.IsActive() && !AbilityManagerLine.dragging` | `instance.filteredItems[i].ability.{DisplayName, Command, NotUsableDescription}`、`.category` | UI: `instance.HandleSelectLeft(instance.filteredItems[i])`（`ability != null` かつ `NotUsableDescription` が空の行） | UI: `instance.Cancel()` | 不要 |
| OptionsScreen | ゲームスレッドの `OptionsMenu().Result` | `OptionsUI.Show()` | 任意: `CurrentGameView == "ModernOptionsMenu"`。UI: `instance.completionSource != null && !instance.completionSource.Task.IsCompleted` | 不要（`Options.*`） | なし | UI: `instance.Exit()` | 不要 |
| KeybindsScreen | ゲームスレッドの `KeybindsMenu().Result` | `KeyMappingUI.Show()` | 任意: `CurrentGameView == "Keybinds"`。UI: `completionSource` が未完了、かつ `!ControlManager.mappingMode` | 不要 | なし | UI: `instance.Exit()`。`bChangesMade` が真なら続いて出る DynamicPopupMessage に F1 のレシピで "No" と答える | 不要 |
| キー捕捉（GetRebindAsync） | UI 側の `RebindingOperation`。外側の Exit などを待たせる | KeybindsScreen の行で Accept（プローブでは開かない） | `ControlManager.mappingMode == true` | なし | 物理キーのみ | 10 秒のタイムアウトを待つ。即座に止めるには Harmony が要る | 即座の中止には必要: `CommandBindingManager.GetRebindAsync` を prefix して `Task.FromResult<List<string>>(null)` を返す |
| HelpScreen | ゲームスレッドの `HelpMenu(...).Result` | `The.Manual.ShowHelp("")` | 任意: `CurrentGameView == "ModernHelp"`。UI: `completionSource` が未完了 | `The.Manual.Pages` | なし | UI: `instance.Exit()` | 不要 |
| レベルアップ・購入の確認 | ゲームスレッドまたはスレッドプールの `WaitNewPopupMessage` | `The.Player.AwardXP(...)`、または AP を持たせて `StatusScreen.BuyStat(The.Player, "Strength")` | F1: `"PopupMessage"` / `"DynamicPopupMessage"` の述語 | F1 | F1 | F1（`Leveler.cs:325` は `AllowEscape: false`） | 不要（F1 の前提による） |

## 5. 主張一覧

- **C-F4-status-screens-01（high）** Modern のステータス画面は `Options.ModernUI && Options.ModernCharacterSheet` のときに限り、`StatusScreensScreen.show(...).Result` でゲームスレッドを止める。どちらかが偽なら Legacy の `ScreenList` ループに入る。根拠: `XRL.UI/Screens.cs:45,80,90,125,128-151`。
- **C-F4-status-screens-02（high）** ステータス画面の入口は、XRLCore のコマンド 9 種、自分のコンテナ、`MessageQueue.Show` である。いずれもゲームスレッドから `.Result` で待つ。根拠: `XRL.Core/XRLCore.cs:1706-1712,1889-1918,2296-2297`、`XRL.World.Parts/Container.cs:100-103`、`XRL.Messages/MessageQueue.cs:78-83`。
- **C-F4-status-screens-03（high）** `showScreen` は `PushGameView("StatusScreensScreen")` をゲームスレッドで行い、UI スレッドに移ってから `menucomplete` を作り直す。ビュー名が見えてから完了させてよい TCS ができるまでに窓がある。根拠: `Qud.UI/StatusScreensScreen.cs:136-187`（:141, :144, :177-178）。
- **C-F4-status-screens-04（high）** `StatusScreensScreen.Exit()` は public で、`menucomplete.TrySetResult(ScreenReturn.Exit)` と `Hide()` を行う。ゲーム自身も、アイテム操作の後にこれをプログラムから呼ぶ。UI スレッドから呼べば Harmony なしで閉じられる。根拠: `Qud.UI/StatusScreensScreen.cs:225-238`、`Qud.UI/InventoryAndEquipmentStatusScreen.cs:402-405`。
- **C-F4-status-screens-05（high）** `navigationContext.IsActive()` は、画面の初期化（`ActivateAndEnable`）が済み、かつ入れ子の `SuspendContextWhile`（APIDispatch やポップアップ）がないときに限って真になる。ゲーム自身も閉じる前にこれを確かめる。閉じる前の必須ガードに使える。根拠: `XRL.UI.Framework/NavigationContext.cs:124-132`、`XRL.UI.Framework/NavigationController.cs:156-176`、`Qud.UI/StatusScreensScreen.cs:217-223,289-292,408-414,444-450`。
- **C-F4-status-screens-06（high）** ステータス画面内のゲーム操作は `APIDispatch.RunAndWaitAsync` → `Task.Run` でスレッドプールで実行される。その中の確認ポップアップが止めるのはスレッドプールのスレッドであり、ゲームスレッドではない。根拠: `XRL.UI.Framework/APIDispatch.cs:46-80`、`Qud.UI/InventoryAndEquipmentStatusScreen.cs:394-397`、`Qud.UI/CharacterStatusScreen.cs:343-367`、`Qud.UI/SkillsAndPowersLine.cs:71-80`。
- **C-F4-status-screens-07（high）** 画面内の確認（能力値、変異、スキルの購入）は、どれも `Popup.ShowYesNo` / `Popup.PickOption` / `Popup.Show` である。専用の Modern ダイアログはない。根拠: `XRL.UI/StatusScreen.cs:62-80,699`、`Qud.API/MutationsAPI.cs:111`、`XRL.UI/SkillsAndPowersScreen.cs:159,212`。
- **C-F4-status-screens-08（medium）** インベントリの Options と派閥の Sort は、UI スレッドから `Popup.PickOptionAsync` を呼ぶ。`PickOptionAsync` は `activeContext` を `suspensionContext` に差し替えるので、その間は画面の `IsActive()` が偽になる。ポップアップは UI スレッドの経路（`NewPopupMessageAsync` の `"DynamicPopupMessage"` 複製）で出ると推定する。`PickOption` の内部の経路は追っていない。根拠: `Qud.UI/InventoryAndEquipmentStatusScreen.cs:643-649`、`Qud.UI/FactionsStatusScreen.cs:188-190`、`XRL.UI/Popup.cs:1624-1642,751-799,804-822`。
- **C-F4-status-screens-09（medium）** タブの index は 0=Skills、1=Character、2=Inventory&Equipment、3=Tinkering、4=Journal、5=Quests、6=Factions、7=Message Log である。プレハブ順は静的には見えないので推定にとどまる。根拠: `XRL.UI/Screens.cs:92-124`、`Qud.UI/StatusScreensScreen.cs:17-20`、`Qud.UI/TinkeringStatusScreen.cs:114-118`、`XRL.Messages/MessageQueue.cs:82`、`JoppaTutorial/BattleRemains.cs:225-229`。
- **C-F4-status-screens-10（high）** ステータス画面が開いている間、ゲームスレッドは `.Result` で止まっている。ブリッジが `gameQueue` に積んだ仕事は、画面を閉じるまで実行されない。根拠: `XRL.UI/Screens.cs:80,125`。`gameQueue.executeTasks` の呼び出し元は `ConsoleLib.Console/Keyboard.cs:1040`、`XRL.Core/XRLCore.cs:2604`、`XRL.UI/Look.cs:658,933` だけである。
- **C-F4-status-screens-11（high）** `AbilityManager.Show` は Modern では `OpenAbilityManager(GO).Result` で待ち、選ばれた能力の `Command` を返す。XRLCore はそれを `CommandEvent.Send` で送る。画面を開かずに同じ API を直接呼べる。根拠: `XRL.UI/AbilityManager.cs:138-156`、`XRL.Core/XRLCore.cs:1806-1818`。
- **C-F4-status-screens-12（high）** AbilityManagerScreen は、public の `HandleSelectLeft(filteredItems[i])` で完了させられ、public の `Cancel()` でキャンセルできる。`Cancel` は `AbilityManagerLine.dragging` が真だと何もしない。`NotUsableDescription` がある行を選んでも完了しない。根拠: `Qud.UI/AbilityManagerScreen.cs:55,425-433,439-460`、`Qud.UI/AbilityManagerLine.cs:59`。
- **C-F4-status-screens-13（high）** AbilityManagerScreen の `menucomplete` は、`PushGameView` より前にゲームスレッドで作り直される。能力が null または 0 件のときは画面を出さずに Popup を出す。根拠: `Qud.UI/AbilityManagerScreen.cs:163-200`（:168-169, :170-177, :178, :184-190）。
- **C-F4-status-screens-14（high）** OptionsScreen は `SuspendContextWhile` を使わずに `completionSource` を待つ。public の `Exit()` は `TrySetResult(false)` だけを行う。ビュー名は `"ModernOptionsMenu"` である。根拠: `XRL.UI/OptionsUI.cs:67-73`、`Qud.UI/OptionsScreen.cs:120-170,214-217`。
- **C-F4-status-screens-15（high）** KeybindsScreen の `Exit()` は `async void` である。`bChangesMade` が真なら、閉じる前に Yes/No/Cancel のポップアップを出し、Cancel なら閉じない。根拠: `Qud.UI/KeybindsScreen.cs:83,147-166`、`XRL.UI/KeyMappingUI.cs:73-87`。
- **C-F4-status-screens-16（medium）** キー割り当ての捕捉（`GetRebindAsync`）は、ローカルの `RebindingOperation` を物理入力、Cancel キー、10 秒のタイムアウトのいずれかで終える。Harmony なしで即座に中止する手段はない。タイムアウトで null（取り消し）になるかは Unity InputSystem の挙動で、実機で確かめる。根拠: `XRL.UI/CommandBindingManager.cs:1912-1920,1950-1958,2018-2019`、`ControlManager.cs:2250-2267`。
- **C-F4-status-screens-17（high）** HelpScreen は `"ModernHelp"` ビューで `HelpMenu(...).Result` を待つ。閉じるには public の `Exit()` を呼ぶ。根拠: `XRL.Help/XRLManual.cs:190-208`、`Qud.UI/HelpScreen.cs:57-96`。
- **C-F4-status-screens-18（high）** レベルアップ（`Leveler`）は専用画面を持たず、ゲームスレッドから Popup を直接呼ぶ。急速変異の問いは `AllowEscape: false` で、キャンセルできない。根拠: `XRL.World.Parts/Leveler.cs:289,325,341`。
- **C-F4-status-screens-19（high）** 焚き火と料理は Popup 系だけで構成され、専用画面を持たない。根拠: `XRL.World.Parts/Campfire.cs:680,693,952,1030`。
- **C-F4-status-screens-20（high）** Legacy の `XRL.UI.InventoryScreen` などの `Show` は `Screens.Show` の Legacy 分岐からしか呼ばれない。Modern 構成では到達しない。`TinkeringScreen.Show` は Modern 構成では即座に Exit を返す。根拠: `XRL.UI/Screens.cs:22-32,128-151`、`XRL.UI/TinkeringScreen.cs:21-26`。
- **C-F4-status-screens-21（high）** `await The.UiContext` の継続は UI へ `Post` される。ゲームスレッドの SynchronizationContext は素のものなので、`.Result` の解除はスレッドプール経由になる。閉じてから `.Result` が返るまでに、少なくとも 1 回の UI の `Post` とスレッドプールの継続が挟まる。根拠: `XRL/SynchronizationContextAwaiter.cs:16-21`、`XRL.Core/XRLCore.cs:3553-3559`、`XRL.UI.Framework/NavigationController.cs:156-176`。
- **C-F4-status-screens-22（medium）** `MinEvent.UIHold` は、ステータス画面とアビリティ画面が開いている間だけ真になる補助信号で、どのスレッドからでも読める static bool である。APIDispatch の実行中は偽に戻る。書き込み以外で参照する箇所はない。根拠: `Qud.UI/StatusScreensScreen.cs:140,184`、`Qud.UI/AbilityManagerScreen.cs:181,198`、`XRL.UI.Framework/APIDispatch.cs:49-50,75`。

## 6. 実機でしか分からないこと

- **R1** `await The.UiContext` の継続（UnitySynchronizationContext）と、`uiQueue.executeTasks()` の実行順。ステータス画面の :144-:178 は同期的に走るので、一度 UI に入れば割り込まれない。ただし、ビュー名が見えてから `IsActive()` が真になるまでのフレーム数は、実機で測る。
- **R2** `Screens`（タブ）のプレハブ順と `Screens.Count` が 8 であること。プローブで `instance.Screens[i].GetComponent<IStatusScreen>().GetTabString()` を列挙して確かめる。
- **R3** `Exit()` の後、`CurrentGameView` が元に戻り、ゲームスレッドが次の入力待ちに入るまでの遅延。スレッドプールの継続が入るので、閉じたことは「ビュー名が戻る」と「ゲームスレッドが CTA / getvk に戻る」の両方で確かめる。
- **R4** `RebindingOperation.WithTimeout(10f)` が満了したとき、`OnCancel` が呼ばれて null が返るか（Unity InputSystem の仕様）。
- **R5** ステータス画面の上に出た PopupMessage（スレッドプールが待つ）に、F1 のレシピで答えると、APIDispatch が正常に戻り、`navigationContext.IsActive()` が真に戻ること。
- **R6** `AbilityManagerScreen.HandleSelectLeft` を UI スレッドから呼んだとき、`leftSideScroller` の選択状態と不整合が起きないこと。
- **R7** Joppa で新規に始めたキャラクターが、アクティブ能力を 1 件以上持つか。プローブが Popup の経路に入るかどうかが決まる。

## 7. 未解決の問い

- **Q1** `ModernUI=Yes` かつ `ModernCharacterSheet=No` の混成で、Legacy のステータス画面が Modern の画面上にどう描かれるか。配信で見えるか、PushKey で操作できるか。エージェントが誤って開いたときの逃げ道になるかもしれない。
- **Q2** 閉じる操作を APIDispatch の実行中（`IsActive()` が偽）に誤って行うと、ゲームスレッドとスレッドプールのゲームロジックが並行して走る。ガードでは防げるが、UI スレッドで予約してから実行されるまでの間に状態が変わる競合を、トークンで防ぐ必要があるか。
- **Q3** `OptionModernCharacterSheet` をエージェントの運用で固定するか。既定は Yes（`docs/exploration/data/opt_table.md:47`）で、本書は Yes を前提にしている。
- **Q4** TutorialManager のゲート（`TutorialManager.AllowInventoryInteract` など。`Qud.UI/InventoryAndEquipmentStatusScreen.cs:390`）が、チュートリアル以外の開始で常に真になるか。
