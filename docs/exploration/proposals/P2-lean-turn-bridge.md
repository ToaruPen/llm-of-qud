# P2: Lean Turn Bridge — v1 から工程を引き、LLM を足す

| 項目 | 内容 |
|---|---|
| 提案 | P2（探索フェーズの設計案の 1 つ。採否は未決定） |
| 作成 | Opus 5.5 worker、2026-09-25 |
| レンズ | 「v1 minus the process, plus the LLM」。v1 が実証した CTA 同期の判断境界、WebSocket ブリッジ、ScreenBuffer と状態の取得、wake の仕組みは残す。そのうえで、day 3 に実物の LLM が 1 手を打てる最小構成まで削る |
| 引用基準 | `stable/` は `~/Dev/coq-decompiled_stable` を指す。**現在の stable は `AssemblyVersion("2.0.211.56")`**（`stable/Properties/AssemblyInfo.cs:8`）。01 と 04 の「stable = 2.0.211.50」は、同日 17:14 に stable が更新される前の記述である。いまの stable の行番号は、03 が `NEW/` として引いた行番号と一致する（付録 A で確認） |
| 表記 | **[推論]** は静的な読解から導いた主張。**[要実測]** はランタイムのプローブで確かめるまで前提として扱わない主張 |
| 証拠の出典 | 01〜04 の探索レポート（`docs/exploration/0*.md`）。本書で「01 K19」のように書いたものは、そのレポートの項目番号を指す |

---

## 0. TL;DR

1. **判断は CTA で行い、実行は PlayerTurn に任せる（decide-in-CTA, execute-in-PlayerTurn）。**
   - CTA ハンドラはゲームスレッドを止めたまま Brain と対話する。観測と、ターンを消費しない問い合わせには、ゲームスレッド上で答える。
   - LLM が選んだ行動は `Keyboard.PushCommand` で注入する。これは人間のキー入力と同じ `Command:` イベントの経路で、PlayerTurn の switch がそのまま処理する（`stable/XRL.Core/XRLCore.cs:779, 981`）。
   - ハーネス側に移動や待機のロジックを再実装しないので、行動の忠実度と主張の透明性が上がる。ステータスバーなど HUD の更新も正しく走る。
   - PlayerTurn 経路のプローブが失敗した場合に備え、v1 で実証済みの CTA 直接 `Move`/`AttackDirection`/`PassTurn` をフォールバックとして残す。
2. **モーダルは Harmony を使わずに扱う。**
   - ゲームスレッドが `Popup.cs:908` の `Task.Wait()` で止まっている間は、ブリッジスレッドが `uiQueue` 経由で UI スレッド上の `PopupMessage` を読み、`OnActivateCommand` で答える。
   - Rosetta は不要で、arm64 ネイティブのまま動く。
3. **Brain は Python（uv）で書く。**
   - ツールループ、記憶、コスト階層、証拠の台帳を Brain が持つ。
   - ゲームとの接続は v1 と同じ構成で、mod がクライアント、Brain がサーバー（`ClientWebSocket` → `ws://127.0.0.1:4040`）。
4. **観測は 1 回の決定あたり推定 1.3〜2.2k トークン。** 中身は 80×25 の glyph マップ、構造化した状態、メッセージの差分で、画像は使わない。
5. **3 週間の最初のマイルストーンは、day 3 の「LLM による最初の自律ターン」。** その前に 7 本のランタイムプローブ（合計 1〜1.5 日）を回す。
6. **主張の形。**
   - 「CoQ 2.0.211.56 を、テキスト観測だけで、ゲーム内の行動をすべて LLM が選んでエンディング（`EndGame.IsAnyEnding`）まで進めた」。ハーネス由来の入力は台帳ですべて開示する。
   - 「最初」かどうかは未検証である。「SOTA モデルならクリアできて当然」とする根拠はない（§8.5）。

---

## 1. 概要と狙い

### 1.1 何を最適化するか

| 最適化の対象 | 理由と根拠 |
|---|---|
| **LLM がプレイを始めるまでの距離** | v1 は観測、ブリッジ、envelope、冪等性まで作ったところで、LLM を一度も呼ばずに止まった（01 TL;DR 1-2、§5.2）。P2 はまず day 3 に LLM に 1 手を打たせ、その後の機能はすべてこのループに足していく |
| **行動の忠実度** | 行動は人間の入力と同じ経路（`Command:X` → `XRLCore.cs:754-780` → switch `:981`）を通る。`CmdWait` の中身（消火、探索、`PassedTurn` イベント。`XRLCore.cs:1517-1541`）や `CmdAutoExplore` の世界地図チェック（`:1920-1925`）などを、ハーネス側で再現しなくてよい |
| **主張の検査可能性** | LLM 以外が発した入力は、すべて台帳の決まった種類のどれかになる（§8.3）。人間の入力も検出して記録する |
| **部品の少なさ** | C# は 7 ファイルで約 1,500 行、Python は約 1,500 行（目安）、Harmony のパッチは 0 件。プロセスの成果物は、この提案書、プローブのログ 1 枚、コミットメッセージだけにする |

### 1.2 v1 から残すもの、捨てるもの、変えるもの

| 区分 | 対象 | 根拠 |
|---|---|---|
| **残す** | CTA を判断境界にする（BTA ではない）。`PreventAction` は保険としてだけ使う | 01 K14、`stable/XRL.Core/ActionManager.cs:789-791` |
| 残す | 専用スレッドの `ClientWebSocket` ブリッジ（p95 1 ms） | 01 K19 |
| 残す | AfterRender で `_Buffer` を読み、`_Char` → `BackupChar` → 空白の順に glyph を復元する | 01 K5-K7、`stable/ConsoleLib.Console/ConsoleChar.cs:392-420` |
| 残す | wake の仕組み（`SkipPlayerTurn` と `KeyEvent.Set`） | 01 K20、`stable/XRL.Core/XRLCore.cs:2390-2396` |
| 残す | `[NonSerialized]` のソケットとスレッドを `AfterLoad` で作り直す | 01 K18 |
| 残す | `SnapshotState.cs` にある「どのフィールドをどの API で取るか」の知識 | 01 §4.1 |
| **捨てる** | 500 ms の timeout と、timeout 時に heuristic の explore にフォールバックする仕組み | 実物の LLM をつなぐと毎ターン timeout して東へ歩き続ける（01 §5.2-4） |
| 捨てる | `ToolRouter`、terminal の冪等性層、`session_epoch`、supervisor の骨格 | 中身が no-op だった（01 TL;DR 2） |
| 捨てる | ADR、decision record、仕様凍結、grep による静的契約テスト | 摩擦の主因（01 §3.3、§3.5） |
| 捨てる | 手書きの JSON パーサ 2 個 | Newtonsoft 13 が参照できればそれに置き換える（プローブ PR0） |
| **変える** | 実行経路を「CTA 内での直接 API」から「PlayerTurn への `PushCommand`」に変える | §3.1。CTA 直接呼び出しは HUD の更新を飛ばす（§3.1 の表）。M1 のフォールバックとしては残す |

### 1.3 意図的に諦めるもの

- **Harmony。**
  - これにより、次の 3 つを諦める。
    1. ゲームスレッドで `Popup.*` の引数を傍受すること。
    2. `XRLCore.cs:737-740` のフォーカス待機ループを無効化すること。
    3. `AutoAct.TryToMove` を書き換えること。
  - 見返りは、Rosetta と `0Harmony.dll` の差し替えが要らなくなり、ゲームの更新で壊れる面が小さくなることである（04 §4.6）。
- **ゲーム内 MCP サーバー（RimMolt 型）。**
  - CoQ はターン制で、1 手ごとにゲームスレッドを止めて対話する。そのため、ループの持ち主は外部の Brain にした方が単純になる。
  - Claude Code から MCP で操作したい場合は、Brain 側の薄いファサードとして後から足せる（§6.4）。一次クライアントにはしない。
- **キャラクター作成とメインメニューの自動化。** 人間が操作し、その事実を台帳に記録する（§8.3）。
- **軌跡の再現性。** 戦闘などで使われる静的 RNG はシードされない（01 K27、`stable/XRL.Rules/Stat.cs:26-36`）。再現できるのはハーネスの構成であって、軌跡ではない。
- **取引の自動化。** week 3 まで後回しにする。
- **同じプロファイルでの QudJP との共存。** 観測テキストは英語に固定する。
- **Legacy UI での運用。** Modern UI を既定にする。Legacy UI（`OptionModernUI=No`）は、§4 のモーダル経路が破綻したときの Plan B として残す。

---

## 2. 観測

### 2.1 使う表面

すべてゲームスレッドで読む。例外はモーダルの状態（§4、UI スレッド）だけである。

| # | 内容 | API | 引用 |
|---|---|---|---|
| O1 | glyph マップ（80×25） | `XRLCore.RegisterAfterRenderCallback` で受け取った `_Buffer` の各セルを、`_Char` → `BackupChar` → `' '` の順に読む | `stable/XRL.Core/XRLCore.cs:652-655`（登録）、`:2506-2509`（呼び出し。引数は常に static `_Buffer`）、`stable/ConsoleLib.Console/ConsoleChar.cs:392-420`（tile モードでは `_Char='\0'`、`BackupChar=RenderString[0]`） |
| O2 | 可視と探索済みのフラグ | `Zone.GetVisibility(x,y)` / `GetExplored(x,y)` | `stable/XRL.World/Zone.cs:7245, 7255` |
| O3 | 可視エンティティ | `Cell.GetObjects()` をたどり、`IsVisible()` と `IsHostileTowards(player)`、`ShortDisplayNameStripped` を読む | `stable/XRL.World/GameObject.cs:10458, 11424`、`:669-753` |
| O4 | プレイヤーの状態 | `hitpoints`/`baseHitpoints`、Statistics（AV/DV/MS/QN/AP/SP/MP/XP/Level）、`Stomach.FoodStatus`/`WaterStatus`、`_Effects`、`GetFreeDrams`、積載重量 | `stable/XRL.World/GameObject.cs:1176-`、`stable/XRL.World.Parts/Stomach.cs:87, 104`。サイドバーが読んでいる一覧は `stable/Qud.UI/PlayerStatusBar.cs:310-422` |
| O5 | メッセージの差分 | `XRLCore.RegisterNewMessageLogEntryCallback`（push 型、重複登録は防止される）。色コードは `ColorUtility.StripFormatting` で除く | `stable/XRL.Core/XRLCore.cs:657-663`、`stable/XRL.Messages/MessageQueue.cs:138-148` |
| O6 | 起動アビリティ | `ActivatedAbilities` の各 `ActivatedAbilityEntry` の `Command`、`DisplayName`、`Cooldown`、`IsUsable` | `stable/XRL.World.Parts/ActivatedAbilityEntry.cs:40, 42, 259, 290` |
| O7 | クエスト | `XRLGame.Quests` と各 Quest の step | `stable/XRL/XRLGame.cs:145-148`、`stable/XRL.World/Quest.cs:11-113` |
| O8 | AutoAct の状態と停止理由 | `AutoAct.IsActive()`、`GetDescription()`。停止時のメッセージは O5 で拾う | `stable/XRL.World.Capabilities/AutoAct.cs:114, 405, 419` |
| O9 | Look の本文（要求時のみ） | `Look.GenerateTooltipContent(GameObject)` | `stable/XRL.UI/Look.cs:239` |
| O10 | 所持品と装備（要求時のみ） | `Inventory.Objects`、`Body.GetEquippedParts()`、`EquipmentAPI.GetInventoryActions` | `stable/Qud.API/EquipmentAPI.cs:378` |
| O11 | エンディング到達 | `EndGame.IsAnyEnding` | `stable/XRL.World.Conversations.Parts/EndGame.cs:103-113` |
| O12 | 開いているモーダル | §4（UI スレッドの `PopupMessage`、`GameManager.CurrentGameView`、`PickTargetWindow.currentMode`） | §4 |

**使わないもの。**

- Modern UI での HUD、ログ、ポップアップの ScreenBuffer 表示。これらは ScreenBuffer に描かれない（03 §1.3）。
- UAP。ゲームのコードから参照されていない（03 §1.4）。
- ミニマップ。色の情報しか持たない。
- スクリーンショット。オーナーの固定方針で使わない。

### 2.2 取得のタイミング

CTA ハンドラに入ったら、LLM に問い合わせる前にゲームスレッドで `The.Core.RenderBase()` を 1 回呼ぶ。これは、エネルギーが 1000 未満のプレイヤーに対して ActionManager 自身が呼んでいるのと同じ呼び出しである（`stable/XRL.Core/ActionManager.cs:1618-1621`）。呼ぶ効果は 3 つある。

1. **視界マップを作り直す。** `ClearVisiblityMap` → `AddVisibility(player, radius)` が走る（`stable/XRL.Core/XRLCore.cs:2486-2493`）。これで、03 §2.2 が指摘した「描画前に `IsVisible` を読むと 1 フレーム古い」という問題が消える。
2. **glyph マップを最新にする。** AfterRender コールバックが走り、O1 が更新される（`:2506-2509`）。
3. **配信画面を最新にする。** LLM が考えている間も、画面は現在の状態を映す。

