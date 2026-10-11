# P5. Evidence-First: 台帳つきターンブリッジ

> 提案者: Opus 5.5 worker（レンズ: 「主張の防御可能性」と「反復の速さ」）／ 2026-09-25
> 前提資料: `docs/exploration/01`〜`04`。エンジンの行番号は `/Users/sankenbisha/Dev/coq-decompiled_stable` による（以下 `D/`）。
> **重要な訂正**: `D/Properties/AssemblyInfo.cs:8` は現在 `AssemblyVersion("2.0.211.56")` である。01/02 は同じツリーを 2.0.211.50 と書いているが、ツリーはその後更新されていた。したがって 03 が `NEW/` として挙げた行番号は、そのまま `D/` に当てはまる。インストール済みの Steam ビルドは `appmanifest_333640.acf` で `buildid 25520692` と確認した。
> 推論には **[推論]** を付ける。外部の事実のうち WebFetch や検索の要約で得たものは **[C]** とする。

---

## 0. 自分で確認した引用（スポットチェック）

03/04 の引用を再利用する前に、次の箇所を `D/` で目視確認した。どれも 03 の記述と一致した。

| # | 箇所 | 確認した内容 |
|---|---|---|
| S1 | `D/XRL.Core/XRLCore.cs:734` | `PlayerTurn` 冒頭の `Keyboard.ClearMouseEvents(LeaveMovementEvents: true)` |
| S2 | `D/XRL.Core/XRLCore.cs:737-740` | `while (!GameManager.focused && Game.Running) Thread.Sleep(200);`（フォーカス待機） |
| S3 | `D/XRL.Core/XRLCore.cs:652-663` | `RegisterAfterRenderCallback`（Add のみ）と `RegisterNewMessageLogEntryCallback`（重複を防ぐ） |
| S4 | `D/XRL.Core/XRLCore.cs:2322-2334` | switch の `default:` が `CommandEvent.Send(The.Player, text2)` を呼ぶ |
| S5 | `D/XRL.Core/XRLCore.cs:2600-2618` | `RenderBase` は CoreThread 上なら `gameQueue.executeTasks()` を呼ぶ。休息中は早期 return する |
| S6 | `D/XRL.Core/ActionManager.cs:743, 789, 798, 805, 810-814` | BTA の Check、CTA の Check から `continue`、プレイヤーのエネルギーゲート、`AutoAct.IsActive()`、`kbhit()` による AutoAct の中断 |
| S7 | `D/XRL.UI/Popup.cs:801-921` | `WaitNewPopupMessage` は、UI スレッド以外から呼ばれると `uiQueue.awaitTask` を使い、`complete.Task.Wait()`（`:908`）でゲームスレッドを止める |
| S8 | `D/XRL.UI/Popup.cs:1433-1443` | `AskString` は Modern UI では `AskStringAsync(...).Result` になる |
| S9 | `D/GameManager.cs:404-426, 1920-1928` | `focused` の setter（false から true になるとき入力をクリアする）、`OnApplicationFocus` が `bThreadFocus` と `focused` を書く、`OnApplicationPause` |
| S10 | `D/ConsoleLib.Console/Keyboard.cs:723-726, 938-954` | `PushCommand` の実体は `PushMouseEvent("Command:"+cmd)`。`kbhit` は非フォーカス時に `KeyEvent.WaitOne(200)` で待つ |
| S11 | `D/XRL.UI/ConversationUI.cs:514-537` | `Render()` が `Popup.ShowConversation` の戻り値で分岐する（-1 Escape、-2 Trade、-3 Look、0 以上は `Select`） |

このほか、本提案のために新しく読んだ箇所は各節で引用する。主なものはエンディング判定（`EndGame.cs`、`ThinWorld.cs`、`AscensionCable.cs`、`ShevaStarshipControl.cs`）、ポップアップの合流点（`Popup.cs:751, 801` とその呼び出し元）、能力値・スキルの購入（`StatusScreen.cs:61`、`SkillsAndPowersScreen.cs:141`）、シード（`XRLGame.cs:1505-1515`、`QudGameBootModule.cs:215-227`）である。

---

## 1. 概要と狙い

### 1.1 一文で

**CoQ の CTA（`CommandTakeActionEvent`）と、ゲームスレッド上のポップアップ関数の入口の 2 か所だけを「判断点」とする。判断点ではゲームスレッドを止め、外部ハーネスに観測を渡して答えを待つ。観測と答えはすべて、ハッシュで鎖状につないだ台帳（ledger）に記録する。** 台帳に載らない手段では、プレイヤーの行動も選択肢の決定も起こらない。そういう構造にして、「LLM がクリアした」という主張を台帳だけで検証できるようにする。

### 1.2 最適化する対象

1. **主張の防御可能性**。2026-09-21 の NetHack ascension（GPT 6 Astra）は、ハーネスと証拠アーカイブを公開した。著者自身も「ローカルのハッシュは整合性を示すだけで、独立した出所の証明にはならず、人間が介入しなかった証明にもならない」と認めている [C]（https://github.com/kenforthewin/nethack_astra ）。NetHack にはサーバーのダンプという第三者の記録があった。CoQ はオフラインの 1 人用ゲームで、その役割を果たすものがない。そこで本提案は次の 4 点で補う。
   - (a) 行動と決定の経路を 1 本に限る（**帰属の完全性**）
   - (b) 帰属できない事象を検出して記録する（**介入の検出**）
   - (c) 台帳の先頭ハッシュを配信の VOD と git push で外部の時刻に結びつける（**外部アンカー**）
   - (d) 固定プロトコルの API ループを「主張用の走行」とし、Claude Code のような対話型クライアントの走行とはラベルで分ける
2. **反復の速さ**。v1 の失敗（01 §5）を繰り返さないために、次のようにする。
   - LLM が 1 手目を打つのは第 1 週とする。
   - 証拠の仕組みは、最初は JSONL と SHA-256 と検証スクリプト 1 本だけで始める。
   - テストは 3 層で、ゲームを起動せずに回る部分を最大にする。

### 1.3 意図して捨てるもの

- **最速の配信映え**。判断点ごとにゲームスレッドを止めるので、画面は LLM が考えている間ずっと静止する。配信の工夫は §9 で述べる。
- **Harmony を使わない純粋さ**。モーダルを取りこぼすと人間のクリックが必要になり、主張が「介入あり」に格下げされる。そのため第 2 週からは Harmony を Rosetta 上で使う。第 1 週の M1 は Harmony なしで成立させる。`0Harmony.dll` の差し替えは採らない。証拠マニフェストに「ゲームファイルは無改変」と書けなくなるからである。
- **Modern UI の画面を操作すること**。インベントリ、キャラクター、スキルの画面は開かない。同じことを直接 API で行う（03 §2.8 の方針を踏襲）。
- **完全な再現性**。戦闘の RNG は世界シードとは別系統である（`D/XRL.Rules/Stat.cs:26-36` のシードなし `new Random()`。`ReseedFrom` は `:101-109`）。そのうえ LLM は確率的に動く。再現できるのは「世界」と「判断に使った入力」までである。「同じ結果」は再現できない。これは主張の限界として明記する。
- **多エージェントの記憶アーキテクチャ**。記憶は 1 つのノートファイルと、要約つきのエピソードの境界だけで始める（§7）。

---

## 2. 観測

### 2.1 使う面（すべてゲームスレッドで読む）

| 観測要素 | 面 | 引用 | 人間と同じ情報量か |
|---|---|---|---|
| 局所マップ（グリフ格子） | `XRLCore.RegisterAfterRenderCallback` で受け取った source buffer から、`_Char` → `BackupChar` → 空白の順にグリフを復元する（v1 の K5〜K7） | `D/XRL.Core/XRLCore.cs:652-655`、`D/ConsoleLib.Console/ConsoleChar.cs:392-420`、呼び出し箇所 `XRLCore.cs:2464, 2508` | 同じ（描画されたものだけ。可視セルと既探索セルの記憶を含む） |
| 自分の状態 | HP、Statistics、`Stomach.FoodStatus/WaterStatus`、Effects、AP/SP/MP、重量、時刻 | 03 §2.4、`D/Qud.UI/PlayerStatusBar.cs:310-422` | 同じ（サイドバーとキャラクター画面に出る量） |
| 周辺の実体 | 可視セル上の `GameObject` について、表示名、方角と距離、`Look.GenerateTooltipContent` の SubHeader と WoundLevel | `D/XRL.UI/Look.cs:239-251`、`D/XRL.World/Cell.cs:3469-3497` | **同じにそろえる**。他者の `hitpoints` は出さず、負傷度の文言だけを出す。表示名は UI と同じ経路で取り、未鑑定のアーティファクトの本名を漏らさない |
| メッセージ | `XRLCore.RegisterNewMessageLogEntryCallback` で push を受け、ターン間の差分を送る。色コードは `ColorUtility.StripFormatting` で除く | `D/XRL.Core/XRLCore.cs:657-663`、`D/XRL.Messages/MessageQueue.cs:138-150` | 同じ（メッセージログ） |
| クエストとジャーナル | `XRLGame.Quests` / `FinishedQuests`、`Quest.StepsByID`、`JournalAPI` | `D/XRL/XRLGame.cs:145-148`、`D/XRL.World/Quest.cs:11-56`、`D/Qud.API/JournalAPI.cs:27-41` | 同じ（クエスト画面とジャーナル画面） |
| 開いているモーダル | Harmony prefix が受け取るポップアップの引数（§4） | `D/XRL.UI/Popup.cs:751, 801` | 同じ（ポップアップの本文と選択肢） |
| 現在の UI ビュー（監視用） | `GameManager.CurrentGameView` | `D/GameManager.cs:469-480` | LLM には渡さない。watchdog 専用 |

**使わない面**: `ScreenBuffer.ToString()` と `CurrentBuffer`（tile モードでは空白になる。03 §1.3）。スクリーンリーダー（存在しない。04 §2.5）。画像はいっさい使わない。

