# 07. Legacy UI の検証: `OptionModernUI=No` で状況把握と制御は単純になるか

> 静的解析だけで書いた。ゲームは起動していない。推論には **[推論]** を付ける。

> **監督者注（2026-09-25、Fable）。** 本書は「Modern UI のままでよいか」という問いに答えるために、オーナー決定の前に依頼したものである。オーナーはその後、配信画面のアートワークを優先して **Modern UI を画面に残す方向（方向 2）** を選んだ。したがって §10 の「Legacy を Plan A に」は採らない。本書は Plan B（Legacy フォールバック）の証拠として残し、§4 の応答トークン表と §9 のプローブ L0〜L11 は、08 §8.2 の条件でフォールバックが決まったときに使う。方向 2 の静的検証は `08-modern-ui-modal-driving.md` にある。 2026-09-26 追記: R5 は実機で通った（`probes/R5-modal-driver/results/`、08 §6.3）。本書は Plan B の証拠として残す。

## 0. 結論

オーナーの見立ては、Popup 系とステータス画面群については正しい。`OptionModernUI=No` にすると `UIManager.UseNewPopups` が偽になる(`Qud.UI/UIManager.cs:55`)。すると同期版の Popup API はどれも、`RenderBlock` で文字を組み、`DrawBuffer` で `TextConsole.CurrentBuffer` に写し、ゲームスレッドで `Keyboard.getvk` か `getch` を待つループに入る。UGUI の canvas は、ビューが切り替わっても表示されなくなる(`GameManager.cs:1607-1614`)。

ただし、単純になるのは入力と観測の**経路**であって、得られる**情報**は増えない。Modern のポップアップは、選択肢や command を構造のまま持っている(`Qud.UI/PopupMessage`)。Legacy では、それらは Popup メソッドの局所変数に閉じている。Harmony を使わない限り、mod が読めるのは 80x25 の文字格子だけになる。

判定の要点は次の五つ。

| 問い | 判定 | 根拠の節 |
|---|---|---|
| (A) Legacy で「ScreenBuffer の文字 + ゲームスレッドの getvk」に乗るモーダルの割合 | ゲーム中(キャラクター作成の後)のモーダル 24 系統のうち **22 系統は完全に乗る**。残る 2 系統(キー再割り当て、代名詞のカスタム作成)も入口は文字画面で、内部の小ダイアログだけが UGUI に出る。24 系統のうち 4 系統(Look、PickTarget/PickDirection/射撃、Sifrah、ThinWorld)は Modern でも getvk なので、Legacy で変わるのは画面に文字が載るかどうかだけである | §3、§6 |
| 例外 | `*Async` 系の Popup API と `ForceNewPopup`(常に UGUI)、キャラクター作成(両モードで UGUI)、終局のクレジット(入力なし)、ロード状況の表示(非モーダル)、メインメニューの Mods 画面。チュートリアルは Legacy では選べない | §6 |
| (B) エージェントが失うもの | ポップアップの構造化データ。長文ポップアップの一括取得(スクロールが要る)。配信の見た目(サイドバーが地図の約 24 列を覆い、左右に入れ替わる) | §7 |
| 06 §3.4 の応答規則 | **そのままでは動かない**。`ShowBlock` は `PushCommand("Accept")` では閉じない。系統ごとの応答トークン(§4)に置き換える | §4、§5 |
| (D) 推奨 | **Legacy UI を Plan A にする。tiles は ON**。条件は §9 のプローブ L1〜L6 が第 1 週のうちに通ること。Modern は配信の見た目を優先するときの Plan B に下げる | §10 |

## 1. 前提と引用

| 項目 | 内容 |
|---|---|
| コード | `~/Dev/coq-decompiled_stable`(`Properties/AssemblyInfo.cs:8` は `AssemblyVersion("2.0.211.56")`)。以下、コードの引用はこのルートからの相対パスで書く |
| データ | `Base/` = `.../CoQ.app/Contents/Resources/Data/StreamingAssets/Base` |
| 03・06 との対応 | 03 と 06 は `NEW/` の行番号を使っている。本書は stable の行番号だけを使う。例として、06 §3.2 の `GameManager.cs:3178-3182`(ビュー切り替え時の入力消去)は、stable では `GameManager.cs:3172-3182`(`Update` からの呼び出し)と `:1573-1581`(`UpdateView` 本体、`Keyboard.ClearInput()` は `:1580`)に当たる |
| Harmony | 03 §4.2 のとおり、arm64 ネイティブ起動では使えない前提で書く |

## 2. Legacy で何が一本化されるか

### 2.1 振り分けの鍵は二つある

一つ目は Popup の振り分けである。`Options.ModernUI` は `OptionModernUI` の値から設定され(`XRL.UI/Options.cs:34`、`:1296-1303`)、`UIManager.UseNewPopups` はその値を返すだけである(`Qud.UI/UIManager.cs:55`)。`Popup.cs` の分岐点(`:648, 676, 968, 1038, 1092, 1138, 1198, 1440, 1653, 1709, 2258, 2371`)はすべてこれを見る。

二つ目は UGUI canvas の表示である。ゲーム側がビューを積むと、UI スレッドの `UpdateView` がそのビューの `UICanvas` を開く。ところが、開くのは `ModernUI` が真のときだけで、偽なら `currentWindow = null` にする(`GameManager.cs:1588`、`:1607-1614`)。つまり Legacy では、`[UIView]` 属性で結び付いた Modern の画面は、ビュー名が積まれても出てこない。出てくるのは、コードが `UIManager.copyWindow` や `createWindow` で直接開く窓だけになる(§6 の例外はすべてこれ)。

Legacy では、画面全体も 80x25 の文字コンソールに切り替わる。`ShouldForceFullscreen` が常に真になり(`GameManager.cs:2035-2037`)、Modern の Stage、PlayerStatusBar、AbilityBar、MessageLog、NearbyItems、Minimap の各窓は隠される(`:2868-2895`、`:3366-3377`)。`consoleTileAreaHandler` は `!Options.ModernUI` のときに有効になる(`:2910-2912`)。

### 2.2 描画: モーダルの文字は `CurrentBuffer` にしか残らない

`TextConsole.DrawBuffer` は、`bSkipIfOverlay && ModernUI` のときだけコピーを省く(`ConsoleLib.Console/TextConsole.cs:145-163`、条件は `:151`)。Legacy では、どの `DrawBuffer` 呼び出しも `CurrentBuffer` に写る。写すときに、そのときのビュー名が `CurrentBuffer.ViewTag` に入る(`:154`)。

