# F3: ピッカー系モーダルの静的検証（Modern UI 前提）

対象ビルド: 2.0.211.56（ILSpy 逆コンパイル、`~/Dev/coq-decompiled_stable`）。
引用はすべて、ソースルートからの相対パス `path:line` で書く。本書の作業中に `sed -n` / `awk` / `grep -n` で実際に表示した行だけを引く。

## 1. 目的

Modern UI を画面に残したまま、ゲームスレッドを止める「ピッカー」系の入力待ちについて、次の三点を確かめる。

- (a) 検出: ブリッジスレッドか UI スレッドから、いまどのピッカーで止まっているかを判定できるか。
- (b) 読み取り: Legacy 相当の文字情報（プロンプト、候補、カーソル）を取り出せるか。
- (c) 回答: 非ゲームスレッドから確定またはキャンセルできるか。Harmony なしでできるか。

結論を先に書く。**ピッカー系は、Harmony なしで成立する。** ただし、成立のしかたは二種類に分かれる。

- getvk ループ型（PickDirection、PickTarget の 3 モード、射撃・投擲、Look）は、`Keyboard.PushKey` / `PushMouseEvent` で答える。
- `.Result` 型（PickGameObjectScreen、ゲームパッド時の AskNumberScreen）は、UI スレッドで画面オブジェクトの public メソッドを呼んで答える。

getvk ループ型にはカーソル座標を公開する static がない。そこでブリッジは、カーソルの位置を読まずに「絶対座標を押し付けてから確定する」方式を採る。

## 2. 対象一覧

| # | モーダル | 入口 | ゲームビュー（`CurrentGameView`） | `PickTargetWindow.currentMode` | 待ち方 |
|---|---|---|---|---|---|
| M1 | PickDirection | `PickDirection.ShowPicker(Label)` | `"PickTarget"` | `PickDirection` | getvk ループ |
| M2 | PickTarget（セル選択） | `PickTarget.ShowPicker(...)` | `"PickTarget"` | `PickCells` | kbhit + getvk のループ |
| M3 | PickTarget（フィールド） | `PickTarget.ShowFieldPicker(...)` | `"PickTarget"` | `PickField` | kbhit + getvk のループ |
| M4 | 射撃・投擲の照準 | `MissileWeapon.ShowPicker(...)` | `"FireMissileWeapon"` | `PickCells` | kbhit + getvk のループ |
| M5 | Look | `Look.ShowLooker(Range,X,Y)` | `"Looker"` | `PickCells` | kbhit + getvk、空なら IdleWait |
| M6 | PickGameObjectScreen | `PickItem.ShowPicker(...)`（Modern 分岐） | `"PickGameObject"` | ― | `Task.Result` |
| M7 | AskNumberScreen | `Popup.AskNumber`（ゲームパッド時だけ） | `"ModernPopupGamepadAskNumber"` | ― | `Task.Result` |

依頼文は「throw/fire は PickTarget に入る」と想定していたが、これは誤りである。射撃も投擲も `MissileWeapon.ShowPicker` に入り、ビュー `"FireMissileWeapon"` を積む（`XRL.World.Parts/Combat.cs:270`、`:453`、`XRL.World.Parts/MissileWeapon.cs:22`、`:300-303`）。05 の C03 は「PickTarget と PickDirection は同じ `"PickTarget"` ビュー」としていた。これはそのとおりだが、それだけでは足りない。ゲームスレッド側のピッカーは `"PickTarget"`（3 モード）、`"FireMissileWeapon"`、`"Looker"` の三つのビューに分かれる。

## 3. 各モーダルの動作

### 3.0 共通の土台

**UIView 登録。** 属性の引数の順番は `UIView(ID, WantsTileOver, ForceFullscreen, IgnoreForceFullscreen, NavCategory, UICanvas, TakesScroll, UICanvasHost, ...)` である（`XRL.UI/UIView.cs:45`）。
- `"PickTarget"` は、WantsTileOver=true、NavCategory "Targeting"、UICanvas "PickTargetFrame"、host 1（`XRL.UI/PickTarget.cs:15`）。
- `"FireMissileWeapon"` は、WantsTileOver=true、"Targeting"、"PickTargetFrame"（`XRL.World.Parts/MissileWeapon.cs:22`）。
- `"Looker"` は、WantsTileOver=**false**、"Looker"、"PickTargetFrame"（`XRL.UI/Look.cs:20`）。
- `"PickDirection"` という UIView も登録されている（`XRL.UI/PickDirection.cs:11`）。しかし、文字列リテラル `PushGameView("PickDirection")` は、grep では見つからなかった。PickDirection 自身は `"PickTarget"` を積む（`XRL.UI/PickDirection.cs:30-31`）。

三つのビューは、どれも同じ `PickTargetWindow` を表示する。この窓が持つのは、static の `currentText` と `currentMode` だけで、`Update` で `currentText` を UITextSkin に写す（`Qud.UI/PickTargetWindow.cs:5`、`:8-13`、`:17-19`、`:26-32`）。`currentMode` は、各入口が `PushGameView` の直前に代入するだけで、終了時に戻す処理はない（`XRL.UI/PickDirection.cs:30`、`XRL.UI/PickTarget.cs:86`、`:380`、`XRL.UI/Look.cs:407`、`XRL.World.Parts/MissileWeapon.cs:302`）。そのため、検出はかならず「ビュー」と「モード」の論理積で行う。

**入力の経路。** getvk ループは `Keyboard.GetNextKey` を通る。
- `GetNextKey` は、まず `MouseEventQueue` を見て、次に `KeyQueue` を見る（`ConsoleLib.Console/Keyboard.cs:967-1005`、`:1006-1043`）。
- `metaMousecommands` に載っているマウスイベント（`"Meta:NavigateN"` など）は、対応する `Keys` に変換される。載っていないものは `Keys.MouseEvent` になり、`CurrentMouseEvent` に写される（`:156-290`、`:969-1003`）。
- `PushKey(KeyCode)` は `allowmap=false` で積む（`:772-787`）。キーパッドの `KeyCode.Keypad1..9` は `Keys.NumPad1..9` に対応し（`:534-543`）、矢印キーは NumPad に読み替えられる（`:1193-1212`）。Escape、F1、Space、Return、F の対応は `:426`、`:431`、`:532-533`、`:568` にある。
- `getvk` は、`pumpActions=false` のまま `GetNextKey` を呼ぶ（`:1354-1358`）。そのため、待っている間に `gameQueue` は回らない（回すのは `pumpActions` のときだけ。`:1017-1023`、`:1038-1041`）。

