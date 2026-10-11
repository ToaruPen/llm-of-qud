# F7-observation: Modern UI 表示中に legacy 相当テキストを合成する

対象ビルド: 2.0.211.56（ILSpy 逆コンパイル、`/Users/sankenbisha/Dev/coq-decompiled_stable`）。以下の引用 `path:line` は、すべてこのソースルートからの相対パスである。本書の作業中に `sed -n` / `grep -n` で表示した範囲だけを引用している。

## 1. 目的

画面には Modern UI を出したままにする。そのうえで、エージェントが「見る」べき面ごとに、次の三点を静的に確定する。

1. Harmony を使わずに読めるデータ源はどれか（型・メンバー・行）。
2. それをどのスレッドで読んでよいか。
3. legacy の文字画面と同等のテキストに、どう整形するか。

結論を先に書く。**観測のために Harmony が必須になる面は、静的には見つからなかった。** ただし一つだけ条件がある。PickTarget のカーソル位置は、ローカル変数にしかない。これは、ブリッジ側から `PointerOver` のマウスイベントでカーソルを置く方法が実機で成り立つ場合に限って、既知になる（C-F7-observation-11、runtime_only）。

- **代替策。** 成り立たなければ、`CurrentBuffer` に写る照準の imposter（`TargetReticle`）を探す（`UseImposters` のときだけ。C-F7-observation-26）。
- **Harmony に頼る場合。** それでも駄目なら Harmony が要る。`x` / `y` はローカル変数なので、prefix や postfix では届かない。`PickTarget.ShowPicker`（`XRL.UI/PickTarget.cs:378`）の transpiler で、`x` / `y` を static に書き出す必要がある。

また、読む時点とスレッドの選び方には制約がある。モーダルの待機中は `gameQueue` が回らない（C-F7-observation-03）。また、一部の処理はゲームスレッド以外（スレッドプール）でゲームロジックを走らせる（C-F7-observation-14）。

## 2. 対象一覧

| 記号 | 面 | 主な入口 |
|---|---|---|
| a | ポップアップ（Show / ShowBlock / ShowYesNo / YesNoCancel / PickOption / Popup.PickGameObject / AskString / AskNumber） | `XRL.UI/Popup.cs` → `Qud.UI/PopupMessage.cs` |
| b | 会話 | `XRL.UI/ConversationUI.cs` → `Popup.ShowConversation` |
| c | ピッカー（PickGameObjectScreen、PickTarget、PickDirection） | `XRL.UI/PickItem.cs`、`XRL.UI/PickTarget.cs`、`XRL.UI/PickDirection.cs` |
| d | 取引 | `XRL.UI/TradeUI.cs` → `Qud.UI/TradeScreen.cs` |
| e | ステータス画面（能力値、スキル、変異、装備、所持品、クエスト、日誌） | `XRL.UI/Screens.cs` → `Qud.UI/StatusScreensScreen.cs`。代わりに XRL の API を直接読む |
| f | メッセージログ | `XRL.Messages/MessageQueue.cs`、`Qud.UI/MessageLogWindow.cs` |
| g | HUD（HP、能力値、効果、アビリティ、クールダウン、時刻、重量、ゾーン名、ターゲット） | `Qud.UI/PlayerStatusBar.cs`、`Qud.UI/AbilityBar.cs`、`XRL.UI/Sidebar.cs` |
| h | 地図 | `ConsoleLib.Console/TextConsole.cs`、`ConsoleLib.Console/ConsoleChar.cs`、`XRL.Core/XRLCore.cs` |
| i | ツールチップ、Look のテキスト、Alt ハイライト | `XRL.UI/Look.cs`、`XRL.World/Zone.cs` |
| j | qud-accessibility が Harmony で拾っていた面（本、端末、スクローラーの選択など） | `docs/exploration/02-prior-art.md` §1.12.1 の表 |

## 3. スレッドモデル（読み取りの三段階）

以下の議論の前提になるので、先にまとめる。

### 3.1 どのスレッドから何を読めるか

- **(T1) 素の managed フィールド／static。** 参照の読み取りは原子的なので、ブリッジスレッドから直接読んでよい。整合性は保証されないので、値はヒントとして扱う。
  - 例: `GameManager.__CurrentGameView`（`GameManager.cs:453-482` の getter は素の文字列を返す）、`PickTargetWindow.currentText` / `currentMode`（`Qud.UI/PickTargetWindow.cs` の `public static`。grep で `:17`, `:19`）、`UITextSkin.text`（`XRL.UI/UITextSkin.cs:54`、`public string text`）、`ConversationUI.CurrentNode` などの static（`XRL.UI/ConversationUI.cs:135-157`）。
- **(T2) Unity のプロパティとコンポーネントの状態。** UI スレッドでしか読めない。
  - 例: `inputBox.text`（TMP）、`gameObject.activeInHierarchy`、`canvas.enabled`、`canvasGroup.interactable`（`Qud.UI/WindowBase.cs:28-45,180-218`）。
  - UI スレッドへは `GameManager.Instance.uiQueue.executeAsync` / `queueTask` で渡す（`QupKit/ThreadTaskQueue.cs:77-100,157`）。`uiQueue` は毎フレーム `GameManager.Update` から `executeTasks()` される（`GameManager.cs:2963`）。
- **(T3) ゲームオブジェクトの状態（Statistics、Effects、Inventory、DisplayName など）。** 原則としてゲームスレッドで読む。ただし例外がある。
  - **例外（エンジン自身の先例）。** ゲームスレッドが `.Result` / `Task.Wait` で止まっている間は、エンジン自身が UI スレッドからゲーム状態を読む。
    - `TradeScreen.showScreen` は `await The.UiContext` の後に `BeforeShow` → `UpdateViewFromData` → `UpdateTotals` と進み、`The.Player.GetCarriedWeight()` を UI スレッドで呼ぶ（`Qud.UI/TradeScreen.cs:465-470,665-686,727-733`）。
    - `PickGameObjectScreen` も、`await The.UiContext` の後で `GetInventoryCategory()` を呼ぶ（`Qud.UI/PickGameObjectScreen.cs:231-251,270-300`）。
  - したがって、**モーダル表示中のゲーム状態の読み取りは、`uiQueue.executeAsync` で UI スレッドにまとめて行う**のが、エンジンと同じ流儀になる。

### 3.2 `gameQueue` はモーダル中に回らない

ソース全体を grep すると、`gameQueue.executeTasks()` を呼ぶ場所は四つある。

1. `pumpActions` つきの getvk 待機（`ConsoleLib.Console/Keyboard.cs:1017-1041`）。これを使うのは PlayerTurn の入力待ち（`XRL.Core/XRLCore.cs:3938`）などである。
2. コアスレッド上の `RenderBase`（`XRL.Core/XRLCore.cs:2600-2605`）。
3. Looker のループ（`XRL.UI/Look.cs:658`）。
4. 同じく Looker（`XRL.UI/Look.cs:933`）。

本物の Look の最中なら、`gameQueue` 経由の読み取りは返ってくる。一方、Modern のモーダル待機（`Popup.cs:908` の `complete.Task.Wait()`、各画面の `.Result`）はどれにも当たらない。この間に積んだ `gameQueue` のタスクは、モーダルが閉じるまで走らない。したがって、**モーダル中の読み取りを `gameQueue` 経由で待つと、答えるまで返ってこない（実質ハング）。**

### 3.3 ゲームスレッド以外でゲームロジックが走る場所

次の三つがある。

- **`APIDispatch.RunAndWaitAsync`。** 中身を `Task.Run`（スレッドプール）で実行する（`XRL.UI.Framework/APIDispatch.cs:10-44,46-70`）。
  - 使っている場所: 取引のオファー（`Qud.UI/TradeScreen.cs:842-861`）、PickGameObject の Take All（`Qud.UI/PickGameObjectScreen.cs:445-472`）、端末（`Qud.UI/CyberneticsTerminalScreen.cs:68-90,279-335`）。
  - この中から出るポップアップ（たとえば `TradeUI.PerformOffer` の `ShowYesNo`。`XRL.UI/TradeUI.cs:1296-1390`）は、**プールスレッドを** `Task.Wait` で止める。
