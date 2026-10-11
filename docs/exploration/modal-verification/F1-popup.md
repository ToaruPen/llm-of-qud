# F1-popup: PopupMessage 系モーダルの静的検証

対象ビルド: 2.0.211.56（ILSpy 逆コンパイル、`~/Dev/coq-decompiled_stable`）。
引用はすべてソースルートからの `path:line`。本書の作業中に `sed -n` / `grep -n` で表示した行だけを引く。

## 1. 目的

Modern UI を画面に残したまま、`XRL.UI.Popup` 経由でゲームスレッドを止めるモーダルについて、次の三つが Harmony なしで成り立つかを静的に確かめる。

- (a) 検出: ゲームスレッドがどのモーダルで止まっているかを知る。
- (b) 読み取り: そのモーダルの内容を Legacy 相当のテキストにする。
- (c) 応答: ゲームスレッド以外（ブリッジスレッド → `uiQueue` → UI スレッド）から答えて、ゲームスレッドの待ちを正しく解く。

結論を先に書く。F1 の範囲では、三つとも Harmony なしで組める。ただし次の四点を守ることが条件になる。

1. 検出と読み取りは UI スレッドで行い、ブリッジにはスナップショットを渡す。
2. 答えるときは、コントローラーが持っている実物の項目を渡す。
3. `Hide()` を先に呼ばない。
4. `onHide` の参照をトークンにして、同じポップアップに二度答えない。

静的に決まらないのは、プレハブでの UnityEvent の配線と、Unity API をスレッド外から触ったときの挙動である。これらは実機プローブで確かめる（§6）。

## 2. 対象一覧（Popup.cs の公開入口）

Modern 時（`UIManager.UseNewPopups => Options.ModernUI`、`Qud.UI/UIManager.cs:55`）の経路は、次の 2 本に集約される。

- **同期経路 S**: `Popup.WaitNewPopupMessage`（`XRL.UI/Popup.cs:801-921`）。単体ウィンドウ `"PopupMessage"` を `UIManager.getWindow` で取る（`:826`）。
- **非同期経路 A**: `Popup.NewPopupMessageAsync`（`XRL.UI/Popup.cs:751-799`）。複製 `"PopupMessage #N"` を `UIManager.copyWindow` で作る（`:760`）。

`ShowPopup(` を呼ぶのはこの 2 か所だけである。`grep` で見つかる他の `ShowPopup` は、Battlehub と `Screens.ShowPopup` という別物だった。

| 入口 | 定義 | Modern 時の経路 | 窓 | ボタン（`bottomContextOptions`） | 本文の選択肢（`menuData`） |
|---|---|---|---|---|---|
| `Show` | `Popup.cs:658-671` | `ShowBlock` → S | 単体 | `SingleButton`（`"Accept"`、hotkey `"Accept,Cancel"`） | なし |
| `ShowFail` | `:629-632` | `Show` → S | 単体 | 同上 | なし |
| `ShowBlock` | `:1118-1142` | S（`:1138-1142`） | 単体 | 同上。`buttons ?? SingleButton`（`:833`） | なし |
| `ShowBlockPrompt` | `:947-971` | S（`:968-971`。Prompt は title に入る） | 単体 | 同上 | なし |
| `ShowBlockSpace` | `:1015-1042` | S（`:1038-1041`） | 単体 | 同上 | なし |
| `ShowSpace`（死亡メッセージを含む） | `:1079-1096` | S（`:1092-1095`。Title は contextTitle に入る） | 単体 | 同上 | なし |
| `ShowBlockWithCopy` | `:673-739` | S（`:676-691`） | 単体 | `CopyButton`（Copy / Cancel） | なし |
| `ShowYesNo`、`WarnYesNo` | `:2251-2276`、`:2246-2249` | S（`:2258-2276`） | 単体 | `YesNoButton`（Yes / No） | なし |
| `ShowYesNoCancel`、`WarnYesNoCancel` | `:2365-2388`、`:2360-2363` | S（`:2371-2388`） | 単体 | `YesNoCancelButton` | なし |
| `DisplayLoadError` | `:2476-` | `ShowYesNoCancel`（`:2509`） | 単体 | 同上 | なし |
| `PickOption`、`ShowOptionList` | `:1650-1760`、`:1645-1648` | S（`:1709-1760`） | 単体 | `Buttons` と、`AllowEscape` なら `CancelButton`（`:1727-1735`） | `GetPopupOption` で作る `"option:N"`（`:1711-1715`、`:2011-2044`） |
| `PickOptionAsync`、`ShowOptionListAsync` | `:1624-1643`、`:1618-1622` | `PickOption(ForceNewPopup:true)` → S | 単体 | 同上 | 同上 |
| `Popup.PickGameObject` | `:1520-1558` | `PickOption` → S | 単体 | 同上 | 同上 |
| `PickSeveral` | `:2046-2138` | `PickOption` を繰り返す → S | 単体 | `"option:-2"`（Accept）、`"option:-3"`（全選択） | 同上 |
| `ShowColorPicker`、`ShowColorPickerAsync` | `:2222-2232`、`:2234-2244` | `PickOption` / `PickOptionAsync` → S | 単体 | 同上 | 同上 |
| `ShowConversation`（F2 の範囲。参考として） | `:1571-1616` | S（`:1594`。`AllowRenderMapBehind`） | 単体 | Look / trade / Cancel | `"option:N"` |
| `AskString` | `:1433-1443` | `AskStringAsync(...).Result`（`:1442`）→ A | 複製 | `SubmitCancel(Color)Button`。`WantsSpecificPrompt` があり PC なら `SubmitCancelHoldButton`（`:1374-1385`） | なし（入力欄あり） |
| `AskStringAsync` | `:1371-1431` | A（`:1396`） | 複製 | 同上 | なし |
| `AskNumber`（キーボード） | `:1191-1205` | `AskNumberAsync(...).Result`（`:1200`）→ A（`:1341-1349`） | 複製 | `SubmitCancelButton` | なし（入力欄あり） |
| `AskNumber`（ゲームパッド） | 同上 | `AskNumberScreen.show`（`:1323-1331`） | `AskNumberScreen` | 独自 | — |
| `ShowAsync`、`ShowFailAsync` | `:639-656`、`:624-627` | A（`:648-650`） | 複製 | `SingleButton` | なし |
| `ShowYesNoAsync`、`ShowYesNoCancelAsync` | `:2326-2339`、`:2341-2358` | A | 複製 | YesNo / YesNoCancel | なし |
| `ShowKeybindAsync` | `:634-637` | A（`AnyKey` と cancelToken） | 複製 | 空 | 空 |
| `ShowProgress` / `ShowProgressAsync` | `:741-749` | モーダル入力ではない | — | — | — |

