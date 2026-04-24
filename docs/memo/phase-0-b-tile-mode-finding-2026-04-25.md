# Phase 0-B — tile-mode による snapshot 空白化の発見 (2026-04-25)

## Status

`docs/superpowers/plans/2026-04-25-phase-0-b-screen-buffer-observation.md` Task 3 まで完了。構造的な受け入れ (BEGIN/END ペア生成、shape 80×25、catch 未発火) はパスしたが、snapshot 本文がほぼ空白で `@` も壁も視認できない。原因を decompile 上で同定したので、コード修正の前に証拠を凍結する。

## 観測された事実 (verbatim)

### build_log.txt (コンパイル + load-probe)

```
[2026-04-25T07:55:25] === LLM OF QUD ===
[2026-04-25T07:55:25] Compiling 2 files...
[2026-04-25T07:55:26] Success :)
[2026-04-25T07:56:30] [LLMOfQud] loaded v0.0.1 at 2026-04-24T22:56:30.0025960Z
```

Roslyn コンパイル成功、`IPlayerSystem.RegisterPlayer` が一度だけ発火していることを確認。

### Player.log 構造サマリ

```
BEGIN marker: 13
END   marker: 13
ERROR marker: 0
begin_take_action count= (per-10 counter): 1
```

すべての BEGIN に END が対応。catch ブロックは一度も発火せず、`TextConsole.GetScrapBuffer1(bLoadFromCurrent: true)` と `SnapshotAscii` は例外投げずに完走している。per-turn cost も実測で許容範囲内。

### turn=1 (プレイヤー操作直前)

```
INFO - [LLMOfQud][screen] BEGIN turn=1 w=80 h=25
<25 行すべて空白>
[LLMOfQud][screen] END turn=1
```

80×25 の形状は正しい。全セルがスペースで埋まっている。

### turn=5 (ステータスメッセージ表示中)

```
INFO - [LLMOfQud][screen] BEGIN turn=5 w=80 h=25
...
                                        The beauty! My stomach is in stirs.
...
[LLMOfQud][screen] END turn=5
```

テキスト UI 由来の 1 行 (status message) のみ ASCII で見えている。マップ本体は空白。

### turn=13 (マップ表示中)

```
INFO - [LLMOfQud][screen] BEGIN turn=13 w=80 h=25
...
                                         ÜÜÜÜ
                                        ÛÞÛÛÞ
                                        ÛÝÝÜÜ
                                         ÝÝ
...
[LLMOfQud][screen] END turn=13
```

CP437 ブロック文字 (Ü=0xDC, Û=0xDB, Þ=0xDE, Ý=0xDD) が 4 行だけ見える。プレイヤー `@` もフロア `.` も壁 `#` も見えない。

## 同定された原因

`decompiled/XRL.World/Zone.cs:5407-5418` — `Zone.Render` のセル処理ループ:

```csharp
ConsoleChar consoleChar = Buf.Buffer[j, i];
consoleChar._Tile = null;
RenderEvent renderEvent = Map[j][i].Render(consoleChar, ...);
consoleChar.SetColors(renderEvent);
consoleChar._Char = renderEvent.RenderString[0];   // ASCII glyph を先にセット
if (consoleChar._Tile != null)
{
    consoleChar.BackupChar = consoleChar._Char;     // ASCII を BackupChar へ退避
    consoleChar._Char = '\0';                       // tile で描画するため _Char をゼロ化
    consoleChar.HFlip = renderEvent.HFlip;
    consoleChar.VFlip = renderEvent.VFlip;
}
```

つまり CoQ は:

1. まず `_Char` に ASCII glyph (`@`, `#`, `.` など) を書く
2. セルが tile を持っていれば (`_Tile != null`)、`BackupChar` に ASCII を退避し、`_Char` を `'\0'` に書き換える
3. 描画エンジンは `_Char != '\0'` なら ASCII を、`'\0'` なら `_Tile` を表示する

現在の `SnapshotAscii` は `_Char` のみを読み、`'\0'` をスペースに変換している:

```csharp
// mod/LLMOfQud/LLMOfQudSystem.cs:63
char c = buf.Buffer[x, y].Char;
sb.Append(c == '\0' ? ' ' : c);
```

tile-mode では大多数のセルが `_Char == '\0'` になるため、snapshot が空白で埋まる。これが turn 13 の観測と完全に一致する。CP437 ブロック文字が残っていたのは、それらのセルに tile が割り当てられていないパターン (おそらくライティング / 視界条件による text-fallback) で、`_Char` がゼロ化されなかったため。