- **`AllowRenderMapBehind` 付きの `WaitNewPopupMessage`。** 待機中も 33ms ごとに `RenderBaseToBuffer` を呼ぶ（`XRL.UI/Popup.cs:897-904`）。これは可視・光マップを書き換え、AfterRender コールバックを発火させる（`XRL.Core/XRLCore.cs:2436-2465`）。
- **PickTarget のループ。** `kbhit` が偽なら `continue` して、描画を回し続ける（`XRL.UI/PickTarget.cs:408-412,786-790`）。

## 4. 各面の動作

### 4.1 ポップアップ（a）

#### 4.1.1 経路は二つある

- **同期経路 `WaitNewPopupMessage`。**
  - 非 UI スレッドから呼ばれた場合: `uiQueue.awaitTask` の中で、**単体の** `UIManager.getWindow("PopupMessage")` に `ShowPopup` し、`PushGameView("PopupMessage")` する（`XRL.UI/Popup.cs:824-829`）。呼び出し側は `complete.Task.Wait()` で止まる（`:908`）。
  - UI スレッドから呼ばれた場合: `NewPopupMessageAsync` に回る（`:804-822`）。
  - ShowBlock / Show、ShowYesNo、ShowYesNoCancel、PickOption、Popup.PickGameObject、ShowConversation がこの経路に乗る（`XRL.UI/Popup.cs:1138-1141,2258-2275,2371-2373,1709-1760,1520-1558,1594-1613`）。
- **非同期経路 `NewPopupMessageAsync`。**
  - 呼ぶとすぐ `PushGameView("DynamicPopupMessage")` し、`await The.UiContext` の後で `UIManager.copyWindow("PopupMessage")` の**複製**に `ShowPopup` する（`XRL.UI/Popup.cs:755-760`）。
  - AskString と AskNumber は、ゲームスレッドから `.Result` でこれを待つ（`XRL.UI/Popup.cs:1440-1442,1198-1200,1349,1396`）。
  - 複製の名前は `"PopupMessage #N"` で、`windowsByName` に登録される。`releaseCopy` は非アクティブにしてプールに戻すだけで、辞書からは消さない（`Qud.UI/UIManager.cs:323-352`）。

#### 4.1.2 読むフィールド（`Qud.UI/PopupMessage.cs:721-875`）

| 内容 | フィールド | 設定箇所 | 形式 |
|---|---|---|---|
| 本文 | `Message.text`（`UITextSkin`） | `:777` | `"{{y|" + message + "}}"` |
| タイトル | `Title.text` | `:800`、`:805` | 空、または `"{{W|" + title + "}}"` |
| 文脈タイトル（会話の話者、アイコン付き PickOption のタイトル） | `contextText.text` | `:855` | 渡された文字列そのまま |
| 本文の選択肢 | `controller.menuData`（`List<QudMenuItem>`） | `:781` | `QudMenuItem.text/command/hotkey`（`Qud.UI/QudMenuItem.cs:8-44`） |
| 下段ボタン | `controller.bottomContextOptions` | `:782` | 同上（`Qud.UI/QudBaseMenuController.cs:65`） |
| 入力欄 | `inputBox.text`（TMP。T2） | `:814` | 初期値 `inputDefault` |
| 識別子 | `PopupID`、static の `lastPopupID` | `:771`、`:874` | 会話では `"Conversation:" + Title`（`XRL.UI/Popup.cs:1613`） |
| 選択中の位置 | `controller.selectedOption` | `Qud.UI/QudBaseMenuController.cs:81` | int |

- **タイトルの置き場所は一定しない。** PickOption は、アイコン（`Context` か `IntroIcon`）があればタイトルを `contextTitle` に、なければ `title` に入れる（`XRL.UI/Popup.cs:1716-1758`）。会話は `title` を空にして、話者を `contextTitle` に入れる（`:1613`）。したがって `Title.text` と `contextText.text` の両方を読む。
- **選択肢の書式。**
  - PickOption: `"{{W|[c]}} {{y|…}}"`、ホットキーがなければ `"    {{y|…}}"` か `"{{y|…}}"`（`XRL.UI/Popup.cs:2011-2045`）。
  - 会話: `"{{w|[n]}} " + 本文 + "\n\n"`（`:1589`）。本文にも `"\n\n"` が付く（`:1594`）。
  - どの選択肢も `command = "option:" + Index` を持つ（`:2011-2045`、`:1589-1592`）。**選択肢の同定は、リスト上の位置ではなく `command` で行う。**
- **ボタンの書式。**
  - ボタンの `text` は `"{{y|Yes}}"` などで、`command` は `Yes` / `No` / `Cancel` / `keep` / `Accept` / `Copy` / `Look` / `Color`（`Qud.UI/PopupMessage.cs:44-230`）。
  - `buttons=null` の Show / ShowBlock は `PopupMessage.SingleButton` になる（`XRL.UI/Popup.cs:764`）。これは `command="Accept"`、`hotkey="Accept,Cancel"` の 1 個で、デスクトップでは text が `"{{W|press [<キー>]}}"` に差し替わる（`Qud.UI/PopupMessage.cs:331-362`）。**Cancel の command を持たない**ので、答えも取り消しも `OnActivateCommand(bottomContextOptions[0])` になる。
  - デスクトップの `CancelButton` は、キー表記つきの `"{{W|[Esc]}} Cancel"` 形に差し替わる（`:255-285`）。
  - 会話の取引ボタンの text は `"{{[W|" + キー + "]}} {{y|Trade}}"` で、括弧が制御部に食い込んでいる（`:693-713`）。`StripFormatting` を通すと `"[W|"` が制御部として消え、`"<キー>] Trade"` になる（`ConsoleLib.Console/ColorUtility.cs:470-530` の `GetNext`）。表示用の整形では `command` から組み直す。

#### 4.1.3 色マークアップの除去

- `ColorUtility.GetNext` は、`{{X|…}}` の制御部（`{{` から `|` まで）と `}}`、`&X` / `^X` を捨てる。`&&` と `^^` は 1 文字に戻す（`ConsoleLib.Console/ColorUtility.cs:470-530`）。
- **`string StripFormatting(string)` はブリッジスレッドから呼ばない。**
  - 共有の static `StripSB`（`:179`）を、lock の外で Clear / Append している（`:303-343`。lock はキャッシュの辞書にしか掛かっていない）。
  - ゲームスレッドも同じ関数を使う（例: `XRL.UI/TradeUI.cs:452-454`）ので、ブリッジから並行に呼ぶと競合する。
- **安全な代替。** `StripFormatting(ReadOnlySpan<char>, TextBuilder)`（`:2257-2275`）は、呼び出し側の出力バッファだけを使い、span 版の `GetNext`（`:2298-`）も static を触らない。
  - ブリッジ専用の `TextBuilder` を持ってこれを呼ぶか、`GetNext` と同じ規則の除去関数を mod 側に移植する。
  - `UITextSkin` 自身も span 版を使っている（`XRL.UI/UITextSkin.cs:110-116`）。
- **TMP のタグ（`<color=#…>`）はこの除去では消えない。** Modern 専用に組まれた文字列（AbilityBar の `"ACTIVE EFFECTS:"` など。`Qud.UI/AbilityBar.cs:293`）は、RTF 化する前の元の文字列を自前で組み直す。
- **入力欄の値は CP437 変換を通る。** 表示前は `Sidebar.FromCP437`、確定時は `Sidebar.ToCP437`（`XRL.UI/Popup.cs:761,784`）。

#### 4.1.4 検出

UI スレッドで `UIManager.instance.windowsByName.Values` を列挙し、`PopupMessage` を拾う。条件は次の 3 つ。

1. `gameObject.activeInHierarchy` が真。
2. `canvasGroup.interactable` が真。
3. `commandCallback != null || selectCallback != null`。

条件 2 の根拠: `WindowBase.Show` は `interactable=true` にし、`PopupMessage.Hide` は `interactable=false` にする（`Qud.UI/WindowBase.cs:197-218`、`Qud.UI/PopupMessage.cs:1083-1104`）。`Qud.UI/` 全体を grep すると、窓の `canvasGroup.interactable` を書くのは `WindowBase.cs:177,193,217` と `PopupMessage.cs:1096` だけである。残りのヒットは、ドラッグ中の別オブジェクトとボタンである。`canvasGroup` は public のプロパティ（`WindowBase.cs:48`）。`OnSelect` の後も `commandCallback` は残る（`:936-944`）。しかし直後の `Hide` で `interactable` が落ちるので、05 C03 で必要とされた「トークン」の代わりになる。

