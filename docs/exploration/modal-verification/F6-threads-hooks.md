# F6: スレッド、キュー、フックの仕組み（threads-hooks）

対象ビルド: 2.0.211.56（ILSpy で逆コンパイルしたソース。ソースルートは `/Users/sankenbisha/Dev/coq-decompiled_stable`）。
引用 `path:line` はすべてソースルートからの相対パスで、本作業で `sed -n` / `grep -n` を使って表示し、確認したものに限る。
Unity 側の挙動（メインスレッド専用 API、UnitySynchronizationContext、runInBackground が Update を止めるかどうか、動的アセンブリの MonoBehaviour）は逆コンパイルに含まれない。これらは「Unity の挙動」と明記し、確度を medium 以下にして実機検証へ回す。

## 1. 目的

Modern UI を画面に出したまま、ゲームスレッドがモーダルで止まっていることを検出し（detect）、その内容を読み（read）、ゲーム外のブリッジスレッドから答える（answer）。本書では、ほかの全ファミリーが前提にする「土台」を静的に確定させる。

- 二つのキュー（`uiQueue` / `gameQueue`）の意味と、どのスレッドで実行されるか
- フォーカスとビュー・スタックの管理
- `windowsByName` へのアクセス規則
- 入力キューが消される時点
- Harmony を使わずに mod から使えるフック
- プローブ用 wish の書き方
- ログの出し方

ここで確定した規則が、プローブ mod の実装仕様になる。

## 2. 対象一覧

| 領域 | ファイル |
|---|---|
| スレッド間キュー | `QupKit/ThreadTaskQueue.cs`, `QupKit/ThreadTaskQueueEntry.cs`, `XRL/SynchronizationContextAwaiter.cs`, `XRL/The.cs` |
| Unity 側の毎フレーム処理 | `QupKit/BaseGameController.cs`, `GameManager.cs`（`OnUpdate`, `AwakeRoutine`, `OnApplicationFocus`, `focused`, ビュー・スタック） |
| ウィンドウ管理 | `Qud.UI/UIManager.cs`, `Qud.UI/WindowBase.cs`, `Qud.UI/SingletonWindowBase.cs`, `Qud.UI/PopupMessage.cs`（Show / Hide / Update） |
| 入力 | `ConsoleLib.Console/Keyboard.cs`, `ControlManager.cs` |
| ゲームスレッド | `XRL.Core/XRLCore.cs`（`_ThreadStart`, `PlayerTurn`, ターンのコールバック, `RenderBase`, `NewGame`） |
| mod のフック | `XRL/ModManager.cs`, `XRL/ModInfo.cs`, `XRL/*Attribute.cs`, `XRL/PlayerMutator.cs`, `XRL.CharacterBuilds.Qud/QudGameBootModule.cs`, `XRL/XRLGame.cs`, `Qud.UI/NearbyItemsWindow.cs`（前例） |
| wish | `XRL.Wish/WishManager.cs`, `XRL.Wish/WishCommand.cs`, `XRL.Wish/MutationBGoneWishHandler.cs`, `XRL.World.Capabilities/Wishing.cs` |
| オプション | `XRL.UI/Options.cs`（`MusicBackground`, `CapInputBuffer`, `UpdateFlags`） |
| ログ | `MetricsManager.cs`, `XRL.Core/XRLCore.cs`（`LogError`） |

## 3. 各機構の動作

### 3.1 ThreadTaskQueue（`uiQueue` / `gameQueue`）

- 実体は `Queue<ThreadTaskQueueEntry>` の `taskQueue` と、エントリを使い回す `taskPool` である（`QupKit/ThreadTaskQueue.cs:10-14`）。
- **`queueTask(a, delay)`** は `lock(taskQueue)` の中で、プールからエントリを取り出し（なければ新しく作り）、キューに積んでエントリを返す。待たない（`:157-176`）。
- **`executeTasks()`** は、呼ばれた時点の件数 `num` だけを処理する（`:39-42`）。取り出しは `lock(taskQueue)` の中で行う（`:44-50`）。`Delay>0` のエントリは Delay を 1 減らして `delayedTasks` へ回し、最後にまとめて積み直す（`:53-57,64-74`）。
  - 実行中のタスクが自分自身を積み直した場合、そのタスクは次の `executeTasks` まで走らない。`num` の上限があるためである。したがって、`uiQueue` で自分を積み直すタスクは、Unity の 1 フレームにちょうど 1 回走る。
  - `queueTask(a, delay:n)` は、実行を n 回分（n フレーム分）遅らせる。
- **例外**: `ThreadTaskQueueEntry.Execute` がタスクを try/catch で包み、例外を `XRLCore.LogError` に渡してから、エントリを片付けてプールへ返す（`QupKit/ThreadTaskQueueEntry.cs:30-45`）。例外はキューを止めず、呼び出し元にも伝わらない。`XRLCore.LogError(Exception)` は `Debug.LogError("ERROR:"+ex)` を出す。`Keyboard.Closed` のときだけスレッドを Abort する（`XRL.Core/XRLCore.cs:3383-3391`）。
- **`executeAsync<T>(Func<T>)`** は `TaskCompletionSource` に結果か例外を入れて返す（`QupKit/ThreadTaskQueue.cs:77-100`）。ブリッジから「UI スレッドで読んで値を返す」処理を頼むときは、これを使うと例外も受け取れる。
- **`awaitTask(a)`** は二通りに動く（`:135-155`）。
  - 呼び出し元が `threadContext` 自身なら、その場で実行する。
  - そうでなければ、`ManualResetEvent` を使ってタスクを積み、完了まで**タイムアウトなしで**待つ。例外は `finally` でイベントを立てた後に Execute が握りつぶすので、待っている側には伝わらない。
  - ブリッジスレッドが使うと、UI スレッドが回っていない間（フォーカス喪失と runInBackground=false の組み合わせなど）は永久に止まりうる。ブリッジでは `executeAsync(...).Wait(timeout)` を使う。
- **スレッド安全性の穴**: `poolEntry` は `taskPool.Enqueue` を**ロックなしで**行う（`:23-26`）。呼ぶのは Execute、つまり実行側のスレッドである。一方、`queueTask` / `queueSingletonTask` は `taskPool.Dequeue` を `lock(taskQueue)` の中で行う（`:118-122,162-165`）。実行側はプールに返すときにこのロックを取らないので、別スレッドからの `queueTask` と実行側の `poolEntry` は、同じ `Queue<T>` を同時に変更しうる。
  - ゲーム自身もゲームスレッドから `uiQueue` に積んでいる（例: `UIManager.pushWindow` → `uiQueue.awaitTask`、`Qud.UI/UIManager.cs:356-370`。`WindowBase.queueUIAction`、`Qud.UI/WindowBase.cs:121-124`）。したがって、これは既存の競合である。ブリッジが頻繁に積むと、それだけ競合の頻度が上がる。
  - 推奨: ブリッジスレッドから `uiQueue.queueTask` を繰り返し呼ばない。UI スレッド上で自分を積み直すタスク（UI ティック）を 1 本だけ走らせ、それがブリッジ所有の `ConcurrentQueue` を毎フレーム空にする。積み直しは Execute の中、つまり UI スレッド上で起きるので、`taskPool` の競合は生じない。最初の 1 回は `[ModSensitiveCacheInit]`（UI スレッドで走る。§3.6）から積む。
- `threadContext` の設定: `uiQueue.threadContext` は `AwakeRoutine` で UI スレッドに（`GameManager.cs:852,868`）、`gameQueue.threadContext` は `StartGameThread` で `XRLCore.Start()` の返すスレッドに設定される（`GameManager.cs:1677-1678`）。
- **`gameQueue` を回すのは誰か**:
  - `XRLCore.RenderBase` が、呼び出し元が CoreThread のときにだけ回す（`XRL.Core/XRLCore.cs:2600-2605`）。PlayerTurn は反復ごとに `RenderBase` を呼ぶ（`:2368,2373`）。
  - `Keyboard.GetNextKey(pumpActions:true)` もキーが無いときに回す（`ConsoleLib.Console/Keyboard.cs:1033-1041`）。
  - ほかに `XRL.UI/Look.cs:658,933`（grep で確認）。
  - `WaitNewPopupMessage` の `Task.Wait()`（`XRL.UI/Popup.cs:906-909`）や `.Result` で止まっている間は、**だれも回さない**。