ゲーム本体が `NewPopupMessageAsync(...).Result` を直に使う箇所もある。アイテムの説明を見る `Description.cs:361`（`InventoryActionEvent` の処理 `:333-`）がそれで、経路は A になる。

`ShowChoice` という公開メソッドは、このビルドには存在しない（`grep -rn "ShowChoice"` で 0 件）。

## 3. 各モーダルの動作

### 3.1 同期経路 S: `WaitNewPopupMessage`

- **UI スレッドから呼んだ場合**は、A に委ねて即座に戻る（`Popup.cs:804-821`）。`async void` なので、呼び出し側は結果を待たない。ゲームスレッドの経路ではないので、以下では扱わない。
- **ゲームスレッドからの場合**（`ThreadPool` スレッドの場合も同じ）:
  1. `uiQueue.awaitTask` で UI スレッドにタスクを積み、`ManualResetEvent` で実行完了まで待つ（`Popup.cs:824-895`、`QupKit/ThreadTaskQueue.cs:135-155`）。
  2. UI タスクの中で、`getWindow("PopupMessage")`（`:826`）、`PushGameView("PopupMessage")`（`:829`）、`ShowPopup(...)`（`:884`）の順に実行する。
  3. ゲームスレッドは `complete.Task.Wait()` で待つ（`:908`）。`AllowRenderMapBehind` のときは `Wait(33)` のループになる（`:896-905`）。
  4. 解けたら `PopGameView`（`:910`）を実行し、`callback(complete.Task.Result)` を呼ぶ（`:911-914`）。
- **コールバックの中身**:
  - `commandCallback`（`:834-852`）: 入力欄があれば `ToCP437(inputBox.text)` を text に入れる。さらに `EscapeNonMarkupFormatting` が真なら `i.text.Replace(...)` を呼ぶ（`:842-845`）。そのうえで `complete.SetResult(i)` を呼ぶ。text が null なら NRE になり、`TrySetException`（`:848-851`）に落ちる。
  - `selectedItemCallback`（`:854-868`）: `Replace` を呼ばずに `SetResult` する。
  - `onHide`（`:873-877`）: `complete.TrySetCanceled()` を呼ぶ。
- **`SetResult` は Try 版ではない。** 二度目は例外になるが、catch の中の `TrySetException` は完了済みの Task に対して何もしない（`:846-851`）。

**キャンセル時の実害（新規の指摘）。** `WaitNewPopupMessage` は `public static async void` である（`Popup.cs:801`）。そのため、`Hide()` → `onHide` → `TrySetCanceled` の順でキャンセルが立ち、`Task.Wait()`（`:908`）が例外を投げても、その例外は呼び出し元に伝わらない。C# の async void では、例外は捕まえられたときの `SynchronizationContext` に Post され、呼び出し元には正常に戻る。ゲームスレッドの `SynchronizationContext` は素の `SynchronizationContext` なので（`XRL.Core/XRLCore.cs:3557-3559`）、例外は ThreadPool 側で再送出される。起きることは次のとおり。

- `:910` の `PopGameView` は実行されない。ビュースタックに `"PopupMessage"` が残る。
- callback は呼ばれず、呼び出し元は既定値を返す。
  - `PickOption` は `SelectedOption = DefaultSelected` で初期化されている（`:1664`）ので、既定の選択肢（通常は 0）を返す（`:1759-1760`）。死亡メニューなら「Reload from checkpoint」を選んだことになる（`XRL/CheckpointingSystem.cs:114-118`）。
  - `ShowYesNo` と `ShowYesNoCancel` は `defaultResult` を返す（`:2257,2276`、`:2370,2388`）。

05 の C02 第 5 条件「`Task.Wait` が例外になる」は、正確には「例外は呼び出し元に届かず、黙って既定値の答えになる」と言い直すべきである。ThreadPool 上の未処理例外を Unity の Mono がどう扱うか（ログだけか、落ちるか）は実機で確かめる。

### 3.2 非同期経路 A: `NewPopupMessageAsync`

呼び出しスレッド（ゲームスレッド）の上では、次の順に進む。

1. `PushGameView("DynamicPopupMessage")`（`Popup.cs:755`）と `ControlManager.ResetInput()`（`:756`）を実行する。
2. `NavigationController.SuspendContextWhile` に入る。`activeContext` の切り替えは呼び出しスレッドの上で起きる（`XRL.UI.Framework/NavigationController.cs:156-178`）。
3. `await The.UiContext`（`Popup.cs:759`）で UI スレッドへ移る。この awaiter は `IsCompleted => _context == SynchronizationContext.Current` で、そうでなければ `_context.Post` する（`XRL/SynchronizationContextAwaiter.cs:7-26`）。`The.UiContext` の実体は `GameManager.uiSynchronizationContext` で（`XRL/The.cs:41`）、UI スレッドで捕まえたものである（`GameManager.cs:868-869`）。

UI スレッドの上では、次の順に進む。

