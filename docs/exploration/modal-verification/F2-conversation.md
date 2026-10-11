# F2-conversation: Modern UI の会話モーダルの検出・読み取り・応答（静的検証）

対象ビルド: 2.0.211.56（ILSpy 逆コンパイル、`/Users/sankenbisha/Dev/coq-decompiled_stable`）。引用はすべてソースルートからの相対パスと行番号である。

## 1. 目的

Modern UI を画面に残したまま、エージェントが会話を扱えるかを静的に確かめる。必要なのは次の三つである。

- ゲームスレッドが会話ノードで止まっていることを、ブリッジスレッドまたは UI スレッドから**検出**する。
- ノードの本文、話者、選択肢を、Legacy と同等のテキストとして**読む**。
- `GameManager.Instance.uiQueue` 経由で UI スレッドに渡した処理で、Harmony なしに**答える**。

あわせて、会話の中から開く取引、Look、クエスト開始や水の儀式のポップアップへの遷移と、会話終了時の後始末を整理する。

結論を先に書く。会話ノードの応答口は `ConversationUI.Select` ではない。単体の `PopupMessage` ウィンドウの `OnActivateCommand` か `OnSelect` を UI スレッドから呼んで、`WaitNewPopupMessage` の `TaskCompletionSource` を完了させる。これで Harmony なしに、人間の入力と同じ経路で答えられる。

## 2. 対象一覧

| # | モーダル／状態 | 表示の実体 | ゲームスレッドの待ち方 |
|---|---|---|---|
| M1 | 会話ノード（本文、選択肢、Look/Trade/Cancel） | 単体の `PopupMessage`（ビュー `"PopupMessage"`、PopupID `"Conversation:"+Title`） | `WaitNewPopupMessage` の `complete.Task.Wait()`。RenderMapBehind の会話では `Wait(33)` のループ |
| M2 | 会話から開く取引（下段の Trade ボタン、または `[begin trade]` の選択肢） | `TradeScreen`（ビュー `"ModernTrade"`） | `TradeScreen.show(...).Result` |
| M3 | 会話の Look ボタン | `copyWindow` の `"PopupMessage #N"`（ビュー `"DynamicPopupMessage"`） | `NewPopupMessageAsync(...).Result` |
| M4 | 会話中に入れ子で出るポップアップ（`Popup.Show`、ShowFail、クエスト開始、迷子の解消、水の儀式の YesNoCancel、PickOption） | 単体の `PopupMessage`（PopupID は null か別の値） | `WaitNewPopupMessage` の `Task.Wait()` |
| M5 | 会話セッション全体（開始から後始末まで） | ビュー `"Conversation"`（Modern のキャンバスはない） | ノード間ではゲームスレッドが走っている |

## 3. 各モーダルの動作

### 3.1 会話の入口とループ

- `HaveConversation` はまず statics（`CurrentConversation`、`Speaker`、`Listener` など）を設定する。次に `PushGameView("Conversation", bHard:false)` を積み、`InternalConversation()` を呼ぶ。`finally` では、体の復元、`Reset()`、`PopGameView(bHard:true)` の順に後始末する（`XRL.UI/ConversationUI.cs:361-394`）。
- `InternalConversation` は、開始可否のイベント、`StartNode`、`CheckLost()` を通る。その後 `while (CurrentNode != null) { Prepare(); if (UIManager.UseNewPopups) Render(); else RenderClassic(); }` を回す（`XRL.UI/ConversationUI.cs:396-429`）。`UseNewPopups` は `Options.ModernUI` と同じである（`Qud.UI/UIManager.cs:55`）。
- 会話クラスのビュー属性は `[UIView("Conversation", true, false, false, "Conversation", null, false, 0, true)]` である。6 番目の引数 `UICanvas` が null なので、会話専用の Modern キャンバスはない（`XRL.UI/ConversationUI.cs:14`、`XRL.UI/UIView.cs:45`）。Modern の画面は `PopupMessage` が受け持つ（`Qud.UI/PopupMessage.cs:16-17`）。
- `Prepare()` は `CurrentChoices` を作り直す。対象は `IsVisible()`（述語と `IsElementVisibleEvent`）を通った選択肢だけで、最後に安定ソートする（`XRL.UI/ConversationUI.cs:491-512`、`XRL.World.Conversations/IConversationElement.cs:385-392`）。

### 3.2 Modern の Render と Popup.ShowConversation