**モード依存**: LLM への観測は Zone/Cell/GameObject の API とコールバックから作るので、**tile/text のモードにも Modern/Legacy の UI にも依存しない**。唯一グリフ格子だけは描画経路を通る。tile モードでは `BackupChar` の復元が要る（v1 で実証済み。2.0.211.56 でも `ConsoleChar.Set` の中で維持されている）。配信の見栄えのため、既定は tile モードと Modern UI のままとする。

### 2.2 取得のタイミング

CTA のハンドラの中で、次の順に処理する。

1. `The.Core.RenderBase()` を呼ぶ（`D/XRL.Core/XRLCore.cs:2600-2665`）。`PlayerTurn` がキー待ちの前に描画するのと同じ扱いで、画面を最新にする。その結果 AfterRender コールバックが走り、グリフ格子がコピーされる。
2. 状態と実体を読み、メッセージの差分をまとめる。
3. `decision_request` を送り、答えが来るまでブロックする（§5）。

可視マップは描画時に作り直される（03 §2.2 の注意）。1. を先に行うことで、視界の 1 フレーム遅れを避けられる **[推論: P2 で実測]**。

### 2.3 LLM に渡す表現（1 ターンの実例）

ハーネスは 2 つの表現を持つ。台帳には **JSON**（完全な構造化データ）を記録し、LLM には **レンダリングしたテキスト**（トークン効率がよい）を渡す。テキストは JSON から決定的に生成し、その生成器のバージョンを台帳に記録する。

以下は作例である。値は架空で、実測値ではない。

```text
=== T18342  Joppa (JoppaWorld.11.22.1.1.10)  surface  3rd of Ut yara Ux, 13:40 ===
HP 34/41  AV 6  DV 8  QN 100  MS 100  Lv6 XP 1830/2250  AP 0 SP 20 MP 1
Food: Sated  Water: Quenched  Carried 132/200 lbs  Drams: 5 fresh water
Effects: none
Last action: attack E -> resolved (1 action), you are at (38,12)
New messages:
  - You hit the snapjaw scavenger (x1) for 5 damage!
  - The snapjaw scavenger misses you.
View 41x15 (@ you, rows N->S, fog = ' '):
          ###########
          #.........#     ""  ""
   ...    #...s.....+.......
   ...    #....@s...#   ;;
          #.........#
          #####+#####
Entities (visible):
  e1 s snapjaw scavenger  E1   hostile  "wounded"
  e2 s snapjaw hunter     E2   hostile  "fine"
  e3 + wooden door        E5   -
  e4 ; watervine          SE6  -
Quest: Fetch Argyve a Knickknack / "Find a knickknack" (active)
Pending: none   Autoexplore: available   Notes: 3 active goals (see notes)
```

同じ内容の JSON の抜粋（台帳側）は次の通り。

```json
{"kind":"decision_request","req":"t18342-0","game_turn":18342,"zone":"JoppaWorld.11.22.1.1.10",
 "player":{"hp":34,"hpmax":41,"pos":[38,12],"stats":{"AV":6,"DV":8,"QN":100,"MS":100},"lvl":6,
           "xp":[1830,2250],"pts":{"AP":0,"SP":20,"MP":1},"food":"Sated","water":"Quenched","effects":[]},
 "last_action":{"verb":"attack","dir":"E","energy_spent":true,"pos_changed":false},
 "messages":["You hit the snapjaw scavenger (x1) for 5 damage!","The snapjaw scavenger misses you."],
 "view":{"w":41,"h":15,"origin":[18,5],"rows":["...","..."]},
 "entities":[{"id":"e1","gid":"<GameObject.ID>","glyph":"s","name":"snapjaw scavenger","rel":"E1","attitude":"hostile","wound":"wounded"}],
 "quests":[{"name":"Fetch Argyve a Knickknack","step":"Find a knickknack","finished":false}],
 "modal":null,"obs_renderer":"v0.3.1"}
```

- **ID の方針**: LLM に見せる ID は、判断ごとに振る短い別名（`e1`…）にする。台帳には対応表を残す（`gid` は `GameObject.ID`。v1 の K10 にある、ID 取得の副作用に注意する）。rimagent の教訓（生の座標を扱わせない。02 A5）に従い、行動で使う位置は方角、別名、ランドマーク名で指定させる。
- **敵対の判定**: `IsHostileTowards` を使う（`D/XRL.World/GameObject.cs:11424`）。人間も Look の文言（SubHeader の感情）で知ることができるので、情報量は同じとみなす **[推論: P9 で Look の文言と照合する]**。

### 2.4 サイズの見積もり

| 部分 | 文字数 | トークン（目安） |
|---|---:|---:|
| ヘッダ・自分の状態・直前の行動 | 350 | 120 |
| 新メッセージ（平均 3〜8 行） | 300〜800 | 80〜220 |
| 局所マップ 41×15 | 615 + 改行 | 350〜600（記号列は 1 トークンあたり 1〜2 文字と仮定） |
| 実体一覧（平均 4〜12 件） | 250〜800 | 80〜250 |
| クエスト・保留・ノートへのポインタ | 200 | 60 |
| **合計** | | **約 0.7k〜1.3k（平常時）、戦闘・町中で 2k 程度** |

ゾーン全体（80×25）は、無料ツール `map` で要求されたときだけ出す（約 1.2k〜2k トークン）。これは rimagent の「グリッドは要求時のみ」に倣っている。**実測は M1 の必須計測項目**とし、`usage` から判断ごとに記録する。

---

## 3. 操作

### 3.1 文法

ツールは 2 種類に分ける（dcss-ai の P3 に倣う）。

- **無料ツール**: ゲーム内の時間を進めない。1 判断あたり最大 6 回まで使える。
- **行動ツール**: ちょうど 1 回だけ使え、判断を終える。

行動ツールの結果には、次の判断の観測を自動で付ける。行動の成否は、戻り値ではなく**行動後の状態**から判定する（02 P4）。

| 種別 | ツール | 実行方法（すべて CTA 内、ゲームスレッド） | 引用 |
|---|---|---|---|
| 移動 | `move(dir)`（dir は N/NE/…/U/D） | `GameObject.Move(dir, ...)` | `D/XRL.World/GameObject.cs:16234`、v1 K13 |
| 攻撃 | `attack(dir or eN)` | `AttackDirection(dir)`。別名 eN の場合は方角に変換する（隣接が条件） | `GameObject.cs:18397`、`Cell.cs:9196` |
| 待機 | `wait(n=1)`、`rest(until="healed")` | n=1 は `PassTurn()`。n>1 と休息は `AutoAct.Setting` に `".N"`、`"r"`、`"z"` を設定する | `GameObject.cs:18058`、`D/XRL.Core/ActionManager.cs:855-1441` |
| 自動探索 | `explore()` | `AutoAct.Setting="?"`。エンジンの中断条件で止まったら、次の CTA で LLM を起こす | `ActionManager.cs:805-814`、`D/XRL.World.Capabilities/AutoAct.cs:105-419` |
| 移動（経路） | `travel(to)`。to は `eN`、`landmark:<name>`、`exit:<dir>`、`note:<id>` | ハーネスが座標に解決し、`AutoAct.Setting="M x,y"` を設定する。ゾーン境界へは `CmdMoveToBorder:x,y` 相当の処理を行う | `ActionManager.cs:857-905`、`D/XRL.Core/XRLCore.cs:908-919` |
| 階段・ワールドマップ | `move(U)` / `move(D)` | `Move("U"/"D")` | 04 §1.11 |
| 物を拾う | `get(eN or "all")` | `The.Player.FireEvent("CommandGet")` と同じ処理。複数あるときの選択は PickOption のモーダルになり、指定済みの答えで応答する（§3.3） | `XRLCore.cs:2144-2146` |
| 相互作用 | `interact(eN, verb)` | `EquipmentAPI.GetInventoryActions` の候補から選んだ verb で `InventoryActionEvent.Check` を呼ぶ。候補の一覧は無料ツール `actions(eN)` で得る | `D/Qud.API/EquipmentAPI.cs:378`、`D/XRL.World/InventoryActionEvent.cs:110` |
| 装備 | `equip(item)`、`unequip(slot)`、`drop(item)` | `EquipmentAPI.EquipObjectToPlayer` / `UnequipObject` / `DropObject` | `EquipmentAPI.cs:439-501` |
| 能力 | `ability(id, target?)` | `CommandEvent.Send(player, entry.Command)`。対象選択は指定済みの答えで応答する | `D/XRL.World/CommandEvent.cs:124`、`XRLCore.cs:2322-2334` |
| 遠隔 | `throw(target)`、`fire(target)` | `Combat.ThrowWeapon(The.Player)` と `CmdFire` の case 本体を呼び、PickTarget を指定済みの答えで応答する | `XRLCore.cs:1837-1840` |
| 会話の開始 | `talk(eN)` | `CmdTalk` の case 本体を呼ぶ（`PickDirection.ShowPicker("Talk")` を指定済みの方角で応答する） | `XRLCore.cs:2212-2216` |
| 成長 | `raise(stat)`、`learn(skill_or_power)`、`mutate(...)` | `StatusScreen.BuyStat(GO, stat)` と、`SkillsAndPowersScreen.BuildNodes` 後の `SelectNode(node, GO)` を呼ぶ。確認の YesNo は指定済みの Yes で応答する | `D/XRL.UI/StatusScreen.cs:61-86`、`D/XRL.UI/SkillsAndPowersScreen.cs:141-227, 229` |
| メタ | `save_and_quit()` | `CmdSaveAndQuit` 相当の処理（主張用の走行でもセッション境界で許す。ロードの手段は提供しない） | `XRLCore.cs:1718` |
| **禁止** | wish、load、デバッグコマンド | 文法に存在しない。wish が実行されたら sensor が検出する（§8） | `D/XRL.Wish/WishManager.cs:131` |