`RenderBase` の先頭は、CoreThread 上で `gameQueue.executeTasks()` も実行する（`:2600-2605`）。副作用は、ゲーム本体の描画 1 回分と同じである。

### 2.3 LLM に渡す表現

通信路では JSON を使う（ログとリプレイのため）。LLM には、Python 側でこの JSON から組み立てたテキストを渡す。テキストの並び順は rimagent の「変化の大きい情報から順に」に従う（02 P5）。

1. 警告
2. 直前の行動の結果
3. 新しいメッセージ
4. 周囲のエンティティ
5. プレイヤーの状態
6. マップ
7. 能力とクエスト

座標は、絶対座標 `[x,y]` と相対表現 `E5 N1` を併記する（02 P6、A5）。`goto` は座標、エンティティ ID、地物 ID のどれでも受け付ける（§3.2）。

#### 実例: Joppa、1 ターン分（数値と glyph は説明用の架空値）

通信路の JSON（抜粋。`map` は 25 行のうち 7 行だけ示す）:

```json
{
  "type": "decision", "seq": 212, "game_turn": 1187,
  "zone": {"id": "JoppaWorld.11.22.1.1.10", "name": "Joppa", "world_map": false},
  "alerts": ["hostile_visible"],
  "last_action": {"act": "move E", "cmd": "CmdMoveE", "outcome": "energy_spent",
                  "moved": [1, 0], "hp_delta": 0, "turns": 1},
  "messages": ["You see a snapjaw scavenger."],
  "player": {"pos": [37, 14], "hp": [16, 19], "level": 2, "xp": [310, 440],
             "av": 4, "dv": 7, "ms": 100, "qn": 100, "ap": 0, "sp": 50, "mp": 0,
             "food": "Sated", "water": "Quenched", "drams": 27, "weight": [98, 250],
             "effects": []},
  "entities": [
    {"id": "e17", "name": "snapjaw scavenger", "glyph": "s", "pos": [42, 13],
     "rel": "E5 N1", "hostile": true, "wound": "Uninjured", "adjacent": false},
    {"id": "e4", "name": "Mehmet", "glyph": "@", "pos": [35, 12],
     "rel": "W2 N2", "hostile": false, "talk": true}
  ],
  "here": ["witchwood bark"],
  "features": [{"id": "f2", "glyph": ">", "name": "stairway down", "pos": [60, 20]}],
  "abilities": [{"cmd": "CommandSprint", "name": "Sprint", "cd": 0, "usable": true}],
  "autoact": null,
  "quests": [{"name": "What's Eating the Watervine?", "step": "Travel to Red Rock"}],
  "map_origin": [0, 0],
  "map": ["...", "          ####.....~~~~~....  ", "          #..@.....~~~~~....s ",
          "          #........~~~~~.....  ", "..."]
}
```

LLM に渡すテキスト（Python がレンダリングする）:

```
[ALERT] hostile visible
[LAST] move E -> moved E, 1 turn, HP 16/19 (no change)
[MSG] You see a snapjaw scavenger.
[NEAR]
  e17 snapjaw scavenger (s) HOSTILE  E5 N1 [42,13]  Uninjured
  e4  Mehmet (@) friendly, can talk   W2 N2 [35,12]
[HERE] witchwood bark
[YOU] Joppa [37,14] Lv2 XP 310/440 HP 16/19 AV4 DV7 MS100 QN100
      Sated/Quenched  27 drams  98/250 lb  SP 50 (unspent)
[MAP] rows 11-17 of 25 (full map every decision; x→ 0..79)
11|          ####.....~~~~~....
12|          #..@.....~~~~~....s
...
[ABIL] CommandSprint(Sprint) ready
[QUEST] What's Eating the Watervine? -> Travel to Red Rock
[FEAT] f2 stairway down [60,20]
```

LLM が返すもの（ツール呼び出し 1 回）:

```json
{"tool": "act", "action": "attack_nearest", "say": "スナップジョーが近い。村の中で先に叩く。"}
```

`say` は配信のオーバーレイに出す 1 行のナレーション（§9）で、ゲームには影響しない。

### 2.4 サイズの見積り [要実測: プローブ PR6]

| 部分 | 見積り | 根拠 |
|---|---|---|
| マップ（80×25 に行番号） | 約 600〜1,200 トークン | 約 2,100 文字。未探索は空白で、`.` の連続は圧縮して符号化されやすい **[推論]** |
| 構造化部分（エンティティ 5〜15 体、メッセージ 3〜8 行） | 約 400〜900 トークン | 上の例は約 250 トークン **[推論]** |
| **1 回の決定あたり** | **約 1.3〜2.2k トークン** | 実測はトークナイザで行う（PR6） |
| 直近の履歴（15 決定分の要約行） | 約 1.5〜3k | §7.2 |
| システムプロンプト、規約、ノートの上位節 | 約 10〜15k（キャッシュ対象） | Manual.xml は約 6k（04 §3.1） |

マップは毎回全体を渡す。ゾーンは 80×25 しかなく、戦略的な判断（出口、未探索の方角）に全体が要る。コストがきつい場合の第一の手段は、ゾーンが変わらず新しく探索したセルもない決定で、マップを「前回と同じ」の 1 行に置き換えることである。

### 2.5 tile モードと Modern UI への依存

- **tile モード。**
  - 観測は tile モードでも text モードでも同じになる。tile モードでは `BackupChar` から glyph を復元するからである（O1）。
  - 配信では tile の見た目を使い、LLM には glyph を渡す。
  - 未検証の端のケースとして、`OverlayTile` と、複数オブジェクトが重なったセルがある（03 U9）。PR6 で両モードのダンプを比べる。
- **Modern UI。**
  - Modern UI では、ScreenBuffer にはマップしか入らない（03 §1.3）。P2 は HUD とメッセージを状態 API から取るので、Modern UI でも Legacy UI でも観測は変わらない。
  - Modern UI に依存するのはモーダルの読み取りだけである（§4）。
- **glyph の正規化。**
  - `_Buffer` の文字は CP437 の値である。Python 側で CP437 → Unicode の表で変換し、罫線などは代表の文字に寄せる。
  - 変換表はゲームの `Sidebar.FromCP437` に合わせる。

---

## 3. 操作

### 3.1 実行器は 3 種類（M1 のフォールバックを入れて 4 種類）

| 実行器 | 経路 | 使う場面 | 引用 |
|---|---|---|---|
| **E1: command ID を PlayerTurn に注入する（既定）** | CTA ハンドラが `Pending` にコマンドを置き、エネルギーを使わずに `true` を返す。→ ActionManager の `:798` を通って `PlayerTurn()` に入る（`:1611`）。→ `ClearMouseEvents`（`XRLCore.cs:734`）の後に EndPlayerTurn コールバック（`:2358`）が走り、そこで `Keyboard.PushCommand(cmd)` を呼ぶ。→ `IdleWait`（`:2392`）が `KeyEvent.Set` で起き、次の反復で `Command:` として取り出され（`:779`）、switch（`:981`）で実行される | 移動、攻撃、待機、自動探索、goto、`CmdUse{Dir}`、`CmdGetFrom{Dir}`、会話と開扉（ピッカーつき）、能力コマンド | `stable/XRL.Core/XRLCore.cs:690-780, 2355-2396`、`stable/ConsoleLib.Console/Keyboard.cs:723-726, 825-850` |
| **E2: CTA 内でゲーム関数を直接呼ぶ** | ステータス画面が呼ぶのと同じ static 関数を、ゲームスレッドで呼ぶ | 使う、食べる、飲む、読む。装備と外し、捨てる。能力値、スキル、変異の購入 | `stable/XRL.World/InventoryActionEvent.cs:110`、`stable/Qud.API/EquipmentAPI.cs:439-501`、`stable/XRL.UI/StatusScreen.cs:62, 652`、`stable/XRL.UI/SkillsAndPowersScreen.cs:141` |
| **E3: モーダルに答える** | UI スレッドの `PopupMessage.OnActivateCommand`、またはピッカーへの `Keyboard.PushKey` | 選択肢、Yes/No、会話、文字入力、方向と対象 | §4 |
| E0: CTA 内で直接行動する（M1 のフォールバック） | `Move(dir)` / `AttackDirection(dir)` / `PassTurn()` と 3 層のドレイン | PR1 が失敗した場合の M1 だけ | 01 K13、`stable/XRL.World/GameObject.cs:16234, 18397, 18058` |

**E1 を既定にする理由。** CTA で直接行動すると、PlayerTurn の中でしか起きない処理を飛ばす。

| 飛ばされる処理 | 行 | 影響 |
|---|---|---|
| `CallBeginPlayerTurnCallbacks()` と EndPlayerTurn コールバック | `XRLCore.cs:693, 2358` | `PlayerStatusBar`、`NearbyItemsWindow`、`AutogotItems` がこれに登録している（`Qud.UI/PlayerStatusBar.cs:276-277` ほか）。**HUD が更新されなくなるので、配信で致命的** |
| `Messages.BeginPlayerTurn` / `EndPlayerTurn` | `XRLCore.cs:710, 2366` | メッセージのターン境界 |
| HP 警告のポップアップ | `:748-751` | ゲーム仕様どおりの警告が出ない |
| `CmdWait` の中身（消火、Search、`PassedTurn`） | `:1517-1541` | `PassTurn()` の直接呼び出しは、これを再現しない |
| `EnqueuePlayerCell` / `CheckPlayerLocations` | `:2387-2388` | 静的に読んだ限り、デバッグ用の整合性チェックで、影響はない（`stable/XRL.World/GamePlayer.cs:32-58`）。`RunCommands` もセグメントごとに別途実行されている（`ActionManager.cs:1672`） |

v1 の 2,399 ターンの受け入れ試験は東西の往復移動だけだったので、飛ばしても無害なことの証明にはならない。E1 はこれらをすべてゲーム自身に任せられる。

**E1 の代償。** PlayerTurn のフォーカス待機（`XRLCore.cs:737-740`）と入力クリア（`:734`）の影響を受ける。対策は §5.6。

### 3.2 行動文法（LLM が `act` ツールに渡す文字列）

1 回の `act` で 1 行動である。文法は小さく保ち、構文エラーは `rejected: parse_error` とヒントを返す（02 §3.4）。

```
action   := move | attack | wait | explore | goto | stairs | use | get | talk | open
          | ability | item | equip | unequip | drop | raise | learn | buy_mutation | cmd
DIR      := N | S | E | W | NE | NW | SE | SW
move     := "move " DIR                 -> CmdMove{DIR}
attack   := "attack " DIR               -> CmdAttack{DIR}
          | "attack_nearest"            -> CmdAttackNearest
wait     := "wait" | "wait 20" | "wait 100" | "rest"
                                        -> CmdWait | CmdWait20 | CmdWait100 | CmdWaitUntilHealed
explore  := "explore"                   -> CmdAutoExplore            (AutoAct "?")
goto     := "goto " (X "," Y | ENT_ID | FEAT_ID)
                                        -> CmdMoveToBorder:X,Y       (AutoAct "M x,y")
stairs   := "up" | "down"               -> CmdMoveU | CmdMoveD
use      := "use " DIR                  -> CmdUse{DIR}               (隠しコマンド)
get      := "get" | "get " DIR          -> CmdGet | CmdGetFrom{DIR}  (隠しコマンド)
talk     := "talk " DIR                 -> CmdTalk + PickDirection(DIR)   (マクロ)
open     := "open " DIR                 -> CmdOpen + PickDirection(DIR)   (マクロ)
ability  := "ability " ABIL_CMD [DIR]   -> ABIL_CMD (switch の default で CommandEvent.Send)
                                           + 方向ピッカーが出たら DIR で答える
item     := "item " ITEM_ID " " VERB    -> E2: InventoryActionEvent.Check(player, player, item, VERB)
equip    := "equip " ITEM_ID            -> E2: EquipmentAPI.EquipObjectToPlayer
unequip  := "unequip " ITEM_ID          -> E2: EquipmentAPI.UnequipObject
drop     := "drop " ITEM_ID             -> E2: EquipmentAPI.DropObject
raise    := "raise " STAT               -> E2: StatusScreen.BuyStat(player, STAT)
learn    := "learn " SKILL_OR_POWER     -> E2: SkillsAndPowersScreen.SelectNode(node, player)
buy_mutation := "buy_mutation"          -> E2: StatusScreen.BuyRandomMutation(player)
cmd      := "cmd " COMMAND_ID           -> E1: 許可リストにある任意の Commands.xml ID（逃げ道）
```