- `Render()` は `CurrentChoices` から `GetDisplayText(WithColor:true)` の文字列リストを作る。次に `GetTitle()` と `RenderNodeEvent` でタイトルを決め、`Popup.ShowConversation(Title, Icon, CurrentNode.GetDisplayText(true), options, Trade.Visible, CurrentNode.AllowEscape, HasState("RenderMapBehind"))` を呼ぶ。返り値の -1 で Escape、-2 で `Trade.ShowScreen()`、-3 で Look、それ以外で `Select(num)` を行う。**すべてゲームスレッド上で進む**（`XRL.UI/ConversationUI.cs:514-537`）。
- `ShowConversation` の組み立ては次のとおり（`XRL.UI/Popup.cs:1571-1615`）。
  - 下段ボタン: 常に `LookButton`（command `"Look"`、`Qud.UI/PopupMessage.cs:72-77`）を置く。`AllowTrade` なら `AcceptCancelTradeButton[0]`（command `"trade"`、`:693-700`）、`AllowEscape` なら `CancelButton[0]`（command `"Cancel"`、`:255-285`）を足す。並びは [Look, trade?, Cancel?] になる。
  - 本文の項目: `text = ("{{w|[i+1]}} " を i<9 かつ AllowKeyboardHotkeys のとき付ける) + Options[i] + "\n\n"`、`command = "option:" + i`、`hotkey = "Alpha"+(i+1)`（i<9 のとき）。
  - `WaitNewPopupMessage(Intro+"\n\n", 下段, callback, 本文項目, title:"", inputDefault:null, 0, contextTitle:Title, contextRender:Icon, ..., PopupID:"Conversation:"+Title, AllowRenderMapBehind)` を呼ぶ。
  - callback は `item.command` だけを見て、`Cancel` を -1、`trade` を -2、`Look` を -3、`option:N` を N に写す。**初期値は `SelectedOption = 0`** である（`:1583`）。

### 3.3 待ち方（WaitNewPopupMessage、ゲームスレッドから呼ばれた場合）

- `uiQueue.awaitTask` の中で次を行う（`XRL.UI/Popup.cs:823-895`）。`awaitTask` はゲームスレッドを `ManualResetEvent` で止め、UI スレッドで実行する（`QupKit/ThreadTaskQueue.cs:135-155`）。
  1. `getWindow("PopupMessage")` の単体ウィンドウを取る。
  2. `PushGameView("PopupMessage")` を積む。
  3. `ShowPopup(..., commandCallback, items, selectedItemCallback, ..., onHide, ..., PopupID)` を呼ぶ。
- 二つのコールバックは、どちらも `complete.SetResult(i)` を呼ぶ。`commandCallback` は、その前に `i.text.Replace(...)` を実行する（EscapeNonMarkupFormatting が真のため。`:834-852`）。`selectedItemCallback` は text に触れない（`:854-868`）。`onHide` は `complete.TrySetCanceled()` を呼ぶ（`:873-877`）。
- 待機は、`AllowRenderMapBehind` が偽なら `complete.Task.Wait()` である。真なら `Wait(33)` と `RenderBaseToBuffer` を交互に回す（`:896-909`）。
- 待機を抜けると `PopGameView(bHard:true)` の後に callback を呼ぶ（`:910-914`）。キャンセルされたタスクに `Wait()` を呼ぶと、.NET の仕様で AggregateException が投げられる。したがって `:910` の PopGameView は実行されない。
- `RenderMapBehind` の状態を書き込むコードは、逆コンパイル結果の中にない（grep で `ConversationUI.cs:521` の読み出しだけ）。会話 XML のデータで決まると考えられる。`RenderBaseToBuffer`（`XRL.Core/XRLCore.cs:2436-2446`）は `gameQueue` を回さない。`gameQueue.executeTasks` の呼び出しは、`RenderBase` の中（`:2600-2605`）と、`Keyboard.cs:1040`、`Look.cs:658,933` にしかない。

### 3.4 PopupMessage 側（UI スレッド）

- `ShowPopup` の処理（`Qud.UI/PopupMessage.cs:721-875`）:
  - `PopupID`、`onHide`、`Message.SetText("{{y|"+message+"}}")`、`commandCallback`、`selectCallback`、`controller.menuData = items`、`controller.bottomContextOptions = buttons` を設定する（`:771-782`）。
  - contextTitle は `contextText.SetText` に入る（`:852-856`）。
  - 最後に `lastPopupID = PopupID` を書く（`:874`）。
  - `UITextSkin.SetText` は public フィールド `text` に代入する（`XRL.UI/UITextSkin.cs:54,158-167`）。