ここに一つ落とし穴がある。**AfterRender コールバックはモーダルの文字を見ない。** コールバックが呼ばれるのは `RenderMapToBuffer` と `RenderBaseToBuffer` の中だけで(`XRL.Core/XRLCore.cs:2430-2432`、`:2462-2464`、`:2506-2508`)、Popup のループは `ScrapBuffer` に書いて `DrawBuffer` するだけだからである。したがって、モーダルの文字を読む確実な場所は次の一つに絞られる。

- `lock (TextConsole.BufferCS)` の中で `TextConsole.CurrentBuffer` を読む(`TextConsole.cs:29, 31`)。
- 読むきっかけには `TextConsole.DrawBufferEvent`(`AutoResetEvent`、`:37`)を使う。`DrawBuffer` のたびに `Set` される(`:162`)。これを待つメソッド `TextConsole.WaitForDraw`(`:165-169`)はあるが、呼び出し元は 0 件である(grep)。ブリッジスレッドが待っても、誰の通知も奪わない **[推論: 静的な参照数からの判断]**。

`Popup.ScrapBuffer`(`XRL.UI/Popup.cs:144`)と `TextConsole.ScrapBuffer`(`TextConsole.cs:11`)は別の静的フィールドで、どちらも描画の途中で書き換わる。読む対象にはしない。

本文の全文が欲しいときは別の道がある。`Show`、`ShowBlock`、`ShowSpace`、`ShowBlockPrompt` などは、分岐の**前**に `MessageQueue.AddPlayerMessage(Message)` を呼ぶ(`Popup.cs:1136`、`:1091`、`:966` ほか)。これは `XRLCore.CallNewMessageLogEntryCallbacks` を発火する(`XRL.Messages/MessageQueue.cs:138-149`)ので、mod は両モードとも、ポップアップが出る前に全文を受け取れる。一方、`PickOption` の Intro と選択肢はログに流れない。こちらは格子から読むしかない。

### 2.3 入力: 一本のキューと、それを消す三つの場所

Legacy のモーダルはすべて `Keyboard.GetNextKey` からキーを受け取る(`ConsoleLib.Console/Keyboard.cs:956-1352`、`getvk` / `getch` は `:1354-1370`)。キューは二本ある。

| キュー | 公開 | 積む API | 上限 |
|---|---|---|---|
| `KeyQueue` | public(`Keyboard.cs:108`) | `PushKey(XRLKeyEvent, bAllowMap)`(`:777-796`) | `bCapInputBuffer` が真なら 3 件を超えて積めない(`:786`) |
| `MouseEventQueue` | **private**(`:130`)。件数は `HasMouseEvent()`(`:865`)で見るか、リフレクションで読む | `PushMouseEvent(ev, x, y, data)`(`:820-849`)、`PushCommand(cmd)` は `"Command:"+cmd` の糖衣(`:723-726`) | 同上(`:827`) |

`GetNextKey` はマウスイベントを先に返す(`:966-999`)。スレッドを問わず積めるので、ブリッジスレッドから直接積める。`gameQueue` を回すのは `pumpActions: true` のときだけで(`:1040`)、Legacy でそうしているのは `InventoryScreen`(`XRL.UI/InventoryScreen.cs:468`)、`ConsoleTrade`(`XRL.UI/TradeUI.cs:735`)、`LegacySaveManagement`(`XRL.Core/XRLCore.cs:3938`)、`ShowBlockWithCopy`(`Popup.cs:707`)の四つしかない。ほかの Legacy モーダルの間は、Modern の `Task.Wait` と同じく `gameQueue` が止まる。

積んだものが消える場所は三つある。

1. **UI スレッドのビュー切り替え。** `Update` は `BufferUpdated` が立っていて、ビューが変わっていれば `UpdateView` を呼ぶ(`GameManager.cs:3172-3182`)。`UpdateView` は `Keyboard.ClearInput()` を呼ぶ(`:1580`)。
2. **Popup の入口。** `ShowBlock` と `ShowYesNo` は、ビューを積んだ直後に `ClearInput` する(`Popup.cs:1149-1150`、`:2281-2282`)。その後で最初の `DrawBuffer` が来る(`:1155`、`:2289`)。一方、`PickOption` の Legacy 分岐には入口の `ClearInput` がない(`:1764` 以降)。残っていたキーをそのまま食べる。
3. **PlayerTurn の冒頭。** `ClearMouseEvents(LeaveMovementEvents: true)` が移動以外のマウスイベントを消す(`XRLCore.cs:734`)。`KeyQueue` は消さない。

### 2.4 人間の打鍵はどう Legacy に届くか(`GameManager.cs:1898-1912`)

人間の入力は二つの道に分かれる。

- **束縛されていないキー**は、`OnGUI` → `pushKeyEvents` が `Keyboard.PushKey(new XRLKeyEvent(Event.current), bAllowMap: true)` で積む(`GameManager.cs:1813`、`:1888-1914`)。このとき `character` も入る(`Keyboard.cs:27-34`)。Legacy で `CurrentGameView` が `Popup:AskString` か `Popup:Text` のときは、束縛の有無にかかわらずすべてのキーをこの道で積む(`GameManager.cs:1823-1827`)。`OptionPushAZHotkeys=Yes` なら、Legacy では A〜Z も常にこの道に乗る(`:1898-1901`)。
- **束縛されたキー**は Rewired を経由して `UpdateInput` に届く(`:2163`)。そこで `PushCommand(name)` になる(`:2429-2474`)。ただし Menus レイヤーでは、Accept が `PushKey(Space)`、Cancel が `PushKey(Escape)` に変わる(`:2475-2489`)。Adventure では移動が `DoNavigate` を経て `CmdMove*` になる(`:2604-2613`)。

mod が真似るべきは、この道の**結果**のほうである。Legacy のモーダルが受け取っているのは「Space」「Escape」「文字付きのキー」「`Command:` 付きのマウスイベント」であって、`PushCommand("Accept")` ではない。`bAllowMap` は、人間が移動キーを付け替えたときに `getvk(MapDirectionsToArrows)` でテンキーに読み替えるための印にすぎない(`Keyboard.cs:1218`)。mod が NumPad キーを直接積めば関係なくなる。

## 3. 系統ごとの判定

列の意味は次のとおり。「文字」は、Legacy でその系統の文字が `DrawBuffer` 経由で `CurrentBuffer` に載るか。「待ち」は、Legacy でゲームスレッドが `getvk` / `getch` / `kbhit` のループで待つか。「UGUI」は、Legacy でも Qud.UI / UIManager を通る部分。

### 3.1 Popup API

