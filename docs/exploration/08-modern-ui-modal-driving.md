# 08: Modern UI を画面に残したままモーダルを検出・読取・応答する（方向 2 の静的検証の統合）

- 対象ビルド: 2.0.211.56（ILSpy 逆コンパイル、`/Users/sankenbisha/Dev/coq-decompiled_stable`）。
- 作成日: 2026-09-25。
- 入力は次の二つである。
  - 7 ファミリの分析: `docs/exploration/modal-verification/F1-popup.md`、`F2-conversation.md`、`F3-pickers.md`、`F4-status-screens.md`、`F5-other-blocking.md`、`F6-threads-hooks.md`、`F7-observation.md`。
  - 各ファミリに対する二つの懐疑レンズの判定。
    - T: THREAD & LIFECYCLE。
    - P: PATH COMPLETENESS & CITATION ACCURACY。
- 本書の `path:line` は、断りがなければ逆コンパイルのソースルートからの相対パスである。家族文書の該当箇所は `F1 §4` のように示す。
- 引用の一部は、本書の作成時に `sed -n` で表示し直して確かめた（§9）。
- 判定の規則は次のとおりである。
  - 両レンズが confirmed で、著者が runtime_only としていない主張だけを「確立」とする。
  - どちらかが partial なら「条件付き」とし、条件を書く。
  - どちらかが refuted なら事実として書かず、訂正した所見を書く。一方のレンズが主張の一部を明示的に否定した場合は「部分反証」とする。
  - runtime_only の主張は「実機」とし、§6 のプローブ計画に回す。

## 1. 結論

**全体。** 方向 2（Modern UI を画面に出したまま、mod が legacy 相当のテキストを合成し、UI スレッドから答える）は、**静的には条件付きで成立する**。

- 7 ファミリのどれにも、Harmony が必須になるモーダルは見つからなかった。
- 家族文書が示した「答え方」の多くは、懐疑レンズの指摘で修正が必要になった。修正後のレシピを §2 に載せる。
- 判定の集計は次のとおりである（174 件）。

| 状態 | 件数 |
|---|---|
| 確立 | 110 |
| 条件付き | 43 |
| 部分反証 | 4 |
| 反証 | 2 |
| 実機 | 15 |

- 反証は二件である。
  - C-F2-conversation-21: キャンセル時の挙動の説明が誤っていた。
  - C-F5-other-blocking-18: 終局演出に入力は要らない、という主張が誤っていた。

**Harmony なしで答えられるモーダル群。** 条件は、§3 の横断ルール（トークン、同一タスクでの検証と実行、先に Hide を呼ばない、チュートリアルのオーバーレイを最優先で処理する）を守ることである。これを守れば、次のモーダルは public のメンバーとリフレクションだけで、検出、読取、応答ができる。

| 系統 | 含まれるモーダル | 応答の仕方 |
|---|---|---|
| 同期 PopupMessage | Show、ShowFail、ShowBlock 系、ShowYesNo、ShowYesNoCancel、PickOption 系、死亡メニュー、PickSeveral | 本物の項目を `OnActivateCommand` / `OnSelect` に渡す |
| 非同期 PopupMessage の複製 | AskString、キーボード時の AskNumber、ShowAsync、Look の説明 | 入力欄は `inputBox.text` を設定してから `OnInputSubmit` を呼ぶ |
| 会話ノード | 会話と、その中に入れ子で出るポップアップ | 同期 PopupMessage と同じ |
| `.Result` 型の Modern 画面 | PickGameObjectScreen、AskNumberScreen、StatusScreensScreen、AbilityManagerScreen、Options、Keybinds、Help、TradeScreen、BookScreen、端末、GameSummaryScreen、SaveManagement、HighScoresScreen（懐疑レンズが追加。medium） | public の `HandleSelect*`、`Cancel()`、`Exit()`、`SelectedInfo` |
| チュートリアルのオーバーレイ | 終局のコーダの幕間を含む | public の `OnPopupAcceptPressed()`。ただし `TutorialManager` の GameObject が active で、その Update が回っている間に限る。Update がフラグを消費するのは `ShowingPopup` が真のときだけである（`TutorialManager.cs:769-789`、C-F5-other-blocking-17 は条件付き） |
| 主メニュー、Sifrah | 主メニューはゲームスレッドの getvk ループ。Sifrah は、ゲームスレッドか APIDispatch のプールスレッド（`XRL.UI.Framework/APIDispatch.cs:19, 56` の `Task.Run`。端末のハックの場合、§2.5）で回る getvk ループ（`XRL/SifrahGame.cs:646-671`） | `Keyboard.PushMouseEvent` / `PushKey` |

- 主要な根拠: `Qud.UI/PopupMessage.cs:926-944`、`TutorialManager.cs:764-767`、F1〜F5 の各 §4。

**条件付きのもの。** 静的には成立するが、実行時の条件か、追加の手順が要るもの。

- **getvk ループのピッカー**（PickDirection、PickTarget のセル選択、PickField、FireMissileWeapon、Looker）。
  - `Keyboard.PushKey` / `PushMouseEvent` は届く。
  - 入力は、ビューの切り替えのたびに `ClearInput` で消える。そのため、P'（`_ActiveGameView == CurrentGameView && !bViewUpdated && bThreadFocus`、§2.0）を確かめる処理と入力を積む処理を、同じ uiQueue タスクで行う必要がある（`GameManager.cs:3172-3183`）。
  - この前提は非フォーカス中には成り立たない。`GameManager.cs:3108-3113` で return するためである。
  - カーソル位置は読めないので、`PointerOver` を 2 回積んで座標を押し付ける方式が前提になる（C-F7-observation-11、実機）。
  - PickField は、確定キーと取消キーの意味がほかと違う。別のレシピにする（F7 レンズ P の blocker）。
- **AskNumber**。人の入力がない環境では `ControlManager._activeControllerType` が既定の Mouse のままなので（`ControlManager.cs:337`）、AskNumberScreen の経路に入る。二つの表面の両方を扱う必要がある。
- **取引、本、端末**。APIDispatch がプールスレッドでゲームロジックを走らせている間は、応答してはならない。
- **キャラクター作成（EmbarkBuilder）**。
  - 公開モジュール API で 1 手ずつ進められる見込みだが、連鎖の全体は実機でしか確かめられない（C-F5-other-blocking-23、実機）。
  - `SelectPregen` は、知らない名前を渡すと KeyNotFound を投げる（`XRL.CharacterBuilds.Qud/QudPregenModule.cs:95-98` の `pregens[pregen]`）。public の `pregens` にあるキーだけを渡す。
  - 途中で経路 A の複製ポップアップが出る（§2.5）。
- **UI ティックの前提**。全レシピは、Unity の Update が回り続けることを前提にしている。`Application.runInBackground` とフォーカスの扱いは、実機で確かめるまで条件である。

**答えられないもの（静的には見つからない）。** Harmony がないと原理的に答えられないモーダルは、静的には見つからなかった。境界にあるのは二つだけである。

- **キー割り当ての捕捉（`GetRebindAsync`）の即時中止。**
  - 10 秒のタイムアウトを待てば終わる。
  - 合成の Cancel キーイベントは、Harmony なしの候補だが未検証である。
  - どちらも駄目な場合に限って、prefix で `Task.FromResult<List<string>>(null)` を返す。
  - エージェントがこの画面を開かない運用にすれば、問題にならない。
- **PickTarget のカーソル位置の読み戻し。**
  - `PointerOver` の押し付けと、照準 imposter の走査の両方が実機で駄目な場合に限って、`PickTarget.ShowPicker` の transpiler が要る。
  - これは「答える」ことではなく、「確認する」ことの問題である。

**実機でしか分からないもの。** 次の項目は静的には決まらない。§6 のプローブ R5 で確かめる。

- UI ティックと Unity の実行環境
  - フォーカスがないときに Unity の Update が回るか。`runInBackground` と `bThreadFocus` を書き直した場合の効果。
  - `async void` の WaitNewPopupMessage がプールスレッドで例外を再送出したとき、Mono がログに残すだけか、プロセスを落とすか。
  - UI スレッド以外から Unity の getter を呼んだときの挙動。
  - `TaskAwaiter` の継続がどのスレッドで走るか（インラインか、プールか）。
  - プレハブの UnityEvent の配線。
- ピッカー
  - `PointerOver` を 2 回積む方式の成否。照準 imposter の走査の成否。
- 会話
  - 端から端までの挙動（C-F2-conversation-26）。
- 画面ごとの事実
  - StatusScreensScreen のタブ順（プレハブで決まる）。
  - 端末を閉じた後にビュー名が残るか。
  - EmbarkBuilder の最終窓。
  - キャラクター作成の後の WorldGenerationScreen と OpeningStory の流れ（§2.5）。
  - クレジットの早送り。
  - メモリ上の mod アセンブリに置いた MonoBehaviour に Update が届くか。

## 2. 検出・読取・応答の一覧表

### 2.0 表の読み方と共通の記号

**列の意味。**

- 確度は、修正後のレシピに対する確度である。
  - high: 両レンズの確認か、懐疑レンズの証拠による修正がある。
  - medium: 懐疑レンズが追加したモーダルか、推論を含む。
  - low: 未検証。
- 「実機」の列は、§6 で確かめるべき点を示す。

**スレッドの記号。**

- UI: `GameManager.Instance.uiQueue` の UI ティック（§3.1）の中、つまり UI スレッドで評価し、実行すること。
- 任意: ブリッジスレッドから直接読んでよいこと。対象は `CurrentGameView` と `GetGameViewStackCopy()` だけで、これらはヒントとして扱う。

**述語とトークン。**

- **D(w)**: PopupMessage `w` が未回答であることの述語。
  - 式は `w.onHide != null && w.gameObject.activeSelf && w.canvasGroup.interactable` である。
  - 評価の対象は、単体の `"PopupMessage"` と、`windowsByName` にある `"PopupMessage #N"` の複製の両方である。
  - 複製が複数開いているときは、同じ親を持つものの中で sibling index が最大のものを選ぶ。
  - sibling index は、同じ親を持つ窓の間でしか比べられない。複製は `instance.transform` の子になる（`Qud.UI/UIManager.cs:323-338`）。親が違う窓の間では、複製を優先する。候補はすべてログに残す。
  - 根拠: F1 §4、C-F1-popup-08、F2 レンズ P の修正。
- **tok(w)**: PopupMessage のトークン。
  - 検出時の `w.onHide`、`w.commandCallback`、`w.selectCallback` の参照である。
  - 応答タスクの中で `ReferenceEquals` を再確認する。
  - 応答後の成功の確認は、同じタスクの中で `!ReferenceEquals(w.onHide, token)` を見るだけで十分である。
    - `OnActivateCommand` / `OnSelect` は、コールバックを呼んで null にした後で `Hide()` を呼ぶ（`Qud.UI/PopupMessage.cs:926-944`）。
    - `Hide()` は onHide を null にする（`:1083-1104`）。
    - したがって同じタスクの中では、onHide の変化は、コールバックが呼ばれたことと同値である。コールバックが null になったことは、診断として記録するだけにする。
- **P'**: getvk ループのピッカーに入力を積む前の前提。
  - 式は `_ActiveGameView == CurrentGameView && !bViewUpdated && bThreadFocus` である。
  - 評価と入力の積み込みを、同じ UI タスクで行う。
  - 根拠: C-F3-pickers-04（条件付き）、C-F6-threads-hooks-12（実機）。
- **tcs(s)**: `.Result` 型の画面 `s` のトークン。
  - protected / private の `menucomplete` か `completionSource` を、リフレクションで読んだ参照である。
  - `!Task.IsCompleted` と組み合わせて使う。

### 2.1 F1 ポップアップ（PopupMessage）

| モーダル種別 | ゲームスレッドの待ち方 | 検出述語 | 読取元 | 応答手順 | 取消手順 | Harmony | 確度 | 実機 |
|---|---|---|---|---|---|---|---|---|
| 通知（Show / ShowFail / ShowBlock / ShowBlockPrompt / ShowBlockSpace / ShowSpace。チェックポイントなしの死亡メッセージ PopupID `"DeathMessage"` を含む） | 経路 S: 呼び出し元のスレッドが `uiQueue.awaitTask` の後に `complete.Task.Wait()`（`XRL.UI/Popup.cs:823-909`） | UI: D(w)。ボタンは SingleButton（command `Accept`、hotkey `Accept,Cancel`）が 1 個 | `Message.text`、`Title.text`。`contextText.text` は `contextText.gameObject.activeSelf` のときだけ読む（C-F7-observation-01） | tok を再確認してから `OnActivateCommand(bottomContextOptions[0])`。同じタスクで `commandCallback == null` になったかを見る | 応答と同じ（Accept が取消を兼ねる）。`Hide()` を先に呼んではならない | 不要 | high | 事後確認の文言だけ |
| ShowBlockWithCopy | 経路 S（`Popup.cs:676-691`） | D(w)。ボタンは `Copy` / `Cancel` | 同上 | `OnActivateCommand(Copy)` の後に、続く Show に答える | `OnActivateCommand(Cancel)` | 不要 | high | なし |
| ShowYesNo / WarnYesNo | 経路 S（`Popup.cs:2251-2276`） | D(w)。ボタンは `{Yes, No}` だけ | `Message.text`。本文はメッセージログに載らない（C-F7-observation-17） | `OnActivateCommand(Yes または No の項目)` | **`No` の項目を渡す。** `Cancel` の項目は存在しない。Hide や onHide で閉じると、呼び出し側は既定値 `Yes` を受け取る（`Popup.cs:2257`）。これは F4 の購入確認では購入の成立を意味する | 不要 | high | なし |
| ShowYesNoCancel / WarnYesNoCancel / DisplayLoadError | 経路 S（`Popup.cs:2371-2388`） | D(w)。ボタンは `{Yes, No, Cancel}` | 同上 | 該当する項目を渡す | `Cancel` の項目。既定値は Cancel | 不要 | high | なし |
| PickOption 系（PickOption / ShowOptionList / PickOptionAsync / Popup.PickGameObject / ShowColorPicker） | ゲームスレッドかプールスレッドから呼ばれると経路 S。**UI スレッドから呼ばれると経路 A の複製**になる（`Popup.cs:803-821`）。例: Modern のインベントリの Options、派閥の Sort、キャラクター作成、Keybinds | D(w) を単体と複製の**両方**に適用する。`menuData` に `option:N` がある | `menuData[i].text/command`。`Title.text` と `contextText`（アイコン付きなら contextText 側。C-F7-observation-07） | `OnActivateCommand(menuData[k])`。k は command `option:N` で同定する | AllowEscape なら `Cancel` の項目。なければ選ぶしかない。キャンセルすると `DefaultSelected` が選ばれる | 不要 | high（検出範囲は懐疑レンズの修正による） | 複製に出る場合の確認 |
| PickSeveral | 経路 S の PickOption を繰り返す（`Popup.cs:2046-2137`）。入れ子の AskNumber は `Popup.cs:2126` | D(w)。menuData と、ボタン `option:-2`（確定）/ `option:-3`（全選択の切り替え） | menuData と bottomContextOptions の両方 | `menuData[k]` で切り替え、`option:-2` で確定する | AllowEscape なら `Cancel` の項目（null を返す） | 不要 | medium | 反復の終わり方 |
| チェックポイントの死亡メニュー（`CheckpointingSystem.ShowDeathMessage` の PickOption ループ） | 経路 S（`XRL/CheckpointingSystem.cs:111-122`） | D(w)。ボタンなし、menuData が 4 件。本文の先頭ではなく 4 つの選択肢の文字列で判定する（本文は "You died." 以外もある） | menuData | **文字列で選ぶ。** 並びは `OptionDefaultDeathToViewFinalMessages` で入れ替わる（`:113-114`）。"View final messages" は StatusScreensScreen(7) を `.Result` で開く（`:121`）ので、F4 の Exit に引き継ぐ | なし。キャンセルすると 0 番が選ばれる（オプション次第で "View final messages"） | 不要 | high | なし |
| DEBUG の "really die" 確認（`Options.AllowReallydie` のとき。`CheckpointingSystem.cs:106`）【懐疑レンズが追加】 | 経路 S の ShowYesNo | ShowYesNo と同じ | 同上 | 同上 | `No` | 不要 | medium | なし |
| AskString（wish のプロンプトを含む） | 経路 A: `AskStringAsync(...).Result`（`Popup.cs:1442`）。窓は copyWindow の複製 | UI: 複製 `"PopupMessage #N"` で D(w) が真で、`inputBox.gameObject.activeSelf`。スタックに `"ModernPopup:AskString"` がある | `Message.text`（`ClipText` で 60 桁に切られている）、`inputBox.text` | `inputBox.text = s` の後に `OnInputSubmit(s)`（`PopupMessage.cs:946-958`）。MaxLength / RestrictChars は Modern では効かないので、ブリッジ側で守る | `Cancel` の項目。`""` か null が返る。EndGame の `.ToUpper()`（`EndGame.cs:162`）では null で NRE になる | 不要 | high | TMP の setter が値を変えないか |
| AskString（WantsSpecificPrompt: RETIRE / endgame / ABANDON） | 経路 A | 上に加えて `WantsSpecificPrompt != null`。PC ではボタンが keep / Cancel / CmdOptions | 同上 | `inputBox.text = WantsSpecificPrompt` の後に `OnInputSubmit` | `Cancel` の項目 | 不要 | high | 同上 |
| AskNumber（入力欄。`activeControllerType == Keyboard` のとき） | 経路 A: `AskNumberAsync(...).Result`（`Popup.cs:1200, 1341-1354`） | スタックに `"ModernPopup:AskNumber"`。複製で D(w) が真 | `Message.text`、`inputBox.text` | 整数で `[Min, Max]` の範囲にあることを先に確かめ、`inputBox.text = n` の後に `OnInputSubmit` | `Cancel` の項目は null を返す。値の解析に失敗した場合も null になり、区別できない | 不要 | high | どちらの経路に入るか |
| AskNumberScreen（`activeControllerType != Keyboard` のとき。**既定の Mouse を含む**） | `AskNumberAsync(...).Result` の後に `menucomplete`（`Popup.cs:1320-1331`、`Qud.UI/AskNumberScreen.cs:117-146`） | UI: `SingletonWindowBase<AskNumberScreen>.instance.isCurrentWindow()` と tcs。**ビュー名は使えない。** `TradeScreen.cs:247` は pushView なしで呼ぶ | `messageText.text`、`Current`、`Min`、`Max` | 整数を確かめ、`numberText.SetText(n)` の後に `Accept()`。その後 `isCurrentWindow()` が偽になったかを見る | `Cancel()` は null を返す | 不要 | high（仕組み）/ medium（どちらの経路か） | `_activeControllerType` の実際の値 |
| そのほかの経路 A（ShowAsync / ShowYesNoAsync / ShowYesNoCancelAsync / Look の説明 `Description.cs:361`） | 経路 A。同期の呼び出し元は `.Result` で待つ | 複製で D(w) が真。ビューは `"DynamicPopupMessage"` | `Message`、`contextText`、ボタン（`Story` など） | ボタンの項目を `OnActivateCommand` に渡す。`Story` は BookScreen に進む | Look の説明では `Accept` の項目が取消を兼ねる | 不要 | high | なし |
| AnyKey / cancelToken のポップアップ（ShowKeybindAsync。オプションのヘルプ）【懐疑レンズが追加】 | UI 側 | 項目のない複製 | `Message.text` | 呼び出し側の cancelToken か any-key の経路だけ（`PopupMessage.cs:1040-1045`） | 同じ | 不要（エージェントは開かない） | low | 対象外にしてよいか |
| AskString の中の色選択（`ShowColorPickerAsync`。`Popup.cs:1390-1405`）【懐疑レンズが追加】 | 複製を重ねる。どのスレッドで走るかは実機で決まる | PickOption 系の述語（単体と複製の両方）で拾える | menuData | PickOption と同じ | 同じ | 不要 | low | どのスレッドか、どの窓か |

