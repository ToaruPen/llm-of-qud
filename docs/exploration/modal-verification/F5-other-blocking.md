# F5: そのほかのブロッキング画面（取引・本・端末・終了画面・Sifrah・チュートリアル・終局・死亡・メインメニュー・キャラクター作成）

対象ビルド: 2.0.211.56（ILSpy 逆コンパイル、`~/Dev/coq-decompiled_stable`）。
引用は、ソースルートからの相対パスと行番号（`path:line`）で示す。どれも本調査で `grep -n` / `sed -n` / `nl` を使って表示し、確かめた行である。

## 1. 目的

Modern UI を画面に出したまま、次の 3 点ができるかを静的に確かめる。

- (a) ゲームスレッドがどの画面で止まっているかを検出する。
- (b) その画面の中身を Legacy と同等のテキストとして読む。
- (c) ブリッジスレッドから `GameManager.Instance.uiQueue` を通して、UI スレッドで答える。

対象は、F1〜F4 が扱わない残りの画面である。原則として Harmony を使わない。Harmony が必要な箇所は、パッチ点を明示する。

## 2. 対象一覧

| # | 画面 | 入口 | ゲームスレッドの待ち方 |
|---|---|---|---|
| 1 | 取引 / コンテナ格納（Qud.UI.TradeScreen） | `TradeUI.ShowTradeScreen` | `TradeScreen.show(...).Result` |
| 1b | 取引の申し出の中のポップアップ | `TradeUI.PerformOffer`（スレッドプール） | プールのスレッドが `WaitNewPopupMessage` の `Task.Wait` で待つ |
| 2 | 本（Qud.UI.BookScreen） | `BookUI.ShowBookByID` / `ShowBook` | `BookScreen.show(...).Result` |
| 3 | 端末（Qud.UI.CyberneticsTerminalScreen） | `CyberneticsTerminal._ShowTerminal` / `GenericTerminal._ShowTerminal` | `Show*Terminal(this).Result` |
| 4 | ゲームの要約（Qud.UI.GameSummaryScreen） | `XRLCore.BuildScore` → `GameSummaryUI.Show` | `ShowGameSummary(...).Result` |
| 5 | 死亡メニュー / チェックポイントの再開 | `CheckpointingSystem.ShowDeathMessage` | Popup 系（F1 の PopupMessage） |
| 6 | Sifrah（Modern の窓はない） | `SifrahGame.Play` | ゲームスレッドの `Keyboard.getvk` |
| 7 | チュートリアルのポップアップとゲート | `TutorialManager.ShowCIDPopupAsync` | `PopupCompletion`（ゲームスレッドは同期では待たない） |
| 8 | 終局演出（暗転、クレジット、コーダ） | `EndGame.Start` | `Thread.Sleep` / `Task.Wait` / `ManualResetEvent.WaitOne`。入力は要らない |
| 9 | メインメニュー | `XRLCore._Start` | ゲームスレッドの `Keyboard.getvk` |
| 10 | セーブ選択（Qud.UI.SaveManagement） | 「Continue」 | `ContinueMenu().Wait()` |
| 11 | ロード時の mod 構成不一致の確認 | `XRLCore.RestoreModsLoadedAsync` | UI スレッドの async ポップアップ。ゲームスレッドは #10 の `.Wait()` の中にいる |
| 12 | キャラクター作成（EmbarkBuilder） | `XRLCore.NewGame` | `EmbarkBuilder.Begin().Result` |

## 3. 各画面の動作（待ち方・フィールド・コールバック）

### 3.0 共通の仕組み

- **`APIDispatch.RunAndWaitAsync`。** Modern 画面がゲーム側の処理を呼ぶときは、これを通る。処理を `Task.Run` でスレッドプールに投げ（`XRL.UI.Framework/APIDispatch.cs:16-19,54-56`）、その間は `NavigationController.SuspendContextWhile` で `activeContext` を `suspensionContext` にすり替える（`XRL.UI.Framework/NavigationController.cs:132-154`、フィールドは `:50`）。終わると `EnsureGameView(oldView)` でビューを戻す（`APIDispatch.cs:41,78`）。
  - したがって、`NavigationController.instance.activeContext == NavigationController.instance.suspensionContext` が真の間は、画面の裏でゲーム側の処理が走っている。これを「busy 信号」と呼ぶ。エンジン自身もこの比較を使っている（`Qud.UI/CyberneticsTerminalRow.cs:75`）。
  - busy の間は、画面そのものに答えない。入れ子のポップアップ（F1 の述語）を先に探す。
- **ポップアップの分岐。** `Popup.WaitNewPopupMessage` は、呼び出し元が UI スレッドかどうかだけで分岐する（`XRL.UI/Popup.cs:804`）。UI スレッド以外から呼ぶと、`uiQueue.awaitTask` で窓を出し、`complete.Task.Wait()` で待つ（`Popup.cs:822-908`）。スレッドプールから呼んでも、ゲームスレッドから呼んだときと同じ「同期ポップアップ」になる。
- **ビューの切り替え。** `GameManager.PushGameView` / `PopGameView` は `GameViewStack` をロックして `CurrentGameView` を書き換える（`GameManager.cs:1493-1540`）。

### 3.1 取引 / コンテナ格納（TradeScreen）

- **待ち方。** `TradeUI.ShowTradeScreen` は、Modern では `TradeScreen.show(Trader, costMultiple, screenMode).Result` でゲームスレッドを止める（`XRL.UI/TradeUI.cs:456-463`）。
  - 結果が REFRESH / NEXT / TOP なら内側のループを抜け、外側のループでもう一度開く。それ以外は return する。
  - 開く前に、ゲームスレッドは `TradeUI.Objects[0/1]` を `GetObjects` で埋めている（`TradeUI.cs:433-434`）。