- **`gameQueue` では自分を積み直すタスクを使わない**: `GetNextKey(pumpActions:true)` は `gameQueue.HasTask()` が真だと `KeyEvent.WaitOne(20)` を飛ばす（`ConsoleLib.Console/Keyboard.cs:1017-1023`）。積み直し続けるタスクがあると、そうしたループが CPU を 100% 使って空回りする。
- `gameQueue.clear()` はロックを取らずに `taskQueue.Clear()` を呼ぶ（`QupKit/ThreadTaskQueue.cs:18-21`）。これは `XRLCore.Reset`（`XRL.Core/XRLCore.cs:508-519`）と `NewGame`（`:2837-2839`）で呼ばれるので、新規ゲームを始めると積んであったゲームスレッドのタスクは消える。
- **SynchronizationContext**:
  - `The.UiContext` は `GameManager.uiSynchronizationContext` で、`AwakeRoutine` の中で `SynchronizationContext.Current`（Unity の UnitySynchronizationContext）を取ったものである（`XRL/The.cs:41`、`GameManager.cs:869`）。
  - ゲームスレッドの `The.GameContext` は、素の `new SynchronizationContext()` である（`XRL.Core/XRLCore.cs:3553-3559`）。素の Post はスレッドプールに投げる（.NET の既定の挙動）。したがって `await The.GameContext` をしてもゲームスレッドには戻らない。
  - `await The.UiContext` は `SynchronizationContextAwaiter` を通して `_context.Post` を呼ぶ（`XRL/SynchronizationContextAwaiter.cs:16-21`）。ブリッジから UI スレッドへ投げるもう一つの経路として `The.UiContext.Post(cb, state)` が使える。Unity の実装はロックを取るのでスレッド安全と考えられるが、これは Unity の挙動で、逆コンパイルでは確かめられない。

### 3.2 GameManager の Update とフォーカス

- `GameManager : BaseGameController<GameManager>` の `Update()` は `OnUpdate()` を呼ぶだけである（`GameManager.cs:37`、`QupKit/BaseGameController.cs:27-34`）。
- `OnUpdate`（`GameManager.cs:2899`〜）の中の順序:
  1. `UpdateInput()`（`:2958`）
  2. `uiQueue.executeTasks()`（`:2963`）
  3. `if (!XRLCore.bThreadFocus) { SoundManager.Update(); Thread.Sleep(250); return; }`（`:3108-3113`）
  4. `TextConsole.BufferUpdated` のときに、`lock(GameViewStack)` の中で `_ActiveGameView != CurrentGameView || bViewUpdated` なら `ControlManager.ResetInput()` と `UpdateView()` を呼ぶ（`:3172-3183`）

  つまり **`uiQueue` はフォーカスが無くても毎フレーム回る**。ただし直後の `Thread.Sleep(250)` で UI スレッド全体が止まるので、フレームレートは約 4 fps に落ちる（Update が呼ばれていることが前提。runInBackground については下記）。
- `OnApplicationFocus(focus)` は `XRLCore.bThreadFocus = focus; focused = focus;` を実行する（`GameManager.cs:1920-1924`）。`OnApplicationPause` は `focused = !pauseStatus` を実行する（`:1926-1929`）。
- `GameManager.focused` のセッター（`GameManager.cs:404-427`）:
  - false から true に変わるときに `Keyboard.ClearInput(); Keyboard.ClearMouseEvents(); mouseDisable = 0.25f` を実行する（`:412-417`）。**フォーカスを戻すと、積んであった入力は消える**。
  - 値に応じて `focusedEvent` を Set / Reset する。
- **ゲームスレッドはフォーカスが無いと PlayerTurn の先頭で止まる**: `while (!GameManager.focused && Game.Running) Thread.Sleep(200);`（`XRL.Core/XRLCore.cs:737-740`）。フォーカスが無いと、`kbhit` は `KeyEvent.WaitOne(200)` をしてから判定し（`ConsoleLib.Console/Keyboard.cs:938-954`）、`GetNextKey` は `WaitOne(1000)` で待つ（`:1015-1031`）。
- `XRLCore.bThreadFocus` は public static（`XRL.Core/XRLCore.cs:223`）、`GameManager.focused` は public static プロパティである。ブリッジはこの二つを true に書ける。ただし `OnApplicationFocus(false)` が来るたびに上書きされるので、UI ティックで毎フレーム書き直す必要がある。書き直すと false→true の遷移で入力が消えるので、**入力を積む前に書く**。
- `Application.runInBackground` は、`Options.MusicBackground`（`[OptionFlag]` の static bool。`XRL.UI/Options.cs:66-67`）に従って設定される。ID は、プレフィックス "Option" とフィールド名から `OptionMusicBackground` になる（`XRL.UI/Options.cs:1159-1169`）。設定は、`Options.UpdateFlags`（`:1273`）が積む `uiQueue` タスク（`:1410`）の中で行われる（`:1445-1453`）。
  - runInBackground=false のとき、macOS のスタンドアロンでフォーカスを失うと Update 自体が止まるか。これは Unity の挙動で、実機で確認する。
  - 止まる場合、uiQueue も回らず、UI スレッドを経由する回答はすべて止まる。

### 3.3 ビュー・スタック（CurrentGameView）

- `CurrentGameView` は、string フィールド `__CurrentGameView` に対するプロパティの二重ラッパーである（`GameManager.cs:240,453-484`）。**volatile でもロックでもない**。
- `PushGameView` / `PopGameView` / `SetGameViewStack` / `RemoveGameView` / `ForceGameView` は `lock(GameViewStack)` の中で書き換える（`GameManager.cs:1493-1571`）。
- `PushGameView` と `PopGameView` は、ロックに入る前に `ControlManager.ResetInput()` を呼ぶ（`:1495,1525`）。
- PlayerTurn は、ループの反復ごとにロックなしで `CurrentGameView = Options.StageViewID`（"Stage"）を代入する（`XRL.Core/XRLCore.cs:741`、`XRL.UI/Options.cs:1063`）。
- **別スレッドから読む方法**:
  - 参照型フィールドの読み出しは不可分なので、ブリッジスレッドが `GameManager.Instance.CurrentGameView` を読んでも、途中まで書き換わった値は見えない。ただしメモリバリアが無いので、少し古い値が見えることはある。
  - スタック全体は `GetGameViewStackCopy()` で読める。これは `lock(GameViewStack)` の中で配列にコピーする（`GameManager.cs:1441-1462`）。
  - モーダルを確定させる判定は UI ティックで行う。ブリッジスレッドは、目安のポーリングだけに使う。
- UI スレッドが実際に反映したビューは `_ActiveGameView`（public。`GameManager.cs:238`）である。`OnUpdate` は `_ActiveGameView != CurrentGameView` **または `bViewUpdated`**（public。`GameManager.cs:248`）のときに `ResetInput` と `UpdateView` を走らせる（`:3178-3182`）。`bViewUpdated` を立てるのは `EnsureGameView`（`:1436-1439`。`XRL.UI.Framework/APIDispatch.cs:41,78` から呼ばれる）、`SetGameViewStack`、`PushGameView`、`ForceGameView`、`PopGameView`、`RemoveGameView`（`:1476,1488,1504,1519,1540,1560`）である。`UpdateView()` は、`_ActiveGameView != _CurrentGameView` のとき `ControlManager.ResetInput()` と `Keyboard.ClearInput()` を呼んでから、`_ActiveGameView` を更新する（`:1573-1582`）。

### 3.4 UIManager と windowsByName