したがって **`Keyboard.PushKey` / `PushCommand` / `PushMouseEvent` は、M1〜M5 に届く**（C-F3-pickers-01）。`PushCommand(c)` は `PushMouseEvent("Command:"+c)` と同じである（`:723-726`）。

**入力が消える条件と、積める数の上限。**
- `PushKey` は、`TutorialManager.AllowPushKey` が偽なら捨てる。`GameManager.bCapInputBuffer` が真のときは、`KeyQueue.Count <= 2` の間しか積まない（`ConsoleLib.Console/Keyboard.cs:777-796`）。
- `PushMouseEvent` も、`AllowMouseEvent` が偽のときと、上限のときに捨てる（`:825-849`）。条件は `MouseEventQueue.Count > 2 && bCapInputBuffer` である。
- どちらも黙って捨てる。`bCapInputBuffer` は `Options.CapInputBuffer` から設定される（`XRL.UI/Options.cs:1279-1286`、`GameManager.cs:152`）。
- チュートリアルのポップアップ表示中は、どちらも拒否される（`TutorialManager.cs:311-319`、`:361-369`）。
- **ビューが切り替わると入力が消える。** UI スレッドの `UpdateView` は、`_ActiveGameView != _CurrentGameView` のとき `Keyboard.ClearInput()` を呼ぶ（`GameManager.cs:1573-1582`）。`UpdateView` は `Update` の後半、`TextConsole.BufferUpdated` の分岐から呼ばれる（`:3172-3183`）。一方、`uiQueue.executeTasks()` は同じフレームのもっと前で走る（`:2963`）。
- `XRLCore.bThreadFocus` が偽のときは、`Update` が `:3108-3113` で return する。この場合 `UpdateView` は走らず、`_ActiveGameView` も更新されない。`focused` が false から true に変わると、入力が消える（`:404-418`、`:1920-1924`）。

以上から、getvk 型に入力を積む**前提条件**は次の式になる。UI スレッドの `uiQueue` タスクの中で評価する。

```
XRLCore.bThreadFocus
&& GameManager.Instance._ActiveGameView == GameManager.Instance.CurrentGameView
&& CurrentGameView == <対象ビュー> && PickTargetWindow.currentMode == <対象モード>
```

`_ActiveGameView` は public のフィールドである（`GameManager.cs:238`）。`CurrentGameView` は public のプロパティである（`:469-483`）。ビューの push と pop はゲームスレッドから `lock (GameViewStack)` の中で行われる（`:1493-1510`、`:1523-1542`）。

**本物のマウスによる干渉。** Modern では、`OnTileOver` は `WantsTileOver` が真のビューに限って `"PointerOver"` を積む（`GameManager.cs:1180-1199`）。したがって、`"PickTarget"` と `"FireMissileWeapon"` では、画面上の本物のマウスがカーソルを動かしうる。`"Looker"` では動かさない。

**ゲームパッドの入力の変換。** UI スレッドの `UpdateInput` は、NavCategory が "Targeting" か "Looker" のとき、`CmdFire` と `CmdThrow` の押下を `PushCommand("CmdFire")` に変換する。PickDirection モードでは、方向の押下を `"Meta:Navigate*"` に変換する（`GameManager.cs:2163-2192`、`:2193-2234`）。これは実入力の経路であり、ブリッジは同じイベントを直接積めばよい。

### 3.1 M1 PickDirection

- 入口: `ShowPicker(Label)` は `currentMode=PickDirection` を代入してから、`PushGameView("PickTarget")` を呼ぶ（`XRL.UI/PickDirection.cs:28-31`）。
- 待ち方: `while (!flag)` の中で毎回 `Keyboard.getvk(MapDirectionToArrows: true)` を呼び、ブロックする（`:38-54`）。
- プロンプト: Modern では `PickTargetWindow.currentText = Label + " | [Select a direction]"` が入る（`:44-47`）。Legacy の画面では、同じ文字列が画面の 0 行目に書かれていた（`:50-51`）。
- 確定と戻り値:
  - NumPad1〜9 は、それぞれ "SW","S","SE","W","E","NW","N","NE" を返す（`:68-99`）。
  - NumPad5、`"Meta:Navigate"`（接尾辞なし）、`"Command:CmdTargetSelf"` は "." を返す（`:56-61`）。
  - Escape と `"RightClick"` は null を返す（`:64-67`、`:102-106`）。
  - `"LeftClick"` の x,y が自分のセルなら "."、隣接セルならその方向を返す（`:107-125`）。
  - `"Meta:NavigateNorth"` などは `metaMousecommands` で NumPad に変換されるので、キーと同じ扱いになる（`ConsoleLib.Console/Keyboard.cs:156-229`）。
- 終了: 返る直前に、必ず `PopGameView(bHard:true)` を呼ぶ（`XRL.UI/PickDirection.cs:58`、`:65`、`:70` ほか）。

### 3.2 M2 PickTarget.ShowPicker（セル選択）