- **`show` の中身。** `show` は `SuspendContextWhile(() => showScreen(...))` を返す（`Qud.UI/TradeScreen.cs:528-531`）。`showScreen`（`:433-492`）は最初の `await The.UiContext`（`:465`）までゲームスレッドで同期に走り、次のことをする。
  - 古い TCS をキャンセルし、新しい TCS を作る（`:440-441`）。
  - `ClearAndSetupTradeUI` を呼ぶ。
  - `MinEvent.UIHold = true` を立て、`PushGameView("ModernTrade")` する（`:461-462`）。

  その後は UI スレッドで `await menucomplete.Task`（`:483`）し、finally で `PopGameView(bHard:true)` する（`:489`）。
- **完了させる経路。** `menucomplete` を完了させるのは、次の二つだけである。
  - `Cancel()`（`TradeScreen.cs:874-880`）。CLOSE を立てる。
  - `HandleMenuOption(OFFER_TRADE)` の末尾（`:840-862`）。NEXT / REFRESH / TOP のときは途中で return するので、ここで立つのは CLOSE だけである。

  `PerformOffer` が返すのは NEXT / REFRESH / TOP だけである（`TradeUI.cs:1309,1317,1342,1351,1392,1397,1536`）。したがって、取引が成立しても画面は開いたまま残る。ゲームスレッドを返す唯一の出口は `Cancel()` である。
- **申し出。** `HandleMenuOption(OFFER_TRADE)` は次の順に進む。
  1. `UpdateTotals` と `CalculateTrade` で差額を出す。
  2. `APIDispatch.RunAndWaitAsync(() => TradeUI.PerformOffer(...))`（`TradeScreen.cs:845`）で決済を投げる。
  3. `PerformOffer` はスレッドプールで、`Popup.Show` / `Popup.ShowYesNo` を呼ぶ。
     - 水の不足や差額の確認: `TradeUI.cs:1305-1349,1388-1390`
     - 取引モードの "Trade complete!" / "Nothing to trade.": `:1521-1530`。Container モードでは出ない。
  4. これらは UI 以外のスレッドからの `WaitNewPopupMessage` なので、同期の PopupMessage になる（§3.0）。ゲームスレッドは `.Result` に止まったままで、実際にポップアップを待つのはプールのスレッドである。
  5. TOP / REFRESH なら、`ClearAndSetupTradeUI` と `UpdateViewFromData`（`:548`）で一覧を作り直す。
- **状態を読む場所。** 次のフィールドは `public` か static である。
  - `tradeEntries[0]`（相手）/ `[1]`（自分）: `TradeScreen.cs:53`。各要素は `TradeEntry`（`GO`、見出しなら `CategoryName`。`XRL.UI/TradeEntry.cs`）。
  - `NumberSelected`（static）: `:65`
  - `ObjectSide` / `ObjectIndex`: `:67-69`
  - `Totals` / `Weight`: `:49-51`
  - `Trader` / `CostMultiple`（static）: `:87-89`
  - `menucomplete` だけは `protected` である（`:30`）。
- **価格。** 行の価格は、`TradeLine` と同じく `TradeUI.GetValue(go, traderInventory)` を `0.00` 書式で出す（`Qud.UI/TradeLine.cs:473`）。
- **数量の設定。** `setHowManySelected(go, n)`（`TradeScreen.cs:275-295`）は、自分の側の重要品に `ConfirmUseImportantAsync` の確認ポップアップを出す。これは UI スレッドの async ポップアップである。
  - `NumberSelected[ObjectSide[go]][ObjectIndex[go]]` に直接書けば、この確認を飛ばせる。
  - ただし、人間なら出るはずの確認を飛ばすことになる（下記の方針を参照）。
- **入口の例。** 会話の Trade パーツ（`XRL.World.Conversations.Parts/Trade.cs:100`）。空のコンテナへの格納（`XRL.World.Parts/Container.cs:131-135`）。随行者との取引（`Container.cs:96-98`）。

### 3.2 本（BookScreen）

- **待ち方。** `BookUI.ShowBookByID` と `ShowBook` は、Modern では `BookScreen.show(...).Result` で止まる（`XRL.UI/BookUI.cs:425-431,462-468`）。
- **`showScreen` の中身。** `showScreen`（`Qud.UI/BookScreen.cs:185-245`）は次の順に進む。
  1. ゲームスレッドで `PushGameView("Book")`（`:195,226`）する。
  2. UI スレッドで `await menucomplete.Task`（`:205,236`）する。
  3. finally で `PopGameView(bHard:true)`（`:211,242`）する。
- **完了させる経路。** 完了は `Cancel()` だけである（`:368-374`）。
- **読む。** `RenderCurrentPage()` は public である（`:276-290`）。`Book` と `BookID` は public のフィールドである（`:54-56`）。`CurrentPage` と `PageCount` は private である（`:70,110-120`）。本文の全ページは、次から直接読める。
  - `BookUI.Books[BookID]`（`XRL.UI/BookUI.cs:29`）
  - `MarkovBook.Pages`（`XRL.World.Parts/MarkovBook.cs:32`）
  - 各ページの `BookPage.Lines` / `FullText`（`XRL.UI/BookPage.cs:20-34`）
- **注意。** ページのコールバック `onShowPage` / `afterShowPage` は、実際に表示したページについてだけ `APIDispatch` で走る（`BookScreen.cs:300-316`）。本を読んで何かを得る効果を Legacy と同じに起こすには、`HandleMenuOption(BookScreen.NEXT_PAGE)`（`:334-357`）でページをめくる。