| API | Legacy の経路 | 文字 | 待ち | UGUI | 備考 |
|---|---|---|---|---|---|
| `Show` / `ShowFail` | `ShowBlock` に委ねる(`Popup.cs:658-671`) | ○ | ○ | なし | `Suppress` か `_TextConsole == null` ならログに流すだけ |
| `ShowBlock` | `PushGameView("Popup:MessageBox")` → `RenderBlock` → `DrawBuffer` → `getvk`(`:1138-1188`) | ○ | ○(`:1158`) | なし | 抜けるのは Space、Enter、Escape だけ(`:1152`) |
| `ShowSpace` / `ShowBlockPrompt` / `ShowBlockSpace` | 同型のループ(`:1092-1116`、`:968-1012`、`:1038-1076`) | ○ | ○(`getch` `:1111`、`getvk` `:983`、`:1051`) | なし | |
| `ShowBlockWithCopy` | `:676-739` | ○ | ○(`pumpActions: true` `:707`) | なし | |
| `ShowAsync` / `ShowFailAsync` | ゲームスレッド上なら `Show`、それ以外なら `NewPopupMessageAsync`(`:639-656`、分岐は `:648`) | 条件付き | 条件付き | **ゲームスレッド外から呼ばれたとき** | |
| `PickOption` / `ShowOptionList` | `PushGameView("Popup:Choice")` → 枠と選択肢を `ScrapBuffer` に描く → `getvk`(`:1650-2009`、分岐 `:1709`) | ○ | ○(`:1916`) | `ForceNewPopup` のときだけ | 窓は最大 20 行、幅 74。はみ出すと `<More...>` が出る(`:1661-1665`、`:1884`、`:1889`) |
| `PickGameObject` / `PickSeveral` / `ShowColorPicker` | いずれも `PickOption` を呼ぶ(`:1520-`、`:2046-2138`、`:2222-2232`) | ○ | ○ | なし | |
| `PickOptionAsync` / `ShowOptionListAsync` / `ShowColorPickerAsync` | `ForceNewPopup: true` で `PickOption` を呼ぶ(`:1624-1643`) | × | × | **常に** | |
| `ShowYesNo` | `:2251-2324`、分岐 `:2258` | ○ | ○(`:2290`) | なし | `Suppress` は効かない(両モード共通) |
| `ShowYesNoCancel` | `:2365-2474`、分岐 `:2371` | ○ | ○(`:2413`) | なし | |
| `ShowYesNoAsync` / `ShowYesNoCancelAsync` | 常に `NewPopupMessageAsync`(`:2326-2358`) | × | × | **常に** | |
| `AskString` | `PushGameView("Popup:AskString")` → `getch`(`:1433-1518`、分岐 `:1440`) | ○ | ○(`:1453`) | なし | Legacy では `WantsSpecificPrompt` は使われない。確認語の比較は呼び出し側が行う(例: `CheckpointingSystem.cs:135`) |
| `AskNumber` | `PushGameView("Popup:AskNumber")` → `getch`(`:1191-1318`、分岐 `:1198`) | ○ | ○(`:1223`) | なし | |
| `AskStringAsync` / `AskNumberAsync` | 常に `NewPopupMessageAsync`(`:1320-1431`) | × | × | **常に** | |
| `ShowConversation` | 呼び出し元は `ConversationUI.Render` だけ(`XRL.UI/ConversationUI.cs:521`)。Legacy ではそもそも呼ばれない | — | — | — | 次の表を参照 |
| `WaitNewPopupMessage` / `NewPopupMessageAsync` | Legacy の同期 API からは呼ばれない | × | × | **常に** | |

### 3.2 ゲーム中の画面