- 辞書は `copyWindow` が書き換える（`Qud.UI/UIManager.cs:337`）ので、列挙は UI スレッドで行う。
- ブリッジ側の粗い前段フィルタとして、T1 で読める `CurrentGameView` が `"PopupMessage"` か `"DynamicPopupMessage"` かを使える。会話中は `"Conversation"`（非ハード）の上に `"PopupMessage"` が積まれる（`XRL.UI/ConversationUI.cs:377`、`XRL.UI/Popup.cs:829`）。

#### 4.1.5 ログとの関係

`ShowBlock` は表示の前に本文をメッセージログへ送る（`XRL.UI/Popup.cs:1134-1137`）が、`ShowYesNo` の本体（`:2251-2330`）には `AddPlayerMessage` がない。ポップアップの本文は、ログではなくウィンドウから読む。

#### 4.1.6 AskNumber の分岐

`AskNumberAsync` は、`ControlManager.activeControllerType` がキーボードでなければ `AskNumberScreen` に分岐する（`XRL.UI/Popup.cs:1320-1337`）。レシピはキーボード前提で書き、実行時はこの値を確かめる。

### 4.2 会話（b）

- **Modern のループ。** `while (CurrentNode != null) { Prepare(); if (UseNewPopups) Render(); }`（`XRL.UI/ConversationUI.cs:418-428`）。`Render` は `Popup.ShowConversation` を呼び、戻り値で分岐する（`:514-537`）。
  - `-1`: Escape。
  - `-2`: `Trade.ShowScreen()`。
  - `-3`: Look。
  - それ以外: `Select(n)`。
- **ゲームスレッドが書く static。** `Speaker` / `Listener` / `CurrentConversation` / `CurrentNode` / `CurrentChoices` / `SelectedChoice`（`:135-157`）。モーダル中はゲームスレッドが止まっているので、ブリッジから T1 で読める。
  - ただし `Choice.GetDisplayText` はイベントを経由しうるので、ブリッジから呼ぶことは勧めない。
  - 表示された文字列そのものは `PopupMessage.menuData` にあるので、そちらを正とする。
- **話者名。** `GetTitle()` は `"{{W|" + Speaker.DisplayName + "}}"` を返す（`:474-487`）。これが `contextText` に入る（`XRL.UI/Popup.cs:1613`）。
- **下段ボタンの並び。** `Look`（常に先頭）、`trade`（取引可のとき）、`Cancel`（`AllowEscape` のとき）（`XRL.UI/Popup.cs:1573-1582`）。
- **検出。** `PopupID.StartsWith("Conversation:")`、あるいは `lastPopupID` を使う。

### 4.3 PickGameObjectScreen（c）

- **待ち方。** `PickItem.ShowPickerInternal` の Modern 分岐は、`PickGameObjectScreen.show(...).Result` でゲームスレッドを止める（`XRL.UI/PickItem.cs:269-330`）。
- **showScreen の中身**（`Qud.UI/PickGameObjectScreen.cs:213-262`）。`rawGameObjects` に候補を入れ、`await The.UiContext` の後で `PushGameView("PickGameObject")`、`titleText.SetText(Title)`、`BeforeShow` を行い、`menucomplete.Task` を待つ。
- **読むもの。**
  - `rawGameObjects`（`:47`）。元の候補一覧。
  - `listItems`（`:49`）。`PickGameObjectLineData` の並びで、`type`（Category か Item）、`category`、`go` を持つ（`:317-335`）。
  - `usedCategories` / `categoryCollapsed`（`:55-59`）。
  - `titleText.text`（`:65`）。
  - 名前と分類は `go.GetDisplayName(...)` と `GetInventoryCategory()` で得る。UI スレッドで呼ぶのが先例に沿う（`:286-300`）。
- **答え方（UI スレッド）。** `HandleSelectItem(listItems[i])` に `type==Item` の行を渡すと、`menucomplete.TrySetResult(new Result{item=go})` になる（`:577-594`）。Category の行を渡すと、折りたたみが切り替わるだけである。
- **取り消し。** `Cancel()`（`:512-517`）。
- **注意。** GetItemDialog では、選択の後に `EquipmentAPI.TwiddleObject` が続けて別のメニューを開く（`XRL.UI/PickItem.cs:283-301`）。

### 4.4 PickTarget / PickDirection（c）

どちらも**ゲームスレッドの getvk ループ**で、Modern の `PickTargetWindow` は表示を担うだけである。

- **ビューとモード。** 両者とも `PushGameView("PickTarget")` する。`PickTargetWindow.currentMode` は、PickCells（`XRL.UI/PickTarget.cs:380-381`）、PickField（`:86-87`）、PickDirection（`XRL.UI/PickDirection.cs:30-31`）のどれか。
- **Modern の案内文。** `PickTargetWindow.currentText` に入る（`XRL.UI/PickTarget.cs:747-750`、`XRL.UI/PickDirection.cs:44-47`）。`Label` を含む。
- **入力。** `Keyboard.PushKey` / `PushMouseEvent`（`ConsoleLib.Console/Keyboard.cs:772-830`）は、このループの getvk にそのまま届く。
  - 確定: `F` / `Space` / `Enter`、または `"Command:CmdFire"`、`"LeftClick"`（`XRL.UI/PickTarget.cs:965-982`）。
  - 取り消し: `NumPad5` / `Escape`、または `"Command:CmdTargetSelf"`（`:809-812`）。
  - 選んだマスが範囲外か不可視だと、確定の代わりに `Popup.ShowFail` の同期ポップアップが出る（`:967-978`）。
- **カーソル位置。**
  - `x` / `y` はローカル変数で、初期値は `StartX` / `StartY`（`:400-401`）。`Sidebar.CurrentTarget` が同じゾーンにいれば、その位置になる（`:391-398`）。
  - `Buffer.focusPosition` に書かれるのは、テンキーで動かして `flag4=false` になった後だけである（`:782-785,817-820`）。
  - `DrawBuffer` → `CurrentBuffer.Copy` で `focusPosition` も写る（`ConsoleLib.Console/TextConsole.cs:149-161`、`ConsoleLib.Console/ScreenBuffer.cs:317`）。したがって、public の `TextConsole.BufferCS`（`TextConsole.cs:29`）を lock すれば、どのスレッドからでも読める。
  - ロック時はテンキーの移動が `GetObjectListCone` で対象に飛ぶ（`XRL.UI/PickTarget.cs:821-835`）。キー入力から位置を算術で追うことはできない。
  - **Harmony なしで位置を確定する方法。** `PointerOver` を 2 回送る。1 回目は `flag3` を下ろすだけで、2 回目で `x,y = CurrentMouseEvent.x,y` になる（`:792-799,804-807`）。ブリッジが置いた座標なので、位置は既知になる。
  - ただし、実マウスのホバーも `PointerOver` を生む可能性がある。`PushMouseEvent` は、`MouseEventQueue.Count > 2 && bCapInputBuffer` のとき捨てられる（`ConsoleLib.Console/Keyboard.cs:825-830`）。
- **ゲームスレッドで読む足場。** PickTarget は毎反復 `RenderMapToBuffer` を呼び（`XRL.UI/PickTarget.cs:412`）、そこで `AfterRenderCallbacks` が回る（`XRL.Core/XRLCore.cs:2407-2433`）。mod のコールバックの中なら、ゲームスレッドで Look のテキストなどを計算できる。PickDirection はキー 1 回ごとに 1 回だけ描く（`XRL.UI/PickDirection.cs:38-54`）。

### 4.5 取引（d）

- **待ち方と前処理。**
  - `TradeUI.ShowTradeScreen` は、前処理の後で Modern なら `TradeScreen.show(...).Result` を待つ（`XRL.UI/TradeUI.cs:456-458`）。
  - 前処理は、`_Trader` の設定、`GetTradePerformanceEvent`、`Objects[0/1]` の `GetObjects`、`UpdateTotals`（`:380`、`:411`、`:433-437`、`:447-449`）。
