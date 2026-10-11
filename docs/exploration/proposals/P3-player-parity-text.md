# P3. プレイヤー等価・テキスト限定（Player Parity, Text Only）

> 探索フェーズのアーキテクチャ提案（Opus 5.5 worker）。2026-09-25。
> レンズは「人間と同じ画面を見て、人間と同じキーを押す」。LLM に渡す情報は、画面に出た文字と色だけにする。行動は、人間が押すキーと同じ入力経路で入れる。

## 0. 引用規約とスポットチェック

- `stable/` は `~/Dev/coq-decompiled_stable` を指す。現在の中身は **2.0.211.56** である（`stable/Properties/AssemblyInfo.cs:8` が `AssemblyVersion("2.0.211.56")`）。報告 01 の時点では 2.0.211.50 だったが、その後差し替えられている。したがって報告 03 の `NEW/` の行番号は、`stable/` の行番号として読める。
- `Base/` はインストール先の `StreamingAssets/Base` を指す。
- **[推論]** は推論、**[要実測]** は起動して確かめる必要がある主張を表す。

**筆者が今回 `stable/` で目視確認した引用**（課題の「5 件以上」を満たす。うち 12 件は報告 03/04 の引用の再確認）

1. `ConsoleLib.Console/TextConsole.cs:142-161`：`DrawBuffer` が `lock (BufferCS)` の中で `if (!bSkipIfOverlay || !GameManager.Instance.ModernUI)` のときだけ `CurrentBuffer.Copy(Buffer)` を実行する。`:154` で `CurrentBuffer.ViewTag = CurrentGameView` を代入する。`CurrentBuffer` と `BufferCS` は static である（`:29,:31`）。**報告 03 と一致。**
2. `Qud.UI/UIManager.cs:55`：`UseNewPopups => Options.ModernUI`。**一致。**
3. `XRL.UI/Popup.cs:1118-1189`：`ShowBlock` の legacy 経路は `PushGameView("Popup:MessageBox")` → `Keyboard.ClearInput` → `RenderBlock` → `DrawBuffer(..., bSkipIfOverlay:true)` → `Keyboard.getvk` の順に進む。**一致**（`ClearInput` が入口にあることは今回新たに確認した）。
4. `XRL.UI/ConversationUI.cs:418-429`：`UseNewPopups` なら `Render()`、そうでなければ `RenderClassic()`。`RenderClassic` の中は `getvk` で、`D1`〜`D9` と `A`〜`Z` を `Select(index)` に写す（`:264-318` 付近）。**一致。**
5. `XRL.UI/Screens.cs:88-151`：`ModernUI && ModernCharacterSheet` でなければ `ScreenList`（Skills/Status/Inventory/Equipment/Factions/Quest/Journal、`:22-29`）の legacy ループに入る。**一致。**
6. `XRL.Core/XRLCore.cs:734`（`ClearMouseEvents(LeaveMovementEvents:true)`）、`:737-740`（`!GameManager.focused` の間 `Thread.Sleep(200)`）。**一致。**
7. `XRL.Core/XRLCore.cs:1167-1169`（`CmdMoveE`）、`:2322-2334`（default 分岐の `CommandEvent.Send`）。**一致。**
8. `GameManager.cs:404-425`：`focused` のセッターは、false から true に変わるときに `Keyboard.ClearInput()` と `ClearMouseEvents()` を呼ぶ。`:1920-1924` の `OnApplicationFocus` は `bThreadFocus` と `focused` を両方書き換える。**一致**（入力が消える副作用は今回新たに確認した）。
9. `XRL.Core/ActionManager.cs:805-814`：AutoAct の実行中に `Keyboard.kbhit()` が真だと `AutoAct.Interrupt()` が呼ばれる。**一致。**
10. `XRL.Core/XRLCore.cs:652-655`（`RegisterAfterRenderCallback`）。**一致。**
11. `ConsoleLib.Console/ConsoleChar.cs:392-420`：`Set(RenderEvent)` は、tile があれば `_Char='\0'` として `BackupChar` に退避する。**一致。**
12. `ConsoleLib.Console/Keyboard.cs:723-726`（`PushCommand` は `PushMouseEvent("Command:"+cmd)`）、`:777-796`（`PushKey` と `bCapInputBuffer`）。**一致。**

**今回新たに確認した事実**（報告 01〜04 に記載がないもの）

- 以下はすべて legacy 分岐を持つ。
  - `TradeUI.cs:456-465`（`ConsoleTrade`）
  - `AbilityManager.cs:144`
  - `Look.cs:487-927`
  - `PickTarget.cs:117,747`、`PickDirection.cs:44`
  - `BookUI.cs:427,464`
  - `TinkeringScreen.cs:23`
  - メインメニューの Continue（`XRLCore.cs:3780-3805`。legacy では `SaveManagement().Wait()`）
- **キャラクター作成は legacy でも UGUI である。** `EmbarkBuilder.Begin` は `The.UiContext` 上に `EmbarkBuilder` コンポーネントを作る（`XRL.CharacterBuilds/EmbarkBuilder.cs:61-87`）。legacy 分岐は `exitWithInfo` の中の `WorldGenerationScreen` の要否だけである（`:269`）。
- legacy でも Modern のポップアップを出してしまう呼び出し元がある（§4.3 で扱う）。
  - `Popup.ShowYesNoAsync`（`Popup.cs:2326-2339`）は無条件で Modern になる。
  - `PickOptionAsync` は `ForceNewPopup:true` を付ける（`Popup.cs:1624-1640`）。
- legacy でサイドバーを `Hidden` にすると、HUD は画面右上の 3 行（`[/]`、HP、ターゲットの負傷度）だけになる（`XRL.UI/Sidebar.cs:848-884`）。切り替えは `CmdShowSidebar`（`XRLCore.cs:2251-2253`）。
- `Zone.Render` はセル `(x,y)` を `Buf.Buffer[x,y]` に書く（`XRL.World/Zone.cs:5730-5735`）。**legacy のマップでは、画面の座標がそのままセルの座標になる。**
- ゲームのクリア判定は、ゲーム状態 `EndType` が `Brightsheol`/`Marooned`/`Return`/`Covenant`/`Accede`/`Launch` のいずれかになることである（`XRL.World.Conversations.Parts/EndGame.cs:67-79`）。終了の確認は `Popup.AskString` による**文字列の入力**である（`:162`）。

---

## 1. 概要と狙い

### 1.1 一文で

**CoQ を `OptionModernUI=No` と `OptionUseTiles=No` の「クラシック ASCII」構成で動かす。** LLM には、人間の目に映る 80×25 の文字と色（`TextConsole.CurrentBuffer`）だけを渡す。LLM の出力は、人間が押すのと同じキーとして `Keyboard.PushKey` に積む。**Harmony を使わず、Rosetta も要らない。ゲームスレッドを一度も止めない。**

### 1.2 何を最適化するか

1. **「特権的な状態を使っていない」と主張できる強さ。** LLM に渡る情報はすべて画面のフレームから導けるものにする。第三者が、ログだけで機械的に検証できるようにする（§8.3）。
2. **NLE/BALROG と比べられる形。** `step(key) -> screen` という gym 形式の環境にする。観測のレベル（L0/L1/L2、§2.2）を公開し、ablation を回せるようにする。
3. **モーダルを専用の仕組みなしで扱える一様さ。** legacy UI では、ポップアップ、会話、インベントリ、取引、レベルアップ、方向・対象の選択がすべて「`CurrentBuffer` に描かれ、`Keyboard.getvk` でキーを待つ」という同じ形になる（§4）。モーダルごとの API は要らない。
4. **エンジン結合の小ささ。** 依存するシンボルは 15 個程度に収まる（§10.2）。v1 の CTA フック、エネルギードレイン、`IGameSystem` の直列化はどれも使わない。

### 1.3 意図的に捨てるもの