### 3.3 端末（CyberneticsTerminalScreen）

- **待ち方。** `CyberneticsTerminal._ShowTerminal` と `GenericTerminal._ShowTerminal` は、Modern では `PushGameView("CyberneticsTerminalScreen")` の後に `.Result` で止まり、そのまま return する（`XRL.UI/CyberneticsTerminal.cs:196-203`、`XRL.UI/GenericTerminal.cs:76-84`）。この分岐には `PopGameView` がない。閉じた後もビューの名前が残るかどうかは、実機で確かめる。
- **`_ShowCyberneticsTerminal` の中身。** `_ShowCyberneticsTerminal`（`Qud.UI/CyberneticsTerminalScreen.cs:68-90`）と `_ShowGenericTerminal`（`:92-114`）は、次の順に進む。
  1. public の `completionSource`（`:24`）を作り直す。
  2. UI スレッドで `BeforeRender` を `APIDispatch` 経由で呼ぶ。
  3. `Show()` する。
  4. `await completionSource.Task` する。
- **完了させる経路。** 完了は次の二つである。
  - `Exit()`（`:121-124`）
  - 選んだ結果、`CurrentScreen` が null になったとき（`:279-337`）
- **選択。** `HandleSelect(element)` は、`element` が `CyberneticsTerminalLineData` で、しかも行の `CursorDone`（`row.cursorDone`。`Qud.UI/CyberneticsTerminalLineData.cs`）が真のときしか動かない（`:279-283`）。
  - 行は 15 ms に 1 字ずつタイプされる。行が動くのは、`initReady` が真で、suspension 中でないときだけである（`Qud.UI/CyberneticsTerminalRow.cs:73-115`）。
  - 最後の行が打ち終わると `HandleTextComplete`（`CyberneticsTerminalScreen.cs:206-217`）が走る。そこで画面が変わって `Show()` し直すことがある。
  - 入力があると、タイプを飛ばす（`CyberneticsTerminalRow.cs:79-89`）。ただしこれは `ControlManager.currentFrameCommands` を見ているので、mod からは使いにくい。
- **読む。**
  - 端末の実体は public static の `CyberneticsTerminal.Instance`（`XRL.UI/CyberneticsTerminal.cs:14`）と `GenericTerminal.instance`（`XRL.UI/GenericTerminal.cs:10`）で取れる。画面側のフィールドは private である（`CyberneticsTerminalScreen.cs:40-42`）。
  - 本文は `CurrentScreen.RenderedTextForModernUI`、選択肢は `CurrentScreen.Options` から読む（`XRL.UI/TerminalScreen.cs:15,25`、`XRL.UI/GenericTerminalScreen.cs:14,18`）。
  - 行データの並び（本文 1 行と選択肢）は `GetMenuItems`（`:219-251`）が作る。実際に結び付いたデータは `displayScroller.choices`（`XRL.UI.Framework/FrameworkScroller.cs:23`）に入っている。

### 3.4 ゲームの要約（GameSummaryScreen）

- **待ち方。** `RunGame` のループが死亡で終わると、`BuildScore()` が呼ばれる（`XRL.Core/XRLCore.cs:3031-3038`）。そこから `GameSummaryUI.Show` に進む（`:3345`）。
  - Modern では、`PushGameView("GameSummaryScreen")` の後に `ShowGameSummary(...).Result` で止まる（`XRL.UI/GameSummaryUI.cs:29-33`）。
  - bReal が偽の場合は、その後 Legacy の文字画面を 1 回描くだけで return する（`:34-40,94`）。
- **完了させる経路。** `_ShowGameSummary`（`Qud.UI/GameSummaryScreen.cs:65-141`）は `await completionSource.Task`（`:133`）で待つ。完了は `Exit()` だけである（`:143-146`）。
- **読む。**
  - `Name` と `Details`（public。`:40-42`）
  - `causeText.text`（`UITextSkin.text` は public。`XRL.UI/UITextSkin.cs:54`）

### 3.5 死亡メニュー / チェックポイントの再開

- **チェックポイントなし。** `CheckpointingSystem.ShowDeathMessage`（`XRL/CheckpointingSystem.cs:85-153`）は、`Popup.ShowSpace(..., PopupID:"DeathMessage")`（`:98,102`）を出して false を返す。`ShowSpace` は、Modern では `WaitNewPopupMessage` に進む同期ポップアップである（`XRL.UI/Popup.cs:1079-1095`）。
- **チェックポイントあり。** `Popup.PickOption` のループになる（`CheckpointingSystem.cs:114`）。
  - 選択肢の順は、オプション `OptionDefaultDeathToViewFinalMessages` で入れ替わる（`:113-114`）。**添字ではなく文字列で選ぶ**。
  - Retire は AskString で "RETIRE" を求める。
  - Quit は `forceNoDeath` を立てる（`:142-147`）。
  - Reload は `QueueRestore` → `LoadCommand.Issue` に進む（`:152,261-264`）。
- **チュートリアルのゲーム（JoppaWorldTutorial）。** 死亡メニューの前に、チュートリアルの幕間ポップアップが積まれる（`XRL.World/GameObject.cs:15047-15059`）。

どれも、特別な画面ではなく F1 のポップアップ系である。

### 3.6 Sifrah（Modern の窓なし）