1. `copyWindow("PopupMessage")` で複製を取る（`Popup.cs:760`）。プールにあれば再利用して `SetActive(true)` する。なければ `Instantiate` して `"PopupMessage #N"` の名前で `windowsByName` に登録する（`Qud.UI/UIManager.cs:323-342`）。
2. `ShowPopup` に二つの callback を渡す。どちらも「`messageWindow.onHide` を `t.TrySetResult(item)` に差し替える」だけである（`Popup.cs:764-775`）。元の `onHide` は `t.TrySetCanceled()` である（`:776-778`）。
3. `await t.Task`（`:781`）の後、入力欄つきか `CmdOptions` なら、`result.text` を `ToCP437(inputBox.text)` にし、`&` と `^` を二重にする（`:782-789`）。
4. finally で `releaseCopy` と `PopGameView` を実行する（`:793-797`）。`releaseCopy` は複製を `SetActive(false)` にしてプールに戻す（`UIManager.cs:344-354`）。

呼び出し側の待ち方は次のとおり。

- `AskString` は `AskStringAsync(...).Result`（`Popup.cs:1442`）、`AskNumber` は `AskNumberAsync(...).Result`（`:1200`）でゲームスレッドを止める。
- `.Result` でもデッドロックしない。ゲームスレッドのコンテキストは素のもので（`XRLCore.cs:3557-3559`）、`AskStringAsync` の継続は ThreadPool で走るからである。
- `AskStringAsync` と `AskNumberAsync` は例外をすべて握って `null` を返す（`:1418-1422`、`:1356-1360`）。キャンセルが立つと `AskString` は `null` を返す。`EndGame.cs:162` のように `null.ToUpper()` を呼ぶ呼び出し元は、ゲームスレッドで NRE になる。`CheckpointingSystem.cs:136` は null を検査している。
- `AskStringAsync` は `command == "Color"` なら色選択に回ってループする（`Popup.cs:1394-1411`）。色選択の `ShowColorPickerAsync` → `PickOptionAsync` → `PickOption` は ThreadPool スレッドの上で S を通る。その間、ゲームスレッドは `.Result` で止まったままである。

### 3.3 窓クラス `Qud.UI.PopupMessage`

**状態を持つフィールド**（すべて public）:

| フィールド | 行 | 意味 |
|---|---|---|
| `Message` | `Qud.UI/PopupMessage.cs:20` | 本文。`UITextSkin`。`SetText("{{y|" + message + "}}")`（`:777`）。`UITextSkin.text` は public な string フィールド（`XRL.UI/UITextSkin.cs:54`） |
| `Title` | `:42` | `"{{W|" + title + "}}"`。title がなければ `""`（`:797-806`） |
| `contextText` | `:34` | contextTitle（`:853-856`）。`ShowSpace` の Title はここに入る |
| `commandCallback`、`selectCallback` | `:22`、`:24` | `ShowPopup` で設定する（`:779-780`） |
| `controller` | `:26` | `QudTextMenuController`。`menuData`＝本文の選択肢、`bottomContextOptions`＝下段のボタン（`:781-782`、`Qud.UI/QudBaseMenuController.cs:50,65`） |
| `inputBox` | `:28` | 入力欄。`includeInput` のときだけ `SetActive(true)`。`text = inputDefault`、`onSubmit` に `OnInputSubmit` を登録（`:807-817`） |
| `onHide` | `:231` | `ShowPopup` で設定（`:773`）。`Hide()` で取り出して null にしてから呼ぶ（`:1098-1103`） |
| `cancellationToken` | `:233` | A の cancelToken 用（`:772`、`:985-991`） |
| `WantsSpecificPrompt`、`RestrictChars` | `:237`、`:239` | 確認語と、許す文字（`:783-784`） |
| `PopupID` | `:247` | 呼び出し側が与える ID（`"DeathMessage"` など）。`:771` |
| `static lastPopupID` | `:249` | 最後に開いた ID。`:874` で設定され、消されない |
| `HideNextFrame`（private） | `:253` | `Hide` で 2 にし、2 フレーム後に `SetActive(false)`（`:970-983`） |

**待ちを解くメソッド**（UI スレッドで呼ぶ）:

- `OnActivateCommand(item)`（`:926-934`）: チュートリアルのゲートを通り、`command != "CmdOptions"` で、`commandCallback != null` のときだけ、`commandCallback(item)`、`commandCallback = null`、`Hide()` の順に実行する。
- `OnSelect(item)`（`:936-944`）: ゲートを通り、`selectCallback != null` のとき、`selectCallback(item)`、`selectCallback = null`、`Hide()` の順に実行する。
- `OnInputSubmit(value)`（`:946-958`）: `bottomContextOptions` の中で、hotkey が `"Submit"` / `"Accept"` / `"CmdOptions"` の最初の項目に `OnSelect` を呼ぶ。`WaitForKeyup` はリストに足すだけで、ブロックしない（`ControlManager.cs:704-713`）。
- `BackgroundClicked()`（`:1067-1074`）: `bottomContextController.items` から Cancel か `"Accept,Cancel"` の項目を選び、`OnActivateCommand` に渡す。
- `Hide()`（`:1083-1104`）: 単独で呼ぶとキャンセルになる（§3.1、§3.2）。

**エンジン自身が `commandCallback` を呼ぶ経路**（`Update`、`:968-1065`）:

- cancelToken が立ったとき: `commandCallback(default)`（`:985-991`）。
- ボタンも選択肢もない `AnyKey` ポップアップで任意のキーが押されたとき: `commandCallback(default)`（`:1040-1045`）。
- 本文の選択肢の `char:` ホットキーが押されたとき: `commandCallback(menuDatum)`、`commandCallback = null`、`Hide()`（`:1046-1062`）。本文の選択肢に `OnActivateCommand` を使うのは、この経路と同じ効果になる。
- `WantsSpecificPrompt` の長押しが 2 秒に達したとき: `inputBox.text = WantsSpecificPrompt` の後に `OnInputSubmit`（`:1024-1030`）。

**チュートリアルのゲート**: `TutorialManager.AllowSelectedPopupCommand` は、`ShowingPopup` 中なら false、それ以外は `currentStep?.AllowSelectedPopupCommand(...) ?? true` を返す（`TutorialManager.cs:341-349`）。チュートリアルの外では常に true になる。