| 系統 | Legacy の経路 | 文字 | 待ち | UGUI | 備考 |
|---|---|---|---|---|---|
| 会話 | `InternalConversation` のループが `UseNewPopups` で分岐し(`ConversationUI.cs:421-428`)、Legacy は `RenderClassic` → `TC.DrawBuffer(SB)` → `Input()` の `getvk`(`:184-235`、`:262-264`) | ○ | ○ | なし | ビュー名は両モードとも `Conversation`(`:377`)。`CurrentNode` と `CurrentChoices` は静的フィールドなので構造のまま読める |
| PickItem(拾う・しまう・選ぶ) | `ShowPickerInternal` の分岐(`XRL.UI/PickItem.cs:272`)。Legacy は `PushGameView("Popup:Item")` → `DrawBuffer` → `getvk`(`:336`、`:592-597`) | ○ | ○ | なし | Modern の `PickGameObjectScreen` は使われない |
| ステータス画面 8 種(技能・能力、キャラクター、所持品、装備、派閥、クエスト、ジャーナル、Tinkering) | `Screens.Show` / `ShowPopup` は `ModernUI && ModernCharacterSheet` のときだけ `StatusScreensScreen`(`XRL.UI/Screens.cs:45`、`:90`)。Legacy は `PushGameView("StatusScreens")` → `ScreenList[i].Show(GO)`(`:128-131`) | ○ | ○(各画面の `DrawBuffer` と `getvk`: `SkillsAndPowersScreen.cs:512-513`、`StatusScreen.cs:405-406`、`InventoryScreen.cs:461-468`、`EquipmentScreen.cs:339-340`、`FactionsScreen.cs:220-221`、`QuestLog.cs:124-125`、`JournalScreen.cs:574-575`、`TinkeringScreen.cs:413-414`) | なし | 所持品画面だけ `pumpActions: true` |
| 有効な効果 | `GameObject.ShowActiveEffects` → `BookUI.ShowBook`(`XRL.World/GameObject.cs:5246-5281`) | ○ | ○ | なし | 両モードとも `BookUI` 経由。Modern では `BookScreen` になる |
| メッセージ履歴 | `MessageQueue.Show` は Modern なら `StatusScreensScreen.show(7)`、Legacy なら `BookUI.ShowBook`(`XRL.Messages/MessageQueue.cs:78-88`) | ○ | ○ | なし | Modern 側は `ModernCharacterSheet` を見ない |
| 取引 | `TradeUI` の分岐(`XRL.UI/TradeUI.cs:456`)。Legacy は `PushGameView("ConsoleTrade")` → `DrawBuffer` → `getvk(pumpActions: true)`(`:465`、`:734-735`) | ○ | ○ | なし | |
| 能力一覧 | `AbilityManager.Show` の分岐(`XRL.UI/AbilityManager.cs:144`)。Legacy は `PushGameView("AbilityManager")` → `:338-339` | ○ | ○ | なし | |
| Look | `ShowLooker`(`XRL.UI/Look.cs:405`)は両モードとも `kbhit` + `getvk`(`:668-672`)。説明文を `Buffer` に描くのは Legacy だけ(`:521-640`)。Modern は `PickTargetWindow.currentText` と UGUI のツールチップに出し、`uiQueue.awaitTask` で待つ(`:519-523`、`:646-663`) | Legacy のみ ○ | ○(両モード) | なし | |
| PickTarget / PickDirection / 射撃 | 両モードとも `RenderMapToBuffer` → `DrawBuffer` → `getvk`(`XRL.UI/PickDirection.cs:28-56`、`XRL.UI/PickTarget.cs:87`、`:108`、`:159-164`、`:381`、`:786-791`)。案内文を `Buffer` に書くのは Legacy だけ(`PickDirection.cs:44-52`、`PickTarget.cs:117-131`、`XRL.World.Parts/MissileWeapon.cs:303`、`:343`、`:473-538`、`:785-790`) | Legacy のみ ○ | ○(両モード) | なし | `RenderMapToBuffer` を回すので AfterRender も発火する |
| 本 | `BookUI.ShowBookByID` / `ShowBook` の分岐(`XRL.UI/BookUI.cs:427`、`:464`)。Legacy は `PushGameView("Book")` → `DrawBuffer` → `getvk`(`:431-444`、`:468-481`) | ○ | ○ | なし | |
| Tinkering | `TinkeringScreen` の分岐(`XRL.UI/TinkeringScreen.cs:23`)。所持品の「Mod with tinkering」は Legacy だけ直接この画面を開く(`XRL.World.Parts/Physics.cs:2725-2735`) | ○ | ○ | なし | |
| サイバネティクス端末 / 汎用端末 | ビュー `CyberneticsTerminalScreen` は両モードで積む。Legacy は文字ループ(`XRL.UI/CyberneticsTerminal.cs:198-316`、`XRL.UI/GenericTerminal.cs:80-189`) | ○(タイプライター表示で 15 ms ごとに 1 文字進む `CyberneticsTerminal.cs:227-232`) | ○(`kbhit` + `getvk`。サイバネティクス側は `wait: false`) | なし | 表示途中の格子は本文の一部しか含まない。本文は `CyberneticsTerminal.Instance.CurrentText` から読める(`:14`、`:109`) |
| ヘルプ | `XRLManual.ShowHelp` の分岐(`XRL.Help/XRLManual.cs:192`)。Legacy は `PushGameView("Help")` → `:225-226` | ○ | ○ | なし | |
| Sifrah | 分岐なし。両モードとも `ScreenBuffer.Draw()`(`DrawBuffer` をスキップなしで呼ぶ `ConsoleLib.Console/ScreenBuffer.cs:180-184`)+ `getvk`(`XRL/SifrahGame.cs:343`、`:661-671`) | ○(両モード) | ○(両モード) | なし | |
| 代名詞・ジェンダーの変更 | 画面本体は文字ループ(`XRL/PronounAndGenderSets.cs:97`、`:204-206`、`:304`、`:551-553`)。入口は Legacy の `StatusScreen.cs:520` | ○ | ○ | **カスタム作成の小ダイアログ**(`CustomizeAsync().Result` `:223`、`:573`、`:589` → `BasePronounProvider.cs:683-702`、`Gender.cs:250`、`:264` の `*Async`) | 走行には要らない |
| システムメニュー(Esc) | `Popup.PickOption`(`XRLCore.cs:983-1022`)。ABANDON / QUIT の確認は `AskString` | ○ | ○ | なし | |
| レベルアップ・変異の選択 | `Popup.Show` / `ShowYesNo` / `PickOption`(03 §2.8) | ○ | ○ | なし | |
| 所持品の操作メニュー | `EquipmentAPI.TwiddleObject` → `ShowInventoryActionMenu` → `Popup.PickOption`(`Qud.API/EquipmentAPI.cs:30`、`:141`、`:154-185`)。`ModernPopupTwiddleObject` のビューを積むのは Modern だけ(`:159-162`) | ○ | ○ | なし | |
| ゲーム中のオプション | `OptionsUI.Show` の分岐(`XRL.UI/OptionsUI.cs:69`)。Legacy は `PushGameView("Options")` → `:329-330` | ○ | ○ | なし | |
| キー設定 | `KeyMappingUI` の分岐(`XRL.UI/KeyMappingUI.cs:73`)。Legacy は `PushGameView("Keymapping")` → `:229-230` | ○ | ○ | **再割り当ての小ダイアログ**(`KeybindsScreen.HandleRebindAsync(...).Wait()` `:333`) | 走行には要らない |
| 死亡時 | `CheckpointingSystem` は `ShowSpace` → `PickOption` → `AskString`(`XRL/CheckpointingSystem.cs:98-135`)。スコア画面は `GameSummaryUI` の分岐(`XRL.UI/GameSummaryUI.cs:29-37`)で、Legacy は `PushGameView("GameSummary")` → `DrawBuffer` → `getvk`(`:38`、`:93-96`) | ○ | ○ | なし | |
| ThinWorld | 分岐なし。`PushGameView("GameSummary")` → `getch`(`XRL.World.Parts/ThinWorld.cs:260`、`:278`)。確認は `AskString`(`:62`) | 演出に依存 **[推論]** | ○(両モード) | なし | |
| 終局 | 確認は `AskString`(`XRL.World.Conversations.Parts/EndGame.cs:162`)。クレジットは `UIManager.mainCanvas` 上の `EndgameCredits`(`:345`) | 確認のみ ○ | 確認のみ ○ | **クレジット**(入力は求めない) | |

### 3.3 常時表示とゲームの外

| 系統 | Legacy の経路 | 文字 | 待ち | UGUI | 備考 |
|---|---|---|---|---|---|
| サイドバー(HP、メッセージ、敵一覧) | `Sidebar.Render` の Legacy 分岐が `_Buffer` に書く(`XRL.UI/Sidebar.cs:787-1311`)。Modern 分岐は数値を更新するだけで何も書かない(`:793-834`) | ○ | 非モーダル | なし | AfterRender はこれより前に呼ばれる(03 §1.2)ので、`CurrentBuffer` を読む |
| ロード状況 | `Loading.SetLoadingStatus` は両モードとも `LoadingStatusWindow`(`XRL.UI/Loading.cs:76-86`) | × | 非モーダル | **常に** | |
| メインメニュー | 両モードとも `_Buffer` に描いて `getvk`(`XRLCore.cs:3636-3729`)。Legacy では Modern の `MainMenu` 窓が自分を隠す(`Qud.UI/MainMenu.cs:460-464`) | ○ | ○ | Mods 画面(`XRLCore.cs:3757`) | `Pick:Continue` などのマウスイベントを受ける(`:3773`、`:3778`) |
| Continue(セーブ選択) | Modern は `ModernSaveManagement`、Legacy は `XRLCore.SaveManagement()`(`:3780-3802`、`:3885-`)。`PushGameView("LegacySaveManagement")` → `DrawBuffer` → `getvk(pumpActions: true)`(`:3887`、`:3937-3938`) | ○ | ○ | ロード時の mod 不一致の確認(`:3428`、`:3448`) | `SaveManagement().Wait()` の中の `await` の続きは、ゲームスレッドの素の `SynchronizationContext`(`XRLCore.cs:3557-3559`)に Post されるので、スレッドプールで走る見込み **[推論]** |
| キャラクター作成 | `EmbarkBuilder.Begin` が UI コンテキストでモジュール窓を作る(`XRL.CharacterBuilds/EmbarkBuilder.cs:61-87`、`:329-335`)。分岐なし | × | × | **常に** | 06 のとおり人間が作る |
| 世界生成 | Modern だけ `WorldGenerationScreen` を出す(`EmbarkBuilder.cs:269-272`、`XRL.CharacterBuilds.Qud/QudGameBootModule.cs:235-238`)。Legacy は `WorldCreationProgress` が `DrawBuffer` する(`XRL.UI/WorldCreationProgress.cs:86`) | ○ | 非モーダル | なし | |
| チュートリアル | Legacy ではゲームモードの一覧から消える(`XRL.CharacterBuilds.Qud.UI/QudGamemodeModuleWindow.cs:107-114`) | — | — | — | 使えない |