### 2.2 F2 会話

| モーダル種別 | ゲームスレッドの待ち方 | 検出述語 | 読取元 | 応答手順 | 取消手順 | Harmony | 確度 | 実機 |
|---|---|---|---|---|---|---|---|---|
| M1 会話ノード | 経路 S の単体窓。`complete.Task.Wait()`、RenderMapBehind のときは `Wait(33)` と `RenderBaseToBuffer` のループ（`Popup.cs:896-909`） | UI: 単体の窓で D(w)、`commandCallback != null && selectCallback != null`。さらに `PopupID` が `"Conversation:"` で始まるか、ボタンに command `Look` がある（`Popup.cs:1582, 1613`）。トークンは tok(w) | 話者: `contextText.text`（activeSelf のときだけ）。本文: `Message.text`（`{{y\|…}}` と末尾の `\n\n` を除く）。選択肢: `menuData[i]`。補助の情報は UI タスクの中で `ConversationUI.CurrentChoices[i].ID/Target`。`GetDisplayText` は呼ばない | `OnActivateCommand(menuData[k])`。同じタスクで `commandCallback == null` を確かめ、偽ならゲートによる不成立として返す | `Cancel` の項目（`AllowEscape` のノードだけ）。終わったことは `ConversationUI.CurrentConversation == null` で確かめる | 不要 | high | 端から端まで（C-F2-conversation-26） |
| M2 会話からの取引 | `TradeScreen.show(...).Result`。REFRESH / NEXT / TOP で開き直す | §2.5 の取引の述語。スタックに `"Conversation"` がある | F5 の取引 | F5 の取引。閉じると同じノードが描き直される | `Cancel()` | 不要 | high | 実験に使える商人 |
| M3 会話内の Look | 経路 A（`Description.cs:333-375`） | 複製で D(w) が真。トークンは tok | `Message`、`contextText` | `Accept`。`Story` を選ぶと BookScreen に進む | `Accept` | 不要 | high | なし |
| M4 会話内の入れ子のポップアップ（クエスト開始と段階完了、CheckLost、水の儀式の YesNoCancel、PickOption、EndGame の AskString） | 経路 S。EndGame の AskString だけ経路 A | D(w) を単体と複製の両方に適用する。スタックに `"Conversation"` がある | F1 | F1 | F1 | 不要 | high | なし |
| M5 会話セッション | ノードとノードの間はゲームスレッドが走る | 開始: `CurrentConversation != null`。終了: null に戻ること。ビューのスタックは従の信号として使う（キャンセルが漏れると `"Conversation"` が残る） | `ConversationUI.Speaker`、`CurrentConversation.ID` | なし | `Cancel` か `End` | 不要 | high | なし |
| 会話から開くそのほかの画面（GiveArtifact / ReceiveItem の PickGameObject、LibrarianGiveBook / GiveReshephSecret の PickSeveral、Story からの Book、水の儀式の Sifrah、CmdTalk の PickDirection）【懐疑レンズが追加】 | それぞれの画面の待ち方 | 各ファミリの述語 | 各ファミリ | 各ファミリ | 各ファミリ | 不要 | medium | なし |

### 2.3 F3 ピッカー

| モーダル種別 | ゲームスレッドの待ち方 | 検出述語 | 読取元 | 応答手順 | 取消手順 | Harmony | 確度 | 実機 |
|---|---|---|---|---|---|---|---|---|
| PickDirection | getvk でブロック（`XRL.UI/PickDirection.cs:38-54`） | UI: P'、ビュー `"PickTarget"`、`PickTargetWindow.currentMode == PickDirection` | `PickTargetWindow.currentText`（前のピッカーの文が残りうる。C-F3-pickers-13） | `PushKey(KeyCode.Keypad1..9)` か、`PushMouseEvent("LeftClick", 自分±1)`。自分を指すのは `Keypad5`。`Meta:Navigate*` は ResetInput を生き残るので使わない | `PushKey(Escape)` | 不要 | high | P' で十分か |
| PickTarget セル選択（PickCells） | kbhit + getvk。入力がない間も描画を回し続ける（`XRL.UI/PickTarget.cs:786-791`） | UI: P'、ビュー `"PickTarget"`、`currentMode == PickCells` | `currentText`。カーソルはローカル変数（`:400-405`）なので、押し付けた座標を正とする | `PushMouseEvent("PointerOver", x, y)` を 2 回。消費を確かめる（`CurrentMouseEvent` が PointerOver(x, y)）。最後は `PushCommand("CmdFire")`（`PushKey(F)` は使わない）。範囲の検査は Chebyshev で、Origin か自分のセルから測る。EnforceRange と Constrain で座標が動かされうる。CmdAttackCell は `Sidebar.CurrentTarget` の周り ±1 にクランプされる | `Escape` / `Keypad5` / `CmdTargetSelf` | 不要。インスタンスのトークンだけは prefix を使うと確実になる（§5） | high（仕組み）/ medium（全体） | PointerOver の注入（C-F7-observation-11） |
| PickField（ShowFieldPicker）【レンズ P の blocker で分離】 | kbhit + getvk（`PickTarget.cs:160-164`） | UI: P'、`currentMode == PickField` | `currentText`（残りのマス数、Start / End）。`focusPosition` は最初のフレームから書かれる | `PointerOver` を 2 回、`Space` で開始、`PointerOver` かテンキーで道を引き、`Space` で終了。手を打つたびに `currentText` を読み直す | `Escape`。選択中なら 2 回押す。**`Keypad5` と `CmdTargetSelf` は開始か確定になる**（`:322-338`）ので取消に使わない | 不要 | medium | あり |
| FireMissileWeapon（射撃と投擲） | kbhit + getvk（`XRL.World.Parts/MissileWeapon.cs:786-790`） | UI: P'、ビュー `"FireMissileWeapon"` | `currentText`。リフレクションで `PlayerMissilePath` を読む（X1/3、Y1/3） | PointerOver を 2 回。射線を 2 回続けて読んで目標と一致したら `CmdFire`。ピッカーを避けて `Combat.FireMissileWeapon` / `ThrowWeapon` に `TargetCell` を渡し、ゲームスレッドで呼んでもよい | `Escape` / `Keypad5` | 不要 | high | 射線を UI スレッドから読むときの整合 |
| Looker（Look.ShowLooker） | kbhit + getvk。入力がなければ IdleWait。対象が変わると gameQueue を回す（`XRL.UI/Look.cs:658, 669-672`） | UI: P'、ビュー `"Looker"` | `currentText`、`Look.lookingAt`（次の反復で更新される）、UI スレッドで `GameManager.Instance.lookerTooltip.parameterizedTextFields`。`GenerateTooltipInformation` を UI スレッドから呼ばない | `PushMouseEvent("LeftClick", x, y)` の後、`lookingAt?.CurrentCell` が目標と一致するまで何フレームか待つ。セルを返すときは `CmdFire` | `Escape` / `Enter` | 不要 | high | `AfterLookedAt` が発火するか |
| PickGameObjectScreen | ゲームスレッドの `.Result`（`XRL.UI/PickItem.cs:285, 307, 319`） | UI: ビュー `"PickGameObject"`、`instance.Visible` と `isCurrentWindow()`、tcs（`menucomplete`） | `rawGameObjects`、`listItems`（カテゴリ順のときは畳まれた分類が抜ける）、`titleText.text` | 対象が `rawGameObjects` に含まれることを確かめ、`HandleSelectItem(new PickGameObjectLineData().set(Item, go: x))`。行データを複数のタスクにまたがって持ち越さない | `Cancel()` | 不要 | high | なし |
| TwiddleObject の操作メニュー（ビュー `"ModernPopupTwiddleObject"` の後に PickOption、PopupID `"InventoryActionMenu:<id>"`）【懐疑レンズが追加】 | 経路 S（`Qud.API/EquipmentAPI.cs:141, 161`） | PickOption 系 | menuData | PickOption 系 | 同じ | 不要 | medium | なし |
| PickItem.TakeAll の重量超過の ShowYesNo（プールスレッド）【懐疑レンズが追加】 | プールスレッドの経路 S（`XRL.UI/PickItem.cs:811`） | ShowYesNo | 同じ | 同じ | `No` | 不要 | medium | なし |
| PickGameObjectScreen の上に重なる PickTarget【懐疑レンズが追加】 | 二重（`Qud.UI/PickGameObjectScreen.cs:604-612`） | ビューは `"PickTarget"` で、PickGameObject の tcs は未完了 | ピッカー | 先にピッカーに答える | ピッカー | 不要 | medium | どの操作で起きるか |

### 2.4 F4 全画面のステータス系

| モーダル種別 | ゲームスレッドの待ち方 | 検出述語 | 読取元 | 応答手順 | 取消手順 | Harmony | 確度 | 実機 |
|---|---|---|---|---|---|---|---|---|
| StatusScreensScreen（8 タブ） | ゲームスレッドの `show(...).Result`（`XRL.UI/Screens.cs:80, 125`）。中の操作は APIDispatch のプールスレッドで走る | UI: ビュー `"StatusScreensScreen"`、`navigationContext.IsActive()`、tcs（`menucomplete`。`:177` で作り直された後に取る） | 画面は読まず、直接 API を使う（F4 §3.2 の表）。今のタブは `CurrentScreen % Screens.Count` | 中の確認は F1 で答える（待っているのはプールスレッド）。入れ子の PickGameObject、Book、ピッカー、AskNumberScreen は各ファミリへ | `Exit()`。ガードとトークンを確かめてから呼ぶ | 不要 | high | タブ順、`IsActive()` が真になるまでのフレーム数 |
| AbilityManagerScreen | ゲームスレッドの `OpenAbilityManager(GO).Result`（`XRL.UI/AbilityManager.cs:149`） | UI: ビュー、`navigationContext.IsActive()`、`!AbilityManagerLine.dragging`、tcs | `filteredItems[i].ability` | `HandleSelectLeft(filteredItems[i])`。**できれば画面を開かず**、ゲームスレッドで世界地図の判定（`XRLCore.cs:1812`）をしてから `CommandEvent.Send` を呼ぶ | `Cancel()` | 不要 | high | 選択後に窓が消えるか |
| OptionsScreen（`"ModernOptionsMenu"`） | ゲームスレッドの `OptionsMenu().Result` | UI: ビュー、`completionSource` が未完了、`globalContext.IsActive()` | 不要（`Options.*` を読む） | なし | `Exit()`。入れ子の Keybinds やヘルプのポップアップを先に閉じる | 不要 | high | なし |
| KeybindsScreen（`KeyMappingUI.Show` のときはビュー `"Keybinds"`。Options から開いたときはビューを積まず、待つのは UI スレッドの HandleSelect）【後者は懐疑レンズが追加】 | `KeybindsMenu().Result`、または UI 側の async | UI: `completionSource` が未完了、`isActiveAndEnabled`、`globalContext.IsActive()`、`!ControlManager.mappingMode` | 不要 | なし | `Exit()` は async void なので 1 回だけ呼ぶ。`bChangesMade` なら保存の問いに F1 で `No` と答える | 不要 | high | なし |
| キー割り当ての捕捉（GetRebindAsync） | UI 側の RebindingOperation（`XRL.UI/CommandBindingManager.cs:1912-1920`） | `ControlManager.mappingMode` | なし | 物理キーだけ | 10 秒のタイムアウトを待つ。合成の Cancel キーイベントは候補だが未検証。即時中止の最後の手段は Harmony の prefix（§5） | 即時中止だけ候補 | medium | あり（C-F4-status-screens-16） |
| HelpScreen（`"ModernHelp"`） | ゲームスレッドの `HelpMenu(...).Result` | UI: ビュー、`completionSource` が未完了（Exit の後もビューは残る）、`globalContext.IsActive()` | `The.Manual.Pages` | なし | `Exit()` | 不要 | high | なし |
| レベルアップと購入の確認（Leveler、BuyStat、変異、スキル） | ゲームスレッドかプールスレッドで経路 S | F1 | F1 | 明示の項目を選ぶ | **`No` の項目を渡す。** Hide で閉じると既定の Yes になり、購入が成立する（C-F4-status-screens-07 / 18）。PickOption は 0 番を選んでしまう | 不要 | high | なし |
| 焚き火と料理 | F1 の各種と AskNumberScreen | F1 と AskNumberScreen | 同じ | 同じ | 同じ | 不要 | high | なし |
| 混成構成（`ModernUI=Yes`、`ModernCharacterSheet=No`）での Legacy のステータス画面【懐疑レンズが追加】 | getvk ループ（`Screens.cs:128-151`）。PopupScreens（`:84`）もある | ビュー `"StatusScreens"` | `CurrentBuffer` | `PushKey` | `PushKey(Escape)` | 不要 | low | 構成を Yes に固定して避ける |

### 2.5 F5 そのほかのブロッキング画面