**UnityEvent の配線は見えない。** 本文の選択肢とボタンは `QudBaseMenuController` の `activateHandlers`、`activateContextHandlers`、`selectHandlers`、`cancelHandlers` を通る（`QudBaseMenuController.cs:73-79,438-465`）。`PopupMessage` のどのメソッドにつながるかは、プレハブ（シリアライズ済みの UnityEvent）で決まり、ソースには現れない。本書の手順は、この配線を通らずに `PopupMessage` のメソッドを直接呼ぶので、配線に依存しない。

`selectHandlers` はハイライト（`selectedOption` の setter）でも呼ばれる（`:111-114`、`:153-172`）。もし `OnSelect` につながっていれば、ハイライトしただけで確定してしまう。人間の操作ではそうならないので、つながっていないと推定できるが、実機で確かめる。

### 3.4 AskNumberScreen（ゲームパッド時の AskNumber）

- `AskNumberAsync` は、`ControlManager.activeControllerType != Keyboard` のときだけ `AskNumberScreen.show` を使う（`Popup.cs:1323-1340`）。このとき `PushGameView("ModernPopupGamepadAskNumber")`（`:1327`）を積む。
- `activeControllerType` は、Deck か Controller のプラットフォームなら Gamepad を返し、それ以外は `_activeControllerType` を返す（`ControlManager.cs:611-622`）。
- `showScreen` の流れ: `await The.UiContext` → `Current/Min/Max` を設定 → `messageText.SetText(Message)` → `menucomplete` を作り直す → `Show()` → `await menucomplete.Task`（`Qud.UI/AskNumberScreen.cs:117-141`）。`menucomplete` は protected なので、外からは見えない（`:19`）。
- 確定と取り消し:
  - `Accept()` は `Convert.ToInt32(numberText.text)` を読み、`Hide()` の後に `TrySetResult(value)` を呼ぶ（`:213-220`）。
  - `Cancel()` は `TrySetResult(null)` を呼ぶ（`:222-228`）。
  - どちらも public である。`UpdateViewFromData` は private（`:159-170`）。
  - `Accept` は値を丸めないが、同期の `AskNumber` が `Min` と `Max` で丸める（`Popup.cs:1200-1205`）。
- インスタンスは `SingletonWindowBase<AskNumberScreen>.instance`（`Qud.UI/SingletonWindowBase.cs:5-24`）。`Current`、`Min`、`Max`、`messageText`、`numberText` は public（`AskNumberScreen.cs:25-33`）。

### 3.5 死亡メニューと終局の確認（具体例）

- **死亡**: `The.Player.Die`（wish `"die"`、`XRL.World.Capabilities/Wishing.cs:225-229`）から `CheckpointingSystem.ShowDeathMessage` が呼ばれる（`XRL.World/GameObject.cs:15059`）。
  - チェックポイントが無効なら、`ShowSpace(..., PopupID "DeathMessage")` を S で 1 枚出して終わる（`XRL/CheckpointingSystem.cs:87-104`）。
  - 有効なら（wish `CheckpointOn`、`:179-185`）、`while (true)` の中で `PickOption("", message+"\n", ..., 4 択)` を出す（`:111-114`）。ボタンはなく、`AllowEscape` も既定の false である。したがって `bottomContextOptions` は空で、`menuData` は `"option:0..3"` の 4 項目になる。`PopupID` は null。
  - 選択肢の並びは `OptionDefaultDeathToViewFinalMessages` で入れ替わる（`:113-114`）。`"option:N"` の N は、並べ替えた後の添字である。
  - 2 番（Retire）は `AskString(..., Default "", WantsSpecificPrompt "RETIRE", MaxLength 7)`（`:126-141`）を出す。答えが `"RETIRE"` でなければ switch を抜けて、ループの先頭に戻る。
- **終局**: `EndGame.HandleEvent(EnterElementEvent)` は、PC では `Default ""` と `WantsSpecificPrompt = text` で `AskString` を呼ぶ（`XRL.World.Conversations.Parts/EndGame.cs:148-175`）。`ToUpper() == text` なら `gameQueue.queueTask(Start)` を積む。
  - PC ではボタンが `SubmitCancelHoldButton` になる。Submit（command `"keep"`、hotkey `"Submit"`）、Cancel、Hold（`"CmdOptions"`）の三つである（`Popup.cs:1375-1380`、`PopupMessage.cs:599-619`）。
  - `OnInputSubmit` は最初の Submit に `OnSelect` を呼ぶ（`PopupMessage.cs:946-958`）。
  - 結果の text は `inputBox.text` から写される（`Popup.cs:782-789`）。
  - このため、`inputBox.text = "RETIRE"` の後に `OnInputSubmit("RETIRE")` を呼べば、長押しと同じ経路で確定する（`PopupMessage.cs:1024-1030`）。
  - 同じ形の呼び出しは、ほかに `XRLCore.cs:1054`（ABANDON）、`WishManager.cs:109`（wish 入力。確認語なし）などがある。

### 3.6 スレッドと読み取りの安全性

**ブリッジスレッドから直接読んでよいもの**（Unity API を通らない、素の C# の状態）:

- `GameManager.Instance.CurrentGameView`: `__CurrentGameView` という string フィールドを返すだけ（`GameManager.cs:240,453-481`）。
- `GameManager.Instance.GetGameViewStackCopy()`: `lock (GameViewStack)` の中でコピーする（`:1441-1461`）。`PushGameView` と `PopGameView` も同じ lock を取る（`:1493-1541`）。
- `PopupMessage.lastPopupID`、`Options.ModernUI`、`XRLCore.CoreThread`（`XRLCore.cs:300`）の `ThreadState`。

**技術的には読めるが、同期がないもの**: `PopupMessage` の `commandCallback`、`selectCallback`、`onHide`、`PopupID`、`WantsSpecificPrompt`、`controller.menuData`、`Message.text`。

- どれも管理メモリ上のフィールドなので、読むこと自体で Unity の例外は出ない（推定）。
- ただし `ShowPopup` の途中の状態が見えうるので、複数のフィールドをまとめて読むと食い違う。
- 入口の `UIManager.instance.windowsByName` は、UI スレッドの `copyWindow` が書き換える `Dictionary` である（`UIManager.cs:25,337`）。別スレッドから列挙すると、並行変更で壊れうる。