- 入口: `ShowPicker(Style, Radius, Range, StartX, StartY, Locked, VisLevel, ..., Label, EnforceRange, UseTarget)` は、`currentMode=PickCells` を代入してから `PushGameView("PickTarget")` を呼ぶ（`XRL.UI/PickTarget.cs:378-381`）。
- 初期位置: `UseTarget` が真で、`Sidebar.CurrentTarget` が同じゾーンにいれば、その位置から始まる（`:391-399`）。
- ロック: ロックの状態はローカル変数 `flag = Locked` に入り、static の `bLocked` は使われない（`:382`）。
- 待ち方: 毎反復で描画してから、`if (!Keyboard.kbhit()) continue;` で分岐し、入力があれば `getvk` を呼ぶ（`:786-791`）。`bThreadFocus` が真の間、`kbhit` は待たない（`ConsoleLib.Console/Keyboard.cs:938-954`）ので、このループは入力待ちの間も描画を回し続ける。
- プロンプト: Modern では `currentText = Label + " | {{W|<Accept>}}-select" + ...` が入る（`XRL.UI/PickTarget.cs:747-750`）。Legacy では、同じ情報を 0 行目に書いていた（`:751-781`）。
- カーソル: カーソルは**ローカル変数** x, y で持つ。外から読める static はない（`:400-401`）。`Buffer.focusPosition` は `flag4` が偽のときしか更新されず、`flag4` の初期値は真である（`:405`、`:782-785`）。
- 入力の意味:
  - `"PointerOver"` は x,y をマウス座標に動かす。ただし最初の 1 回は、`flag3` の初期値が真なので捨てられる（`:402`、`:792-808`）。
  - NumPad5、Escape、`"Command:CmdTargetSelf"` は、`flag2=true` を立てて**キャンセル**する（result は null のまま。`:809-812`）。
  - F1 と `"Command:CmdLockUnlock"` は、ロックを切り替える（`:813-816`）。
  - ロック中の NumPad は、円錐の中の最初の対象に飛ぶ（`:821-866`）。
  - F、Space、Enter、`"Command:CmdFire"`、`"LeftClick"` は、**現在のカーソル位置**で確定する。`"LeftClick"` のマウス座標は使われない（`:965-984`）。
  - 確定のとき、Burst で範囲外なら `Popup.ShowFail` を出す。`VisLevel` が満たされない場合も `Popup.ShowFail` を出す（`:967-978`）。
- 終了: `PopGameView(bHard:true)` を呼んで、`Cell` を返す（`:988-990`）。

### 3.3 M3 PickTarget.ShowFieldPicker（壁などの連続セル）

- 入口: `currentMode=PickField`、`PushGameView("PickTarget")`（`XRL.UI/PickTarget.cs:84-87`）。
- プロンプト: `currentText` に、「space/5 で Start/End」「残りマス数」「Escape で Clear/Cancel」を入れる（`:111`、`:117-120`）。
- 待ち方: kbhit + getvk（`:160-164`）。
- 入力の意味:
  - Escape は、選択中なら選択を消し、そうでなければ中止する（`:165-186`）。
  - `"PointerOver"` は最初の 1 回だけ捨てられる（`:197-212`）。`"RightClick"` は中止する（`:213-216`）。
  - NumPad5、F、Space、Enter、`"LeftClick"`、`"Command:CmdFire"`、`"Command:CmdTargetSelf"` は、未開始なら開始し、開始済みなら終了する（`:322-338`）。
  - 開始後にカーソルを動かすと、隣接のセルが順に追加される（`:339-366`）。
- 戻り値: 中止で `ReturnNullForAbort` なら null、そうでなければ `List<Cell>` を返す（`:369-375`）。
- 呼び出し元: `XRL.World.Parts/ForceProjector.cs:695`、`XRL.World/IComponent.cs:3637-3657`。

### 3.4 M4 射撃・投擲（`MissileWeapon.ShowPicker`）

- 入口:
  - `Combat.ThrowWeapon` は、`TargetCell == null && Attacker.IsPlayer()` のときだけピッカーを開く（`XRL.World.Parts/Combat.cs:214`、`:236-238`、`:270`）。
  - `Combat.FireMissileWeapon` は、`TargetCell == null` のときだけピッカーを開く（`:336`、`:414-420`、`:453-458`）。`TargetCell` が与えられていれば、ピッカーを通らずに `else if` 以降へ進む（`:478-482`）。
  - `XRLCore` の `CmdThrow` は `Combat.ThrowWeapon(The.Player)` を呼ぶ（`XRL.Core/XRLCore.cs:1837-1839`）。
- 本体: `currentMode=PickCells`、`PushGameView("FireMissileWeapon")`（`XRL.World.Parts/MissileWeapon.cs:300-303`）。Snap が真なら、`Sidebar.CurrentTarget` か、いちばん近い敵から始める（`:305-322`）。
- 待ち方: kbhit + getvk（`:786-790`）。
- プロンプト: `currentText = <撃ち方の説明> + " | Fire Missile Weapon"`（`:773-776`）。
- カーソル: ローカル変数 num, num2 で持つ。ただし毎反復で `CalculateMissilePath(PlayerMissilePath, ..., num, num2, ...)` を呼び、private static の `PlayerMissilePath` に弾道を書き込む（`:80`、`:326-345`）。
  - `MissilePath` の public フィールドは `Path`、`Cover`、`X0`、`Y0`、`X1`、`Y1` である（`XRL.World.Parts/MissilePath.cs:5-19`）。
  - 投擲側は `Path.X1/3`、`Path.Y1/3` を目標のセルとみなしている（`XRL.World.Parts/Combat.cs:275`）。射撃側は `Path.Last()` を目標とみなしている（`:458`）。
  - したがって、**リフレクションで `PlayerMissilePath` を読めば、カーソルと射線を Harmony なしで推定できる**。ただし、ゲームスレッドが書いている最中の値を読む競合がある。
- 入力の意味:
  - `"PointerOver"` は、最初の 1 回だけ捨てられる（`flag2` の初期値が真。`:313`、`:825-837`）。
  - NumPad5、Escape、`"RightClick"` は、`PopGameView` してから null を返す（`:842-847`）。
  - U、L、F1、`"Command:CmdLockUnlock"` は、ロックを切り替える（`:848-851`）。
  - `"Command:CmdMissileWeaponMenu"` は、入れ子の `Popup.PickOption` を開く（`:792-803`）。
  - F、Space、Enter、`"Command:CmdFire"`、`"LeftClick"` は、現在のカーソル位置で確定する（`:1080-1095`）。Combat からの呼び出しは `AllowVis.Any` を渡すので、ここでは `ShowFail` は出ない（`XRL.World.Parts/Combat.cs:270`、`:453`）。
  - 特殊な撃ち方（Mark、AltFire1〜4）は、技能がある場合だけ有効になる（`XRL.World.Parts/MissileWeapon.cs:979-984`、`:985-1079`）。