- `OnActivateCommand(item)`: チュートリアルのゲートを通り、`command != "CmdOptions"` かつ `commandCallback != null` のときに限り、`commandCallback(item)`、`commandCallback = null`、`Hide()` の順に実行する（`:926-934`）。
- `OnSelect(item)`: ゲートを通り、`selectCallback != null` のときに限り、`selectCallback(item)`、`selectCallback = null`、`Hide()` の順に実行する（`:936-944`）。
- `Hide()` は `onHide` を同期で呼ぶ（`:1083-1104`）。結果を立てた後なら、`TrySetCanceled` は何もしない。
- コールバックを null にする経路は五つあり、どれも片方しか消さない。
  - `commandCallback` を消す: `OnActivateCommand`（`:931`）、Update の `char:` ホットキー（`:1058`）。
  - `selectCallback` を消す: `OnSelect`（`:941`）、キャンセルトークン（`:988`）、any-key（`:1043`）。
  - 会話では下段ボタンが空にならない（Look が常にある）。キャンセルトークンも既定値なので、`:985-991` と `:1040-1045` は発火しない。
- ゲート: `TutorialManager.AllowSelectedPopupCommand` は、チュートリアルがポップアップを表示中なら偽を返し、そうでなければ現在の手順の判定に従う（`TutorialManager.cs:341-349`）。ExploreJoppa は常に真を返す（`JoppaTutorial/ExploreJoppa.cs:27-30`）。
- キー入力の経路: 本文項目の `Alpha1` などのホットキーは、`QudTextMenuController.Update` の `CheckKeyInteractions(menuData, Activate)` に入る（`Qud.UI/QudTextMenuController.cs:8-12`）。コマンド名でも `char:` でもないので、`ParseUnityEngineKeyCode` を経て `ActivateContextButton` に回る（`Qud.UI/QudBaseMenuController.cs:324-356`）。`activateHandlers` と `activateContextHandlers` が PopupMessage のどのメソッドにつながるかは、コードになくプレハブで決まる（`:75-79,455-469`）。直接 `OnActivateCommand` か `OnSelect` を呼べば、この配線には依存しない。

### 3.5 選択の確定、拒否、終了

- `Select(k)` の順序（`XRL.UI/ConversationUI.cs:539-571`）:
  1. `choice.Enter()` を呼ぶ。偽なら false を返す。
  2. `CurrentNode.Leave()` を呼ぶ。
  3. 遷移先を求める。`Target` が空なら同じノード、`"End"` なら null、`"Start"` なら開始ノード（`GetTargetNode`、`:589-615`）。
  4. `LastChoice` を更新し、`Entered` と `Left` を呼んで、`CurrentNode` を差し替える。
- `Enter` は `EnterElementEvent.Check` で決まる（`XRL.World.Conversations/IConversationElement.cs:257-264`）。パーツの `HandleEvent(EnterElementEvent)` の戻り値は `HandlePartDispatch` を通じて伝わり、偽なら全体が偽になる（`IConversationElement.cs:240-244`、`XRL.World.Conversations/EnterElementEvent.cs:55-68`）。
  - **拒否**された場合、`CurrentNode` と `LastChoice` は変わらず、同じノードが新しいポップアップ（新しいクロージャ）として描き直される。
  - 例 1: Trade パーツは `EnterElementEvent` で取引画面を開いてから false を返す（`XRL.World.Conversations.Parts/Trade.cs:30-34`）。
  - 例 2: WaterRitualBegin は、距離、Sifrah の確認、ドラム数を検査する（`XRL.World.Conversations.Parts/WaterRitualBegin.cs:28-75`）。
- `Escape()` は `AllowEscape` が偽なら false を返す。真なら `CurrentNode = null` にしてループを終える（`XRL.UI/ConversationUI.cs:573-587`）。
- 終了時の後始末は `Leave`、`Left`、`AfterConversationEvent`、`Dispose` の順である（`:430-433`）。その後、`finally` で `Reset()` と `PopGameView(bHard:true)` が走る（`:385-393`）。`Reset()` は `Transmitter` と `Receiver` を消さない（`:436-450`）。

### 3.6 会話の中から開くもの