- **待ち方。** `SifrahGame.Play`（`XRL/SifrahGame.cs:646-760`）は、ゲームスレッドの `Keyboard.getvk` ループである（`:671`）。`PushGameView("Sifrah")`（`:661`）で入り、`PopGameView()`（`:759`）で出る。
- **描画。** 描画は `scrapBuffer.Draw()`（`:343`）で行う。これは `DrawBuffer(this)` を `bSkipIfOverlay` なしで呼ぶ（`ConsoleLib.Console/ScreenBuffer.cs:180-184`）ので、Modern でも `TextConsole.CurrentBuffer` に盤面が書かれる（`ConsoleLib.Console/TextConsole.cs:142-159`）。`Qud.UI` には Sifrah を参照するファイルがない（grep で確認）。
- **入力。** getvk ループなので、`Keyboard.PushKey` / `PushMouseEvent` がそのまま効く。
  - `"Slot:i"`（`:716-721`）
  - `"Command:SifrahEnter"`（`:680`）
  - `"Command:SifrahSpace"`、または Z キー（`:684`。`Options.PrereleaseInputManager` は常に真で、`XRL.UI/Options.cs:741`）
  - Escape（`:701`）
  - 手を選ぶと `Popup.PickOption`（`:597`）が出る。これは F1 の系統である。
- **避け方。** `Options.Sifrah*` はどれも、`SifrahGame.Installed`（`GlobalConfig` の `EnableSifrah`。`Options.cs:1537`）と個別のオプションを条件にしている（`Options.cs:743-753,772-782` ほか）。呼び出し側はこれを確かめている（`XRL.World.Parts/Examiner.cs:438`、`XRL.World.Parts/Door.cs:483`）。オプションを No にしておけば入らない。

### 3.7 チュートリアル

- **有効かどうか。** `TutorialManager.IsActive` は `currentStep != null` である（`TutorialManager.cs:147`）。`StartTutorial` を呼ぶのは、ゲームモード "Tutorial" だけである（`XRL.CharacterBuilds.Qud/QudGamemodeModule.cs:90-97`）。`EndTutorial()` は public static で、`currentStep` を null にする（`TutorialManager.cs:381-384`）。
- **ゲート。** private の `ShowingPopup`（`:85`）が真の間は、次がすべて false を返し、入力が黙って捨てられる。
  - `AllowMouseEvent`（`:311-319`）
  - `AllowSelectedPopupCommand`（`:341-349`）
  - `AllowOnSelected`（`:351-359`）
  - `AllowPushKey`（`:361-369`）
  - `AllowCommand`（`:371-379`）

  `Keyboard.PushKey`（`ConsoleLib.Console/Keyboard.cs:777-782`）と `PushMouseEvent`（`:825-830`）も、この判定で入力を捨てる。
- **ポップアップの完了。** `ShowCIDPopupAsync` は private static の `PopupCompletion` を待つ（`:242-278`）。
  - public の `OnPopupAcceptPressed()`（`:764-767`）を呼ぶと、次の `Update` で `PopupCompletion.SetResult(true)` と `ShowingPopup=false` が立つ（`:769-790`）。
  - `instance` は private static（`:65`）なので、`FindObjectOfType<TutorialManager>()` かリフレクションで取る。

### 3.8 終局演出（EndGame）

- **待ち方。** `EndGame.Start(bool)`（`XRL.World.Conversations.Parts/EndGame.cs:282-293`）は、次の順に進む。
  1. `PushGameView("Cinematic")` する（`:286`）。
  2. `Thread.Sleep(11000)` する（`:288`）。
  3. `RunCredits` を呼ぶ。中身は `Task.Run(RunCreditsAsync).Wait()`（`:328`）で、`ev.WaitOne(145000)` と `Thread.Sleep(3000)`（`:415-416`）がある。
  4. `GoCoda` を呼ぶ。`PushGameView("Empty")`（`:468`）の後、`ev.WaitOne()` で**期限なく**待つ（`:495`）。UI スレッドの `FadeText` がコールバックを返すまで続く（`:576-590`）。その後はセーブ（`:515`）と 6 秒の描画ループ（`:519`）がある。
- **入力。** 入力は要らない。会話のパーツは、AskString の確認（`:162`）の後に `gameQueue.queueTask(Start)`（`:172`）を積む。
- **クレジットの早送り。** `EndgameCredits.Run` は、`runtime > scrollTime` になると `complete` を呼ぶ（`EndgameCredits.cs:103-128`）。`runtime`、`scrollTime`、`running`、`complete` は public である（`:16-28`）。
- **バックグラウンド実行。** `runInBackground` はクレジットの間だけ真にされ、終わると元に戻る（`EndGame.cs:344,419`）。

### 3.9 メインメニュー

- **待ち方。** `XRLCore._Start` のループは、ゲームスレッドの `Keyboard.getvk` で待つ（`XRL.Core/XRLCore.cs:3727-3729`）。このとき `pumpActions` は偽なので、`gameQueue` は実行されない（`ConsoleLib.Console/Keyboard.cs:1017-1040`）。
- **Modern のメニュー。** Modern の `MainMenu.SelectedInfo` も、`Keyboard.PushMouseEvent(command)` を積むだけである（`Qud.UI/MainMenu.cs:347`）。
- **分岐。**
  - "Pick:New Game" は `NewGame()` に進む（`XRLCore.cs:3773-3776`）。
  - "Pick:Continue" は、`flag`（セーブがある）のとき `SaveManagement.ContinueMenu().Wait()` に進む（`:3778-3796`）。

### 3.10 セーブ選択（SaveManagement）

- **待ち方。** `ContinueMenu`（`Qud.UI/SaveManagement.cs:137-173`）は、ループの頭で public の `completionSource` を作り直す。その後、UI スレッドで `Show()` し、`await completionSource.Task` で待つ。
  - `Show()` は `SavesAPI.GetSavedGameInfo()` を同期で待ってから、`savesScroller` を埋める（`:49-108`）。