### 3.5 M5 Look

- 入口: `ShowLooker` は `currentMode=PickCells` を代入してから、`PushGameView("Looker")` を呼ぶ（`XRL.UI/Look.cs:405-408`）。`CmdLook` から入る（`XRL.Core/XRLCore.cs:1682-1697`）。
- 待ち方: `if (Keyboard.kbhit()) { getvk(...) } else { Keyboard.IdleWait(); }`（`XRL.UI/Look.cs:669-672`、`:897-900`）。
- プロンプト: `currentText` に `"Look [{i}/{n}] | "` と、操作の説明（Cancel、ロック、V±、Accept で interact、CmdWalk）を入れる（`:486-523`）。
- 見ている対象: public static の `Look.lookingAt` に、毎反復で書き込まれる（`:69`、`:667`）。
  - Modern では、対象が変わると、UI スレッドにツールチップの消去を `uiQueue.awaitTask` で**同期に**依頼する。その後、`gameQueue.executeTasks()` を回し、`QueueLookerTooltip` を積む（`:646-666`）。
  - 本文は `GenerateTooltipInformation(go)` で作られる。中身は DisplayName、Feeling、Difficulty、WoundLevel、LongDescription である（`:239-270`）。
  - ツールチップが消えるとき、`AfterLookedAt` / `LookedAt` を `gameQueue` に積む（`:360-402`）。
- 入力の意味:
  - `"LeftClick"` は、カーソルをマウスの x,y に**絶対座標で**動かす（`:673-685`）。
  - Space と `"Command:Interact"` は `Twiddle` を呼ぶ。これは入れ子のモーダルを開く（`:686-694`）。
  - Enter、NumPad5、Escape、`"RightClick"` は終了する（`:675-678`、`:695-698`、`:747-750`）。
  - F と `"Command:CmdFire"` は、そのセルを返して終了する（`:875-879`）。
  - `"Command:CmdWalk"` は、チュートリアル外なら `AutoAct` を設定して終了する（`:737-742`）。
  - ロックの切り替えは `:751-754` にある。
- 終了: `HideTooltips()` の中でも `uiQueue.awaitTask` を使う（`:918-922`、`:925-935`）。
- **注意:** `uiQueue.awaitTask` は、呼び出しスレッドが UI スレッドでなければ、`ManualResetEvent` で待つ（`QupKit/ThreadTaskQueue.cs:135-155`）。UI スレッドの側でゲームスレッドを同期で待つと、ここでデッドロックする。

### 3.6 M6 PickGameObjectScreen（`PickItem.ShowPicker` の Modern 分岐）

- 入口: Modern では、`PickItem.ShowPickerInternal` が、三つの Style（`SelectItemDialog`、`StoreItemDialog`、`GetItemDialog`）のどれでも `PickGameObjectScreen.show(...).Result` で待つ（`XRL.UI/PickItem.cs:36-41`、`:269-334`、特に `:285`、`:307`、`:319`）。
- `GetItemDialog` は、品物を選ぶと `EquipmentAPI.TwiddleObject` を呼ぶ。その後、`Regenerate()` で一覧を作り直し、`Reentry=true` で同じ画面を開き直す（`:283-304`、`:331-332`）。`wantToStore` のときは、TradeUI のコンテナ画面へ移る（`:289-293`）。
- `show` は、`NavigationController.SuspendContextWhile` 経由で `showScreen` を呼ぶ（`Qud.UI/PickGameObjectScreen.cs:265-268`、`XRL.UI.Framework/NavigationController.cs:156-178`）。
- `showScreen` は async で動く（`Qud.UI/PickGameObjectScreen.cs:213-263`）。
  - 最初の `await` までは、ゲームスレッドで走る。この区間で static の Actor / Container / Cell などを設定し、`menucomplete.TrySetCanceled()` を呼んでから、新しい `TaskCompletionSource` に入れ替え、`rawGameObjects` を埋める（`:215-228`）。
  - `await The.UiContext` の後は、UI スレッドで走る。`PushGameView("PickGameObject")`、`Show()`、`BeforeShow` と進み、`await menucomplete.Task` で待つ（`:231-253`）。`The.UiContext` の実体は `GameManager.uiSynchronizationContext` である（`XRL/The.cs:41`、`GameManager.cs:172`、`:869`）。
  - finally 節で `Hide()`、`PopGameView(bHard:true)`、`UIHold=false` を実行する（`Qud.UI/PickGameObjectScreen.cs:257-261`）。
- 一覧:
  - `listItems`（`List<PickGameObjectLineData>`）は、カテゴリの見出しと品物の行を並べたものである（`:49`、`:317-355`）。
  - `CategoryPriority` があるとき、既定では畳まれたカテゴリの品物が `listItems` に**入らない**（`:155-162`、`:324-327`）。全体を読むときは `rawGameObjects` を使う（`:47`、`:227-228`）。
  - カテゴリは `GetInventoryCategory()` で決まる（`:285-316`）。
  - 行の `quickKey` と `hotkeyDescription` はホットキーである（`:378-394`、`Qud.UI/PickGameObjectLineData.cs:6-35`）。
  - タイトルは `titleText` にある（`Qud.UI/PickGameObjectScreen.cs:65`、`:249`）。並べ方は `sortMode` で決まる（`:30-34`、`:89`）。