- **TradeScreen が持つデータ。**
  - `ClearAndSetupTradeUI` が、自前の `tradeEntries[0]`（商人側）と `tradeEntries[1]`（プレイヤー側）を作り直す（`Qud.UI/TradeScreen.cs:494-526`）。
  - public のフィールド: `tradeEntries`、`Totals`、`Weight`、static の `NumberSelected`、static の `Trader`、`CostMultiple`、`mode`、`ObjectSide` / `ObjectIndex`（`:41-89`）。
- **各行の値段。** `TradeUI.GetValue(go, traderInventory)` を `:0.00` で整形する（`Qud.UI/TradeLine.cs:473-483`）。`GetValue` は、`TraderInventory` を省くと `TradeUI.Objects` で側を判定する（`XRL.UI/TradeUI.cs:218-243`）。明示の bool を渡す。
- **合計と水。**
  - 合計は `"{{B|" + FormatPrice(Totals[0], CostMultiple) + " drams →}}"`。
  - 水は、商人とプレイヤーの `GetFreeDrams()`。
  - 重量は `carried + Weight[0] - Weight[1] - 水の重さ` と最大重量（`Qud.UI/TradeScreen.cs:727-743`）。
  - 差額は `TradeUI.CalculateTrade(Totals[0], Totals[1])`（`:842-845`）。
- **操作。**
  - 数量の設定は `setHowManySelected(go, n)`。プレイヤー側の重要品には `ConfirmUseImportantAsync` の確認ポップアップが出る（`:275-296`）。
  - オファーは `HandleMenuOption(OFFER_TRADE)`（`:754-757,838-862`）。`PerformOffer` はプールスレッドで走り、その中から `ShowYesNo` が出る（§3.3）。
  - 取り消しは `Cancel()`（`:874-880`）。

### 4.6 ステータス画面（e）

Modern の `StatusScreensScreen` は表示のためだけの画面で、ゲームスレッドを `.Result` で止める（`XRL.UI/Screens.cs:80,125`、`XRL.Messages/MessageQueue.cs:78-88`）。閉じるには `Exit()` を使う（`Qud.UI/StatusScreensScreen.cs:225-237`）。

エージェントはこの画面を開かず、PlayerTurn の時点で次の API をゲームスレッド（コールバックか `gameQueue`）で読む。

| 項目 | データ源 |
|---|---|
| 能力値 | `GameObject.Statistics`（`XRL.World/GameObject.cs:148`） |
| HP | `hitpoints` / `baseHitpoints`（`:1164`、`:1176`） |
| 効果 | `Effects`（`:556`） |
| 装備 | `Body`（`:132`）、`Body.GetEquippedObjects()`（`XRL.World.Parts/Body.cs:458`） |
| 所持品 | `Inventory.Objects` / `GetObjects()`（`XRL.World.Parts/Inventory.cs:21,524`） |
| アビリティ | `ActivatedAbilities`（`XRL.World/GameObject.cs:1203`） |
| スキル | `Skills.SkillList`（`XRL.World.Parts/Skills.cs:19`） |
| 変異 | `Mutations.MutationList`（`XRL.World.Parts/Mutations.cs:90`） |
| クエスト | `XRLGame.Quests` / `FinishedQuests`（`XRL/XRLGame.cs:145,148`） |
| 日誌 | `JournalAPI.GetKnownNotes(...)`（`Qud.API/JournalAPI.cs:233`）ほか |

### 4.7 メッセージログ（f）

- **登録と受け渡し。**
  - `MessageQueue.Add` は `Markup.Transform` した文字列を `Messages` に積み（`"!clear"` は積まない）、`XRLCore.CallNewMessageLogEntryCallbacks` を呼ぶ（`XRL.Messages/MessageQueue.cs:138-150`）。
  - mod は `XRLCore.RegisterNewMessageLogEntryCallback` で登録できる（`XRL.Core/XRLCore.cs:657-680`）。Modern のログ窓も同じコールバックを使い、`":: "` を付けて `uiQueue` に回す（`Qud.UI/MessageLogWindow.cs:94-112`）。**Harmony なしで、画面と同じ源から取れる。**
- **注意点。**
  - コールバックは、`Add` を呼んだスレッドで走る。プールスレッドも含む（§3.3）。受け手はスレッド安全なキューに積む。
  - コールバックのリストは `[ModSensitiveStaticCache(true)]` で、hotload のたびに空になる（`XRL.Core/XRLCore.cs:252-273`）。登録は init のたびに行う。
  - `"!clear"` はコールバックには届くが、履歴には残らない（`XRL.Messages/MessageQueue.cs:143-148`）。
- **間引き。** 履歴は `BeginPlayerTurn` で 2000 件を超えると先頭 100 件を捨てる（`:94-104`）。これは UI の種類に関係しない。Modern のログ窓の表示が別に切り詰めているかどうかは、本書では確認していない。

### 4.8 HUD（g）

- **PlayerStatusBar（Modern 専用の UGUI）。** 表示用の文字列を、**ゲームスレッドの** `XRLCore` Begin/End/PassedTen のコールバックで組み立てる（`Qud.UI/PlayerStatusBar.cs:273-278,310-420`）。
  - ゾーン名は `ParentZone.DisplayName`。
  - 能力値は `player.Statistics`。
  - 空腹と渇きは `Stomach.FoodStatus()/WaterStatus()`。
  - 重量と水は `GetCarriedWeight/GetMaxCarriedWeight/GetFreeDrams`。
  - 温度は `Physics.Temperature`。
  - 時刻は `Calendar.GetTime/GetDay/GetMonth`。
  - HP は `hitpoints/baseHitpoints`。Analgesia のときは `Strings.WoundLevel`。
  - mod は同じコールバック（`XRL.Core/XRLCore.cs:604-650`）を登録すれば、同じ値を同じスレッドで得られる。
- **AbilityBar。** `XRLCore.RegisterAfterRenderCallback` の中で組み立てる（`Qud.UI/AbilityBar.cs:218-222,286-420`）。
  - 効果は `Effect.GetDescription()` で、`SuppressInStageDisplay` のものは除く。
  - アビリティは `ActivatedAbilities.GetAbilityListOrderedByPreference()`。
  - ターゲットは `Sidebar.CurrentTarget` の表示名、`Strings.WoundLevel`、`Description.GetFeelingDescription/GetDifficultyDescription`。
  - ボタンの文字列は、アビリティ名に `"[disabled]"`、またはクールダウン `"[" + CooldownRounds + "]"` と、トグル状態を足したもの（`:560-575`）。
- **`XRL.UI.Sidebar`。** Modern では `Render` が `sPlayerHP`、XP、`CurrentHP/MaxHP` だけを更新して return し、バッファには何も書かない（`XRL.UI/Sidebar.cs:787-833`）。**Modern の HUD の文字は ScreenBuffer に載らない。** API から組み直す必要がある。

### 4.9 地図（h）

- **中身。** Modern でも、`TextConsole.DrawBuffer` は `bSkipIfOverlay` が偽の描画（地図）を `CurrentBuffer` に写す（`ConsoleLib.Console/TextConsole.cs:142-162`）。`ViewTag` に `CurrentGameView` が付く。
- **スナップショット。** `TextConsole.BufferCS` を lock して写せば、どのスレッドからでも取れる。
- **タイル表示のとき。** `ConsoleChar.Set(RenderEvent)` は `_Char='\0'` にし、`BackupChar = RenderString[0]` を入れる（`ConsoleLib.Console/ConsoleChar.cs:392-426`）。
  - **ところが `ConsoleChar.Copy` は `BackupChar` を写さない**（`:360-375`。`_Char`、`_Tile`、色、`imposterExtra` などは写す）。`ScreenBuffer.Copy` はこの `Copy` を使う（`ConsoleLib.Console/ScreenBuffer.cs:300-318`）ので、`TextConsole.CurrentBuffer` の `BackupChar` は描画元の値を反映しない。
  - タイル表示で文字を得るには、AfterRender コールバックが受け取る、描画直後のバッファ（`XRL.Core/XRLCore.cs:2430-2433,2458-2465`）の `BackupChar` を、ゲームスレッドで読む。
  - ただし `RenderBaseToBuffer` は、引数の `Buffer` ではなくコアの `_Buffer` をコールバックに渡す（`:2462-2465`）。`AllowRenderMapBehind` の待機ループ（`XRL.UI/Popup.cs:901-903`）では、コールバックに渡るのは描画先ではない。