**無料ツール**: `look(eN)`（`Look.GenerateTooltipContent`）、`map()`、`inventory()`、`equipment()`、`abilities()`（クールダウン込み）、`character()`、`quests()`、`journal()`、`messages(n)`、`actions(eN|item)`、`notes_read/notes_write`、`kb_search(q)`（§7）。

### 3.2 「case 本体の shim」という考え方

`XRLCore.PlayerTurn` の switch の多くは、1〜3 行の静的呼び出しにすぎない（例: `CmdThrow` → `Combat.ThrowWeapon(The.Player)`、`CmdGet` → `The.Player.FireEvent("CommandGet")`）。本提案では、**許可した命令 ID ごとに、その case 本体を CTA 内で同じように呼ぶ shim** を持つ。どの shim にも、写した元の行番号を書いておく。

- 利点: キー注入を使わずに済むので、`ClearMouseEvents`（S1）の問題も、入力バッファの上限（04 §1.8）の問題も避けられる。
- 欠点: ゲームを更新すると shim が古くなる。対策として、shim 表と decompile 上の行のハッシュを CI で照合する（§10）。

### 3.3 指定済みの答え（staged answers）

行動に引数として対象や方角が含まれている場合、ハーネスはそれを「この行動の範囲に限って有効な答え」として mod に預ける。預かり方は、**その行動が出すと分かっているプロンプトに限定する**。

- **PickDirection と PickTarget**: 行動の引数（方角、eN）から作った答えを 1 回だけ消費する。
- **YesNo**: 行動ごとに、期待する確認文のパターンを固定しておく。例は `raise` の「It will cost ... attribute point」（`D/XRL.UI/StatusScreen.cs:75`）と、`learn` の「Are you sure you want to buy」（`D/XRL.UI/SkillsAndPowersScreen.cs:212`）である。**一致したときだけ** Yes を返す。行動の途中で出たほかの YesNo（危険な液体への移動、仲間への攻撃などの警告）は情報を含むので、必ず LLM に回す。
- **AskString と AskNumber**: 自動では**決して**答えない。エンディングの確認（「Type 'CROSS' to confirm」など。§8.1）はすべてこの種類である。
- **PickOption**: 行動の引数で選択肢のラベルを指定したときだけ、ラベルが一致すれば答える。

預かった答えが合わない場合（種類が違う、選択肢にない）はモーダル判断に落として、LLM に聞き直す。**どちらの経路でも、モーダルの引数と使った答えは台帳に記録する**。LLM が意図を示さないまま自動で選ばれる選択は存在しない。

例外は、選択肢のない単なるお知らせのポップアップだけである。これは自動で閉じ、本文を**次の観測の `notices` 欄に直接入れて**記録する。`Popup.Show` の既定は `LogMessage=true` だが（`D/XRL.UI/Popup.cs:658-666`）、呼び出し元によっては `LogMessage:false` を渡すので、メッセージログには頼らない。

### 3.4 結果のフィードバック

行動ツールの戻り値の形は次の通り。

```
{status: "resolved"|"interrupted"|"rejected"|"modal_pending",
 energy_spent: bool, pos_before, pos_after, game_turns_elapsed,
 interrupt_reason?, new_messages[], next_observation}
```

- `rejected` は文法エラーか前提条件の不成立で、ゲーム内の時間は進まない。LLM に理由を返して、もう一度選ばせる。
- **CTA から抜けるのは次の 3 つの場合だけである。** (a) エネルギーが実際に消費された、(b) `AutoAct.Setting` を設定して委任した、(c) オペレーターの `release`。v1 の K13 が示したように、`Move` や `AttackDirection` は false を返したうえでエネルギーを消費しないことがある。そのまま戻ると `Energy>=1000` のまま `PlayerTurn` に入り（`D/XRL.Core/ActionManager.cs:798-1611`）、キー待ちで止まるか、人間の入力で進んでしまう。そこでハンドラは、行動の前後でエネルギーを比べる。消費されていなければ、結果を `rejected` として LLM に返し、同じ CTA の中で再度判断を要求する。`PreventAction` は、v1 と同じく異常なエネルギーへの最後の保険にだけ使う（01 K14）。
- v1 のような「timeout したら既定の行動で代行する」処理は**置かない**。これは帰属の完全性のための決定である。
- 無料ツールの予算（1 判断あたり 6 回）を超えた呼び出しには、ハーネスがエラーの `tool_result`（「budget exhausted; choose an action」）を返す。`tools` の一覧と `tool_choice` は変えない。理由は 2 つある。ツール一覧はキャッシュされる先頭部分の最初にあるので、変えるとキャッシュが失われる。また、Opus 5.5 と Fable 5.1 では、`tool_choice` の `any` / `tool` による強制が 400 になる。3 回連続で `rejected` になったら、判断を保留したまま watchdog が人間に知らせる。

---

## 4. モーダル UI

### 4.1 方式: ゲームスレッド側の合流点に Harmony prefix を当てる

`Popup.*` の Modern UI の経路は、2 つの合流点に集まる。

1. **`Popup.WaitNewPopupMessage`**（`D/XRL.UI/Popup.cs:801`。async void）。呼び出し元は次の通り。
   - `ShowBlockWithCopy`（:679）
   - `ShowBlockPrompt`（:970）
   - `ShowBlockSpace`（:1040）
   - `ShowSpace`（:1094）
   - `ShowBlock` / `Show`（:1140）
   - `ShowConversation`（:1594）
   - `ShowOptionList` / `PickOption`（:1740）
   - `ShowYesNo`（:2260）
   - `ShowYesNoCancel`（:2373）

   ゲームスレッドから呼ばれた場合、このメソッドは `uiQueue` 経由でウィンドウを出し、`Task.Wait()` で止まる（S7）。prefix で元の処理を飛ばし、LLM の答えから作った `QudMenuItem` で `callback` を同期的に呼べば、同じ結果になる。
2. **`Popup.NewPopupMessageAsync`**（`:751`。`Task<QudMenuItem>`）。呼び出し元は次の通り。
   - `ShowAsync` / `ShowFailAsync`（:636, :650）
   - `AskNumberAsync`（:1349）
   - `AskStringAsync`（:1396）
   - `ShowYesNoAsync`（:2329）
   - `ShowYesNoCancelAsync`（:2344）

   prefix で `__result = Task.FromResult(item)` を返す。`AskString` は `qudMenuItem.text` を返り値にし（`:1413-1417` 付近）、`command=="Cancel"` のときは空文字を返す。したがって `QudMenuItem{command="Submit", text=answer}` を返せばよい。

選択肢の答えの形は、ゲームが使っているものと同じにする。選択肢は `command="option:N"`（`:1571-1615`、`:1740`）、ボタンは `Yes`/`No`/`Cancel`/`Submit` である。

**prefix が介入する条件**: `Thread.CurrentThread == XRLCore.CoreThread` で、かつ自律モード中であること。UI スレッドから呼ばれた場合（`:804` の分岐）は元の処理に任せ、台帳に `ui_thread_popup` として記録する。

| モーダル族 | 検出 | 読むもの | 答え | Harmony |
|---|---|---|---|---|
| Show / ShowBlock 系（お知らせ） | 合流点 1・2 | message, title | 自動で閉じる（記録する） | 要 |
| PickOption / ShowOptionList / PickGameObject | 合流点 1 | title, intro, options[], hotkeys, AllowEscape | `choose(i)` / `escape` | 要 |
| YesNo / YesNoCancel | 合流点 1・2 | message | `yes` / `no` / `cancel` | 要 |
| AskString / AskNumber | 合流点 2 | message, WantsSpecificPrompt, min/max | `text(s)` / `number(n)` | 要 |
| 会話（`ShowConversation`） | 合流点 1（`:1594`） | 話者のタイトル、本文、選択肢。ほかに `look`。AllowTrade のときの `trade` は、交易の prefix が完成するまで**選択肢に出さない** | `choose(i)` / `look` / `escape`（`ConversationUI.cs:514-537` の戻り値の規約に合わせる）。交易の完成後に `trade` を加える | 要 |
| PickDirection | `PickDirection.ShowPicker`（`D/XRL.UI/PickDirection.cs:28`）の prefix | label | 方角の文字列 | 要 |
| PickTarget | `PickTarget.ShowPicker`（`D/XRL.UI/PickTarget.cs:378`）の prefix | style, range, radius、範囲内の可視候補 | `Cell` を返す（候補 eN から解決する） | 要 |
| 交易 | `TradeUI.ShowTradeScreen`（`D/XRL.UI/TradeUI.cs:344`）の prefix | 双方の在庫と価格（`TradeUI.GetObjects` / `GetValue` :232） | 完成前は**番兵**として働く。記録して即座に戻り、LLM には「trade unavailable」と返す。完成後は、テキストで提示した offer を `PerformOffer`（`:1296`）で確定する | 要（完成は第 4 週以降。**高リスク**） |
| ステータス画面 | 開かない。`Screens.Show`（`D/XRL.UI/Screens.cs:88`）に番兵の prefix を当て、自律中に呼ばれたら記録して即座に戻る | — | — | 要 |
| キャラクター作成 | 走行の外（準備段階）で扱う。§4.3 | — | — | 不要 |
| レベルアップ | `Leveler` は `Popup.*` を呼ぶ（`D/XRL.World.Parts/Leveler.cs:289, 325, 341`）ので、上の族として処理される | — | — | 要 |

**Rosetta は必須とする**。同梱の Harmony 2.2.2 は、arm64 ネイティブでは `mprotect EACCES` で失敗する（04 §4.6）。そこで x86_64 スライスで起動する（`arch -x86_64 .../CoQ.app/Contents/MacOS/CoQ`）。

- `Managed/0Harmony.dll` の差し替えは**採らない**。ゲームの更新で元に戻るうえ、証拠マニフェストに「ゲームのバイナリは無改変」と書けなくなる。
- パッチは 10 本程度の小集合にする。QudJP の 1693 本とは違い、パッチの適用時間は問題にならない **[推論]**。