- **答える。**
  - `SelectedInfo(SaveInfoData)`（`:129-135`）か `completionSource.TrySetResult(SaveGameInfo)` で選ぶ。
  - `Exit()`（`:175-179`）は null を返す。
  - `SaveInfoData.SaveGame` は public である（`XRL.UI.Framework/SaveInfoData.cs:7`）。
- **ロード。** ロードは `TryRestoreModsAndLoadAsync`（`Qud.API/SaveGameInfo.cs:51-64`）で行う。UI スレッドで mod を照合し、`Task.Run` で `XRLGame.LoadGame` を呼ぶ。

### 3.11 mod 構成不一致の確認

- **確認の流れ。** `RestoreModsLoadedAsync`（`XRL.Core/XRLCore.cs:3423-3467`）は、次の順に確認する。
  1. 見つからない mod があると、`Popup.NewPopupMessageAsync`（`DynamicPopupMessage`。`Popup.cs:751-781`）で Yes/No を聞く（`XRLCore.cs:3428`）。
  2. 構成が違うと、`PickOptionAsync` で聞く（`:3448`）。選択肢 0 は、mod の設定を書き換えて `GameManager.Restart()` を呼ぶ（`:3452-3462`）。**エージェントは 0 を選んではならない**。-1 は false を返し、セーブ一覧に戻る。
- **避け方。** セーブしたときと同じ mod 構成で起動すれば、この確認は出ない。

### 3.12 キャラクター作成（EmbarkBuilder）

- **待ち方。** `XRLCore.NewGame` は `EmbarkBuilder.Begin().Result` で止まる（`XRLCore.cs:2853`）。
  - `Begin`（`XRL.CharacterBuilds/EmbarkBuilder.cs:61-87`）は、UI スレッドから呼ぶと例外を投げる（`:64-66`）。
  - `CurrentGameView="EmbarkBuilder"` にした後、UI スレッドで `GameManager.Instance.gameObject` にコンポーネントを加え、static の `finishedEvent`（`:29`）を待つ。
- **完了させる経路。** 完了は `exitWithInfo` と `exitWithoutInfo` の二つである（`:263-316`）。
- **advance。** `advance`（`:206-225`）は、`checkStateAsync`（`:190-204`）でエラーや警告を出さない限り同期で進む。次の有効な窓がなければ `exitWithInfo` を呼ぶ。オーバーレイの Next は `advance(editableOnly:true)` である（`XRL.CharacterBuilds.UI/EmbarkBuilderOverlayWindow.cs:79-82`）。
- **プログラムで完了させる部品。** 次のメソッドはどれも public で、ビルドコードを読み込む機能もある（`EmbarkBuilder.cs:505-519`）。
  - `QudGamemodeModule.SelectMode(mode)`（`QudGamemodeModule.cs:83-141`）
  - `QudChartypeModule.selectType(type)`（`XRL.CharacterBuilds.Qud/QudChartypeModule.cs:68-143`）。Last / Random / Pregen を扱う。
  - `QudPregenModule.SelectPregen(name)`（`XRL.CharacterBuilds.Qud/QudPregenModule.cs:95-100`）。`advanceToSummary` まで進む。
  - `advanceToSummary`（`EmbarkBuilder.cs:167-180`）
- **ビルドコードの範囲。** ゲームモードはビルドコードに含まれない（`QudGamemodeModule.cs:69-72`）。

## 4. レシピ表

「UI:」は、`GameManager.Instance.uiQueue.queueTask` で UI スレッドに渡して実行する処理を表す。検出はブリッジから読むと競合するので、原則として UI スレッドのタスクの中で評価する。