| モーダル種別 | ゲームスレッドの待ち方 | 検出述語 | 読取元 | 応答手順 | 取消手順 | Harmony | 確度 | 実機 |
|---|---|---|---|---|---|---|---|---|
| TradeScreen（取引とコンテナ格納） | ゲームスレッドの `TradeScreen.show(...).Result`（`XRL.UI/TradeUI.cs:456-463`） | UI: ビュー `"ModernTrade"`、`TradeScreen.instance.navigationContext.IsActive()`（busy 信号の代わり）、tcs。先に Book、PopupMessage、PickGameObject、AskNumber の述語を評価する | `tradeEntries[0/1]`（GO が null の行は飛ばす）、`NumberSelected`、`Totals`、`Weight`、`TradeUI.GetValue(go, bool)` | 数量を `[0, go.Count]` にクランプしてから設定し、`UpdateTotals` と `UpdateViewFromData` の後に `HandleOfferTrade()`。ブリッジ側で実行中フラグを持つ | `Cancel()`。実行中フラグが立っている間は呼ばない | 不要 | high（仕組み）/ medium（申し出の順序） | 申し出の途中で NavigationController が邪魔をしないか |
| 取引の申し出の中のポップアップ | プールスレッドの経路 S（`TradeUI.cs:1296-1390`） | F1。取引の述語より先に評価する | F1 | F1 | `No` | 不要 | high | なし |
| BookScreen | ゲームスレッドの `.Result`（`XRL.UI/BookUI.cs:429, 466`） | UI: ビュー `"Book"`、`isCurrentWindow()`、`navigationContext.IsActive()`、tcs | `Book` が null（ShowBookByID）なら `BookUI.Books[BookID].Pages`、そうでなければ `Book.Pages` | ページごとの効果が要るときは、1 タスクに 1 回ずつ `HandleMenuOption(NEXT_PAGE)`（コールバックは表示したページにしか走らない） | `Cancel()`。コールバックが終わってから呼ぶ | 不要 | high | なし |
| CyberneticsTerminalScreen / GenericTerminal | ゲームスレッドの `.Result`。ビュー `"CyberneticsTerminalScreen"` は pop されない（`XRL.UI/CyberneticsTerminal.cs:196-203`） | UI: `completionSource` が未完了、`isCurrentWindow()`、`initReady`、トークン（completionSource と CurrentScreen）、実行中フラグなし | `CyberneticsTerminal.Instance.CurrentScreen.RenderedTextForModernUI` と `Options` | `displayScroller` 自身のデータ要素で `CursorDone` が真のものを `HandleSelect` に渡す。ブリッジで作った要素は黙って無視される | `Exit()`。実行中フラグが立っている間は呼ばない | 不要 | high | ビュー名が残るか |
| GameSummaryScreen | ゲームスレッドの `.Result`（`XRL.UI/GameSummaryUI.cs:29-33`） | UI: `completionSource` が未完了、ビュー、`isCurrentWindow()` | `Name`、`Details`（await の前に代入される） | `Exit()` | 同じ | 不要 | high | 読める時点 |
| 死亡メニュー | F1 | §2.1 | F1 | 文字列で選ぶ | なし | 不要 | high | なし |
| Sifrah | getvk。ゲームスレッドとは限らず、端末のハックでは APIDispatch のプールスレッドになる（`XRL/SifrahGame.cs:646-760`） | ビュー `"Sifrah"`（どのスレッドが回していても使える） | `TextConsole.CurrentBuffer`（80×25） | イベントを 1 個積み、状態の変化（ポップアップが出る、getvk に戻る）を見てから次を積む。`ClearInput` は入口、各手の後、出口で走る | `Escape` を積み、続く確認に F1 で答える | 不要 | high | 画面にどう映るか |
| チュートリアルのオーバーレイのポップアップ（ShowCIDPopupAsync / ShowIntermissionPopupAsync。終局のコーダ、JoppaWorldTutorial の死亡、チュートリアルのセーブのロードでも出る） | UI 側の `PopupCompletion`。ゲームスレッドは同期では待たない。ただしコーダは例外で、`EndGame.cs:495` がこれを待つ | UI: private static の `instance` をリフレクションで取り（`FindObjectOfType` は非アクティブを飛ばす）、private の `ShowingPopup`（`TutorialManager.cs:85`）を読む。`instance.gameObject.activeInHierarchy` も見る。**毎ティック、最優先で評価する** | private の `PopupText`（`TutorialManager.cs:87`） | `OnPopupAcceptPressed()`（`:764-767`）か、public の `popupAcceptPressed = true`（`:133`）。次の Update で完了する | 同じ。`EndTutorial()` は表示中のポップアップを解放しない | 不要 | high（仕組み）/ medium（Tutorial モード以外） | 非アクティブのときに効くか |
| 終局演出（暗転、クレジット、コーダ） | `Thread.Sleep(11000)`、クレジットの `Task.Wait`、コーダの `ev.WaitOne()` には期限がない（`XRL.World.Conversations.Parts/EndGame.cs:282-293, 495`） | ビュー `"Cinematic"` / `"Empty"`、`EndgameCredits` が active | なし | **コーダの幕間のポップアップに Accept が必要**（C-F5-other-blocking-18 は反証）。クレジットの早送りは `running == true` を見てから `runtime = scrollTime + 1` | なし | 不要 | high（反証の訂正） | あり |
| 主メニュー | ゲームスレッドの getvk（`XRLCore.cs:3727-3729`） | ビュー `"MainMenu"`、主メニューの子窓も DynamicPopupMessage も出ていない | 固定 | `PushMouseEvent("Pick:New Game" / "Pick:Continue")`。Q、`"Quit"`、`"Pick:Quit"` は積まない | なし | 不要 | high | なし |
| 主メニューの UI 側の窓（Redeem Code の AskStringAsync、ModManagerUI、ModToolkit、AchievementView）【懐疑レンズが追加】 | ゲームスレッドは止まらない（`Qud.UI/MainMenu.cs:293-345`） | 各窓が active | なし | 開かない | 各窓の Exit | 不要 | medium | なし |
| HighScoresScreen【懐疑レンズが追加】 | `HighScoresScreen.ShowScreen().Wait()`（`XRLCore.cs:3808-3831`） | 画面が active | なし | 使わない | `Exit()` は null で完了する | 不要 | medium | なし |
| SaveManagement（Continue） | ゲームスレッドの `ContinueMenu().Wait()`（`XRLCore.cs:3786`） | UI: ビュー `"ModernSaveManagement"`、`completionSource` が未完了、`savesScroller.GetNavigationContext().IsActive()` | `SavesAPI.GetSavedGameInfo()` | トークンを確かめてから `SelectedInfo(choice)` | `Exit()` | 不要 | high | なし |
| ロード時のポップアップ（古い形式の ShowAsync、LoadGame のエラーをプールスレッドから出すもの）【懐疑レンズが追加】 | F1 | F1 | F1 | F1 | F1 | 不要 | medium | なし |
| mod 構成の不一致 | UI の async ポップアップ。ゲームスレッドは SaveManagement の `.Wait()` の中にいる | F1 の複製。タイトルは "Incomplete Mod Configuration" / "Mod Configuration Differs" | F1 | 1 番（"Load keeping current mod configuration"）。**0 番を選ぶと `GameManager.Restart()` が走る** | -1 | 不要 | high | なし |
| キャラクター作成（EmbarkBuilder） | ゲームスレッドの `EmbarkBuilder.Begin().Result`（`XRLCore.cs:2853`） | UI: コンポーネントが付いている、`finishedEvent` が未完了、ビュー `"EmbarkBuilder"` | `activeWindow.viewID`、public の `pregens` のキー | 1 タスクに 1 手ずつ: `SelectMode` → `selectType` → `SelectPregen`（存在するキーだけ）→ `advance`。手を打つたびに viewID が変わり、ポップアップが出ていないことを確かめる。`advance`（`XRL.CharacterBuilds/EmbarkBuilder.cs:206`）は UI の async void で、`checkStateAsync`（`:190-202`）が経路 A の複製ポップアップを出す。エラー（SingleButton、`:195`）には `Accept` で答え、同じ窓の不備を直す。警告の "Continue anyway?"（YesNoButton、`:199`。`"Yes"` 以外なら進まない）には、既定で `No`、進めると決めたときだけ `Yes` で答える。ビルドライブラリの "Manage Build"（AcceptCancelButton と選択肢、`XRL.CharacterBuilds.Qud.UI/QudBuildLibraryModuleWindow.cs:122`）は開かない。開いたら `Cancel` で答える | `back()` の後に `exitWithoutInfo` | 不要 | medium | 最終窓と起動後の流れ |
| WorldGenerationScreen / OpeningStory（キャラクター作成の後）【懐疑レンズが追加】 | WorldGenerationScreen は応答を待たない表示である。`ShowWorldGenerationScreen`（`Qud.UI/WorldGenerationScreen.cs:82-86`）は UI コンテキストで表示し、`EmbarkBuilder.cs:271` と `XRL.CharacterBuilds.Qud/QudGameBootModule.cs:237`（`.Result`）から呼ばれる。OpeningStory は、最初の `BeforeTakeActionEvent`（`XRL.World.Parts/OpeningStory.cs:29-57`）で `WorldGenerationScreen.HideWorldGenerationScreen()`（`:56`）の後に `Popup.Show(text)`（`:57`）を呼ぶ | OpeningStory は F1 の Show。ゲームスレッドから呼ばれれば経路 S、UI スレッドからなら経路 A（`XRL.UI/Popup.cs:804-821`） | F1 | OpeningStory は F1（単一ボタン）。WorldGenerationScreen に答える操作はない | WorldGenerationScreen の `Exit()` は空（`:269`） | 不要 | medium（OpeningStory が F1 であること）/ low（流れの全体） | WorldGenerationScreen が閉じるまでの流れ |

## 3. 横断ルール

### 3.1 スレッドとキュー

**UI ティック。** 自分自身を積み直す uiQueue タスクを 1 本だけ走らせる。

- `executeTasks` は、呼ばれた時点の件数だけを処理する。そのため、自分を積み直すタスクは 1 フレームに 1 回走る（`QupKit/ThreadTaskQueue.cs:33-75`。C-F6-threads-hooks-02 は確立）。
- 検出、読み取り、応答、`PushKey` / `PushMouseEvent` は、すべてこのティックの中で行う。
- ティックは、ブリッジが持つ `ConcurrentQueue` を空にする。
- 積み直しは `finally` の中で行う。そうしないと、例外が 1 回起きただけでティックが黙って止まる（F6 レンズ P）。

**最初の起動と hotload。**

- 最初の 1 回は `[ModSensitiveCacheInit]` から積む。このメソッドは UI スレッドで、ゲームスレッドより前に走る（C-F6-threads-hooks-18 は確立）。
- hotload のときも、同じメソッドが呼び直される。
  - wish `reload` は、`uiQueue.awaitTask` の中で `HotloadConfiguration` を呼ぶ（`XRL.World.Capabilities/Wishing.cs:1006-1013`）。したがってこの経路では UI スレッドで走る。F6 レンズ T は「ゲームスレッドから呼ばれる」としたが、この経路についてはそうではない。
  - どちらのスレッドから呼ばれても、前のティックは uiQueue に残っている。
  - 世代番号の static を持ち、古い世代のティックは積み直しをやめる。
  - これを怠ると、ティックが 2 本になり、同じポップアップに二度答える（F6 レンズ T の major）。

**タスクの積み方。**

- ブリッジスレッドから `uiQueue.queueTask` を何度も呼ばない。
- `poolEntry` は、ロックなしで `taskPool.Enqueue` をする（`QupKit/ThreadTaskQueue.cs:23-26`）。
- 一方、`queueTask` はロックの中で取り出す（`:157-176`）。ブリッジが積むたびに、この競合が起きやすくなる。
- 代わりに次のどちらかを使う。
  - `The.UiContext.Post`（エンジン自身が別スレッドから Post している。`XRL.UI/Popup.cs:759`）。
  - UI ティックの `ConcurrentQueue`。

**例外。**

- `queueTask` の例外は `ThreadTaskQueueEntry.Execute` に握りつぶされる（`QupKit/ThreadTaskQueueEntry.cs:30-45`）。
- 結果が要る処理は、UI ティックの `ConcurrentQueue` に積み、ブリッジ側の TaskCompletionSource で返す。
- `executeAsync`（`:77-100`）はブリッジスレッドから使わない。中で `queueTask` を呼ぶので（`:97`）、上の競合に当たる。ティックが止まったときの比較用の経路は、`The.UiContext.Post` にする（`XRL/The.cs:41`）。
- TaskCompletionSource は `RunContinuationsAsynchronously` 付きで作るか、ブリッジ専用のスレッドで `.Wait(timeout)` する。そうしないと、ブリッジの継続が UI スレッドの上でインラインに走りうる（F7 レンズ T）。

**ブリッジスレッド。**

- `awaitTask` を使わない。タイムアウトがないためである（C-F6-threads-hooks-04 は条件付き）。
- `Wait(timeout)` がタイムアウトしても、積んだ処理はキューに残り、後で実行される。したがって、応答の処理は実行される時点でトークンを検証し、ブリッジが立てた取消フラグも見る。
- ブリッジが直接読んでよいものは、次の二つだけである。
  - `CurrentGameView`（不可分に読める）。
  - `GetGameViewStackCopy()`（ロックの中でコピーする）。
- Unity のプロパティと `windowsByName` は UI ティックの中でだけ読む（C-F6-threads-hooks-16 は確立）。

**ゲームスレッドのティック。**

- EndPlayerTurn のコールバック（Single:false）は、PlayerTurn のループの反復ごとに走る（`XRL.Core/XRLCore.cs:2355-2359`）。ただし次の条件がある（C-F6-threads-hooks-14 と 19 は条件付き）。
  - AutoAct 中は Begin だけが呼ばれ、End は呼ばれない（`XRL.Core/ActionManager.cs:805-809`）。
  - End から積んだコマンドは、エネルギーを使わなかった反復（`Energy >= 1000`）でしか読まれない。使った反復の場合、次の PlayerTurn の入口 `XRLCore.cs:734` で捨てられる。
- wish を起動したいときは、`PushCommand("CmdWish")` ではなく、End から一度だけのフラグで `WishManager.AskWish()` を直接呼ぶ。
- 待機中の PlayerTurn は `Keyboard.IdleWait()` で止まる。`OptionDisableAllIdleTileAnimations=Yes` の場合、この待ちには期限がない。依頼を積んだ後は、public static の `Keyboard.KeyEvent.Set()` を呼んで起こす（`ConsoleLib.Console/Keyboard.cs:110`）。

**プローブのポップアップ。** 必ずゲームスレッドから開く。UI スレッドから呼ぶと、経路 A に入って待たずに戻る（`XRL.UI/Popup.cs:803-821`。C-F6-threads-hooks-22 は確立）。

**待っているのがゲームスレッドとは限らない。**

- 次の場合は、プールスレッドが待つ。
  - APIDispatch の中のポップアップ（ステータス画面、取引の申し出、端末、TakeAll）。
  - 端末のハックから入る Sifrah。
- この間、ゲームスレッドは外側の `.Result` で止まっている。
- したがって、トークンはポップアップのインスタンスとコールバックの参照に結び付け、「ゲームスレッドの状態」には結び付けない。

**モーダル中の読み取り。**

- モーダルの待機中は gameQueue が回らない（C-F7-observation-03 は条件付き）。
- 読み取りは UI タスクで行う。ただし、次の三つの場合には、生きているゲームコードと競合する。
  - RenderMapBehind の会話。33ms ごとに `RenderBaseToBuffer` が走る。
  - PickTarget のループ。
  - APIDispatch の最中。
- これらの場合、ゲームの API は UI スレッドから呼ばず、ゲームスレッドの AfterRender コールバックで取った値を使う。

### 3.2 トークンと二重回答の防止

述語だけではトークンにならない。単体の窓は次のノードや次のポップアップにすぐ再利用され、複製の窓はプールから再利用されるからである（C-F7-observation-05 は条件付き）。

| 対象 | トークン | 応答タスクの中で再確認すること | 成功の確認 |
|---|---|---|---|
| PopupMessage（単体と複製） | `onHide`、`commandCallback`、`selectCallback` の参照 | D(w)、参照が同じであること | 同じタスクで `!ReferenceEquals(onHide, token)` になったこと（§2.0 tok(w)。これで十分）。呼んだコールバックが null になったことは、診断として記録する |
| `.Result` 型の Modern 画面 | リフレクションで読んだ `menucomplete` / `completionSource` の参照 | 同じ参照で、`!Task.IsCompleted`、`isCurrentWindow()`、`navigationContext.IsActive()`（または `globalContext.IsActive()`） | ビューが元に戻ること。次の待ち（入力ループかポップアップ）が観測されること |
| getvk ループのピッカー | インスタンスのトークンはない | P'、ビュー、モード。`bViewUpdated` の立ち上がりを「別のインスタンス」とみなす | ビューが変わること。確実に知るには prefix が要る（§5） |
| 取引、端末、本の途中の操作 | ブリッジ側の実行中フラグ | `navigationContext.IsActive()`。入れ子のポップアップがないこと | 入れ子の処理が終わって、同じ画面に戻ったこと |

### 3.3 順序（毎ティックの評価順）

1. **チュートリアルのオーバーレイ**（`ShowingPopup`）を最初に見る。
   - これが立っている間は、`PushKey`、`PushMouseEvent`、`OnActivateCommand` / `OnSelect`、FrameworkScroller の Accept、ControlManager のコマンドが、すべて黙って捨てられる。
   - ただし、`TradeScreen.Cancel` などの直接呼び出しは捨てられない（C-F5-other-blocking-16 は条件付き）。
2. **入れ子の PopupMessage。**
   - 複製は後から作られるので、先に見る。
   - 同じ親の中で sibling index が最大のものを選ぶ。親が違うものの間では複製を選ぶ（§2.0 D(w)）。
3. **スタックの最上位にある Modern 画面とピッカー。**
   - `CurrentGameView` が `"PickTarget"`、`"ModernPopupGamepadAskNumber"`（`XRL.UI/Popup.cs:1327`）、`"Book"`、`"PickGameObject"`（`Qud.UI/PickGameObjectScreen.cs:233`）のどれかか、その画面の `isCurrentWindow()` が真のものを先に見る。
   - `GetGameViewStackCopy()` に含まれるだけの画面（スタックの途中にある画面）は、ここでは選ばない。その上に、ピッカーやポップアップなどの別の画面が重なっていることがあるからである。