| 捨てるもの | 代償 |
|---|---|
| Modern UI とタイルの見た目 | 配信は 2015 年頃のクラシック ASCII の見た目になる。§9 のオーバーレイで補う |
| 構造化された状態（HP の数値、エンティティ一覧、敵対フラグ） | `g` が何者かは、人間と同じく Look（`l`）で調べるしかない。1 手あたりの LLM 呼び出しが増え、判断の質は下がる |
| CTA 内での直接行動（v1 の資産） | 行動は必ず「キー → 画面が落ち着くのを待つ」の往復になる。v1 の `Move` 直呼びより遅い |
| キャラクター作成の完全自律 | 作成画面は UGUI なので、初期版ではオペレーターが入力する（§4.4）。公開する主張では例外として明記する |
| 日本語プロファイル（QudJP） | 隔離したプロファイルを英語で使う（§10.4） |

**判断**：このレンズは「クリアできる確率」より「クリアしたときの主張の強さ」を取る。P1/P2 系の直接 API 案と比べると到達は遅い。代わりに、到達したときに「人間と同じ入出力で」と言える。

---

## 2. 観測

### 2.1 使う表面

| # | 表面 | 読むスレッド | 用途 | 引用 |
|---|---|---|---|---|
| O1 | `TextConsole.CurrentBuffer`（80×25。各セルの `Char` と `Foreground`/`Background`） | ブリッジスレッド。`lock(TextConsole.BufferCS)` だけを取る | **LLM に渡す唯一の画面** | `TextConsole.cs:29-31,149-157` |
| O2 | `CurrentBuffer.ViewTag`（描画した時点の `CurrentGameView`） | O1 と同時 | 画面の種類の表示、Modern リークの検出 | `TextConsole.cs:154`、`GameManager.cs:469-480` |
| O3 | `XRLCore.RegisterNewMessageLogEntryCallback` | 追加したスレッド（主にゲームスレッド）。`ConcurrentQueue` に積むだけ | メッセージフィード（L1。§2.2 で開示する） | `XRLCore.cs:657-680`、`MessageQueue.cs:148` |
| O4 | 同期用に読む値：`Keyboard.KeyQueue.Count`、`Keyboard.HasMouseEvent()`、`XRLCore.CoreThread.ThreadState`、`AutoAct.IsActive()`、`GameManager.focused` | ブリッジスレッド | **落ち着き判定にだけ使う。LLM には渡さない** | `Keyboard.cs:108,865`、`XRLCore.cs:300`、`AutoAct.cs:105-412`、`GameManager.cs:404` |
| A1 | 監査タップ：`RegisterOnBeginPlayerTurnCallback` の中で `XRLGame.Turns`、ゾーン ID、HP、`Quests`/`FinishedQuests`、`EndType` を読む | ゲームスレッド | **監査ログにだけ書く。LLM には渡さない**（§8） | `XRLCore.cs:604`、`XRLGame.cs:50,145-148`、`EndGame.cs:67-79` |

**使わないもの**：`AfterRenderCallback` の `_Buffer` は使わない。サイドバーより前の段階のバッファで、混乱（confusion）時の表示シャッフルも反映されていない（`XRLCore.cs:2506-2531`）。人間が見ていない情報が漏れるので、観測からは外す。Zone/Cell/GameObject の API も使わない。

**なぜ `OptionUseTiles=No` が必須か**：tile モードでは `_Char='\0'` になり、グリフは `BackupChar` に退避される（`ConsoleChar.cs:402-405`）。ところが `ConsoleChar.Copy` は `BackupChar` をコピーしないので、`CurrentBuffer` ではグリフが消える（`ConsoleChar.cs:360-375`、v1 の K5/K6）。text モードなら `_Char` にグリフが残る（`:414-417`）。

**なぜ `OptionModernUI=No` が必須か**：Modern UI では、HUD、ログ、ポップアップが UGUI に描かれ、`CurrentBuffer` には入らない（`Sidebar.cs:793-833`、`TextConsole.cs:151` の `bSkipIfOverlay`）。legacy なら、サイドバー（`Sidebar.cs:848-` の legacy 分岐）もポップアップ本文も、`DrawBuffer` を経由して `CurrentBuffer` に入る。

### 2.2 観測レベル（公開仕様）

| レベル | 内容 | 位置づけ |
|---|---|---|
| **L0 `tty`** | 80×25 の文字グリッドと前景色の文字グリッド（CoQ の色コード `y`,`W`,`R` など。`ColorUtility.ColorToCharMap` で逆引き、`ColorUtility.cs:165`） | NLE の `tty_chars`/`tty_colors` に相当する。純粋な観測 |
| **L1 `tty+annot`**（**クリアを主張する既定レベル**） | L0 に次を足す。<br>(a) 行と列のルーラー<br>(b) `@` を基準にした「目立つグリフ」の一覧（位置、相対方向、色）。L0 だけから機械的に導く<br>(c) 画面の種類（ViewTag を人間が読める形にしたもの）<br>(d) **メッセージフィード**（O3） | (a)(b)(c) は L0 の決定的な関数なので、情報は増えない。(d) は `CmdMessageHistory` を開けば人間が読めるのと同じ文字列である。等価性は §8.3 の監査で確かめる |
| **L2 `tty+macros`** | L1 に、キーだけで実装したマクロ（`look_at`、`use_ability`、`travel_poi` など。§3.3）を足す | 情報の集合は L1 と同じ。LLM の呼び出し回数を減らすためのもの |

**サイドバーの方針**：`Sidebar.Hidden` 相当の最小 HUD で運用する。

- 既定値は `_Hidden=false`、つまりサイドバーは全表示である（`Sidebar.cs:24,285-298`）。`CmdShowSidebar` は反転するトグルである。そこでハーネスは、画面の右端の列を読み、全表示なら 1 回押す。人間が見て判断するのと同じ手順である。
- getter は、`OptionShiftHidesSidebar` が有効で Shift が押されている間だけ表示を反転する（`Sidebar.cs:289-292`）。Shift 付きのキーを送った瞬間のフレームは、サイドバーの状態が変わりうる。
- この既定状態は R1 の合格条件に含める。

- マップを遮るのは、右上の最大 3 行 × 12 列程度だけになる（`Sidebar.cs:848-884`）。
- 能力値や重量は、`peek_sidebar` マクロ（`CmdShowSidebar` を押して画面を取り、もう一度押す。ゲーム内の時間は進まない）か、ステータス画面で読む。
- 表示中のサイドバーの 12 行のメッセージは、忙しいターンにはあふれる。そこでメッセージは L1 のフィードに一本化する。

### 2.3 1 ターン分の観測例（L1）

**これは説明用の例で、実際に取得したものではない**（Joppa 付近の典型的な配置を手で作った）。サイドバーを表示した状態で示す。既定の Hidden では、右側 25 列もマップになる。

```text
[frame 1842 | view=Stage | settled 140ms | last_keys=["CmdAttackE"]]
    0         1         2         3         4         5         6         7
    01234567890123456789012345678901234567890123456789012345678901234567890123456789
00| .......................................................|Mehmet the Mutant
01| .......................................................|HP: 14 / 18
02| ..................................................>....|ST17 AG19 TO16
03| .~.,"..".~##########~,.......",,,".,..."..,.,~,,~,.,...|IN12 WI14 EG11
04| ,~......""#........#..,,~.~......~..,....,,,.,,"~,~.~.,|AV 3  DV 7  QN100
05| ..,.~.~,.,#.&......#"...,.".,.,.,,..,....~...,.,..,,.".|Joppa, 10th of Ut
06| .,."....~.#....%...#.",,.,,.,..."~,~.."~.~,.......~.,..|Hungry   Quenched
07| "..~...~~,#........#..~......",....~~,.",......."..~~",|-----------------
08| .,.,,,.,..####+#####,"~,.,.,",,,"...~..,.,..,,~..".~,.,|You hit the snapjaw
09| ~.."..,.~..,..,..."....~~..~.~.~,.....",.,,,~,.,~.,.,~"|scavenger for 3
10| .,...""~".....~,.~.,.....",g.,.,".,"."~.".,."..........|damage.
11| ....,.,.......,",..,,,,".g",.~,...,."~..~,,"...,~~."~,.|The snapjaw
12| ....,"..~.,,~.."".....@~,,...,..."~..~,,,"~.,"........,|scavenger hits you
13| ,..,.~~....,..",,,~."~.".....".~"..~..~"...."...,.~."~.|for 2 damage.
14| ,,,,....,...,.",..,...,"".~,."T."","."..,,"~,,....,."~.|The snapjaw hunter
15| ....,~.....""...,",,...,.,"....,"..,.,....".".~..,,,..,|yells, "Rrrraw!"
... (16-24 行は省略)
```