| 族 | 文法 | 実行 | 根拠 | 注意 |
|---|---|---|---|---|
| 移動 | `move DIR`、`up`/`down` | E1 | `CmdMoveE` は switch 内で `AutoAct.ClearAutoMoveStop(); The.Player.Move("E")`（`XRLCore.cs:1167-1169`） | 世界地図でも同じ ID を使う |
| 攻撃 | `attack DIR`、`attack_nearest` | E1 | `CmdAttackE` は `:1358`（03 §3.3） | 遠隔攻撃（`CmdFire`/`CmdThrow`）は PickTarget を経るので week 3 に回す（§4） |
| 待機と休息 | `wait`、`wait 20`、`wait 100`、`rest` | E1 | `CmdWait20` → `AutoAct.Setting=".20"`（`:1543-1551`）、`CmdWaitUntilHealed` → `"r"`（`:1596-1606`） | 休息中は `RenderBase` が早期に return する（`:2614-2618`）。配信での見え方は §9 |
| 自動探索 | `explore` | E1 | `CmdAutoExplore` → `AutoAct.Setting="?"`。世界地図では無効（`:1920-1925`） | AutoAct の実行中は、CTA ハンドラが LLM に問い合わせずに素通りさせる（§5.2）。停止すると次の CTA で `last_action.outcome = autoact_stopped` と停止メッセージを渡す |
| ゾーン内の移動先指定 | `goto x,y` / `goto e17` / `goto f2` | E1 | `CmdMoveToBorder:x,y` は、隣接していなければ `AutoAct.Setting = "M{x},{y}"` になる（`:908-919`）。名前は Border だが、実質はゾーン内の goto である | ID から座標への変換は Brain が観測をもとに行う。到達できない場合は AutoAct 側のメッセージで返る |
| 相互作用 | `use DIR`、`get`、`get DIR` | E1 | `CmdUseE` → `PerformSmartUse("E")`（`:1661-1663`）、`CmdGetFromE`（`:2156-2158`） | 隠しコマンドなので、ピッカーを経ずに 1 手で実行できる（04 §1.5） |
| 会話 | `talk DIR` → 以後は `answer` | E1 とマクロと E3 | `CmdTalk` → `PickDirection.ShowPicker`（`:2212-2214`）→ 会話は `Popup.ShowConversation`（`ConversationUI.cs:514-537`） | 方向ピッカーには Brain が DIR で自動的に答える（台帳の種類 H2）。選択肢は LLM が選ぶ |
| 能力 | `ability CommandSprint [DIR]` | E1 | switch の default で `CommandEvent.Send(The.Player, id)`（`:2322-2334`） | 観測 O6 にない ID は拒否する。対象ピッカーが出る能力は §4 |
| 所持品と装備 | `item`、`equip`、`unequip`、`drop` | E2 | ゲームの画面も、同じ関数を `APIDispatch.RunAndWaitAsync` 経由（スレッドプール）で呼んでいる（`stable/XRL.UI.Framework/APIDispatch.cs:10, 46`、03 §2.8） | VERB は `GetInventoryActions` の候補に限る。確認のポップアップは §4 の監視が拾う |
| 取引 | 会話で `answer trade` → 取引専用のモーダル | E3 | `ConversationUI.Render` で -2 → `Trade.ShowScreen()`（`ConversationUI.cs:528`）→ `TradeScreen.show(...).Result`（`TradeUI.cs:458`） | week 3（§4.3） |
| レベルアップ | 通知はポップアップ（§4）。ポイントを使うのは `raise`、`learn`、`buy_mutation` | E2 と E3 | `Leveler` が `Popup.Show`/`ShowYesNo`/`PickOption` を直接呼ぶ（`stable/XRL.World.Parts/Leveler.cs:289, 325, 341`） | 購入関数の中の確認（`ShowYesNo`、`StatusScreen.cs:75`）には、E2 を発した LLM の意図で自動的に Yes と答える（台帳の種類 H3） |
| キャラクター作成 | なし | 人間 | `EmbarkBuilder` は UI コンテキストで動く（03 §2.8） | LLM は事前にビルドの希望（種族、職業、属性）をテキストで出し、人間がそのとおりに入力する。台帳の種類 H6 |

**許可しないコマンド**（`rejected: forbidden` を返す）:

- `Screens.Show` 系: `CmdInventory`、`CmdEquipment`、`CmdCharacter`、`CmdSkillsPowers`、`CmdQuests`、`CmdJournal`、`CmdTinkering`、`CmdLastStatusPage`（`XRLCore.cs:1706-1919`）。これらは Modern UI でゲームスレッドをブロックし、情報は O4、O7、O10 から得られる。
- `CmdSystemMenu`、`CmdSave`、`CmdLoad`、`CmdQuit`、`CmdSaveAndQuit`。
- `CmdWish`。`gocoda`/`goend` のようなエンディング直行のウィッシュがある（`EndGame.cs` の `[WishCommand("gocoda")]` ほか）。
- Debug カテゴリの全件、`CmdToggleAnimation`（`EnableAnimation` が false になると `:900` の `GetNextCommand` がキー待ちで止まる）、`CmdMessageHistory`、`CmdHelp`。

### 3.3 ターンを消費しない問い合わせ（free tools）

dcss-ai の区分に倣い、ターンを消費しないツールと消費するツールを分ける（02 P3）。前者は、CTA ハンドラが止まっている間にゲームスレッドで答える。

| ツール | 中身 | 引用 |
|---|---|---|
| `look(target)` | `Look.GenerateTooltipContent`。target はエンティティ ID、方向、座標のどれか | `Look.cs:239` |
| `inventory()` | 所持品、装備スロット、アイテムごとの動詞（`GetInventoryActions`）、重量 | `EquipmentAPI.cs:378` |
| `character()` | 能力値、AP/SP/MP、スキル、パワー、変異、購入できる候補とコスト | `Skills.cs:19`、`Mutations.cs:90`（03 §2.4） |
| `quests()` / `journal(q)` | クエストの step と、ジャーナルの記録 | `stable/Qud.API/JournalAPI.cs:27-41` |
| `path(x,y)` | `FindPath` で到達できるかと歩数（`goto` の前の確認） | `stable/XRL.World.AI.Pathfinding/FindPath.cs:57-71` |
| `kb_search(q)`、`note(section, text)`、`recall(q)` | Brain 内で完結する（§7）。ゲームには問い合わせない | — |

### 3.4 結果の返し方

`act` の戻り値は、ゲームが次に入力を求めた時点の観測である。つまり次の `decision` か `modal` になる（02 P3、P4）。戻り値の「成功」は信用しない。`last_action.outcome` は、行動後の状態から判定する。

| outcome | 判定 |
|---|---|
| `autoact_started` / `autoact_stopped` | **最初に判定する。** `AutoAct.IsActive()` が真なら started。`CmdWait20` などは AutoAct を設定してから `CmdNone` に落ちるので（`XRLCore.cs:1543-1551`）、エネルギーの変化だけで判定すると誤る。停止理由は O5 のメッセージ |
| `energy_spent` | 注入したイベントがキューから消え、エネルギーが 1000 未満になった |
| `no_energy_spent` | 注入したイベントが消えたが、エネルギーが変わらない（壁への移動、対象のない `get` など）。`SkipPlayerTurn` で CTA に戻る（§5.2） |
| `modal` | 実行中にモーダルが出た（§4）。答え終わったあとの行動の結果は、次の `decision` にまとめて入れる |
| `rejected:{parse_error,forbidden,unknown_id,not_usable}` | Brain か mod が実行前に拒否した。ゲームのターンは進まない |
| `not_consumed` | CTA に戻った時点で、注入したイベントがまだキューに残っていた（フォーカスのセッターによるクリアの取りこぼしなど）。残っていたイベントは CTA で取り除き（二重実行の防止）、**自動では再注入しない**。LLM に返し、LLM が出し直す |

**消費の判定は、CTA に入るたびに行う（`Pending` の解決）。**

- PlayerTurn には、EndPlayerTurn コールバック（`XRLCore.cs:2358`）を通らずに抜ける経路がある。
  - switch の中の `return;`: `CmdAutoExplore`（`:1926`）、`CmdAutoAttack`（`:1940`）、`CmdMoveTo` 系（`:1324`）、`:2103`
  - while を抜ける `break;`: 隣接していない `CmdMoveToBorder:x,y`（`:917`）、Tutorial のゲート（`:768, 906`）
  - マウスイベント処理の `return;`（`:789, 803, 816, 837`）
- したがって、`explore` と `goto`（最も多いと見込まれる 2 つ）の結果は、コールバックでは確定できない。
- 次に CTA に入ったこと自体が、PlayerTurn を抜けた証拠になる。そこで、outcome は CTA の入口で確定する。EndPlayerTurn コールバックは、エネルギーを使わなかった場合に CTA へ戻すためだけに使う。

どの outcome にも `hp_delta`、`moved`、`turns`（`XRLGame.Turns` の差分）、その間の新しいメッセージを添える。

---

## 4. モーダル UI

### 4.1 原則: 監視は UI スレッド側に置く

- **CTA ハンドラではモーダルに対処できない。**
  - モーダルの大半は、ゲームスレッドが `Popup.WaitNewPopupMessage` の中の `complete.Task.Wait()` で止まっている状態である（`stable/XRL.UI/Popup.cs:824-908`）。
  - E2 の直接呼び出し（`BuyStat` など）がポップアップを出した場合は、**自分の CTA ハンドラの中で**ゲームスレッドが止まる。
  - したがって、検出と応答はブリッジの IO スレッドと UI スレッドで行う。
- **監視の範囲。** ブリッジの状態が `RUNNING`（§5.3）の間は常に監視する。`RUNNING` は、`act` を送ってから次の `decision` が来るまでのすべての期間を指し、E1、E2、AutoAct、他の行動主体のターンを含む。
- **監視の手順。** `RUNNING` に入って 200 ms たったら、以後 150 ms ごとに `GameManager.Instance.uiQueue.queueSingletonTask("qb.modal", ModalProbe.Scan)` を積む。
  - `awaitTask` は使わない。相手のキューが処理されていないとデッドロックするからである（01 K21、`stable/QupKit/ThreadTaskQueue.cs:135`）。
  - `uiQueue` を処理するのは `GameManager.Update` である（`stable/GameManager.cs:2963`）。
- **`PopupMessage` のインスタンスの探し方。** `UnityEngine.Object.FindObjectsOfType<PopupMessage>()` で、有効かつ `commandCallback != null || selectCallback != null` のものを探す。
  - ゲームスレッド発の `WaitNewPopupMessage` は共有インスタンス `getWindow("PopupMessage")` を使う（`Popup.cs:826`）。
  - 非同期の経路と AskString は `copyWindow` を使う（`Popup.cs:760`、`stable/Qud.UI/UIManager.cs:282, 323`）。
  - 全件を探索すれば、両方を 1 つの経路で拾える。
- **答え方。** `PopupMessage` は必要な状態をすべて public で持っている（`stable/Qud.UI/PopupMessage.cs:20-42`）。

  | フィールド | 内容 |
  |---|---|
  | `Message` / `Title` | `UITextSkin` |
  | `controller.menuData` | 選択肢 |
  | `controller.bottomContextOptions` | ボタン |
  | `inputBox` | 文字入力欄 |
  | `commandCallback` / `selectCallback` | 結果を返すコールバック |
  | `PopupID` | ポップアップの識別子 |

  - 答えるには、`OnActivateCommand(item)` を呼ぶ（`:926-934`）。これは `commandCallback(item)` を呼んだうえで `commandCallback = null` にし、`Hide()` する。
  - ゲームスレッド側のコールバックが見るのは `item.command` の文字列だけである。
    - `option:N`: `ShowConversation` と `PickOption`（`Popup.cs:1595-1614, 1740-1753`）
    - `Yes`/`No`/`Cancel`: `ShowYesNo`（`:2262-2274`）
    - `trade` / `Look`: 会話画面
  - したがって、`menuData` や `bottomContextOptions` にある実物の `QudMenuItem` をそのまま渡せばよい。
- **ゲームスレッドで読める情報。** 会話ではゲームスレッドが止まっているので、`ConversationUI.CurrentNode`/`CurrentChoices`/`Speaker` の static 状態（`stable/XRL.UI/ConversationUI.cs:135-157`）も、ほぼ静止した状態で読める。LLM には、`Choice` の本文と、話者の Look 本文（O9）を添える。

`ModalProbe.Scan` の骨子（UI スレッドで動く C#。説明用）:

```csharp
static void Scan() {
  var view = GameManager.Instance.CurrentGameView;                 // GameManager.cs:469
  foreach (var w in UnityEngine.Object.FindObjectsOfType<PopupMessage>()) {
    if (!w.isActiveAndEnabled || (w.commandCallback == null && w.selectCallback == null)) continue;
    var snap = new ModalSnap {
      kind = Classify(w),          // info | choice | yesno | input | conversation
      popup_id = w.PopupID, title = Strip(w.Title?.text), text = Strip(w.Message?.text),
      options = w.controller.menuData.Select((m,i) => (i, Strip(m.text), m.command)).ToList(),
      buttons = w.controller.bottomContextOptions.Select(b => (Strip(b.text), b.command)).ToList(),
      input = w.inputBox != null && w.inputBox.gameObject.activeInHierarchy };
    snap.modal_id = Hash(snap.popup_id, snap.text, snap.options);
    Bridge.Outbox.Enqueue(snap);   // ConcurrentQueue -> IO thread -> Brain
    return;
  }
  if (view == "PickTarget") Bridge.Outbox.Enqueue(PickerSnap(PickTargetWindow.currentMode,
                                                             PickTargetWindow.currentText));
  else if (!KnownViews.Contains(view)) Bridge.Outbox.Enqueue(UnknownViewSnap(view));
}
```