### 4.2 Harmony に依存しない第 1 週の構成（M1）

M1 は Harmony なしで、ネイティブの arm64 で動かす。モーダルの頻度は次の設定で下げる。

- `Popup.Suppress = true` を立てる（`D/XRL.UI/Popup.cs:132`）。これで `Show` / `ShowBlock` 系はログに流れる。
- オプションで、ポップアップをメッセージに回す（`OptionDismemberAsPopup`、`AbilityCooldownWarningAsMessage` など。04 §2.3）。
- 移動は `DoConfirmations:false` で行う。

それでも出るモーダル（YesNo、会話、PickOption）は watchdog が検出して走行を止める。そこでは人間が操作し、「開発走行・介入あり」として記録する。**M1 の走行は主張には使わない。** 変更した設定は、すべて run manifest に記録して開示する。

### 4.3 キャラクター作成

主張用の走行では、キャラクター作成を「ゲーム開始前の準備」として扱う。

1. ハーネスは、`EmbarkModules.xml` の Presets（例: Praetorian Prime。ビルドコードが XML に埋め込まれている）の説明文と、Genotype/Calling の要約を LLM に示す。LLM は 1 つを選ぶ（**この選択も台帳に載せる**）。
2. 選ばれたビルドコードを `SavePath/lastcharacter.txt` に書き、Chartype の `Last` で開始する（`D/XRL.CharacterBuilds.Qud/QudChartypeModule.cs:84-97`、`D/XRL.CharacterBuilds/EmbarkBuilder.cs:254-257`）。モード（Classic）の選択と数回のクリックは人間が行い、「準備段階の人間操作」として記録する。
3. `EmbarkBuilder.Begin`（`:61`）を Harmony で差し替えて完全に自動化する案は、第 3 週以降に回す（優先度は低い）。

### 4.4 取りこぼしの検出（watchdog）

mod のブリッジスレッドは 2 秒ごとに heartbeat を送る。内容は、`GameManager.Instance.CurrentGameView`（どのスレッドからでも読める。03 §6.1 J）と、ゲームスレッドの状態（`in_cta_wait` / `in_modal_wait` / `running`）である。ハーネスは次の 2 つの条件を異常として扱い、`unhandled_modal` として台帳に記録し、配信のオーバーレイで警告する。

- ビュー名がモーダルの名前（`PopupMessage`、`ModernPopup:*`、`Popup:*`、`PickTarget`、`ModernTrade`、`StatusScreensScreen` など。03 §2.8）なのに、ゲームスレッドが私たちの待機状態にない。
- 30 秒以上、判断要求も heartbeat の変化もない。

1 件でも起きれば、その走行は「介入の可能性あり」になる。

---

## 5. スレッドと同期

### 5.1 どこで止めるか

```
[game thread]
  ActionManager.RunSegment
   ├─ BTA (Check)                                  ActionManager.cs:743
   ├─ CTA.Check → LLMOfQudSystem.HandleEvent(CTA)  :789
   │     ├─ if AutoAct.IsActive(): return (委任中。LLM は呼ばない)
   │     ├─ Keyboard の迷い入力を数えて破棄 (ledger: stray_input)
   │     ├─ The.Core.RenderBase()  → AfterRender でグリフ格子を複写
   │     ├─ loop:
   │     │    obs = Build();  bridge.Request(obs)  ← ★ここで無期限にブロック
   │     │    行動を実行 → energy が減った or AutoAct.Setting を設定した なら break
   │     │    そうでなければ result=rejected を返して loop（PlayerTurn へは落とさない）
   │     └─ (release 中だけは何もせず return)
   ├─ (energy>=1000 なら) AutoAct 分岐 / PlayerTurn     :798-1611
   └─ ...
[game thread, 行動の途中]
   Popup.WaitNewPopupMessage / NewPopupMessageAsync / PickDirection / PickTarget の prefix
     └─ staged answer があれば即座に返す。なければ bridge.Request(modal) ← ★ブロック
[bridge thread]  ClientWebSocket → ws://127.0.0.1:4040 （v1 K19 の実証済み構成）
[UI thread]      Unity の Update（ゲームスレッドが止まっていても描画は続く）
```

- **ブロックしてよい根拠**: 人間がプレイ中に考えている間、`PlayerTurn` はキー待ち（`GetNextKey`）でゲームスレッドを止めている。このキー待ちは `pumpActions` なしで呼ばれる（`D/XRL.UI/CommandBindingManager.cs:928-931` → `D/ConsoleLib.Console/Keyboard.cs:1372-1375`。gameQueue を回すのは `:1038-1041` の `pumpActions` のときだけ）。したがって、CTA 内で gameQueue を回さずにブロックしても、「人間が考えている状態」と同等になる **[推論: P1 で 60 秒以上のブロックを実測]**。v1 が実証したブロックは 500ms までである。
- **gameQueue は待機中に回さない**。回すのは、ブロックの直前に呼ぶ `RenderBase` の中だけとする（S5）。

### 5.2 タイムアウト、停止、切断、再開

| 事象 | 挙動 |
|---|---|
| LLM API の遅延やエラー | ハーネス側で再試行する（SDK の既定の再試行 + 指数バックオフ）。mod 側に**タイムアウトはない**。代わりの行動はしない |
| 停止（オペレーター） | ハーネスが答えを返さないだけ。ゲームは判断点で凍結する。台帳に `pause` / `resume` を記録する |
| 切断 | mod のブリッジスレッドが再接続を繰り返す。ゲームスレッドは待ち続ける。再接続したら、同じ `req` ID で保留中の要求を再送する（ハーネスは `req` で冪等に扱い、答え済みなら同じ答えを返す） |
| 起床 | 不要。常に CTA かモーダルの prefix の中で待っているので、v1 の `SkipPlayerTurn` + `KeyEvent.Set` は使わない |
| 人間に操作を渡す（release） | ハーネスの `release` 命令で、CTA は行動せずに戻る。その結果 `PlayerTurn` が走り、人間が操作できる。**この区間の行動はすべて帰属不能**として記録する。次に `acquire` されるまで、CTA は素通りする |
| ハーネスの異常終了 | ゲームは判断点で凍結したまま待つ。再起動したハーネスは、台帳の末尾から状態を復元する |

### 5.3 フォーカス停止への対策

- CTA で行動する限り `PlayerTurn` には入らないので、`XRLCore.cs:737-740` のフォーカス待機（S2）は通常は発生しない。
- 残るのは次の 2 つである。
  - AutoAct の各ステップで呼ばれる `kbhit()` の 200ms 待ち（S10、`ActionManager.cs:810-814`）
  - release 中の `PlayerTurn`
- 対策は次の 2 つ。
  1. `OptionMusicBackground=Yes` にする。これで `Application.runInBackground` が有効になり、Unity の Update と描画がバックグラウンドでも続く（`D/XRL.UI/Options.cs:1445-1454`）。
  2. `GameManager.OnApplicationFocus(bool)` と `OnApplicationPause(bool)` に prefix を当てる（`D/GameManager.cs:1920-1928`）。自律モード中は、`bThreadFocus` と `focused` を true のまま保つ。setter が false から true になるときに入力をクリアする副作用（S9）は、M1 では問題にならない。

- Harmony がない M1 では、CTA ごとに `XRLCore.bThreadFocus = true; GameManager.focused = true;` を再設定する。AutoAct の途中でフォーカスを失うと、1 歩あたり 200ms に落ちる。これは許容する。

### 5.4 人間の入力が紛れ込んだ場合

**帰属できない行動の検出は、入力の手段に依存させない。** Modern UI には `Keyboard` を通らない入力経路もある（例: AbilityBar は `GameManager` から `TrySendCommandEventOnPlayer` を呼ぶ。04 §1.9、`D/GameManager.cs:2389-2426`）。そのためキー入力のフックでは足りない。代わりに mod は次の 2 つを検査する。

- 次の BTA で、プレイヤーのエネルギーの減少と、直前の `action_result` または AutoAct の委任とを突き合わせる。
- release 中でないのに `PlayerTurn` に入ったことを検出する（CTA ハンドラが抜けた理由を毎回記録し、release でない抜け方は起こりえないことを assert する）。

対応の取れない減少は `unattributed` として I4 に記録する。モーダルが私たちの prefix を経ずに閉じた場合も、watchdog（§4.4）が同じく I4 として記録する。

CTA でブロックしている間に人間がキーを押しても、その入力はキューに溜まるだけで、`PlayerTurn` は走らない。ただし AutoAct の実行中は、`kbhit` が真になって AutoAct が**中断される**（`ActionManager.cs:810-814`）。そこで CTA の入口で `Keyboard` のキューの件数を数えてから破棄し、`stray_input{n}` として台帳に記録する。これで「押されたが効果がなかった入力」も証拠に残る。

---

## 6. 通信と配置

### 6.1 プロセス構成

```
┌──────── CoQ (x86_64 / Rosetta, -savepath <profile>) ────────┐
│  LLMOfQud mod (C# source, Roslyn)                            │
│   ├─ Sensors  (CTA snapshot, AfterRender glyphs, msg cb)     │
│   ├─ Actuators(CTA shims, AutoAct delegation)                │
│   ├─ Modal interceptor (Harmony ~10 patches)                 │
│   ├─ Integrity sensors (wish, ending, focus, stray input)    │
│   └─ BridgeClient (ClientWebSocket → 127.0.0.1:4040)         │
└──────────────────────────────────────────────────────────────┘
                 │ JSON (Newtonsoft 13; 1 message = 1 JSON)
┌──────── loq-harness (Python 3.12, uv) ───────────────────────┐
│  ws server :4040  ── Ledger (append-only JSONL + SHA-256 chain)│
│  Brain loop (anthropic SDK, pinned model / prompt / tools)    │
│  MCP server :8790 (streamable HTTP; same tool functions)       │
│  Overlay server :8080 (SSE → OBS browser source)              │
│  Run manager (profile / options / launch / evidence packer)   │
└───────────────────────────────────────────────────────────────┘
```