**UI スレッド専用のもの**: `gameObject.activeSelf`、`isActiveAndEnabled`、`transform.GetSiblingIndex()`、`canvas.enabled`、`raycaster.enabled`（`isCurrentWindow`、`WindowBase.cs:143-146`）、TMP の `inputBox.text`、`UnityEngine.Object` の `== null`。

**推奨**: 毎フレーム（または要求時）に UI スレッドで不変のスナップショットを作り、`volatile` 参照で公開する。ブリッジはその参照だけを読む。

**UI スレッドへの渡し方**:

- `GameManager.Instance.uiQueue.queueTask(action)`（`ThreadTaskQueue.cs:157-176`）。結果が要るなら `executeAsync<T>`（`:77-100`）を使う。`GameManager.Update` の `uiQueue.executeTasks()`（`GameManager.cs:2963`）で実行されるので、遅れは 1 フレーム以内である。
  - 注意: `poolEntry` は lock なしで `taskPool.Enqueue` する（`ThreadTaskQueue.cs:23-26`、実行後に `ThreadTaskQueueEntry.cs:30-44` の Execute から呼ばれる）。一方、`queueTask` は lock の中で `taskPool.Dequeue` する。この競合は、ゲームスレッドが `awaitTask` を使う時点で既にあるもので（`Popup.cs:824`）、ブリッジはその生産者を一つ増やすだけである。
- もう一つの手は `The.UiContext.Post(...)` である。エンジンは A 経路のたびに、ゲームスレッドからこの Post を使っている（`Popup.cs:759`、`SynchronizationContextAwaiter.cs:19-22`）。

### 3.7 Harmony なしで購読できる通知

ポップアップの開閉を知らせる専用の static event はない。`Popup.cs`、`PopupMessage.cs`、`UIManager.cs`、`WindowBase.cs`、`XRL.UI.Framework` を `grep` した結果、static event は `ControlManager.onActiveDeviceChanged`（`ControlManager.cs:624`）だけで、ポップアップとは関係がない。代わりに使えるものは次の三つである。

- **`NavigationController.instance.suspensionContext.enterHandler` / `exitHandler`**: public な `Action` フィールドである（`XRL.UI.Framework/NavigationContext.cs:13-15`、呼び出しは `:146-160`）。`activeContext` の setter が変化したときに `FireEvent(Exit/Enter)` を呼び、`_activeContext` から親をたどって `OnEnter` / `OnExit` を呼ぶ（`NavigationController.cs:60-93,189-229`）。ポップアップは `SuspendContextWhile`（`:156-178`）と `EnforceSuspensionContext`（`PopupMessage.cs:960-966`）で suspension context に入る。ただし次の制約がある。
  - 遷移したときにしか発火しないので、入れ子のポップアップでは再発火しない。
  - `AskNumberScreen` や設定画面など、他の画面も使う。
  - 設定したスレッドの上で走る。A 経路ではゲームスレッドになる。
  
  したがって「何か開いたかもしれない」という合図にしか使えない。
- **`PopupMessage.lastPopupID`**: 最後に開いた ID。閉じても消えない。
- **`CurrentGameView` とビュースタック**: 同期経路は `"PopupMessage"`（`Popup.cs:829`）、非同期経路は `"DynamicPopupMessage"`（`:755`）、その下に `"ModernPopup:AskString"`（`:1389`）、`"ModernPopup:AskNumber"`（`:1345`）、`"ModernPopupGamepadAskNumber"`（`:1327`）が積まれる。これらの文字列を積むのは、この 5 か所だけである（`grep` 済み）。

結局、検出は UI スレッドでのポーリングになる。候補は二つある。

- ブリッジが `uiQueue` に毎回スナップショットのタスクを積む。
- mod が作る MonoBehaviour の `Update` で作る。これは実機で確かめる。

どちらも Harmony は要らない。

## 4. レシピ表

共通の定義:

- **UI 検出 D(pm)**: UI スレッドで `UIManager.instance.windowsByName` を列挙し、値が `PopupMessage pm` で、`pm.onHide != null` かつ `pm.gameObject.activeSelf` のものを選ぶ。
  - キーが `"PopupMessage"` なら S、`"PopupMessage #"` で始まれば A である。
  - 複数あれば、`transform.GetSiblingIndex()` が最大のものが最前面である（`ShowPopup` が `SetAsLastSibling` を呼ぶ、`PopupMessage.cs:775`）。
  - `onHide` は `ShowPopup` で必ず非 null になり（`:773`）、`Hide` で必ず null になる（`:1098-1103`）。そのため、答え済みで 2 フレームの消去待ちにある窓を除外できる。
  - `copyWindow` と `ShowPopup` は、同じ UI 継続の中で続けて実行される（`Popup.cs:760-779`）。UI スレッドで読む限り、その途中の状態は見えない。
- **トークン**: `token = pm.onHide`。1 回の `ShowPopup` ごとに、新しいクロージャになる（`Popup.cs:776-778`、`:873-877`）。答える直前に `ReferenceEquals(pm.onHide, token)` を確かめる。
- **R(pm)**:
  - 本文: `pm.Message.text` から `{{y|…}}` の外枠を外し、`ColorUtility.StripFormatting` を通す。
  - 題: `pm.Title.text` と `pm.contextText.text`。後者は `contextText.gameObject.activeSelf` のときだけ使う。
  - 選択肢: `pm.controller.menuData[i].text / command / hotkey`。
  - ボタン: `pm.controller.bottomContextOptions[j]`。
  - 入力: `pm.inputBox.gameObject.activeSelf`、`pm.inputBox.text`、`pm.WantsSpecificPrompt`、`pm.RestrictChars`、`pm.PopupID`。
- **A(item)**: UI スレッドで、トークンを確かめてから `pm.OnActivateCommand(item)` を呼ぶ。item は `menuData` か `bottomContextOptions` から取った実物に限る。事後に `pm.onHide == null` を確かめる。`CmdOptions` は使わない。
- **I(s)**: UI スレッドで `pm.inputBox.text = s` の後に `pm.OnInputSubmit(s)` を呼ぶ。