```json
{
  "frame": 1842,
  "view": "Stage",
  "player": {"x": 22, "y": 12},
  "salient": [
    {"ch": "g", "fg": "W", "x": 25, "y": 11, "rel": "E3 N1"},
    {"ch": "g", "fg": "w", "x": 27, "y": 10, "rel": "E5 N2"},
    {"ch": "T", "fg": "g", "x": 30, "y": 14, "rel": "E8 S2"},
    {"ch": "&", "fg": "c", "x": 12, "y": 5,  "rel": "W10 N7"},
    {"ch": ">", "fg": "y", "x": 50, "y": 2,  "rel": "E28 N10"}
  ],
  "color_rows": {"12": "=g except 22:Y 23:B"},
  "messages_new": [
    "You hit the snapjaw scavenger for 3 damage.",
    "The snapjaw scavenger hits you for 2 damage.",
    "The snapjaw hunter yells, \"Rrrraw!\""
  ],
  "result": {"screen_changed": true, "cells_changed": 41}
}
```

- `salient` は「床と地形に使う記号の集合に含まれない、または色が行の多数派と異なるセル」を L0 から抽出したものである。**それが何であるかの名前は付けない。** `g` の正体を知りたければ、LLM は `look_at` を使う。
- `color_rows` は前景色の行ごとの RLE である。「行の多数派の色 + 例外」の形にする。液体（`~` の色）や、同じグリフの別の生物を区別するために必要である。**色は人間が見ている情報なので、省略すると人間より情報が少なくなる。**

### 2.4 サイズ見積もり

以下はすべて **[推論]** の概算である。

| 部分 | 文字数 | トークン |
|---|---|---|
| 80×25 のグリッドと行番号（記号が多く、`.` の連なりは圧縮される） | 約 2.1k | 900〜1,500 |
| 色の RLE | 0.5〜2k | 250〜800 |
| `salient`（10〜30 件） | 0.4〜1.5k | 150〜500 |
| メッセージと付帯情報 | — | 50〜300 |
| **合計（1 フレーム）** | | **約 1.5k〜3k** |

- 履歴は、最新のフレームだけを全文で渡し、過去分は「キーと差分の要約とメッセージ」に縮める。
- システムプロンプト（操作の説明、キー表、ノート）は prompt caching の対象にする。

### 2.5 tile モードと Modern UI への依存

- **Modern UI には依存しない**（無効化が前提である）。
- **tile モードは明示的に使わない。** tile + legacy でも、`AfterRender` で `BackupChar` を補えばマップは読める（v1 の K7）。ただしポップアップとサイドバーは `CurrentBuffer` 側にしかない。2 つのバッファを合成すると、どの時点のバッファかの整合を取る仕事が増える。text モードに固定すれば `CurrentBuffer` 1 本で済む。

---

## 3. 操作

### 3.1 行動文法（LLM に見せるツール）

ツールは 2 系統に分ける（dcss-ai の FREE/TURN の分離に倣う）。すべてのツールは **1 回に 1 入力イベントだけを積み、画面が落ち着くのを待ってから次の観測を返す**（§5.3 の鉄則）。

| ツール | 引数 | 実装 | ゲーム内時間 |
|---|---|---|---|
| `press(cmd)` | `Commands.xml` の ID（例：`CmdMoveNE`、`CmdAttackE`、`CmdGet`、`CmdAutoExplore`、`CmdWait`、`CmdInventory`） | 現在のキーマップで ID をキーに解決し（`CommandBindingManager.GetKeyFromCommand`、`CommandBindingManager.cs:954`）、そのキーを `Keyboard.PushKey` で積む。**人間が押すキーと同じイベントになる。** 解決できない ID（Modern 専用の `CmdAbility1-10` など、報告 04 §1.9）は拒否する | ID による |
| `key(k)` | 1 キー（`a`-`z`、`A`-`Z`、`0`-`9`、`Enter`、`Esc`、`Space`、`Tab`、テンキー 1-9、`PageUp`/`PageDown`） | `PushKey(new XRLKeyEvent(KeyCode, char, shift, ctrl, alt))`（`Keyboard.cs:777`） | モーダルの中では 0 |
| `type(text)` | 文字列 | 1 文字ずつ `key` を送り、毎回落ち着きを待つ。最後に `Enter` を押すかどうかは引数で指定する | 0 |
| `wait_screen(ms)` | — | 何も押さず、次の落ち着いたフレームを待つ（AutoAct 中など） | — |
| `note_write/read` | — | ブレイン側のファイル操作。ゲームには触れない | 0 |

**使わない入力経路**：

- `PushCommand("Command:X")`（`Keyboard.cs:723-726`）は PlayerTurn では有効である（`XRLCore.cs:776-780`）。しかし人間のキー入力とは経路が異なるので、既定では使わない。例外は、legacy の会話で `Command:CmdStartTrade` を受ける箇所（`ConversationUI.cs` の `RenderClassic`）のように、ゲーム自身がマウスコマンド経由を想定している箇所だけで、使う場合は開示する。
- 報告 04 §1.5 の「隠しコマンド」（`CmdUseE` など 27 件）は、`Commands.xml` に存在せずキーが割り当てられていない。**人間には押せないので禁止する。**

### 3.2 行動の系統ごとの実行

| 系統 | 人間の操作 | このハーネスでの操作 | 開くモーダル |
|---|---|---|---|
| 移動 | テンキーまたは `CmdMove{Dir}` | `press("CmdMoveNE")`。`XRLCore.cs:1167-1169` と同じ switch に入る | なし |
| 攻撃 | 敵に向かって移動するか `CmdAttack{Dir}` | `press("CmdAttackE")`（`XRLCore.cs:1358`） | なし |
| 待機 | `CmdWait` / `CmdWait20` / `CmdWaitUntilHealed` | `press(...)`（`XRLCore.cs:1517`） | `CmdWaitN` は AskNumber（`:1559`）なので `type("15")` |
| 自動探索 | `CmdAutoExplore` | `press("CmdAutoExplore")`（`XRLCore.cs:1920`）→ `wait_screen` | なし。止まった理由はメッセージで分かる |
| 移動先の指定 | `CmdMoveToPointOfInterest`（候補リスト）、`CmdMoveTo`（カーソル） | L2 マクロ `travel_poi(label)`：押す → 落ち着く → PickOption の画面からラベルに対応するホットキーを探す → 押す（`XRLCore.cs:1347`） | PickOption（legacy） |
| 階段 | `<` / `>` | `press("CmdMoveU"/"CmdMoveD")` | `AskAutostair` の YesNo（Options で既定オン。確認に答える） |
| 相互作用 | `CmdUse` → 方向、`CmdGet`、`CmdOpen` → 方向、`CmdTalk` → 方向 | `press("CmdUse")` → `key(Keypad6)`。PickDirection の legacy ループ（`PickDirection.cs:28-123`） | PickDirection、その後にポップアップ |
| 能力 | `CmdAbilities` → 一覧から文字キー | L2 マクロ `use_ability(name)`：押す → 一覧の画面から名前の行を探す → その文字キーを押す → 対象の選択があれば PickTarget/PickDirection に進む（`XRLCore.cs:1806-1821`、`AbilityManager.cs:144` の legacy 分岐） | AbilityManager（legacy）→ Pick* |
| 射撃・投擲 | `CmdFire`/`CmdThrow` → カーソルを動かして Enter | `press("CmdFire")` → テンキーでカーソル移動 → `key(Enter)`。PickTarget の legacy（`PickTarget.cs:747`） | PickTarget |
| インベントリと装備 | `CmdInventory`/`CmdEquipment` → 文字キーで品を選ぶ → 行動メニュー | 同じ操作。legacy の `InventoryScreen`/`EquipmentScreen`（`Screens.cs:22-29,128-151`） | 画面、PickOption、YesNo |
| 会話 | `CmdTalk` → 方向 → 数字または文字キー | `key("1")` など。`RenderClassic` が `D1-D9`/`A-Z` を `Select(index)` に写す（`ConversationUI.cs:264-318` 付近） | 会話（legacy） |
| 取引 | 会話中に `CmdStartTrade` → `CmdTradeAdd`/`Remove`/`Offer` | `ConsoleTrade` のキー操作（`TradeUI.cs:465-`） | ConsoleTrade |
| レベルアップ | ポップアップと PickOption | 同じ操作（`Leveler.cs:289,325,341`） | legacy のポップアップ |
| 変異のバリアント選択 | PickOption | 同じ操作（`BaseMutation.cs:1017`） | legacy |
| セーブ | `CmdSave`（オプションで許可が必要） | ゲームモード次第（§8.4） | YesNo |
| キャラクター作成 | UGUI | **例外**（§4.4） | — |