回答の反映（UI スレッド。`modal_id` が現在のモーダルと一致しない答えは捨てる）:

```csharp
uiQueue.queueTask(() => {
  var w = FindActive(modal_id); if (w == null) return;               // すでに閉じた、または別のモーダル
  if (ans.text != null) w.inputBox.text = ans.text;                  // AskString / AskNumber
  var item = ans.option >= 0 ? w.controller.menuData[ans.option]
                             : w.controller.bottomContextOptions.First(b => b.command == ans.button);
  w.OnActivateCommand(item);                                         // PopupMessage.cs:926
});
```

### 4.2 モーダルの種類ごとの対処

| 種類 | ゲームスレッドの状態 | 検出 | 読むもの | 答え方 | Harmony | Rosetta |
|---|---|---|---|---|---|---|
| `Popup.Show` / `ShowSpace` / `ShowFail`（ボタン 1 つの通知） | `Task.Wait`（`Popup.cs:908`） | 有効な `PopupMessage` で、`menuData` が 0 件かつボタンが 1 つ | `Message`、`Title`。本文は既定でメッセージログにも入る（`Popup.cs:658-671`） | **ハーネスが自動で閉じる**。0.8 秒待ってから `OnActivateCommand(button[0])` を呼ぶ（台帳 H1） | 不要 | 不要 |
| `PickOption` / `ShowOptionList` | 同上 | `menuData` が 1 件以上で、各項目の command が `option:N`（`Popup.cs:1700-1755`） | 各選択肢の本文、Intro | LLM が `answer N` か `answer cancel` を返す | 不要 | 不要 |
| `ShowYesNo` / `ShowYesNoCancel` | 同上 | ボタンの command が `Yes`/`No`(/`Cancel`)（`Popup.cs:2251-2275`、`PopupMessage.cs:363-430`） | 本文 | LLM が `answer yes`/`no` を返す。例外は、E2 が自分で出した確認（H3） | 不要 | 不要 |
| `AskString` / `AskNumber` | `AskStringAsync(...).Result`。インスタンスは copyWindow 側（`Popup.cs:1433-1450, 760`） | `inputBox` が有効 | 本文、既定値 | `inputBox.text` に入れてから Submit のボタンを押す。既定は `cancel` **[要実測: PR4]** | 不要 | 不要 |
| `ShowConversation` | `Task.Wait`。`PopupID = "Conversation:" + Title`（`Popup.cs:1571-1615`） | `PopupID` の接頭辞 | `ConversationUI.CurrentNode.GetDisplayText`、`CurrentChoices`、`menuData` の本文。ボタンは Look/Trade/Cancel | `answer N` / `answer trade` / `answer cancel`。外部から `ConversationUI.Select` は呼ばない。`Render()` 内の `Select` と競合する（03 §3.6） | 不要 | 不要 |
| レベルアップと変異の選択 | `Leveler` が `Show`/`ShowYesNo`/`PickOption` を呼ぶ（`Leveler.cs:289-352`） | 上の各行と同じ | 同上 | 同上 | 不要 | 不要 |
| 死亡（Roleplay） | `PickOption("Reload from checkpoint", "View final messages", "Retire character", "Quit to main menu")`（`stable/XRL/CheckpointingSystem.cs:114`） | 選択肢の本文が完全に一致する | message（死因） | **ハーネスの規則で "Reload from checkpoint" を選ぶ**。Retire/Quit は LLM に見せない（台帳 H4）。Classic では `ShowSpace` の通知になり（`:85-104`）、それでその回は終わる | 不要 | 不要 |
| 方向ピッカー（`PickDirection`） | Legacy の `getvk` ループ。Modern UI でもゲームスレッドで回る（`stable/XRL.UI/PickDirection.cs:28-60`） | `CurrentGameView == "PickTarget"` かつ `PickTargetWindow.currentMode == PickDirection`（`PickDirection.cs:30-31`、`stable/Qud.UI/PickTargetWindow.cs:17-19`） | `currentText`（例: "Talk \| [Select a direction]"） | マクロの DIR があれば `Keyboard.PushKey(NumPadN)`（H2）。なければ LLM に尋ねる | 不要 | 不要 |
| 対象ピッカー（`PickTarget`: 射撃、投擲、対象を取る能力） | 同じく `getvk` ループ（`stable/XRL.UI/PickTarget.cs:378`） | 同じビューで、別のモード | `currentText` と、Brain 側の可視エンティティ一覧 | `PushMouseEvent("PointerOver", x, y)` → `PushKey(Enter)` **[要実測: 03 U7。week 3]**。M1〜M3 では `Escape` で取り消し、遠隔攻撃の文法は無効にしておく | 不要 | 不要 |
| ステータス画面（Modern） | `StatusScreensScreen.show(...).Result`（`stable/XRL.UI/Screens.cs:80, 125`） | ビュー名 | 読まない（O4、O7、O10 で足りる） | 許可リストで開かせない。何かの拍子に開いたら `NavigationController` に Cancel を送る **[要実測]** | 不要 | 不要 |
| 取引（Modern） | `TradeScreen.show(...).Result`（`stable/XRL.UI/TradeUI.cs:458`） | ビュー名が `ModernTrade` | 両側の一覧を `TradeUI.GetObjects`（`TradeUI.cs:150`）で読む。ゲームスレッドが止まっているので、UI スレッドから読んでも実質静止している **[推論]** | UI スレッドで、LLM の指定どおりに `setHowManySelected(go, n)` を呼び、`HandleOfferTrade()` か `Cancel()` を呼ぶ（`stable/Qud.UI/TradeScreen.cs:275, 754, 874`）。成立するまでに出る確認ポップアップは、上の行と同じ経路で扱う | 不要 | 不要 |
| 本、端末、その他の Modern 画面 | 各画面の Task | 既知のビュー名にない | ビュー名だけ | 配信のオーバーレイに警報を出し、ブリッジは `stall` を送る。Cancel を 1 回試し、駄目なら人手に回す（台帳 H7） | 不要 | 不要 |
| キャラクター作成、メインメニュー、ロード | UI | — | — | 人間が操作する（H6） | — | — |

**TutorialManager のゲート。** `OnActivateCommand` は `TutorialManager.AllowSelectedPopupCommand` の検査を通る（`PopupMessage.cs:928`）。チュートリアルのモードは使わない。

### 4.3 ハーネスが自分で答えるもの（LLM を通さない）

ここに挙げるものだけに限る。どれも台帳（§8.3）に 1 件ずつ記録する。

| ID | 内容 | 理由 |
|---|---|---|
| H1 | ボタン 1 つの通知ポップアップを閉じる | 情報は次の観測のメッセージ欄に入る。BALROG の `--More--` 自動送り（02 §1.5）と同じ扱い |
| H2 | マクロの方向ピッカーに答える（`talk W` の W） | LLM がすでに指定した値である |
| H3 | E2 の購入や装備に伴う確認に Yes と答える | 購入の意図は LLM がすでに示している。本文は観測に残す |
| H4 | Roleplay の死亡時に "Reload from checkpoint" を選ぶ | Retire や Quit を選ぶとその回が終わる。死亡回数は主要な指標として公開する |

### 4.4 Plan B と Plan C

- **Plan B（R3 が崩れた場合）: `OptionModernUI=No`。**
  - Legacy UI にすると、すべてのポップアップがゲームスレッドの `getvk` ループになる。本文は ScreenBuffer に描かれ（03 §1.3）、`PushKey` で答えられる（03 §6.2 経路 7）。
  - 代償は、配信の見た目が古くなることと、Legacy UI の保守状況がわからないことである。
- **Plan C: Harmony の prefix で `Popup.*` を置き換える。**
  - 起動は Rosetta（`arch -x86_64`。04 §4.6）になる。
  - モーダルの網羅性は最も高いが、P2 の「Harmony なし」を捨てることになる。

---

## 5. スレッドと同期

### 5.1 スレッドの役割

| スレッド | 実体 | P2 での役割 | 止まってよいか |
|---|---|---|---|
| ゲームスレッド | `XRLCore.CoreThread`（`stable/XRL.Core/XRLCore.cs:3540-3571`） | 観測の組み立て、問い合わせへの応答、E2 の実行、E1 の注入（EndPlayerTurn コールバック内） | **止めてよい。** CTA ハンドラで Brain を待つ。ゲーム本体も、ポップアップ（`Popup.cs:908`）やステータス画面（`Screens.cs:80`）で同じようにこのスレッドを止めている |
| UI スレッド | Unity のメインスレッド（`GameManager.Update` → `uiQueue.executeTasks()`、`GameManager.cs:2963`） | モーダルの監視と応答（`ModalProbe`） | **止めない。** `uiQueue` にはタスクを積むだけにする |
| ブリッジの IO スレッド | mod が起こす専用スレッド（v1 `BrainClient` の後継） | WebSocket の送受信、状態機械、モーダル監視のタイマー、ピッカーへの `PushKey` | 止めない |
| Brain | 別プロセスの Python（asyncio） | LLM の呼び出し、記憶、台帳、オーバーレイ | 任意 |

### 5.2 1 ターンの流れ

```
Game thread                                   Bridge IO thread                 Brain (Python)
RunSegment
 ├ BTA (ActionManager.cs:743)
 ├ CTA.Check (:789) → QBSystem.HandleEvent(CTA)
 │   ├ if AutoAct.IsActive(): return true            (LLM に問い合わせない)
 │   ├ The.Core.RenderBase()        (視界・glyph・HUD・gameQueue)
 │   ├ obs = Snapshot()  ──────────────────────────► "decision" ──────────────► 観測のテキスト化 → LLM
 │   ├ loop { req = Inbox.Take(50ms)                                          ◄── "query look e17"
 │   │        query → ゲームスレッドで応答 ─────────► "query_result" ─────────►
 │   │        gameQueue.executeTasks()               (UI のツールチップを止めない)
 │   │      }                                                                  ◄── "act talk W"
 │   ├ E1: Pending = ("CmdTalk", picker=W); state=RUNNING
 │   └ return true   (エネルギーはそのまま → :798 → PlayerTurn :1611)
 ├ PlayerTurn
 │   ├ ClearMouseEvents (XRLCore.cs:734)
 │   ├ 反復 1: 入力なし → EndPlayerTurn cb (:2358): focus を強制 → PushCommand("CmdTalk")
 │   ├ IdleWait (:2392) は PushMouseEvent の KeyEvent.Set ですぐ抜ける
 │   ├ 反復 2: "Command:CmdTalk" (:779) → switch (:981) → PickDirection.ShowPicker
 │   │                                          ModalProbe: view=PickTarget/PickDirection
 │   │                                          → PushKey(NumPad4)             [H2]
 │   │     → ConversationUI.HaveConversation → Popup.ShowConversation → Task.Wait (:908)
 │   │                                          ModalProbe: PopupMessage を検出
 │   │                                          → "modal" ───────────────────────► LLM
 │   │                                          ◄── "answer 1" ──────────────────
 │   │                                          uiQueue: OnActivateCommand(menuData[1])
 │   ├ 会話が終わる（outcome は次の CTA の入口で確定する。§3.4）
 │   └ エネルギーが 1000 未満ならループを抜ける。1000 以上なら SkipPlayerTurn=true → :2393-2396 で抜ける
 ├ EndActionEvent。他の行動主体が行動する …
 └ 次の BTA/CTA → 次の "decision"（last_action に結果が入る）
```

**要点。**

- **LLM を待つ場所は 2 か所だけである。**
  - CTA ハンドラ（`decision`）
  - モーダル（`modal`。このときゲームスレッドはゲーム自身の Wait で止まっている）
- **注入は EndPlayerTurn コールバックで行う。**
  - `PlayerTurn` は冒頭で `CallBeginPlayerTurnCallbacks()`（`:693`）を呼び、そのあとで `ClearMouseEvents(LeaveMovementEvents: true)`（`:734`）を呼ぶ。そのため、BeginPlayerTurn で積んだ移動以外のコマンドは消える（03 §3.2 注意点 1）。
  - EndPlayerTurn のコールバックは、クリアのあと、ループの反復ごとに呼ばれる（`:2355-2359`）。
- **エネルギーを使わないコマンド（`no_energy_spent`）の扱い。**
  - コールバックで `The.Game.ActionManager.SkipPlayerTurn = true` にし、`Keyboard.KeyEvent.Set()` を呼ぶ。
  - これで `IdleWait` の直後に `break` し（`:2392-2396`）、RunSegment の内側 while（`ActionManager.cs:755`）に戻り、もう一度 CTA が発火する。
  - v1 の wake（01 K20）と同じ仕組みである。