- **取引**: 二つの経路がある。
  - 下段の `trade` を選ぶと -2 が返り、`Trade.ShowScreen()`、`TradeUI.ShowTradeScreen(Trader)` と進む（`ConversationUI.cs:527-528`、`Trade.cs:98-101`）。
  - `[begin trade]` の選択肢（`Trade.cs:24-28`）を選ぶと、`Enter` の中で同じ画面が開く。
  - Modern では `TradeScreen.show(...).Result` で待つ。結果が REFRESH、NEXT、TOP なら再計算し、それ以外なら戻る（`XRL.UI/TradeUI.cs:456-463`）。取引の前に `Popup.ShowFail`、`Popup.Show`、`ShowYesNo` が出ることがある（`:357-409`）。ビュー名は `"ModernTrade"`（`Qud.UI/TradeScreen.cs:17`）。
  - 戻った後は、同じノードが描き直される。
  - 下段の Trade ボタンが出るのは `Trade.Visible` のときに限る。条件は、`Enabled`、`AllowEscape`、`Trade.Choice != null`、`Choice.CheckPredicates()` のすべてである（`Trade.cs:50-53`）。`Choice` は、その会話で最初に Initialize された Trade パーツの親選択肢である（`:36-43`）。`Enabled` は、話者が同じか隣のセルにいることを要求する（`:55-89`）。
- **Look**: -3 を返すと、`InventoryActionEvent.Check(話者, Listener, 話者, "Look")` が走る（`ConversationUI.cs:530-531`）。`Description` パーツは Modern では `NewPopupMessageAsync(...).Result` を呼ぶ（`XRL.World.Parts/Description.cs:333-365`）。`NewPopupMessageAsync` は `"DynamicPopupMessage"` を積み、`copyWindow` の複製で表示する（`XRL.UI/Popup.cs:751-799`）。その後 `LookedAt` と `AfterLookedAt` を発火する（`Description.cs:374-375`）。
- **クエスト**: QuestHandler の `EnteredElementEvent` は `StartQuest` などを呼ぶ（`XRL.World.Conversations.Parts/QuestHandler.cs:107-125`）。`StartQuest` は `PopupStartQuest` を経て `Popup.Show("You have received a new quest, ...")` を出す（`XRL/XRLGame.cs:535-546,577`、`XRL.World/Quest.cs:193-196`）。
- **水の儀式**: `ShowYesNoCancel` で Sifrah を尋ねるのは、Sifrah が導入済みで、かつ `OptionSifrahWaterRitual` が "Never" でも "Always" でもないときに限る（`WaterRitualBegin.cs:36-53`）。未導入なら "Never" になり、空の設定も "Never" になる（`XRL.UI/Options.cs:1016-1030`）。秘密を売る処理は `Popup.PickOption` を呼ぶ（`WaterRitualSellSecret.cs:64`）。
- **入れ子のポップアップの見分け方**:
  - `Popup.Show` は `ShowBlock` を経て、PopupID なしで `WaitNewPopupMessage` を呼ぶ（`XRL.UI/Popup.cs:658-671,1118-1141`）。
  - Modern の `PickOption` は、会話と同じ `"option:N"` の語彙で、同じ単体ウィンドウを使う。PopupID は既定値の null である（`:1650,1709-1760`）。
  - `CheckLost` は、最初のノードの前に `Popup.Show` を出すことがある（`ConversationUI.cs:452-471`）。
  - したがって、会話ノードとそれ以外を分けるのは **PopupID の `"Conversation:"` 接頭辞**だけである。

## 4. レシピ表