### 3.3 L2 マクロの規約

- マクロの中身は `press`/`key` の列と画面の読み取りだけで作る。**ゲーム状態の API は呼ばない。**
- 各ステップで落ち着きを待ち、画面の文字列をパースしてから次のキーを決める（キーを先に積んでおくことはしない。§5.3）。
- マクロが実際に押したキーと、途中のフレームは、すべて `keys.jsonl`/`frames.jsonl` に記録する。LLM には最終フレームと要約だけを返す。
- 代表的なマクロ：
  - `look_at(dx,dy)`：`CmdLook` → カーソル移動 → 画面を取る → `Esc`。Look は時間を消費しない。
  - `peek_sidebar`
  - `read_messages_page`：`CmdMessageHistory`（`XRLCore.cs:2296`）
  - `use_ability(name)`
  - `travel_poi(label)`
  - `drop/eat/equip(item_label)`

### 3.4 結果とエラーのフィードバック

- **戻り値は返さない。返すのは「押したキー」「次の落ち着いたフレーム」「新しいメッセージ」「`screen_changed`/`cells_changed`」だけである**（報告 02 の P4「戻り値ではなく状態を返す」）。
- 無効なキー（画面が変わらず、メッセージもない）は、`result.no_visible_effect=true` として返す。BALROG のように既定の行動に置き換えることはしない。同じフレームで無効な入力が 3 回続いたら、ブレイン側で `Esc` を推奨するヒントを出す。ヒントは画面から導ける範囲に限る。
- `press` の ID が不正な場合はツールエラーを返し、キーは押さない。

---

## 4. モーダル UI

### 4.1 基本方針

legacy UI では、主要なモーダルはすべて同じ形をしている。

1. `GameManager.PushGameView("<名前>")` を呼ぶ。
2. `ScrapBuffer` に描画する。
3. `DrawBuffer(..., bSkipIfOverlay:true)` を呼ぶ。legacy なので `CurrentBuffer` にコピーされる。
4. `Keyboard.getvk` でキーを待つ。

したがって、次のように扱える。

- **検出**：`ViewTag` が `Stage` 以外になったら「モーダル中」とみなす。
- **読み取り**：モーダルの中身は O1 の画面そのものである。
- **応答**：`key`/`type` で答える。

**モーダル専用の API、Harmony、`uiQueue` はどれも要らない。**

### 4.2 モーダル系統ごとの表

| 系統 | legacy の入口 | ViewTag | 読む | 答える | Harmony | Rosetta |
|---|---|---|---|---|---|---|
| `Popup.Show` | `Popup.cs:676-710`（`ClearInput` → `getvk(pumpActions:true)`） | `Popup:MessageBox` | O1 | `Space`/`Enter`/`Esc` | 不要 | 不要 |
| `Popup.ShowBlock` | `Popup.cs:1138-1188` | `Popup:MessageBox` | O1（`PageUp`/`PageDown` で送る） | 同上 | 不要 | 不要 |
| `PickOption`/`ShowOptionList` | `Popup.cs:1709-1916` | `Popup:Choice` | O1（ホットキーの文字が画面に出る） | 文字キーか、カーソル移動 + `Enter` | 不要 | 不要 |
| `ShowYesNo`/`YesNoCancel` | `Popup.cs:2258-2290`、`:2371-2413` | `Popup:MessageBox` | O1 | `y`/`n`/`Esc` | 不要 | 不要 |
| `AskString`/`AskNumber` | `Popup.cs:1440-1450`（legacy の `Popup:AskString`）、`:1198-1213` | `Popup:AskString`/`Popup:AskNumber` | O1 | `type(text)` + `Enter` | 不要 | 不要 |
| `ShowConversation`（会話） | `ConversationUI.cs:418-429` → `RenderClassic` | 会話用の legacy ビュー **[要実測：タグ名]** | O1（本文と番号つきの選択肢） | `1`-`9`/`a`-`z`、`Esc` | 不要 | 不要 |
| ステータス画面（インベントリ、装備、スキル、クエスト、ジャーナル、派閥） | `Screens.cs:128-151`（`ModernUI && ModernCharacterSheet` のときだけ Modern） | `StatusScreens` | O1 | 画面ごとのキー（legacy の画面にはキーの案内が描かれている） | 不要 | 不要 |
| Tinkering | `TinkeringScreen.cs:23` の legacy 分岐 | `Tinkering` | O1 | キー | 不要 | 不要 |
| 取引 | `TradeUI.cs:456-465` → `ConsoleTrade` | `ConsoleTrade` | O1 | `CmdTradeAdd`/`Remove`/`Offer` のキー | 不要 | 不要 |
| PickDirection | `PickDirection.cs:28-123`（`:44` の Modern 分岐は描画だけ **[推論]**） | `PickTarget` | O1 | テンキー | 不要 | 不要 |
| PickTarget / Look | `PickTarget.cs:378,747`、`Look.cs:487-927` | `PickTarget`/`Looker` | O1（Look の本文も legacy では画面に描かれる） | テンキー、`Enter`/`f`、`Esc` | 不要 | 不要 |
| 本・端末 | `BookUI.cs:427,464` の legacy 分岐 | `Book` など | O1 | ページ送り、`Esc` | 不要 | 不要 |
| レベルアップと変異の選択 | `Leveler.cs:289-341`（Popup 系の組み合わせ） | 上と同じ | O1 | 上と同じ | 不要 | 不要 |
| メインメニューとロード | `XRLCore.cs:3727-3805`（legacy の Continue は `SaveManagement()`） | メインメニュー | O1 **[要実測：legacy のメインメニューが `CurrentBuffer` に描かれるか]** | 文字キー | 不要 | 不要 |
| **キャラクター作成** | `EmbarkBuilder.cs:61-87`（**常に UGUI**） | `EmbarkBuilder` | 読めない | §4.4 | — | — |
| エンディングの確認 | `EndGame.cs:162`（`Popup.AskString`） | `Popup:AskString` | O1 | 表示された語を `type` → `Enter` | 不要 | 不要 |

### 4.3 legacy でも Modern のポップアップが出る箇所（リーク）と対処

| 呼び出し元 | 経路 | ゲーム中に到達するか | 対処 |
|---|---|---|---|
| `Popup.ShowYesNoAsync`（`Popup.cs:2326-2339`、無条件で Modern） | 呼び出し元は `Qud.UI/*` だけ（MainMenu の終了、Keybinds、`MouseBlocker.cs:72`、HighScores、AbilityManagerScreen、`TradeScreen.cs:279` の `ConfirmUseImportantAsync`） | legacy では、`MouseBlocker` のクリック連打以外は到達しない **[推論]** | マウス入力を使わない。`OptionMouseInput=No` にする |
| `PickOptionAsync`（`ForceNewPopup:true`、`Popup.cs:1624-1640`） | `XRLCore.cs:3448`（ロード時の「Mod Configuration Differs」）、`CommandBindingManager.cs:1036`（キーセットの選択） | **ロード時に到達しうる** | 隔離プロファイルで mod の構成を固定し、構成が異なるセーブを使わない |
| `ModInfo` のポップアップ（`ModInfo.cs:516,581,608`、`ModScrollerOne.cs:55`） | 起動時の mod の依存関係やスクリプトの確認 | 起動時 | `OptionAllowCSMods=Yes` と `ModSettings.json` を事前に書いておく |
| 代名詞のカスタム設定 | `StatusScreen.cs:520` → `PronounAndGenderSets.ShowChangePronounSet`（`:90`）→ `CustomizeAsync`（`:223,573,589`）→ `Popup.AskStringAsync`（`Popup.cs:1371`、Modern） | **legacy のステータス画面から到達しうる**（カスタム代名詞を選んだ場合） | L2 の禁止操作リストに入れる。到達した場合はリークとして扱う（下記） |
| `Description.cs:361`（Look の「Recall Story」） | `Options.ModernUI` のときだけ | 到達しない | — |
| `EndGame.RunCredits`（`EndGame.cs:326-345`、UGUI のキャンバス） | エンディングの後 | `EndType` が確定した**後**なので、クリア判定には影響しない | 監査で `EndType` を確認した時点でクリアとする |