### 6.2 選択の理由

- **mod をクライアント、ハーネスをサーバーにする**。ClientWebSocket は v1 で p95 1ms の実績がある（K19）。一方 `HttpListener` による mod 内サーバーは Mono/macOS 上で未検証である（03 U10）。証拠の観点でも、**台帳を書くのはゲームの外の 1 プロセスだけ**にしたい。ゲームのクラッシュで台帳が壊れないからである。
- **MCP はゲームの中に置かず、ハーネスに置く**。所有者は「Claude Code や Codex を最初のクライアントにしたい」と考えている。MCP をハーネス側に置けば、この希望はそのまま満たせる（`claude mcp add --transport http loq http://127.0.0.1:8790/mcp`）。そのうえで、すべての呼び出しが台帳を通る。つまり、RimMolt の「ゲーム内 MCP」とは違って、**どのクライアントが操作しても証拠の形式は変わらない**。
- **Brain は Python にする**。理由は 4 つある。
  - 所有者の他のリポジトリが Python と uv である。
  - 公式の `anthropic` SDK と MCP の Python SDK がそろっている。
  - 台帳の検証、コスト集計、セグメント評価の集計は pandas と pytest で済む。
  - v1 の `brain/protocol.py` の envelope 設計を流用できる（01 §4.2）。
- **シリアライズ**: mod 側では `Newtonsoft.Json` を使う。コンパイルで参照できるかは P0 で確認する。ロード済みであることは 03 §5 で確認されている。失敗した場合は、v1 の手書き JSON を出力専用に縮めて使う。
- **ポート**: すべて 127.0.0.1 に bind する。MCP にはランダムトークンで認証をかける（RimMolt の 9/15 アップデートに倣う）。

### 6.3 主張用の走行と、開発・対話の走行

| 走行の種類 | LLM クライアント | 用途 | 主張 |
|---|---|---|---|
| `protocol` | ハーネス内蔵の API ループ（モデル ID、effort、システムプロンプト、ツール定義、観測レンダラのバージョンを固定する） | 主張用の走行、セグメント評価 | 可 |
| `interactive` | Claude Code / Codex を MCP 経由で使う | 探索、デバッグ、配信の余興 | 不可（コンテキスト管理が不透明で、人間のメッセージが混ざりうる） |

---

## 7. 記憶と知識

### 7.1 永続化するもの

| 種類 | 置き場所 | 書き手 | LLM に見せる方法 |
|---|---|---|---|
| 台帳 | `runs/<run_id>/ledger.jsonl` | ハーネス | 見せない |
| エピソードの要約 | `runs/<run_id>/episodes/NNNN.md` | LLM（エピソード境界で書く） | 直近 3 本を常に入れる |
| ノート（目標、既知の地点、学んだ規則） | `runs/<run_id>/notes.md`（節の構成は固定: `GOALS`、`PLACES`、`LESSONS`（上限 40 件）、`CHARACTER`） | LLM（`notes_write`） | 常に入れる（1k トークン以下を目標にする） |
| 周回をまたぐ学習 | `profiles/<profile>/lessons.md` | LLM（死亡後の振り返りで書く） | 次の周回の起動時に上位だけを入れる |
| mod の状態 | `IGameSystem` に保存（セーブに入る） | mod | —（**最小限にする**。ID の対応表だけを置き、フィールドは `[NonSerialized]` を基本にする。`D/XRL/XRLGame.cs:157, 1580-1600`。セーブのロードに mod が必要になる点は §10） |

**エピソード**は、最大 10 判断ぶんの追記専用の会話とする。エピソードの内側では、履歴を編集も削除もしない。理由は 2 つある。

- キャッシュが効くのは、先頭が変わらない部分だけである。
- Opus 5.5 と Fable 5.1 の preserved thinking では、編集した履歴が 400 になりうる。

境界で LLM に要約とノートの更新を書かせ、新しいエピソードを始める。10 判断という長さは、コストの前提（§8.5 の R≈20k）と釣り合う値である。40 判断にすると、平均の履歴が約 55k に増え、1 呼び出しあたりのコストは約 1.3 倍になる（Opus 5 の場合。キャッシュ読み出しの増分のみ）。エピソードと外部ノートの組み合わせは、RimMolt の配信者の「学習は外部ファイルに書かないと残らない」と、GPP の「10 万トークンを超えるとループする」への対策である（02 §3.5）。

### 7.2 知識源と spoiler policy

**エージェントに見せてよい知識**と、**評価器だけが使う知識**を分ける。

| 知識 | エージェント | 評価器 | 理由 |
|---|---|---|---|
| `Manual.xml`（約 6k トークン） | ○（システムプロンプト） | ○ | ゲーム内のヘルプと同じ |
| ゲーム内のテキスト（会話、本、ジャーナル、Look） | ○（観測経由） | ○ | 人間と同じ |
| `Skills.xml`、`Mutations.xml`、`ActivatedAbilities.xml` の説明文 | ○（`kb_search`） | ○ | ゲーム内の説明画面と同じ文面 |
| 公式 wiki のスナップショット（CC BY-NC-SA 4.0） | **条件つき**（open-book のときだけ `kb_search` で引ける） | ○ | 人間の多くは wiki を見て遊ぶ。Astra も web と wiki を参照していた [C]。**開示が前提** |
| `Quests.xml` の構造、`Conversations.xml` の述語とアクションのグラフ、`ObjectBlueprints` | ×（エージェントには渡さない） | ○（進行指標と監査に使う） | 会話の分岐条件や未見の物体の内部値は、人間の画面には出ない |
| decompile のソース | × | ○ | 同上 |

- **条件を 2 つ定める**。`closed-book`（wiki なし）と `open-book`（wiki あり）である。主張には、どちらの条件で走らせたかを必ず付ける。
- **redaction manifest**: wiki から取得した本文は、ライセンス（NC-SA）と再配布の配慮から、証拠アーカイブには入れない。入れるのは URL、revid、SHA-256 だけにする（Astra も「第三者のソース本文は同梱せず、リンクと元のチェックサムを保持」した [C]）。ほかに API キー、ローカルのユーザー名やパス、視聴者のチャットの本文を墨消しする。何を消したかを manifest に記録する。
- 視聴者のチャットは、`protocol` 走行では LLM に**渡さない**（02 A9 のプロンプトインジェクション対策）。

---

## 8. 評価と証拠

### 8.1 「クリア」の定義（機械で判定できる述語）

CoQ のエンディングは、1 つの関数を通るわけではない。

- **状態**: `EndType` のゲーム状態が `Brightsheol` / `Marooned` / `Return` / `Covenant` / `Accede` / `Launch` のどれかになり、`EndGame.IsAnyEnding` が真になる（`D/XRL.World.Conversations.Parts/EndGame.cs:67-110`）。
- **経路**（いずれも `EndType` を設定したあとで達成を解除する）:
  - 会話パーツ `EndGame`: `AskString` で「End game? Type X to confirm」に答えると `EndType` を設定し、`queueTask(Start)` する（`EndGame.cs:162-172`）。
  - `AscensionCable`（Return）: `AskString` で「RETURN」を確認してから `Start()` を呼ぶ（`D/XRL.World.Parts/AscensionCable.cs:119-133`）。
  - `ShevaStarshipControl`（Launch）: `D/XRL.World.Parts/ShevaStarshipControl.cs:220-231`。
  - `ThinWorld`（Brightsheol）: `AskString` で「CROSS」を確認すると、`EndType="Brightsheol"` を設定し、`UnlockAchievement()` と `RunCredits()` を直接呼ぶ。`Start` は通らない（`D/XRL.World.Parts/ThinWorld.cs:62-82`）。
  - `CheckMarooned`: ArkCore と ArkOpenedSystem から呼ばれる（`EndGame.cs:813-816`、`D/XRL.World.Parts/ArkCore.cs:196`）。
  - 同じ関数は wish からも呼べる: `goend`、`gocreditscoda`、`gocoda`、`gocredits`（`EndGame.cs:276-324`）。
- **注意**: クエスト「Tomb of the Eaters」には、途中のステップとして「Ascend the Tomb and Cross into Brightsheol」がある（`Quests.xml` の該当ステップ）。そのため、**ゾーン名やクエストのステップ名で終了を判定してはいけない**。

**述語**: **`EndGame.UnlockAchievement()` の prefix が発火した時点で `EndType` が上の 6 値のどれかであり、かつ台帳に `wish` 事象が 1 件もないこと。**

静的な追跡では、実エンディングはすべて `UnlockAchievement` を通る。

- Accede、Covenant、Return（会話）: `HiddenConversations.xml` の `<part Name="EndGame" Type=...>` は Accede、Covenant、Return（それぞれ Grade="Super" あり・なし）だけである。これらは `EndGame` パーツ → `queueTask(Start)` → `Start` → `UnlockAchievement` の順に進む（`EndGame.cs:162-172, 282-291`）。
- Return（ケーブル）: `AscensionCable.cs:133` → `Start`。
- Launch: `ShevaStarshipControl.cs:231` → `Start`。
- Marooned: `CheckMarooned` → `Start`（`EndGame.cs:812-824`）。
- Brightsheol: `ThinWorld.cs:78` で直接呼ぶ。

念のため、`SetStringGameState("EndType", ...)` の変化も EndTurn ごとの読み取りで二重に監視する。これは `UnlockAchievement` を経ない経路を見落とした場合の保険である。実測での確認は P7 で行う。