## 4. 答え方: 系統ごとの応答トークン

06 §3.4 は、Legacy では「束縛されたコマンドは `PushCommand`、束縛されていないキーは `PushKey(bAllowMap:true)`」で答えるとしていた。各ループの終了条件を読むと、この規則では閉じないものがある。`ShowBlock` のループは Space、Enter、Escape のキーでしか抜けない(`Popup.cs:1152`)。`PushCommand("Accept")` はマウスイベントとして届き、ループは待ち続ける。人間の Enter が効くのは、`UpdateInput` が Accept を `PushKey(Space)` に変えているからである(`GameManager.cs:2475-2489`)。

Legacy のループの多くは、キーのほかに**意味の付いたマウスイベント**も受け付ける。番号や名前で答えが一意に決まり、`Keyboard.Char` や現在の選択位置に左右されないので、こちらを主に使う。

| 系統 | 推奨トークン | 代替 | 注意 | 引用 |
|---|---|---|---|---|
| ShowBlock 系 | `PushKey(Space)` | Enter、Escape | `PushCommand("Accept")` では閉じない | `Popup.cs:1152` |
| ShowYesNo | `PushMouseEvent("LeftOption:1")`(Yes)/ `"LeftOption:2"`(No) | `PushKey(Y)` / `PushKey(N)`(`RawCode` で判定) | Space と Enter はループを抜けるが、結果は `defaultResult` のままになる | `:2285`、`:2313-2320` |
| ShowYesNoCancel | `LeftOption:1` / `LeftOption:2` / `PushKey(Escape)` | Y / N | Space は Yes に読み替えられる。`Command:Accept` / `Command:V Negative` / `Command:Cancel` も効く | `:2414-2433`、`:2463-2470` |
| PickOption 系 | `PushMouseEvent("Choice:N")`(0 起点の番号) | Escape で -1(`AllowEscape` のとき) | ホットキーは `Keyboard.Char` で照合する。`PushKey(KeyCode)` だけでは `character` が `'\0'` になり一致しない。下段ボタンは `"Command:" + hotkey` | `:1925`、`:1948`、`:1955`、`Keyboard.cs:36-43` |
| AskString | `PushMouseEvent("SubmitString:" + 文字列)` | 1 文字ずつ `PushKey(code, char)` + Enter | 1 文字ずつ積むと上限(§5)で落ちる。`MinLength` 未満だと受け付けない | `Popup.cs:1454-1463` |
| AskNumber | `PushMouseEvent("SubmitString:" + 数値)` | NumPad で増減 + Enter | | `:1228-1236` |
| 会話(classic) | `PushMouseEvent("Click:N")` | `PushKey(D1..D9)`、`A..Z`(vk で判定するので文字は不要)、Escape | 取引は `Command:CmdStartTrade` | `ConversationUI.cs:266-320` |
| PickItem | `PushMouseEvent("ItemSelected", 0, 0, gameObject)` | 文字付きの `PushKey` | Select と Store のスタイルでは、その物体がそのまま返る。Get のスタイルでは `EquipmentAPI.TwiddleObject` の操作メニュー(PickOption)へ進む | `PickItem.cs:602`、`:680-690`、`:706-713` |
| PickDirection | `PushKey(NumPad1..9)` | NumPad5 または `Command:CmdTargetSelf` で自分 | | `PickDirection.cs:53-99` |
| メインメニュー | `PushMouseEvent("Pick:Continue")` / `"Pick:New Game"` | C / N | | `XRLCore.cs:3773`、`:3778` |
| Legacy のセーブ選択 | `PushMouseEvent("Play:N")` | NumPad8/2 + Space | | `:3963-3967` |
| 移動 | CTA からの直接呼び出し(06 §1.3) | `PushKey(NumPad*)` | NumPad を直接積めば `bAllowMap` は関係ない | `Keyboard.cs:1218` |

## 5. 危険: 一本のキューをすべての Legacy モーダルが共有する

Modern では、キーボードのキューは Modern のポップアップに届かなかった。これが意図しない応答を防ぐ壁にもなっていた。Legacy ではその壁がなくなる。漏れたトークンは、次にキューを読むものに食べられる。

06 の設計では、エージェントは CTA から `SkipPlayerTurn=true` で戻り、EndPlayerTurn のカウンタは 0 のままでなければならない(06 §1.2)。つまり通常の運転では PlayerTurn が走らず、その冒頭の `ClearMouseEvents`(`XRLCore.cs:734`)も、default 分岐の `CommandEvent.Send`(`:878-883`、`:2322-2334`)も起きない。漏れたトークンを掃除する仕組みは、次のモーダルに届くまで何もない。

- 漏れたトークンは、キーでも意味付きマウスイベントでもキューに残り、次の `getvk` / `getch` の消費者に渡る。
- 次の消費者が `ShowBlock` か `ShowYesNo` なら、入口の `ClearInput` が消す(`Popup.cs:1150`、`:2282`)。
- `PickOption` の Legacy 分岐は入口で消さない(§2.3)。残っていた `Choice:0` はそのまま選択肢 0 の確定になる(`:1955`)。Space は現在の選択の確定に、NumPad2/8 は選択の移動になる。
- UI スレッドの `UpdateView` は、ビューが変わるたびにキーとマウスイベントの両方を消す(`GameManager.cs:1580` → `Keyboard.cs:877-891`。`ClearMouseEvents` は `:884`)。ただし、これはモーダルの最初の `getvk` より先に UI スレッドが走った場合にしか効かない **[推論: 両スレッドの順序はフレームの時刻で決まる]**。
- PlayerTurn に落ちた場合(人間への引き渡しの後など)は別の問題になる。漏れた NumPad キーは `:734` で消されず、`GetNextCommand` に拾われてプレイヤーを動かしうる。意味付きマウスイベントは `:734` で消える。
- 06 §3.2 の「`getvk` がキーを取らなければ送り直す」は、Legacy では二重送信の危険を持つ。送り直す前に、キューが空であることを確かめる。