| modal | wait_kind | trigger_for_probe | detect | read | answer | cancel | Harmony |
|---|---|---|---|---|---|---|---|
| M1 会話ノード | `WaitNewPopupMessage` の `complete.Task.Wait()`（RenderMapBehind なら `Wait(33)` のループ） | (a) wish `conv:<ConversationID>[:<Blueprint>]`（`Wishing.cs:52-57`）。ID は実行時に `Conversation.Blueprints.Keys` を列挙して選ぶ。(b) `var m=The.Player.CurrentZone.FindObject("Mehmet"); The.Player.SystemMoveTo(m.CurrentCell.GetFirstEmptyAdjacentCell()); ConversationScript.AttemptConversation(The.Player, m);` | ブリッジ: `ConversationUI.CurrentConversation!=null`、かつ `GetGameViewStackCopy()` の末尾が `"PopupMessage"`、その下に `"Conversation"` がある。UI タスク: `w=(PopupMessage)UIManager.getWindow("PopupMessage")` について、`w.PopupID?.StartsWith("Conversation:")`、`w.commandCallback!=null`、`w.selectCallback!=null` がすべて真。トークンは `w.commandCallback` の参照 | UI タスク: 話者 `w.contextText.text`、本文 `w.Message.text`（`{{y|…\n\n}}` を剥がす）、選択肢 `w.controller.menuData[i].text/command`、下段 `w.controller.bottomContextOptions[*].command`（Look/trade/Cancel）。メタ情報（プレイヤーには見えない）: `option:i` を `ConversationUI.CurrentChoices[i]` に対応させ、`.ID/.Target/.Predicates/.Parts` の型名、`.Visited`、`CurrentNode.ID`、`CurrentConversation.ID` を読む | 別の UI タスクで、トークン、PopupID、両コールバック非 null を再確認する。そのうえで `w.OnActivateCommand(w.controller.menuData[k])` を呼ぶ（text は非 null）。`OnSelect` でもよい。下段は `bottomContextOptions` の実物を渡す。`Hide` は呼ばない | `bottomContextOptions` の command `"Cancel"` の項目を `OnActivateCommand` に渡す（`AllowEscape` のときだけ存在する）。なければ `[End]` の選択肢で終える | 不要 |
| M2 会話からの取引 | `TradeScreen.show(...).Result` | M1 の (b) を商人に対して行い、下段の `trade` を選ぶ（`[begin trade]` の選択肢でもよい）。対象は MakeCamp のカブトムシか、Joppa の商人（在否は実機で確かめる） | 両スレッド: `CurrentGameView=="ModernTrade"`、かつ `"Conversation"` がスタックにある | 取引ファミリーに委ねる | 取引ファミリーに委ねる。閉じると M1 の同じノードに戻る | 取引ファミリーに委ねる | 取引ファミリーの結論に従う |
| M3 Look（会話内） | `NewPopupMessageAsync(...).Result` | M1 で下段の `Look` を選ぶ | `CurrentGameView=="DynamicPopupMessage"` のとき、`windowsByName` のうち "PopupMessage #" で始まりアクティブな複製を探す（UI スレッド） | 複製の `Message.text` と `contextText.text` | 複製の `OnActivateCommand(bottomContextOptions` のうち command `"Accept"` の項目 `)`。Story があれば `"Story"` を選ぶと BookUI に進む | `"Accept"`（hotkey は `"Accept,Cancel"`） | 不要 |
| M4 会話内の入れ子のポップアップ | `WaitNewPopupMessage` の `Task.Wait()` | クエストを与える選択肢、`WaterRitual` の選択肢、ShowFail を誘う選択肢 | UI タスク: 単体ウィンドウの `PopupID` が `"Conversation:"` で始まらず、両コールバックが非 null で、スタックに `"Conversation"` がある | ポップアップファミリー（F1）と同じ | F1 と同じ（`Accept`、`Yes`/`No`/`Cancel`、`option:N`） | F1 と同じ | 不要 |
| M5 会話セッション | ノード間ではゲームスレッドが走る | M1 と同じ | 開始: `ConversationUI.CurrentConversation!=null`。終了: null に戻り、`"Conversation"` がスタックから消える | `ConversationUI.Speaker`、`CurrentConversation.ID` | （応答なし） | Cancel か End | 不要 |

## 5. 主張一覧