- ゲームには**チート使用フラグがない**。`WishManager.HandleWish` はマッチしたメソッドを呼ぶだけで、何も記録しない（`D/XRL.Wish/WishManager.cs:131-161`。grep でも "Cheat"/"Wished" 系の状態は見つからなかった）。したがって、**`HandleWish` への Harmony postfix だけが wish の使用を検出する手段**になる。この限界は主張文にも書く。
- 開発プロファイルでの P7 では、禁止された `goend` wish を使って、2 つの sensor（エンディングの検出と wish の検出）が両方とも発火することを確かめる。
- 補助の外部アンカー: `Achievement.CAVES_OF_QUD.Unlock()`（`EndGame.cs:247-274`）で Steam の実績が解除され、Steam 側に解除時刻が残る。ただし、そのアカウントでまだ解除されていない場合に限る **[推論]**。

### 8.2 進行度の指標

28 クエスト・84 ステップの単純な割合は使わない。終盤のクエスト（The Golem、Reclamation、We Are Starfreight、If Then Else）は**分岐する別ルート**であり、手続き生成のクエストも混ざるからである。代わりに次の **spine（背骨）** を使う。`Quests.xml` の Level 属性を並べ、評価器が `Conversations.xml` の `StartQuest` / `FinishQuest` の辺で補正したものである。

| 段 | 内容（`Quests.xml` の Level とステップ数） | 観測の方法 |
|---|---|---|
| S0 | 開始（Joppa） | 台帳 |
| S1 | What's Eating the Watervine?（Lv1, 4 ステップ） | `Quest.StepsByID[..].Finished` |
| S2 | Fetch Argyve a Knickknack → Another Knickknack（Lv3/5, 各 2 ステップ） | 同上 |
| S3 | Weirdwire Conduit... Eureka!（Lv7, 2） | 同上 |
| S4 | A Canticle for Barathrum（Lv10, 3）＝ Grit Gate に到達 | 同上 + ゾーン ID |
| S5 | A Signal in the Noise / More Than a Willing Spirit（Lv10, 3/4） | 同上 |
| S6 | Decoding the Signal（Lv15, 4） | 同上 |
| S7 | The Earl of Omonporch（Lv20, 3） | 同上 |
| S8 | A Call to Arms / Grave Thoughts / The Assessment（Lv20） | 同上 |
| S9 | Pax Klanq, I Presume?（Lv25, 6） | 同上 |
| S10 | Tomb of the Eaters（Lv30, 6） | 同上 |
| S11 | 終盤の分岐（Golem / Reclamation / Starfreight など、Lv40） | 同上（分岐ごとに別の枝として記録する） |
| S12 | **終了**（§8.1 の述語） | sensor |

**Qud-spine%** は、S12 までに通過した spine のステップ数の割合と定義する。分岐の段では、選んだ枝のステップだけを分母に入れる。補助指標として、到達ゾーン数、最大深度（strata）、レベル、死因（Classic）、判断あたりのゲームターン数を集計する。

### 8.3 台帳と証拠パッケージ

**台帳の 1 行**:

```json
{"seq":1234,"prev":"<sha256 of previous line>","t":"2026-10-02T12:34:56.789Z","game_turn":18342,
 "kind":"decision_request|decision|action_result|modal|modal_answer|message|sensor|operator|llm_call|anchor",
 "body":{...},"body_sha":"..."}
```

- `llm_call` には、リクエストを「先頭部分のハッシュ + 今回追記したメッセージ」の形で入れる。これで全文を再構成できる。毎回全文を入れると、1 走行で数 GB になるからである。プロンプトはハーネスが生成するので、全文を残せる。ほかに、レスポンス全文、`usage`、モデル ID、レイテンシを入れる。Astra のように「コーディングエージェントのセッションが推論を担った」形ではない。**ハーネス自身が API を呼んで全文を残す**点が、本設計の差別化になる。
- `anchor`: 5 分ごとに先頭ハッシュを配信のオーバーレイに表示し（§9）、1 時間ごとに `ledger_heads.txt` を git commit して push する。VOD と GitHub の時刻が、台帳がその時点に存在したことの外部証拠になる。

**証拠パッケージ**（`evidence/<run_id>.tar.gz` と `SHA256SUMS`）:

| 項目 | 中身 |
|---|---|
| `MANIFEST.json` | ゲームの `AssemblyVersion`（2.0.211.56）、Steam の `buildid`、`Managed/*.dll` の SHA-256、起動アーキテクチャ（x86_64/Rosetta）、実際にロードされた mod の一覧（**`build_log.txt` から抽出する**。`StreamingAssets/Mods` は常に走査されるので思い込まない。04 §4.1）、mod ソースのハッシュ、ハーネスの git commit、プロンプトとツール定義のハッシュ、モデル ID と effort、`Local/PlayerOptions.json` のハッシュとデバッグ系オプションの値（`OptionAllowSaveLoad`、`OptionEnableSeed`、`OptionDisablePermadeath`、`OptionShowQuickstart` は **すべて No**。`Options.xml:190-199`）、ゲームモード（`GameMode`）、`OriginalWorldSeed`（常に保存される。`D/XRL/XRLGame.cs:1505-1515`、`D/XRL.CharacterBuilds.Qud/QudGameBootModule.cs:215-227`）、knowledge 条件（closed/open-book） |
| `ledger.jsonl` | §8.3 のとおり |
| `interventions.jsonl` | 人間の介入の一覧（下の分類）。空であることが主張の条件 |
| `saves/` | セッション境界ごとのセーブのスナップショット（`Synced/Saves/<GUID>/`）と、そのハッシュ |
| `logs/` | `Player.log`、`build_log.txt`、`game_log.txt` |
| `episodes/`、`notes.md`、`lessons.md` | LLM が書いた記憶 |
| `REDACTION.json` | 墨消しした項目と理由 |
| `SPOILER_POLICY.md` | §7.2 の表と、この走行の条件 |
| `verify.py` | 台帳のハッシュ鎖、アンカーの照合、sensor の集計、述語の判定、Qud-spine% の再計算を行う |
| `vod_index.json` | 配信 VOD の URL と、アンカーを表示した時刻の対応 |

**介入の分類**（`interventions.jsonl`）:

| 区分 | 例 | 主張への影響 |
|---|---|---|
| I0 準備 | キャラクター作成時のクリック、ゲームの起動、ブリッジの接続 | 開示すれば許容する |
| I1 基盤の復旧 | ゲームやハーネスのクラッシュ後の再起動、同じ判断点からの再開 | 開示すれば許容する。ただし再開は**最後の正規セーブから**に限り、ロードは 1 回ずつ理由つきで記録する |
| I2 ハーネスの変更 | セッション境界でのバグ修正、観測レンダラの修正 | 開示し、差分を同梱する。攻略知識を含む変更は I3 とみなす |
| I3 助言 | 人間から LLM へのメッセージ、戦略の追記 | 「assisted」に格下げする |
| I4 代行 | release 区間での人間の操作、手動のモーダル応答、`unhandled_modal`、帰属できない行動 | 「assisted」に格下げする |
| X 無効 | wish、デバッグオプション、セーブの読み直し（save-scum） | 主張は無効 |

### 8.4 この設計が支えられる主張

**所有者の質問（すでにクリアされているか、挑戦した人はいるか）への答え**:

- 2026-09-25 に web 検索で「Caves of Qud」と LLM や AI エージェントを組み合わせて調べた。LLM による CoQ のクリアや、LLM に挑戦させた公開記録は見つからなかった（02 の否定結果とも矛盾しない）。**検索による否定結果であり、存在しないことの証明ではない。** 主張を公開する前には、Steam の議論、r/cavesofqud、YouTube、X を改めて調べ、その記録を証拠に添える。

**クリアまで導けた場合に主張できること**（強い順）:

1. **「LLM エージェントによる、Caves of Qud の初めて記録されたクリア（Classic、パーマデス、wish なし、介入 I3/I4 なし、`protocol` 走行）」**。付帯条件として、ハーネスは人間が書いたこと、エージェントに見せた知識の条件（closed/open-book）、モデル ID、介入 I0〜I2 の一覧を明記する。Astra の自己申告と同じ限界（ローカルのハッシュは出所を証明しない）はあるが、VOD と git によるアンカーで時間の連続性を補強できる。
2. Roleplay（チェックポイントあり）でのクリアは、「チェックポイントからの復帰 N 回」を併記すれば、別の主張として出せる。弱いが正直な主張である。
3. `interactive` 走行でのクリア（Claude Code など）は、「LLM を用いたクリア」にとどまる。

**「現在の SOTA ならクリアできて当然か」への答え**:

- **未検証であり、当然とは言えない**。
  - NetHack では、LLM が初めて ascension したのは 2026-09 で、エージェント自身が作ったハーネスを使い、3 回目の挑戦だった [C]。
  - BALROG の NetHack 進行度は、一桁台から 10% 台にとどまっていた（02 §1.5、[C]）。
- CoQ には NetHack と比べて有利な点も不利な点もある **[推論]**。
  - 有利: クエストのジャーナルが行き先を文章で示す。Roleplay ならチェックポイントがある。
  - 不利: 主線が長い。会話の分岐がある。パーマデスで死に方が多い。
- 「SOTA なら既定で解ける」を検証するには、1 回のクリアではなく**割合**が要る。本設計で現実的な方法は次の 2 つである。
  - **セグメント評価**: 開発プロファイルで標準セーブ（S0 Joppa 開始、S4 Grit Gate 到着、S10 Tomb 入口など）を作る。各区間を同じ `protocol` で N≥5 回ずつ走らせ、区間ごとの通過率とコストを測る。**これはクリアの主張ではない**とラベルする。区間の通過率の積は、通しの成功率の粗い上限の目安になる **[推論]**。
  - **ablation**: 同じ区間で、マクロ（explore/travel）の有無、open-book と closed-book、モデルの違いを比べる。これで「ハーネスの寄与」と「モデルの寄与」を分けられる。これは dunnolab の議論で指摘された、「プロトコルを固定していたか」と「誰がハーネスを書いたか」の区別に当たる [C]。

### 8.5 コストモデル

**価格は claude-api スキルが持つキャッシュ表（2026-06-24 時点）による。走らせる前に公式の価格ページで再確認する。** キャッシュの読み出しは入力の 0.1 倍、5 分 TTL の書き込みは 1.25 倍とする。thinking トークンは出力として課金される。