意味付きマウスイベントを主に使う理由は、PlayerTurn で消えることではない。番号や名前で答えが一意に決まり、`Keyboard.Char` や現在の選択位置に左右されないことにある(§4)。

このため、送るときは次の四条件をすべて確かめる。

1. `GameManager.Instance.CurrentGameView` がモーダルのビュー名である。
2. `GameManager.Instance._ActiveGameView == CurrentGameView` であり、`TextConsole.BufferUpdated` が偽である。UI スレッドの `UpdateView` による消去(`GameManager.cs:1580`)がすでに済んだことを表す **[推論]**。
3. `CurrentBuffer.ViewTag` がそのビュー名で、しかも**枠の中に本文がある**。ビュー名だけでは足りない。`ShowYesNo` は背景の復元を `PopGameView` より前に描く(`Popup.cs:2312` → `:2322`)。`PickOption` も同じ順である(`:2000` → `:2002`)。そのため、最後のフレームはビュー名がポップアップのまま、本文が消えている。`ShowBlock` は逆で、先にビューを戻してから描く(`:1186-1187`)。
4. `Keyboard.KeyQueue.Count == 0` かつ `Keyboard.HasMouseEvent() == false`。

上限にも注意がいる。`OptionCapInputBuffer` の既定は Yes で(`Base/Options.xml:42`)、`GameManager.bCapInputBuffer` が真になる(`XRL.UI/Options.cs:1279-1286`)。このとき、キューに 3 件以上あると `PushKey` と `PushMouseEvent` は黙って捨てる(`Keyboard.cs:786`、`:827`)。隔離プロファイルでは `OptionCapInputBuffer=No` にするか、1 件ずつ送って消費を確かめてから次を送る。

## 6. (A) 割合と例外

ゲーム中のモーダルを、キャラクター作成の後に走行中に出うるものとして数えると、§3.1〜§3.2 の 24 系統になる。内訳は、Popup の 6 系統(お知らせ、PickOption 系、YesNo、YesNoCancel、AskString、AskNumber)と、画面の 18 系統(会話、PickItem、ステータス画面、有効な効果、メッセージ履歴、取引、能力一覧、Look、PickTarget/PickDirection/射撃、本、Tinkering、端末、ヘルプ、Sifrah、代名詞の変更、ゲーム中のオプション、キー設定、死亡時とスコア画面、ThinWorld から、システムメニュー・レベルアップ・操作メニューは PickOption 系に含めて除いたもの)である。

- **22 系統**は、Legacy で完全に「`CurrentBuffer` の文字 + ゲームスレッドの `getvk` / `getch`」に乗る。
- **2 系統**(キー設定、代名詞の変更)は入口の画面は文字だが、中の小ダイアログが UGUI に出る。どちらも走行には要らない。
- 22 系統のうち **4 系統**(Look、PickTarget/PickDirection/射撃、Sifrah、ThinWorld)は、Modern でもすでに `getvk` で待っている。Legacy で変わるのは、案内文や説明が格子に載るかどうかだけである(Sifrah は Modern でも載る)。入力経路そのものが変わるのは残りの 18 系統と、部分的な 2 系統になる。

例外は系統ではなく、UGUI の窓を直接開くサブ経路として現れる。

| 例外 | 経路 | 走行中に出るか | 回避策 |
|---|---|---|---|
| E1. `*Async` 系の Popup API と `ForceNewPopup` | `NewPopupMessageAsync` は `UIManager.copyWindow("PopupMessage")` を開く(`Popup.cs:751-799`)。ゲームロジックからの到達点は、ロード時の mod 構成不一致(`XRLCore.cs:3428`、`:3448`)、代名詞・ジェンダーのカスタム作成(§3.2)、キーの再割り当て(`KeyMappingUI.cs:333`)、ゲームスレッドの外から呼ばれた `ShowAsync` / `ShowFailAsync`(`Popup.cs:648`。例: `XRL/XRLGame.cs:2474` のセーブ失敗 **[推論: 呼び出しスレッドは未確認]**) | ロード時の不一致だけは出うる | mod の構成を固定する。ロードは `XRLGame.LoadGame` を直接呼ぶ案を検討する |
| E2. キャラクター作成 | `EmbarkBuilder`(§3.3) | 走行の外 | 人間が作る(06) |
| E3. 終局のクレジット | `EndgameCredits`(`EndGame.cs:345`) | 終局だけ。入力は求めない | 待つ |
| E4. ロード状況の表示 | `LoadingStatusWindow`(`Loading.cs:76-86`) | 非モーダル | 無視する |
| E5. メインメニューの Mods 画面 | `UIManager.pushWindow("ModManager")`(`XRLCore.cs:3757`) | 走行の外 | 開かない |

E1 には未確認の点が一つある。Legacy では `UpdateView` が `currentWindow = null` にする(`GameManager.cs:1612`)。`copyWindow` で直接 `Show()` した窓(`Popup.cs:760`、`:780`)がこのとき画面に見え、人間が答えられるかは、コードからは決まらない **[推論: 見えない場合、ロード時の不一致の確認が無言の停止になる]**。§9 の L7 で確かめる。

補足として、`Progress.draw` は Legacy 分岐で `buffer` を初期化しないまま使う(`XRL.UI/Progress.cs:16`、`:42-53`、初期化は Modern 分岐の `:58-62` だけ)。呼び出し元は `Popup.ShowProgress` / `ShowProgressAsync`(`Popup.cs:741-749`)を経たコード引き換えだけなので(`CodeRedemptionManager.cs:77`)、走行には関係しない **[推論: Legacy では NullReferenceException になる]**。

## 7. (B) Legacy でエージェントが失うもの