- 答え方:
  - `HandleSelectItem(PickGameObjectLineData)` は public である。type が Item なら `menucomplete.TrySetResult(new Result{item=go})` を呼び、Category なら開閉を切り替える（`:577-594`）。
  - `PickGameObjectLineData` は、`PooledFrameworkDataElement<T>` の `new()` 制約により、public の既定コンストラクタを持つ（`XRL.UI.Framework/PooledFrameworkDataElement.cs:5-16`）。したがって、`new PickGameObjectLineData().set(PickGameObjectLineDataType.Item, go: x)` で、一覧に出ていない品物（畳まれたカテゴリの中の品物）も直接渡せる。
- キャンセル: `Cancel()` は public である。`Hide()` を呼んでから `TrySetResult(default)` を呼ぶ（`Qud.UI/PickGameObjectScreen.cs:512-517`）。ここの `Hide` は一覧を解放するだけで、Task を取り消さない（`:501-510`）。PopupMessage とは異なり、`Hide` が先でも安全である。
- 複数選択: 画面としては**ない**。`GetItemDialog` にある TAKE_ALL だけは、`HandleMenuOption(TAKE_ALL)` から `APIDispatch.RunAndWaitAsync` 経由で `PickItem.TakeAll` を呼ぶ（`:445-474`、`XRL.UI.Framework/APIDispatch.cs:46-67`）。STORE_ITEM は `wantToStore` を返す（`Qud.UI/PickGameObjectScreen.cs:475-482`）。
- 入力: ホットキーは、UI スレッドの `Update` が `ControlManager.isCharDown(quickKey)` で拾う（`:601-633`）。ゲームスレッドは `.Result` で止まっているので、`Keyboard.PushKey` はこの画面に届かない。
- 入れ子: `CurrentGameView == "PickTarget"` の間は、自分の画面を alpha 0 で隠す（`:604-612`）。つまり、この画面の上に PickTarget が重なる経路がある。

### 3.7 M7 AskNumberScreen（ゲームパッド時だけ）

- `Popup.AskNumber` は、Modern では `AskNumberAsync(..., pushView: true).Result` で待つ（`XRL.UI/Popup.cs:1191-1206`）。
- `AskNumberAsync` の分岐:
  - `ControlManager.activeControllerType != Keyboard` のときだけ、`PushGameView("ModernPopupGamepadAskNumber")` を呼んでから `AskNumberScreen.show` を呼ぶ（`:1320-1340`）。
  - キーボードのときは、`PushGameView("ModernPopup:AskNumber")` のうえで、`NewPopupMessageAsync(..., askingNumber: true)` を呼ぶ（`:1341-1349`）。これはポップアップ系（別ファミリー）の担当である。
- `AskNumberScreen` 自身はビューを積まない（`Qud.UI/AskNumberScreen.cs:117-141`）。
  - `Current`、`Min`、`Max`、`numberText`、`messageText` は public である（`:25-33`）。
  - `Accept()` は `numberText.text` を `Convert.ToInt32` で読み、結果を立てる（`:213-220`）。
  - `Cancel()` は null を立てる（`:222-228`）。
  - `menucomplete` は protected である（`:19`）。

## 4. レシピ表

表の「UI タスク」は、`GameManager.Instance.uiQueue.queueTask(...)` で UI スレッドに積む処理を指す。「前提 P」は §3.0 の前提条件の式である。

| モーダル | wait_kind | trigger_for_probe | detect | read | answer | cancel | Harmony |
|---|---|---|---|---|---|---|---|
| M1 PickDirection | getvk（ブロック） | wish `clone`（`Wishing.cs:4109-4112`）。または `PushCommand("CmdMoveDirection")` / `"CmdAttackDirection"`（`XRLCore.cs:1223-1225`、`:1391-1393`） | P ∧ view=="PickTarget" ∧ mode==PickDirection | `PickTargetWindow.currentText`（Label + "[Select a direction]"） | `PushKey(KeyCode.Keypad1..9)`。自分を指すときは `Keypad5` か `PushCommand("CmdTargetSelf")`。1 回で確定する | `PushKey(KeyCode.Escape)` | 不要 |
| M2 PickTarget セル | kbhit+getvk（描画が回り続ける） | `PushCommand("CmdTarget")`（`XRLCore.cs:1826-1829`）。`CmdMoveTo` / `CmdAttackCell`（`:1232-1237`、`:1400-1405`） | P ∧ view=="PickTarget" ∧ mode==PickCells | `currentText`。カーソルは読めない（ブリッジが押し付けた値を真とする） | `PushMouseEvent("PointerOver",x,y)` ×2 → 空になるのを待つ → `PushCommand("CmdFire")`（または `KeyCode.F`）。範囲と可視性は事前に検証する | Escape か `Keypad5` か `CmdTargetSelf` | 不要（引数 Style/Range/VisLevel を知るには必要） |
| M3 FieldPicker | kbhit+getvk | Force Projector などの能力（`ForceProjector.cs:695`）。probe の wish は見つかっていない | P ∧ view=="PickTarget" ∧ mode==PickField | `currentText`（残りのマス数、Start/End の状態） | `PointerOver` ×2 で始点へ → `Keypad5` で開始 → `Keypad1..9` で 1 マスずつ → `Keypad5` で終了 | Escape（選択中は 1 回目で Clear、2 回目で Cancel） | 不要 |
| M4 射撃・投擲 | kbhit+getvk | `PushCommand("CmdThrow")`（`XRLCore.cs:1837-1839`）で、投擲武器を持っている場合 | P ∧ view=="FireMissileWeapon" | `currentText`。リフレクションで `MissileWeapon.PlayerMissilePath`（X1/3,Y1/3、Path） | `PointerOver` ×2 → `PushCommand("CmdFire")` | Escape か `Keypad5` | 不要。ピッカーを避けるなら、`Combat.ThrowWeapon(player, TargetCell: c)` / `FireMissileWeapon(player, TargetCell: c)` をゲームスレッドで直接呼ぶ |
| M5 Look | kbhit+getvk / IdleWait | `PushCommand("CmdLook")`（`XRLCore.cs:1682-1697`） | P ∧ view=="Looker" | `currentText`、`Look.lookingAt`、`Look.GenerateTooltipInformation(lookingAt)` | `PushMouseEvent("LeftClick",x,y)` でカーソルを移す → 読む →（セルを返すなら）`PushCommand("CmdFire")` | Escape か Enter | 不要 |
| M6 PickGameObject | `.Result` | Modern で、ゲームスレッドから `PickItem.ShowPicker(The.Player.Inventory.GetObjects())` を呼ぶ。または `Container` を開く（`Container.cs:153`） | `CurrentGameView=="PickGameObject"` ∧（UI スレッドで）`instance.isCurrentWindow()`。トークンは `menucomplete`（リフレクション） | `rawGameObjects`、`listItems`、`titleText.text`、`style`、`sortMode` | UI タスクで `instance.HandleSelectItem(new PickGameObjectLineData().set(PickGameObjectLineDataType.Item, go: x))` | UI タスクで `instance.Cancel()` | 不要 |
| M7 AskNumberScreen | `.Result` | ゲームパッドを有効にして `Popup.AskNumber` を呼ぶ | `CurrentGameView=="ModernPopupGamepadAskNumber"` | `messageText.text`、`Current`、`Min`、`Max` | UI タスクで `Current=v; numberText.SetText(v.ToString()); Accept()` | `Cancel()` | 不要 |