**1 回の API 呼び出しの仮定**:

- キャッシュ済みの先頭部分 R = 20k トークン。静的部分が 8k（システムプロンプト、Manual の要約、ツール定義、ノート、直近 3 本のエピソード要約）、エピソード内の履歴が平均 12k。後者は、10 判断のエピソードで平均 4〜5 判断ぶん × 約 2.8k（観測 + 行動の結果 + 見える出力）である。
- 新しい入力 W = 2.5k トークン（観測と行動の結果。次の呼び出しのためにキャッシュへ書き込む）。
- 出力 O = 1.2k トークン（行動と短い理由 + adaptive thinking。effort を medium とした仮定）。

| モデル（表の価格 $/MTok: 入力/出力） | 1 呼び出しあたり |
|---|---:|
| Claude Sonnet 5（2/10） | 約 $0.022 |
| Claude Opus 5.5（4/20、cache read 0.20） | 約 $0.041 |
| Claude Opus 5（5/25） | 約 $0.056 |
| Claude Fable 5.1（10/50、cache read 0.25） | 約 $0.096 |

**1 走行あたり**: 呼び出し回数 N = (G / r) × c。

- G: クリアまでのゲームターン数。**未知の変数**である。人間のクリアの長さを事実として置くことはしない。
- r: 1 判断あたりのゲームターン数（マクロで伸びる）。
- c: 1 判断あたりの API 呼び出し数（無料ツールとモーダルの分）。

| シナリオ | G | r | c | 呼び出し数 N | Opus 5 | Sonnet 5 | 1 呼び出し 12 秒とした実時間 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 楽観 | 60k | 15 | 1.3 | 約 5.2k | 約 $290 | 約 $115 | 約 17 時間 |
| 中央 | 120k | 8 | 1.5 | 約 22.5k | 約 $1.3k | 約 $500 | 約 75 時間 |
| 悲観 | 250k | 5 | 2.0 | 約 100k | 約 $5.6k | 約 $2.2k | 約 330 時間 |

- Classic で複数回挑戦する場合は、失敗した走行（多くは序盤で終わる）の分を足す。
- **G、r、c の実測は、M1〜M3 の計測項目にする**。M3 のセグメント評価（S0→S4）で得た r と c を使い、この表を更新する。
- 「SOTA は既定で解けるか」を N≥5 の通し走行で確かめると、中央シナリオでも Opus 5 級で $6k 以上かかる。これがセグメント評価を勧める理由である。

---

## 9. 配信適性

- **視聴者に見えるもの**:
  - ゲーム画面（tile と Modern UI をそのまま使う）
  - OBS のブラウザソースによるオーバーレイ。内容は、現在の判断（LLM の短い理由）、直近の行動、Qud-spine% の進捗バー、ノートの `GOALS` 節、今日のコストと呼び出し数、**台帳の先頭ハッシュの下 8 桁と seq**（5 分ごとに更新。§8.3 のアンカー）、介入カウンタ（I0〜I4、X）。
- **間合い**:
  - 考えている間、ゲーム画面は判断点で静止する。そこでオーバーレイに「thinking…」と、`thinking.display: "summarized"` の要約を流す。
  - 行動の後に、最低 0.4〜1.0 秒の表示保持をハーネス側で入れられる（`pacing_ms`）。これは v1 の K15（エンジン速度での暴走）への対策で、`protocol` の固定パラメータとして manifest に記録する。
  - AutoAct による委任中は、`OptionAutoexploreRate`（既定は 20 セル/秒。`Options.xml:126`）で見やすい速度に抑える。
- **視聴者の参加**: `protocol` 走行ではチャットを LLM に渡さない。配信の外で、視聴者向けの予想や投票（LLM には見えない）を運営するのは自由である。
- **停止の見せ方**: `unhandled_modal` やクラッシュでは、オーバーレイに赤いバナーを出し、介入の記録がそのまま視聴者に見えるようにする。隠さないことが、主張の信用になる。

---

## 10. プラットフォームと更新耐性

- **Apple Silicon**:
  - M1 はネイティブの arm64 で Harmony を使わない（v1 と同じ条件）。
  - M2 以降は Rosetta（`arch -x86_64`、`SteamAppId=333640`、`SteamGameId=333640`。04 §4.6）で動かす。
  - Rosetta の性能コストは、判断待ちが律速になる本設計ではほぼ無視できる **[推論]**。
- **分離プロファイル**: `-savepath ~/Library/Application Support/Freehold Games/CavesOfQud-llm-<purpose>` を使う（04 §5.1）。用途ごとにプロファイルを分ける。
  - `dev`: デバッグオプションあり。セーブとロードを許可し、wish の probe を置く。
  - `bench`: セグメント評価用。標準セーブを置く。
  - `claim`: デバッグオプションはすべて No。英語。**mod は LLMOfQud だけ**。
  - `PlayerOptions.json` と `ModSettings.json` は事前に書いておく。これが初回起動で上書きされないかは P0 で確認する（04 §6）。
- **QudJP との共存**:
  - `claim` と `bench` では QudJP を入れない。
    - 観測テキストを英語の wiki とモデルの事前知識にそろえるため。
    - 「バニラ + ハーネス mod」の主張を単純に保つため。
  - `dev` では、QudJP と同時に読み込めることを任意で確認する（どちらも Rosetta 前提なので、Harmony の条件は同じ）。
  - QudJP の既定の配置先は `StreamingAssets/Mods` で、`-savepath` に関係なく常に走査される（04 §4.1, §4.7）。したがって claim の起動前に、`build_log.txt` でロードされた mod の一覧を確認する処理を、run manager の必須チェックにする。
- **ゲームの更新への耐性**:
  1. 更新を検知する。起動時に `AssemblyVersion` と `buildid` を manifest の固定値と比べ、違えば `claim` の起動を拒否する。
  2. shim 表の照合。§3.2 の shim ごとに、「decompile 上のシンボル名 + 元になった行のテキストの SHA-256」を保存しておく。更新後に decompile を取り直したら、CI で差分を報告する（v1 の教訓どおり、行番号ではなくシンボルとテキストを主キーにする。01 §2.2）。
  3. Harmony パッチの対象は、メソッドのシグネチャをテストで固定する（L0。§11）。
- **セーブの互換性**: `XRLGame.Systems` には mod の型がシリアライズされる（03 §4.3）。そのため、証拠のセーブをロードするには同じ mod が必要になる。証拠パッケージには mod のソースを同梱する。主張用の走行の途中では**ハーネスや mod のバージョンを上げない**。上げるのはセッション境界だけで、I2 として記録する。セーブ → 終了 → ロードの往復は P6 で確かめる。
- **C# のコンパイル CI**: v1 には C# の CI がなかった（01 §3.3）。本提案では、mod の `.cs` を `Managed/*.dll` を参照する csproj でも `dotnet build` できるようにする（QudJP の方式。04 §4.7。ただし出荷するのはソースのまま）。こうすれば、ゲームを起動せずにコンパイルエラーを検出できる。

---

## 11. マイルストーン（最初の 3 週間）

### 11.1 最初に行うランタイムプローブ

| ID | プローブ | 合格条件 | 週 |
|---|---|---|---|
| P0 | `dev` プロファイルを作り、事前に書いた Options と ModSettings で mod をロードする（ネイティブ） | `build_log.txt` に `Success :)`、`Player.log` に `[LLMOfQud]`、設定が上書きされない | 1 日目 |
| P1 | CTA 内で 60 秒以上ブロックする（Modern UI、tile モード） | ハングしない。UI スレッドが応答し、ウィンドウが描画を続け、解除後に正常に進む | 1 日目 |
| P2 | CTA 内で `RenderBase()` を呼んだあと、AfterRender で得たグリフ格子を tile モードで取得する | 可視範囲のグリフが `BackupChar` から復元され、画面と一致する | 1〜2 日目 |
| P3 | Rosetta 上で Harmony 2.2.2 の prefix を `Popup.WaitNewPopupMessage` と `Popup.NewPopupMessageAsync` に当てる（ネイティブでの失敗も確認する） | PickOption、YesNo、AskString、ShowConversation の 4 種類で、prefix の答えがゲームに反映される | 1 週目（並行。M1 の条件にはしない） |
| P4 | CTA から `AutoAct.Setting` に `"?"`、`"M x,y"`、`".10"` を設定する | 同じセグメントで実行され、中断後の CTA で制御が戻る。`AutoAct.GetDescription` が取れる | 2 週目 |
| P5 | バックグラウンド走行（`OnApplicationFocus` の prefix + `OptionMusicBackground`） | ウィンドウが非フォーカスでも判断の速度が変わらない。AutoAct の歩行速度を記録する | 2 週目 |
| P6 | セーブ → 終了 → ロードの往復（mod の system あり） | ロード後に CTA の購読が復帰し、`req` の連番が衝突しない | 2 週目 |
| P7 | `dev` で wish `goend` を実行する | wish の sensor と ending の sensor が両方発火し、`verify.py` が「無効（X）」と判定する | 2 週目 |
| P8 | `Popup.Suppress` とオプションの組み合わせで、M1 のモーダルの頻度を数える | 200 ターンあたりの `unhandled_modal` の件数を記録する | 1 週目 |
| P9 | 未鑑定のアーティファクトと敵の負傷度を、観測と Look 画面の文面で照合する | 本名と HP の数値が漏れていない | 2 週目 |

### 11.2 第 1 週: M1「最初の自律 LLM ターン」

- 1 日目
  - mod の骨格: `[PlayerMutator]` → `RequireSystem`（v1 の資産をそのまま使う）、CTA の購読
  - ClientWebSocket ブリッジ
  - P0 / P1
- 2 日目
  - ハーネスの骨格: uv プロジェクト、ws サーバー、**台帳（ハッシュ鎖）と `verify.py` を最初のコミットに含める**
  - 観測ビルダー（自分の状態、実体、メッセージ、グリフ格子）。P2