4. **ホストになっている画面。** スタックの途中にある AskNumber、Book、PickGameObject と、Trade、StatusScreens、端末など。
5. **主の入力待ち。** getvk のピッカー、主メニュー、PlayerTurn。

**そのほかの規則。**

- 1 タスクで行う操作は 1 つにする。例: 数量を 1 つ設定する、ページを 1 枚めくる、EmbarkBuilder で 1 手進める、Sifrah でイベントを 1 個積む。
- 操作の後は、状態が変わるのを見てから次へ進む。
- `PickOption` は、戻った直後に `Keyboard.ClearInput` を呼ぶ（`XRL.UI/Popup.cs:1759`）。そのため、次の入力は次の待ちを検出してから積む。

### 3.4 複製の窓

- 経路 A と、UI スレッドから呼ばれた経路 S は、`copyWindow` の複製 `"PopupMessage #N"` を使う（`Qud.UI/UIManager.cs:323-352`）。
- 複製は release の後も `windowsByName` に残る。非アクティブになるだけである。
- `Visible` は Hide の後 2 フレームのあいだ偽陽性になる。そのため `activeSelf && canvasGroup.interactable && onHide != null` で判定する（C-F6-threads-hooks-17 は確立）。
- 経路 A では、キャンセルすると AskString / AskNumber が null を返す。それを受けた `EndGame.cs:162` は NRE を投げる（C-F1-popup-07 は確立）。

### 3.5 キャンセルの意味（async void の帰結）

`WaitNewPopupMessage` は `async void` である（`XRL.UI/Popup.cs:801`）。

**経路 S のキャンセルと失敗。** 次のどれかが起きた場合を考える。

- Hide を先に呼んだ。
- ShowPopup の健全性チェックが onHide を呼んだ。
- text が null の項目で失敗した。

このとき例外は呼び出し元に届かない。呼び出し元は、エラーなしに既定値で戻る。

| 呼び出し | キャンセル時に返る既定値 |
|---|---|
| ShowYesNo | `Yes`（`:2257`） |
| ShowYesNoCancel | `Cancel` |
| PickOption | `DefaultSelected` |
| ShowConversation | 0。つまり最初の選択肢が選ばれる |

- 通常の `Wait` 経路では、`PopGameView`（`:910`）が飛ばされ、`"PopupMessage"` がビューのスタックに残る。
- ThreadPool で例外が再送出されたとき、Mono がログに残すだけか、プロセスを落とすかは実機で確かめる。

**規則。**

- `Hide()` を先に呼ばない。
- 渡すのは `menuData` か `bottomContextOptions` の実物だけにする。
- 答えた直後に、同じタスクでコールバックが null になったかを確かめる。
- 答えを出さずに放置することもしない。

### 3.6 チュートリアル

- `TutorialManager.ShowingPopup` は private（`TutorialManager.cs:85`）である。
- 解放できるのは、public の `OnPopupAcceptPressed()` か `popupAcceptPressed`（`:764-767, :133`）と、それに続く Update だけである。
- Update は、TutorialManager の GameObject が active のときにしか走らない。
- このポップアップは Tutorial モード以外でも出る。
  - 終局のコーダの FadeText（`XRL.UI/FadeText.cs:68-76`）。
  - JoppaWorldTutorial の死亡。
  - チュートリアルのセーブのロード（`TutorialManager.cs:40-52`）。
- したがって、この検出はモードを問わず毎ティック行う（C-F5-other-blocking-17 は条件付き）。

**応答の規則。**

- トークンは、private static の `PopupCompletion`（`TutorialManager.cs:95`）の参照である。ポップアップごとに作り直される（`:199`、`:256`）。
- Accept は、トークンごとに 1 回だけ押す。
- `popupAcceptPressed` が既に立っていたら、押さない。Update がこのフラグを消費するのは `ShowingPopup` が真の間だけなので（`:769-789`）、残ったフラグは次のポップアップを黙って閉じる。
- 押してから約 3 秒たってもトークンが同じなら、「Update が回っていない」と記録し、押し直さない。

### 3.7 ゲームパッドとコントローラの種類

- `ControlManager._activeControllerType` は初期化子を持たない。したがって初期値は enum の 0、つまり Mouse である（`ControlManager.cs:337`）。
- 値を書くのは、本物の InputSystem のイベントだけである。
- したがって、人が触らない環境では `AskNumberAsync` の `!= Keyboard` が真になり（`XRL.UI/Popup.cs:1323`）、AskNumberScreen が使われる。
- AskNumber は「一つのモーダルに二つの表面がある」ものとして扱い、両方の述語を常に評価する。
- ゲームパッドがつながっていると、`CancelButton` と `SingleButton` の text が変わる。command は変わらないので、項目の同定は command で行う。

### 3.8 フォーカス

- 非フォーカスでも uiQueue は回る。ただし、1 フレームごとに `Thread.Sleep(250)` が入る（`GameManager.cs:3108-3113`）。
  - `UpdateView` は走らないので、P' は永久に偽のままになる。
  - PlayerTurn は `while(!focused) Sleep(200)` で止まる（`XRLCore.cs:737-740`）。
- `Application.runInBackground` は `OptionMusicBackground` に従う（`XRL.UI/Options.cs:1445-1453`）。
  - EndGame と AscendAnimation は、この値を一時的に上書きし、後で元に戻す。
  - false のまま非フォーカスになると、Update そのものが止まるおそれがある（実機）。
- mod は起動時に UI スレッドで `Application.runInBackground = true` にし、その後も定期的に書き直す。
- `XRLCore.bThreadFocus` と `GameManager.focused` を毎ティック true に書き直す案もある。
  - 書き直しで false から true に変わると入力が消えるので（`GameManager.cs:404-418`）、入力を積む前に書く。
  - 効果は実機で確かめる。
- 実機（2026-09-26、走行 4 の `probe:focus:play`、`probes/R5-modal-driver/results/2026-09-26-run4.md`）: `runInBackground=true`、毎 tick の `bThreadFocus=true`、`GameManager._focused=true` をフィールドへ直接書く（setter を通さないので `ClearInput` は走らない）の 3 点で、非フォーカス 30 秒の間に UI タスクから積んだ `CmdWait` 30 回のうち 28 ターンが進んだ（UI tick 143 Hz）。`_focused` の書き直しは 1 回で足りた（非フォーカス中は `OnApplicationFocus` が再び偽を書かない）。緩和策なし（`OptionMusicBackground=No`）では Update 自体が 0 Hz で止まる。
  - 副作用: 実際に再フォーカスしたとき setter は false→true の遷移を見ないので `Keyboard.ClearInput()` が走らない。人が触らないエージェントでは問題にならない。
  - ブリッジは 3 点を周期的に再設定する。長時間の安定性は未測定。

### 3.9 実行プロファイルで固定するオプション

| オプション | 値 | 理由 |
|---|---|---|
| `OptionCapInputBuffer` | No | 3 件を超えた入力を黙って捨てるため（`ConsoleLib.Console/Keyboard.cs:777-796, 825-849`） |
| `OptionMusicBackground` | Yes | runInBackground のため。mod 側でも書き直す |
| `OptionModernCharacterSheet` | Yes | 混成構成の Legacy 画面を避けるため |
| `OptionDisableAllIdleTileAnimations` | No | 無期限の IdleWait を避けるため。または `KeyEvent.Set()` を使う |
| `Options.Sifrah*` | bool は No、文字列（`SifrahWaterRitual` など）は `"Never"` | Sifrah を避けるため。`SifrahGame.Installed = false` にしてもよい |
| `OptionDefaultDeathToViewFinalMessages` | どちらでもよい | 死亡メニューは文字列で選ぶため |
| mod 構成 | セーブ時と同じ構成で起動する | mod 構成の不一致の確認で 0 番を選ぶと再起動するため |

## 4. legacy 相当テキストの合成（Modern を表示したまま何が読めるか）

F7 のマトリクス（F7 §5）を、懐疑レンズの修正を反映して整理する。「スレッド」の列の意味は次のとおりである。

| 記号 | 意味 |
|---|---|
| T1 | 素の managed フィールド。任意のスレッドから読めるが、ヒントとして扱う |
| UI | UI ティックの中で読む |
| G | ゲームスレッドのコールバックの中で読む |

### 4.1 読めるもの

| 面 | データ源 | スレッド | 整形の規則 | 根拠と判定 |
|---|---|---|---|---|
| ポップアップの本文、タイトル、選択肢、ボタン | `PopupMessage.Message/Title.text`、`controller.menuData`、`controller.bottomContextOptions`。`contextText.text` と `inputBox.text` は、その GameObject が activeSelf のときだけ読む | UI | 選択肢は command `option:N` で同定する。前置きの `[c]` / `[n]` と会話の末尾の `\n\n` を除く。ボタンの表示は text ではなく command から組み直す（会話の Trade ボタンの text は除去すると `[` が欠ける） | C-F7-observation-01（条件付き）、06、07、25（確立） |
| 会話 | 上に加えて、UI タスクの中で `ConversationUI.CurrentNode/CurrentChoices/Speaker` | UI | 表示は PopupMessage の文字列を正とする。`GetDisplayText` はゲームスレッド以外から呼ばない。Hash / Visited は述語を確かめたタスクの中だけで読む | C-F2-conversation-13（確立）、14（条件付き） |
| PickGameObject | `rawGameObjects`、`listItems`、`titleText.text` | UI（エンジン自身が UI スレッドで分類を計算している） | 全件は `rawGameObjects` から読む。カテゴリ順のときは、`listItems` に畳まれた分類が入らない | C-F7-observation-15（確立）、C-F3-pickers-20（条件付き） |
| ピッカーの案内文 | `PickTargetWindow.currentText/currentMode` | T1 | 直前のピッカーの文が残りうるので、ビューとモードの論理積で読む。PickTarget の lock / unlock の表記は Legacy と一致しない | C-F3-pickers-13（条件付き） |
| 射撃の射線 | リフレクションで `MissileWeapon.PlayerMissilePath` | UI（競合がある） | 2 回続けて読んで一致したら採用する | C-F3-pickers-11、12 |
| Look の中身 | UI では `GameManager.Instance.lookerTooltip.parameterizedTextFields`。Looker の外では、ゲームスレッドで `Look.GenerateTooltipContent` | UI / G | RTF タグを除く | C-F7-observation-21（部分反証。§7） |
| 取引 | `tradeEntries`、`NumberSelected`、`Totals`、`Weight`、`TradeUI.GetValue`、`GetFreeDrams` | UI（APIDispatch の最中は読まない） | 値段は `0.00` 書式。GO が null の行は飛ばす | C-F7-observation-13、C-F5-other-blocking-04（確立） |
| ステータス類 | `Statistics`、`Effects`、`Body`、`Inventory`、`ActivatedAbilities`、`Skills.SkillList`、`Mutations.MutationList`、`XRLGame.Quests`、`JournalAPI` | G（PlayerTurn）。モーダル中は UI | 画面は開かない | F7 §4.6 |
| メッセージログ | `XRLCore.RegisterNewMessageLogEntryCallback` | 呼び出し元のスレッド（プールもありうる） | スレッド安全なキューで受ける。hotload のたびに登録し直す | C-F7-observation-16（確立） |
| HUD（HP、能力値、空腹、重量、時刻、ゾーン名、効果、ターゲット） | PlayerStatusBar / AbilityBar と同じ API を、同じ XRLCore のコールバックで読む | G | Modern の Sidebar は ScreenBuffer に書かない（C-F7-observation-19 は確立）。効果の見出しには TMP の `<color>` タグが入るので、元の文字列から組み直す | C-F7-observation-18（条件付き） |
| アビリティのボタン文字列 | `ActivatedAbilities` のエントリ（名前、`[disabled]`、クールダウン、トグル） | G で同じ規則を再現する（エンジンは UI スレッドの `AbilityBar.Update` で組み立てる） | `AbilityBar.cs:558-575` と同じ規則 | C-F7-observation-18（条件付き） |
| 地図（ASCII） | `TextConsole.CurrentBuffer`。`TextConsole.BufferCS` を lock して読む | 任意 | 80×25 | C-F7-observation-20（確立） |
| 地図（タイル） | AfterRender コールバックの引数のバッファの `BackupChar` | G | `ConsoleChar.Copy` は `BackupChar` を写さないので、CurrentBuffer からは読めない | C-F7-observation-20（確立） |
| 本 | `Book == null` なら `BookUI.Books[BookID].Pages`、そうでなければ `Book.Pages` | UI / T1 | 現在のページ番号は private（`leftPageNumber.text` かリフレクション） | C-F7-observation-23（確立） |
| 端末 | `CyberneticsTerminal.Instance.CurrentScreen.RenderedTextForModernUI`、`Options` | T1 / UI | なし | C-F5-other-blocking-11（確立） |
| Sifrah の盤面 | `TextConsole.CurrentBuffer` | 任意 | Modern の窓はない | C-F5-other-blocking-14（条件付き） |
| スクローラーの選択 | `FrameworkScroller.onHighlight` に AddListener する | UI | 27 か所の `RemoveAllListeners` で消されるので、セットアップのたびに付け直す | C-F7-observation-22（条件付き） |

### 4.2 読めないもの、損失があるもの

| 面 | 何が読めないか | 対処 | 判定 |
|---|---|---|---|
| PickTarget のカーソル | ローカル変数の x, y（`XRL.UI/PickTarget.cs:400-405`）。`focusPosition` はテンキーの後にしか書かれない | 第一案: `PointerOver` を 2 回積んで押し付ける。第二案: 照準の imposter を走査する。どちらも駄目なら transpiler（§5） | 実機（C-F7-observation-11、26） |
| getvk ピッカーのインスタンスと引数（Style、Range、VisLevel） | static にない | エージェントが自分で開いたピッカーなら、引数を知っている。能力が開いたピッカーは `currentText` の Label から推測する。確実に知るには prefix が要る | F3 §7 の問い 1、2 |
| ShowYesNo の本文をログから取ること | ShowYesNo の本体には `AddPlayerMessage` がない | 窓から読む | C-F7-observation-17（確立） |
| AskString / AskNumber の長い本文 | `ClipText(Message, 60)` で切られている | 画面に出た文字列だけを使う | F7 §9 の問い 5 |
| Look の副作用 | `GenerateTooltipContent` では `LookedAt` / `AfterLookedAt` が発火しない（壁画や村の物語の開示など） | 本物の Look（Looker、`Description`）を使うと発火する | C-F7-observation-21（部分反証） |
| 本のページごとの効果 | データから読んで閉じると、表示したページのコールバックしか走らない | 必要なら画面でページをめくる | C-F5-other-blocking-08（確立） |
| チュートリアルのポップアップの本文 | private の `PopupText`（`TutorialManager.cs:87`） | リフレクションで読む | レンズ P が確認 |
| Alt によるハイライト | 別のデータ源はない | 見えているセルの対象を列挙する | F7 §4.10 |

### 4.3 除去と変換の規則

- `ColorUtility.StripFormatting(string)` は、共有の static `StripSB` を lock の外で使う。したがってブリッジからは呼ばない。
- 代わりに span 版の `StripFormatting(ReadOnlySpan<char>, TextBuilder)` を使うか、`GetNext` と同じ規則の関数を mod 側に移植する（C-F7-observation-08 は確立）。
- 入力欄の値は CP437 変換を通る（`XRL.UI/Popup.cs:761, 784`）。

## 5. Harmony が要る箇所とパッチ点

**必須の箇所はない。** 静的には、Harmony がなければ答えられないモーダルは見つからなかった。

以下はすべて**任意**か、**実機の結果によっては必要になる**ものである。採用する場合は、Harmony 2.2.2 が arm64 で失敗する問題を避けられることが前提になる（Rosetta を使うか、Harmony を 2.4.2 に差し替える）。

**Harmony の実行条件。**

- mod のアセンブリに `HarmonyAttribute` を持つ型が一つもなければ、`PatchAll` は呼ばれない（`XRL/ModInfo.cs:845-861`。C-F6-threads-hooks-23 は条件付き）。
- ただし、本体の `ModManager` は static フィールドで `new Harmony(...)` を作る（`XRL/ModManager.cs:70`）。したがって、0Harmony のアセンブリ自体はどの場合も読み込まれる。生成するだけでは何もパッチしない。

| # | 目的 | パッチ点 | 種類 | 必要になる条件 |
|---|---|---|---|---|
| H1 | PickTarget のカーソル座標を読み戻す | `XRL.UI.PickTarget.ShowPicker`（`XRL.UI/PickTarget.cs:378`）。ローカル変数 x, y を static に書き出す | transpiler（prefix や postfix ではローカル変数に届かない） | `PointerOver` の 2 回押し付けと、照準 imposter の走査の両方が実機で使えないとき |
| H2 | getvk ピッカーのインスタンスのトークンと引数を知る | `PickTarget.ShowPicker`、`PickTarget.ShowFieldPicker`、`PickDirection.ShowPicker`、`MissileWeapon.ShowPicker`、`Look.ShowLooker` | prefix（連番と Style / Range / VisLevel / Label を static に記録） | 同じビューのピッカーが連続して開き、見分けられないことが実機で問題になったとき |
| H3 | キー割り当ての捕捉を即時に中止する | `CommandBindingManager.GetRebindAsync`（`XRL.UI/CommandBindingManager.cs:1912-1958`） | prefix で `Task.FromResult<List<string>>(null)` を返す | 合成の Cancel キーイベントが効かず、10 秒のタイムアウトも許されないとき。エージェントがこの画面を開かない運用なら不要 |
| H4 | 呼び出し元の識別（死亡メニューなど） | `CheckpointingSystem.ShowDeathMessage`、`Popup.PickOption` | prefix | 文字列による判定が曖昧になったとき |