- **意味の情報。** 誰が何かは、ゾーンとセルの API で読む（ゲームスレッド、または §3.1 の T3 の例外）。`RenderBaseToBuffer` は可視・光マップを変える（`XRL.Core/XRLCore.cs:2436-2510`）ので、ブリッジから描画を呼んではいけない。

### 4.10 ツールチップ、Look、Alt（i）

- **Look のテキスト。** `Look.GenerateTooltipContent(O)` は、表示名、長い説明、SubHeader、`WoundLevel` を 1 つの文字列にまとめる（`XRL.UI/Look.cs:239-270`）。Looker の画面は要らない。
  - エンジンは `gameQueue.executeAsync` でゲームスレッドに回して呼ぶ（`:284`）。
  - ただし `AfterLookedAt` / `LookedAt` は、ツールチップの `onHide` でしか発火しない（`:394-402`）。**観測には足りるが、本物の Look の代わりにはならない**（05 C11(d)）。
- **タイルのツールチップ。** `QueueLookerTooltip(x, y)` はマスの対象を `lookSorter` で選び、UI スレッドのツールチップに流す（`:331-404`）。同じ選び方は `Cell.Objects` と `IsVisible()` で再現できる。
- **Alt ハイライト。** `Zone.Render` が `Keyboard.bAlt` を各セルの `Render` に渡すだけである（`XRL.World/Zone.cs:5722-5737`）。見た目の強調で、別のデータ源はない。同じ意味は、可視セルの対象を列挙すれば得られる。

### 4.11 本と端末（j）

- **本。**
  - `BookUI` の Modern 分岐は、`BookScreen.show(...).Result` で待つ（`XRL.UI/BookUI.cs:427-429,464-466`）。文字列から作る本も `MarkovBook` に変換してここを通る（`:500-525`）。
  - `BookScreen.instance.Book` / `BookID` は public（`Qud.UI/BookScreen.cs:54-56`）、`CurrentPage` は private（`:70`）。
  - 全ページは `Book.Pages[i]` か `BookUI.Books[BookID].Pages[i]` の `RenderForModernUI` から読める（`:276-291`）。
  - 閉じるには `Cancel()`（`:368-374`）。
- **端末。**
  - 画面の `cyberneticsTerminal` / `genericTerminal` は private（`Qud.UI/CyberneticsTerminalScreen.cs:40-42`）。ただし、static の `CyberneticsTerminal.Instance`（`XRL.UI/CyberneticsTerminal.cs:14`）と `GenericTerminal.instance`（`XRL.UI/GenericTerminal.cs:10`）がある。
  - 本文は `CurrentScreen.RenderedTextForModernUI`、選択肢は `Options` から読める（`Qud.UI/CyberneticsTerminalScreen.cs:219-251`）。
  - 選択には、行のタイプ演出の完了（`CursorDone`）が要る（`:279-283`、`Qud.UI/CyberneticsTerminalLineData.cs:19`）。
  - 閉じるには `Exit()`（`Qud.UI/CyberneticsTerminalScreen.cs:121-124`）。

### 4.12 qud-accessibility のフックとの対応（j）

| 同 mod のパッチ | Modern で Harmony なしに同じ情報を得る方法 | 判定 |
|---|---|---|
| `Popup.ShowYesNoCancel`、`PopupMessage.ShowPopup` | §4.1 のウィンドウ列挙で、`Message/Title/contextText/menuData/bottomContextOptions` を読む | 不要（ポーリング） |
| `Look.ShowLooker` | `Look.GenerateTooltipContent`、および PickTarget の AfterRender の足場（§4.4） | 不要（本物の Look の副作用は別） |
| `XRLCore.PlayerTurn` | `RegisterOnBeginPlayerTurnCallback`（`XRL.Core/XRLCore.cs:604-607,684-686`） | 不要 |
| `FrameworkScroller.UpdateSelection` | public の `onHighlight` UnityEvent に UI スレッドで `AddListener` する。`UpdateSelection` から呼ばれる（`XRL.UI.Framework/FrameworkScroller.cs:37-41,443-450`） | 不要（インスタンスの探索は要る） |
| `TradeScreen.showScreen/UpdateTotals/Update` | §4.5 の public フィールドと static | 不要 |
| `CyberneticsTerminalScreen.Show` | static の `Instance` / `instance` | 不要 |
| `BookScreen.showScreen`、`UpdateViewFromData` | `BookScreen.instance.Book/BookID` | 不要。ただし現在のページ番号は private なので、読むにはリフレクションか `leftPageNumber.text` を使う |
| `StatusScreensScreen.UpdateActiveScreen` | §4.6 の API | 不要（画面を開かない） |
| `AbilityBar.MoveSelection/MovePage` | §4.8 の API。選択位置は人間の操作用なので要らない | 不要 |
| `TutorialManager` | `TutorialManager.currentStep` / `IsActive`（`TutorialManager.cs:107,147`）。ゲートは `AllowSelectedPopupCommand`（`:341-349`） | 不要 |
| MainMenu、SaveManagement、キャラクター作成、Options、Keybinds、WorldCreationProgress | 起動前の画面で、観測の本線ではない。`WorldCreationProgress.CurrentStep/Steps` は public static（`XRL.UI/WorldCreationProgress.cs:16-20`） | 本書の範囲外（別家族） |
| `GameSummaryScreen.Show` | `ShowGameSummary(name, cause, details, real)` の引数（`Qud.UI/GameSummaryScreen.cs:54-65`）。フィールドの `Name` / `Details` は public（`:40-42`） | 不要（読み出しの時点は実機で確認する） |

## 5. マトリクス（面 → データ源 → スレッド → Harmony → 穴）

| 面 | データ源（型.メンバー、file:line） | 読めるスレッド | Harmony | 穴 |
|---|---|---|---|---|
| ポップアップの本文・タイトル・選択肢・ボタン | `PopupMessage.Message/Title/contextText.text`、`controller.menuData/bottomContextOptions`（`Qud.UI/PopupMessage.cs:771-874`） | 列挙は UI。text は T1 でも可 | 不要 | 同じ窓の再利用中に読むと、値が混ざりうる |
| 入力欄 | `PopupMessage.inputBox.text`（`:814`） | UI のみ | 不要 | CP437 変換 |
| 会話 | `ConversationUI.CurrentNode/CurrentChoices/Speaker`（`XRL.UI/ConversationUI.cs:135-157`）＋ popup の表示文字列 | T1（モーダル中）／UI | 不要 | `GetDisplayText` はブリッジから呼ばない |
| PickGameObject | `PickGameObjectScreen.rawGameObjects/listItems/titleText`（`Qud.UI/PickGameObjectScreen.cs:47-65`） | UI | 不要 | 名前の計算は UI スレッドで行う |
| PickTarget | `PickTargetWindow.currentText/currentMode`、`TextConsole.CurrentBuffer.focusPosition` | T1／BufferCS の lock | 不要 | テンキー前の位置 → PointerOver で解消 |
| PickDirection | `PickTargetWindow.currentText`（`XRL.UI/PickDirection.cs:44-47`） | T1 | 不要 | なし |
| 取引 | `TradeScreen.tradeEntries/Totals/Weight/NumberSelected/Trader/CostMultiple`、`TradeUI.GetValue`（`Qud.UI/TradeScreen.cs:41-89`、`Qud.UI/TradeLine.cs:473`） | UI | 不要 | オファー中はプールスレッドでポップアップが出る |
| ステータス類 | `GameObject.Statistics/Effects/Body/Inventory/ActivatedAbilities`、`Skills.SkillList`、`Mutations.MutationList`、`XRLGame.Quests`、`JournalAPI` | ゲーム（PlayerTurn）／UI（モーダル中） | 不要 | なし |
| メッセージログ | `XRLCore.RegisterNewMessageLogEntryCallback`（`XRL.Core/XRLCore.cs:657-680`） | 呼び出し元のスレッド | 不要 | ポップアップの本文の一部は載らない |
| HUD | PlayerTurn のコールバックで同じ API を読む（`Qud.UI/PlayerStatusBar.cs:310-420`、`Qud.UI/AbilityBar.cs:286-420`） | ゲーム | 不要 | TMP タグは自前で組み直すので問題にならない |
| 地図の文字 | ASCII 表示なら `TextConsole.CurrentBuffer` の `Char`。タイル表示なら AfterRender の引数バッファの `BackupChar`（`ConsoleLib.Console/ConsoleChar.cs:360-375,392-426`） | 前者は任意（BufferCS の lock）、後者はゲーム | 不要 | `Copy` は `BackupChar` を写さない。字は損失がある。意味は Zone の API で読む |
| Look | `Look.GenerateTooltipContent`（`XRL.UI/Look.cs:239-270`） | ゲーム（AfterRender の中、PlayerTurn）／UI（モーダル中） | 不要 | LookedAt 系は発火しない |
| 本 | `BookScreen.instance.Book/BookID`（`Qud.UI/BookScreen.cs:54-56`） | UI／T1 | 不要 | ページ番号は private |
| 端末 | `CyberneticsTerminal.Instance.CurrentScreen`、`GenericTerminal.instance.currentScreen` | T1／UI | 不要 | 選択には CursorDone が要る |