| 項目 | Modern | Legacy | エージェントへの影響 |
|---|---|---|---|
| ポップアップの構造化データ | `PopupMessage` が本文、題、選択肢(`QudMenuItem` の command)、ボタンを持つ(03 §2.8)。ただし UI スレッドから読む必要がある | 引数は Popup メソッドの局所変数に閉じる。読めるのは格子だけ | **最大の損失**。PickOption の選択肢は格子から読む。行頭のホットキー(`[a]` など)と `<More...>` を手がかりにし、番号は `Choice:N` で返す。CP437 の罫線文字は `Sidebar.FromCP437` の類で変換する **[推論: 変換表の網羅性は未確認]** |
| 長い本文 | 全文が窓の中にある | 窓の高さを超えるとスクロールが要る(`Popup.cs:1159-1178`) | お知らせ系はメッセージログのコールバックで全文が取れる(§2.2)。PickOption の Intro は取れない |
| 会話 | 構造は `ConversationUI` の静的フィールド | 同じ | 失わない |
| Look の説明 | UGUI のツールチップ | 格子の中 | `Look.GenerateTooltipContent`(`Look.cs:239`)が両モードで使えるので失わない |
| 状態表示(HP、メッセージ、周囲の物、ミニマップ) | UGUI の窓 | サイドバーの文字 | 観測は API から取る(06 §1.4)ので失わない |
| チュートリアル | 使える | 使えない | 関係しない |
| 入力の分離 | キューが Modern のポップアップに届かない | 一本のキューを共有する | §5 の混線が新しい危険になる |
| キーの表記 | 私用領域のグリフ(`` など) | 文字のキー名(`ControlManager.cs:1325-1328` がグリフを切る) | むしろ読みやすくなる |
| 配信の見た目 | UI スケール、再生領域のスケール、ドック、ミニマップ(`Base/Options.xml` で `OptionModernUI==Yes` を要する 21 項目) | 80x25 の全画面。サイドバーが地図の約 24 列を覆い、プレイヤーの x が 42 を超えると左、38 を下回ると右に移る(`Sidebar.cs:891-916`、`:559-566`、`XRL.World.Capabilities/AutoAct.cs:950-957`) | 視聴者向けの損失。エージェントには影響しない |

`Base/Options.xml:102-109` の「Legacy UI」カテゴリは、表示の切り替え(サイドバーの能力アイコン、現在のセルの内容表示、HP の色、所持品の件数、名前の代わりに場所)と、人間のキー入力の扱い(テンキーへの読み替え、Shift+方向のページ送り、A〜Z の素通し)である。mod が直接キューに積む入力を制限するものは含まれない。制限として効くのは、前節の `OptionCapInputBuffer`(`:42`)だけである。`OptionShowCurrentCellPopup`(既定 Yes、`:103`)は現在のセルの内容を格子に重ねて描く(`Sidebar.cs:883`)ので、格子を読むときの雑音になる。配信では情報として役に立つ。

## 8. Tiles と Legacy は両立する

`OptionUseTiles` は `Globals.RenderMode` を決めるだけで(`XRL.UI/Options.cs:1288-1295`)、`ModernUI` とは独立している。UI スレッドは `CurrentBuffer` の各セルについて、`Char == '\0'` なら `Tile` のスプライトを、そうでなければ文字のスプライトを置く(`GameManager.cs:3207-3336`、分岐は `:3266`)。この描画は `ModernUI` を見ない。したがって Legacy + tiles では、地図のセルはタイルで、サイドバーやポップアップの文字は文字で描かれる。枠の飾りも、tiles のときは UI 用のタイルになる(`:1727-1758`)。

`ControlManager.cs:1325` の `if (mapGlyphs && !Options.ModernUI)` は、キー名の表記からグリフを外すだけで、描画モードとは関係がない。

エージェント側への影響はない。地図の glyph は AfterRender の `BackupChar` か Zone の API から取る(03 §1.1-1.3)。tiles を ON にすると `CurrentBuffer` の地図セルは `'\0'` になるが、Legacy で `CurrentBuffer` から読みたいのはサイドバーとモーダルの文字で、これは tiles でも文字のまま残る。

## 9. (C) 静的な読みを確かめるプローブ

どれも隔離プロファイル(`OptionModernUI=No`、`OptionUseTiles=Yes`、`OptionCapInputBuffer=No`)で回す。ログはブリッジスレッドから `Player.log` に書く。

| ID | 確かめること | 手順 | 記録するもの | 期待する結果 |
|---|---|---|---|---|
| L0 | 設定が効いている | mod の初期化時に読む | `Options.ModernUI`、`GameManager.Instance.ModernUI`、`Options.UseTiles`、`GameManager.bCapInputBuffer`、`GameManager.Instance.consoleTileAreaHandler.activeSelf` | `False, False, True, False, True` |
| L1 | 格子の取得 | ブリッジスレッドで `TextConsole.DrawBufferEvent.WaitOne(500)` を回し、合図のたびに `lock (TextConsole.BufferCS)` の中で `CurrentBuffer` を写す | `ViewTag`、`CurrentGameView`、`_ActiveGameView`、25 行の文字(`'\0'` は `·`)、`Tile != null` のセル数 | Stage では、サイドバーの列に HP の文字列(`Sidebar.sPlayerHP`)とメッセージが並び、地図のセルは `·` になる。ポップアップ中は `ViewTag = Popup:MessageBox` などになり、枠の中に本文がある |
| L2 | 系統ごとの往復 | 使い捨てキャラクターで、お知らせ、YesNo、YesNoCancel、PickOption、AskString(ABANDON の確認)、会話、PickItem(宝箱)、PickDirection を順に出し、§4 のトークンを 1 回だけ送る | トークン、送る前後のビュー、送ってからビューが戻るまでの ms、ゲーム側の結果 | 1 回の送信で 1 回閉じる。ビューが `Stage` に戻る。結果が人間の操作と同じになる。宝箱は `ItemSelected` で中身を取れる |
| L3 | 復元フレームの順序 | YesNo と ShowBlock を 1 往復ずつ行い、L1 のフックで全フレームを記録する | 各フレームの `(ViewTag, 最初の空でない行)` | YesNo では、最後の `Popup:MessageBox` のフレームに本文がない(`Popup.cs:2312` → `:2322`)。ShowBlock では、復元のフレームがすでに下のビュー名になっている(`:1186-1187`) |
| L4 | 消去との競合 | ビューが変わった瞬間に送る場合と、§5 の四条件を待ってから送る場合を、キー(`PushKey(Space)`)とマウスイベント(`LeftOption:1`)の両方で各 50 回 | 失われた回数 | 前者はキーでもマウスイベントでもときどき失われる(`GameManager.cs:1580` → `Keyboard.cs:877-891`、`Popup.cs:1150`)。後者は 0 回 |
| L5 | 漏れの持ち越し | CTA で待機している間に `PushMouseEvent("Choice:0")` を 1 件だけ積み、続けてシステムメニュー(`PickOption`)を出す行動を指示する。対照として、人間への引き渡しの後に `PushKey(NumPad6)` を積んで PlayerTurn に落とす | PickOption が人の操作なしに返した番号、プレイヤーの位置、エネルギー、CTA 入口での `KeyQueue.Count` と `HasMouseEvent()` | 何もキューを空けなければ、PickOption は選択肢 0 を即座に返す(`Popup.cs:1955`)。PlayerTurn では NumPad6 で 1 歩動く。CTA の入口で `ClearInput` を呼べば、どちらも起きない |
| L6 | 上限 | `OptionCapInputBuffer` を Yes と No にして、5 件を一度に積む | 積んだ直後の `Keyboard.KeyQueue.Count` | Yes では 3、No では 5 |
| L7 | E1 の見え方 | mod を 1 つ外してセーブをロードし、構成不一致の確認を出す | `CurrentGameView`(`DynamicPopupMessage` のはず)、`copyWindow` の窓が有効か、人間がマウスで答えられるか | 見えて答えられるなら、運用で避けるだけで済む。見えないなら、ロードは `XRLGame.LoadGame` に限る |
| L8 | ホットキーの文字 | ホットキー付きの PickOption に `PushKey(new XRLKeyEvent(KeyCode.A))` と `PushKey(new XRLKeyEvent(KeyCode.A, 'a'))` を送る | 選ばれた番号 | 前者は選ばれない。後者は選ばれる(`Popup.cs:1925`) |
| L9 | tiles + Legacy の見た目 | Joppa で 1 画面を撮る | スクリーンショット、L1 の `Tile != null` のセル数、AfterRender の `BackupChar` の格子 | 地図はタイル、サイドバーとポップアップは文字。AfterRender の格子は Zone の実体と一致する |
| L10 | Legacy の Continue | メインメニューで `Pick:Continue` → `Play:0` | ビューの遷移、ロードの完了、`LegacySaveManagement` 中の `XRLCore.CoreThread.ThreadState` | ロードが完了し、最初の CTA が来る。ゲームスレッドは `.Wait()` で止まっている(継続はスレッドプール)**[推論]** |
| L11 | 非フォーカス | ウィンドウのフォーカスを外して L2 の一部を回す | 送ってから閉じるまでの ms | `getvk` の待ちは `KeyEvent.Set` で起きる(`Keyboard.cs:794`、`:1031`)ので 50 ms 未満。`kbhit` を使う Look、PickTarget、端末は 1 周ごとに約 200 ms かかる(`:938-954`)。なお、PlayerTurn は非フォーカスの間 200 ms ごとに眠り続け、コマンドを取りに行かない(`XRLCore.cs:736-739`)。これは両モード共通である |