**リークの検出**：ブリッジスレッドが `GameManager.Instance.CurrentGameView` を監視する。Modern 系のビュー名（`PopupMessage`、`DynamicPopupMessage`、`ModernPopup:*`、`ModernTrade`、`StatusScreensScreen`、`EmbarkBuilder` など。報告 03 §2.8）になったら、次のように扱う。

- `interventions.jsonl` に記録する。
- 配信のオーバーレイに「HARNESS LEAK」と表示する。
- **オペレーターが手で閉じる。** この介入は主張の例外として数え、公開する。

`uiQueue` 経由の `PopupMessage.OnActivateCommand('option:N')`（報告 03 の U4）で自動化する選択肢もある。ただし未実証で、人間と同じ経路でもない。そのため初期版では使わない。

### 4.4 キャラクター作成（唯一の設計上の例外）

- `EmbarkBuilder` は UGUI の `NavigationController` の上で動き、`CurrentBuffer` には描かれない（`EmbarkBuilder.cs:61-87`）。
- **判断**：初期版（M1〜M3）では次の手順で作る。
  1. LLM が、ゲーム内の `Manual.xml` の範囲の知識で、テキストの「ビルド仕様」を書く。内容は genotype、subtype、属性の配分、変異とサイバネティクス、開始地点である。
  2. オペレーターが、その仕様をそのまま作成画面で入力する。配信中に行う。
  3. 仕様と、作成後の最初のフレームを証拠として保存する。
- 作成が済めば、`SavePath/lastcharacter.txt` にビルドコードが残る（`EmbarkBuilder.cs:254-262`）。**同じキャラクターでの再挑戦には、`Last` の chartype（報告 04 §5.3）を使えば、オペレーターの操作を 2〜3 クリックに減らせる。**
- 将来は `NavigationController.FireInputCommandEvent`（報告 03 の制御経路 8）でキーボード相当の操作を注入し、画面の情報は EmbarkBuilder の各モジュールのデータをテキスト化する案がある。ただし後者は「画面そのもの」ではなくなるので、L1 の主張に含めてよいかは別途判断する。

---

## 5. スレッドと同期

### 5.1 スレッド構成

```text
[Unity UI スレッド]   GameManager.Update: lock(GameViewStack) → lock(BufferCS) → CurrentBuffer を描画   (GameManager.cs:3172-3212)
[ゲームスレッド]      ActionManager.RunSegment → PlayerTurn → Keyboard.GetNextKey で待つ（人間待ちと同じ）
                        ├ OnBeginPlayerTurn コールバック → 監査スナップショットを ConcurrentQueue へ   (XRLCore.cs:604)
                        └ NewMessageLogEntry コールバック → メッセージを ConcurrentQueue へ           (XRLCore.cs:657)
[ブリッジスレッド]    ClientWebSocket（v1 の BrainClient を流用）、画面サンプラ（30Hz）、
                      落ち着き判定、キー注入、フォーカス維持、リーク検出
```

- **ブリッジはゲームスレッドを一度も止めない。** ゲームスレッドは、人間を待つときと同じ `GetNextKey` の中で待つ。
  - 注目時は `KeyEvent.WaitOne(20)` を繰り返す。
  - 非注目時は `WaitOne(1000)`。
  - 出典は `Keyboard.cs:1011-1031`。
- この構成から、次のことが言える。
  - v1 の CTA ブロック、500ms のタイムアウト、エネルギーの 3 層ドレインは要らない。
  - 「タイムアウトしたら東へ歩く」問題（報告 01 §5.2-4）は構造上起きない。
  - ゲームスレッドを待たせる `gameQueue`/`awaitTask` のデッドロック（K21）も起きない。
- ロックは `BufferCS` だけを短時間取る。`GameViewStack` は取らない（UI スレッドと入れ子の順序が逆になるのを避けるため）。
- ゲームスレッドの中でやるのは、2 つのコールバックが `ConcurrentQueue` に積むことだけである。

### 5.2 落ち着き（settled）の判定

次のすべてを満たしたとき、「フレームが落ち着いた」とみなす **[要実測]**。

1. `Keyboard.KeyQueue.Count == 0` かつ `!Keyboard.HasMouseEvent()`。注入したキーが消費されたことを表す。
2. `CurrentBuffer` の文字と色のハッシュが、`T_settle` の間（既定 120ms）変わらない。
3. `XRLCore.CoreThread.ThreadState` に `WaitSleepJoin` が含まれる。`GetNextKey` の待ちを近似している。
4. `AutoAct.IsActive() == false`。

条件 4 が必要な理由：休息中は `RenderBase` が早期に return するので（`XRLCore.cs:2614-2618`）、**画面が止まっていてもゲームは動いている。** この状態でキーを積むと、AutoAct の中断として扱われる（`ActionManager.cs:810-814`）。

補助の設定：

- アイドル時のアニメーションは、`CmdToggleAnimation`（`XRLCore.cs:1703-1704`）で `EnableAnimation=false` にする。これで PlayerTurn は `GetNextCommand` の中でブロックし、画面がちらつかなくなる（`XRLCore.cs:754,900`）。
  - このコマンドは `Commands.xml` に **Debug カテゴリで存在するが、既定のキーバインドがない**（`Base/Commands.xml:862`）。
  - そこで、隔離プロファイルのキーマップに 1 つのキーを割り当て、開始時にそのキーを押す。人間もキー設定画面で割り当てられる操作ではあるが、§3.1 の「既定のキーマップ」の例外に当たるので、§5.5 と同じ開示リストに載せる。
  - 使わない場合は、落ち着き判定がアニメーションのフレームを許容する必要がある（画面の差分が色だけのときは無視する、など）。
- 念のため `OptionDisableAllIdleTileAnimations=Yes` も設定する（`Keyboard.cs:926-936` の `IdleWait`）。

**Harmony が使える場合の上位互換**：`Keyboard.GetNextKey` に prefix を当てて「待ち入り」を正確に通知する。これは同期のためのフックで、情報は増えないので、主張は弱まらない。ただし Rosetta が必要になるので（§10.1）、**既定では使わない。**

### 5.3 鉄則：1 つの落ち着いたフレームにつき、入力は 1 つ

入力を黙って消す仕組みが少なくとも 5 つある。

| # | 消える仕組み | 引用 |
|---|---|---|
| 1 | `Popup.ShowBlock` や legacy の `Show` は、入口で `ClearInput` を呼ぶ | `Popup.cs:687,1150` |
| 2 | PlayerTurn は冒頭で `ClearMouseEvents(LeaveMovementEvents:true)` を呼ぶ | `XRLCore.cs:734` |
| 3 | AutoAct の実行中にキーがあると中断になり、そのキーは `getch` で食われる | `ActionManager.cs:810-814` |
| 4 | `GameManager.focused` が false から true に変わると `ClearInput` と `ClearMouseEvents` が走る | `GameManager.cs:410-414` |
| 5 | ビューが切り替わると UI スレッドで `ControlManager.ResetInput()` が呼ばれる。Keyboard のキューに影響するかは **[要実測]** | `GameManager.cs:3177-3180` |

したがって、次のようにする。

- 次の入力は、必ず落ち着きを確認してから 1 つだけ積む。
- 画面の遷移をまたいでキーを先に積んでおくことは、どの場面でも禁止する。
- `OptionCapInputBuffer=No` にしても、先積みの問題は解決しない。

**レイテンシ予算 [推論]**：1 入力あたり、落ち着き 120〜250ms と WebSocket の往復（v1 の p95 は 1ms）がかかる。LLM を呼ばないマクロの 1 ステップは約 0.2〜0.3 秒になる。`look_at` は約 4 ステップなので約 1 秒、`use_ability` は 2〜4 ステップである。支配的なのは LLM の 3〜20 秒である。

### 5.4 タイムアウト、一時停止、切断、起床