**getvk 型に共通の手順。** 次の順で進める。
1. UI タスクで前提 P を確かめる。
2. イベントは 1 個ずつ積む。
3. `Keyboard.KeyQueue.Count` と `HasMouseEvent()` が空になるのを確かめてから、次を積む。
4. 確定のイベントより後ろには、何も積まない（残ると、次の getvk ループに漏れる）。
5. ビューが元に戻るか、入れ子の Popup に変わったかを見る。

入れ子の `Popup.ShowFail` / `PickOption` / `Twiddle` が開くと、ビューが変わって入力が消える。ゲームスレッドはその間 Modern のポップアップで止まる。この状態は、ポップアップ系（F1 など）のレシピに引き継ぐ。

## 5. 主張一覧

- **C-F3-pickers-01（high）** PickDirection、PickTarget（ShowPicker と ShowFieldPicker）、MissileWeapon.ShowPicker、Look.ShowLooker は、どれもゲームスレッドの上で `Keyboard.getvk` を回して入力を待つ。`Keyboard.PushKey` / `PushMouseEvent` / `PushCommand` で積んだイベントは、`GetNextKey` が `MouseEventQueue` → `KeyQueue` の順に取り出すので、これらに届く。根拠: `XRL.UI/PickDirection.cs:54`、`XRL.UI/PickTarget.cs:164`、`:791`、`XRL.World.Parts/MissileWeapon.cs:790`、`XRL.UI/Look.cs:672`、`ConsoleLib.Console/Keyboard.cs:723-726`、`:967-1043`、`:1354-1358`。
- **C-F3-pickers-02（high）** 射撃と投擲は、PickTarget ではなく `MissileWeapon.ShowPicker` に入り、ビュー `"FireMissileWeapon"`（NavCategory "Targeting"、UICanvas "PickTargetFrame"）を積む。根拠: `XRL.World.Parts/Combat.cs:270`、`:453`、`XRL.World.Parts/MissileWeapon.cs:22`、`:300-303`。
- **C-F3-pickers-03（high）** 三つのビュー `"PickTarget"`、`"FireMissileWeapon"`、`"Looker"` は、どれも同じ `PickTargetWindow`（UICanvas "PickTargetFrame"）を表示する。区別は `CurrentGameView` と、static の `PickTargetWindow.currentMode` の組で行う。PickDirection、PickCells、PickField の三つが `"PickTarget"` を共有する。`currentMode` は入口で代入されるだけで、終了時には戻されない。根拠: `XRL.UI/PickTarget.cs:15`、`:86-87`、`:380-381`、`XRL.UI/PickDirection.cs:30-31`、`XRL.UI/Look.cs:20`、`:407-408`、`XRL.World.Parts/MissileWeapon.cs:22`、`:302-303`、`Qud.UI/PickTargetWindow.cs:8-19`。
- **C-F3-pickers-04（high）** UI スレッドの `UpdateView` は、`_ActiveGameView != _CurrentGameView` のとき `Keyboard.ClearInput()` を呼ぶ。`uiQueue.executeTasks()` は、同じ Update の中で `UpdateView` より先に走る。したがって、ピッカーに入った直後に積んだ入力は、UI スレッドがビューの変化を処理した時点で消えうる。積む前に `_ActiveGameView == CurrentGameView` を確かめる必要がある。根拠: `GameManager.cs:1573-1582`、`:2963`、`:3172-3183`、`:238`。
- **C-F3-pickers-05（high）** `bThreadFocus` が偽の間、`GameManager.Update` は `:3108-3113` で return する。この間 `UpdateView` は走らず、`_ActiveGameView` もピッカーのビューに追いつかない。`focused` が false から true に変わると、入力が消去される。根拠: `GameManager.cs:3108-3113`、`:404-418`、`:1920-1924`。
- **C-F3-pickers-06（high）** 入力の上限: `bCapInputBuffer`（`Options.CapInputBuffer`）が真のとき、`PushKey` はキューに 3 件以上あると黙って捨てる。`PushMouseEvent` も 3 件を超えると黙って捨てる。チュートリアルのポップアップ表示中は、どちらも捨てる。根拠: `ConsoleLib.Console/Keyboard.cs:777-796`、`:825-849`、`XRL.UI/Options.cs:1279-1286`、`TutorialManager.cs:311-319`、`:361-369`。
- **C-F3-pickers-07（high）** PickDirection の戻り値は、NumPad1〜9 が方角の文字列、NumPad5 と `"Command:CmdTargetSelf"` と `"Meta:Navigate"` が "."、Escape と `"RightClick"` が null である。どの経路でも `PopGameView(bHard:true)` してから返る。根拠: `XRL.UI/PickDirection.cs:56-99`、`:100-127`。
- **C-F3-pickers-08（high）** `PickTarget.ShowPicker` では、NumPad5、Escape、`"Command:CmdTargetSelf"` は**キャンセル**になり、確定にはならない。確定は、F、Space、Enter、`"Command:CmdFire"`、`"LeftClick"` のどれかで、**現在のカーソル座標**で行われる（LeftClick のマウス座標は使わない）。根拠: `XRL.UI/PickTarget.cs:809-812`、`:965-984`。
- **C-F3-pickers-09（high）** PickTarget.ShowPicker、ShowFieldPicker、MissileWeapon.ShowPicker は、最初の `"PointerOver"` を 1 回捨て、2 回目以降でカーソルをイベントの x,y に絶対座標で動かす。そのため、「同じ座標の PointerOver を 2 回積む」と、先に本物の PointerOver が来ていたかどうかに関係なく、同じ結果になる。根拠: `XRL.UI/PickTarget.cs:402`、`:792-808`、`:197-212`、`XRL.World.Parts/MissileWeapon.cs:313`、`:825-837`。
- **C-F3-pickers-10（high）** Look では、`"LeftClick"` がカーソルを x,y に直接動かす（最初の 1 回を捨てる処理はない）。F / `"Command:CmdFire"` はそのセルを返す。Enter、NumPad5、Escape は何も返さずに終了する。根拠: `XRL.UI/Look.cs:673-685`、`:695-698`、`:747-750`、`:875-879`。
- **C-F3-pickers-11（high）** PickTarget、FieldPicker、射撃のピッカーは、カーソル座標をローカル変数に持ち、外から読める static を持たない。Harmony なしでカーソルを知るには、ブリッジが押し付けた座標を真とする。射撃の場合は、リフレクションで private static の `PlayerMissilePath` を読む。根拠: `XRL.UI/PickTarget.cs:400-401`、`:405`、`:782-785`、`XRL.World.Parts/MissileWeapon.cs:80`、`:326-345`。
- **C-F3-pickers-12（medium）** 射撃のピッカーの `PlayerMissilePath` は、毎反復でカーソルまでの射線に再計算される。その `X1/3`、`Y1/3` と `Path.Last()` は、目標のセルを表す（ゲーム自身がそう解釈している）。根拠: `XRL.World.Parts/MissileWeapon.cs:345`、`XRL.World.Parts/Combat.cs:275`、`:458`、`XRL.World.Parts/MissilePath.cs:5-19`。
- **C-F3-pickers-13（high）** プロンプトの文字列は、どのピッカーでも Modern のとき static の `PickTargetWindow.currentText` に入る。Legacy で 0 行目に書かれていた情報と同じものである。根拠: `XRL.UI/PickDirection.cs:44-51`、`XRL.UI/PickTarget.cs:117-120`、`:747-750`、`XRL.UI/Look.cs:521-523`、`XRL.World.Parts/MissileWeapon.cs:773-776`、`Qud.UI/PickTargetWindow.cs:17`。
- **C-F3-pickers-14（high）** Look は、今見ている対象を public static の `Look.lookingAt` に毎反復で書く。本文は `Look.GenerateTooltipInformation(go)` で、Modern のツールチップと同じ中身を作れる。根拠: `XRL.UI/Look.cs:69`、`:667`、`:239-270`。
- **C-F3-pickers-15（high）** Look は、Modern で対象が変わるたびと終了時に、`uiQueue.awaitTask` で UI スレッドを同期で待つ。ブリッジの UI タスクがゲームスレッドの進行を同期で待つと、デッドロックする。根拠: `XRL.UI/Look.cs:652-658`、`:925-935`、`QupKit/ThreadTaskQueue.cs:135-155`。
- **C-F3-pickers-16（high）** ピッカーの確定が検証に失敗すると、入れ子の Modern ポップアップが開く。PickTarget（範囲外、非可視、未探索）では `Popup.ShowFail`、射撃（撃ち方メニュー）では `Popup.PickOption`、Look（Space）では `Twiddle` である。この間、ゲームスレッドは getvk ではなくポップアップで止まる。根拠: `XRL.UI/PickTarget.cs:967-978`、`XRL.World.Parts/MissileWeapon.cs:792-803`、`XRL.UI/Look.cs:686-694`。
- **C-F3-pickers-17（high）** Modern の `PickItem.ShowPicker` は、三つの Style のどれでも、`PickGameObjectScreen.show(...).Result` でゲームスレッドを止める。getvk を通らないので、`Keyboard.PushKey` はこの画面に届かない。画面のホットキーは、UI スレッドの `ControlManager.isCharDown` で拾われる。根拠: `XRL.UI/PickItem.cs:272-334`、`Qud.UI/PickGameObjectScreen.cs:601-633`。
- **C-F3-pickers-18（high）** `PickGameObjectScreen` は、UI スレッドに移った後で `PushGameView("PickGameObject")` を呼ぶ。`HandleSelectItem` の引数に、Item 型で `go` を設定した `PickGameObjectLineData` を渡すと、`menucomplete` に `Result{item=go}` が立ち、`.Result` が戻る。`PickGameObjectLineData` は public の既定コンストラクタで作れる。根拠: `Qud.UI/PickGameObjectScreen.cs:231-233`、`:253`、`:577-594`、`Qud.UI/PickGameObjectLineData.cs:6-35`、`XRL.UI.Framework/PooledFrameworkDataElement.cs:5-16`。
- **C-F3-pickers-19（high）** `PickGameObjectScreen.Cancel()` は `Hide()` の後で `TrySetResult(default)` を呼ぶ。この画面の `Hide` は Task を取り消さない。そのため、PopupMessage と違って、`Hide` が先でも答えが壊れない。根拠: `Qud.UI/PickGameObjectScreen.cs:501-517`。
- **C-F3-pickers-20（high）** 候補の全体は `rawGameObjects` にある。`listItems` は表示用で、`CategoryPriority` があると、既定で畳まれたカテゴリの品物を含まない。根拠: `Qud.UI/PickGameObjectScreen.cs:47`、`:155-162`、`:227-228`、`:317-337`。
- **C-F3-pickers-21（high）** PickGameObjectScreen に複数選択はない。GetItemDialog に限って、TAKE_ALL（`HandleMenuOption(TAKE_ALL)` → `APIDispatch.RunAndWaitAsync` で `PickItem.TakeAll`）と STORE_ITEM（`wantToStore`）がある。GetItemDialog では、1 件を選ぶと `TwiddleObject` の後に同じ画面を開き直す。根拠: `Qud.UI/PickGameObjectScreen.cs:413-435`、`:445-482`、`XRL.UI/PickItem.cs:283-304`、`:331-332`、`XRL.UI.Framework/APIDispatch.cs:46-67`。
- **C-F3-pickers-22（high）** `menucomplete` は protected で、`showScreen` の中の最初の await より前（ゲームスレッド）で、新しいものに入れ替わる。二度答えないためのトークンにするには、リフレクションで参照を読む必要がある。根拠: `Qud.UI/PickGameObjectScreen.cs:36`、`:225-226`、`:232`。
- **C-F3-pickers-23（high）** AskNumberScreen は、`activeControllerType != Keyboard` のときだけ使われる（ビュー `"ModernPopupGamepadAskNumber"`）。キーボードのときの AskNumber は、PopupMessage の入力欄（`askingNumber:true`）である。AskNumberScreen の `Accept()` は `numberText.text` を数値として読む。根拠: `XRL.UI/Popup.cs:1191-1206`、`:1320-1349`、`Qud.UI/AskNumberScreen.cs:117-141`、`:213-228`。
- **C-F3-pickers-24（medium）** 対象を取る操作の多くは、ピッカーを通さずにゲームスレッドから直接呼べる（効果が同じかどうかは推論による）。`Combat.FireMissileWeapon` は、`TargetCell` を与えるとピッカーを飛ばす。`Combat.ThrowWeapon` は、`TargetCell != null` なら飛ばす。`CmdTarget` の効果は、`Sidebar.CurrentTarget = cell.GetCombatTarget(...)` の代入である。根拠: `XRL.World.Parts/Combat.cs:236-238`、`:414-420`、`:478-482`、`XRL.Core/XRLCore.cs:1826-1834`。
- **C-F3-pickers-25（high）** PickTarget、FieldPicker、射撃のピッカーは、`bThreadFocus` が真の間、`kbhit` が待たないので、入力がなくても描画を回し続ける。getvk を `pumpActions` なしで呼ぶので、待っている間に `gameQueue` は回らない。Look だけは、対象の変化時と終了時に `gameQueue.executeTasks()` を呼ぶ。根拠: `ConsoleLib.Console/Keyboard.cs:938-954`、`:1017-1041`、`XRL.UI/PickTarget.cs:787-790`、`XRL.UI/Look.cs:658`、`:933`。