`BackupChar` の書き手は decompile 全体で `Zone.cs:5414` のみ (`grep -rn "\.BackupChar\s*=" decompiled/` で確認済み)。よって `_Char == '\0'` のとき `BackupChar` を読めば、tile-mode で隠された ASCII glyph を損失なく回収できる。

## 初期仮説と Codex review による却下

初期仮説は `SnapshotAscii` 内で `_Char == '\0'` のとき `cell.BackupChar` にフォールバックするだけで済むというものだったが、Codex の spec + quality review が重大な欠陥を発見した。

### Codex の指摘

`TextConsole.GetScrapBuffer1(bLoadFromCurrent: true)` は `ScrapBuffer.Copy(CurrentBuffer)` を呼び、内部的には全セルに対して `ConsoleChar.Copy` を適用する。その `ConsoleChar.Copy` の実装 (`decompiled/ConsoleLib.Console/ConsoleChar.cs:385-400`):

```csharp
public void Copy(ConsoleChar C)
{
    _Char = C._Char;
    _Tile = C._Tile;
    _Foreground = C._Foreground;
    _Background = C._Background;
    _TileForeground = C._TileForeground;
    _TileBackground = C._TileBackground;
    _Detail = C._Detail;
    HFlip = C.HFlip;
    VFlip = C.VFlip;
    BackdropBleedthrough = C.BackdropBleedthrough;
    WantsBackdrop = C.WantsBackdrop;
    soundExtra?.CopyFrom(C.soundExtra);
    imposterExtra?.CopyFrom(C.imposterExtra);
}
```

`BackupChar` はコピー対象外。よって ScrapBuffer 内の `ConsoleChar.BackupChar` は常にデフォルト (`'\0'`) となり、フォールバックを入れても tile-mode セルは回収できない。

### 修正方針 (pivot)

`GetScrapBuffer1` を廃止し、`BufferCS` lock を自前で取って `CurrentBuffer` を直接読む。ロック範囲は `SnapshotAscii` の 80×25 走査のみ。

```csharp
// LogScreenSnapshot 内
string body;
int w, h;
lock (TextConsole.BufferCS)
{
    ScreenBuffer cur = TextConsole.CurrentBuffer;
    if (cur == null)
    {
        body = "<null-current-buffer>\n";
        w = 0;
        h = 0;
    }
    else
    {
        w = cur.Width;
        h = cur.Height;
        body = SnapshotAscii(cur);
    }
}
// LogInfo は lock 外で呼ぶ (I/O を抱え込まない)
```

`SnapshotAscii` 内のセル読みは advisor の当初案どおり:

```csharp
ConsoleChar cell = buf.Buffer[x, y];
char c = cell.Char;
if (c == '\0') c = cell.BackupChar;
sb.Append(c == '\0' ? ' ' : c);
```

### 変更の性質

- **純粋な read**: `ConsoleChar` の書き換えも `_Tile` の無効化もしない
- **ゲーム挙動への影響ゼロ**: 視聴者に見える画面 (tile graphics) は従来通り
- **Options の ASCII/tile 切り替えに不変**: どちらのモードでも同じ出力形式
- **フォールバック連鎖**: `_Char` → `BackupChar` → ` ` (真の空セル)
- **Lock 範囲**: 80×25=2000 セルの field read + StringBuilder.Append のみ。I/O は lock 外。CoQ の `DrawBuffer` (`decompiled/ConsoleLib.Console/TextConsole.cs:149-153`) と同じ `BufferCS` を共有しているので、render との競合は想定内で CoQ 自身の lock 取り方と対称

## 2 度目の Codex review による再却下と最終的な pivot

上記「`CurrentBuffer` を lock 下で直接読む」方式も Codex (2 回目) が却下した。

### 追加で発見した事実

`TextConsole.DrawBuffer` の実装 (`decompiled/ConsoleLib.Console/TextConsole.cs:149-153`):

```csharp
lock (BufferCS)
{
    if (!bSkipIfOverlay || !GameManager.Instance.ModernUI)
    {
        CurrentBuffer.Copy(Buffer);   // ← ここ
        CurrentBuffer.ViewTag = GameManager.Instance?.CurrentGameView;
        ...
    }
    BufferUpdated = true;
}
```

`CurrentBuffer` そのものが各フレームで `Copy(Buffer)` され、そのコピーは `ScreenBuffer.Copy` → `ConsoleChar.Copy` 経由で行われる (`decompiled/ConsoleLib.Console/ScreenBuffer.cs:291-308`)。つまり `CurrentBuffer` に到達した時点で `BackupChar` はすでに失われている。

render 実行後に tile-mode の ASCII を得られる buffer は、`Zone.Render` に渡された **source buffer** (`DrawBuffer` の引数) だけ。`CurrentBuffer` はその source を copy した後の像であり、BackupChar を持たない。