## 10. (D) 推奨: Legacy UI を Plan A にする

比べる対象は、避けられないモーダルに絞る。06 はすでに、ステータス画面、所持品、本、端末を直接 API で置き換え、画面を開かない方針を取っている。残るのは YesNo、PickOption(レベルアップ、死亡時のメニュー、システムメニューを含む)、AskString、会話、お知らせ、PickDirection/PickTarget、宝箱のピッカーである。

この七つについて、Legacy が UGUI に残すものはない(§6)。Modern で同じことをするには、UI スレッドで窓の実体(`getWindow` の共有インスタンスか `copyWindow` の複製か)を探し、`OnSelect`、`OnActivateCommand`、`OnInputSubmit` を正しい引数で呼ぶ必要があった。06 はこれを R5 の成否に賭けていた。宝箱の `PickGameObjectScreen` に至っては、`Cancel()` しかできなかった。Legacy では、すべてがキューへの 1 件の送信になり、宝箱の中身も `ItemSelected` で選べる(続く操作メニューは PickOption なので `Choice:N` で答える)。検出も、`ViewTag`、格子の本文、キューの空の三つで統一できる。

代わりに払うものは三つある。

1. **格子を読む手間。** PickOption の選択肢は格子から読むことになる。ただし、お知らせ系の全文はメッセージログのコールバックで取れる。会話は静的フィールドで取れる。staged answers(06 §3.2)は、送る側が問いの内容をすでに知っている。格子の解析が本当に要るのは、LLM に選ばせる PickOption だけに狭まる。
2. **入力の混線。** §5 の四条件と、意味付きマウスイベントを主にする方針で抑える。06 §3.3 の `stray_input` センサー(CTA の入口でキューを数えて捨てる)は、Legacy では必須になる。
3. **配信の見た目。** 画面は 80x25 の全画面になり、サイドバーが地図の約 3 割を覆って左右に動く。

配信は tiles を ON にする。地図はタイルで描かれ、サイドバー、メッセージ、ポップアップは古典的な文字の箱として上に重なる。エージェントは地図を AfterRender と API から取るので、tiles は何の代償にもならない。サイドバーを畳みたい場面では `CmdShowSidebar` で最小表示にできる(`XRLCore.cs:2251-2253`、`Sidebar.cs:849-884`)。text モードにする理由は、エージェント側にはない。

06 からの変更点を具体的に書くと、次のとおりである。

- §3.1 のオプション固定で、`OptionModernUI=Yes` を `No` に替え、`OptionCapInputBuffer=No` を加える。`OptionUseTiles=Yes` は残す。
- §3.2 の駆動を、`uiQueue` による窓の操作から、§4 のトークンをキューに積む方式に替える。送り直しは、§5 の条件 4(キューが空)を確かめてからに限る。
- 06 §3.3 の `stray_input` を、Legacy では両方のキューを対象にする。CTA の入口で `Keyboard.KeyQueue.Count` と `Keyboard.HasMouseEvent()` を記録してから、`Keyboard.ClearInput(LeaveMovementEvents: false)` を呼ぶ。これはキーとマウスイベントの両方を消す(`Keyboard.cs:877-891`)。`MouseEventQueue` は private なので(`:130`)、件数まで要るならリフレクションで読む。
- R5 を Legacy 版に書き換え、§9 の L1〜L6 にする。第 1 週のうちに通らなければ、Modern(06 の現行案)を Plan B に戻す。L7 と L10 は、運用の手順(ロードの仕方)を決めるために同じ週に回す。
- 「ModernUI=Yes かつ ModernCharacterSheet=No」という第三の構成もある。ステータス画面だけが Legacy になり(`Screens.cs:45`、`:90`、`GameManager.cs:1828-1868`)、ポップアップは Modern のままになる。ステータス画面は開かない方針なので、この構成に得はない。

オーナーの見立てで一点だけ直すところがある。「どの画面も ScreenBuffer に描かれる」は正しいが、それは `CurrentBuffer` の話であって、v1 から使ってきた AfterRender のバッファには届かない。Legacy のモーダルを読む仕組みは、`DrawBufferEvent` を待って `CurrentBuffer` を写す新しい一本になる。