- `windowsByName` は、ロックの無い `Dictionary<string, WindowBase>` である（`Qud.UI/UIManager.cs:25`）。
  - 書き込み: `Init`（`:422-431`）、`DiscoverWindows`（`:405-420`）、`createWindow`（`:319`）、`copyWindow`（`:337`。`lock(popupMessages)` の中だが、読み手はこのロックを取らない）、`DestroyWindow`（`:134-145`）。
  - `copyWindow` は `UnityEngine.Object.Instantiate` を呼ぶ（`:335`）ので、UI スレッドでしか動かない（Unity の挙動）。実際の呼び出し元は `NewPopupMessageAsync` の `await The.UiContext` の後だけである（`XRL.UI/Popup.cs:759-760`）。
  - したがって、**ブリッジスレッドが `windowsByName` を列挙すると、UI スレッドの Add と競合する**。Dictionary を読んでいる最中に別スレッドが書くと、例外や不整合が起きうる（.NET の仕様）。
  - さらに `WindowBase.Visible` は `gameObject.activeInHierarchy` と `canvas.enabled` を読む（`Qud.UI/WindowBase.cs:28-46`）。これらは Unity の API で、メインスレッド以外から呼ぶと例外になる可能性が高い（Unity の挙動）。
  - 結論: ウィンドウの状態を調べるのは UI ティックの中だけにする。
- 複製: `copyWindow("PopupMessage")` は、プールに空きがあればそれを `SetActive(true)` にして使い回す。なければ `Instantiate` して "PopupMessage #N" として `windowsByName` に登録する。複製は `windows` リストには入らない（`Qud.UI/UIManager.cs:323-342`）。`releaseCopy` はプールに戻して `SetActive(false)` にする（`:344-354`）。登録は解除されないので、**非アクティブの複製も `windowsByName` に残る**。
- **表示中かどうかの判定**:
  - `PopupMessage.Hide()` は `HideNextFrame = 2` にし、raycaster と interactable を切り、`onHide` を同期で呼ぶ。`canvas.enabled` は切らない（`Qud.UI/PopupMessage.cs:1083-1104`）。
  - 2 フレーム後の `Update` で alpha=0、canvas を無効にし、`SetActive(false)` にする（`:968-981`）。
  - `Show` は `HideNextFrame=0` にしてから `WindowBase.Show` を呼び、active、canvas、raycaster、alpha、interactable を立てる（`Qud.UI/PopupMessage.cs:1076-1081`、`Qud.UI/WindowBase.cs:197-218`）。
  - したがって、`Visible`（active && canvas.enabled）は Hide の後 2 フレームのあいだ偽陽性になる。表示中の判定には `gameObject.activeSelf && canvasGroup.interactable` を使う。
- `getWindow<T>(name)` は、キーが無いと `KeyNotFoundException` を投げる（`Qud.UI/UIManager.cs:277-280`）。`getWindow(name)` は null を返す（`:282-297`）。
- 単体のウィンドウは `SingletonWindowBase<T>.instance` で取れる。これは `Init` で設定される（`Qud.UI/SingletonWindowBase.cs:5-23`）。
- `UIManager.ModReload`（`[ModSensitiveCacheInit]`）は、`uiQueue` 経由ですべてのウィンドウの `Init` を呼び直す（`Qud.UI/UIManager.cs:452-465`）。mod の hotload で UI が作り直されるわけではない。

### 3.5 Keyboard と ControlManager：入力が消える時点

- `Keyboard.PushKey(ev)`:
  - `TutorialManager.AllowPushKey` を通らないと捨てる。
  - `KeyQueue.Count <= 2 || !GameManager.bCapInputBuffer` のときだけ `lock(KeyQueue)` で積み、`KeyEvent.Set()` を呼ぶ（`ConsoleLib.Console/Keyboard.cs:777-796`）。
- `Keyboard.PushCommand(cmd)` = `PushMouseEvent("Command:"+cmd)` である（`:723-726,128`）。`PushMouseEvent` は、`TutorialManager.AllowMouseEvent` が偽のとき、または `MouseEventQueue.Count > 2 && bCapInputBuffer` のときに捨てる（`:825-849`）。
- `GameManager.bCapInputBuffer` は `Options.CapInputBuffer`（`OptionCapInputBuffer`）から設定される（`XRL.UI/Options.cs:1279-1286`、`:336`）。**プローブのプロファイルでは OptionCapInputBuffer=No にする**。有効だと、3 件を超えて積んだ入力が黙って捨てられる。
- 入力を**読むのはゲームスレッドの `GetNextKey` だけ**である（`getvk` / `getch` / `getchraw`、`ConsoleLib.Console/Keyboard.cs:956-1060,1354-1370`）。ほかに PlayerTurn が `kbhit`、`HasMouseEvent`、`PopMouseEvent` を直接読む（`XRL.Core/XRLCore.cs:754-780`）。UGUI の Modern ポップアップは、このキューを読まない（05 C02 と同じ結論）。
- **入力が消える時点**（どれも `KeyQueue` と `MouseEventQueue` を空にする）:
  1. `ControlManager.ResetInput()` → `Keyboard.ClearInput(LeaveMovementEvents)`（`ControlManager.cs:1491-1494`、`ConsoleLib.Console/Keyboard.cs:877-891`）。`PushGameView`、`PopGameView`、`SetGameViewStack`（`GameManager.cs:1465-1467,1481-1483,1493-1495,1523-1525`）、`NewPopupMessageAsync`（`XRL.UI/Popup.cs:756`）、`WaitNewPopupMessage`（`:804`）、`AskStringAsync`（`:1373`）、`AskNumberAsync`（`:1322`）から呼ばれる。
  2. UI スレッドの `OnUpdate` が、`_ActiveGameView != CurrentGameView || bViewUpdated` のフレームに `ControlManager.ResetInput()` を呼び、続く `UpdateView()` がビューの変化時に `Keyboard.ClearInput()` を呼ぶ（`GameManager.cs:3172-3183,1577-1581`）。**この処理は同じ `OnUpdate` の中で `uiQueue.executeTasks()`（`:2963`）より後に走る。** したがって、ビューが変わったフレームに UI ティックで積んだ入力は、同じフレームのうちに消える。
  3. `GameManager.focused` が false から true に変わるとき（`GameManager.cs:412-417`）。
  4. PlayerTurn の入口の `Keyboard.ClearMouseEvents(LeaveMovementEvents: true)`（`XRL.Core/XRLCore.cs:734`）。これは PlayerTurn の while ループの**前**で 1 回だけ呼ばれ、移動系（`Meta:Navigate`、`Command:CmdMove`、`Command:CmdAutoMove`）以外のマウスイベントとコマンドを捨てる（`ConsoleLib.Console/Keyboard.cs:893-924`）。したがって、`PushCommand` はゲームスレッドが PlayerTurn のループに入った後に積む。
  5. 各ポップアップ自身の `Keyboard.ClearInput(..., clearFrameDown:true)`（例: `XRL.UI/Popup.cs:1759`、`:2282`）。
- **ゲームスレッドの getvk ループ（PickDirection / PickTarget）に入力を積むときの前提**: `GameManager.Instance._ActiveGameView == CurrentGameView && !bViewUpdated` を UI ティックで確かめてから積む。確認しないと、2. で消される。`bViewUpdated` は `TextConsole.BufferUpdated` が立ったフレームまで下りない（`GameManager.cs:3172-3181`）ので、条件が成り立つまで数フレーム待つことがある。
- `ControlManager.ResetInput` の後半（レイヤーの無効化、`Input.ResetInputAxes`）は UI コンテキストでしか走らない（`ControlManager.cs:1503-1515`）。`ControlManager.WaitForKeyup` はリストに足すだけで、ブロックしない（`ControlManager.cs:704-713`）。

### 3.6 Harmony を使わずに mod から使えるフック