## 6. レシピ表

表の中の「UI」は、`uiQueue.queueTask` / `executeAsync` で UI スレッドに渡すことを指す。

| モーダル | wait_kind | 探査のきっかけ（wish、ゲームスレッド） | 検出 | 読み取り | 答え方 | 取り消し | Harmony |
|---|---|---|---|---|---|---|---|
| 同期 PopupMessage（Show / ShowBlock / YesNo / YesNoCancel / PickOption / Popup.PickGameObject） | 呼び出し元のスレッドが `complete.Task.Wait()`（`Popup.cs:908`） | `Popup.ShowYesNo("probe")`（`:2251`）、`Popup.PickOption("T","intro",Options:["a","b"],AllowEscape:true)`（`:1650`）、`Popup.Show("probe")`（`:658`） | UI: `windowsByName` のうち、`PopupMessage` で、`activeInHierarchy && canvasGroup.interactable && (commandCallback!=null \|\| selectCallback!=null)` のもの。T1 の前段: `CurrentGameView=="PopupMessage"` | `Message.text`、`Title.text`、`contextText.text`、`menuData[i].text/command`、`bottomContextOptions[j].text/command`、`PopupID` | 選択肢: `w.OnSelect(item)`（`command=="option:N"` の実物）。ボタン: `w.OnActivateCommand(btn)`。`CmdOptions` 以外で、`TutorialManager.AllowSelectedPopupCommand` が真のとき | `bottomContextOptions` のうち `command=="Cancel"` のものに `OnActivateCommand` する。Show / ShowBlock（SingleButton、`command="Accept"`）では `bottomContextOptions[0]` に `OnActivateCommand` する。Cancel がなく（`AllowEscape:false`）、選択肢だけのときは選ぶしかない | 不要 |
| 非同期 PopupMessage（AskString / AskNumber / ShowAsync） | ゲームスレッドの `.Result`（`Popup.cs:1200,1442`） | `Popup.AskString("probe")`（`:1433`）、`Popup.AskNumber("probe",Start:1,Min:0,Max:9)`（`:1191`） | 同じ述語。複製 `"PopupMessage #N"` も含める。前段は `CurrentGameView=="DynamicPopupMessage"` | 上と同じ。加えて `inputBox.text` と `RestrictChars` | `w.inputBox.text = s; w.OnInputSubmit(s)`（`PopupMessage.cs:946-958`） | Cancel ボタンに `OnActivateCommand` | 不要 |
| 会話 | 同期 PopupMessage（`Popup.cs:1594`）。外側は `ConversationUI` のループ | 対象: 会話を持つ、アクティブゾーンの NPC。`ConversationUI.HaveConversation(id, speaker)`（`ConversationUI.cs:333`）。合成で試すなら `Popup.ShowConversation("T", null, "intro", ["a","b"], AllowTrade:true)`（`Popup.cs:1571`） | 同期 PopupMessage の述語 ＋ `PopupID.StartsWith("Conversation:")` | `contextText.text`（話者）、`Message.text`（ノード本文）、`menuData`（選択肢）。補助に `ConversationUI.CurrentNode/CurrentChoices` | 選択肢: `OnSelect(menuData[k])`。取引／Look: 該当ボタンに `OnActivateCommand` | `command=="Cancel"` のボタン。`AllowEscape` が偽のノードでは出ない | 不要 |
| PickGameObjectScreen | ゲームスレッドの `.Result`（`PickItem.cs:285,307,319`） | `PickItem.ShowPicker(The.Player.Inventory.GetObjects())`（`PickItem.cs:263`） | T1: `CurrentGameView=="PickGameObject"`。UI: `PickGameObjectScreen.instance.Visible` | `rawGameObjects`、`listItems[i].type/category/go`、`titleText.text` | UI: `instance.HandleSelectItem(listItems[i])`（Item 行） | UI: `instance.Cancel()` | 不要 |
| PickTarget | ゲームスレッドの `kbhit` / getvk ループ（`PickTarget.cs:786-791`） | `PickTarget.ShowPicker(PickStyle.Burst, 0, 9999, x, y)`（`:378`） | T1: `CurrentGameView=="PickTarget" && PickTargetWindow.currentMode==PickCells` | `currentText`、`TextConsole.CurrentBuffer.focusPosition`（BufferCS の lock）。セルの内容は AfterRender コールバックの中で計算する | `PushMouseEvent("PointerOver",x,y)` を 2 回、次に `PushMouseEvent("Command:CmdFire")`、または `PushKey` で Space。これが実機で成り立たなければ、代替は照準の imposter（C-26）。それも駄目なら、`ShowPicker` の transpiler | `PushKey(Escape)` | 不要（条件付き） |
| PickDirection | ゲームスレッドの getvk（`PickDirection.cs:54`） | `PickDirection.ShowPicker("probe")`（`:28`） | T1: `CurrentGameView=="PickTarget" && currentMode==PickDirection` | `currentText` | `PushKey` でテンキーの方向、または NumPad5 で `"."`（`:56-61`） | `PushKey(Escape)`（`:64-67`） | 不要 |
| TradeScreen | ゲームスレッドの `.Result`（`TradeUI.cs:458`） | 商人の部品を持つ、アクティブゾーンの NPC で `TradeUI.ShowTradeScreen(npc)`（`:344`）。容器モードなら `ShowTradeScreen(container, 0f, TradeScreenMode.Container)`（`PickItem.cs:289` と同じ形） | T1: `CurrentGameView=="ModernTrade"`（`TradeScreen.cs:462`） | `tradeEntries[side][i].GO`、`NumberSelected`、`Totals`、`Weight`、`TradeUI.GetValue(go, side==0)`、`GetFreeDrams()` | UI: `await setHowManySelected(go,n)` → `UpdateViewFromData()`（配信画面の行表示を合わせる）→ `HandleOfferTrade()`。続くポップアップ（プールスレッド）には同期 PopupMessage のレシピで答える | UI: `instance.Cancel()` | 不要 |
| StatusScreensScreen | ゲームスレッドの `.Result`（`Screens.cs:80,125`） | `Screens.Show(The.Player)`（`:88`）、`MessageQueue.Show()`（`MessageQueue.cs:78`） | T1: `CurrentGameView=="StatusScreensScreen"` | 使わない。§4.6 の API を読む | ─ | UI: `instance.Exit()` | 不要 |
| BookScreen | ゲームスレッドの `.Result`（`BookUI.cs:429,466`） | `BookUI.ShowBook("page","title")`（`:500`） | T1: `CurrentGameView=="Book"`（`BookScreen.cs:195,226`） | `Book.Pages[i].RenderForModernUI`、または `BookUI.Books[BookID].Pages` | ─（読むだけ） | UI: `instance.Cancel()` | 不要 |
| CyberneticsTerminalScreen | ゲームスレッドの `.Result`（`CyberneticsTerminal.cs:201`、`GenericTerminal.cs:83`） | Joppa の初期状態では開けない（実機で要確認） | T1: `CyberneticsTerminal.Instance != null` など。ビュー名は未確認 | `CurrentScreen.RenderedTextForModernUI`、`Options` | UI: `HandleSelect(line)`。`CursorDone` が要る | UI: `Exit()` | 不要 |