## 6. 実機でしか分からないこと

1. 前提 P を満たした後で `PushMouseEvent("PointerOver",x,y)` を 2 回、`PushCommand("CmdFire")` を 1 回積んだとき、`CmdTarget` のピッカーが (x,y) のセルを返すか。本物のマウスが画面上にあるときに干渉するか（`GameManager.cs:1180-1199`）。
2. 非フォーカスで `OptionMusicBackground` を有効にしたとき、`bThreadFocus` を周期的に書き戻せば、`UpdateView` と PickTargetWindow の表示が追従するか（05 C06 と共通）。
3. 非フォーカスのとき、`UnitySynchronizationContext` の継続（PickGameObjectScreen の `await` の後の `PushGameView`）が進むか。
4. エージェントの環境で `ControlManager.activeControllerType` がどの値になるか（AskNumber の経路が変わる）。
5. `PickTarget.Buffer` / `TextConsole.CurrentBuffer` の `imposterExtra` にある `"Prefabs/Imposters/TargetReticle"` を走査して、カーソルを読み戻せるか（読めても低信頼。描画中の競合がある）。
6. `MissileWeapon.PlayerMissilePath` を UI スレッドからリフレクションで読んだとき、値が一貫しているか。
7. Look の中で `LeftClick` → 待機 → `lookingAt` と進めたとき、`AfterLookedAt` が発火するか（05 C11(d)）。ツールチップの `onHideAction` 経由で `gameQueue` に積まれ、Look の中の `executeTasks` で走るはず（`XRL.UI/Look.cs:391-400`、`:658`）。
8. 一瞬で閉じて再び開くピッカー（`AutoAct.Setting = "ReopenMissileUI"`、`XRL.World.Parts/Combat.cs:466`）を、フレーム単位のポーリングで見落とさないか。