- **mod のコンパイル**: Roslyn（`RoslynCSharpCompiler`）でコンパイルする。`GenerateInMemory = !Options.OutputModAssembly` なので、既定ではアセンブリはメモリ上にある（`XRL/ModManager.cs:116-135`）。できたアセンブリは `ModAssemblies` に入る（`:43,445`）。`ActiveAssemblies` は本体と mod のアセンブリを返す（`:104-114`）。
- **Harmony が走る条件**: アセンブリに `HarmonyAttribute` を持つ型があるときだけ、`PatchAll` を呼ぶ（`XRL/ModInfo.cs:845-861`）。**Harmony の属性を一つも使わなければ、arm64 ネイティブでも失敗の経路に入らない**。
- **(a) ブリッジスレッドの起動**:
  - `[ModSensitiveCacheInit]`: 付けたクラスに `[HasModSensitiveStaticCache]` が必要（`XRL/HasModSensitiveStaticCacheAttribute.cs:5-8`、`XRL/ModManager.cs:340-371`）。起動時は `GameManager.AwakeRoutine`（UI スレッドのコルーチン。`GameManager.cs:852`）→ `ModManager.Init()`（`:912`）→ `ResetModSensitiveStaticCaches()`（`XRL/ModManager.cs:661`）の順で呼ばれる。
    - このとき `uiQueue.threadContext` は設定済みで（`GameManager.cs:868`）、ゲームスレッドはまだ起動していない（`StartGameThread` は `OnUpdate` の `:3146-3150`）。
    - hotload（`XRLCore.HotloadConfiguration`、`XRL.Core/XRLCore.cs:575-577`）のたびにも呼ばれる。
    - **フィールドのリセットがメソッドの呼び出しより先**である（`XRL/ModManager.cs:344-358` が `:359-369` より前）。
    - スレッドの起動は、mod 側の static フィールド（`[ModSensitiveStaticCache]` を付けない）で二重起動を防ぐ。コールバックの登録は、無条件で毎回行う（下記）。
  - `[CallAfterGameLoaded]`（`[HasCallAfterGameLoaded]` クラスに付ける）: セーブのロード時だけ、`XRLGame.LoadGame` の中から呼ばれる（`XRL/XRLGame.cs:1954`、`XRL/ModManager.cs:374-386`）。`LoadCurrentGame` は `task.Wait()` で同期的に待つ（`XRL/XRLGame.cs:1653-1658`）。
  - `[PlayerMutator]`（`IPlayerMutator.mutate(player)`）: 新規ゲームの embark 時に `QudGameBootModule.bootGame` から呼ばれる（`XRL.CharacterBuilds.Qud/QudGameBootModule.cs:229,303-307`）。呼び出しは `XRLCore._Start`（`XRL.Core/XRLCore.cs:3585`）→ `NewGame()`（`:3775,2837`）→ `EmbarkInfo.bootGame`（`:2860`、`XRL.CharacterBuilds/EmbarkInfo.cs:38-43`）とたどれる。`_Start` は CoreThread で走る（`XRL.Core/XRLCore.cs:3553-3563`）ので、ゲームスレッドで呼ばれる。v1 はここから `The.Game.RequireSystem<T>()` を呼んでいた（04 の記述）。
  - `IGameSystem`: `XRLGame.RequireSystem<T>()`（`XRL/XRLGame.cs:304-344`）で登録する。`IGameSystem` はイベントハンドラ（`XRL/IGameSystem.cs:12`〜）。ゲームごとのフックとしては使えるが、ブリッジスレッドの起動は `[ModSensitiveCacheInit]` に寄せる方が単純である。
- **(b) 毎 UI フレームで走るコード**:
  - 第一案（Harmony も MonoBehaviour も使わない）: 自分を積み直す `uiQueue` タスク。§3.1 の性質から 1 フレームに 1 回走り、`OnUpdate` の `:2963` で実行される。フォーカスが無くても走るが、約 4 fps に落ちる（§3.2）。
  - 第二案: mod で定義した `MonoBehaviour` を `AddComponent` する。ゲーム自身が、XML に書かれた Class 名を `ModManager.ResolveType` で解決し（mod のアセンブリも探す。`XRL/ModManager.cs:296-320`、`XRL.CharacterBuilds/AbstractEmbarkBuilderModule.cs:385-405`）、`UIManager.createWindow` の中で `obj.AddComponent(scriptType)` を呼んでいる（`Qud.UI/UIManager.cs:299-321`、`XRL.CharacterBuilds/EmbarkBuilderModuleWindowDescriptor.cs:60-72`）。つまり、mod の型を `AddComponent` する経路をゲーム自身が想定している。ただし、メモリ上の Roslyn アセンブリの MonoBehaviour に Unity の `Update` が届くかは Unity(Mono) の挙動で、実機で確かめる。
- **(c) PlayerTurn の出入りの通知**:
  - `XRLCore.RegisterOnBeginPlayerTurnCallback`（`XRL.Core/XRLCore.cs:604-607`）は `PlayerTurn()` の入口で呼ばれる（`:690-693,682-688`）。
  - `RegisterOnEndPlayerTurnCallback(action, Single:false)` は、**PlayerTurn のループの反復ごと（キー入力なしの待機も含む）**に呼ばれる（`:2355-2359`）。これは `if (kbhit…)` / `else if` の後にあるので、どちらの分岐を通っても呼ばれる（`:754`、`:2350-2354`）。
  - `Single:true` は、`flag`（コマンドを処理した）のときだけ呼ばれる（`:2376-2386`）。
  - これらのリストは `[ModSensitiveStaticCache(true)]` で、hotload のたびに空になる（`XRL.Core/XRLCore.cs:251-265`、`XRLCore` は `[HasModSensitiveStaticCache]`。`:40`）。前例として、`NearbyItemsWindow.SystemInit` が `[ModSensitiveCacheInit]` の中で登録している（`Qud.UI/NearbyItemsWindow.cs:16,53-64`）。
  - **入力を積む場所は End であって Begin ではない**: Begin のコールバックは `PlayerTurn()` の入口（`XRL.Core/XRLCore.cs:690-693`）で、入口の `Keyboard.ClearMouseEvents(LeaveMovementEvents:true)`（`:734`）より前に走る。したがって Begin から `PushCommand` したコマンドは、ループが読む前に捨てられる。End（Single:false）はループの中（`:2355-2359`）、つまり `:734` の後で走るので、ここから積んだコマンドは次の反復で読まれる。
  - 呼ばれるのはゲームスレッドなので、ここで `gameQueue` 相当の処理（ブリッジからゲームスレッドへの依頼）を実行できる。これが Harmony を使わないゲームスレッドのティックになる。ただし、モーダルで待っている間と、フォーカス待ちで止まっている間（`:737-740`）は呼ばれない。
  - PlayerTurn は CoreThread で走ると考えてよい。`runPlayerTurnOnUIThread` への書き込みは false だけで（`XRL.Core/XRLCore.cs:2346,2353,2401`）、`runWholeTurnOnUIThread` は 0 で初期化されて減らされるだけである（`GameManager.cs:384`、`XRL.Core/ActionManager.cs:758-762`）。どちらも true / 正の値に設定する箇所が無い（grep で 0 件）。
  - 押し込んだ入力の後始末: `ActionManager.SkipPlayerTurn=true` にすると、`IdleWait` の直後に PlayerTurn を抜ける（`XRL.Core/XRLCore.cs:2390-2397`）。
- **ウィンドウ / ポップアップが開いたことの通知**: Harmony を使わないイベントは無い。UI ティックの中で、`CurrentGameView`、`_ActiveGameView`、各ウィンドウの `activeSelf && canvasGroup.interactable`、各コールバック参照の変化をポーリングして検出する。

### 3.7 プローブの起点としての wish

- `[HasWishCommand]` クラスの `[WishCommand]` メソッドは、`ModManager.GetMethodsWithAttribute` で集められる（`XRL.Wish/WishManager.cs:40-85`）。
  - 引数なしのメソッドは `^cmd$` に、string / Match 引数のメソッドは `^cmd(?::|\s+)(.*)$` に一致する（`:63-75`）。
  - 最初の一致を実行し、void か true を返したら終わる（`:131-165`）。
  - static でなければ `Activator.CreateInstance` で作ったインスタンスで呼ばれる（`:87-99,157`）。