| 事象 | 挙動 |
|---|---|
| LLM が考えている | ゲームは人間を待つときと同じように止まっている。**行動を強制するタイムアウトはない** |
| 落ち着かない（自動探索が長い、移動中など） | `busy` フレームを 1 秒ごとにオーバーレイへ送る。LLM は `wait_screen` するか、`interrupt`（何かキーを押す。人間の中断と同じ）を選ぶ |
| 30 秒以上落ち着かず、`AutoAct` も非アクティブ | `stall` としてログとオーバーレイに出す。`CurrentGameView` を見て、Modern リーク（§4.3）かどうかを判定する |
| WebSocket の切断 | ブリッジは再接続を繰り返すだけで、ゲームには何もしない（AFK と同じ）。v1 の `SkipPlayerTurn` + `KeyEvent.Set` による起床は**不要**。再接続したら最新のフレームを再送する |
| 一時停止（配信の都合） | ブレイン側でキーを送らないだけにする。ゲームは止まっている |

### 5.5 フォーカスによる停止への対処

- PlayerTurn は `!GameManager.focused` の間 `Thread.Sleep(200)` し続ける（`XRLCore.cs:737-740`）。`kbhit` と `GetNextKey` は、`bThreadFocus==false` のときに 200ms と 1000ms 待つ（`Keyboard.cs:938-950,1031`）。
- **FocusKeeper**（ブリッジスレッド）は、キーを積む**直前**に次のことを行う。
  1. `GameManager.focused` と `XRLCore.bThreadFocus`（`XRLCore.cs:223`）を確認する。
  2. false なら true を書き込む。
  3. 書き込みで `ClearInput` が走るので、**その後で**キーを積む。
- 加えて `OptionMusicBackground=Yes`（`Application.runInBackground`、`Options.cs:1445-1454`）を設定する。
- ゲーム状態の情報も行動も与えないハーネス側の配管なので、開示リストに載せる。**[要実測]** Unity の `OnApplicationFocus(false)` が再び来たときに、次の入力まで遅延が出るかを測る。

---

## 6. 通信と配置

### 6.1 プロセス構成

```text
CoQ.app（arm64 ネイティブ、隔離プロファイル、Harmony なし）
  └ mod "LLMOfQudParity"（.cs のみ。Roslyn でコンパイル）
       Bootstrap: [HasModSensitiveStaticCache] + [ModSensitiveCacheInit] で、プロセスごとに 1 回だけブリッジスレッドを起動する（二重起動を防ぐ static ガード付き）
       ↕ ws://127.0.0.1:4040/qud （mod がクライアント。v1 の ClientWebSocket を流用。報告 03 §5）
qudenv（Python / uv、同じ Mac）
  ├ env サーバー：step / observe / reset（gym 形式）
  ├ agent ループ：Anthropic SDK（prompt caching、ツール定義は §3.1）
  ├ MCP アダプタ（stdio）：同じ step をツールとして公開し、Claude Code や Codex を一次クライアントとして使えるようにする
  ├ overlay：http://127.0.0.1:8080（SSE。OBS のブラウザソース）
  └ ログ：runs/<run_id>/*.jsonl
```

- **起動を `[ModSensitiveCacheInit]` にする理由**：
  - この属性は、ゲーム開始前（メインメニュー）に処理を走らせる公式の入口である（`ModManager.cs:340-372`、`XRLCore.cs:577`）。
  - `IGameSystem` を使わないので、**mod の型がセーブに書き込まれない**（`XRLGame.cs:1580-1600`、K18）。
  - v1 の `[PlayerMutator]` は新規ゲームでしか呼ばれない（報告 04 §6）。
  - コールバックの登録（`RegisterOnBeginPlayerTurnCallback`、`RegisterNewMessageLogEntryCallback`）は static リストへの追加である。重複しないように、1 回だけ登録するガードを付ける（`XRLCore.cs:604-680`。後者は重複を防ぐ実装になっている）。

### 6.2 シリアライズ

- `frame`：`{seq, view_tag, chars:[25×string(80)], fg:[25×string(80)], settled_ms, keyq:0, t}`。bg は既定では送らない。
- `msg`：`{seq, text_raw, text_stripped}`。`ColorUtility.StripFormatting` で色を除いた版も付ける。
- `key`：`{seq, keycode, ch, shift, ctrl, alt, why:"press:CmdMoveE"}`。
- `ack`：`{seq, consumed:true, next_frame_seq}`。
- `audit`：`{turn, zone_id, hp, level, quests_done, end_type}`。**ブレイン側で LLM 用の経路と物理的に分けたファイルに書く。**
- JSON は Newtonsoft 13 を第一候補にする（参照できるかは報告 03 §5 の compile probe で確かめる）。駄目なら手書きで直列化する。中身が文字列の配列なので小さく済む。

### 6.3 ブレインの言語を Python にする理由

1. 主な利用面が **gym 形式の env** なので、NLE/BALROG と同じ言語で比較しやすい。
2. オーナーの他のリポジトリが Python/uv である。
3. mod がクライアントになる構成は v1 で実証済み（K19）。mod 内に `HttpListener` の MCP サーバーを置く構成は未実証である（報告 03 の U10）。
4. このレンズでは、mod の責務が「画面を取る」「キーを入れる」「落ち着きを判定する」だけになる。C# の in-process MCP にする利点が小さい。
5. オーナーの「Claude Code を一次クライアントに」という希望は、Python の MCP アダプタで満たせる。

---

## 7. 記憶と知識

### 7.1 何を永続化するか

| 対象 | 書く主体 | 場所 |
|---|---|---|
| フレーム、キー、メッセージ、LLM の入出力、監査、介入 | ハーネス | `runs/<run_id>/{frames,keys,messages,llm,audit,interventions}.jsonl` |
| 実行中のノート（現在の目標、地図のメモ、NPC と依頼、危険物） | **LLM**（`note_write`） | `runs/<run_id>/notes.md`。上限は約 3k トークン。超えたら LLM 自身に要約させる |
| 周回をまたぐ学習（死因と教訓） | **LLM**（死亡か中断の後の振り返りで） | `knowledge/lessons.md`。RimMolt の `ACTIVE_LESSONS` と同じく約 40 件を上限にし、「X を覚える」ではなく行動規則の形で書かせる（報告 02 の P9/P10） |
| キーの表 | ハーネス（生成物） | `Commands.xml` の既定のキーバインドから生成する。人間向けのキー設定画面に出るのと同じ情報である |

### 7.2 知識ベースと、ネタバレの扱い

| 階層 | 内容 | クリア主張の run で使うか |
|---|---|---|
| K0 | ゲーム内で読めるもの：ヘルプ（`CmdHelp`、`Manual.xml` 25KB、約 6k トークン、`XRLManual.cs:33`）、ゲーム内の本、ジャーナル | **使う**（人間も読める） |
| K1 | モデルが事前学習で持っている CoQ の知識 | **除去できない。そのように開示する** |
| K2 | `Quests.xml`、`Conversations.xml`、`ObjectBlueprints` などの生データ | **使わない**（人間の画面には出ない。特権的なデータに当たる） |
| K3 | 公式 Wiki（CC BY-NC-SA 4.0） | **使わない。** ablation や配信用の「攻略本あり」モードでだけ使う |

**判断**：クリアを主張する run は **K0 + K1** で行う。K1 を消せないことは BALROG でも同じで、「ゲーム内の知識と、モデルが事前に持っている知識」として開示する。

---

## 8. 評価と証拠

### 8.1 進行度の指標（監査の経路でだけ計算する）

| 指標 | 計算方法 |
|---|---|
| 主線クエストの段階 | `Quests.xml` の 28 クエスト / 84 ステップのうち主線に当たるもの。例：`What's Eating the Watervine?` → `Fetch Argyve...` → `A Canticle for Barathrum` → … → `Tomb of the Eaters` → `The Golem` → `Reclamation`。`XRLGame.Quests`/`FinishedQuests`（`XRLGame.cs:145-148`）で段階を数える |
| クリア | `The.Game.GetStringGameState("EndType")` が空でないこと（`EndGame.cs:67-79`） |
| 補助指標 | レベル、到達した最深の階層、生存ターン数、死亡回数、チェックポイントの使用回数、介入回数、LLM の 1 手あたりのトークン数とドル |

### 8.2 ログと再現性