| 画面 | 待ち方 | プローブの起動 | 検出 | 読む | 答える | 取り消す | Harmony |
|---|---|---|---|---|---|---|---|
| 取引 | ゲームスレッドの `.Result`（`TradeUI.cs:458`） | probe wish で Joppa の商人を `TradeUI.ShowTradeScreen(npc)` に渡す | UI: `TradeScreen.instance.isCurrentWindow()`、かつリフレクションで読む `menucomplete.Task` が未完了、かつ busy でない。補助に `CurrentGameView=="ModernTrade"` | `tradeEntries`、`NumberSelected`、`TradeUI.GetValue`、`Totals`、`CalculateTrade` | UI: 数量を設定し、`UpdateTotals()` と `UpdateViewFromData()` を呼んでから `HandleOfferTrade()`。入れ子のポップアップは F1 で答える | UI: `Cancel()` | 不要 |
| 取引の入れ子ポップアップ | プールのスレッドの `Task.Wait` | 上の申し出 | F1 の PopupMessage の述語。取引画面の述語より優先する | F1 | F1 | F1（Yes/No の No） | 不要 |
| 本 | `.Result`（`BookUI.cs:429,466`） | `BookUI.ShowBookByID(id)`。ID は実機で確かめる | UI: `BookScreen.instance.isCurrentWindow()`、かつ `menucomplete` が未完了。補助に view=="Book" | `BookUI.Books[BookID]` / `Book.Pages[*].Lines`、`RenderCurrentPage()` | UI: `HandleMenuOption(NEXT_PAGE)` を必要なだけ | UI: `Cancel()` | 不要 |
| 端末 | `.Result`（`CyberneticsTerminal.cs:201` / `GenericTerminal.cs:83`） | Grit Gate の端末、または `GenericTerminal.ShowTerminal` | UI: `instance.completionSource` があり未完了、かつ `isCurrentWindow()`、かつ `initReady`、かつ busy でない | `CyberneticsTerminal.Instance.CurrentScreen` の `RenderedTextForModernUI` と `Options`（Generic も同様） | UI: `displayScroller.choices` のすべての行で `CursorDone` になるまで待ち、`HandleSelect(choices[1+i])` | UI: `Exit()` | 不要 |
| 要約 | `.Result`（`GameSummaryUI.cs:32`） | `The.Core.BuildScore(Real:false)`。副作用がある | UI: `completionSource` があり未完了、かつ view=="GameSummaryScreen" | `Name`、`Details`、`causeText.text` | UI: `Exit()` | 同じ | 不要 |
| 死亡メニュー | F1 の同期ポップアップ | `CheckpointingSystem.ShowDeathMessage("You died.\n\nprobe")` を直接呼ぶ（Roleplay の場合） | F1。`PopupMessage.PopupID=="DeathMessage"` か、選択肢の文字列で判定する | F1 | F1。選択肢の文字列で選ぶ | F1 | 不要 |
| Sifrah | ゲームスレッドの getvk（`SifrahGame.cs:671`） | `new ExamineSifrah(...).Play(obj)` など | `CurrentGameView=="Sifrah"` | `TextConsole.CurrentBuffer`（80×25） | 任意のスレッドから `PushMouseEvent("Slot:i")` → F1 の PickOption → `PushMouseEvent("Command:SifrahSpace")` | `PushKey(Escape)` → F1 の Yes/No | 不要 |
| チュートリアルのポップアップ | UI 側の `PopupCompletion` | ゲームモード Tutorial | UI: リフレクションで `ShowingPopup` を読む | リフレクションで `PopupText` などを読む（未確認） | UI: `FindObjectOfType<TutorialManager>().OnPopupAcceptPressed()` | 同じ | 不要 |
| 終局演出 | Sleep / Wait / WaitOne | wish の `goend` / `gocredits` | view が "Cinematic" / "Empty"、または `EndgameCredits` が active | 入力は要らない | 待つか、UI: `credits.runtime = credits.scrollTime + 1` | なし | 不要 |
| メインメニュー | ゲームスレッドの getvk（`XRLCore.cs:3729`） | 起動直後 | `CurrentGameView=="MainMenu"`、かつ `Game==null` か `!Game.Running` | 固定のメニュー | 任意のスレッドから `PushMouseEvent("Pick:Continue" / "Pick:New Game")` | なし | 不要 |
| セーブ選択 | ゲームスレッドの `.Wait()`（`XRLCore.cs:3786`） | `Pick:Continue` | UI: view=="ModernSaveManagement"、かつ `completionSource` が未完了、かつ `savesScroller.choices` が空でない | `SavesAPI.GetSavedGameInfo()` の各 `SaveGameInfo`（`Name`、`Description`、`SaveTime`、`ModsEnabled`） | UI: `SelectedInfo(choice)`。TCS の参照が変わっていないことを確かめてから | UI: `Exit()` | 不要 |
| mod 不一致 | UI の async ポップアップ（ゲームスレッドは #10 の中） | 別の mod 構成で作ったセーブをロードする | F1 の `DynamicPopupMessage` の述語と、タイトル "Incomplete Mod Configuration" / "Mod Configuration Differs" | F1 | "Load keeping current mod configuration"（1）。0 は禁止 | -1（Escape） | 不要 |
| キャラクター作成 | ゲームスレッドの `.Result`（`XRLCore.cs:2853`） | `Pick:New Game` | UI: `GetComponent<EmbarkBuilder>()!=null`、かつ `finishedEvent` が未完了、かつ view=="EmbarkBuilder" | `activeWindow.viewID`。エージェントに読ませる必要はない | UI: `SelectMode("Roleplay")` → `selectType("Pregen")` → `SelectPregen(name)`、またはコードを読み込む → `advanceToViewId("Chargen/BuildSummary")` → `advance(editableOnly:true)`。途中で警告が出れば F1 で答える | UI: `back()` を最初の窓まで → `exitWithoutInfo` | 不要 |

## 5. 主張一覧