- `Wishing.HandleWish` はまず `WishManager.HandleWish` を試し、失敗したときに組み込みの wish（`conv:<ID>[:<Blueprint>]` など）を処理する（`XRL.World.Capabilities/Wishing.cs:45-56`）。
- 実行スレッドは起点によって決まる。
  - **経路 A（主）**: ブリッジが次のどちらかでゲームスレッドに依頼する。
    - (i) EndPlayerTurn コールバックの中で、依頼キューを取り出して実行する。
    - (ii) `gameQueue.queueTask` に 1 回だけ積む。PlayerTurn の `RenderBase`（`XRL.Core/XRLCore.cs:2368,2373` → `2602-2605`）が実行する。
    
    どちらもゲームスレッドなので、`Popup.ShowYesNo` などを同期で呼べる。ゲーム自身も `gameQueue` のタスクの中で Popup を出す（例: `GameManager.cs:2946-2950` の `FinishQuestStep`）。
  - **経路 B（副）**: `Keyboard.PushCommand("CmdWish")` → PlayerTurn の `case "CmdWish": WishManager.AskWish()`（`XRL.Core/XRLCore.cs:1883-1885`）。`AskWish` は Modern の `Popup.AskString` を出す（`XRL.Wish/WishManager.cs:106-122`）。これに答えれば AskString のプローブを兼ねる。コマンドは PlayerTurn のループに入ってから積む（§3.5 の 4）。
- 前例: `MutationBGoneWishHandler` は、wish ハンドラの中から `Popup.PickOption` と `Popup.Show` を同期で呼んでいる（`XRL.Wish/MutationBGoneWishHandler.cs:11-32`）。
- 注意: `WaitNewPopupMessage` は、UI スレッドから呼ばれると async の経路に入り、待たずに戻る（`XRL.UI/Popup.cs:804-826`）。**プローブの Popup 呼び出しは、必ずゲームスレッドから行う**。

プローブ用 wish の例（Roslyn でコンパイルする mod のコード。API は下記の引用で確認済み）:

```csharp
using System.Collections.Generic;
using XRL;
using XRL.UI;
using XRL.Wish;
using XRL.World;
using XRL.World.Parts;

[HasWishCommand]
public static class LLMProbeWishes
{
    static void Log(string s) => MetricsManager.LogInfo("[LLMProbe] " + s);

    [WishCommand("llmprobe")]
    public static void Probe(string arg)
    {
        switch (arg)
        {
        case "yesno":   // XRL.UI/Popup.cs:2251, WaitNewPopupMessage + YesNoButton
            Log("yesno=" + Popup.ShowYesNo("LLMProbe: yes or no?"));
            break;
        case "askspecific": // XRL.UI/Popup.cs:1433 / 1371-1389。Default="" なので PC では SubmitCancelHoldButton
            Log("ask=" + Popup.AskString("LLMProbe: type RETIRE", "", WantsSpecificPrompt: "RETIRE"));
            break;
        case "askstring":
            Log("ask=" + Popup.AskString("LLMProbe: type anything", ""));
            break;
        case "pickoption": // XRL.UI/Popup.cs:1650, 1709-1757
            Log("pick=" + Popup.PickOption("LLMProbe", "Pick one", Options: new[] { "alpha", "beta", "gamma" }, AllowEscape: true));
            break;
        case "asknumber":  // XRL.UI/Popup.cs:1191-1205。キーボード時は NewPopupMessageAsync(askingNumber)
            Log("num=" + Popup.AskNumber("LLMProbe: how many?", Start: 3, Min: 0, Max: 10));
            break;
        case "pickitem": { // XRL.UI/PickItem.cs:263, 316-327 → PickGameObjectScreen.show(...).Result
            var items = new List<GameObject> { GameObject.Create("Torch"), GameObject.Create("Waterskin"), GameObject.Create("Bookshelf") };
            var got = PickItem.ShowPicker(items, Title: "LLMProbe: pick", PreserveOrder: true);
            Log("item=" + got?.Blueprint);
            break; }
        case "pickdir":    // XRL.UI/PickDirection.cs:28-31
            Log("dir=" + PickDirection.ShowPicker("LLMProbe"));
            break;
        case "picktarget": { // XRL.UI/PickTarget.cs:378-381
            var c = The.Player.CurrentCell;
            var cell = PickTarget.ShowPicker(PickTarget.PickStyle.EmptyCell, 0, 9999, c.X, c.Y, Locked: false, Label: "LLMProbe");
            Log("cell=" + (cell == null ? "null" : cell.X + "," + cell.Y));
            break; }
        case "conv": {     // XRL.World.Parts/ConversationScript.cs:528-531 → ConversationUI.HaveConversation → Popup.ShowConversation
            var npc = The.Player.CurrentZone?.FindObject("Mehmet");
            if (npc == null) { npc = GameObject.Create("Mehmet"); The.Player.CurrentCell.GetFirstEmptyAdjacentCell(1, 2)?.AddObject(npc); }
            npc.GetPart<ConversationScript>()?.AttemptConversation();
            break; }
        case "trade": {    // XRL.UI/TradeUI.cs:344, 456-458 → TradeScreen.show(...).Result
            var tam = The.Player.CurrentZone?.FindObject("Tam") ?? GameObject.Create("Tam");
            TradeUI.ShowTradeScreen(tam);
            break; }
        case "status":     // XRL.UI/Screens.cs:39-80。ModernCharacterSheet=Yes のときだけ StatusScreensScreen
            Screens.ShowPopup("Factions", The.Player);
            break;
        }
    }
}
```

`GameObject.Create(string)` は `XRL.World/GameObject.cs:2295` にある。`"Torch"` / `"Waterskin"` / `"Bookshelf"` / `"Mehmet"` / `"Tam"` は、ソース中で blueprint 名として使われている（`XRL.World.Effects/DeepDream.cs:279`、`XRL.Annals/ImportedFoodorDrink.cs:49`、`XRL.World.ZoneBuilders/VillageCodaBase.cs:2452`、`XRL.World.ZoneBuilders/FindASpecificItemDynamicQuestTemplate_FabricateQuestGiver.cs:47`、`XRL.World.Capabilities/Wishing.cs:2888`）。`Cell.GetFirstEmptyAdjacentCell(int,int)` は `XRL.World/Cell.cs:7191` にある。wish を `llmprobe:yesno` のように呼ぶと、`^llmprobe(?::|\s+)(.*)$` に一致して `arg="yesno"` になる。

ゲームスレッドへの依頼の例:

```csharp
GameManager.Instance.gameQueue.queueTask(() => Wishing.HandleWish(The.Player, "llmprobe:yesno"));
```

これは 1 回だけ積む。積み直しはしない（§3.1）。

### 3.8 ログ

- `MetricsManager.LogInfo(msg)` は `UnityEngine.Debug.Log("INFO - " + msg)` を出す（`MetricsManager.cs:411-414`）。`XRLCore.LogError(Exception)` は `Debug.LogError("ERROR:"+ex)` を出す（`XRL.Core/XRLCore.cs:3383-3386`）。
- 出力先は Unity の Player.log である。macOS の既定は `~/Library/Logs/Freehold Games/CavesOfQud/Player.log`。`-logFile` で変えられる（出典: `docs/exploration/04-coq-data-and-deploy.md:176,197`。逆コンパイルでは確認できない）。
- Debug.Log を別スレッドから呼んでよいかは Unity の挙動である。ゲーム自身は CoreThread から `Debug.Log` を呼んでいる（`XRL.Core/XRLCore.cs:3563-3570` の `_ThreadStart` の catch）。したがって、少なくともゲームスレッドからは実績がある。ブリッジスレッドからの呼び出しは、プローブで確かめる。