- CoQ の戦闘 RNG はシードを与えても再現しない（`XRL.Rules/Stat.cs:26-36`、K27）。したがって**決定的な再シミュレーションはできない。** 代わりに**観測の完全なリプレイ**を保証する。
  - `frames.jsonl` に、LLM に渡した全フレーム（L0）を残す。
  - `llm.jsonl` に、プロンプトと応答の全文を残す。
  - `keys.jsonl` に、実際に注入した全キーを残す。
- 配信の録画（OBS）と照合できるように、各フレームに単調増加の `seq` と壁時計の時刻を付ける。

### 8.3 検証可能な「特権的な状態なし」の主張

公開する検証スクリプト `verify_parity.py` は、次のことを確かめる。

1. **L1 の再導出**：`llm.jsonl` の各プロンプトに含まれる観測ブロックを、`frames.jsonl` の L0 と `messages.jsonl` だけから再生成し、**バイト単位で一致すること。** L1 の注釈（ルーラー、salient、color_rows、ViewTag の表示名）は L0 の決定的な関数として実装するので、一致しなければ違反である。
2. **メッセージフィードの等価性**：run 中、500 手ごとにハーネスが `CmdMessageHistory` を開いて画面を取り、`messages.jsonl` の該当区間と突き合わせる（色を除いた文字列で）。不一致の率を報告する。
3. **入力の等価性**：`keys.jsonl` のすべてが、`Commands.xml` の既定のキーマップにあるキーか、モーダル内の文字や数字のキーであること。`PushCommand` の使用は 0 件か、開示した例外に限られること。
4. **監査の隔離**：`audit.jsonl` の値（ターン数、ゾーン ID、HP の数値）が、どのプロンプトにも出現しないことを確かめる。サイドバーの HP のように画面にも出る値は、同じフレームの画面に出ている場合だけ許す。

### 8.4 ゲームモードと主張

**判断：主となる run は Roleplay にする。**

- Roleplay はチェックポイントのあるモードである（`Base/EmbarkModules.xml:16-60`）。
- 死亡した後にチェックポイントへ戻るかどうかは、legacy のポップアップで**エージェント自身が選ぶ。** 人間の Roleplay プレイヤーと同じ条件になる。
- Classic（パーマデス）は主張としては最も強い。しかし 1 回の死で数十時間分の進行が消える。予算の範囲でクリアに届く見込みが低いので、主要な指標（主線の到達段階）を比べるための**副次の run** として回す。
- Wander は戦闘による XP がないので、主張には使わない。

**このレンズが支えられる主張**（上から強い順）：

1. 「LLM が、**人間と同じ 80×25 のテキスト画面（色を含む）と、人間と同じキー入力だけで**、Caves of Qud（2.0.211.56、Roleplay）のエンディングに到達した。ハーネスはゲームの内部状態を LLM に渡していない。これは公開ログと検証スクリプトで確かめられる」。
2. 例外として明記するもの：
   - キャラクター作成はオペレーターが入力した（仕様は LLM が書いた）
   - Modern リークによる介入が N 回あった
   - フォーカスを維持するなどの配管
   - モデルが事前に持っている知識

**先行例について**：

- 報告 02 と、筆者が今回行った簡単な Web 検索（2026-09-25）では、LLM が CoQ をクリアした報告も、公開された自律プレイの試みも見つからなかった。**これは「見つからなかった」ということであって、「存在しない」ことの証明ではない。** 主張の文言は「我々の調べた範囲で初」とする。
- **現在の SOTA なら当然クリアできるか**：できる根拠は見当たらない。
  - BALROG の NetHack では、最良のモデルでも進行度は約 13% 以下にとどまっている（o1-preview は 1.5%。二次情報）。
  - 画像を使わない RimWorld のクリアにも、人間による 1 回の指示とスクリーンショットが使われていた（報告 02 §1.1.2）。
  - CoQ の主線は、人間でも数十時間かかる長い計画を要する **[推論]**。
- したがって、プレイヤーと同等の条件でクリアすれば、それ自体が非自明な結果になる。ただし事前学習に Wiki の知識が含まれることは、主張の限定として必ず書く。

---

## 9. 配信適性

- **視聴者に見えるもの**：
  - 実際のゲームウィンドウ（クラシック ASCII。LLM が見ているものと同じ）
  - OBS のブラウザソースによるオーバーレイ：現在の目標、LLM の要約された思考、直近の 5 手のキー（`CmdMoveNE` → `9` のように、人間のキー表記で出す）、主線の進行バー、コストメーター
  - LEAK/介入のバナー
- **「LLM と同じものを見ている」ことが演出になる。** オーバーレイに「LLM に渡した画面」を小さく並べる（L1 の salient に印を付けたもの）。
- **ペーシング**：
  - LLM 自体が自然なスロットルになる。v1 の K15 で問題になった暴走は、キーを 1 つずつ入れるこの構成では起きない。
  - マクロの内部ステップは、人間が目で追えるように、最低 150ms 画面に残す。
  - 自動探索は `OptionAutoexploreRate` の既定（20 セル/秒）のままでよい。
- **弱点**：
  - タイルの見た目にならない。
  - Look を多用すると、画面がカーソル操作で忙しく見える。オーバーレイで「調べている」と表示して補う。
  - 思考が 10 秒以上続く場面では、オーバーレイの思考ログのストリーミングで間を埋める。

---

## 10. プラットフォームと更新への耐性

### 10.1 Apple Silicon と Harmony

- **Harmony を使わないので、arm64 ネイティブで起動できる。Rosetta は要らない。**
- 同梱の Harmony 2.2.2 は、ネイティブ起動では EACCES で失敗する（報告 04 §4.6）。このリスクを丸ごと避けられる。
- Harmony を使う任意の拡張（§5.2 の `GetNextKey` の prefix）は、Rosetta で起動する別のプロファイルに隔離する。主張の run では使わない。

### 10.2 更新への耐性

依存するシンボルは以下に限る。更新があれば、Roslyn のコンパイルエラーとして起動時に検出できる。`BUILD_2_0_211` シンボルで分岐することもできる。

| 分類 | シンボル |
|---|---|
| 画面 | `TextConsole.CurrentBuffer`、`BufferCS`、`ScreenBuffer.Buffer[x,y]`、`ConsoleChar.Char`/`Foreground`、`ScreenBuffer.ViewTag`、`ColorUtility.ColorToCharMap` |
| 入力 | `Keyboard.PushKey(XRLKeyEvent)`、`KeyQueue`、`HasMouseEvent` |
| フォーカス・ビュー | `GameManager.focused`/`CurrentGameView`、`XRLCore.bThreadFocus`、`CoreThread` |
| 同期・監査 | `AutoAct.IsActive`、`XRLCore.RegisterOnBeginPlayerTurnCallback`/`RegisterNewMessageLogEntryCallback` |
| その他 | `CommandBindingManager.GetKeyFromCommand`、`[ModSensitiveCacheInit]`、監査用の `XRLGame.Quests`/`GetStringGameState` |

**最大の更新リスクは、legacy UI そのものが保守されなくなることである。**

- `OptionModernUI` は `RequiresCapability="IsDesktop"` の詳細オプションである（`Base/Options.xml:53`）。一方で、現行の Options.xml には `Category="Legacy UI"` のオプションが 6 件ある（`:102-109`。`OptionPushAZHotkeys`「Always pass A-Z hotkeys through to the legacy UI」など）。legacy UI は少なくとも設定の面では現役である。
- **[推論]** 開発元の主眼は Modern UI にある。legacy の画面が壊れても、それが放置される可能性がある。
- 対策：
  - 検証済みのビルド（2.0.211.56）の参照コピーを固定し、主張の run はそのビルドで行う。
  - Steam の自動更新を止める。QudJP が `~/Games/CavesOfQud-stable-ref` を持っているのと同じやり方である。

### 10.3 隔離プロファイル

- `-savepath "$HOME/Library/Application Support/Freehold Games/CavesOfQud-llm"` で起動する（報告 04 §4.9、§5.1）。
- `Local/PlayerOptions.json` に次を事前に書く。
  - `OptionModernUI=No`、`OptionUseTiles=No`
  - `OptionAllowCSMods=Yes`、`OptionShowAdvancedOptions=Yes`
  - `OptionCapInputBuffer=No`、`OptionMusicBackground=Yes`
  - `OptionMouseInput=No`、`OptionDisableAllIdleTileAnimations=Yes`
  - `Language=en`