## 7. 主張一覧

- **C-F7-observation-01**（high）
  - Modern のポップアップの legacy 相当テキストは、`PopupMessage` のフィールドにすべてそろう。
    - 本文: `Message`、`"{{y|…}}"` で包まれる（`Qud.UI/PopupMessage.cs:777`）。
    - タイトル: `Title`、`"{{W|…}}"`（`:800-805`）。
    - 文脈タイトル: `contextText`（`:855`）。
    - 選択肢: `controller.menuData`、ボタン: `controller.bottomContextOptions`（`:781-782`）。
    - 入力: `inputBox`（`:814`）。
- **C-F7-observation-02**（high）
  - 同期経路は、非 UI スレッドからだと**単体の** `getWindow("PopupMessage")` を使う（`XRL.UI/Popup.cs:824-829`）。
  - 非同期経路（AskString / AskNumber）と、UI スレッドからの同期呼び出しは、**複製の** `copyWindow` を使う（`:755-760,804-822`）。
  - 複製は release の後も `windowsByName` に残り、非アクティブになるだけである（`Qud.UI/UIManager.cs:323-352`）。
- **C-F7-observation-03**（high）
  - `gameQueue.executeTasks()` の呼び出しは四つある。
    - `pumpActions` つきの getvk（`ConsoleLib.Console/Keyboard.cs:1040`。PlayerTurn は `XRL.Core/XRLCore.cs:3938`）。
    - コアスレッドの `RenderBase`（`XRL.Core/XRLCore.cs:2604`）。
    - Looker（`XRL.UI/Look.cs:658,933`）。
  - Modern のモーダル待機（`XRL.UI/Popup.cs:908`、各画面の `.Result`）の間は回らない。モーダル中の読み取りは `uiQueue.executeAsync`（`QupKit/ThreadTaskQueue.cs:77-100`）で行う。
- **C-F7-observation-04**（high）
  - ゲームスレッドが止まっている間、エンジン自身も UI スレッドからゲーム状態を読んでいる。
    - `TradeScreen.UpdateTotals` → `The.Player.GetCarriedWeight()`（`Qud.UI/TradeScreen.cs:465-470,676-686,727-733`）。
    - `PickGameObjectScreen.UpdateViewFromData` → `GetInventoryCategory()`（`Qud.UI/PickGameObjectScreen.cs:231-251,286-300`）。
- **C-F7-observation-05**（medium、runtime_only=false）
  - 未回答の PopupMessage は、UI スレッド上の `activeInHierarchy && canvasGroup.interactable && (commandCallback!=null || selectCallback!=null)` で判定できる。
  - 根拠: `Show` は `interactable=true`、`Hide` は `interactable=false` にする（`Qud.UI/WindowBase.cs:197-218`、`Qud.UI/PopupMessage.cs:1083-1104`）。したがって、`OnSelect` の後に残る `commandCallback`（`:936-944`）による二重回答を防げる。
  - `Qud.UI/` 全体で、窓の `canvasGroup.interactable` を書くのは `WindowBase.cs:177,193,217` と `PopupMessage.cs:1096` だけである。フレーム途中の過渡状態は、実機で確かめる。
- **C-F7-observation-06**（high）
  - 選択肢は `command="option:N"` を持ち、表示の text には `{{W|[c]}}` や `{{w|[n]}}` の前置き、会話では末尾の `"\n\n"` が付く（`XRL.UI/Popup.cs:2011-2045,1586-1594`）。
  - 同定は `command` で行い、表示は前置きと末尾を除いて整形する。
- **C-F7-observation-07**（high）
  - タイトルは `Title` か `contextText` のどちらかに入る。
    - PickOption は、アイコンがあれば `contextText`、なければ `Title` に入れる（`XRL.UI/Popup.cs:1716-1758`）。
    - 会話は `Title=""` にし、話者の `"{{W|DisplayName}}"` を `contextText` に、`PopupID="Conversation:"+Title` にする（`:1613`、`XRL.UI/ConversationUI.cs:474-487`）。
- **C-F7-observation-08**（high）
  - `ColorUtility.StripFormatting(string)` は、lock の外で共有の static `StripSB` を使う（`ConsoleLib.Console/ColorUtility.cs:179,303-343`）。ブリッジスレッドから呼ぶとゲームスレッドと競合しうる。
  - span 版の `StripFormatting(ReadOnlySpan<char>, TextBuilder)` は、static を使わない（`:2257-2275,2298-`）。
- **C-F7-observation-09**（high）
  - 会話の Modern ループは、`ConversationUI.Render` → `Popup.ShowConversation` の同期ポップアップである（`XRL.UI/ConversationUI.cs:418-428,514-537`）。
  - 戻り値は、-1 が Escape、-2 が取引、-3 が Look、それ以外は選択（`:521-536`）。
  - ボタンは `Look`、`trade`、`Cancel` の順に並ぶ（`XRL.UI/Popup.cs:1573-1582`）。
- **C-F7-observation-10**（high）
  - PickTarget と PickDirection は、ゲームスレッドの getvk ループで入力を取る（`XRL.UI/PickTarget.cs:786-791`、`XRL.UI/PickDirection.cs:54`）。Modern の案内文は、static の `PickTargetWindow.currentText` に入る（`XRL.UI/PickTarget.cs:747-750`、`XRL.UI/PickDirection.cs:44-47`）。
  - 確定は F / Space / Enter / `"Command:CmdFire"` / `"LeftClick"`（`XRL.UI/PickTarget.cs:965-982`）、取り消しは NumPad5 / Escape / `"Command:CmdTargetSelf"`（`:809-812`）。
- **C-F7-observation-11**（medium、runtime_only=true）
  - PickTarget のカーソル位置はローカル変数（`XRL.UI/PickTarget.cs:400-405`）である。`focusPosition` に出るのは、テンキーの後だけ（`:782-785,817-820`）。ロック時の移動は対象に飛ぶ（`:821-835`）。
  - ただし、`PointerOver` のマウスイベントを 2 回送れば、ブリッジが指定した `(x,y)` にカーソルを置ける（`:792-799,804-807`）。したがって、Harmony なしで位置が既知になる。
  - 実マウスのホバーとの干渉と、`bCapInputBuffer` による取りこぼし（`ConsoleLib.Console/Keyboard.cs:825-830`）は、実機で確かめる。
- **C-F7-observation-12**（medium、runtime_only=true）
  - PickTarget は毎反復 `RenderMapToBuffer` を呼び（`XRL.UI/PickTarget.cs:412`）、そこで AfterRender コールバックが走る（`XRL.Core/XRLCore.cs:2407-2433`）。したがって、ピッカーが開いている間も、mod はゲームスレッドで Look などを計算できる。
  - 呼ばれる頻度（`kbhit` が偽のときの `continue` の速さ）は、実機で確かめる。
- **C-F7-observation-13**（high）
  - 取引の画面データは、`TradeScreen` の public フィールドと static にある（`Qud.UI/TradeScreen.cs:41-89`）。
    - `tradeEntries[0]` が商人、`[1]` がプレイヤー（`:494-526`）。
    - 各行の値段は `TradeUI.GetValue(go, traderInventory)` の `:0.00` 表示（`Qud.UI/TradeLine.cs:473-483`）。
    - 合計、水、重量は `UpdateTotals` と同じ式で出せる（`Qud.UI/TradeScreen.cs:727-743`）。
- **C-F7-observation-14**（high）
  - `APIDispatch.RunAndWaitAsync` は、処理を `Task.Run`（プールスレッド）で実行する（`XRL.UI.Framework/APIDispatch.cs:10-44`）。
  - 取引のオファー（`Qud.UI/TradeScreen.cs:842-861`）の中で出る `ShowYesNo`（`XRL.UI/TradeUI.cs:1296-1390`）は、プールスレッドを止める。
  - したがって、「ゲームスレッドが止まっている」ことを前提にした検出や読み取りは、この区間で成り立たない。