## 4. ブリッジの推奨構成（静的に言える範囲）

1. `[HasModSensitiveStaticCache]` クラスの `[ModSensitiveCacheInit]` で、次のことを行う。
   - (i) Begin / EndPlayerTurn コールバックを無条件で登録する。
   - (ii) ブリッジスレッドが未起動なら起動する。
   - (iii) UI ティックが未起動なら、`uiQueue.queueTask(UiTick)` で 1 回だけ積む。
2. **UI ティック**（UI スレッド、毎フレーム）。`[ModSensitiveCacheInit]` から積むので、`AwakeRoutine` の途中から走り始める。uiQueue は `bInitComplete` の検査（`GameManager.cs:3155-3158`）より前に回る（`:2963`）ので、メインメニューや embark の間も走る。`The.Game` や `The.Player` が null でも落ちないように書く。
   - (a) `XRLCore.bThreadFocus` と `GameManager.focused` を true に書き直す（任意）。
   - (b) `_ActiveGameView`、`CurrentGameView`、`GetGameViewStackCopy()` と各モーダルの述語を評価し、スナップショットをブリッジに渡す。
   - (c) ブリッジの `ConcurrentQueue<Action>` を空にする（回答の実行と、getvk 系への `PushKey` / `PushMouseEvent`）。
   - (d) 最後に自分を `uiQueue.queueTask(UiTick)` で積み直す。例外で積み直しが途切れないよう、try/finally を使う。
3. **ゲームスレッドのティック** = EndPlayerTurn コールバック（BeginPlayerTurn ではない。§3.6 (c)）。ブリッジの `ConcurrentQueue<Action>` を空にし、wish やゲーム状態の読み取りを実行する。モーダルで待っている間は止まる。
4. ブリッジスレッドは、`Wait(timeout)` 付きの待ちだけを使う。`awaitTask` は使わない。

## 5. レシピ表

述語の欄の「UI」は UI ティック（UI スレッド）で評価することを表す。ブリッジスレッドが直接読んでよいのは、`CurrentGameView`（不可分に読める）と `GetGameViewStackCopy()`（ロック付き）だけである。

| モーダル | 待ち方 | プローブの起点 | 検出 | 読み取り | 回答（UI スレッド） | 取り消し | Harmony |
|---|---|---|---|---|---|---|---|
| YesNo / Show（同期 PopupMessage） | `uiQueue.awaitTask` で設定してから `complete.Task.Wait()`（`XRL.UI/Popup.cs:823-909`）。`Popup.Show` → `ShowBlock` → `WaitNewPopupMessage`（`:658-670,1118-1142`）、`ShowYesNo`（`:2258-2276`） | `llmprobe:yesno` | UI: `CurrentGameView=="PopupMessage"`。`getWindow("PopupMessage")` が activeSelf かつ interactable。`commandCallback!=null` | `controller.menuData`、`bottomContextOptions`、`inputBox.text`（`Qud.UI/PopupMessage.cs:22-28`） | 下段ボタンは `OnActivateCommand(item)`、本文の選択肢は `OnSelect(item)`（`:926-944`）。先に Hide を呼ばない | Cancel の項目を `OnActivateCommand` に渡す | 不要 |
| AskString（WantsSpecificPrompt） | `AskStringAsync(...).Result`（`XRL.UI/Popup.cs:1440-1442`）。中身は `NewPopupMessageAsync` の複製 | `llmprobe:askspecific`、または CmdWish | UI: 視点が "DynamicPopupMessage"、スタックに "ModernPopup:AskString"。"PopupMessage #N" のうち activeSelf かつ interactable のもの | 複製の `inputBox.text`、本文 | `inputBox.text = 語` を設定してから `OnInputSubmit(語)`（`Qud.UI/PopupMessage.cs:946-958`） | Cancel の項目を `OnSelect` / `OnActivateCommand` に渡す | 不要 |
| PickOption / 会話 | `WaitNewPopupMessage` の `Task.Wait()`（`XRL.UI/Popup.cs:1740-1759`、`:1594`） | `llmprobe:pickoption`、`llmprobe:conv`（会話の選択肢がクエストなどの Popup を出すと、会話の上に同期 PopupMessage が重なる） | UI: 同期 PopupMessage と同じ。会話はスタックに "Conversation"（`XRL.UI/ConversationUI.cs:377`） | `menuData`（`option:i`）。会話は `ConversationUI.CurrentNode` と `CurrentChoices` も読む | `OnSelect(menuData[i])` | Cancel の項目（AllowEscape のとき） | 不要 |
| AskNumber（キーボード） | `AskNumberAsync(...).Result`（`XRL.UI/Popup.cs:1198-1205`）。キーボードでは `NewPopupMessageAsync(..., inputDefault: num, askingNumber:true)`（`:1349-1354`）。Cancel なら null、それ以外は `Convert.ToInt32(item.text)` | `llmprobe:asknumber` | UI: スタックに "ModernPopup:AskNumber"（`:1343-1345`）と、アクティブな複製 | 複製の `inputBox.text` | `inputBox.text` を設定してから `OnInputSubmit` | Cancel | 不要 |
| PickItem（3 個） | `PickGameObjectScreen.show(...).Result`（`XRL.UI/PickItem.cs:317-327`） | `llmprobe:pickitem` | UI: `CurrentGameView=="PickGameObject"`（`Qud.UI/PickGameObjectScreen.cs:233`）で、instance が表示中 | `instance.listItems`（`.go`、`.category`。`:49`） | `instance.HandleSelectItem(listItems[i])`（`:577-592`。public） | `instance.Cancel()`（`:512-517`） | 不要 |
| PickDirection | ゲームスレッドの `Keyboard.getvk` ループ（`XRL.UI/PickDirection.cs:28-56`） | `llmprobe:pickdir` | `CurrentGameView=="PickTarget"` かつ `PickTargetWindow.currentMode==PickDirection`（`:30-31`）。UI: `_ActiveGameView==CurrentGameView && !bViewUpdated` | `PickTargetWindow.currentText`（`:44-47`） | `Keyboard.PushMouseEvent("LeftClick", x, y)` で隣のセルを指す（`:100-122`）。自分自身は `PushCommand("CmdTargetSelf")` | `PushMouseEvent("RightClick")`（`:102-106`） | 不要 |
| PickTarget | ゲームスレッドの `getvk` ループ（`XRL.UI/PickTarget.cs:378-381,791`） | `llmprobe:picktarget` | `CurrentGameView=="PickTarget"` かつ `currentMode==PickCells`。UI: `_ActiveGameView==CurrentGameView && !bViewUpdated` | `currentText` と対象セル | `PointerOver` をセル x,y に積み（最初の 1 回は位置を動かさない。`:794-807`）、その後 `LeftClick`（`:965`）。範囲外や不可視なら、`Popup.ShowFail` が上に重なる（`:967-975`） | `RightClick` または `Command:CmdTargetSelf`（`:800-812`） | 不要 |
| 取引 | `TradeScreen.show(...).Result`（`XRL.UI/TradeUI.cs:456-458`） | `llmprobe:trade` | UI: `CurrentGameView=="ModernTrade"`（`Qud.UI/TradeScreen.cs:462`） | 取引ファミリーに任せる | 申し出の手順（`HandleOfferTrade`、`:754`）は未読なので取引ファミリーに任せる | `instance.Cancel()`（`Qud.UI/TradeScreen.cs:874-880`） | 不要（取消は確定。申し出は未確定） |
| StatusScreens | `StatusScreensScreen.show(...).Result`（`XRL.UI/Screens.cs:80`） | `llmprobe:status`（ModernCharacterSheet=Yes が必要。`XRL.UI/Screens.cs:45`） | UI: `CurrentGameView=="StatusScreensScreen"`（`Qud.UI/StatusScreensScreen.cs:141`） | 各タブ（該当ファミリー） | ― | `instance.Exit()`（`:225-237`） | 不要 |