## 6. 実機プローブ計画 R5

### 6.1 共通の仕組み

実装は `probes/R5-modal-driver/ModalProbe.cs` にある。手順と合否の詳細は `probes/R5-modal-driver/README.md` に書いた。

**プローブ mod の構成。** F6 §3.7 の `[HasWishCommand]` の例を土台にし、次の四点を加える。

- `[ModSensitiveCacheInit]` で、世代番号付きの UI ティックを積む。tick が止まっているときだけ、比較用に `uiSynchronizationContext.Post` を 1 回ずつ使う（`XRL/The.cs:41`）。R5 では、この経路を tick と比べるためだけに使う。
- EndPlayerTurn のコールバックで、ゲームスレッドへの依頼を実行する（`probe:endturn:run:<名前>`）。
- ログは `MetricsManager.LogInfo("[R5] ...")` で出す。
- Harmony の属性は一つも使わない。

**ログの見方。**

- ログの出力先は Player.log である（macOS の既定は `~/Library/Logs/Freehold Games/CavesOfQud/Player.log`。04 の 176 行と 197 行）。
- 実際の行は `INFO - [R5] ...` の形になる（`MetricsManager.cs:411-414`）。
- タスクの例外は `ERROR:` で始まる行になる（`XRL.Core/XRLCore.cs:3383-3386`）。

**起動の仕方。**

- wish は `probe:<名前>[:<引数>]` である。`[WishCommand("probe")]`（`XRL.Wish/WishCommand.cs:6-16`）が受け、ゲームスレッドで走る。
- 通常は、オペレーターが `Ctrl+W`（CmdWish）の入力欄に打つ。
- EndPlayerTurn から起動するときは、`probe:endturn:run:<名前>` を打つ。一度だけのコールバックが、次の `Energy >= 1000` の反復で `probe:<名前>` を起動する。
- `gameQueue.queueTask` の後に `Keyboard.KeyEvent.Set()` を呼ぶ起動は、実装していない。

**R5-0 の合否。** R5-0 が不合格なら、ほかのプローブは数えない。

**ログの約束。**

- どのプローブも、最初に `BEGIN r5=<ID> ModernUI=.. ModernCharacterSheet=.. controller=.. capInputBuffer=.. focused=.. tickAlive=.. stack=[..]` を出す。
- answerer は、`DETECT kind=<種別> view=<CurrentGameView> stack=[..] inConversation=.. readMs=<n>` の後に、読み取ったテキストを続けて出す。
- 応答は `ANSWER ...`（ピッカーは `PUSH <ラベル> via=<tick|post> outcome=pushed`）で出す。
- 最後に `RESULT expected=<期待値> got=<値> value=ok|MISMATCH views=restored|LEAKED ... -> PASS|FAIL` を出す。R5-0、R5-F6a、R5-F7a は `RESULT r5=<ID> ...` の形で出す。
- 起動直後と tick の生存確認では `tick alive gen=<n> thread=ui ctl=<_activeControllerType> runInBackground=.. focused=.. bThreadFocus=..` を出す。

### 6.2 プローブ一覧

wish の列が「未実装」の行は、今回のプローブに入れていない。理由は `probes/R5-modal-driver/README.md` §6.3 にある。

| ID | 対象 | wish | 合格の基準 | ログで見る文字列（DETECT / ANSWER / RESULT） |
|---|---|---|---|---|
| R5-0a | UI ティック、hotload | `probe:reload`（エンジンの wish `reload`、`XRL.World.Capabilities/Wishing.cs:1006-1013`） | hotload は同じアセンブリの `[ModSensitiveCacheInit]` を呼び直すだけである（`XRL.Core/XRLCore.cs:575-577`、`XRL/ModManager.cs:340-372`）。tick が生きていれば積み直さないので、世代は増えない。3 秒後も世代が同じで、同じフレームの重複 tick が 0 で、tick が生きている | `tick already alive gen=1 reason=init (not reseeded)`、`RESULT r5=R5-0a gen before=1 after=1 dupTicksDelta=0 tickAlive=True -> PASS` |
| R5-0b | フォーカスと runInBackground | `probe:focus`（基準）、`probe:focus:force`（`runInBackground=true` と毎 tick の `bThreadFocus=true`）。`OptionMusicBackground` を Yes と No で 1 回ずつ。`probe:focus:play`（R5-0b-play。force に加えて毎 tick `GameManager._focused=true` をフィールドへ書き、非フォーカスの間 UI タスクから毎秒 `CmdWait` を積んで `XRLGame.Turns` が進むかを数える） | force のときに、非フォーカスの 1 秒標本が 20 以上、平均 3.5Hz 以上、P' が真の標本が 1 以上。基準のほうは、Update が止まるかを記録する。play は非フォーカスの標本が 10 以上で、進んだターンが 8 以上 | `RESULT r5=R5-0b unfocusedSamples=<n> avgTickHz=<x> P'TrueSamples=<n> rib=<b> -> PASS\|FAIL`、`RESULT r5=R5-0b-play unfocusedSamples=<n> turnsAdvanced=<n> pushes=<n> avgTickHz=<x> -> PASS\|FAIL` |
| R5-0c | コントローラの種類 | なし（起動して何も触らない） | 起動時の `tick alive` 行に `ctl=` が出る。予想は `Mouse` | `tick alive gen=1 thread=ui ctl=Mouse ...` |
| R5-0d | async void のキャンセル（安全な場所で 1 回だけ） | `probe:cancel`（使い捨ての ShowYesNo に、UI タスクから Hide を先に呼ぶ。最後に単独で実行し、その後再起動する） | プロセスが落ちず、3 秒後も tick が生きている。`Yes` と `LEAKED` は予想どおりの所見として記録する | `ANSWER popup Hide() FIRST ... outcome=hidden`、`RESULT r5=R5-0d got=Yes ... views=LEAKED ... tickAliveAfter3s=True -> PASS` |
| R5-0e | UI スレッド以外からの Unity getter | `probe:offthread`（ブリッジスレッドから `activeSelf` を 1 回読む。try/catch） | 例外になるかどうかを記録する。設計は UI タスクでしか読まないので、結果の行が出れば合格 | `RESULT r5=R5-0e offthread activeSelf=<ok:..\|exception:..> -> PASS (informational)` |
| R5-F1a | ShowYesNo | `probe:yesno` | `No` の項目で答えると `No` が返る。同じタスクで onHide がトークンでなくなる | `ANSWER popup command=No token=#<h> via=tick outcome=accepted cbNulled=True`、`RESULT expected=No got=No ... -> PASS` |
| R5-F1b | PickOption（単体の窓） | `probe:pickoption`、`probe:stale` | `option:2` で 2 が返る。古い Snap を次の窓に当てると拒否される | `command=option:2 ... accepted`、`stale-answer rejected outcome=token-mismatch(onHide)`、`RESULT expected=1,2,stale=token-mismatch ...` |
| R5-F1c | PickOption（複製の窓） | 未実装 | 複製で D(w) が真になり、答えられる | （複製の検出と応答は R5-F1d と `probe:asknumber:kb` の `path=A` で見る） |
| R5-F1d | AskString と WantsSpecificPrompt | `probe:askstring`（RETIRE） | `RETIRE` が返る。TMP の setter の後に読み返した値が同じ | `DETECT kind=popup ... path=A`、`ANSWER popup input="RETIRE" ... outcome=accepted selNulled=True readBack="RETIRE"` |
| R5-F1e | AskNumber の二つの表面 | `probe:asknumber:mouse`（AskNumberScreen）、`probe:asknumber:kb`（複製）。参考に `probe:asknumber`、`probe:asknumber:pad` | どちらの表面でも 7 が返る。強制した値は finally の UI タスクで戻す | `expectedSurface=AskNumberScreen\|copy-popup`、`ANSWER AskNumberScreen n=7 ...` か `ANSWER popup input="7" ...`、`controller restored=<元の値>` |
| R5-F1f | 死亡メニュー | `probe:death`（Roleplay。チェックポイントを読み直すので最後に実行する） | 文字列で "Retire character" を選び、RETIRE の入力欄を Cancel で閉じると元のループに戻る。最後に "Reload from checkpoint" を選ぶ | `retire-loop ok newToken=True`、`RESULT expected=true step=3 ...` |
| R5-F2a | 会話ノード | `probe:talk`（Mehmet）、`probe:conv:<ConversationID>` | 選択肢 k を選ぶと、次のノードで新しいトークンになり、`LastChoice` が選んだ選択肢と一致する。`LastChoice` は会話の終わりに `Reset()` で消えるので（`XRL.UI/ConversationUI.cs:385-392, 436-443`）、次のノードの中で確かめる | `conv node=<id> token-changed=True ... lastChoice=<id> expected=<id> -> ok`、`RESULT ... nodeOk>=1 nodeBad=0` |
| R5-F2b | 合成の会話 | `probe:conv`（`option:1` だけ）。`AllowTrade: true` と `Look` の -3 は未実装 | `option:1` で 1 が返る | `DETECT ... PopupID=Conversation:[R5] probe:conv`、`command=option:1 ... accepted` |
| R5-F3a | PickDirection | `probe:pickdir` | P' が真になってから `Keypad6` を積むと `E` が返る | `DETECT kind=picker mode=PickDirection ... P=True`、`PUSH Keypad6 ... outcome=pushed`、`RESULT expected=E got=E ...` |
| R5-F3b | PickTarget のセル選択 | `probe:picktarget` | `PointerOver` を 2 回積み、`CmdFire` を積むと、指定したセルが返る。マウスは地図の外に置く | `PUSH PointerOver#1(x,y)`、`PUSH PointerOver#2(x,y)`、`PUSH Command:CmdFire`、`RESULT expected=(x,y) got=(x,y) ...` |
| R5-F3c | 照準 imposter | `probe:imposter`（`OptionUseTiles=Yes` の起動で。ASCII の起動では前提不成立。`probe:picktarget` と同じ手順の後、`CmdFire` の前に UI タスクで `TextConsole.CurrentBuffer` を `BufferCS` のロック下で走査する） | `Prefabs/Imposters/TargetReticle` が 1 セルだけにあり、押し付けた座標と一致する。AfterRender のコールバックでは見えない（PickTarget が照準を足す前に走る） | `IMPOSTER cells=1 at=(x,y) expected=(x,y) ... -> ok`、`RESULT expected=(x,y) got=(x,y) imposter=ok ...` |
| R5-F3d | PickField | `probe:field`、`probe:field:cancel`（`ShowFieldPicker` は public static なので、Force Projector は要らない。`XRL.UI/PickTarget.cs:84-87`） | `Keypad5`、移動、`Keypad5` で `List<Cell>` が返る（開始と確定のキーは `:322-336`）。取消は Escape を 2 回で、1 回目は消去になる（`:165-186`）。中止は null（`:371-375`） | `PUSH Keypad5(start)`、`PUSH Keypad6(extend)`、`PUSH Keypad5(end)`、`PUSH Escape(clear)`、`PUSH Escape(abort)` |
| R5-F3e | PickGameObjectScreen | `probe:pickitem` | 所持品の最後の品を指定すると、その品が返る | `DETECT kind=pickgameobject raw=<n>`、`ANSWER PickGameObject target=<bp> ... accepted` |
| R5-F3f | Looker | 未実装（エージェントは Look を開かず API を直接呼ぶ、§8.1(3)） | `lookingAt?.CurrentCell` が目標と一致する | なし |
| R5-F4a | StatusScreensScreen | `probe:status` | `Exit()` の後にビューが戻る。`accepted` が示すのは、Exit を呼んだタスクの中で `menucomplete` が完了したことだけである。解除の連鎖がインラインで走ったかは、このプローブでは測らない（C-F4-status-screens-21 は実機のまま） | `status-notready`、`DETECT kind=status ... StatusScreens CurrentScreen=..`、`ANSWER Status Exit ... accepted` |
| R5-F4b | 購入の確認 | 未実装（答え方は R5-F1a と同じ） | `No` で答えると能力値が変わらない | なし |
| R5-F4c | キー割り当ての捕捉 | 未実装（手動の準備が要る。エージェントはこの画面を開かない） | 合成の Cancel か、10 秒のタイムアウトで null になる | なし |
| R5-F5a | 取引 | `probe:trade`（Tam。読み取りと `Cancel()` だけ。申し出は未実装） | 実行中でなく、`navigationContext.IsActive()` のときだけ中身を読み、`Cancel()` でゲームスレッドが戻る | `DETECT kind=trade ... side0(trader) goods=<n>`、busy の間は `trade busy or navigation inactive, not read`、`ANSWER Trade Cancel ... accepted` |
| R5-F5b | 本 | `probe:book`（`BookUI.ShowBook("page","title")`） | `Book` と `BookID` が読め、`Cancel()` で戻る | `DETECT kind=book ... Book title=.. pages=<n>`、`ANSWER Book Cancel ... accepted` |
| R5-F5c | 端末 | 未実装（Joppa の初期状態では開けない。後の段階で行う） | 閉じた後に `CurrentGameView` に `"CyberneticsTerminalScreen"` が残るか | なし |
| R5-F5d | チュートリアルのオーバーレイ | `probe:tutorial`（`TutorialManager.ShowIntermissionPopupAsync`、`TutorialManager.cs:237-240`） | トークン（`PopupCompletion`）ごとに 1 回だけ Accept を押し、Task が完了する。Update が回らず約 3 秒たっても消費されないときは、押し直さずに記録する | `DETECT kind=tutorial token=#<n> ...`、`ANSWER tutorial overlay token=#<n> ... outcome=accept-pressed`、`RESULT expected=released ...`。失敗時は `tutorial Update not running` と `RECOVERY tutorial (probe-only)` |
| R5-F5e | 終局のコーダ（遅い段階） | 未実装（仕組みは R5-F5d と同じ `ShowIntermissionPopupAsync`） | 幕間のポップアップを Accept すると、`EndGame.cs:495` を抜けてセーブまで進む | なし |
| R5-F5f | EmbarkBuilder | 未実装（主メニューにいる間は wish を打てない） | 1 手ずつ進めて `exitWithInfo` に達する。途中の経路 A のポップアップ（§2.5）に答えられる | なし |
| R5-F6a | EndPlayerTurn からのコマンド | `probe:endturn`（待機中）、`probe:endturn:spent`（エネルギーを使った反復） | 待機中なら読まれ、使った反復なら捨てられる（予想どおり） | `pushed Command:CmdWish from EndPlayerTurn mode=<waiting\|spent> energy=<n>`、`RESULT r5=R5-F6a endturn push consumed=<b> ... expected=<b> -> PASS` |
| R5-F6b | MonoBehaviour の Update（第二案） | 未実装（UI ティックが R5-0 を通れば要らない） | Update が呼ばれる | なし |
| R5-F7a | 地図（タイル） | `probe:map`（AfterRender のコールバック） | バッファから 80×25 の字が組める。タイル表示では `Zone.Render` が `Char` を 0 にして字形を `BackupChar` に退避するので、合成は `BackupChar` を読む | `RESULT r5=R5-F7a size=80x25 glyphs(Char)=<n> glyphs(BackupChar)=<m> ...` |
| R5-F7b | UI スレッドでの読み取りの負荷 | 専用の wish はない。すべての分類で計る | ヒッチがない（1 回の読み取りが数 ms 以内） | 各 `DETECT` の `readMs=<n>`、`answerer exit ... uiread maxMs=<n>` |

### 6.3 実機結果（2026-09-26）

R5 を 4 回の走行で実行した（走行 1〜3 は ASCII 描画、走行 4 はタイル表示）。証拠と全プローブの表は `probes/R5-modal-driver/results/`（`2026-09-26-run1.md`〜`run4.md`、各 Player.log、使ったオプション）にある。ここには判断に要る点だけを書く。