### 最終方針: AfterRenderCallback で source buffer にアクセス

`XRLCore.RegisterAfterRenderCallback(Action<XRLCore, ScreenBuffer>)` (`decompiled/XRL.Core/XRLCore.cs:624-626`) が source buffer を呼び出し元に渡す公開 API として存在する。呼び出しポイントは `Zone.Render` 直後・`DrawBuffer` 呼び出し前 (`decompiled/XRL.Core/XRLCore.cs:2347-2351, 2380-2383, 2423-2426`)。ここの `ScreenBuffer` は `Zone.Render` が BackupChar を書き込んだ状態のまま。

### 実装の最小差分

1. `HandleEvent(BeginTakeActionEvent)` は turn counter を更新し、**snapshot 要求 flag** (request turn number) を立てるだけ。ここでは log を書かない。
2. `AfterRenderCallback` (新規静的メソッド) は:
   - flag が立っていなければ no-op (renderごとに呼ばれるため cost を避ける)
   - 立っていれば flag をクリアし、受け取った source buffer に対して `SnapshotAscii` を走らせて `MetricsManager.LogInfo` に書く
3. `RegisterPlayer` で一度だけ `XRLCore.RegisterAfterRenderCallback(AfterRenderCallback)` を呼ぶ。`_afterRenderRegistered` 静的フラグで多重登録を防ぐ。
4. `GetScrapBuffer1` も `TextConsole.CurrentBuffer` の直接読みも廃止。`BufferCS` lock も使わない (callback は render パイプラインの一部として同期的に走るので追加 lock 不要)。

### スレッド / ライフサイクルに関する注意

- `BeginTakeActionEvent` は game スレッド、`AfterRenderCallback` は render を駆動するスレッド (多くは UI スレッド)。request flag は `volatile int`。writer は HandleEvent、reader / clearer は callback。race は (多重 BeginTakeAction が 1 render の間に起きた場合) 中間の turn の snapshot を落とすだけで、壊れはしない。Phase 0-B の観測目的ではこのロス率で充分。
- `XRLCore.RegisterAfterRenderCallback` は `AfterRenderCallbacks.Add` するだけで `Clear` の API は見当たらない。`IPlayerSystem` は `[Serializable]` なのでセーブ/ロードを跨ぐと再構築されるが、callback リストは静的。`_afterRenderRegistered` は static なので同一プロセス内で一度だけ登録される。ミドセッションの mod reload が起きる場合 (Phase 0-A で保留している Task 7) は別途対応が必要だが、0-B の exit criteria ではそれまでの単回起動で充分。
- callback はフレーム毎に呼ばれるが、flag=0 のときは早期 return のみ。cost はほぼゼロ。

## 明示的に Phase 0-B のスコープ外とするもの

1. **turn 1-4 の完全空白**: プレイヤー操作に先行する `BeginTakeActionEvent`。character creation / map 初期生成時点では `ScreenBuffer` に Zone が描画されていない可能性が高い。0-B の受け入れは「プレイヤー操作中の snapshot が読める」ことで充分なので、以降のフェーズで調査。
2. **色情報 (`ForegroundColor` / `BackgroundColor` / `_TileForeground`)**: 0-B は ASCII テキストのみ。色は 1-X 以降。
3. **tile の解釈 (`_Tile` 文字列)**: 同上、スコープ外。
4. **1 ターン遅延 (Pivot branch)**: plan で定義された Pivot は「`@` は見えるが 1 タイル遅れる」ケース。今回は `@` 自体が見えない rendering-mode 問題なので Pivot の発動条件を満たさない。Pivot は保留。

## 次アクション

1. この memo を commit せずに保管 (commit policy より user 明示要求まで待機)
2. `SnapshotAscii` に上記 1 箇所修正を適用
3. Codex で spec + quality review
4. user が CoQ を再起動し Player.log を再確認
5. `@` + 壁 + フロアが見えたら Task 8 (exit memo) + Task 9 (PR) へ進む

## 参照

- Plan: `docs/superpowers/plans/2026-04-25-phase-0-b-screen-buffer-observation.md`
- 現行ソース: `mod/LLMOfQud/LLMOfQudSystem.cs:46-69` (`SnapshotAscii`), `:77-95` (`LogScreenSnapshot`)
- CoQ 描画パイプライン: `decompiled/XRL.World/Zone.cs:5388-5439`
- `ConsoleChar` スキーマ: `decompiled/ConsoleLib.Console/ConsoleChar.cs:65` (`BackupChar`), `:67` (`_Char`), `:116` (`Char` property)
- `BackupChar` writer 単一性: `grep -rn "\.BackupChar\s*=" decompiled/` — Zone.cs:5414 のみ