| モーダル | 待ち方 | プローブの起こし方（新規 Joppa） | 検出 | 読み取り | 応答 | 取り消し | Harmony |
|---|---|---|---|---|---|---|---|
| 通知（Show / ShowFail / ShowBlock / ShowBlockPrompt / ShowBlockSpace / ShowSpace） | S。`awaitTask` の後に `Task.Wait()`（`Popup.cs:824-909`） | wish `deathpopuptest`（`Wishing.cs:3338-3342`）。またはプローブの wish で `Popup.Show("probe")` | D(pm) かつキーが `"PopupMessage"`。ブリッジ側の目安は `CurrentGameView=="PopupMessage"` | 本文と題。ShowSpace の Title は contextText。メッセージログにも同文が入る（`:1091`、`:1133-1136`） | A(`bottomContextOptions[0]`)（`"Accept"`） | 応答と同じ（Accept が Cancel を兼ねる） | 不要 |
| ShowBlockWithCopy | S | プローブの wish | 同上 | 同上 | A(Copy) か A(Cancel)。Copy なら続けて Show が出る（`:679-691`） | A(Cancel) | 不要 |
| ShowYesNo / WarnYesNo | S | プローブの wish で `Popup.ShowYesNo` | 同上。ボタンの command が Yes / No | 本文、ボタン | A(Yes) か A(No) | A(No)。Cancel も No として扱われる（`:2260-2276`） | 不要 |
| ShowYesNoCancel / WarnYesNoCancel | S | プローブの wish | 同上 | 同上 | A(Yes / No / Cancel) | A(Cancel) | 不要 |
| PickOption 系（ShowOptionList / PickOptionAsync / Popup.PickGameObject / ShowColorPicker） | S。呼ぶスレッドはゲームスレッドか ThreadPool | wish `charset`（`Wishing.cs:222`。AllowEscape）、またはプローブの wish | D(pm) で `menuData.Count > 0` | 題（Title か contextText）、Intro（本文）、`menuData` の text（`"{{W|[a]}} {{y|…}}"`、`Popup.cs:2011-2044`） | A(`menuData[k]`)。`char:` ホットキーの経路と同じ（`PopupMessage.cs:1046-1062`）。`OnSelect` でもよい | `AllowEscape` なら A(Cancel)、返り値は −1（`Popup.cs:1742-1745`）。なければ選ぶしかない | 不要 |
| 死亡メニュー | S（PickOption、`CheckpointingSystem.cs:111-114`） | wish `CheckpointOn` の後に wish `die` | D(pm)、`PopupID==null`、`bottomContextOptions.Count==0`、`menuData` が 4 項目で本文が "You died." で始まる。呼び出し元を確実に識別するには内容で照合する | 本文（死因）と 4 択 | A(`menuData[k]`) | 取り消しはない。キャンセルを立てると既定値の 0 番になる（§3.1） | 不要（識別を厳密にするなら任意） |
| PickSeveral | S を繰り返す | プローブの wish | PickOption と同じ。ボタンに `"option:-2"` と `"option:-3"` がある | 選択肢の先頭の `[ ]` / `[þ]` / `[n]`（`Popup.cs:2067-2080`） | A(`menuData[k]`) で切り替え、A(`option:-2`) で確定 | AllowEscape なら A(Cancel) | 不要 |
| AskString（wish 入力を含む） | A。`AskStringAsync(...).Result`（`:1442`） | `CmdWish` で wish 入力を開く（`XRLCore.cs:1883-1885` → `WishManager.cs:106-121`） | D(pm)、キーが `"PopupMessage #"`、`inputBox` が有効。ビューは `"DynamicPopupMessage"`、その下に `"ModernPopup:AskString"` | 本文（`ClipText(…, 60)`）、`inputBox.text`（初期値＝Default） | I(s)。最初の Submit（`"keep"`）で `OnSelect` が走る | A(Cancel)。`ReturnNullForEscape` に応じて `""` か null（`:1412-1415`） | 不要 |
| AskString＋WantsSpecificPrompt（RETIRE / 終局 / ABANDON） | A | wish `CheckpointOn` → wish `die` → A(`option:2`) | 上に加えて `pm.WantsSpecificPrompt != null`。ボタンは keep / Cancel / CmdOptions | 本文と確認語（`WantsSpecificPrompt`） | I(`WantsSpecificPrompt`)。`OnActivateCommand(CmdOptions)` は拒否される（`PopupMessage.cs:928`） | A(Cancel) で `""`。RETIRE ならメニューに戻る | 不要 |
| AskNumber（キーボード） | A。`AskNumberAsync(...).Result`（`:1200`） | 積み重なったアイテムを落とす（`Inventory.cs:2444`）、またはプローブの wish | D(pm) で入力欄あり、`RestrictChars` が `"0123456789"` か `"0123456789-"`。ビューの下に `"ModernPopup:AskNumber"` | 本文と `inputBox.text`（初期値＝Start） | I(`n.ToString()`)。結果は `Convert.ToInt32`（`:1354`）と丸め（`:1200-1205`） | A(Cancel) で null | 不要 |
| AskNumber（ゲームパッド、AskNumberScreen） | `.Result` → `menucomplete.Task`（`AskNumberScreen.cs:133`） | プローブで `_activeControllerType` を Gamepad にしてから AskNumber を呼ぶ。上書きされうる | ビュースタックに `"ModernPopupGamepadAskNumber"`、かつ UI で `AskNumberScreen.instance.isCurrentWindow()` | `messageText.text`、`Current`、`Min`、`Max` | UI で `numberText.SetText(n.ToString())` の後に `Accept()` | `Cancel()` で null | 不要 |
| その他の A（ShowAsync / ShowYesNoAsync / Description の説明表示） | A。`.Result` か await | アイテムの説明を見る（`Description.cs:361`） | D(pm) でキーが `"PopupMessage #"` | 本文、ボタン、contextTitle | A(item) | A(Cancel) か A(Accept) | 不要 |