- **`SkipPlayerTurn` はインスタンスフィールドである（`ActionManager.cs:25`）。** 03 §3.4 は static と書いているが誤り。
- **`Pending` は CTA の入口で解決する（§3.4）。** PlayerTurn は `explore` や `goto` のあと、EndPlayerTurn コールバックを通らずに抜けることがある（`XRLCore.cs:917, 1926` など）。
- **AutoAct の実行中も CTA は発火する**（CTA の Check `:789` は AutoAct の分岐 `:805` より前にある）。ハンドラは `AutoAct.IsActive()` なら何もせずに返す。AutoAct が止まった次の CTA が `autoact_stopped` の決定になる。

### 5.3 状態機械（ブリッジの IO スレッドが持つ）

| 状態 | 意味 | 入る条件 | 出る条件 |
|---|---|---|---|
| `DECIDING` | ゲームスレッドが CTA ハンドラで待っている | `decision` を送った | `act` を受けた → `RUNNING` |
| `RUNNING` | ゲームが進行中。モーダル監視が有効 | `act` の実行を始めた | 次の `decision` → `DECIDING`、またはモーダルを検出 → `MODAL` |
| `MODAL` | モーダルが Brain の答えを待っている | `ModalProbe` が新しい `modal_id` を報告した | 答えを反映し、`modal_id` が消えたのを確認 → `RUNNING` |
| `DETACHED` | Brain とつながっていない | WS の切断、または 15 秒間 ping がない | 再接続 → wake（§5.5） |

### 5.4 ブロックする箇所とタイムアウト

| 箇所 | 待ち方 | タイムアウト | 超えたとき |
|---|---|---|---|
| CTA ハンドラ（`DECIDING`） | `Inbox.Take(50ms)` を繰り返す。反復ごとに `gameQueue.executeTasks()` を呼び、`The.Game.Running` と `Keyboard.Closed` を確かめる | **なし**（ターン制なので、待つことがそのまま一時停止になる） | — |
| Brain の LLM 呼び出し | asyncio | 90 秒。2 回まで再試行し、そのあと強い階層に切り替える | 3 回失敗したら `pause`。オーバーレイに "paused: LLM error" と出す |
| 実行中（`RUNNING`） | 監視タイマー | AutoAct 以外で 30 秒たっても `decision` も `modal` も来ない | `stall` を送り、ビュー名とゲームスレッドの位置（直前のコールバック）を報告する。120 秒で警報を出す |
| モーダルの応答 | `modal_id` が消えたかを再スキャンで確かめる | 5 秒 | 1 回だけ再送する。駄目なら `stall` |
| 注入したコマンドの消費 | 次に CTA に入るまで | — | 残っていたイベントを取り除き、`not_consumed` を LLM に返す。自動では再注入しない |

### 5.5 一時停止、切断、wake

- **一時停止。**
  - Brain が `act` を送らない限り、ゲームは CTA ハンドラで止まったままになる。一時停止のために特別な仕組みは要らない。
  - 配信のために人間が止めたいときは、Brain の CLI かオーバーレイの `pause` を使う。
- **切断。**
  - `DETACHED` になると、CTA ハンドラは何もせずに `true` を返す。そのまま PlayerTurn に入るので、人間がキーボードで操作できる（v1 の disconnect_pause と同じ。01 §1.3-5）。
  - この間に消費されたコマンドはすべて `human_input` として台帳に記録する。判定は、EndPlayerTurn コールバックで「自分が注入していないコマンドでエネルギーが減った」かどうかで行う。
- **wake。**
  - 再接続したら、EndPlayerTurn コールバックが次の反復で `SkipPlayerTurn = true` にし、ブリッジが `KeyEvent.Set()` を呼ぶ。`IdleWait` を抜けて break し、CTA に戻る。
  - PlayerTurn の待機ループはこのコールバックを毎反復で呼ぶので、v1 の `gameQueue` 経由は要らない。ただし、v1 の方法も予備として残す。

### 5.6 フォーカス待機への対処 [要実測: PR3]

| 停止の要因 | 場所 | 対処 |
|---|---|---|
| `while (!GameManager.focused) Thread.Sleep(200)` | `XRLCore.cs:737-740`（PlayerTurn の毎反復） | EndPlayerTurn コールバックで、**`PushCommand` の前に** `GameManager.focused = true` と `XRLCore.bThreadFocus = true` を設定する。セッターは false から true への遷移で入力キューを消す（`stable/GameManager.cs:404-425`）ので、順序は必ず「focus → push」にする。Unity が次にフォーカスを変えるのは、フォーカスの変化イベントのとき（`GameManager.cs:1920-1929`）だけなので、1 回強制すれば次の変化まで保たれる **[推論]** |
| `kbhit()` の 200 ms 待ち | `stable/ConsoleLib.Console/Keyboard.cs:938-954`（`bThreadFocus` が false のとき） | 同上（`bThreadFocus` も public static。`XRLCore.cs:223`） |
| Unity の Update そのものが止まる（`uiQueue` が処理されない → モーダルに答えられない） | `Application.runInBackground` | `OptionMusicBackground=Yes`（`stable/XRL.UI/Options.cs:1445-1454`）。これがないと §4 が成り立たない |
| 人間がゲームの窓を触る | — | 配信では専用のディスプレイか Space に置く。人間の入力は §5.5 のとおり検出する |

CTA ハンドラ（`DECIDING`）はフォーカスに関係なく動く。フォーカスが影響するのは E1 の実行とモーダルの応答だけである。

### 5.7 ライフサイクル

- **新規ゲーム。** `[PlayerMutator]` → `RequireSystem<QBSystem>()`（01 K2）。
- **ロード。**
  - `IGameSystem` はセーブに含まれ、`AfterLoad` が呼ばれる（01 K18、`stable/XRL/IGameSystem.cs:11-12`）。ソケットとスレッドは `[NonSerialized]` にし、`AfterLoad` で作り直す。
  - コールバックの登録は static のリストに入る。そのため、プロセス内で 1 回だけ登録されるようにガードする（03 §4.3）。
  - `_beginTurnCount` はキャラクターごとに 0 に戻る（01 K11）。ターンの識別には `XRLGame.Turns` と、ブリッジが振る `seq` を使う。
- **終了。** `Keyboard.Closed` のときにゲームスレッドは `Abort` される（01 K22）。IO スレッドはバックグラウンドスレッドにし、プロセスの終了と一緒に消えるようにする。v1 の `Stop()` が呼ばれていなかった問題（01 §4.1）は、`AfterLoad` と `OnRemoved` での明示的な破棄で塞ぐ。

---

## 6. 通信と配置

### 6.1 通信路

- **構成。**
  - mod がクライアントで、`System.Net.WebSockets.ClientWebSocket` を使う。Brain がサーバーで、`ws://127.0.0.1:4040` を開く。
  - v1 で実働した構成である（p95 1 ms、4 本の受け入れ試験。01 K19）。
- **HttpListener にしない理由。** HttpListener でも mod をサーバーにできるが（03 §5）、次の 2 点でクライアント方式を選ぶ。
  1. Brain を再起動してもゲームを再起動しなくてよい。
  2. macOS/Mono での bind の挙動が未検証である（03 U10）。
- **バインドと認証。** バインドは localhost だけにする。接続時に、Brain が起動時に生成したトークンを `hello` で照合する（RimMolt が 9/15 に追加した認証と同じ趣旨。02 §1.1）。
- **直列化。** JSON を使い、`Newtonsoft.Json` 13 を使う（ゲーム本体が 37 ファイルで使っているのでロード済み。03 §5）。Roslyn の参照に入るかは PR0 で確かめる。入らなければ、送信は v1 の `SnapshotState` 流の手書きにし、受信は 5 種類のメッセージだけを読む小さなパーサにする。

### 6.2 メッセージ

| 向き | type | 主なフィールド | 送れる状態 |
|---|---|---|---|
| mod → Brain | `hello` | `proto`、`game_version`（AssemblyVersion）、`mod_sha256`、`options`（関係するオプションの値）、`world_seed`、`token` | 接続時 |
| mod → Brain | `decision` | `seq`、`obs`（§2.3） | `DECIDING` |
| mod → Brain | `query_result` | `qid`、`data` / `error` | `DECIDING` |
| mod → Brain | `modal` | `seq`、`modal_id`、`kind`、`title`、`text`、`options[]`、`buttons[]`、`input`、`picker`、`context`（会話なら話者と Look 本文） | `RUNNING` → `MODAL` |
| mod → Brain | `event` | `kind` ∈ {`death`, `checkpoint_restore`, `zone_changed`, `level_up`, `ending`, `human_input`, `harness_input`}、`detail` | 常時 |
| mod → Brain | `stall` | `ms`、`view`、`last_hook` | `RUNNING` |
| Brain → mod | `query` | `qid`、`name`、`args` | `DECIDING` |
| Brain → mod | `act` | `seq`、`action`（§3.2 の文字列） | `DECIDING` |
| Brain → mod | `answer` | `modal_id`、`option` / `button` / `text` / `dir` | `MODAL` |
| Brain → mod | `ping` | — | 常時（5 秒ごと） |

`seq` が一致しない `act` と、`modal_id` が一致しない `answer` は捨て、`event: harness_input(kind=stale_drop)` として記録する。v1 の冪等性層（01 §1.2）の代わりは、これだけで足りる。

### 6.3 プロセス構成