- 実行した駆動プローブは、M（§8.2 F-3 の対象）を含めてすべて PASS。`views=restored`、応答は全件 `via=tick`、例外なし。README §10.3 の条件を満たし、F-1〜F-3 は成立しなかった。方向 2 を採る。
- R5-0b: `probe:focus:force` は `OptionMusicBackground` の Yes（118.3 Hz）と No（136.1 Hz）の両方で PASS。対策なしでは Yes で 4.9 Hz（250 ms のゲート）、No で 0 Hz（Unity のループ自体が止まる）。ただし force が示すのは UI ティックの生存だけである。ゲームスレッドの PlayerTurn は `!GameManager.focused` の間 200 ms の待ちに入り（`XRL.Core/XRLCore.cs:737-740`）、force はこのフラグを書き換えない。走行 4 の `probe:focus:play` は、force に加えて `GameManager._focused=true` をフィールドへ書き、非フォーカス 30 秒で 28 ターン進んだ（`pushes=30`、143 Hz）。非フォーカスでの進行は成立する（§3.8）。長時間の安定性だけが残る。
- 走行 4（タイル表示、`OptionUseTiles=Yes`）: R5-0a〜0e と実装済みの全ファミリーを再実行し、駆動の失敗は 0。DETECT / ANSWER / RESULT の文字列と結果は ASCII と同じで、違いは `probe:map` の字形が `BackupChar` に入ることだけ（`glyphs(Char)=0 glyphs(BackupChar)=756`）。走行 3 で未実行だった `probe:asknumber`、`probe:conv:Mehmet`、`probe:endturn:run:yesno` も PASS。`readMs` は 39 件中 38 件が 0 で最大 2 ms（R5-F7b）。
- R5-F3c（`probe:imposter`）: タイル表示で PASS。照準の imposter は UI タスクで `TextConsole.CurrentBuffer` から読め、押し付けた座標 (43,18) と一致した。§8.2 F-4 の「照準 imposter の走査も使えない」は成立しない。
- R5-0d（`probe:cancel`）: `Hide()` を先に呼ぶと Yes と `views=LEAKED` が返り、例外は呼び出し側に届かず、プロセスは落ちなかった（3 秒の観測）。予想どおり。
- 応答の順序: 死亡メニューのプローブで、`OnActivateCommand` の中でゲームスレッドが先に再開し、応答側の UI タスクが戻る前に結果を読む競合が出た。ブリッジは「状態を書いてから応答を呼ぶ」を規則にする。
- 前提不成立: `probe:trade` の既定の Tam は「見つかったが隣接セルが空でない」可能性が高い（Joppa.rpm の (70,19) の周囲 8 マスが家具と壁）。Mehmet では PASS。
- 未実行の wish はない（走行 4 で解消）。未実装の ID は §6.2 のとおり（F1c、F3f、F4b、F4c、F5c、F5e、F5f、F6b）。
- 運用: wish 文字列は自動化ツールで打たず、貼り付ける。打った文字は wish 復帰後に Adventure 層へ漏れ、AbilityManagerScreen が開く（機構は未確定。エージェントは打鍵しないので設計には影響しない）。

## 7. 反証と部分支持の記録

すべての主張 ID について、両レンズの判定と、そこから導いた状態を残す。

- T はレンズ THREAD & LIFECYCLE、P はレンズ PATH COMPLETENESS & CITATION ACCURACY である。
- 「著者 RO」の列は、家族文書の著者が runtime_only とした主張を示す。
- 状態が「確立」でない行には、条件、訂正、または実機での確認点を書く。
- 各レンズの証拠の行番号は、判定の JSON に記録されている。本書では、要点だけを引用する。

### 7.1 F1-popup

| 主張 ID | 著者の確度 | 著者 RO | T | P | 状態 | 条件・訂正・確認点 |
|---|---|---|---|---|---|---|
| C-F1-popup-01 | high | no | 確認 | 部分 | 条件付き | どの窓を使うかは API ではなく呼び出しスレッドで決まる。UI スレッドから WaitNewPopupMessage を呼ぶと、経路 A の複製になる（`Popup.cs:803-821`）。 |
| C-F1-popup-02 | high | no | 確認 | 確認 | 確立 |  |
| C-F1-popup-03 | high | no | 確認 | 部分 | 条件付き | デッドロックしないという結論は成り立つ。継続がどのスレッドで走るかは、標準の TaskAwaiter の挙動しだいである（`Popup.cs:781`、`NavigationController.cs:156-178`）。UI スレッドでインラインに走りうる（実機）。 |
| C-F1-popup-04 | high | no | 確認 | 確認 | 確立 |  |
| C-F1-popup-05 | high | no | 確認 | 確認 | 確立 |  |
| C-F1-popup-06 | medium | no | 部分 | 確認 | 条件付き | 呼び出し元は既定値で戻る。このとき PopGameView（`Popup.cs:910`）が飛ばされ、`"PopupMessage"` がスタックに残る。死亡メニューの 0 番は、オプションしだいで "View final messages" になる（`CheckpointingSystem.cs:113-121`）。プールでの再送出を Mono がどう扱うかは実機。 |
| C-F1-popup-07 | high | no | 確認 | 確認 | 確立 |  |
| C-F1-popup-08 | high | no | 確認 | 確認 | 確立 |  |
| C-F1-popup-09 | medium | no | 確認 | 確認 | 確立 |  |
| C-F1-popup-10 | high | no | 確認 | 確認 | 確立 |  |
| C-F1-popup-11 | high | no | 確認 | 確認 | 確立 |  |
| C-F1-popup-12 | high | no | 確認 | 確認 | 確立 |  |
| C-F1-popup-13 | high | no | 確認 | 確認 | 確立 |  |
| C-F1-popup-14 | high | no | 確認 | 確認 | 確立 |  |
| C-F1-popup-15 | high | no | 確認 | 確認 | 確立 |  |
| C-F1-popup-16 | medium | no | 確認 | 確認 | 確立 |  |
| C-F1-popup-17 | medium | yes | 確認 | 確認 | 実機 | 著者が runtime_only とした。ブリッジから Unity の getter と `windowsByName` に触れてよいかは実機（R5-0e）。 |
| C-F1-popup-18 | medium | no | 部分 | 確認 | 条件付き | フレーム内に走るのは Update が回っている間だけである。非フォーカスで runInBackground が偽なら止まり、真でも 1 フレーム 250ms かかる（`GameManager.cs:3108-3112`）。`poolEntry` の無ロックの競合と、例外の握りつぶしがある（`ThreadTaskQueueEntry.cs:30-45`）。 |
| C-F1-popup-19 | high | no | 確認 | 確認 | 確立 |  |
| C-F1-popup-20 | high | no | 部分 | 確認 | 条件付き | 分岐の条件は `!= Keyboard`（`Popup.cs:1323`）である。`_activeControllerType` の初期値は Mouse（`ControlManager.cs:337`）なので、人が触らない環境では AskNumberScreen に入る。トークンは menucomplete をリフレクションで読む。 |
| C-F1-popup-21 | high | yes | 確認 | 確認 | 実機 | 著者が runtime_only とした。プレハブの UnityEvent の配線はソースにない。 |
| C-F1-popup-22 | medium | no | 確認 | 確認 | 確立 |  |

### 7.2 F2-conversation

| 主張 ID | 著者の確度 | 著者 RO | T | P | 状態 | 条件・訂正・確認点 |
|---|---|---|---|---|---|---|
| C-F2-conversation-01 | high | no | 確認 | 確認 | 確立 |  |
| C-F2-conversation-02 | high | no | 確認 | 確認 | 確立 |  |
| C-F2-conversation-03 | high | no | 確認 | 確認 | 確立 |  |
| C-F2-conversation-04 | high | no | 確認 | 確認 | 確立 |  |
| C-F2-conversation-05 | high | no | 確認 | 確認 | 確立 |  |
| C-F2-conversation-06 | high | no | 確認 | 確認 | 確立 |  |
| C-F2-conversation-07 | high | no | 確認 | 確認 | 確立 |  |
| C-F2-conversation-08 | high | no | 部分 | 部分 | 条件付き | "Conversation:" は `Popup.cs:1613` でしか作られない。ただし「PopupID だけ」は言い過ぎで、command `Look` のボタンも会話ノードにしか付かない（`Popup.cs:1582`、`PopupMessage.cs:72-77`）。 |
| C-F2-conversation-09 | high | no | 部分 | 部分 | 条件付き | キャンセルの経路（Hide と、ShowPopup の onHide 健全性チェック `PopupMessage.cs:723-735`）は、どちらのコールバックも null にしない。述語に `activeSelf` と `onHide != null` を加える。 |
| C-F2-conversation-10 | high | no | 確認 | 確認 | 確立 |  |
| C-F2-conversation-11 | high | no | 確認 | 確認 | 確立 |  |
| C-F2-conversation-12 | high | no | 確認 | 確認 | 確立 |  |
| C-F2-conversation-13 | high | no | 確認 | 確認 | 確立 |  |
| C-F2-conversation-14 | medium | no | 部分 | 確認 | 条件付き | Hash と Visited は純粋なフィールドではない（`Choice.cs:33-35` で遅延して書き込む）。述語を確かめた UI タスクの中でだけ読む。 |
| C-F2-conversation-15 | high | no | 部分 | 部分 | 条件付き | 拒否は Leave（`ConversationUI.cs:553`）や targetNode.Enter でも起きる。「不変なら拒否」という判定は、空の Target による自己遷移（`:592-595`）やチュートリアルのゲートによる no-op を区別できない。次の述語確認済みの読み取りで、新しいトークンと合わせて判定する。 |
| C-F2-conversation-16 | high | no | 部分 | 部分 | 条件付き | 隣接は、話者と Transmitter のどちらでもよい。CanTradeEvent で上書きもされる（`Trade.cs:55-78`）。Visible には AllowEscape も要る。TradeUI は REFRESH / NEXT / TOP で何度も開き直す。 |
| C-F2-conversation-17 | medium | no | 確認 | 確認 | 確立 |  |
| C-F2-conversation-18 | high | no | 確認 | 確認 | 確立 |  |
| C-F2-conversation-19 | high | no | 確認 | 部分 | 条件付き | 水の儀式の YesNoCancel には、WaterRitualed 属性がないことも必要である。"Always" のときは問いなしに Sifrah に入る。既定値が "Never" であることはコードからは言えない（`Options.cs:1537`）。クエストの段階と完了のポップアップ（`Quest.cs:205-223`、`XRLGame.cs:640-671`）も入れ子で出る。 |
| C-F2-conversation-20 | high | no | 確認 | 確認 | 確立 |  |
| C-F2-conversation-21 | high | no | 反証 | 部分 | 反証 | **訂正。** 例外は会話の finally を通らない。WaitNewPopupMessage は async void（`Popup.cs:801`）で、ゲームスレッドの素の SynchronizationContext の下では、プールで再送出される（`XRLCore.cs:3557-3559`）。ShowConversation は初期値 0 を返し、Select(0) が黙って実行される。通常の Wait の経路では PopGameView（`:910`）が飛ばされる。RenderMapBehind の経路では PopGameView は走り、`.Result`（`:913`）が投げる。どちらでも、会話の後に `"Conversation"` がスタックに残りうる（`ConversationUI.cs:391-392`）。 |
| C-F2-conversation-22 | high | no | 確認 | 部分 | 部分反証 | 前半（getvk の Input は RenderClassic からしか呼ばれない）は成り立つ。**後半は反証。** `GameManager.cs:2500` の分岐は ModernUI を要求する。NavCategory "Conversation"（PopupMessage と共有。`PopupMessage.cs:16-17`）のときに、Escape / Tab をキーボードバッファに積むだけである。 |
| C-F2-conversation-23 | medium | no | 確認 | 確認 | 確立 |  |
| C-F2-conversation-24 | medium | yes | 実機 | 実機 | 実機 | prefab の配線（両レンズとも runtime_only）。 |
| C-F2-conversation-25 | high | no | 確認 | 確認 | 確立 |  |
| C-F2-conversation-26 | high | yes | 実機 | 実機 | 実機 | OnActivateCommand(menuData[k]) の端から端までの挙動（両レンズとも runtime_only）。R5-F2a。 |

### 7.3 F3-pickers

| 主張 ID | 著者の確度 | 著者 RO | T | P | 状態 | 条件・訂正・確認点 |
|---|---|---|---|---|---|---|
| C-F3-pickers-01 | high | no | 確認 | 確認 | 確立 |  |
| C-F3-pickers-02 | high | no | 確認 | 確認 | 確立 |  |
| C-F3-pickers-03 | high | no | 確認 | 確認 | 確立 |  |
| C-F3-pickers-04 | high | no | 部分 | 確認 | 条件付き | 前提に `!bViewUpdated` を加え、確認と push を同じ uiQueue タスクで行う（`GameManager.cs:248, 1436-1438, 3172-3183`）。 |
| C-F3-pickers-05 | high | no | 確認 | 確認 | 確立 |  |
| C-F3-pickers-06 | high | no | 確認 | 確認 | 確立 |  |
| C-F3-pickers-07 | high | no | 部分 | 確認 | 条件付き | 戻り値は正しい。NumPad1〜9 は DrawBuffer を先に呼ぶので、「最初に PopGameView」は字義どおりではない。ただし、返る前に必ず pop（と ResetInput）する点は成り立つ。 |
| C-F3-pickers-08 | high | no | 確認 | 確認 | 確立 |  |
| C-F3-pickers-09 | high | no | 確認 | 確認 | 確立 |  |
| C-F3-pickers-10 | high | no | 確認 | 確認 | 確立 |  |
| C-F3-pickers-11 | high | no | 確認 | 確認 | 確立 |  |
| C-F3-pickers-12 | medium | no | 確認 | 確認 | 確立 |  |
| C-F3-pickers-13 | high | no | 部分 | 確認 | 条件付き | currentText は、PushGameView の後の最初の反復でしか書かれず、終了時にも消えない。前のピッカーの文が残りうる。PickTarget の Modern の文は lock / unlock を切り替えない。 |
| C-F3-pickers-14 | high | no | 確認 | 確認 | 確立 |  |
| C-F3-pickers-15 | high | no | 確認 | 確認 | 確立 |  |
| C-F3-pickers-16 | high | no | 確認 | 確認 | 確立 |  |
| C-F3-pickers-17 | high | no | 確認 | 確認 | 確立 |  |
| C-F3-pickers-18 | high | no | 確認 | 確認 | 確立 |  |
| C-F3-pickers-19 | high | no | 部分 | 確認 | 条件付き | Hide は listItems の各要素を free() し、go を null にする（`PickGameObjectLineData.cs:37-41`）。「Hide が先でも安全」なのは、新しい行データを作る場合に限る。 |
| C-F3-pickers-20 | high | no | 部分 | 確認 | 条件付き | 畳まれたカテゴリが抜けるのは SortMode.Category のときだけで、AZ なら全件が入る。rawGameObjects は UI スレッドで並べ替えられるので、検出の後の UI タスクで読む。 |
| C-F3-pickers-21 | high | no | 部分 | 確認 | 条件付き | 開き直すのは、TwiddleObject が RequestInterfaceExit を立てず、Regenerate が空でないときだけである。TAKE_ALL はプールスレッドで走り、uiQueue のタスクは先に戻る。 |
| C-F3-pickers-22 | high | no | 確認 | 確認 | 確立 |  |
| C-F3-pickers-23 | high | no | 確認 | 部分 | 条件付き | 「ゲームパッドのときだけ」は誤り。初期値が Mouse なので、人が触らないと AskNumberScreen に入る。`TradeScreen.cs:247` は pushView なしで呼ぶので、ビュー名では検出できない。 |
| C-F3-pickers-24 | medium | no | 確認 | 確認 | 確立 |  |
| C-F3-pickers-25 | high | no | 確認 | 確認 | 確立 |  |
| C-F3-pickers-26 | medium | yes | 実機 | 実機 | 実機 | 本物のマウスの PointerOver との競合（両レンズとも runtime_only）。R5-F3b。 |

### 7.4 F4-status-screens