## 5. 主張一覧

| ID | 主張 | 根拠 | 確度 | 実機のみ |
|---|---|---|---|---|
| C-F1-popup-01 | Modern の Popup の入口は、同期の `WaitNewPopupMessage`（単体窓）と非同期の `NewPopupMessageAsync`（複製）の 2 本に集約される。`PopupMessage.ShowPopup` を呼ぶのはこの 2 か所だけである | `XRL.UI/Popup.cs:760-784,824-884`、`grep "\.ShowPopup("` | 高 | いいえ |
| C-F1-popup-02 | Show / ShowFail / ShowBlock / ShowBlockPrompt / ShowBlockSpace / ShowSpace / ShowBlockWithCopy / ShowYesNo / ShowYesNoCancel / PickOption（とその派生）は、Modern では同期経路 S を通り、ゲームスレッドは `complete.Task.Wait()` で止まる | `Popup.cs:669,676-679,968-970,1038-1040,1092-1094,1138-1140,1709-1740,2258-2260,2371-2373,908` | 高 | いいえ |
| C-F1-popup-03 | AskString と AskNumber（キーボード）は非同期経路 A の複製窓を使い、ゲームスレッドは `.Result` で止まる。継続は素の SynchronizationContext を通って ThreadPool で走るので、デッドロックしない | `Popup.cs:1442,1200,1349,1396,751-760`、`XRL.Core/XRLCore.cs:3557-3559` | 高 | いいえ |
| C-F1-popup-04 | 同期経路の `commandCallback` と `selectedItemCallback` は、どちらも `complete.SetResult(i)` で待ちを解く。前者は `EscapeNonMarkupFormatting` のとき `i.text.Replace` を呼ぶので、text が null の項目を渡すと例外になり、`TrySetException` に落ちる | `Popup.cs:834-868` | 高 | いいえ |
| C-F1-popup-05 | 非同期経路の二つの callback は、`onHide` を `t.TrySetResult(item)` に差し替えるだけで、完了は後に続く `Hide()` の中で起きる。先に `Hide()` を呼ぶと、元の `onHide`（`TrySetCanceled`）が走る | `Popup.cs:764-778`、`Qud.UI/PopupMessage.cs:926-944,1083-1104` | 高 | いいえ |
| C-F1-popup-06 | `WaitNewPopupMessage` は async void なので、`Hide()` 先行などでキャンセルが立っても、例外は呼び出し元に伝わらない。`PopGameView`（`:910`）は飛ばされ、callback も呼ばれない。そのため `PickOption` は `DefaultSelected` を、`ShowYesNo` は `defaultResult` を返す | `Popup.cs:801,873-877,908-921,1664,1759-1760,2257,2276` | 中（言語仕様は高。Unity の Mono での ThreadPool 例外の扱いは実機） | いいえ（副作用の出方は実機） |
| C-F1-popup-07 | 非同期経路でキャンセルが立つと、`AskStringAsync` と `AskNumberAsync` は例外を握って null を返す。`EndGame.cs:162` は戻り値に直接 `.ToUpper()` を呼ぶので、ゲームスレッドで NRE になる | `Popup.cs:1356-1360,1418-1422`、`XRL.World.Conversations.Parts/EndGame.cs:162` | 高 | いいえ |
| C-F1-popup-08 | `onHide != null` は、ShowPopup から Hide までの「未応答」を表す。S と A の両方で使え、答えた後の 2 フレームの消去待ち（`HideNextFrame`）を除外できる | `PopupMessage.cs:773,1085,1098-1103,970-983` | 高 | いいえ |
| C-F1-popup-09 | `onHide` の参照は `ShowPopup` のたびに新しいクロージャになるので、二重応答を防ぐトークンに使える | `Popup.cs:776-778,873-877`、`PopupMessage.cs:773` | 中（クロージャの割り当ては C# コンパイラの規則による） | いいえ |
| C-F1-popup-10 | 本文の選択肢に `OnActivateCommand(menuData[k])` を渡すと、エンジンの `char:` ホットキーの経路（`commandCallback(menuDatum)`、`commandCallback=null`、`Hide()`）と同じ処理になる | `PopupMessage.cs:926-934,1046-1062` | 高 | いいえ |
| C-F1-popup-11 | `OnActivateCommand` は、`CmdOptions` の項目、チュートリアルのゲート、`commandCallback==null` のいずれかで何もしない。`OnSelect` は、ゲートと `selectCallback==null` で何もしない。チュートリアルの外ではゲートは常に通る | `PopupMessage.cs:926-944`、`TutorialManager.cs:341-349` | 高 | いいえ |
| C-F1-popup-12 | 入力欄つきのポップアップは、UI スレッドで `inputBox.text=s` の後に `OnInputSubmit(s)` を呼べば確定する。`OnInputSubmit` は最初の Submit / Accept / CmdOptions のボタンに `OnSelect` を呼び、非同期経路は結果の text を `inputBox.text` から写す | `PopupMessage.cs:946-958`、`Popup.cs:781-789` | 高 | いいえ |
| C-F1-popup-13 | PC で `WantsSpecificPrompt` つきの AskString（RETIRE / 終局 / ABANDON）は、ボタンが keep / Cancel / CmdOptions になり、I(確認語) で長押しと同じ経路で確定する | `Popup.cs:1374-1385`、`PopupMessage.cs:599-619,1024-1030`、`CheckpointingSystem.cs:126-141`、`EndGame.cs:156-162` | 高 | いいえ |
| C-F1-popup-14 | 死亡メニューは、ボタンのない 4 択の PickOption（PopupID は null）である。Retire に誤った語を入れるとループに戻るので、I(s) の安全な試験場になる | `CheckpointingSystem.cs:111-141`、`Popup.cs:1727-1735,1740-1758` | 高 | いいえ |
| C-F1-popup-15 | 複製窓は `windowsByName["PopupMessage #N"]` に登録され、解放後も辞書に残る（`SetActive(false)` にしてプールに戻すだけ）。検出では、有効かどうかと `onHide` を併せて見る必要がある | `Qud.UI/UIManager.cs:323-354` | 高 | いいえ |
| C-F1-popup-16 | ポップアップの開閉を知らせる static event や callback のリストはない。Harmony なしで得られる通知は、suspensionContext の `enterHandler` / `exitHandler`（遷移時だけ、発火は設定したスレッド）と `lastPopupID`（消えない）にとどまり、検出はポーリングになる | `NavigationContext.cs:13-15,146-160`、`NavigationController.cs:60-93,189-229`、`PopupMessage.cs:249,874`、`ControlManager.cs:624` | 中 | いいえ |
| C-F1-popup-17 | ブリッジスレッドが直接読んでよいのは、`CurrentGameView`（string フィールド）と `GetGameViewStackCopy()`（lock つき）である。`windowsByName` の列挙と、`PopupMessage` の Unity 状態（activeSelf、SiblingIndex、TMP の text）は UI スレッドで読む | `GameManager.cs:240,453-481,1441-1461`、`UIManager.cs:25,337`、`WindowBase.cs:143-146` | 中 | はい（スレッド外アクセスの実際の挙動） |
| C-F1-popup-18 | ブリッジから UI スレッドへは、`uiQueue.queueTask` / `executeAsync` で渡せ、`GameManager.Update` の中で 1 フレーム以内に実行される。`taskPool` の lock なし Enqueue との競合は、既存の生産者（ゲームスレッドの `awaitTask`）と同じ性質のものである | `QupKit/ThreadTaskQueue.cs:23-26,77-100,135-176`、`QupKit/ThreadTaskQueueEntry.cs:30-44`、`GameManager.cs:2963`、`Popup.cs:824` | 中 | いいえ |
| C-F1-popup-19 | 同期経路の `"PopupMessage"` ビューは UI スレッドで積まれ、`ShowPopup` より先に来る。ゲームスレッドが `Task.Wait` に入る時点で、窓は表示済みである。非同期経路の `"DynamicPopupMessage"` は、窓ができる前にゲームスレッドで積まれる | `Popup.cs:824-829,884,908,755-760`、`ThreadTaskQueue.cs:135-155` | 高 | いいえ |
| C-F1-popup-20 | ゲームパッド時の AskNumber は AskNumberScreen になり、UI スレッドで `numberText.SetText(n)` の後に `Accept()` を呼べば確定する（`Cancel()` なら null）。値の丸めは呼び出し元の `AskNumber` が行う | `Popup.cs:1323-1331,1200-1205`、`Qud.UI/AskNumberScreen.cs:117-146,213-228` | 高 | いいえ |
| C-F1-popup-21 | 本文の選択肢とボタンが、プレハブの UnityEvent で `PopupMessage` のどのメソッドにつながっているかは、ソースから決まらない。`selectHandlers` はハイライトでも呼ばれる | `QudBaseMenuController.cs:73-79,111-114,153-172,438-465` | 高（「決まらない」ことについて） | はい |
| C-F1-popup-22 | F1 の検出、読み取り、応答は、どれも Harmony を必要としない。Harmony が役立つのは、呼び出し元を厳密に識別したい場合（例: `CheckpointingSystem.ShowDeathMessage` の prefix で印を付ける）と、プッシュ型の通知が欲しい場合に限られる | 本書 §3–§4 のまとめ | 中 | いいえ |