## 7. 未解決の問い

1. getvk 型のピッカーには、インスタンスを識別するトークンがない。同じビューとモードのピッカーが連続して開いたとき、別のものと区別する手段がない。Harmony なしでは、ビューの出入りの縁を見るしかない。確実にするには、`PickTarget.ShowPicker` / `PickDirection.ShowPicker` / `MissileWeapon.ShowPicker` / `Look.ShowLooker` に prefix を当て、連番と引数（Style、Radius、Range、VisLevel、Label）を static に記録する必要がある。
2. ピッカーの引数（Style、Range、VisLevel、ObjectTest）を読めないので、確定の前に検証（C-F3-pickers-16 の失敗を避けること）ができるのは、エージェント自身が開いたピッカー（呼び出しの場所が分かるもの）に限られる。能力が開くピッカーでは、`currentText` の Label から推測するしかない。
3. `GetItemDialog` の選択後に呼ばれる `EquipmentAPI.TwiddleObject` が開くモーダルの種類は、本書では確かめていない（ポップアップ系か、別の画面か）。
4. `"PickDirection"` の UIView は、どこから積まれるのか。文字列リテラルでは見つからなかったが、変数経由で積まれている可能性は残る。
5. PickGameObjectScreen の上に PickTarget が重なる経路（`Qud.UI/PickGameObjectScreen.cs:604-612`）は、どの操作で起きるのか。その間、`CurrentGameView` は `"PickTarget"` になるので、M6 の検出は偽になる。