- **C-F7-observation-15**（high）
  - PickGameObjectScreen の候補は、`rawGameObjects` と `listItems`（type / category / go）で読める（`Qud.UI/PickGameObjectScreen.cs:47-65,317-335`）。
  - UI スレッドで `HandleSelectItem`（Item 行）を呼ぶと、`menucomplete` が完了する（`:577-594`）。`Cancel()` は既定値で完了する（`:512-517`）。
- **C-F7-observation-16**（high）
  - メッセージログは、`XRLCore.RegisterNewMessageLogEntryCallback` で Harmony なしに受け取れる（`XRL.Core/XRLCore.cs:657-680`）。Modern のログ窓も同じ源を使う（`Qud.UI/MessageLogWindow.cs:94-112`）。
  - コールバックは `Add` の呼び出し元スレッドで走る。hotload で消えるので、init のたびに登録する（`XRL.Core/XRLCore.cs:252-273`）。
- **C-F7-observation-17**（high）
  - `ShowBlock` はポップアップの本文をログにも送るが（`XRL.UI/Popup.cs:1134-1137`）、`ShowYesNo` の本体には `AddPlayerMessage` の呼び出しがない（`:2251-2330` を grep した結果）。
  - したがって、ポップアップの本文の観測をログで代用することはできない。
- **C-F7-observation-18**（high）
  - Modern の HUD の文字列は、ゲームスレッドの XRLCore のコールバックで、プレイヤーの API から組み立てられている。
    - PlayerStatusBar: `Qud.UI/PlayerStatusBar.cs:273-278,310-420`。
    - AbilityBar の効果、アビリティ、クールダウン、ターゲット: `Qud.UI/AbilityBar.cs:218-222,286-420,560-575`。
  - mod も同じコールバック（`XRL.Core/XRLCore.cs:604-655`）で同じ値を得られる。
- **C-F7-observation-19**（high）
  - Modern の `Sidebar.Render` は数値だけを更新して return し、ScreenBuffer に何も書かない（`XRL.UI/Sidebar.cs:787-833`）。
  - したがって、Modern の HUD の文字は `TextConsole.CurrentBuffer` にない。
- **C-F7-observation-20**（high）
  - Modern の `CurrentBuffer` には地図が入る（`ConsoleLib.Console/TextConsole.cs:142-162`）。public の `TextConsole.BufferCS` を lock すれば、どのスレッドからでも写せる（`TextConsole.cs:29,149`）。
  - タイル表示では、`Set` が `Char='\0'`、`BackupChar=RenderString[0]` にする（`ConsoleLib.Console/ConsoleChar.cs:392-426`）。しかし `ConsoleChar.Copy` は `BackupChar` を写さない（`:360-375`）。
  - したがって、タイル表示で文字の地図を作るには、`CurrentBuffer` ではなく、AfterRender コールバックの引数のバッファ（`XRL.Core/XRLCore.cs:2430-2433`）を読む。
- **C-F7-observation-26**（low、runtime_only=true）
  - `UseImposters` のとき、PickTarget の各スタイルは、カーソル位置の `imposterExtra` に `"Prefabs/Imposters/TargetReticle"` を足す（`XRL.UI/PickTarget.cs:432,452,464,476,487,557,647,671,723`）。
  - `ConsoleChar.Copy` は `imposterExtra` を写す（`ConsoleLib.Console/ConsoleChar.cs:374`）。
  - したがって、`CurrentBuffer` で照準を探せば、テンキーの前のカーソル位置も推定できる見込みがある。`ImposterExtra` の中身の読み方と、複数のマスに付く場合（Line / Burst）の区別は未確認である。
- **C-F7-observation-21**（high）
  - `Look.GenerateTooltipContent(O)` は、Looker の画面なしに Look 相当のテキストを返す（`XRL.UI/Look.cs:239-270`）。エンジンはこれをゲームスレッドで呼ぶ（`:284`）。
  - `AfterLookedAt` / `LookedAt` は、ツールチップの `onHide` でしか発火しない（`:394-402`）。
- **C-F7-observation-22**（medium）
  - qud-accessibility の `FrameworkScroller.UpdateSelection` への postfix は、public の `onHighlight` UnityEvent への `AddListener` で置き換えられる（`XRL.UI.Framework/FrameworkScroller.cs:37-41,443-450`）。
  - どの画面のどのスクローラーを購読するかは、画面ごとに決める。
- **C-F7-observation-23**（high）
  - 本の全文は `BookScreen.instance.Book` / `BookID` から読め（`Qud.UI/BookScreen.cs:54-56,276-291`）、`Cancel()` で閉じられる（`:368-374`）。ただし `CurrentPage` は private である（`:70`）。
- **C-F7-observation-24**（high）
  - AskNumber は、`activeControllerType` がキーボードでなければ、PopupMessage ではなく `AskNumberScreen` を使う（`XRL.UI/Popup.cs:1320-1337`）。
- **C-F7-observation-25**（high）
  - 会話の取引ボタンの text は `"{{[W|…]}} {{y|Trade}}"` である（`Qud.UI/PopupMessage.cs:693-713`）。`GetNext` は `{{` から `|` までを捨てる（`ConsoleLib.Console/ColorUtility.cs:477-497`）ので、除去すると先頭の `[` が欠ける。ボタンの表示は `command` から組み直す。

## 8. 実機でしか分からないこと

0. **`PointerOver` の注入。** これで PickTarget のカーソルを確定できるか。できなければ、照準の imposter による代替が使えるか（C-11、C-26）。
1. **`interactable` の述語の偽陽性と偽陰性。** `ShowPopup` の途中（`alpha=0` から `Show` まで）に読んだときと、`HideNextFrame` の 2 フレームの間（`Qud.UI/PopupMessage.cs:968-982`）に読んだときの挙動を確かめる。
2. **PickTarget のカーソル設定の安定性。** `PointerOver` を 2 回送る方法で位置が安定するか。実マウスがゲーム窓の上にあるとき、`PointerOver` が割り込むか。
3. **AfterRender の頻度。** PickTarget 中に AfterRender が何 Hz で呼ばれるか。
4. **取引オファー中のポップアップ。** 入れ子のポップアップが、プールスレッドから単体の窓で正しく出て、同じ述語で拾えるか。
5. **会話と取引の探査対象。** Joppa の初期状態で、会話と取引の探査に使える NPC の ID（会話 ID、商人）。
6. **GameSummaryScreen と端末。** GameSummaryScreen の `Name/Details` を読める時点。端末のビュー名と `CursorDone` の所要時間。
7. **UI スレッドでの読み取りの負荷。** `uiQueue.executeAsync` でゲーム状態を読むときの 1 フレームあたりの負荷と、ヒッチの有無。
8. **メッセージログ窓の件数上限。** Modern のメッセージログ窓（`MessageLogWindow` / `MessageLogStatusScreen`）が、表示の件数を別に切り詰めているか。本書では確認していない。

## 9. 未解決の問い

1. **PickSeveral とカラーピッカー。** `Popup.PickSeveral`（`XRL.UI/Popup.cs:2046`）と `ShowColorPicker`（`:2222`）の Modern 経路は、本書では開いていない。PopupMessage 系に乗るかどうかは未確認である。
2. **`MinEvent.UIHold` の意味。** Modern の画面は表示中に `MinEvent.UIHold=true` にする。これがイベント処理にどう効くか（読む側の場所）は、grep で見つけられなかった。
3. **ブリッジ用の `TextBuilder`。** ブリッジで span 版の `StripFormatting` を使うには、`XRL.World.Text.TextBuilder` の生成方法（コンストラクタ）を確かめる必要がある。移植のほうが安全かもしれない。
4. **スクローラーのインスタンスの探し方。** `FrameworkScroller.onHighlight` をどの画面で購読するか。その画面のインスタンスを、どう安定して見つけるか。
5. **ポップアップの本文が長いとき。** `StringFormat.ClipText(Message, 60, KeepNewlines:true)`（AskString / AskNumber。`XRL.UI/Popup.cs:1349,1396`）で切られた本文を、元の全文に戻す手段はあるか。現状では、表示された文字列しか取れない。