```
┌─────────────── CoQ.app（arm64 ネイティブ、-savepath <隔離プロファイル>）───────────────┐
│  mod "QudBridge"（Roslyn でコンパイルされる .cs 7 本、Harmony なし）                     │
│   QBBootstrap.cs   [PlayerMutator] → RequireSystem<QBSystem>()                          │
│   QBSystem.cs      IPlayerSystem: CTA ハンドラ、EndPlayerTurn / AfterRender / Msg の    │
│                    各コールバック                                                       │
│   QBObserve.cs     スナップショットと free query（v1 SnapshotState の知識を移植）       │
│   QBExec.cs        文法 → E1/E2、許可リスト                                             │
│   QBModal.cs       UI スレッドの Scan / Answer                                          │
│   QBBridge.cs      ClientWebSocket の IO スレッド、状態機械、監視タイマー               │
│   QBCompat.cs      起動時にリフレクションで自己検査（§10）                              │
└──────────────┬───────────────────────────────────────────────────────────────────────────┘
               │ ws://127.0.0.1:4040（JSON、トークン認証）
┌──────────────┴──────────── qudbrain（Python 3.12、uv）─────────────────────────────────┐
│  bridge.py    WS サーバー、状態の追従、再接続                                            │
│  agent.py     ツールループ（decision → free tools* → act、modal → answer）、コスト階層、   │
│               ループ検知                                                                │
│  render.py    obs JSON → LLM 用テキスト（§2.3）、CP437 の正規化                          │
│  memory.py    notes.md、ローリング履歴、要約                                            │
│  kb.py        Base/*.xml から作った BM25 索引（SQLite FTS5）                            │
│  ledger.py    events.jsonl（ハッシュチェーン）、manifest、台帳                          │
│  overlay.py   http://127.0.0.1:8080（SSE）を OBS のブラウザソースに出す                 │
│  mcp.py       （任意、week 3 以降）同じ free tools を MCP stdio で公開する（デバッグ用）  │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

### 6.4 Brain の言語: Python を選ぶ理由

| 観点 | Python（uv） | TypeScript |
|---|---|---|
| オーナーの既存資産 | 他のリポジトリは Python/uv。v1 の `protocol.py`（pydantic の envelope）と `db/writer.py` を流用できる（01 §4.2） | なし |
| 必要なもの | WS サーバー（`websockets`）、LLM SDK、SQLite FTS5、XML の読み取り（`lxml`）、小さな SSE サーバー。どれも標準的で薄い | 同等 |
| TS の強み | Claude Agent SDK や MCP SDK との親和性 | P2 では**ループを Brain が持つ**ので、その強みが効かない。MCP は §6.3 の任意ファサードで足りる |
| 知識ベースの前処理 | Quests と Conversations のグラフ抽出、ObjectBlueprints の `Inherits` 解決は、データ処理として Python が書きやすい | 可能だが利点はない |

**「C# のゲーム内 MCP を先に作り、Claude Code を最初のクライアントにする」案（オーナーの傾き）への評価。**

- 利点は、初日から人間と Claude Code が対話的に試せることである。
- しかし、ツールループ（1 手ごとの観測添付、モーダルの割り込み、コストの階層、台帳）は結局どこかに要る。Claude Code に持たせると、主張の証拠（ループの中で何が起きたか）がハーネスの外に出てしまう。
- P2 は、ループと証拠を同じプロセス（`qudbrain`）に置く方を選ぶ。

---

## 7. 記憶・知識

### 7.1 何を永続化するか

`runs/<run_id>/` 以下に次のファイルを置く。

| ファイル | 書き手 | 中身 |
|---|---|---|
| `manifest.json` | ledger | ゲームの版、`mod_sha256`、Brain の git commit、`PlayerOptions.json` の写し、モデル ID と階層の規則、知識の構成（§7.4）、開始時刻、world seed |
| `events.jsonl` | ledger | すべての `decision`/`modal`/`act`/`answer`/`event`。行ごとに `prev_sha256` を持つハッシュチェーンにする |
| `llm/NNNNNN.json` | agent | LLM への要求の全文、応答の全文、モデル、トークン数、所要時間 |
| `notes.md` | **LLM** と人間 | 下の節構成（§7.3） |
| `deaths.jsonl` | agent | 死因、直前 20 手、LLM による事後分析（§7.3） |
| `summary.md` | LLM（安い階層） | 100 決定ごと、またはゾーンが変わったときに更新する「ここまでのあらすじ」 |

### 7.2 1 回の決定で LLM に渡す文脈

1. **システムプロンプト**（キャッシュ対象）。役割、文法（§3.2）、free tools、規約、`Manual.xml` の要約（約 6k トークン。04 §3.1）。
2. **`notes.md` の上位の節**（キャッシュ対象。100 決定ごとに更新）。
3. **`summary.md`**。
4. **直近 15 決定の 1 行要約。** 形式は `t=1180 move E -> ok | t=1181 attack E -> hit snapjaw (3)`。
5. **現在の観測**（§2.3）。

こうして文脈を有界に保つ。GPP は約 10 万トークンを超えるとループした（02 §1.11）。P2 は 1 回の決定を 30k トークン以下に抑えることを目標にする。

### 7.3 LLM が書くもの

RimMolt の配信者の `RIMWORLD_LEARNING.md` の構成（02 §1.1.2、P9）と、rimworld-ai-manager の POSTMORTEM の規則（02 P10）を合わせる。

- **`CORE_RULES`**（人間だけが書く。変更しない）
  - ハーネスの仕様（例: 「`goto` は AutoAct。敵を見ると止まる」）
  - 禁止事項
- **`LESSONS`**（LLM が書く。上限 40 件）
  - 1 件は「いつ → 何をする」の形でなければならない。「X を覚えておく」は受け付けない。
  - 死亡以外の教訓は、同じことが 2 回起きてから追加する。
- **`CURRENT_GOALS`**（LLM が書く）
  - 3 層で持つ: 長期（メインクエストの段階）、中期（このゾーンでの目的）、即時。
- **`WORLD`**（LLM が書く）
  - 集落、商人、危険なゾーン、未解決の手がかり。
- **書き込みの手段。**
  - `note(section, text)` の free tool で書く。
  - ゾーンが変わったとき、レベルが上がったとき、死亡したときに、Brain が「notes を更新せよ」という 1 回のターンを差し込む。

### 7.4 知識ベースと、ネタバレの方針

| 段 | 出典 | 中身 | 方針 |
|---|---|---|---|
| K0 | `Manual.xml`（12 トピック） | ゲーム内ヘルプ | 常にシステムプロンプトに入れる |
| K1 | `Skills.xml`、`Mutations.xml`、`ActivatedAbilities.xml` の説明、`ObjectBlueprints` の Description Short | キャラクター作成、レベルアップ、Look の画面でプレイヤーが見られる文 | `kb_search` で検索できる。**主張用の実行でも許可する** |
| K2 | `Quests.xml` の step 名（ジャーナルに表示されるもの） | 進行中のクエストの次の目標 | 許可する。ただし、まだ受けていないクエストは検索結果から除く |
| K3 | `Conversations.xml` のグラフ、`Quests.xml` の未受領の部分、`PopulationTables` | 物語と攻略のネタバレ | **主張用の実行では無効**にする。開発用の実行でだけ使う |
| K4 | Wiki（CC BY-NC-SA 4.0、約 85 万語。04 §3.4） | 攻略情報 | 主張用の実行では無効。「wiki-assisted」と明記した別の実行でだけ使う。リポジトリには同梱しない |

**注意。** SOTA の LLM は、事前学習で CoQ の wiki の知識を持っている可能性が高い。そのため、「ネタバレなし」は厳密には主張できない。主張できるのは、「実行時に外部の攻略情報を検索していない」ことだけである（§8.4 の文言に反映する）。

### 7.5 コストの階層

モデル名と価格はここでは固定しない。採用時に現行のものを確認する。

| 階層 | 使う場面（Brain の決定的な規則で振り分け、規則は manifest に記録） |
|---|---|
| **strong** | すべての `modal`。敵が見えていて HP が 60% 未満。新しいゾーンに入った直後の最初の決定。死亡後の事後分析。ループ検知の後。50 決定ごとの計画見直し |
| **fast** | 敵が見えていない状態での探索、移動、休息の判断。`summary.md` の更新 |

- **ループ検知。** 同じ観測ハッシュに同じ行動を 3 回返したら、次の決定を strong にし、「あなたは同じ行動を繰り返している」という注記を足す。
- **全行動を LLM が選ぶ方針。** ルールだけで行動を出す階層は作らない。ハーネスが出す入力は §4.3 の H1〜H4 だけにする。これが主張の中身になる。

---

## 8. 評価と証拠

### 8.1 進行の指標

**主指標は、メインクエストの段階を並べたはしご**である。クエスト名はゲームの `Quests.xml` からそのまま取る。**[推論]** `Quests.xml` に順序のフィールドはない。下の並びは、各 quest の `Level` 属性とゲームの知識から組んだもので、M2 までに `Conversations.xml` の `StartQuest`/`FinishQuest` から機械的に作り直す。

1. What's Eating the Watervine?
2. Fetch Argyve a Knickknack
3. Fetch Argyve Another Knickknack
4. Weirdwire Conduit... Eureka!
5. A Canticle for Barathrum
6. More Than a Willing Spirit
7. Decoding the Signal
8. The Earl of Omonporch
9. A Call to Arms
10. Pax Klanq, I Presume?
11. Tomb of the Eaters
12. The Golem / Reclamation / We Are Starfreight
13. **エンディング**（`EndGame.IsAnyEnding`、`stable/XRL.World.Conversations.Parts/EndGame.cs:103-113`）

エンディングの種類は `The.Game.GetStringGameState("EndType")` で判定する（`:67-77`）。`EndGame.Start` は実績 `CAVES_OF_QUD` を解除する（`:247-249, 282-290`）。mod はこれを毎決定で読み、変わったら `event: ending` を出す。

**副指標。** レベル、ゲーム内ターン数、LLM の決定数、訪れたゾーン数、死亡回数とチェックポイントからの復帰回数、ハーネス入力の件数（種類別）、人間の入力の件数、stall の件数と時間、LLM のトークン数と費用、実時間。

### 8.2 ログ

- **events.jsonl と llm/ で、どの行動がどの観測とどの推論から出たかを 1 対 1 でたどれるようにする。** 同じ内容は mod 側でも `Player.log` に `INFO - [QB]` の 1 行要約として出す（04 §5.4）。こうすると、ゲームのログと Brain のログを互いに照合できる。
- **ハッシュチェーン。** 各行に前の行の SHA-256 を入れる。実行の終わりに、最後のハッシュを manifest に書き、公開の場（git のタグ、配信の概要欄）に固定する。
- **配信のアーカイブ（VOD）は二次的な証拠として扱う。** 各決定の `seq` をオーバーレイに表示しておけば、映像とログを突き合わせられる。

### 8.3 ハーネス入力の台帳（LLM が選ばなかった入力をすべて並べる）

| ID | 入力 | 発生源 | 記録 |
|---|---|---|---|
| H1 | ボタン 1 つの通知を自動で閉じる | Brain の規則 | `harness_input(kind=auto_dismiss, text)` |
| H2 | マクロの方向ピッカーに答える | LLM の `talk W` などを展開したもの | `harness_input(kind=macro_picker, dir)` |
| H3 | E2 に伴う確認に Yes と答える | LLM の `raise`/`learn`/`equip` などを展開したもの | `harness_input(kind=confirm_own_action)` |
| H4 | Roleplay の死亡時にチェックポイントから復帰する | Brain の規則（Retire と Quit は選ばせない） | `event: checkpoint_restore` |
| H5 | フォーカスの強制（`GameManager.focused=true`） | mod | 件数だけ記録する。ゲームへの入力ではないが開示する |
| H6 | キャラクター作成、ワールド生成、ロード、クラッシュからの再起動 | 人間 | `harness_input(kind=human_setup)`。キャラクター作成は LLM が出したビルドの指定どおりに入力し、その指定文も記録する |
| H7 | 未知のモーダルの取り消し、stall の解消 | Brain の規則、または人間 | 人間が関わった場合は `human_input` |
| H8 | `pause`/`resume`、切断と wake | Brain | `event` |
| — | **人間のゲーム内入力** | 人間 | EndPlayerTurn コールバックで、注入していないコマンドの消費を検出して `human_input` にする。**主張の段位を決める数値**になる |
| — | 禁止事項 | — | `CmdWish` とすべてのウィッシュ、Debug コマンド、セーブとロード（主張用の実行では `OptionAllowSaveLoad=No`）、開発者モードに当たる操作。ハーネスは発行しない。発行されていないことは台帳に現れないことで示す |

### 8.4 この設計で支えられる主張

| 段位 | 条件 | 文言の例 |
|---|---|---|
| **S** | Classic（パーマデス）、H6 はキャラクター作成とワールド生成だけ、人間のゲーム内入力 0、再起動 0 | 「Caves of Qud 2.0.211.56 の Classic モードで、LLM（モデル名）がテキストの観測だけを使い、すべてのゲーム内行動を自分で選んでエンディング（種類）に到達した。ハーネスが代行した入力は台帳の N 件で、実行時に攻略情報は検索していない。」 |
| **A（最初の目標）** | Roleplay（ゲーム本体のチェックポイント機能）で、ほかは S と同じ。死亡と復帰の回数を公開する | 上と同じ文に「Roleplay モード、チェックポイントからの復帰 K 回」を足す |
| B | A の条件で、人間のゲーム内入力が少数あり、それぞれ全文と理由を公開する | 「人間による介入 M 回（一覧）」。RimMolt のクリア報告（人間の再指示 1 回とスクリーンショットの併用。02 §1.1.2）と同じ種類の主張になる |

- **モードの選び方（意見）。**
  - 開発と最初の主張は A（Roleplay）で行う。
  - 理由: Classic は 1 回の死が数十時間の実行を無にする。LLM のゲームでの前例（§8.5）から見ても、最初に S を狙うのは費用の割に得るものが少ない。
  - A の後に S に挑む。Wander は殺害で XP が入らず、戦闘の意味が変わるので、主張用には使わない（04 §2.6）。
- **再現性。**
  - RNG がシードされないので、軌跡は再現できない（01 K27）。
  - 再現できるのは「同じ manifest で走らせること」である。監査の手段は、ハッシュチェーンのログと VOD になる。

### 8.5 オーナーの問いへの回答

**Q1. すでにクリアされたという情報や、LLM に挑戦させた人はいるか。**

- 02 の調査では、**CoQ を LLM に自律プレイさせた公開事例は見つからなかった**。
  - CoQ 固有で見つかったのは、qud-accessibility（人間向けの読み上げ mod）と Archipelago mod（ランダマイザー）だけで、どちらも LLM エージェントではない（02 §1.12）。
  - 他のローグライクでも、Brogue、Cogmind、ADOM の LLM エージェントは見つからなかった（02 §2）。
- ただし、02 の否定検索は「CoQ を LLM でクリア」という問いに絞ったものではない。検索による否定は、存在しないことの証明にもならない。
- したがって、**「最初」は現時点では主張できない**。公表の前に、Steam Workshop、Reddit（r/cavesofqud）、YouTube、Twitch、GitHub、X を対象に、"Caves of Qud" と LLM/Claude/GPT/Gemini/agent/AI plays の組み合わせで的を絞った検索を行う。その日付と結果を manifest に添付する。

**Q2. いないとして、クリアまで導けたら何を主張できるか。**

- §8.4 の段位つきの主張になる。
- 既存の事例と比べて新しい点は 3 つある。
  1. **テキストだけで知覚した。** RimMolt のクリアはスクリーンショットを併用していた（02 §1.1.2）。
  2. **物語のあるローグライクをエンディングまで進めた。** BALROG の NetHack での進行度は低い水準にとどまる（02 §1.5）。
  3. **ハーネス入力の台帳が公開されている。**
- 反対に、主張できないこともある。
  - 「ネタバレなし」は主張できない（事前学習に wiki が含まれうる）。
  - 「ハーネスの支援なし」も主張できない（H1〜H4 がある）。
  - 「再現できる」も主張できない（RNG）。

**Q3. 現在の SOTA モデルなら、クリアできて当然か。**

- **当然ではない**、と考える根拠が揃っている。
  - 長期の目標を保つのが難しい: NetHack の進行度が低い（BALROG、02 §1.5）。知識と行動の乖離もある（knowing-doing gap）。
  - 知覚の失敗で詰まる: Claude Plays Pokémon は、画面の読み違いで長く足踏みした（02 §1.10）。
  - 文脈が長くなると壊れる: GPP は約 10 万トークンを超えるとループした（02 §1.11）。
  - クリアしたと報告された事例でも、学習ファイル、人間の再指示 1 回、スクリーンショットが必要だった: RimMolt（02 §1.1.2）。
- CoQ 固有の難しさもある。
  - メインクエストは推奨レベル 30〜40 まで続く（`Quests.xml` の Level 属性）。
  - モーダルと会話が多い。
  - 世界地図での長距離移動がある。
  - パーマデスまたはチェックポイントからのやり直しがある。
- **[推論]** クリアの成否は、モデルの素の能力よりも、ハーネスの質で決まる割合が大きい。
  - 観測の欠け、モーダルでの停止、文脈の管理、ループからの脱出がその中身である。
  - rimagent でも RimMolt でも、失敗の多くはインターフェースの欠陥だった（02 §1.2、§3.1）。
  - だからこそ、クリアした場合の主張には価値があり、ハーネスを公開することが主張の一部になる。

---

## 9. 配信への適性

### 9.1 視聴者に見えるもの

| 画面の領域 | 中身 | 出どころ |
|---|---|---|
| ゲーム画面（主） | tile 表示の Modern UI のまま | OBS のウィンドウキャプチャ |
| 思考の 1 行 | `act` に付いた `say`（120 文字以内、日本語） | Brain → オーバーレイ |
| 行動と結果 | `talk W` → `会話: Elder Irudad` などを直近 5 件 | events |
| モーダルの問答 | LLM に見せた選択肢と、LLM が選んだ番号 | `modal`/`answer` |
| 目標 | `CURRENT_GOALS` の 3 層 | notes.md |
| 進行 | クエストのはしご（§8.1）、レベル、ゲーム内ターン、決定数、死亡回数、**人間の介入 0**、ハーネス入力の件数 | ledger |
| 状態 | `thinking (strong)` / `acting` / `modal` / `paused` / `stall` と経過秒数 | 状態機械 |
| 監査のため | `seq` とハッシュの先頭 8 文字 | ledger |

### 9.2 ペース

- **行動の最小間隔は 1.2 秒**（Brain の設定）。
  - LLM の応答は数秒かかるので、この間隔が実際に効くのは fast 階層の連続行動のときくらいである。
  - エンジンの全速で進むと人間には追えない（01 K15）ので、この下限を設ける。
- **AutoAct の速度。** `OptionAutoexploreRate=10`（既定は 20。`Options.xml:126`、`ActionManager.cs:1567-1575` の sleep に効く）。
- **モーダルへの応答は 1.0 秒遅らせる。** 視聴者が選択肢を読めるようにするためである。H1 の自動クローズは 0.8 秒。
- **休息中の画面。** 休息中（`r`、`z`、`.N`）は `RenderBase` が早期に return する（`XRLCore.cs:2614-2618`）ので、画面が止まって見える。オーバーレイに "resting… turn N" を出す。
- **所要時間の目安 [推論]。**
  - メインクエストの完走を数万ターン、LLM の決定を 2 万〜4 万回、1 回あたり 5〜10 秒と置くと、実時間は 30〜110 時間になる。
  - 数日にわたる連続配信か、区切った回の配信になる。どちらでも、実行を止めて再開できる（`DECIDING` で止まっているだけなので）。

### 9.3 チャット

- チャットは表示するだけにし、LLM の入力には入れない（02 A9、プロンプトインジェクション）。
- 視聴者の提案を採る場合は、人間の運営者が `note(CORE_RULES)` に書き写す。そうした場合は台帳の `human_input(kind=advice)` として記録し、主張の段位を B にする。

---

## 10. プラットフォームと更新への耐性

### 10.1 Apple Silicon と Harmony

- **Harmony を使わないので、arm64 ネイティブで動く。**
  - Rosetta も、`Managed/0Harmony.dll` の 2.4.2 への差し替えも要らない（04 §4.6）。
  - 同梱の 2.2.2 はネイティブでは `PatchAll` が EACCES で失敗するが、P2 はその経路をそもそも通らない。
- **mod が使う公式のフック。**
  - `[PlayerMutator]`、`IPlayerSystem.HandleEvent(CommandTakeActionEvent)`（`stable/XRL/IGameSystem.cs:907`）
  - `XRLCore.Register*Callback`（`XRLCore.cs:604-663`）
  - `uiQueue`/`gameQueue`（`GameManager.cs:148, 150`）
  - どれも公式 wiki が推奨する「Harmony は最後の手段」という方針と合う（02 §1.12.4）。

### 10.2 隔離プロファイル

04 §4.9 の手順に従い、`-savepath "$HOME/Library/Application Support/Freehold Games/CavesOfQud-llm"` で起動する。`Local/PlayerOptions.json` は事前に書いておく **[要実測: PR0。事前に書いたものが採用されるか]**。

| オプション | 値 | 理由 |
|---|---|---|
| `OptionAllowCSMods` | Yes | 既定は No で、C# の mod が無効になる（`ModInfo.cs:126-129`） |
| `OptionModernUI` | Yes | §4 の前提。Plan B では No |
| `OptionUseTiles` | Yes | 配信の見た目のため。観測は `BackupChar` で影響を受けない |
| `OptionMusicBackground` | **Yes** | `Application.runInBackground`（`Options.cs:1445-1454`）。§4 の前提 |
| `OptionAllowSaveLoad` | No（主張用）/ Yes（開発用） | セーブのやり直しを防ぐ |
| `OptionAutoexploreRate` | 10 | §9.2 |
| `OptionDisablePermadeath` / `OptionAllowReallydie` | No / No | 主張の条件 |
| `Language` | en | 知識ベース（英語の XML）と一致させる |
| `OptionDismemberAsPopup` / `OptionPopupJournalNote` | No / No | ポップアップの数を減らす（`data/opt_table.md` の 151, 154） |
| `OptionAbilityCooldownWarningAsMessage` / `OptionShowScavengeItemAsMessage` | Yes / Yes | 同上（152, 153） |

### 10.3 QudJP との共存

- オーナーの本番プロファイル（`Language=ja`、QudJP を Rosetta で起動）には触れない。P2 の mod は隔離プロファイルにだけ置く（`<savepath>/Mods/QudBridge` へのシンボリックリンク。04 §4.8）。
- 同じプロファイルで併用することは技術的にはできる（P2 は Harmony を使わない）。しかし、観測テキストが日本語になり、K1〜K2 の知識ベースと合わなくなるので勧めない。
- 日本語での配信は、オーバーレイの `say` で賄う。

### 10.4 ゲームの更新への耐性

- **起動時の自己検査（`QBCompat.cs`）。**
  - 依存するメンバーをリフレクションで確かめる。確かめる対象は次のとおり。
    - `ActionManager.SkipPlayerTurn`、`XRLCore.RegisterOnEndPlayerTurnCallback`、`XRLCore.EnableAnimation`
    - `PopupMessage.commandCallback`/`controller`/`OnActivateCommand`、`UITextSkin.text`（`stable/XRL.UI/UITextSkin.cs:54`）、`QudMenuItem.text`/`command`/`hotkey`（struct。`stable/Qud.UI/QudMenuItem.cs:10-14`）
    - `PickTargetWindow.currentMode`、`GameManager.focused`、`Keyboard.PushCommand`
    - `StatusScreen.BuyStat`、`SkillsAndPowersScreen.SelectNode`、`EndGame.IsAnyEnding` など、約 25 件
  - 1 つでも欠けていれば、`[QB][compat] FAIL <member>` を出して操作を拒否し、`hello` で Brain に伝える。静かに誤動作することはない。
  - これはユーザーの指針「機械的に検査できる規則は決定的なツールに置く」の実装である。
- **ビルドシンボル `BUILD_2_0_211` による条件コンパイル**（04 §4.4）。版が変わったら、コンパイル時に警告を出す。
- **引用はシンボル名を主キーにする。** 行番号は腐る（01 §2.2-2.3。2.0.210 → 2.0.211 でほぼ全件ずれた）。本書の行番号は 2.0.211.56 での参照用である。
- **主張用の実行中は Steam の自動更新を止める。** 「起動時のみ更新」に設定し、版は manifest に記録する。
- **セーブへの影響。** `IGameSystem` はセーブに書き込まれる（03 §4.3）。mod を外したプロファイルでは、そのセーブをロードしない。隔離プロファイルなので実害はない。

---

## 11. マイルストーン（最初の 3 週間）

### 11.1 先に済ませるランタイムプローブ（day 1〜1.5、合計 1〜1.5 日）

すべて隔離プロファイルで行う。手段は、使い捨ての `[WishCommand]` と、Brain の試験用サーバー（v1 `app.py` のフェーズ切り替えの発想を使う。01 §4.2）。

| # | プローブ | 合格の条件 | 失敗したとき |
|---|---|---|---|
| PR0 | 読み込みとコンパイル: `Newtonsoft.Json`、`ClientWebSocket`、`QBCompat` を含む mod。事前に書いた `PlayerOptions.json` と `ModSettings.json` が採用されるか | `build_log.txt` に `Success :)`、`Player.log` に `[QB][compat] OK` が出る | Newtonsoft が使えなければ手書き JSON にする。オプションが採用されなければ、初回だけ手で設定する |
| PR1 | E1 の実行器: CTA → `Pending` → EndPlayerTurn で `PushCommand` を呼ぶ。`CmdMoveE`、`CmdWait`、`CmdAutoExplore`、`CmdUseE`、`CmdGetFromE`、能力 1 つ、壁への `CmdMoveN`（エネルギーを使わない）で試す | 各コマンドが 1 手で実行される。エネルギーを使わないものは `SkipPlayerTurn` で CTA に戻る。1 手の遅延が 100 ms 未満 | **M1 は E0（CTA 直接の Move/Attack/PassTurn）で進め**、並行して原因を調べる |
| PR2 | 長いブロック: CTA ハンドラで 120 秒待つ。その間 `gameQueue` を回す | UI が応答し続ける。ツールチップが出る。ゲームが落ちない | 待機を 1 秒ごとの `RenderBase` 呼び出しに変える |
| PR3 | フォーカス: OBS を前面にした非フォーカス状態で、`runInBackground` を有効にし、フォーカスを強制する | 決定の速度、AutoAct の歩数/秒、`uiQueue` の処理が、フォーカスがあるときの 8 割以上 | 専用のディスプレイで常に前面に置く運用にし、フォーカス強制の副作用を調べる |
| PR4 | モーダル: `CmdWaitMenu`（`PickOption`、`XRLCore.cs:921-957`）、`CmdWaitN`（AskNumber）、Joppa の NPC との会話、ShowYesNo（試験用のウィッシュで出す）、`Popup.Show` | `FindObjectsOfType<PopupMessage>` で読めて、`OnActivateCommand` で解決できる。copyWindow の経路も解決できる | Plan B（`OptionModernUI=No`）を同じ手順で試す |
| PR5 | ピッカー: `CmdTalk` と `CmdOpen` に `PushKey(NumPadN)` で答える | 方向どおりに会話や開扉が始まる | 会話は `CmdUse{Dir}`（smart use）で代替できるか調べる |
| PR6 | 観測のサイズと忠実度: text と tile の両モードで 20 回分の観測をダンプする | トークン数が §2.4 の範囲に入る。glyph が両モードで一致する | 局所的な窓（41×21）の表示に切り替える |

### 11.2 マイルストーン

| # | 時期 | 到達すること | 完了の判定 |
|---|---|---|---|
| **M1: 最初の自律 LLM ターン** | **day 3** | Joppa で、LLM（strong 階層）が観測を受け取り、`act` を返し、E1（または E0）で実行される。これを 50 決定、人間の入力なしで続ける | `events.jsonl` に 50 組の決定と行動があり、`human_input` が 0 件。オーバーレイは使わず、ログだけで確かめる |
| M2 | week 1 の終わり | モーダル（通知の自動クローズ、選択肢、Yes/No、会話）、free tools（`look`、`inventory`、`character`）、`goto`/`explore`、outcome のフィードバックが揃う。Elder Irudad と会話して「What's Eating the Watervine?」を受ける | 1 時間の無人実行で stall が 0 件。会話の選択を LLM が行う |
| M3 | week 2 の終わり | notes/summary/`kb_search`（K0〜K2）、コストの階層、E2（アイテム、装備、`raise`/`learn`/`buy_mutation`）、Roleplay の死亡方針（H4）、切断と wake、オーバーレイ v0 | 「What's Eating the Watervine?」を自律で完了する。2 時間の無人実行 |
| M4 | week 3 の終わり | 取引の実行器、未知のモーダルの警報、ハッシュチェーンのログと manifest と台帳、私的な試験配信（2〜3 時間） | 「Fetch Argyve a Knickknack」を完了し、台帳を自動で集計する。この時点で主張用のモード（A か S か）を決める |

---

## 12. 最もリスクの高い前提

| # | 反証できる主張 | なぜ重要か | 懐疑的な読者が読むべき箇所 | 実測が要るか |
|---|---|---|---|---|
| R1 | EndPlayerTurn コールバックから `Keyboard.PushCommand` で積んだ移動以外のコマンドは、同じ PlayerTurn の次の反復で必ず消費される。エネルギーを使わなかったコマンドは、`SkipPlayerTurn=true` と `KeyEvent.Set()` で CTA に戻せる。EndPlayerTurn を通らずに抜ける経路（`:917, 1324, 1926, 1940, 2103`）でも、次の CTA の入口で outcome を二重実行なしに確定できる | E1（既定の実行器）全体の前提。崩れると E0 に戻り、HUD が更新されず、`CmdWait` などが別物になる | `stable/XRL.Core/XRLCore.cs:690-780`（Begin コールバック `:693` → Clear `:734` → focus `:737-740` → 取り出し `:754-780`）、`:2355-2396`（End コールバック → IdleWait → SkipPlayerTurn）、`stable/ConsoleLib.Console/Keyboard.cs:723-726, 825-850, 926-936`、`stable/XRL.Core/ActionManager.cs:755, 789, 798, 1584-1611` | はい（PR1） |
| R2 | `Application.runInBackground=true`（`OptionMusicBackground`）なら、非フォーカス時も Unity の Update が回って `uiQueue` が処理される。`GameManager.focused` と `XRLCore.bThreadFocus` を強制すれば、PlayerTurn のフォーカス待機を入力の消失なしに回避できる | 配信中は OBS などにフォーカスが移る。これが崩れるとモーダルに答えられず、E1 も止まる | `stable/XRL.UI/Options.cs:1445-1454`、`stable/GameManager.cs:404-425, 1920-1929, 2963`、`stable/XRL.Core/XRLCore.cs:223, 737-740`、`stable/ConsoleLib.Console/Keyboard.cs:938-954` | はい（PR3） |
| R3 | メインクエストの道中で出会うブロッキングなモーダルは、どれも `PopupMessage` のインスタンス（getWindow か copyWindow）か、`getvk` のピッカーである。UI スレッドから内容を読み、`OnActivateCommand`/`OnSelect`/`PushKey` で解決できる。例外（取引、ステータス画面、本）は、避けるか、専用の実行器で動かせる | Harmony なしでモーダルを扱えるかどうかが、Rosetta の要否とプロセス全体の構成を決める。これが崩れると Plan B か C になる | `stable/XRL.UI/Popup.cs:801-921, 1433-1450, 1571-1615, 1700-1760, 2251-2275`、`stable/Qud.UI/PopupMessage.cs:18-249, 721-800, 926-1066`、`stable/XRL.UI/PickDirection.cs:28-60`、`stable/XRL.UI/TradeUI.cs:344-470`、`stable/Qud.UI/TradeScreen.cs:245-300, 754, 874` | はい（PR4、PR5）。静的には一部だけ確認済み |
| R4 | CTA ハンドラでゲームスレッドを数分止めても（LLM の遅延）安全である。ゲーム本体も、ポップアップ（`Task.Wait`）とステータス画面（`.Result`）で同じようにゲームスレッドを止めている。待機中に `gameQueue.executeTasks()` を回せば、UI のツールチップなども止まらない | v1 の 500 ms 同期待ちの限界（01 §5.2-4）を越えるための中心の仕組み | `stable/XRL.UI/Popup.cs:908`、`stable/XRL.UI/Screens.cs:80, 125`、`stable/XRL.Core/XRLCore.cs:2600-2605`、`stable/QupKit/ThreadTaskQueue.cs:33, 135`、`stable/XRL.UI/Look.cs:284, 317` | はい（PR2） |
| R5 | E2 のゲーム関数（`StatusScreen.BuyStat`、`BuyRandomMutation`、`SkillsAndPowersScreen.SelectNode`、`InventoryActionEvent.Check`、`EquipmentAPI.*`）は、CTA 内のゲームスレッドから呼んでも、ステータス画面から `APIDispatch`（スレッドプール）経由で呼んだときと同じように振る舞う。エネルギーの消費と、確認ポップアップの出方も同じである | 所持品の管理とキャラクターの成長をこの経路に頼っている。崩れると、ステータス画面を UI スレッドから操作する複雑な実行器が要る | `stable/XRL.UI/StatusScreen.cs:62-90, 652`、`stable/XRL.UI/SkillsAndPowersScreen.cs:141-229`、`stable/XRL.World/InventoryActionEvent.cs:110-175`、`stable/Qud.API/EquipmentAPI.cs:378-501`、`stable/XRL.UI.Framework/APIDispatch.cs:10-80`、`stable/Qud.UI/InventoryAndEquipmentStatusScreen.cs:222-426` | 一部（静的な読解で大半は判定できる。エネルギーの消費は実測） |
| R6 | メインクエストの必須の段階に、§3.2 の文法と §4 のモーダル経路で扱えない入力面（端末 UI、Tinkering 画面での必須の製作、ミニゲームなど）はない | ひとつでもあれば、エンディングに到達できない。台帳に人間の入力が入り、主張の段位が下がる | `Base/Quests.xml`（各 quest の System 属性。例: `WeirdwireConduitSystem`、`ReclamationSystem`）、`Base/Conversations.xml` の該当ノード、`stable/Qud.UI/CyberneticsTerminalScreen.cs`、`stable/XRL.UI/` の Tinkering 関連、`stable/XRL.World.Conversations.Parts/EndGame.cs:142-176`（エンディングは会話の選択で始まる） | 静的なレビューでかなり判定できる。最後は実走 |
| R7 | 世界地図での移動（ゾーン間の移動、`CmdMoveU`/`D` による出入り、世界地図上の `CmdMove*`）は、テキストの観測（世界地図の glyph と地名）と文法だけで LLM が扱える。世界地図では `explore` が無効（`XRLCore.cs:1920-1925`）なので、代わりの `goto` が機能する | CoQ の進行は、集落の間を長距離移動することを前提にしている。これが崩れると、中盤以降で進めなくなる | `stable/XRL.Core/XRLCore.cs:908-919, 1920-1925, 2323-2327`（世界地図で使えないコマンドの検査）、`stable/XRL.Core/XRLCore.cs:2452-2458`（世界地図の描画は ExploreAll/VisAll）、`stable/XRL.World/Zone.cs:7127`（`IsWorldMap`） | はい（M3 以降） |
| R8 | 1 回の決定の観測は 2.2k トークン以下に収まり、`BackupChar` による glyph の復元は 2.0.211.56 の tile モードでも欠けない | コスト（数万回の決定）と観測の忠実度を決める | `stable/ConsoleLib.Console/ConsoleChar.cs:360-375, 392-420`、`stable/XRL.Core/XRLCore.cs:2486-2509`、`stable/XRL.World/Cell.cs:547, 589-592, 681-705`（`OverlayTile`） | はい（PR6） |

---

## 付録 A: 引用の自己点検（stable = 2.0.211.56 で目視した箇所）

既存のレポートの引用のうち、次のものを自分で開いて確かめた。★ は、01〜04 の記述と食い違っていた箇所、または補足が要った箇所である。

| # | 主張 | 確かめた箇所 | 結果 |
|---|---|---|---|
| 1 | CTA の Check が false なら continue | `stable/XRL.Core/ActionManager.cs:789-791` | 一致。`:798` のエネルギーゲート、`:805` の AutoAct、`:1584-1587` の SkipPlayerTurn、`:1611` の PlayerTurn、`:1618-1621` の RenderBase も一致 |
| 2 | PlayerTurn の冒頭での Clear とフォーカス待機 | `stable/XRL.Core/XRLCore.cs:734, 737-740` | 一致。Begin コールバックは Clear より前（`:693`）、End コールバックは反復ごと（`:2358`）で、どちらも本書の設計の根拠 |
| 3 | 未知の ID は `CommandEvent.Send` に渡る | `stable/XRL.Core/XRLCore.cs:2322-2334` | 一致（世界地図での可否の検査つき） |
| 4 | Modern のポップアップはゲームスレッドを `Task.Wait` で止める | `stable/XRL.UI/Popup.cs:801-921`（`:908`） | 一致。★ UI スレッドから呼ばれた場合は `NewPopupMessageAsync` に分岐する（`:803-822`） |
| 5 | `OnActivateCommand` で答えられる | `stable/Qud.UI/PopupMessage.cs:926-934` | 一致。★ `commandCallback`/`selectCallback`/`controller`/`inputBox` はすべて public（`:20-42`）。`ShowPopup` が `menuData`/`bottomContextOptions` を設定する（`:779-782`） |
| 6 | 会話は `ShowConversation` の戻り値で分岐する | `stable/XRL.UI/ConversationUI.cs:514-537` | 一致。-2 のとき `Trade.ShowScreen()`（`:528`） |
| 7 | AfterRender は `_Buffer` を渡し、tile では BackupChar に退避される | `stable/XRL.Core/XRLCore.cs:652-655, 2506-2509`、`stable/ConsoleLib.Console/ConsoleChar.cs:392-420` | 一致 |
| 8 | IdleWait の後に SkipPlayerTurn で抜ける | `stable/XRL.Core/XRLCore.cs:2390-2396` | 一致 |
| 9 | `focused` のセッターが入力を消す | `stable/GameManager.cs:404-425` | 一致 |
| 10 | kbhit は非フォーカス時に 200 ms 待つ | `stable/ConsoleLib.Console/Keyboard.cs:938-954` | 一致。`bThreadFocus` は `XRLCore.cs:223` の public static |
| 11 | `runInBackground` は MusicBackground に連動する | `stable/XRL.UI/Options.cs:1445-1454` | 一致 |
| 12 | `SkipPlayerTurn` の型 | `stable/XRL.Core/ActionManager.cs:25` | ★ **インスタンスフィールド**（`public bool SkipPlayerTurn;`）。03 §3.4 の「static bool」は誤り。v1 のコードは `The.Game.ActionManager.SkipPlayerTurn` で正しく使っている |
| 13 | 隠しコマンドの行 | `stable/XRL.Core/XRLCore.cs:1655-1678, 2150-2173` | 一致（`data/hidden.md` の行番号もそのまま有効） |
| 14 | AutoAct の Setting の文字列 | `stable/XRL.Core/ActionManager.cs:855-1441`（case `!`/`M`/`P`/`U`/`X`/`G`/`d`/`?`/`<`/`>`/`g`/`o`/`z`/`r`/`a` と、default の `.N`） | 一致。★ `CmdMoveToBorder:x,y` は、隣接していなければ `M x,y` になる、ゾーン内の汎用 goto である（`XRLCore.cs:908-919`） |

**stable の版についての訂正。** 01 と 04 は「`coq-decompiled_stable` は 2.0.211.50」と書いているが、現在は `AssemblyVersion("2.0.211.56")` である（`stable/Properties/AssemblyInfo.cs:8`。ディレクトリの更新時刻は 2026-09-25 17:14）。したがって、01 の「[再確認] stable」の行番号は古い版のもので、03 の `NEW/` の行番号が現在の stable と一致する。

## 付録 B: 本書で新たに確かめた事実（01〜04 にないもの）

- **CTA で直接行動すると、PlayerTurn の Begin/End コールバックが走らない。** そのため `PlayerStatusBar` の更新が止まる（`stable/Qud.UI/PlayerStatusBar.cs:276-277`）。`EnqueuePlayerCell`/`CheckPlayerLocations` はデバッグ用の整合性チェックで、影響はない（`stable/XRL.World/GamePlayer.cs:32-58`）。
- **`EnableAnimation` が false だと PlayerTurn が `GetNextCommand` でキーを待つ**（`XRLCore.cs:754, 900`）。`CmdToggleAnimation`（`:1703-1705`）は許可リストから除く。
- **Roleplay での死亡は `PickOption` の 4 択になる**（`stable/XRL/CheckpointingSystem.cs:114`）。Classic では `ShowSpace` になる（`:85-104`）。
- **エンディングの判定は `EndGame.IsAnyEnding` と `EndType` のゲーム状態でできる**（`stable/XRL.World.Conversations.Parts/EndGame.cs:67-113`）。`gocoda`/`goend` のウィッシュ（`:295, 316`）が存在するので、`CmdWish` は禁止する。
- **レベルアップのポイントを使うための static 関数がある。** `StatusScreen.BuyStat`（`stable/XRL.UI/StatusScreen.cs:62`）、`StatusScreen.BuyRandomMutation`（`:652`）、`SkillsAndPowersScreen.SelectNode`（`stable/XRL.UI/SkillsAndPowersScreen.cs:141`）。
- **PlayerTurn には、EndPlayerTurn コールバックを通らずに抜ける経路がある。** `CmdAutoExplore`/`CmdAutoAttack` の `return;`（`XRLCore.cs:1926, 1940`）、隣接していない `CmdMoveToBorder` の `break;`（`:917`）などである。そのため、outcome は CTA の入口で確定する（§3.4）。
- **Modern の取引画面には、UI スレッドから操作できる public のメソッドがある。** `setHowManySelected`、`HandleOfferTrade`、`Cancel`（`stable/Qud.UI/TradeScreen.cs:275, 754, 874`）。