- `Local/ModSettings.json` では、この mod だけを有効にする。
- 事前に書いた JSON が初回起動でそのまま採用されるかは、報告 04 §6 の未解決の問いと同じく **[要実測]** である。

### 10.4 QudJP との共存

- **主張の run では共存させない。**
  - QudJP は Harmony で 1,693 メソッドにパッチを当てる（報告 03 §4.2）。Rosetta が必要になる。
  - 画面の文字が日本語になり、英語の Manual や他のベンチマークと比べられなくなる。
- オーナーの普段のプロファイル（`Language=ja`、QudJP 有効）には手を触れない。
- 日本語で配信したい場合は、オーバーレイの側で LLM の思考を日本語で出す。

---

## 11. マイルストーン（最初の 3 週間）

### 最初にやるべきランタイムプローブ（1 週目の前半）

| # | プローブ | 合格条件 |
|---|---|---|
| R1 | legacy + text の隔離プロファイルで起動し、wish コマンドで `CurrentBuffer` をダンプする。対象はマップ、サイドバー（Hidden とそれ以外）、`Popup.Show`、PickOption、YesNo、会話、インベントリ、取引、レベルアップ、Look | すべての画面で、人間が読める本文が `_Char` に入っている。ViewTag が記録される |
| R2 | ブリッジスレッドから `PushKey` で、移動、`CmdAutoExplore`、ポップアップの `Space`、会話の `1`、PickDirection のテンキー、AskString の `type` を行う | どれも期待どおりに消費される。キーが消えた件数を数える |
| R3 | 落ち着き判定の偽陽性と偽陰性 | 休息（`z`）、自動探索、戦闘アニメーション、ゾーンの遷移、`EnableAnimation` のオンとオフで、偽陽性 0 件、落ち着くまでの p95 が 300ms 未満 |
| R4 | 非注目のウィンドウで FocusKeeper を動かす | 1 時間で PlayerTurn の停止が 0 件、キーの消失が 0 件 |
| R5 | `[ModSensitiveCacheInit]` の起動が、新規ゲーム、ロード、メインメニューへの復帰、2 回目の新規ゲームをまたいでも続くか | ブリッジスレッドは常に 1 本。コールバックの二重登録なし。セーブに mod の型が残らない |
| R6 | `ClientWebSocket` と Newtonsoft のコンパイル | `build_log.txt` に `Success :)` が出る |
| R7 | Modern リークの調査 | 通常のプレイを 30 分行い、`CurrentGameView` に現れた名前を一覧にして §4.3 を確定する |

### 週ごとの計画

| 週 | マイルストーン | 完了条件 |
|---|---|---|
| **1 週目** | **M1：最初の自律 LLM ターン。** R1〜R6 を終えた後、Python の env と、最小の agent ループ（L0 観測、`press`/`key` の 2 ツール）で、LLM が画面を見てキーを 1 つ選び、`@` が動き、次のフレームが返る | 20 手を連続で、人手の介入なしに行える。`frames`/`keys`/`llm` の 3 つのログが残る |
| 2 週目 | M2：モーダルと L1 | L1 の注釈（決定的な関数とそのテスト）、メッセージフィード、R7 とリーク検出、L2 マクロ（`look_at`、`use_ability`、`travel_poi`）。Joppa を起点に 1 時間無停止で動き、ポップアップ、会話、インベントリ、レベルアップを自力で抜ける |
| 3 週目 | M3：証拠と配信の土台 | 最初の版の `verify_parity.py`（§8.3 の 1〜4）、オーバーレイ、`notes.md`/`lessons.md`、監査の進行度の指標。Roleplay の run で `What's Eating the Watervine?` と `Fetch Argyve a Knickknack` を完了する |

- キャラクター作成は、全週を通じてオペレーターが入力する（§4.4）。
- エンディングの経路（`EndGame.cs:162` の AskString）の確認は、別プロファイルのデバッグ用セーブで M3 以降に行う（R8）。

---

## 12. 最もリスクの高い前提

| # | 反証可能な主張 | なぜ重要か | 懐疑的な読者が読むべき箇所 | 実測が必要か |
|---|---|---|---|---|
| 1 | `OptionModernUI=No` + `OptionUseTiles=No` では、キャラクター作成の後のゲームプレイの UI（ポップアップ、会話、ステータス画面、取引、Pick*、Look、本、レベルアップ）がすべて `TextConsole.CurrentBuffer` に描かれ、`Keyboard.getvk` でキーを待つ | 設計全体の前提。崩れた画面は読めず、答えられない | `Qud.UI/UIManager.cs:55`、`TextConsole.cs:142-157`、`Popup.cs:676-710,1138-1188,1440-1450,1709-1916,2258-2290`、`ConversationUI.cs:418-429`、`Screens.cs:88-151`、`TradeUI.cs:456-465`、`AbilityManager.cs:144`、`Look.cs:487-927`、`PickTarget.cs:117,747`、`BookUI.cs:427,464` | はい |
| 2 | legacy のままで出る Modern のポップアップ（リーク）は、キャラクター作成を除けば、ロード時の mod 構成の不一致と、代名詞のカスタム設定だけで、どちらも運用で避けられる | リークのたびに人間が介入するので、主張が弱まる | `Popup.cs:1624-1640,2326-2339,1371`、`XRLCore.cs:3448`、`StatusScreen.cs:520`、`PronounAndGenderSets.cs:90,223,573,589`、`MouseBlocker.cs:72` | はい |
| 3 | Harmony なしで、「キューが空」「画面のハッシュが止まる」「CoreThread が WaitSleepJoin」「`AutoAct.IsActive()==false`」の組み合わせによって、入力待ちを偽陽性なしに判定できる | 偽陽性はキーの消失や AutoAct の誤った中断を、偽陰性は停止を招く | `Keyboard.cs:926-1031`、`XRLCore.cs:754,900,1703-1704,2614-2618`、`ActionManager.cs:805-814` | はい |
| 4 | ブリッジスレッドから `GameManager.focused` と `XRLCore.bThreadFocus` を書き換えれば、バックグラウンドでもキーを失わずに PlayerTurn を進められる | 無人の運転と配信で最大の停止要因になる | `XRLCore.cs:223,737-740`、`GameManager.cs:404-425,1920-1924`、`Keyboard.cs:938-950` | はい |
| 5 | 2.0.211.56 の legacy UI は実用に耐える程度に保守されていて、主線の全区間（会話、取引、Tinkering、エンディングの AskString）を legacy だけで進められる | legacy が一部でも壊れていれば、クリア不能か、介入が常態化する | `Base/Options.xml:53,102-109`（Legacy UI カテゴリ）、`Options.cs:1296-1302`、`EndGame.cs:162,326-345`、`TinkeringScreen.cs:23` | はい |
| 6 | `[ModSensitiveCacheInit]` から起動した static のブリッジスレッドは、新規ゲームとロードをまたいでも 1 本のまま動き続け、セーブに痕跡を残さない | `IGameSystem` を使わない設計の要。v1 の未検証の問題（Stop が呼ばれない、スレッドが残る）を避けるため | `XRL/ModManager.cs:340-372`、`XRLCore.cs:577,604-680`、`XRLGame.cs:1580-1600` | はい |
| 7 | L1 の注釈とメッセージフィードは、L0 とゲーム内のメッセージ履歴から完全に再導出できる（特権的な情報を含まない） | 「特権的な状態なし」という主張の検証可能性そのもの | `MessageQueue.cs:94-150`、`XRLCore.cs:657-680,2296`（`CmdMessageHistory`）、`ColorUtility.cs:165` | 一部（§8.3 の監査 2） |
| 8 | 1 フレーム約 1.5〜3k トークンで、マクロ（自動探索、`travel_poi`、休息）による圧縮を使えば、主線の完走に要する LLM の呼び出し（数万回規模 [推論]）が予算内に収まる | 収まらなければ、主張の強さを保ったままではクリアに届かない | `XRLCore.cs:1347,1517,1920`、`ActionManager.cs:855-1441`（AutoAct の各設定） | はい（2〜3 週目に 1 時間あたりの手数とコストを測る） |