- **C-F5-other-blocking-01（high）。** Modern の取引では、ゲームスレッドが `TradeScreen.show(...).Result` で止まる（`XRL.UI/TradeUI.cs:456-463`）。`showScreen` は `await The.UiContext`（`Qud.UI/TradeScreen.cs:465`）まではゲームスレッドで走り、`PushGameView("ModernTrade")`（`:462`）を済ませてから、UI スレッドで `menucomplete.Task` を待つ（`:483`）。
- **C-F5-other-blocking-02（high）。** `TradeScreen.menucomplete` を完了させるのは、`Cancel()` の CLOSE（`TradeScreen.cs:874-880`）だけである。`HandleMenuOption(OFFER_TRADE)` は NEXT / REFRESH / TOP で途中の return をし（`:840-862`）、`PerformOffer` は CLOSE を返さない（`TradeUI.cs:1309,1317,1342,1351,1392,1397,1536`）。取引が成立しても画面は開いたまま残る。
- **C-F5-other-blocking-03（high）。** 申し出の中のポップアップ（差額の確認、"Trade complete!"）は、`APIDispatch.RunAndWaitAsync` の `Task.Run`（`TradeScreen.cs:845`、`APIDispatch.cs:16-19`）の中で呼ばれる。`WaitNewPopupMessage` は UI スレッド以外の分岐を通るので（`Popup.cs:804,822-908`）、同期の PopupMessage として F1 の手順で答えられる。Container モードでは "Trade complete!" は出ない（`TradeUI.cs:1521-1530`）。
- **C-F5-other-blocking-04（high）。** 取引の中身は、public のフィールドから読める。`tradeEntries`（`TradeScreen.cs:53`）、static の `NumberSelected`（`:65`）、`ObjectSide` / `ObjectIndex`（`:67-69`）、`Totals` / `Weight`（`:49-51`）である。価格は、Modern の行と同じ `TradeUI.GetValue(go, traderInventory)` の `0.00` 書式で出せる（`Qud.UI/TradeLine.cs:473`）。
- **C-F5-other-blocking-05（medium）。** Harmony なしで申し出を組める。UI スレッドで `setHowManySelected`（`TradeScreen.cs:275-295`）を呼ぶか、`NumberSelected` に直接書き、`UpdateTotals` / `UpdateViewFromData`（`:548`）の後に `HandleOfferTrade`（`:754-757`）を呼ぶ。ただし `setHowManySelected` は、自分の側の重要品に確認の async ポップアップを出す。直接書くと、その確認を飛ばす。
- **C-F5-other-blocking-06（high）。** `TradeScreen.menucomplete` と `BookScreen.menucomplete` は、フィールド初期化子で作られる（`TradeScreen.cs:30`、`BookScreen.cs:29`）。最初に表示するまでは完了しないので、「TCS が未完了」だけの述語は起動直後に誤検出する。`isCurrentWindow()`（`Qud.UI/WindowBase.cs:143-146`）かビュー名と組み合わせる。
- **C-F5-other-blocking-07（high）。** `APIDispatch` の処理が走っている間は、`NavigationController.activeContext` が `suspensionContext` になる（`NavigationController.cs:132-154`）。エンジン自身も、この比較で行の更新を止めている（`CyberneticsTerminalRow.cs:75`）。これが busy 信号になる。
- **C-F5-other-blocking-08（high）。** 本は `BookScreen.show(...).Result` で止まり（`BookUI.cs:429,466`）、完了は `Cancel()` だけである（`BookScreen.cs:368-374`）。全ページの本文は `BookUI.Books[BookID]` か `MarkovBook.Pages` から読める（`BookUI.cs:29`、`MarkovBook.cs:32`、`BookPage.cs:20-34`）。ページのコールバックは、表示したページにしか走らない（`BookScreen.cs:300-316,334-357`）。
- **C-F5-other-blocking-09（high）。** Modern の端末は `PushGameView("CyberneticsTerminalScreen")` の後に `.Result` で止まり、`PopGameView` を呼ばずに return する（`CyberneticsTerminal.cs:196-203`、`GenericTerminal.cs:76-84`）。完了させるのは、`Exit()`（`CyberneticsTerminalScreen.cs:121-124`）か、`CurrentScreen` が null になったとき（`:279-337`）だけである。
- **C-F5-other-blocking-10（high）。** 端末の `HandleSelect` は、行の `cursorDone` が真の要素しか受け付けない（`CyberneticsTerminalScreen.cs:279-283`）。行は `initReady` で、しかも suspension 中でないときにだけタイプされる（`CyberneticsTerminalRow.cs:73-115`）。答えるには、`displayScroller.choices`（`FrameworkScroller.cs:23`）の、表示中の行データを渡す必要がある。
- **C-F5-other-blocking-11（high）。** 端末の本文と選択肢は、public static の `CyberneticsTerminal.Instance` / `GenericTerminal.instance`（`CyberneticsTerminal.cs:14`、`GenericTerminal.cs:10`）の `CurrentScreen.RenderedTextForModernUI` と `Options` から読める（`TerminalScreen.cs:15,25`、`GenericTerminalScreen.cs:14,18`）。画面側のフィールドは private である（`CyberneticsTerminalScreen.cs:40-42`）。
- **C-F5-other-blocking-12（high）。** 要約画面は `ShowGameSummary(...).Result` で止まる（`GameSummaryUI.cs:29-33`）。完了は `Exit()` だけで（`GameSummaryScreen.cs:143-146`）、`Name` と `Details`（`:40-42`）は public である。
- **C-F5-other-blocking-13（high）。** 死亡メニューは専用の画面ではない。チェックポイントなしなら `ShowSpace(PopupID:"DeathMessage")`、ありなら `PickOption` のループで（`CheckpointingSystem.cs:98,102,114`）、どちらも F1 の同期ポップアップである。選択肢の順はオプションで入れ替わるので（`:113-114`）、文字列で選ぶ。
- **C-F5-other-blocking-14（high）。** Sifrah には Modern の窓がない。ゲームスレッドの getvk ループで（`SifrahGame.cs:646-760,671`）、`bSkipIfOverlay` なしで `CurrentBuffer` に描く（`SifrahGame.cs:343`、`ScreenBuffer.cs:180-184`、`TextConsole.cs:142-159`）。したがって、`PushMouseEvent("Slot:i")` / `"Command:SifrahSpace"` と `CurrentBuffer` の読み取りで扱える。
- **C-F5-other-blocking-15（medium）。** Sifrah の入口は、確かめたもの（Examine、Hacking）がどれも `Options.Sifrah*` を条件にしている。それらは `SifrahGame.Installed` を前提にする（`Options.cs:743-753,1537`、`Examiner.cs:438`、`Door.cs:483`）。オプションを No にすれば、エージェントは Sifrah に入らない。
- **C-F5-other-blocking-16（high）。** チュートリアルのポップアップが出ている間（`ShowingPopup`）は、`Keyboard.PushKey` と `PushMouseEvent` が入力を捨てる（`Keyboard.cs:777-782,825-830`、`TutorialManager.cs:311-319,361-369`）。PopupMessage の選択とスクローラの選択も拒まれる（`TutorialManager.cs:341-359`）。先にチュートリアルのポップアップを閉じないと、ほかのどの答え方も無言で失敗する。
- **C-F5-other-blocking-17（medium）。** チュートリアルのポップアップは、Harmony なしで閉じられる。UI スレッドで public の `OnPopupAcceptPressed()` を呼ぶと、次の `Update` が `PopupCompletion` を完了させる（`TutorialManager.cs:764-790`）。チュートリアルを始めるのはゲームモード "Tutorial" だけで（`QudGamemodeModule.cs:90-97`）、`EndTutorial()` で止められる（`TutorialManager.cs:381-384`）。
- **C-F5-other-blocking-18（high）。** 終局演出は入力を求めず、ゲームスレッドを次の順に止める。
  1. 11 秒（`EndGame.cs:288`）
  2. クレジット。最大 145 秒と 3 秒（`:328,415-416`）
  3. コーダの期限なしの `WaitOne`（`:495`）
  4. 6 秒の描画ループ（`:519`）

  コーダの待ちは、UI スレッドの `FadeText` の完了に依存する。