- 3〜4 日目
  - Brain ループ: `anthropic` SDK、固定のシステムプロンプト、行動 4 種（`move`、`attack`、`wait`、`explore`）と無料ツール 2 種（`look`、`map`）
  - エピソードの概念はまだ入れず、直近 8 判断の履歴だけを持つ
  - **M1 の定義**: Joppa で LLM が観測を受け取り、行動を 1 つ選ぶ。その行動がゲーム内で実行され、要求、応答、実行結果の 3 つが台帳に記録され、`verify.py` が通る。
- 5 日目
  - 200 ターンの連続走行（`dev`、`Popup.Suppress`）。P8 を行う
  - 判断あたりのトークン数、レイテンシ、r、c を初めて実測する
  - Harmony の P3 は並行して進める

### 11.3 第 2 週: M2「モーダルの完全な処理と整合性 sensor」

- Rosetta での起動を標準にする。modal interceptor（2 つの合流点、PickDirection、PickTarget、`Screens.Show` の番兵）と staged answers
- 会話、水の儀式、レベルアップ（`raise`、`learn`）。行動の語彙を §3.1 まで広げる（交易を除く）
- 整合性 sensor: wish、ending、focus、stray input。watchdog。release と acquire
- P4〜P7、P9
- テストを 3 層にする。
  - **L0**: mod の純粋なロジック（観測のレンダリング、方角の計算、JSON）を、ゲームのアセンブリに依存しない形に分ける。QudTestHeadless 方式（net10 の CLI が `AssemblyLoadContext` で `Managed/*.dll` を解決する。04 §5.5）で、Harmony の対象シグネチャの存在と、shim 表のテキストハッシュを検査する。
  - **L1**: ハーネスで記録済みの台帳を replay する（プロンプトの生成、パーサ、`verify.py`）。
  - **L2**: ゲーム内の `[WishCommand("llmprobe:*")]` による probe（`dev` プロファイルだけ。結果は JSON）。
- **M2 の定義**: `dev` で Joppa から S1（Watervine）と S2 の一部まで進む。2 時間以上連続して `unhandled_modal` が 0 件で、人間はクリックしない。

### 11.4 第 3 週: M3「証拠パッケージ v0 とセグメント評価」

- evidence packer（manifest、redaction、SHA256SUMS）。git と VOD のアンカー
- オーバーレイ（SSE）
- エピソードと要約、ノート、`kb_search`（Manual と XML の説明文。wiki は別枝）
- `bench` プロファイルに標準セーブ S0 と S4 を作る。S0→S4 のセグメントを `protocol` で 3 回走らせる。G/r/c とコストを実測し、§8.5 を更新する。
- MCP サーバー（`interactive` 用）を公開する。交易の prefix の試作に着手する（完成は第 4 週以降）。
- **M3 の定義**: 第三者が `verify.py` だけで、S0→S4 の走行の「帰属の完全性」「介入の一覧」「spine の到達段」を再計算できる。

---

## 12. 最もリスクの高い前提（反証可能な形で）

| # | 主張 | なぜ重要か | 懐疑的な読者が読むべき箇所 | 実測の要否 |
|---|---|---|---|---|
| R1 | Rosetta（x86_64）で起動した CoQ 2.0.211.56 では、同梱の Harmony 2.2.2 の PatchAll が成功する。async void の `Popup.WaitNewPopupMessage` と `Task<QudMenuItem>` を返す `Popup.NewPopupMessageAsync` に当てた prefix が、元の処理を飛ばして答えを返せる | モーダルを自動で処理できるかどうかが、主張の強さを決める。失敗すれば Legacy UI（`OptionModernUI=No`）+ PushKey の代替に移ることになる | `D/XRL.UI/Popup.cs:751-921`、`D/XRL/ModInfo.cs:845-853`、`D/XRL/ModManager.cs:70`、04 §4.6、03 §4.2 | 要 |
| R2 | ゲームスレッド上で出る Modern UI のモーダルは、次の範囲ですべて捕まえられる。すなわち 2 つの合流点（`WaitNewPopupMessage` と `NewPopupMessageAsync`）に、PickDirection、PickTarget、TradeUI、`Screens.Show` を加えたもの。これらを経ずに、ゲームスレッドをブロックする UI（Book、Tinkering、CyberneticsTerminal など）は、自律走行の通常の経路では出ない | 取りこぼしは見えない停止を生み、人間のクリック（I4）につながる | `D/XRL.UI/Popup.cs` の呼び出し元（:636, 650, 679, 970, 1040, 1094, 1140, 1349, 1396, 1594, 1740, 2260, 2329, 2344, 2373）、`D/XRL.UI/PickDirection.cs:28`、`D/XRL.UI/PickTarget.cs:378`、`D/XRL.UI/TradeUI.cs:344`、`D/XRL.UI/Screens.cs:88-127`、`Qud.UI/BookScreen.cs`、`Qud.UI/CyberneticsTerminalScreen.cs` | 要（静的な列挙 + watchdog による実測） |
| R3 | CTA ハンドラの中で、gameQueue を回さずに数十秒以上ゲームスレッドをブロックしても、Modern UI でデッドロックやフリーズは起きない（`PlayerTurn` のキー待ちと同じ条件である） | 本設計の同期モデルの前提。v1 が実証したのは 500ms まで | `D/XRL.Core/ActionManager.cs:789-798`、`D/ConsoleLib.Console/Keyboard.cs:1030-1041, 1372-1375`、`D/XRL.UI/CommandBindingManager.cs:928-931`、`D/XRL.Core/XRLCore.cs:2600-2605`、01 K19 | 要 |
| R4 | 実際のエンディングはすべて、`EndType` を 6 値のどれかに設定したうえで `EndGame.UnlockAchievement()` を通る。したがって、そこへの hook と `WishManager.HandleWish` への postfix の組み合わせで、「wish なしのクリア」を判定できる | クリアの述語そのもの。漏れがあれば主張を判定できず、wish の検出に穴があれば主張は無効になる | `D/XRL.World.Conversations.Parts/EndGame.cs:67-110, 150-172, 247-324, 769-816`、`D/XRL.World.Parts/ThinWorld.cs:62-82`、`D/XRL.World.Parts/AscensionCable.cs:119-133`、`D/XRL.World.Parts/ShevaStarshipControl.cs:220-231`、`D/XRL.World.Parts/ArkCore.cs:196`、`D/XRL.World.Parts/ArkOpenedSystem.cs:9-19`、`Base/HiddenConversations.xml` の `<part Name="EndGame">`、`D/XRL.Wish/WishManager.cs:131-161` | 要（静的には全経路を追跡済み。実測は P7 の goend と、dev での各エンディング前セーブ） |
| R5 | CTA から `AutoAct.Setting`（`"?"`、`"M x,y"`、`".N"`）を設定すると、同じセグメントでエンジンの自動行動が始まる。中断すると次の CTA で制御が戻る。その結果、r（1 判断あたりのゲームターン数）は 5 以上になる | コストの支配項。r が 1〜2 だと、呼び出し数とコストが数倍になる | `D/XRL.Core/ActionManager.cs:794-815, 855-1441`、`D/XRL.World.Capabilities/AutoAct.cs:51, 105-419` | 要 |
| R6 | 観測は、人間に見える面だけから作れる。表示名は UI と同じ経路で取り、未鑑定の本名は漏れない。他者の HP の数値は出さず、負傷度の文言だけを出す。実体は可視セルと既探索セルのものに限る | 情報量が人間と同じであること（spoiler policy）は主張の公正さの中核である | `D/XRL.UI/Look.cs:239-270`、`D/XRL.World/GameObject.cs:669-753`、`D/XRL.World/Cell.cs:3469-3497`、`D/XRL.World/Zone.cs:7245-7255`、`D/XRL.World.Parts/Description.cs:73` | 要（P9） |
| R7 | `GameManager.OnApplicationFocus` と `OnApplicationPause` への prefix と `OptionMusicBackground=Yes` を組み合わせれば、ウィンドウが非フォーカスでも判断の速度と AutoAct の歩行速度が落ちない | 無人で長時間走らせることと、配信の安定性の前提 | `D/GameManager.cs:404-426, 1920-1928`、`D/XRL.Core/XRLCore.cs:737-740`、`D/ConsoleLib.Console/Keyboard.cs:938-954`、`D/XRL.UI/Options.cs:1445-1454` | 要（P5） |
| R8 | 許可した命令の case 本体（`Combat.ThrowWeapon`、`FireEvent("CommandGet")`、`CmdTalk`、`StatusScreen.BuyStat`、`SkillsAndPowersScreen.SelectNode`、`CommandEvent.Send`）を CTA 内から呼び、ピッカーと確認を staged answers で応答すれば、プレイヤーの入力と同じ結果になる | 行動の語彙を、キー注入なしで広げられるかどうか。駄目なら `PushCommand` と `PlayerTurn` を経由する方式に戻ることになり、`ClearMouseEvents` やフォーカスの問題が戻ってくる | `D/XRL.Core/XRLCore.cs:1837-1840, 2144-2146, 2212-2216, 2322-2334`、`D/XRL.UI/StatusScreen.cs:61-86`、`D/XRL.UI/SkillsAndPowersScreen.cs:141-229`、`D/XRL.World/CommandEvent.cs:124` | 要 |

---

### 付記: この提案が他案と比べて譲らない点

1. 台帳（ハッシュ鎖）と `verify.py` は、**最初のコミットに入れる**。後から証拠を付け足すことはしない。
2. timeout のときに代わりの行動をしない。判断はすべて LLM に帰属させる。
3. `protocol` 走行と `interactive` 走行をラベルで分ける。前者だけが主張の対象になる。
4. 主張の文言は、述語（§8.1）、介入の区分（§8.3）、知識の条件（§7.2）の 3 点を必ず含める。