## 6. 実機でしか分からないこと

1. プレハブの配線（`activateHandlers`、`activateContextHandlers`、`selectHandlers`、`cancelHandlers` → `PopupMessage` のメソッド）。C-F1-popup-21。
2. ブリッジスレッドから `PopupMessage` の素のフィールドを読んだとき、例外や破損が起きないか。Unity API をスレッド外で呼ぶと例外になるか。C-F1-popup-17。
3. UI スレッドで `OnActivateCommand` や `OnInputSubmit` を直接呼んだ後、`NavigationController.activeContext` と入力の状態が、人間の操作の後と同じ状態に戻るか。同期経路は `SuspendContextWhile` を通らない。
4. `Hide()` 先行で async void の例外が ThreadPool に出たとき、Unity の Mono がどう振る舞うか（ログだけか、プロセスが落ちるか）。C-F1-popup-06。
5. 非同期経路で `TrySetResult` の継続がその場で同期実行されるか（`releaseCopy` が応答呼び出しの中で走るか）。応答の後は窓に触らない、という規則で吸収できる。
6. `ControlManager._activeControllerType` を書き換えて AskNumberScreen を起こすプローブが、`LateUpdate` による上書きの前に間に合うか。
7. mod の MonoBehaviour を Unity のシーンに加えて毎フレームのスナップショットを作れるか。できなければ `uiQueue` のタスクを毎回積む。
8. `inputBox.text` の setter と `Update` の `RestrictChars` フィルター（`PopupMessage.cs:992-1001`）が、プログラムから入れた値を消さないか。数字だけなら問題ないはずである。

## 7. 未解決の問い

- 死亡メニュー、`Popup.PickGameObject`、色選択、会話は、どれも同じ PickOption / S の形をとる。Harmony なしで区別する手段は、本文と選択肢の内容照合と、`PopupID` しかない。ID を付けているのは ShowSpace の `"DeathMessage"` と会話の `"Conversation:"+Title` などで、PickOption の多くは null である。内容照合で十分か、それとも任意の Harmony prefix を採るか。
- 色選択のネストがある。`AskStringAsync` の Color ループが ThreadPool から S を開く間、ゲームスレッドは `.Result` で止まったままである。最前面の窓だけに答える方針で足りるか。
- `ShowKeybindAsync`（AnyKey、cancelToken）は設定画面専用で、ゲーム中には出ないと見ているが、全呼び出し元は数えていない。
- `ShowConversation` は F1 と同じ S の窓を使う（`Popup.cs:1594`）。F2 側の述語（`PopupID` が `"Conversation:"` で始まる）と、F1 の汎用述語との優先順位をどう決めるか。