| 主張 ID | 著者の確度 | 著者 RO | T | P | 状態 | 条件・訂正・確認点 |
|---|---|---|---|---|---|---|
| C-F4-status-screens-01 | high | no | 部分 | 部分 | 条件付き | MessageQueue.Show は、ModernUI だけで Modern のタブ 7 を開く（`MessageQueue.cs:80-82`）。ShowPopup の Legacy 側は PopupScreens である（`Screens.cs:84`）。 |
| C-F4-status-screens-02 | high | no | 確認 | 部分 | 条件付き | 死亡メニューの "View final messages"（`CheckpointingSystem.cs:121`）も入口になる。CmdFactions は `Screens.ShowPopup` を通る（`XRLCore.cs:1890`）。 |
| C-F4-status-screens-03 | high | no | 確認 | 確認 | 確立 |  |
| C-F4-status-screens-04 | high | no | 確認 | 確認 | 確立 |  |
| C-F4-status-screens-05 | high | no | 部分 | 確認 | 条件付き | IsActive() は必要だが十分ではない。単体の navigationContext は毎回使い回されるので、セッション N と N+1 を区別できない。menucomplete の参照をリフレクションで読み、トークンにする。 |
| C-F4-status-screens-06 | high | no | 確認 | 確認 | 確立 |  |
| C-F4-status-screens-07 | high | no | 部分 | 確認 | 条件付き | `SkillsAndPowersScreen.cs:159` は ShowYesNoCancel である。Modern の ShowYesNo はキャンセルされると既定の Yes を返すので、Hide で閉じると購入が成立する（`Popup.cs:2251-2276`）。 |
| C-F4-status-screens-08 | medium | no | 確認 | 確認 | 確立 |  |
| C-F4-status-screens-09 | medium | yes | 実機 | 実機 | 実機 | タブの並びはプレハブで決まる（両レンズとも runtime_only）。R5-F4a で GetTabString を列挙する。 |
| C-F4-status-screens-10 | high | no | 確認 | 確認 | 確立 |  |
| C-F4-status-screens-11 | high | no | 部分 | 確認 | 条件付き | 直接呼ぶ場合は、ゲームスレッドで、XRLCore の世界地図の判定（`XRLCore.cs:1812`）と BeforeAbilityManagerOpenEvent（`AbilityManager.cs:140`）を再現する。 |
| C-F4-status-screens-12 | high | no | 確認 | 確認 | 確立 |  |
| C-F4-status-screens-13 | high | no | 確認 | 確認 | 確立 |  |
| C-F4-status-screens-14 | high | no | 確認 | 確認 | 確立 |  |
| C-F4-status-screens-15 | high | no | 確認 | 確認 | 確立 |  |
| C-F4-status-screens-16 | medium | yes | 実機 | 実機 | 実機 | 「Harmony なしに即時中止はできない」は、静的には決まらない。合成の Cancel キーイベントが Harmony なしの候補になる（両レンズとも runtime_only）。R5-F4c。 |
| C-F4-status-screens-17 | high | no | 確認 | 確認 | 確立 |  |
| C-F4-status-screens-18 | high | no | 部分 | 確認 | 部分反証 | **部分反証。** 「急速変異の問いはキャンセルできない」は反証された。Modern の ShowYesNo は AllowEscape を渡さず、Cancel を No に写す（`Popup.cs:2270-2272`）。本当の危険は逆で、Hide やキャンセルで既定の Yes が返る。PickOption（`Leveler.cs:341`）はキャンセルされると 0 を返す（`Popup.cs:1664, 1760`）。 |
| C-F4-status-screens-19 | high | no | 部分 | 部分 | 条件付き | 焚き火は、ShowYesNo（`Campfire.cs:1203`）、ShowFail、Popup.PickGameObject（`:1675`）、InventoryActionMenu（`:1292`）も使う。AskNumber は、既定の Mouse のままなら AskNumberScreen に入る。 |
| C-F4-status-screens-20 | high | no | 部分 | 部分 | 部分反証 | **部分反証。** 「Screens 以外からは生成されない」は反証された（`Physics.cs:2733` に `new TinkeringScreen()` がある）。ただし ModernUI では `:2727` で先に return するので、Modern 構成では到達しない、という結論は成り立つ。 |
| C-F4-status-screens-21 | high | no | 実機 | 部分 | 実機 | 解除の連鎖が「UI への Post の後にプールで継続」だという点は、どの行からも示されない。TrySetResult の中で、UI スレッドにインラインで走りうる（T は runtime_only、P は partial）。R5-F4a。 |
| C-F4-status-screens-22 | medium | no | 部分 | 部分 | 条件付き | UIHold はこの二画面に固有ではない。Book、Trade、PickGameObject、AskNumberScreen、prewarm も立てる。汎用のヒントにしかならない。 |

### 7.5 F5-other-blocking

| 主張 ID | 著者の確度 | 著者 RO | T | P | 状態 | 条件・訂正・確認点 |
|---|---|---|---|---|---|---|
| C-F5-other-blocking-01 | high | no | 確認 | 確認 | 確立 |  |
| C-F5-other-blocking-02 | high | no | 確認 | 確認 | 確立 |  |
| C-F5-other-blocking-03 | high | no | 確認 | 確認 | 確立 |  |
| C-F5-other-blocking-04 | high | no | 確認 | 確認 | 確立 |  |
| C-F5-other-blocking-05 | medium | no | 部分 | 確認 | 条件付き | NumberSelected に直接書くと、`[0, go.Count]` のクランプ（`TradeScreen.cs:286-288`）も飛ぶ。setHowManySelected は async なので、async ラムダが要る。await の後の例外はキューの try/catch を抜ける。 |
| C-F5-other-blocking-06 | high | no | 確認 | 確認 | 確立 |  |
| C-F5-other-blocking-07 | high | no | 確認 | 部分 | 条件付き | APIDispatch の最中に、入れ子の Modern 画面（たとえば商人の Read から BookUI.ShowBook）が自分の context を ActivateAndEnable すると、busy 信号が偽になる（`BookScreen.cs:204`）。代わりに `navigationContext.IsActive()` を使う。 |
| C-F5-other-blocking-08 | high | no | 確認 | 確認 | 確立 |  |
| C-F5-other-blocking-09 | high | no | 確認 | 確認 | 確立 |  |
| C-F5-other-blocking-10 | high | no | 確認 | 確認 | 確立 |  |
| C-F5-other-blocking-11 | high | no | 確認 | 確認 | 確立 |  |
| C-F5-other-blocking-12 | high | no | 確認 | 確認 | 確立 |  |
| C-F5-other-blocking-13 | high | no | 確認 | 確認 | 確立 |  |
| C-F5-other-blocking-14 | high | no | 部分 | 確認 | 条件付き | Play はゲームスレッドで走るとは限らない（端末のハックでは APIDispatch のプールスレッド）。ClearInput が入口、各手の後、出口で走る（`SifrahGame.cs:666, 753, 757`）ので、状態を見ながら 1 個ずつ積む。 |
| C-F5-other-blocking-15 | medium | no | 部分 | 確認 | 条件付き | SifrahWaterRitual は文字列のオプションなので、"Never" にしないと避けられない。`SifrahGame.Installed = false` にすれば、すべてが偽か "Never" になる。 |
| C-F5-other-blocking-16 | high | no | 部分 | 部分 | 条件付き | ゲートがかかるのは入力の経路だけである（PushKey、PushMouseEvent、OnActivateCommand / OnSelect、FrameworkScroller の Accept、ControlManager のコマンド）。TradeScreen.Cancel などを直接呼べば通る。「ほかのどの答え方も失敗する」は言い過ぎ。 |
| C-F5-other-blocking-17 | medium | no | 部分 | 部分 | 条件付き | Tutorial モード以外でも出る。終局のコーダ（`FadeText.cs:68-76`）、JoppaWorldTutorial の死亡（`GameObject.cs:15049-15053`）、チュートリアルのセーブのロード（`TutorialManager.cs:40-52`）。EndTutorial は、表示中のポップアップを解放しない。Update は GameObject が active のときしか走らない。 |
| C-F5-other-blocking-18 | high | no | 反証 | 反証 | 反証 | **訂正（両レンズとも反証）。** 入力は要る。GoCoda の `ev.WaitOne()`（`EndGame.cs:495`）を解放するのは FadeText.After だけである。FadeText は段階 2 で TutorialManager.ShowIntermissionPopupAsync を出し、その Accept があって初めて段階 4 に進む（`FadeText.cs:68-88`）。段階 2 と 3 では Elapsed が進まないので、タイムアウトはない。Accept しなければ、ゲームスレッドは永久に止まる。 |
| C-F5-other-blocking-19 | medium | yes | 実機 | 実機 | 実機 | クレジットの早送り。LateUpdate が runtime を戻すので、running が真になってから書く（両レンズとも runtime_only）。 |
| C-F5-other-blocking-20 | high | no | 確認 | 部分 | 条件付き | MainMenu は、Redeem Code（AskStringAsync）、ModManagerUI、ModToolkit、AchievementView を UI 側で扱う（`MainMenu.cs:293-345`）。Q と "Quit" は終了する（`XRLCore.cs:3771, 3879-3880`）。 |
| C-F5-other-blocking-21 | high | no | 確認 | 確認 | 確立 |  |
| C-F5-other-blocking-22 | high | no | 確認 | 確認 | 確立 |  |
| C-F5-other-blocking-23 | medium | yes | 実機 | 実機 | 実機 | EmbarkBuilder の連鎖（両レンズとも runtime_only）。SelectPregen は、知らない名前を渡すと KeyNotFound を投げる。R5-F5f。 |
| C-F5-other-blocking-24 | high | no | 確認 | 確認 | 確立 |  |

### 7.6 F6-threads-hooks

| 主張 ID | 著者の確度 | 著者 RO | T | P | 状態 | 条件・訂正・確認点 |
|---|---|---|---|---|---|---|
| C-F6-threads-hooks-01 | high | no | 確認 | 確認 | 確立 |  |
| C-F6-threads-hooks-02 | high | no | 確認 | 確認 | 確立 |  |
| C-F6-threads-hooks-03 | high | no | 確認 | 確認 | 確立 |  |
| C-F6-threads-hooks-04 | high | no | 部分 | 確認 | 条件付き | executeAsync(...).Wait(timeout) がタイムアウトしても、処理は後で走る。処理は、実行される時点でトークンを検証する。 |
| C-F6-threads-hooks-05 | high | no | 確認 | 確認 | 確立 |  |
| C-F6-threads-hooks-06 | high | no | 確認 | 確認 | 確立 |  |
| C-F6-threads-hooks-07 | high | no | 確認 | 確認 | 確立 |  |
| C-F6-threads-hooks-08 | high | no | 確認 | 確認 | 確立 |  |
| C-F6-threads-hooks-09 | high | no | 確認 | 確認 | 確立 |  |
| C-F6-threads-hooks-10 | high | no | 確認 | 確認 | 確立 |  |
| C-F6-threads-hooks-11 | high | no | 確認 | 確認 | 確立 |  |
| C-F6-threads-hooks-12 | medium | yes | 実機 | 部分 | 実機 | 順序は確かめられた。リセットのブロックは TextConsole.BufferUpdated でもゲートされ、非フォーカス中は走らない。その場合 bViewUpdated が下りず、前提は永久に偽になる。十分かどうかは実機（T は runtime_only、P は partial、著者も runtime とした）。 |
| C-F6-threads-hooks-13 | high | no | 確認 | 部分 | 条件付き | ResetInput は LeaveMovementEvents=true で呼ばれるので、移動系のイベント（`Meta:Navigate*`、`CmdMove*`、`CmdAutoMove*`）は消えずにモーダルに届く。 |
| C-F6-threads-hooks-14 | high | no | 部分 | 部分 | 条件付き | End から積んだコマンドが読まれるのは、エネルギーを使わなかった反復（`Energy >= 1000`）だけである。使った反復の場合、次の PlayerTurn の `:734` で捨てられる。TutorialManager.AllowCommand も通る必要がある。 |
| C-F6-threads-hooks-15 | high | no | 確認 | 確認 | 確立 |  |
| C-F6-threads-hooks-16 | medium | no | 確認 | 確認 | 確立 |  |
| C-F6-threads-hooks-17 | high | no | 確認 | 確認 | 確立 |  |
| C-F6-threads-hooks-18 | high | no | 確認 | 確認 | 確立 |  |
| C-F6-threads-hooks-19 | high | no | 確認 | 部分 | 条件付き | AutoAct 中は、`ActionManager.cs:808` が Begin を呼ぶが、End は呼ばない。自動探索や移動の間は、End による「ゲームスレッドのティック」がない。 |
| C-F6-threads-hooks-20 | high | no | 確認 | 確認 | 確立 |  |
| C-F6-threads-hooks-21 | high | no | 確認 | 確認 | 確立 |  |
| C-F6-threads-hooks-22 | high | no | 確認 | 確認 | 確立 |  |
| C-F6-threads-hooks-23 | high | no | 部分 | 確認 | 条件付き | Harmony の条件は確かめられた。「メモリ上でコンパイルする」は設定しだいで、OptionOutputModAssembly の既定 Yes ではディスクに書かれる。本体は `ModManager.cs:70` で new Harmony を作る。 |
| C-F6-threads-hooks-24 | medium | yes | 実機 | 実機 | 実機 | 動的アセンブリの MonoBehaviour に Update が届くか（両レンズとも runtime_only）。createWindow は先に SetActive(false) を呼ぶ。 |
| C-F6-threads-hooks-25 | high | no | 確認 | 確認 | 確立 |  |
| C-F6-threads-hooks-26 | medium | no | 確認 | 確認 | 確立 |  |
| C-F6-threads-hooks-27 | high | no | 確認 | 確認 | 確立 |  |
| C-F6-threads-hooks-28 | high | no | 確認 | 確認 | 確立 |  |

### 7.7 F7-observation

| 主張 ID | 著者の確度 | 著者 RO | T | P | 状態 | 条件・訂正・確認点 |
|---|---|---|---|---|---|---|
| C-F7-observation-01 | high | no | 部分 | 確認 | 条件付き | 単体の窓では、contextText と inputBox の text は非アクティブにされるだけで、消されない。activeSelf を確かめてから読む。 |
| C-F7-observation-02 | high | no | 確認 | 確認 | 確立 |  |
| C-F7-observation-03 | high | no | 部分 | 確認 | 条件付き | `XRLCore.cs:3938` は SaveManagement の中で、PlayerTurn ではない。UI スレッドからの読み取りは、RenderMapBehind の 33ms 描画、PickTarget の生きたループ、APIDispatch のプールスレッドと競合する。 |
| C-F7-observation-04 | high | no | 確認 | 確認 | 確立 |  |
| C-F7-observation-05 | medium | no | 部分 | 確認 | 条件付き | 一瞬の判定としては正しいが、トークンの代わりにはならない。単体の窓は次の同期ポップアップで再表示されるので、検出と応答が別のタスクなら、コールバックの参照によるトークンが要る。 |
| C-F7-observation-06 | high | no | 確認 | 確認 | 確立 |  |
| C-F7-observation-07 | high | no | 確認 | 確認 | 確立 |  |
| C-F7-observation-08 | high | no | 確認 | 確認 | 確立 |  |
| C-F7-observation-09 | high | no | 確認 | 確認 | 確立 |  |
| C-F7-observation-10 | high | no | 部分 | 確認 | 条件付き | チュートリアルの ShowingPopup の間は、Push* が捨てられる。ビューが変わると UpdateView が ClearInput を呼ぶので、観測の直後に積んだ入力は消える。 |
| C-F7-observation-11 | medium | yes | 実機 | 実機 | 実機 | PointerOver を 2 回積む方式（両レンズとも runtime_only）。座標は EnforceRange と Constrain で動かされうる。R5-F3b。 |
| C-F7-observation-12 | medium | yes | 確認 | 確認 | 実機 | 著者が runtime_only とした（AfterRender の頻度）。R5-F7a。 |
| C-F7-observation-13 | high | no | 確認 | 確認 | 確立 |  |
| C-F7-observation-14 | high | no | 確認 | 確認 | 確立 |  |
| C-F7-observation-15 | high | no | 確認 | 確認 | 確立 |  |
| C-F7-observation-16 | high | no | 確認 | 確認 | 確立 |  |
| C-F7-observation-17 | high | no | 確認 | 確認 | 確立 |  |
| C-F7-observation-18 | high | no | 部分 | 部分 | 条件付き | アビリティのボタンの文字列は、UI スレッドの `AbilityBar.Update` で組み立てられる（`AbilityBar.cs:444, 558-575`）。効果の見出しには TMP の color タグが入る。 |
| C-F7-observation-19 | high | no | 確認 | 確認 | 確立 |  |
| C-F7-observation-20 | high | no | 確認 | 確認 | 確立 |  |
| C-F7-observation-21 | high | no | 部分 | 部分 | 部分反証 | **部分反証。** 「onHide でしか発火しない」は反証された。Looker（`Look.cs:534, 637, 910`）、Description（`Description.cs:374-375`）、BaseLineWithTooltip（`:170-176`）でも発火する。GenerateTooltipContent は発火させない、という結論は成り立つ。 |
| C-F7-observation-22 | medium | no | 部分 | 部分 | 条件付き | 27 か所の `onHighlight.RemoveAllListeners()` が、mod のリスナーを消す。セットアップのたびに付け直す。 |
| C-F7-observation-23 | high | no | 確認 | 確認 | 確立 |  |
| C-F7-observation-24 | high | no | 確認 | 確認 | 確立 |  |
| C-F7-observation-25 | high | no | 確認 | 確認 | 確立 |  |
| C-F7-observation-26 | low | yes | 実機 | 実機 | 実機 | 照準 imposter の走査（両レンズとも runtime_only）。Line では `list2.Last()` に付く。R5-F3c。 |

集計: 条件付き 43、確立 110、実機 15、反証 2、部分反証 4（計 174）。

### 7.8 レシピへの指摘（blocker と主な major）

懐疑レンズは、主張の判定とは別に、レシピそのものへの指摘を返した。§2 の表は、次の指摘を反映した後の形である。

**blocker（2 件）**

1. **終局のコーダ**（F5。T と P の両方が指摘）。
   - 家族文書のレシピは「応答は不要」としていたが、これは誤りである。
   - 幕間のチュートリアルポップアップを Accept しないと、ゲームスレッドが永久に止まる。
2. **PickField**（F7。P が指摘）。
   - PickCells と同じレシピでは、取消のつもりのキー（`Keypad5`、`CmdTargetSelf`）が、開始か確定として扱われる。
   - PickField は別のレシピにした。

**主な major**