- **C-F5-other-blocking-19（medium）。** クレジットは、UI スレッドで `EndgameCredits.runtime` を `scrollTime` より大きくすれば、次の `Run` で `complete` が呼ばれて終わる（`EndgameCredits.cs:16-28,103-128`）。Harmony は要らない。
- **C-F5-other-blocking-20（high）。** メインメニューでは、ゲームスレッドが `Keyboard.getvk` で待つ（`XRLCore.cs:3729`）。Modern のメニュー自身も `PushMouseEvent` を積むだけなので（`MainMenu.cs:347`）、mod は任意のスレッドから `Keyboard.PushMouseEvent("Pick:Continue")` か `"Pick:New Game"` を積めば、人のクリックなしに進められる（`XRLCore.cs:3773-3786`）。`gameQueue` はここでは実行されない（`Keyboard.cs:1017-1040`）。
- **C-F5-other-blocking-21（high）。** セーブ選択は `ContinueMenu().Wait()` で止まる（`XRLCore.cs:3786`）。UI スレッドで `SelectedInfo(SaveInfoData)` か `completionSource.TrySetResult(SaveGameInfo)` を呼べばロードが始まり（`SaveManagement.cs:129-135,137-165`）、`Exit()` で戻る（`:175-179`）。
- **C-F5-other-blocking-22（high）。** mod 構成不一致の `PickOptionAsync` で選択肢 0 を選ぶと、`GameManager.Restart()` でプロセスが再起動する（`XRLCore.cs:3448-3462`）。エージェントは 1 か -1 しか選んではならない。
- **C-F5-other-blocking-23（medium）。** キャラクター作成は、`EmbarkBuilder.Begin().Result` で止まる（`XRLCore.cs:2853`）。UI スレッドで公開 API をつなげば、人の操作なしに完了できる見込みが高い。
  - 使う API: `SelectMode`、`selectType`、`SelectPregen`、`InitModulesFromCode`、`advanceToSummary`、`advance`（`QudGamemodeModule.cs:83-141`、`QudChartypeModule.cs:68-143`、`QudPregenModule.cs:95-100`、`EmbarkBuilder.cs:167-225,505-519`）
  - `advance` は、`checkStateAsync` が警告ポップアップを出すと非同期で止まる（`EmbarkBuilder.cs:190-225`）。
  - ゲームモードはビルドコードに含まれない（`QudGamemodeModule.cs:69-72`）。
- **C-F5-other-blocking-24（high）。** 範囲内のどの画面も、検出、読み取り、回答に Harmony を必要としない。private / protected のフィールド（`menucomplete`、端末の実体の参照、`TutorialManager.instance` / `ShowingPopup`）はリフレクションで読むだけでよい。

## 6. 実機でしか分からないこと

1. 端末を閉じた後、`CurrentGameView` に "CyberneticsTerminalScreen" が残るか（Modern の分岐に Pop がない）。
2. Sifrah の盤面（Legacy の文字画面）が、Modern の画面に実際に映るか。映る場合、録画でどう見えるか。
3. `BookUI.Books` に "Sifrah" のような ID が、probe の対象として存在するか。
4. `advance(editableOnly:true)` を BuildSummary から呼ぶと `exitWithInfo` に達するか（BuildSummary が最後の編集可能な窓か）。起動後にポップアップ（導入文など）が出るか。
5. プリセットの名前（`QudPregenModule.pregens` のキー）と、スタート地点が Joppa になるか（Random / Daily はスタート地点を乱択する）。
6. `EndgameCredits.runtime` を書き換えて早送りしたとき、音楽とフェードが破綻しないか。
7. `GoCoda` の `WaitOne` が、非フォーカス時に（`runInBackground` が元に戻った後に）完了するか（05 の C06 と関係する）。
8. `TutorialManager.OnPopupAcceptPressed` が、コンポーネントが非表示（`ToggleHide`）のときにも効くか。
9. `TradeScreen.HandleOfferTrade` を UI スレッドで直接呼んだとき、`NavigationController` の状態（オーバーレイや検索欄）が邪魔をしないか。

## 7. 未解決の問い

1. 取引で、重要品の確認（`ConfirmUseImportantAsync`）を、エージェントに見せるべきか、方針として飛ばすべきか。
2. コーダの後に続けて遊ぶか、`GameSummaryScreen` までで 1 本と数えるか。
3. `BuildScore(Real:false)` を probe に使うとき、副作用（`currentWindow=null`、`StaticEffecting`。`GameSummaryUI.cs:38-39`）を許すか。
4. チュートリアルのポップアップの本文（`PopupText`）の保持場所。本調査では、フィールドの宣言を確かめていない。
5. `Command:SifrahSpace` をエンジン自身がどこで生成しているか（`PushMouseEvent` で届くことは getvk の分岐から分かる。ほかの経路は未確認）。