- **C-F2-conversation-01**（high）Modern の会話ループは、各ノードで `Render()`、`Popup.ShowConversation` の順に呼び、返り値で Escape、Trade、Look、`Select(num)` に分岐する。分岐は**ゲームスレッド**で行われる。根拠: `XRL.UI/ConversationUI.cs:418-429,514-537`、`Qud.UI/UIManager.cs:55`。
- **C-F2-conversation-02**（high）`ShowConversation` は、下段を [Look, trade?, Cancel?]、本文を `command="option:i"` の項目にし、PopupID `"Conversation:"+Title` で `WaitNewPopupMessage` を呼ぶ。根拠: `XRL.UI/Popup.cs:1571-1615`、`Qud.UI/PopupMessage.cs:72-77,255-285,693-713`。
- **C-F2-conversation-03**（high）ゲームスレッドは `uiQueue.awaitTask` で単体の `PopupMessage` を表示させた後、`complete.Task.Wait()` で止まる。RenderMapBehind のときは `Wait(33)` のループで止まる。根拠: `XRL.UI/Popup.cs:823-909`、`QupKit/ThreadTaskQueue.cs:135-155`。
- **C-F2-conversation-04**（high）`ConversationUI.Select` を外から呼ぶ方式は誤りである。`Select` は、ポップアップが返った後にゲームスレッドの `Render` が呼ぶ。外から呼ぶと、ポップアップが待っている間に `CurrentNode` と `LastChoice` を書き換え、その後ゲームスレッドがもう一度 `Select(num)` を呼ぶ。根拠: `XRL.UI/ConversationUI.cs:521-535,539-571`、`XRL.UI/Popup.cs:908-914`。
- **C-F2-conversation-05**（high）正しい応答口は、UI スレッドで単体 `PopupMessage` の `OnActivateCommand(item)` か `OnSelect(item)` を呼ぶことである。どちらも `complete.SetResult` の後に `Hide()` を呼ぶ。`onHide` の `TrySetCanceled` は、結果の設定後なので何もしない。根拠: `Qud.UI/PopupMessage.cs:926-944,1083-1104`、`XRL.UI/Popup.cs:834-877`。
- **C-F2-conversation-06**（high）`OnActivateCommand` の経路では、コールバックが `i.text.Replace` を呼ぶ。渡す項目は `controller.menuData` か `bottomContextOptions` の実物（text は非 null）に限る。根拠: `XRL.UI/Popup.cs:834-852`、`:1587-1592`、`Qud.UI/PopupMessage.cs:781-782`。
- **C-F2-conversation-07**（high）`ShowConversation` の結果の初期値は 0 である。認識できない command（例: 手で作った項目の command の誤り）で完了させると、エラーにならず、最初の選択肢が選ばれる。根拠: `XRL.UI/Popup.cs:1583,1594-1614`、`XRL.UI/ConversationUI.cs:533-534`。
- **C-F2-conversation-08**（high）会話ノードは PopupID で見分ける。同じ単体ウィンドウを、入れ子の `Popup.Show`（PopupID なし）と Modern の `PickOption`（同じ `option:N` の語彙で、PopupID は既定値 null）も使うからである。根拠: `XRL.UI/Popup.cs:658-671,1138-1141,1650,1709-1760,826`。
- **C-F2-conversation-09**（high）「ノードが応答待ち」の述語は、UI スレッドで評価する。条件は、`CurrentGameView=="PopupMessage"`、PopupID が `"Conversation:"` で始まる、`commandCallback!=null`、`selectCallback!=null` の四つである。`ShowPopup` は両方のコールバックを設定し、応答のどの経路も片方しか消さないので、両方が非 null なら未応答である。根拠: `Qud.UI/PopupMessage.cs:771-782,926-944,985-991,1040-1045,1055-1059`。
- **C-F2-conversation-10**（high）エンジン自身のチュートリアルも、`CurrentGameView=="PopupMessage"` と `PopupMessage.lastPopupID.StartsWith("Conversation:"...)` で会話ポップアップを検出している（UI スレッドの LateUpdate）。根拠: `JoppaTutorial/MakeCamp.cs:151-157`、`Qud.UI/PopupMessage.cs:249,874`。
- **C-F2-conversation-11**（high）読み取りと応答は、別々の UI タスクで行う（あいだに LLM の待ち時間が入る）。そのため、応答のタスクでは `commandCallback` の参照（トークン）が読み取り時と同じかを再確認する。単体ウィンドウは、次のノードや入れ子のポップアップに再利用され、`ShowPopup` がコールバックを上書きするからである。根拠: `Qud.UI/PopupMessage.cs:779-780`、`XRL.UI/Popup.cs:826-884`。
- **C-F2-conversation-12**（high）ブリッジスレッドからは、`GameManager.Instance.GetGameViewStackCopy()` で安全にビューのスタックを読める（`GameViewStack` のロックの中で読むため）。会話中は `"Conversation"` が積まれ、ノードの表示中はその上に `"PopupMessage"` が積まれる。根拠: `GameManager.cs:1441-1463,1493-1542`、`XRL.UI/ConversationUI.cs:377,392`、`XRL.UI/Popup.cs:829,910`。
- **C-F2-conversation-13**（high）Legacy と同等のテキストは、UI スレッドで PopupMessage のフィールドから作れる。話者は `contextText.text`、本文は `Message.text`、選択肢は `controller.menuData[i].text`、使えるボタンは `bottomContextOptions[*].command` から得る。`option:i` は `CurrentChoices[i]` に対応する（選択肢のリストが `CurrentChoices` と同じ順で作られるため）。根拠: `Qud.UI/PopupMessage.cs:777-782,852-856`、`XRL.UI/UITextSkin.cs:54,158-167`、`XRL.UI/ConversationUI.cs:517`。
- **C-F2-conversation-14**（medium）`Choice`/`Node` の `GetDisplayText` を、ゲームスレッド以外から呼んではならない。プールされた `Event.NewStringBuilder` を使い、`DisplayTextEvent`、`ColorTextEvent`、`GetChoiceTagEvent` を発火するからである。メタ情報には、純粋なフィールド（`ID`、`Text`、`Target`、`Predicates`、`Parts`、`Hash`/`Visited`）だけを使う。根拠: `XRL.World.Conversations/IConversationElement.cs:34-54,175-202`、`XRL.World.Conversations/Choice.cs:20-56,84-107`。
- **C-F2-conversation-15**（high）表示されている選択肢は、すでに述語を通っている。隠れた条件の本体は、パーツの `EnterElementEvent` での拒否である。偽は `HandlePartDispatch` を通じて `Select` の false になり、ノードは変わらない。拒否されたことは、応答の前後で `CurrentNode` の参照と `LastChoice` が変わらないことで分かる。根拠: `XRL.UI/ConversationUI.cs:502-510,549-567`、`XRL.World.Conversations/IConversationElement.cs:240-244,257-264,385-392`、`XRL.World.Conversations/EnterElementEvent.cs:55-68`、`XRL.World.Conversations.Parts/Trade.cs:30-34`、`XRL.World.Conversations.Parts/WaterRitualBegin.cs:28-75`。
- **C-F2-conversation-16**（high）取引の遷移は、下段の `trade`（-2）か `[begin trade]` の選択肢から `TradeUI.ShowTradeScreen` に入る。Modern では `TradeScreen.show(...).Result`（ビュー `"ModernTrade"`）で待ち、閉じると同じノードが描き直される。下段の Trade ボタンが出るのは `Trade.Visible` のときに限り、そのためには話者が隣接していなければならない。根拠: `XRL.UI/ConversationUI.cs:527-528`、`XRL.World.Conversations.Parts/Trade.cs:36-53,82-89,98-101`、`XRL.UI/TradeUI.cs:456-463`、`Qud.UI/TradeScreen.cs:17`。
- **C-F2-conversation-17**（medium）wish `conv:` は、ワールドに置かれていない話者で会話を開く。したがって、隣接の条件を満たさず、取引の遷移は試せない。根拠: `XRL.World.Capabilities/Wishing.cs:52-57`、`XRL.World.Conversations.Parts/Trade.cs:82-89`、`XRL.World.Parts/ConversationScript.cs:437-448`。
- **C-F2-conversation-18**（high）会話の Look（-3）は、`Description` の Modern 分岐で `NewPopupMessageAsync(...).Result`（`"DynamicPopupMessage"`、`copyWindow` の複製）を開く。閉じた後に `LookedAt` と `AfterLookedAt` を発火するので、本物の Look の副作用を持つ。根拠: `XRL.UI/ConversationUI.cs:530-531`、`XRL.World.Parts/Description.cs:333-375`、`XRL.UI/Popup.cs:751-799`。
- **C-F2-conversation-19**（high）会話の中の入れ子のポップアップには、次のものがある。どれも PopupID を持たない単体ウィンドウで表示される。
  - クエスト開始の `Popup.Show`（QuestHandler → StartQuest → PopupStartQuest → `Quest.ShowStartPopup`）
  - 迷子の解消（CheckLost）
  - 水の儀式の YesNoCancel。Sifrah が未導入か設定が "Never" なら出ない
  
  根拠: `XRL.World.Conversations.Parts/QuestHandler.cs:107-125`、`XRL/XRLGame.cs:535-546,577`、`XRL.World/Quest.cs:193-196`、`XRL.UI/ConversationUI.cs:452-471`、`XRL.World.Conversations.Parts/WaterRitualBegin.cs:36-53`、`XRL.UI/Options.cs:1016-1030`、`XRL.UI/Popup.cs:2365-2388`。