## 6. 主張一覧

| ID | 主張 | 根拠 | 確度 | 実機でしか分からないか |
|---|---|---|---|---|
| C-F6-threads-hooks-01 | `uiQueue.executeTasks` は `GameManager.OnUpdate` の中、`bThreadFocus` の検査（`Sleep(250)` で return する）より前で呼ばれる。したがって、Update が回っている限り、フォーカスが無くても uiQueue は毎フレーム実行される | `GameManager.cs:2899,2958-2963,3108-3113`、`QupKit/BaseGameController.cs:31-34` | high | no |
| C-F6-threads-hooks-02 | `executeTasks` は、呼び出し時点の件数だけを処理する。実行中に自分を積み直したタスクは次の呼び出しで走るので、uiQueue の自己積み直しは 1 フレームに 1 回の UI ティックになる | `QupKit/ThreadTaskQueue.cs:33-75,157-176` | high | no |
| C-F6-threads-hooks-03 | uiQueue / gameQueue のタスクが投げた例外は、`ThreadTaskQueueEntry.Execute` が捕まえて `XRLCore.LogError` に記録する。キューは止まらず、`queueTask` / `awaitTask` の呼び出し元には伝わらない。例外を受け取れるのは `executeAsync` の Task だけである | `QupKit/ThreadTaskQueueEntry.cs:30-45`、`QupKit/ThreadTaskQueue.cs:77-100,135-155`、`XRL.Core/XRLCore.cs:3383-3391` | high | no |
| C-F6-threads-hooks-04 | `awaitTask` は、呼び出し元が threadContext 以外なら `ManualResetEvent.WaitOne()` でタイムアウトなしに待つ。UI スレッドが回らなければ、ブリッジスレッドは永久に止まる | `QupKit/ThreadTaskQueue.cs:135-155` | high | no |
| C-F6-threads-hooks-05 | `ThreadTaskQueue.poolEntry` はロックなしで `taskPool` に積み、`queueTask` は `lock(taskQueue)` の中で `taskPool` から取り出す。実行側はこのロックを取らないので、別スレッドからの `queueTask` は `taskPool` で競合しうる | `QupKit/ThreadTaskQueue.cs:23-26,157-176`、`QupKit/ThreadTaskQueueEntry.cs:43-44` | high | no |
| C-F6-threads-hooks-06 | gameQueue を回すのは、CoreThread 上の `RenderBase`（PlayerTurn の反復ごと）、`GetNextKey(pumpActions:true)`、Look だけである。ゲームスレッドが Modern のポップアップの `Task.Wait` / `.Result` で止まっている間は回らない | `XRL.Core/XRLCore.cs:2368,2373,2600-2605`、`ConsoleLib.Console/Keyboard.cs:1033-1041`、`XRL.UI/Popup.cs:906-909` | high | no |
| C-F6-threads-hooks-07 | gameQueue に常にタスクがあると、`GetNextKey(pumpActions:true)` が `KeyEvent.WaitOne(20)` を飛ばして空回りする。gameQueue での自己積み直しは避ける | `ConsoleLib.Console/Keyboard.cs:1015-1041` | high | no |
| C-F6-threads-hooks-08 | フォーカスが無いと、ゲームスレッドは PlayerTurn のループの先頭で `while(!GameManager.focused) Sleep(200)` に入って止まる。`OnApplicationFocus` が `bThreadFocus` と `focused` の両方を書く | `XRL.Core/XRLCore.cs:735-740`、`GameManager.cs:1920-1924` | high | no |
| C-F6-threads-hooks-09 | `GameManager.focused` が false から true に変わると、`Keyboard.ClearInput` と `ClearMouseEvents` が走り、積んであった入力は消える。フォーカスの書き直しは入力を積む前に行う | `GameManager.cs:404-427` | high | no |
| C-F6-threads-hooks-10 | `Application.runInBackground` は `OptionMusicBackground`（`Options.MusicBackground`）に従い、`Options.UpdateFlags` が積む uiQueue タスクの中で設定される | `XRL.UI/Options.cs:66-67,1159-1169,1273,1410,1445-1453` | high | no |
| C-F6-threads-hooks-11 | ビュー・スタックの変更は `lock(GameViewStack)` の中で行われ、`GetGameViewStackCopy()` がロック付きでコピーを返す。PlayerTurn は反復ごとにロックなしで `CurrentGameView="Stage"` を代入する。したがって別スレッドは `CurrentGameView` を単一の参照として読めるが、確定の判定は UI ティックで行う | `GameManager.cs:240,453-484,1441-1571`、`XRL.Core/XRLCore.cs:741` | high | no |
| C-F6-threads-hooks-12 | `_ActiveGameView != CurrentGameView || bViewUpdated` のフレームに、UI スレッドの OnUpdate が `ResetInput`（→`Keyboard.ClearInput`）と `UpdateView` を呼ぶ。これは同じ OnUpdate の中で `uiQueue.executeTasks` より後に走る。したがって getvk 系のモーダル（PickDirection / PickTarget）への入力は、`_ActiveGameView==CurrentGameView && !bViewUpdated` を確かめてから積む必要がある | `GameManager.cs:248,1436-1439,1573-1582,2963,3172-3183` | high（順序）/ 前提が十分かは medium | yes |
| C-F6-threads-hooks-13 | `PushGameView` / `PopGameView` は `ControlManager.ResetInput` を呼び、それが `Keyboard.ClearInput` を呼ぶ。モーダルが開く前に積んだ入力は、モーダルに届く前に消える | `GameManager.cs:1493-1525`、`ControlManager.cs:1491-1494`、`ConsoleLib.Console/Keyboard.cs:877-891` | high | no |
| C-F6-threads-hooks-14 | PlayerTurn の入口の `ClearMouseEvents(LeaveMovementEvents:true)` は、移動系以外の `Command:` イベントを捨てる。`PushCommand` はゲームスレッドが PlayerTurn のループに入ってから積む。BeginPlayerTurn のコールバックはこの消去より前に走るので、そこから積んだコマンドは捨てられる。EndPlayerTurn のコールバックから積めば読まれる | `XRL.Core/XRLCore.cs:690-693,734-735,2355-2359`、`ConsoleLib.Console/Keyboard.cs:893-924,723-726` | high | no |
| C-F6-threads-hooks-15 | `bCapInputBuffer`（OptionCapInputBuffer）が有効だと、`PushKey` はキューが 3 件以上、`PushMouseEvent` / `PushCommand` はキューが 3 件以上のときに黙って捨てる | `ConsoleLib.Console/Keyboard.cs:777-796,825-849`、`XRL.UI/Options.cs:1279-1286` | high | no |
| C-F6-threads-hooks-16 | `windowsByName` はロックの無い Dictionary で、UI スレッドの `copyWindow` / `createWindow` / `DestroyWindow` が書き換える。`copyWindow` は `Instantiate` を呼ぶ。複製は解放後も非アクティブのまま `windowsByName` に残る。ウィンドウの列挙と状態の読み取りは uiQueue の中で行う | `Qud.UI/UIManager.cs:25,134-145,299-354`、`XRL.UI/Popup.cs:759-760` | high（競合の存在）/ Unity の API が別スレッドで例外になるかは medium | no |
| C-F6-threads-hooks-17 | `PopupMessage.Hide` は raycaster と interactable を切り、`onHide` を同期で呼ぶが、canvas と active は 2 フレーム後まで残る。表示中の判定は `activeSelf && canvasGroup.interactable` で行い、`Visible` は使わない | `Qud.UI/PopupMessage.cs:968-981,1076-1104`、`Qud.UI/WindowBase.cs:28-46,197-218` | high | no |
| C-F6-threads-hooks-18 | `[ModSensitiveCacheInit]`（`[HasModSensitiveStaticCache]` クラス）は起動時に UI スレッドの AwakeRoutine から、ゲームスレッドの起動前に呼ばれ、hotload のたびにも呼ばれる。フィールドのリセットはメソッドの呼び出しより先に行われる | `GameManager.cs:852,868,912,3146-3150`、`XRL/ModManager.cs:340-371,661`、`XRL.Core/XRLCore.cs:575-577` | high | no |
| C-F6-threads-hooks-19 | XRLCore のターン・コールバックのリストは `[ModSensitiveStaticCache(true)]` で、hotload で空になる。Begin は PlayerTurn の入口で呼ばれる。End（Single:false）は PlayerTurn のループの反復ごと（待機も含む）に、ゲームスレッドで呼ばれる。ゲーム自身も `[ModSensitiveCacheInit]` の中で登録している | `XRL.Core/XRLCore.cs:40,251-265,604-636,682-693,2350-2359,2376-2386`、`Qud.UI/NearbyItemsWindow.cs:16,53-64` | high | no |
| C-F6-threads-hooks-20 | PlayerTurn（したがって CmdWish → AskWish）は CoreThread で走る。`runPlayerTurnOnUIThread` への書き込みは false だけで、`runWholeTurnOnUIThread` は増やされない | `XRL.Core/XRLCore.cs:1883-1885,2346,2353,2401`、`GameManager.cs:372,384,603-613`、`XRL.Core/ActionManager.cs:758-762,1589-1594` | high | no |
| C-F6-threads-hooks-21 | wish ハンドラ（`[HasWishCommand]` / `[WishCommand]`）は、ゲームスレッドから呼ばれればゲームスレッドで走り、`Popup.ShowYesNo` / `PickOption` などを同期で呼べる。string 引数のハンドラは `^cmd(?::|\s+)(.*)$` に一致する。ゲーム自身のハンドラも同じ使い方をしている | `XRL.Wish/WishManager.cs:40-85,106-165`、`XRL.Wish/MutationBGoneWishHandler.cs:11-32`、`XRL.World.Capabilities/Wishing.cs:45-49` | high | no |
| C-F6-threads-hooks-22 | `WaitNewPopupMessage` は、UI スレッドから呼ばれると async の経路に入って待たずに戻る。したがって、プローブの Popup 呼び出しはゲームスレッド（gameQueue か EndPlayerTurn コールバック）から行う | `XRL.UI/Popup.cs:801-826` | high | no |
| C-F6-threads-hooks-23 | mod は Roslyn でメモリ上にコンパイルされる。Harmony の `PatchAll` は、アセンブリに `HarmonyAttribute` 付きの型があるときだけ呼ばれる。Harmony の属性を使わない mod は、Harmony 2.2.2 の arm64 での失敗の経路に入らない | `XRL/ModManager.cs:116-135`、`XRL/ModInfo.cs:755-790,845-861` | high | no |
| C-F6-threads-hooks-24 | ゲーム自身が、`ModManager.ResolveType`（mod のアセンブリも探す）で解決した型を `UIManager.createWindow` の中で `AddComponent(Type)` している。mod の MonoBehaviour を AddComponent する経路は想定されている。ただし、メモリ上のアセンブリの MonoBehaviour に Update が届くかは Unity の挙動である | `XRL/ModManager.cs:296-320`、`XRL.CharacterBuilds/AbstractEmbarkBuilderModule.cs:385-405`、`XRL.CharacterBuilds/EmbarkBuilderModuleWindowDescriptor.cs:60-72`、`Qud.UI/UIManager.cs:299-321` | medium | yes |
| C-F6-threads-hooks-25 | `[PlayerMutator]` は新規ゲームの embark 時に、CoreThread の `_Start` → `NewGame` → `EmbarkInfo.bootGame` → `QudGameBootModule.bootGame` の中で呼ばれる。`[CallAfterGameLoaded]` はセーブのロード時だけ、`XRLGame.LoadGame` の中から呼ばれる | `XRL.Core/XRLCore.cs:3553-3563,3585,3775,2837-2860`、`XRL.CharacterBuilds/EmbarkInfo.cs:38-43`、`XRL.CharacterBuilds.Qud/QudGameBootModule.cs:229,303-307`、`XRL/XRLGame.cs:1653-1658,1954`、`XRL/ModManager.cs:374-386` | high | no |
| C-F6-threads-hooks-26 | ゲームスレッドの SynchronizationContext は素の `SynchronizationContext` である。`await The.GameContext` をしてもゲームスレッドには戻らない（素の Post はスレッドプールに投げる）。`The.UiContext` は、AwakeRoutine で取った UI スレッドのコンテキストである | `XRL.Core/XRLCore.cs:3553-3559`、`XRL/The.cs:41-43`、`GameManager.cs:869`、`XRL/SynchronizationContextAwaiter.cs:7-26` | high（コンテキストの種類）/ Post の行き先は .NET の挙動 | no |
| C-F6-threads-hooks-27 | `NewGame` と `XRLCore.Reset` は `gameQueue.clear()` を呼ぶ。新規ゲームの前に積んだゲームスレッドの依頼は消える | `XRL.Core/XRLCore.cs:508-519,2837-2839`、`QupKit/ThreadTaskQueue.cs:18-21` | high | no |
| C-F6-threads-hooks-28 | `MetricsManager.LogInfo` は `Debug.Log("INFO - "+msg)` を出し、`XRLCore.LogError(Exception)` は `Debug.LogError("ERROR:"+ex)` を出す | `MetricsManager.cs:411-419`、`XRL.Core/XRLCore.cs:3383-3386` | high | no |