| 対象 | 誤り | 修正 |
|---|---|---|
| ShowYesNo の取消 | `Cancel` の項目が存在しない | `No` の項目で取り消す |
| Hide やキャンセル | 呼び出し元は既定値（Yes、0 番の選択肢）で戻り、購入などが成立する | Hide を先に呼ばない。答えた後の成功確認を必須にする |
| PickOption の検出 | 単体の窓しか見ていない | 複製の窓も見る |
| AskNumber | ゲームパッドのときだけの経路と考えていた。初期値の Mouse でも AskNumberScreen に入り、TradeScreen はビューを積まない | 二つの表面の両方を扱う |
| getvk のピッカー | 前提に `!bViewUpdated` がない。フォーカスへの依存を書いていない。消費を確かめていない | 前提 P' を同じタスクで評価し、消費を確かめる |
| Look | UI スレッドから GenerateTooltipInformation を呼んでいた。読むまでの同期点がない | `lookerTooltip` を読み、`lookingAt` の一致を待つ |
| 単体画面の再利用 | StatusScreens と AbilityManager で、前のセッション向けの応答が次のセッションに当たる | tcs のトークンを使う |
| Options と Keybinds | 入れ子の窓と、ビューを積まない経路を考えていない | `globalContext.IsActive()` で判定する |
| 取引、本、端末 | 処理の途中（実行中）に応答や取消をしうる | 実行中フラグを持ち、`navigationContext.IsActive()` を見る |
| チュートリアルのオーバーレイ | 検出が Tutorial モードに限られていた | 全状態で最優先に検出する |
| UI ティック | hotload の後に二重に走る | 世代番号を持たせる |
| EndPlayerTurn からの push | エネルギーを使った反復では捨てられる | AskWish を直接呼び、`KeyEvent.Set()` で起こす |
| フォーカス | runInBackground が偽だと止まる | mod 側で真に書き直す |

**懐疑レンズが追加したモーダル。** 表 §2 の「【懐疑レンズが追加】」の行である。

## 8. 方向 2 の判断に対する含意と、Legacy UI にフォールバックすべき条件

### 8.1 含意

1. **方向 2 を続ける根拠は十分にある。**
   - 静的には、Modern UI のモーダルはすべて Harmony なしで検出、読取、応答できる見込みである。ただし、§2.5 の WorldGenerationScreen / OpeningStory の行は除く。この行で確かめたのは、OpeningStory が F1 の `Popup.Show` であること（`XRL.World.Parts/OpeningStory.cs:56-57`）までで、流れの全体は low のままである。
   - 残る不確実性は、Unity と Mono の実行時の挙動に集中している。
     - Update がフォーカスなしで回るか。
     - async void の再送出がどう扱われるか。
     - PointerOver の注入が効くか。
   - これらは、R5-0 と R5-F3 の少数のプローブで判定できる。
2. **設計の中心は「応答」ではなく「安全な応答」になる。** 懐疑レンズの指摘の多くは、次のものだった。
   - 前のモーダルへの応答が、次のモーダルに当たること。
   - 黙ってキャンセルされ、既定値で進むこと（ShowYesNo の Yes、ShowConversation の 0）。
   - 入力が黙って消えること。

   したがって、ブリッジは次のものを最初から持つ必要がある。
   - UI ティック（世代番号付き）。
   - 種類ごとのトークン。
   - 同じタスクでの検証と実行。
   - 応答後の成功確認。
   - 実行中フラグ。
   - 最優先のチュートリアル検出。
3. **エージェントは「画面を開かない」運用を基本にする。**
   - ステータス類、アビリティ、射撃、投擲、Look は、ゲームスレッドから直接 API を呼べる。
   - 画面を開くのは、ゲームが強制するモーダルのときだけにする。
     - 会話。
     - 取引。
     - 確認のポップアップ。
     - 死亡メニュー。
     - 能力が開くピッカー。
     - 主メニュー、セーブ選択、キャラクター作成。
   - こうすると、実機の検証面積が小さくなる。
4. **Legacy UI にしても、UGUI の面はなくならない。** 画面ごとに確かさが違う。

   | 画面 | Legacy UI での扱い | 確かさ |
   |---|---|---|
   | 主メニュー、キャラクター作成（EmbarkBuilder） | UGUI のまま | 05 で確かめた既知の事実 |
   | チュートリアルのオーバーレイ、終局のコーダ | UGUI のままと見込まれる | `TutorialManager.cs`、`XRL.UI/FadeText.cs`、`XRL.World.Conversations.Parts/EndGame.cs` には `ModernUI` / `UseNewPopups` の分岐がない（本書で grep して 0 件）。推論の段階である |
   | Modern のセーブ選択（`Qud.UI.SaveManagement`） | Legacy では別の経路になる | `if (Options.ModernUI)` の中にある（`XRL.Core/XRLCore.cs:3780`） |
   | mod 構成の不一致の確認 | 未確認 | `RestoreModsLoadedAsync` は、分岐なしで `Popup.NewPopupMessageAsync` / `PickOptionAsync` を呼ぶ（`XRL.Core/XRLCore.cs:3423-3448`）。ただし、Legacy の経路からこの関数に達するかは確かめていない |

   - したがって、Legacy へのフォールバックは全体の置き換えにはならない。ゲームプレイ中のポップアップ、会話、ピッカーに限った部分的な逃げ道になる。
   - 少なくとも主メニューとキャラクター作成には、どちらの UI でも本書の UGUI のレシピが要る。
   - チュートリアルのオーバーレイ（コーダを含む）も同じだと見込まれる。ただし Legacy UI での実機確認はまだない。

### 8.2 Legacy UI（`Options.ModernUI=false`）にフォールバックすべき条件

次のどれかが R5 で確認されたら、方向 2 をその範囲で諦め、Legacy UI への切り替えを検討する。ゲームプレイ中のモーダルは、Legacy では getvk で待ち、`PushKey` で答えられる。

| # | R5 で確認された事実 | 検証するプローブ | 判断 |
|---|---|---|---|
| F-1 | `runInBackground` を mod が真に書き直しても、非フォーカスで Unity の Update が止まる。あるいは UI ティックが実用に足る頻度で回らない | R5-0b（`probe:focus:force` を `OptionMusicBackground` の Yes と No で。基準は `probe:focus`） | ウィンドウを常にフォーカスさせる運用が取れないなら、Legacy を検討する。Legacy も getvk の待ちでフォーカスの影響を受けるので、差があるかを先に測る |
| F-2 | async void の WaitNewPopupMessage がプールで例外を再送出したとき、Mono がプロセスを落とす | R5-0d（`probe:cancel`） | トークンと成功確認で「キャンセルを起こさない」設計にすれば避けられる。ただし、人の操作やエンジン自身の onHide（`ShowPopup` の健全性チェック、`Qud.UI/PopupMessage.cs:722-735`）でも起きるなら、Modern のポップアップは不安定とみなして Legacy を検討する |
| F-3 | UI ティックの中で Unity の API を読むことや、`OnActivateCommand` / `OnInputSubmit` を直接呼ぶことが、例外や表示の崩れを起こす。あるいは NavigationController の状態を壊す | R5-F1a、b、d、e と R5-F2a（`probe:yesno`、`probe:askstring`、`probe:pickoption`、`probe:stale`、`probe:asknumber:mouse`、`probe:asknumber:kb`、`probe:conv`、`probe:talk`、`probe:conv:<ID>`） | PopupMessage への直接応答が成り立たないので、Legacy を採る |
| F-4 | `PointerOver` の注入も、照準 imposter の走査も使えず、PickTarget の確定位置が保証できない | R5-F3b（`probe:picktarget`）、R5-F3c（`probe:imposter`。タイル表示で PASS） | まず射撃や投擲をピッカーなしの API に寄せる。能力が開くピッカーが残って問題になるなら、transpiler（Harmony、§5 H1）と Legacy のどちらかを選ぶ |
| F-5 | getvk ピッカーへの入力が、P' を守っても消える（ほかの消去の経路がある） | R5-F3a、b、d（`probe:pickdir`、`probe:picktarget`、`probe:field`） | 同じ getvk なので、Legacy でも同じ問題が起きうる。フォールバックの理由にはならず、入力を積む時機の設計を見直す |
| F-6 | 実時間の制約（1 フレーム 250ms の遅延、LLM の待ち時間）のもとで、トークンの検証が実用上成り立たない | R5 全体（`DETECT` の `readMs` と `uiread maxMs` を含む） | 設計の見直しを先に行う。Legacy でも会話とポップアップの応答は必要なので、それだけではフォールバックの理由にならない |

**優先順位。**

- 第一の分岐点は F-2 と F-3 である。
- この二つが Modern で成り立てば、会話とポップアップという最大の面は、方向 2 で確定する。

## 9. 本書で表示し直して確かめた引用

家族文書と判定の引用のうち、次の範囲を `sed -n` で表示し、内容が一致することを確かめた。

| 引用 | 確かめた内容 |
|---|---|
| `XRL.UI/Popup.cs:801` | `public static async void WaitNewPopupMessage(...)` |
| `XRL.UI/Popup.cs:802-806` | `ControlManager.ResetInput()` の後、`Thread.CurrentThread == GameManager.Instance.uiQueue.threadContext` で分岐する |
| `XRL.UI/Popup.cs:896-914` | RenderMapBehind のときは `Wait(33)` と `RenderBaseToBuffer` のループ、そうでなければ `complete.Task.Wait()`。その後 `PopGameView(bHard: true)`、`callback?.Invoke(complete.Task.Result)` |
| `XRL.UI/Popup.cs:2251-2276` | ShowYesNo は `result = defaultResult` で始まり、`Cancel` を `No` に写す |
| `XRL.UI/Popup.cs:1320-1331` | `activeControllerType != Keyboard` のとき AskNumberScreen に入る |
| `ControlManager.cs:337` | `public static InputDeviceType _activeControllerType;`（初期化子なし） |
| `Qud.UI/PopupMessage.cs:926-944` | OnActivateCommand と OnSelect はゲート、コールバックの呼び出し、null 化、Hide の順に進む |
| `TutorialManager.cs:85` | `private bool ShowingPopup;` |
| `TutorialManager.cs:133` | `public bool popupAcceptPressed;` |
| `TutorialManager.cs:764-767` | `OnPopupAcceptPressed()` は `popupAcceptPressed = true` を代入するだけ |
| `XRL.World.Conversations.Parts/EndGame.cs:488-495` | TransitionText のコールバックで `ev.Set()`。その後に期限なしの `ev.WaitOne()` |
| `XRL.UI/FadeText.cs:68-76` | 段階 2 で `TutorialManager.ShowIntermissionPopupAsync("<nohighlight>", () => Stage = 4, ...)` を呼び、`Stage = 3` にする |
| `GameManager.cs:2963` | `uiQueue.executeTasks();` |
| `GameManager.cs:3108-3113` | `!XRLCore.bThreadFocus` なら `Thread.Sleep(250); return;` |
| `GameManager.cs:3172-3183` | `TextConsole.BufferUpdated` の中で、`_ActiveGameView != CurrentGameView \|\| bViewUpdated` なら ResetInput と UpdateView |
| `XRL.UI/PickTarget.cs:400-405` | カーソルはローカル変数の `x = StartX; y = StartY`。`flag3 = true`、`flag4 = true` |
| `XRL.UI/PickTarget.cs:809-812` | NumPad5、Escape、`Command:CmdTargetSelf` で `flag2 = true`（取消） |
| `XRL.UI/PickTarget.cs:322-330` | PickField では、NumPad5、F、Space、Enter、LeftClick、CmdFire、CmdTargetSelf がどれも開始か確定になる |
| `XRL.Core/XRLCore.cs:733-741` | `ClearMouseEvents(LeaveMovementEvents: true)` の後に PlayerTurn のループに入る。フォーカス待ちの `Sleep(200)`。`CurrentGameView = Options.StageViewID` |
| `XRL.Core/XRLCore.cs:2355-2359` | OnEndPlayerTurnCallbacks のループ |
| `XRL.Core/ActionManager.cs:805-809` | AutoAct 中に `CallBeginPlayerTurnCallbacks()` と `RenderBase` を呼ぶ |
| `QupKit/ThreadTaskQueue.cs:23-26` | `poolEntry` はロックなしで `taskPool.Enqueue(e)` を呼ぶ |
| `XRL/ModInfo.cs:845-861` | `HarmonyAttribute` を持つ型があるときだけ `PatchAll` を呼ぶ |
| `XRL/ModManager.cs:119` | `GenerateInMemory = !Options.OutputModAssembly` |
| `XRL.UI/Options.cs:1445-1453` | MusicBackground に従って `Application.runInBackground` を設定する |
| `ConsoleLib.Console/Keyboard.cs:110` | `public static ManualResetEvent KeyEvent` |
| `XRL.World.Capabilities/Wishing.cs:1006-1013` | wish `reload` は `uiQueue.awaitTask` の中で `HotloadConfiguration()` を呼ぶ |
| `XRL.World.Conversations.Parts/EndGame.cs:276, 305, 316` | `[WishCommand("gocreditscoda")]`、`[WishCommand("gocredits")]`、`[WishCommand("goend")]` |
| `XRL.UI/Popup.cs:1566, 1571` | ShowConversation の二つの多重定義（`GameObject Context` と `IRenderable Icon`）。Options はどちらも `List<string>` |
| `XRL.Core/XRLCore.cs:3778-3796` | Continue は `if (Options.ModernUI)` の中で `ContinueMenu().Wait()` を呼ぶ |
| `XRL.Core/XRLCore.cs:3423-3448` | RestoreModsLoadedAsync は分岐なしで NewPopupMessageAsync と PickOptionAsync を呼ぶ |
| `XRL.World.Parts/MissileWeapon.cs:21-23` | `[Serializable]`、`[UIView("FireMissileWeapon", ...)]`、クラス宣言の順 |
| `Qud.UI/TradeScreen.cs:245-249` | HandleTradeSome は pushView なしで `Popup.AskNumberAsync` を呼ぶ |
| `XRL/CheckpointingSystem.cs:111-122` | 死亡メニューの選択肢の並びは `OptionDefaultDeathToViewFinalMessages` で入れ替わり、"View final messages" で `Messages.Show()` を呼ぶ |
| `Qud.UI/PopupMessage.cs:1083-1104` | `Hide()` は interactable を下ろし、`onHide` を退避して null にしてから呼ぶ |
| `Qud.UI/PopupMessage.cs:79-86` | `_SingleButton` の項目は `command = "Accept"`（表示は Continue） |
| `Qud.UI/UIManager.cs:323-338` | `copyWindow` は `"<name> #<n>"` の複製を作り、`instance.transform` の子にする |
| `QupKit/ThreadTaskQueue.cs:77-100` | `executeAsync` は TaskCompletionSource を作り、`queueTask`（`:97`）で積む |
| `XRL/The.cs:41` | `UiContext => GameManager.Instance.uiSynchronizationContext` |
| `XRL.CharacterBuilds/EmbarkBuilder.cs:190-206` | `checkStateAsync` がエラー（SingleButton、`:195`）と警告（YesNoButton、`:199`）の複製ポップアップを出す。`advance` は async void（`:206`） |
| `XRL.CharacterBuilds.Qud.UI/QudBuildLibraryModuleWindow.cs:122` | "Manage Build" を AcceptCancelButton と選択肢で `NewPopupMessageAsync` に出す |
| `XRL.CharacterBuilds.Qud/QudPregenModule.cs:95-98` | `SelectPregen` は `pregens[pregen]` を引く |
| `XRL.World.Parts/OpeningStory.cs:29-57` | 最初の `BeforeTakeActionEvent` で、`HideWorldGenerationScreen()`（`:56`）の後に `Popup.Show(text)`（`:57`） |
| `Qud.UI/WorldGenerationScreen.cs:82-86, 263-274` | 表示は `await The.UiContext` の後。`Exit()` と `Update()` は空 |
| `XRL/SifrahGame.cs:646-671` | `Play` は `PushGameView("Sifrah")` の後、`Keyboard.getvk` のループに入る |
| `XRL.UI.Framework/APIDispatch.cs:19, 56` | `RunAndWaitAsync` は処理を `Task.Run` で走らせる |
| `TutorialManager.cs:95, 199, 256, 769-789` | `PopupCompletion` は private static で、ポップアップごとに作り直される。Update は `ShowingPopup` の間だけ Accept かフラグを消費する |
| `XRL.UI/ConversationUI.cs:385-392, 436-443` | `HaveConversation` の finally が `Reset()` を呼び、`Reset()` が `LastChoice` を null にする |
| `XRL.UI/PickTarget.cs:84-87` | `ShowFieldPicker` は public static で、`PickField` モードにして `"PickTarget"` を積む |

**家族文書の引用の誤りの指摘（本書では、確かめた後の値を使った）。**

| 家族文書の引用 | 訂正 |
|---|---|
| C-F3-pickers-02 の `XRL.World.Parts/MissileWeapon.cs:22`（UIView 属性） | **訂正しない。** レンズ P は `:21` が正しいとしたが、本書で `grep -n` し直すと `:21` は `[Serializable]`、`:22` が `UIView("FireMissileWeapon", ...)`、`:23` がクラス宣言だった。家族文書の `:22` が正しく、懐疑レンズの指摘のほうが誤りである |
| F7 の `XRLCore.cs:3938` | SaveManagement の中で、PlayerTurn ではない |
| F6 の `PopupMessage.cs:22-28` | `20-28` |
| PickSeveral の入れ子の AskNumber | `Popup.cs:2126` |