- **C-F2-conversation-20**（high）正規の終了は二つある。一つは `Cancel`（-1）から `Escape()` で `CurrentNode=null` にする経路で、`AllowEscape` のノードにしか Cancel ボタンがない。もう一つは `Target=="End"` の選択肢である。終了後は、`Leave`/`Left`/`AfterConversationEvent`/`Dispose` の後に `finally` で `Reset()` と `PopGameView` が走る。`Reset` は `Transmitter` と `Receiver` を消さない。根拠: `XRL.UI/Popup.cs:1574-1577`、`XRL.UI/ConversationUI.cs:385-393,430-450,573-587,597-600`。
- **C-F2-conversation-21**（high）`Hide()` で閉じると、`onHide` が `TrySetCanceled` を呼ぶ。キャンセルされたタスクに `Task.Wait()` をかけると AggregateException が投げられ、`Popup.cs:910` の `PopGameView` が実行されない。その結果、`"PopupMessage"` がビューのスタックに残る。例外は会話の `finally`（`Reset`、`PopGameView`）を通り、呼び出し元まで伝わる。根拠: `XRL.UI/Popup.cs:873-877,908-914`、`Qud.UI/PopupMessage.cs:1083-1104`、`XRL.UI/ConversationUI.cs:385-393`。
- **C-F2-conversation-22**（high）`Keyboard.PushKey` と `PushCommand` は、Modern の会話には答えられない。getvk で待つ `Input()` は `RenderClassic` からしか呼ばれないからである。GameManager の会話レイヤーの PushKey（Escape/Tab）は、この getvk ループ向けである。根拠: `XRL.UI/ConversationUI.cs:184-236,262-264,421-428`、`GameManager.cs:2500-2510`。
- **C-F2-conversation-23**（high）会話ノードの応答待ちの間、ゲームスレッドは `gameQueue` を回さない。ブリッジが `gameQueue` に積んだ読み取りは、ノードの表示中は実行されない。RenderMapBehind のループも、`gameQueue` を回さない `RenderBaseToBuffer` を呼ぶだけである。そのため、読み取りは UI タスクで行う。根拠: `XRL.UI/Popup.cs:896-909`、`XRL.Core/XRLCore.cs:2436-2446,2600-2605`。
- **C-F2-conversation-24**（medium）人間のキー操作の経路は、プレハブの配線に依存する。本文項目の数字ホットキーは `ActivateContextButton` に回り、`activateHandlers` と `activateContextHandlers` から PopupMessage のメソッドへの配線はコードにない。直接 `OnActivateCommand` か `OnSelect` を呼ぶ方式は、この配線に依存しない。根拠: `Qud.UI/QudTextMenuController.cs:8-12`、`Qud.UI/QudBaseMenuController.cs:75-79,324-356,438-469`。
- **C-F2-conversation-25**（high）会話ノードの検出、読み取り、応答（M1、M3、M4、M5）に Harmony は要らない。必要な状態（`PopupID`、`commandCallback`、`selectCallback`、`controller`、`Message`、`contextText`、`ConversationUI` の statics）と応答メソッド（`OnActivateCommand`、`OnSelect`）は、どれも public である。根拠: `Qud.UI/PopupMessage.cs:20-42,247-249,926-944`、`XRL.UI/ConversationUI.cs:135-157`。