## 7. 実機でしか分からないこと

1. macOS のスタンドアロンで `runInBackground=false`（OptionMusicBackground=No）のとき、フォーカスを失うと Unity の Update が止まるか。止まるなら、UI ティックも回答もすべて止まる。プローブのプロファイルでは OptionMusicBackground=Yes にして、両方の場合を測る。
2. フォーカスが無い間の約 4 fps（`Sleep(250)`）で、回答の遅延が許容できるか。`bThreadFocus` を UI ティックで毎フレーム true に書き直せば、この Sleep と PlayerTurn のフォーカス待ちを避けられるか。`OnApplicationFocus` と書き合いになるので、書いたときの副作用を測る。
3. `_ActiveGameView==CurrentGameView` を確かめてから積んだ PushMouseEvent が、PickDirection / PickTarget に確実に届くか。ほかに入力を消す箇所（たとえば TutorialManager のゲート）が無いか。
4. PickTarget の PointerOver が、1 回目は位置を動かさないという挙動（`XRL.UI/PickTarget.cs:794-807` の flag3）が、そのとおり再現するか。
5. Roslyn でメモリ上にコンパイルした mod の `MonoBehaviour` を `AddComponent` したとき、Update が呼ばれるか（第二案の検証。第一案の UI ティックだけで足りるなら不要）。
6. ブリッジスレッドから `UnityEngine.Debug.Log` を呼んでも安全か。`The.UiContext.Post` がブリッジスレッドから使えるか。
7. `gameQueue` に積んだ wish タスクが RenderBase の中で Popup を開いたとき、入れ子になった `RenderBase` / `executeTasks` が問題を起こさないか。

## 8. 未解決の問い

- `IGameSystem` を `RequireSystem` で登録するとセーブに書き込まれるか。そのセーブを mod なしでロードするとどうなるか。本書では確認していない。
- UnitySynchronizationContext の Post が、UI フレームのどの時点で実行されるか。uiQueue と比べて、UpdateView の前か後か。入力を消す処理との順序に影響する。
- TradeScreen で申し出を確定する手順（`HandleOfferTrade`、`Qud.UI/TradeScreen.cs:754`）。取引ファミリーに任せる。
- AskNumber のゲームパッドの経路（`AskNumberScreen`、`XRL.UI/Popup.cs:1323-1338`）が、キーボードしか無い環境でも選ばれることがあるか（`ControlManager.activeControllerType` の初期値）。
- TutorialManager のゲート（`AllowPushKey`、`AllowMouseEvent`、`AllowSelectedPopupCommand`）が、新規の Joppa 開始（チュートリアルなし）でどの値を返すか。