## 6. 実機でしか分からないこと

1. UI タスクから単体ウィンドウの `OnActivateCommand(menuData[k])` を呼んだとき、ゲームスレッドが `Select(k)` に進み、次のノードが同じ単体ウィンドウに再表示されるか。確かめる際は、トークンが変わることと、`LastChoice` が更新されることを見る。
2. PopupID の接尾辞の実際の形。`Popup.cs:1613` からは `"Conversation:{{W|名前}}"` になるはずである。一方 `MakeCamp.cs:154` は `"Conversation:"+beetle.ID` と比べている。`RenderNodeEvent` が書き換えるのか、チュートリアル側の比較が古いのかは、静的には決まらない。そこで検出には接頭辞しか使わない。
3. `Hide` を先に呼んだ場合に投げられる例外が、どこで捕捉されるか。また、スタックに残った `"PopupMessage"` が後続にどう影響するか（試す必要はなく、避けることだけを確かめる）。
4. RenderMapBehind の状態を持つ会話がどれか。そのような会話で `Wait(33)` のループ中に UI タスクで答えても問題がないか。
5. プレハブで、`activateHandlers`/`activateContextHandlers` が `OnSelect`/`OnActivateCommand` のどちらに配線されているか。人間の操作と同じ経路を再現したい場合に限って意味がある。
6. 新規の Joppa 開始時に、取引の遷移を試せる商人がいるか（Tam など）。`Conversation.Blueprints` にある Joppa の会話 ID は何か。
7. `ControlManager.ResetInput` や `EnforceSuspensionContext` の副作用で、UI タスクから答えた直後の人間の入力やナビゲーション文脈が乱れないか。

## 7. 未解決の問い

- 会話の中から別の `HaveConversation` を呼ぶ入れ子の会話は、statics を上書きし、`Reset` で外側を壊す（`ConversationUI.cs:361-394`）。これが実際に起きる会話はあるか。
- `CurrentChoices[i]` のフィールドを UI スレッドから読むとき、`Hash` の遅延初期化（`Choice.cs:20-38`）による書き込みは実害がないか。ゲームスレッドは待機中なので競合はないはずだが、RenderMapBehind のループ中の `Sidebar.UpdateState` と干渉しないか。
- 取引、PickGameObject（`GiveArtifact`、`ReceiveItem`）、PickSeveral（`LibrarianGiveBook`、`GiveReshephSecret`）、Sifrah の各画面が会話から開いたときの応答レシピは、それぞれのファミリーの結論に依存する。
- ゲームパッドが接続されていると、`CancelButton` と `SingleButton` の text が変わる（`PopupMessage.cs:255-285,331-361`）。command は同じなので応答には影響しないが、Legacy と同等のテキストの表記は変わる。
