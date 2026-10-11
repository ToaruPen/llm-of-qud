# P4. World Model + Macro: 「盤面を読む指揮者」と「雑務をこなす執事」

> 探索フェーズの提案書（レンズ: ゲームに勝つ）。作成 2026-09-25、Opus 5.5 ワーカー。
> 逆コンパイルの引用はすべて `coq-decompiled_stable`（以下 `D/`）の `path:line`。このツリーは現在 `AssemblyVersion("2.0.211.56")`（`D/Properties/AssemblyInfo.cs:8`）である。01 が付けた「2.0.211.50」というラベルはもう古い。03 が `NEW/` として引いた行番号は、今の `D/` とそのまま一致する。
> 本書では 03・04 の引用を再利用し、以下の行は自分で開いて照合した（§13 に一覧）: `XRLCore.cs:652-680, 690-740, 1326-1352, 1417-1508, 1596-1630, 1920-1925, 2323-2334, 2600-2618`、`ActionManager.cs:789-815, 832-1575, 1584-1611`、`GameObject.cs:1176, 3645, 11424, 16234, 18058, 18397`、`Popup.cs:624-672, 751-921, 1118-1140, 1191-1200, 1371-1442, 1520, 1566-1616, 1650, 1700-1760, 2251-2280, 2365`、`PopupMessage.cs:721, 926-944`、`Look.cs:239-251`、`ModInfo.cs:845-862`、`Keyboard.cs:820-849, 926-954, 1028-1045`、`GameManager.cs:404-425, 1918-1924`。

---

## 1. 概要と狙い

CoQ のクリアには数万ターンかかる。その大半は、歩く、探す、休む、雑魚を叩くといった単調な時間で占められる。そこで 1 手ごとに LLM を呼ぶ設計を考えると、コストと遅延より先に集中力が尽きる。GPP は約 10 万トークンを超えたあたりでループに入った。BALROG は、知っていることと実際にやることのずれ（knowing–doing gap）を記録している（02 §1.5, §1.11）。

P4 は判断の粒度を上げる。LLM は「指揮者」として、状況報告（sitrep）を読み、マクロを 1 つ選んで渡す。マクロはゲームエンジン自身の自動行動（AutoAct、経路探索、休息）と直接 API で実行される。止まる理由は、エンジンが出す中断と、こちらで定めたガードのどちらかである。止まったら LLM をもう一度起こす。その間の食事・給水・回復・定型確認は、決定的な「執事」（Steward）が片づける。形は rimagent の Steward と rimworld-ai-manager の恒常性デーモンを CoQ に移したものである（02 §1.2, §1.4）。

### 最適化するもの

1. **エンディングへの到達確率。** 構造化されたワールドモデル（Zone/Cell/GameObject、敵対関係、Look テキスト、クエスト、ジャーナル、会話ノード、インベントリ、能力）を LLM に渡す。移動や戦闘の反復はエンジンに任せる。
2. **LLM の注意の配分。** 起床は事象駆動にする。単調な区間では LLM を眠らせ、判断の分岐点でだけ起こす。
3. **証拠の質。** ゲームに届いた操作は、全件を出所つき（LLM、Steward、エンジンの自動行動、人間）で台帳に残す。

### 意図的に捨てるもの

- **「素の LLM が 1 手ずつ操作した」という主張。** マクロと Steward がターンの大半を動かす。したがって主張は「LLM が戦略と分岐判断を担った」に限られる。その割合（agency share）は数値で開示する（§8）。
- **画面の忠実な再現。** ScreenBuffer は配信とデバッグの補助にとどめる。LLM が見る地図は、Cell から自前で組み立てる。
- **ネイティブ arm64 での起動。** モーダル層に Harmony を使うため、Rosetta（x86_64）で起動する（§4, §10）。ここは探索の結果次第で反転しうる前提で、Harmony を使わない代替経路も用意する。
- **1 手単位の戦術性。** 普段の戦闘は `fight` マクロに任せる。LLM が毎手指す「戦術モード」は、ボス戦などに限った高価なモードとして残す。

---

## 2. 観測

### 2.1 使う表面

観測はすべてゲームスレッド上で、ゲーム状態から直接組み立てる。描画バッファには依存しない。そのため tile モードでも Modern UI でも同じ出力になる。

| 層 | 表面 | 根拠 |
|---|---|---|
| 地形・可視性 | `Zone.GetVisibility/GetExplored`、`Cell.IsVisible()/IsExplored()`、`Cell.GetObjects()`、`IsPassable`、`IsSolid*` | `D/XRL.World/Zone.cs:7245,7255`、`D/XRL.World/Cell.cs:3469,3490,4854,5920,6123-6209` |
| 実体 | `GameObject.IsVisible()`、`hitpoints/baseHitpoints`、`IsHostileTowards(player)`、`ShortDisplayNameStripped`、`_Effects` | `D/XRL.World/GameObject.cs:10458,1176,11424,6911,146` |
| 説明文 | `Look.GenerateTooltipContent(obj)`（Look 画面と同じ文面） | `D/XRL.UI/Look.cs:239-251` |
| プレイヤー | Stats、`Stomach.FoodStatus/WaterStatus`、`Inventory`、`Body.GetEquippedParts`、`Mutations`、`Skills`、`ActivatedAbilities` | 03 §2.4 |
| 目標と記憶 | `XRLGame.Quests`、`JournalAPI.GetKnownNotes()`（地図メモ、観察記録） | `D/XRL/XRLGame.cs:145-148`、`D/Qud.API/JournalAPI.cs:233` |
| 行き先 | `GetPointsOfInterestEvent.GetFor(player)`（CmdMoveToPointOfInterest と同じ一覧） | `D/XRL.World/GetPointsOfInterestEvent.cs:135`、`D/XRL.Core/XRLCore.cs:1326-1352` |
| メッセージ | `XRLCore.RegisterNewMessageLogEntryCallback`（push）。`MessageQueue.Add` が呼ぶ | `D/XRL.Core/XRLCore.cs:657-680`、`D/XRL.Messages/MessageQueue.cs:138-150` |
| 高レベル事象 | `IGameSystem` の `QuestStarted/QuestCompleted/LocationDiscovered/PlayerTook/PlayerReputationChanged/ZoneActivated/PlayerAfterConversation` | `D/XRL/IGameSystem.cs:2975-3046` |
| 自動行動の状態 | `AutoAct.Setting/IsActive/GetDescription`、`GameObject.AutomoveInterruptBecause/AutomoveInterruptTurn` | `D/XRL.World.Capabilities/AutoAct.cs:51-66,114,405,419-423` |
| モーダル | §4 の Harmony prefix が受け取る引数そのもの（Title、Intro、Options、PopupID）と、`ConversationUI.CurrentNode/CurrentChoices` | `D/XRL.UI/Popup.cs:1433,1571,1650,2251`、`D/XRL.UI/ConversationUI.cs:135-157` |
| 終局 | ゲーム状態 `EndType/EndGrade`（`EndGame.IsAnyEnding`） | `D/XRL.World.Conversations.Parts/EndGame.cs:67-120,166-170` |

`ScreenBuffer` と AfterRenderCallback は LLM に渡さない。使うのは配信 overlay の「ゲームが実際に描いた地図」の確認と、観測の突き合わせテストだけである（03 §1.3 のとおり、Modern UI ではバッファにマップしか入らない）。

### 2.2 LLM に渡す表現: sitrep

sitrep は、LLM を起こすたびに 1 枚渡す状況報告である。並び順は rimagent の知覚順（変化しやすい情報ほど前）に倣う（02 §1.2, P5）。

1. `wake`: なぜ起こしたか（事象の種類、マクロの結果、中断理由）
2. `vitals`: HP・空腹・渇き・状態異常。前回からの差分つき
3. `modal`: 開いている選択肢があれば、その全文（あるときは最優先）
4. `threats`: 可視の敵対実体。方角、距離、HP の目安、Look の 1 行要約
5. `digest`: 前回起床からの事象（重要度でまとめ、上限 12 行）
6. `goals`: 進行中クエストの現ステップと、LLM 自身の `run_state` メモ（§7）
7. `place`: ゾーン名、周囲の POI・出口・階段、地図（必要なときだけ）
8. `kit`: 装備と能力の使用可否（変化があったときだけ全文。それ以外は 1 行）
9. `options`: 今この場で有効なマクロとその引数の候補（ID つき）

座標は LLM に書かせない。実体には `e3`、POI には `p2`、アイテムには `i7` のような短い ID を振り、マクロの引数はこの ID で受ける（02 P6、A5）。ID はゾーンが変わるまで安定させ、裏で `GameObject.ID` に対応させる。

地図は、戦闘・地形判断が必要なときと LLM が `look_map` を呼んだときだけ出す。プレイヤー中心 21×11 の自前 ASCII で、凡例は `#` 壁、`.` 既知の通行可、空白は未探索、`+` 扉、`<` `>` 階段、英字は実体とし、実体の英字は sitrep の ID と揃える。Cell の意味情報から作るので、tile モードの `BackupChar` 問題（01 K5-K7）とは無関係である。

### 2.3 1 ターン分の実例

以下は、Joppa 近郊の「Fetch Argyve a Knickknack」進行中に `explore` マクロがスナップジョーの出現で中断した瞬間の sitrep である。自動探索の敵対中断は引数なしの `AutoAct.Interrupt()` を通る（`D/XRL.World.Capabilities/AutoAct.cs:158-166`）。そのため `AutomoveInterruptBecause` は空のままで、理由はガードの判定（`NEW_HOSTILE`）と spot メッセージから組み立てる（§3.5）。LLM には JSON を下の圧縮テキストに整形して渡す（JSON は台帳と overlay 用）。

```text
== WAKE #214  turn 3187  reason=MACRO_INTERRUPTED(explore) cause=NEW_HOSTILE
   engine: "You see a snapjaw scavenger to the northeast."
== VITALS  HP 21/28 (-4 since #213)  Hunger: Sated  Thirst: Quenched  Effects: none
== THREATS (visible hostiles: 2)
   e1 snapjaw scavenger   NE 4   HP ~full  "A hunched humanoid with a hyena's snout..." wields: bone dagger
   e2 snapjaw hunter      NE 6   HP ~full  wields: short bow   [ranged]
== DIGEST since #213 (38 turns, macro explore ran 36 steps)
   + picked up: 3 witchwood bark (autoget)   + found: rusted chest (opened, empty)
   ! You hear yipping nearby.
== GOALS
   Q "Fetch Argyve a Knickknack": step "Find an artifact" (open)
   run_state: "Explore Joppa's east parasang for a trinket; return to Argyve (p1)."
== PLACE  Joppa, east outskirts (surface)  exits: N,E,S  stairs: none seen
   POI: p1 Argyve's hut [W 31]   p2 Joppa well [W 22]
== KIT  melee: bronze dagger  ranged: none  abilities: Sprint(ready) Freezing Ray(ready, cd 0)
== OPTIONS
   fight(target=e1|e2, until=dead|hp<50%)  flee(to=p1)  ability(Freezing Ray, target=e1|e2)
   explore()  goto(p1|p2)  rest(until=healed)  wait(n)  look(e1|e2)  look_map()
```

JSON 側の骨格は次のとおりである（抜粋。キー名は英語で固定）。

```json
{"wake":{"seq":214,"turn":3187,"reason":"MACRO_INTERRUPTED","macro":"explore",
  "cause":"NEW_HOSTILE","engine_text":"You see a snapjaw scavenger to the northeast.","source":"spot_message+guard"},
 "vitals":{"hp":21,"hp_max":28,"hp_delta":-4,"food":"Sated","water":"Quenched","effects":[]},
 "threats":[{"id":"e1","name":"snapjaw scavenger","dir":"NE","dist":4,"hp_band":"full",
   "look":"A hunched humanoid with a hyena's snout...","hostile":true}],
 "modal":null, "digest":[...], "goals":[...], "place":{...}, "kit":{...}, "options":[...]}
```

### 2.4 サイズ見積もり

| 部分 | トークン目安 | 備考 |
|---|---:|---|
| システムプロンプト + マクロ仕様 + 恒常ルール | 約 4,000 | prompt cache 対象。毎回同一 |
| 学習メモ（`lessons`、上限 40 件）+ `run_state` | 約 1,200 | 起床ごとに更新される部分だけ非キャッシュ |
| sitrep（地図なし） | 400〜900 | 上の例で約 450 |
| sitrep（地図つき、21×11 + 凡例） | +350 | 戦闘・地形判断時のみ |
| 直近の会話履歴（指揮者自身の直前 6 起床分の要約と決定） | 約 1,500 | 古いものは要約して落とす |
| **1 起床あたり入力** | **約 7,000〜8,000（うち約 4,000 キャッシュ）** | 出力は 150〜400 |

1 起床で平均 25〜40 ゲームターンが進むと見込む（探索中は長く、戦闘中は短い）。数万ターンのクリアでも、起床は 1,000〜3,000 回に収まる。この数字は実測前の推定であり、M2 の 30 分走行で最初の実測値を取る（§11）。

### 2.5 tile モード・Modern UI への依存

- **観測:** 依存しない。Cell と GameObject から組み立て、描画バッファを読まないためである。
- **モーダル:** 依存しない。§4 の prefix は `Popup.*` の同期 API の入口に当たる。`UIManager.UseNewPopups`（Modern/Legacy）の分岐は、その入口より後ろにある（例: `ShowYesNo` の分岐は `D/XRL.UI/Popup.cs:2258`、`PickOption` の分岐は `:1709`）。例外は会話で、Legacy UI では `ShowConversation` ではなく `RenderClassic` を通る（`D/XRL.UI/ConversationUI.cs:424-428`）。P4 は Modern UI のまま運用するので、この例外は実害にならない。
- **配信:** 見た目は tile モードの Modern UI のままでよい。ただし prefix で横取りしたモーダルは画面に出ないので、overlay 側で表示する（§9）。

---

## 3. 操作

### 3.1 行動文法

LLM が出せる行動は 1 起床につき 1 つで、次の 3 種類に分かれる。

- **free（ターンを消費しない）:** `look(id)`、`look_map()`、`inventory()`、`quest_log()`、`journal(query)`、`kb(query)`、`path_estimate(target)`、`note(section, text)`。何度呼んでもよい。上限は 1 起床あたり 8 回（dcss-ai の `FREE_ACTIONS` の考え方、02 §1.8）。
- **act（マクロ 1 つ）:** 下の表のいずれか。受理した時点で free は締め切る。
- **policy（Steward の設定変更）:** `steward.set(key, value)`。例: 回復休息を始める HP 閾値、autoget の対象、会話で自動選択してよい定型選択肢。変更は台帳に残す。

act の応答として LLM に同期で返すのは「受理/拒否と理由」だけである。結果は、マクロが終わるか中断したときの次の sitrep で届く（02 P4: 戻り値ではなく行動後の状態で返す）。

```json
{"act":"fight","args":{"target":"e1","until":"dead","retreat_below_hp":0.35},
 "intent":"clear scavenger before hunter closes; bow user second"}
```

`intent` は必須にする。台帳と overlay に出し、次回の sitrep では「前回の意図」として LLM 自身に返す。

### 3.2 実行の基本形: CTA を握る

v1 が確立したとおり、行動の入口は `CommandTakeActionEvent`（CTA）である（01 K13, K14）。`ActionManager.RunSegment` は、CTA の `Check`（`D/XRL.Core/ActionManager.cs:789`）→ 敵対による自動行動の中断判定（`:796`）→ `Energy>=1000 && IsPlayer` のゲート（`:798`）→ AutoAct の分岐（`:805-1575`）→ `PlayerTurn()`（`:1611`）の順に進む。

P4 は、この CTA ハンドラをゲームスレッドの「サービスループ」として使う（詳細は §5）。行動は次の 2 経路で実行する。

- **直接 API:** その場でエネルギーを消費させる。`Move`、`AttackDirection`、`PassTurn`、`CommandEvent.Send`、`InventoryActionEvent.Check`、`EquipmentAPI.*`。
- **AutoAct の委任:** `AutoAct.Setting` を設定し、エネルギーを消費せずに CTA を抜ける。同じセグメントの `:805` で `AutoAct.IsActive()` が真になり、エンジンが 1 歩進める。以後、自動行動の 1 歩ごとに CTA がまた発火する（`:789` が `:805` より先）。そのため CTA が、**エンジン実行中のマクロに対する 1 歩ごとのガードフック**になる。

`PlayerTurn` には原則として入らない。入ったら「帰属不明の入力が起こりうる区間」として台帳に記録する（§8）。

### 3.3 マクロ一覧

「エンジン」列は、人間のプレイヤーも同じ自動化を持っているかを示す。§8 の主張の範囲に直結する分類である。

| マクロ | 実行方法 | エンジン | 終了・中断条件（ガード） |
|---|---|---|---|
| `step(dir)` / `attack(dir)` / `wait(n)` | `Move(dir, DoConfirmations:false)`、`AttackDirection`、`PassTurn`（`D/XRL.World/GameObject.cs:16234,18397,18058`）、`.N` は `AutoAct.Setting="."+n` | 人間と同じ（1 手操作） | 1 手で完了 |
| `explore()` | `Zone.FlushNavigationCaches()` → `AutoAct.Setting="?"`（`CmdAutoExplore` 本体の写し、`D/XRL.Core/XRLCore.cs:1920-1925`） | 人間も持つ自動探索 | AutoAct の中断（敵対、アイテム、行き止まり）。「もう探索先がない」は `Popup.Show` になる（`ActionManager.cs:1083-1091`）ので、§4 の情報ポップアップ処理で `EXPLORE_EXHAUSTED` に変換する |
| `goto(target)` | 座標なら `"M x,y"`、実体なら `"M"+id`、POI なら `PointOfInterest.NavigateTo`（`"P r:id"`、`D/XRL.World/PointOfInterest.cs:157-177`） | 人間も持つ（マウス移動、POI 移動） | 到着、経路なし（`Popup.Show("You cannot find a path...")`、`ActionManager.cs:957,962`）、敵対中断（`M/P/U/!` は `:794` の敵対チェック対象外なので、**CTA ガードで独自に敵対を判定する**） |
| `use_at(target)` | `"!"+id` または `"U"+id`（隣接したら `AttemptSmartUse`、`ActionManager.cs:898-907`） | 人間も持つ | 同上 |
| `stairs(up\|down)` | `AutoAct.Setting="<"` / `">"`（`XRLCore.cs:1498,1512` の写し） | 人間も持つ | 到着、階段なし（`ShowFail` なのでメッセージが残らない。独自コード `NO_STAIRS`） |
| `leave_zone(dir)` | `"G"+dir`（`TryFindEdgeStep`、`ActionManager.cs:968-988`）→ 端で `Move(dir)` | 人間も持つ（端まで自動移動） | 端に到達、経路なし |
| `travel(dest)` | 複合: 地表なら世界地図に上がる（`CmdMoveU` 本体の写し、`XRLCore.cs:1417-1496`）→ 世界地図上を `FindPath` で 1 歩ずつ `Move` → `PullDown`（`:1508`）→ `goto`。行き先は地図メモ、ゾーン ID、既知 POI | 部分的に人間と同じ（世界地図の歩行は人間も 1 歩ずつ） | 各区間の終了、世界地図上の遭遇、敵対 |
| `rest(until)` | `healed`: `RestingUntilHealed=true; RestingUntilHealedCount=0; AutoAct.Setting="r"; PassTurn()`（`XRLCore.cs:1596-1606` の写し）。`morning`: `"z"`。`n`: `".n"` | 人間も持つ | 回復完了（`ActionManager.cs:1263-1325`）、敵対、Steward の空腹・渇きアラーム |
| `fight(target, until, retreat_below_hp)` | 毎 CTA: 隣接なら `AttackDirection`、非隣接なら `FindPath` で 1 歩。遠隔武器・能力の使用は LLM が `until` の方針で許可した場合だけ | **P4 独自**（エンジンの `"a"` 自動攻撃は使わない。中断理由が粗いため） | 対象の死亡・視界外、HP 閾値割れ（→ `P0`）、新しい敵対の出現、N 手経過（既定 12） |
| `flee(to)` | `goto` の変種。毎歩、最寄り敵対との距離が縮まらない方向を優先する | P4 独自 | 到着、追いつかれた |
| `talk(npc)` | 隣接まで `goto` → `ConversationUI.HaveConversation(...)`（`D/XRL.UI/ConversationUI.cs:361-434`）。選択肢は §4 のモーダル層で LLM が選ぶ | 人間と同じ UI 経路 | 会話終了（`PlayerAfterConversation`） |
| `trade(npc, buy[], sell[])` | ゲームスレッドで `TradeUI.GetObjects`（両側）→ `NumberSelected` を設定 → `UpdateTotals` → `CalculateTrade` → `TradeUI.PerformOffer(diff, false, ...)`（`D/XRL.UI/TradeUI.cs:150,276,308,1296,1613`）。取引画面は開かない | **UI 迂回・同一バックエンド** | 完了、または `PerformOffer` の YesNo/Show（§4 で処理） |
| `item(id, verb)` / `equip(id, slot)` / `drop(id)` | `EquipmentAPI.GetInventoryActions` で動詞候補を列挙 → `InventoryActionEvent.Check`、`EquipmentAPI.EquipObject/UnequipObject/DropObject`（`D/Qud.API/EquipmentAPI.cs:378,439,488,501`、`D/XRL.World/InventoryActionEvent.cs:110`） | UI 迂回・同一バックエンド | 1 手で完了。副作用のポップアップは §4 |
| `ability(cmd, target?)` | `CommandEvent.Send(player, cmd, ref exit, Target, TargetCell)`（`D/XRL.World/CommandEvent.cs:44`）。ターゲット引数が効かない能力は `PickTarget` が開くので、PickTarget 用の prefix で答える（§4） | UI 迂回・同一バックエンド（`CmdAbilities` も最後は `CommandEvent.Send`、`XRLCore.cs:1806-1821`） | 1 手で完了 |
| `level_up(spend)` | `StatusScreen.BuyStat(GO, stat)`（`D/XRL.UI/StatusScreen.cs:62`）、`SkillsAndPowersScreen.SelectNode(node, GO)`（`D/XRL.UI/SkillsAndPowersScreen.cs:141`）、変異購入（`StatusScreen.ShowMutationPopup`、`:575`） | UI 迂回・同一バックエンド（Modern の画面も `APIDispatch` 経由で同じ関数を呼ぶ、`D/Qud.UI/CharacterStatusScreen.cs:343-354`） | 1 手で完了 |
| `tactical()` | 以後 N 手、毎 CTA で LLM を起こす戦術モード | — | N 手経過、または LLM が解除 |

実装の原則は 2 つある。第一に、エンジンの `case` 本体を写したマクロ（`explore`、`rest`、`stairs`、`travel` の昇降）は、写し元の行を型名とシグネチャつきでコードコメントに残す。ゲーム更新のたびに差分を機械的に見るためである（§10）。第二に、`CmdWaitUntilHealed` は Setting を変えるだけでなく `RestingUntilHealed*` のフラグと `PassTurn` を伴う。写すときは副作用ごと写す。

### 3.4 マクロの状態機械とガード

マクロは C# 側の状態機械で、毎 CTA に `Step(ctx)` が 1 回呼ばれる。返り値は `Continue`（何もせず抜ける。AutoAct が歩く）、`Acted`（エネルギーを消費した）、`Done(result)`、`Interrupted(reason)` のいずれかである。

CTA ガードは、どのマクロにも共通で次を毎歩確認する。エンジン側の敵対中断は CTA の**後**、同じセグメントの `ActionManager.cs:796` で行われる。そこで AutoAct を委任中のマクロは、`Continue` を返す前に `AutoAct.ShouldHostilesInterrupt()`（`AutoAct.cs:153`）を自分で評価する。真なら CTA の中で中断を確定し、そのままサービスループにとどまる。

1. HP が `retreat_below_hp` または Steward の緊急閾値を割った → `Interrupted(HP_CRITICAL)`
2. 新しい敵対実体が視界に入った（前歩の集合との差分）→ `Interrupted(NEW_HOSTILE)`。`M/P/U/!` の自動移動はエンジンの敵対中断の対象外（`ActionManager.cs:794`）なので、ここで補う
3. AutoAct が前歩で active だったのに今は inactive で、マクロの完了条件も満たしていない → `Interrupted(ENGINE_STOP)`
4. 同じセルに 6 歩以上とどまった、または往復運動を検出した → `Interrupted(STUCK)`（v1 の U 字振動、01 K17）
5. マクロ固有の上限（歩数、ターン、壁時計）→ `Interrupted(BUDGET)`

### 3.5 結果と中断理由の回収

中断理由は 1 か所からは取れない。3 つの出所を突き合わせる。

- `GameObject.AutomoveInterruptBecause`: `AutoAct.Interrupt(string Because, ...)` が設定する（`AutoAct.cs:419-423`）。ただし引数なしの `Interrupt()` と `Interrupt(GameObject)`（`:460`）はこれを設定しない。
- メッセージ「You stop ... because ...」: `Interrupt(Because)` が `MessageQueue.AddPlayerMessage` に流す（`:429-440`）。`Interrupt(GameObject)` は spot メッセージを流す（`:466`）。メッセージコールバックで拾う。
- 独自コード: `STUCK`、`NO_STAIRS`、`EXPLORE_EXHAUSTED`、`NO_PATH`、`BUDGET`、`HP_CRITICAL`、`NEW_HOSTILE`。`ShowFail` は `LogMessage:false` で呼ばれる（`Popup.cs:629-632`）。そのため、そのテキストはモーダル層で拾わないと消える。

結果は常に「行動後の状態」で返す。たとえば `trade` の結果は「PerformOffer が返した値」ではなく、取引前後のインベントリと水の差分である。

### 3.6 事象と起床: LLM を飢えさせず、溺れさせない

事象はすべて C# の `EventBus` に集まる。出所は 5 つある。

- メッセージコールバック
- `IGameSystem` の高レベルフック
- マクロの `Done`/`Interrupted`
- モーダル層
- Steward

事象には重要度を付け、重要度ごとに LLM の起こし方を決める。

| 重要度 | 例 | 扱い |
|---|---|---|
| **P0 即時** | HP が緊急閾値を割り、Steward でも対処できない。未知のモーダル。死亡、復帰の選択。破壊的確認の拒否 | 実行中のマクロを止め、その場で起こす。予算の制限を受けない |
| **P1 分岐** | マクロの完了・中断・失敗。LLM の判断が要るモーダル（会話、Steward 規則にない PickOption） | 起こす。ただし連続起床の下限間隔（戦闘中 0 秒、平時 3 ゲームターン）を守る |
| **P2 注目** | クエスト開始・ステップ完了、レベルアップ、新しい場所の発見、評判の変化、目立つアイテムの入手 | 起こさずに `digest` に積む。ただし 3 件たまったら、次の区切り（マクロの 1 区間の終わり）で起こす |
| **P3 環境** | その他のメッセージ | `digest` に 1 行ずつ。上限を超えたら「+N lines」と畳む |

**飢えさせない仕掛け。** マクロには、経過ゲームターン（既定 300）と経過壁時計（既定 180 秒）の上限を設ける。超えたら `BUDGET` で中断し、その時点の `digest` を持たせて LLM を起こす。長い `travel` や `rest` の途中でも、LLM が世界の変化を知らないまま置き去りにされることはない。さらに P2 が 3 件たまった時点でも起こす。重要な変化が `digest` の中で埋もれて古くなることを防ぐためである。

**溺れさせない仕掛け。**

- 同じ種類の事象は、1 起床の中で 1 行にまとめる（「snapjaw ×3 が視界に入った」）。
- 起床の頻度には上限を設ける。戦闘外では 1 分あたり 6 回までとし、超えた P1 は次の枠に回す。P0 はこの上限の対象外である。
- 戦闘中は、LLM が `fight` の方針（`until`、`retreat_below_hp`、使ってよい能力）を 1 回決めたら、1 手ごとには起こさない。
- `tactical()` を明示したときだけ毎手起こす。

**予算。** 1 時間あたりの入力トークンと費用に上限を置く。上限に近づくと、ゲートウェイが指揮者に「節約モード」を告げる。節約モードでは起床の間隔を広げ、Steward の閾値を保守側に倒す。予算の状態は sitrep の末尾に 1 行で出す。

### 3.7 Steward: 決定的な執事

Steward は C# の規則表である。規則は「条件 → 行動 → 記録名」の形で書く。LLM は `steward.set` で閾値を変えられるが、規則そのものは追加できない。規則の追加は開発者がコードで行い、台帳の `run_header` に規則表のハッシュを残す。

| 規則 | 条件 | 行動 |
|---|---|---|
| `drink` | 渇きが Thirsty 以上、敵対が視界になし | 所持している真水を飲む（`InventoryActionEvent.Check(..., "Drink")`） |
| `eat` | 空腹が Hungry 以上、敵対なし | 食料を食べる。候補がなければ P2 事象 `NO_FOOD` |
| `heal_rest` | HP < `rest_below`（既定 60%）、敵対なし、マクロなし | `rest(until=healed)` |
| `autoget` | エンジンの autoget 設定に従う | エンジンに任せる（Steward は設定値だけを管理する） |
| `modal_rules` | 既知の PopupID・文言パターン（死亡時の復帰、POI の選択の確定、危険な液体の確認は No など） | 規則どおりに答える |
| `loop_break` | 同じ会話ノードで同じ選択肢を 3 回選んだ。同じマクロが同じ理由で 3 回中断した | P1 事象として LLM に「ループの疑い」と伝える |

Steward は戦わない。逃げもしない。HP の緊急閾値で行うのは「マクロを止めて LLM を起こす」ことだけである。生死の分かれ目の判断は LLM に残す。その判断が遅れて死んだ場合、死因は LLM の側にあると台帳から読める。

---

## 4. モーダル UI

### 4.1 なぜ Harmony を主経路にするのか

Harmony を避けたい理由は十分にある。同梱の `0Harmony.dll` は 2.2.2.0 で、ネイティブ arm64 では `mprotect returned EACCES` でパッチが 0 件になる（04 §4.6）。この失敗は、オーナー自身の QudJP 検証レポートでも同じ M4 機で確認されている（`coq-japanese_stable/docs/reports/2026-05-12-harmony-2.4.2-native-arm64-verification.md`）。それでも P4 は、モーダル層に限って Harmony を主経路に置く。「勝つ」レンズで見ると、決め手はゲームの最後の 1 手にある。

エンディングの確定は会話パーツ `EndGame` の `EnterElementEvent` で行われる。そこで呼ばれるのは `Popup.AskString("End game?\n\nType RETURN to confirm.", ..., WantsSpecificPrompt: text)` である（`D/XRL.World.Conversations.Parts/EndGame.cs:148-172`）。一致したときに初めて `EndType` が設定され、クレジットが始まる。Modern UI では `WantsSpecificPrompt` があると、ボタンが長押し確定の `SubmitCancelHoldButton` になる（`D/XRL.UI/Popup.cs:1375-1385`）。UI スレッドから長押しボタンを模擬する経路は、どの調査でも実証されていない。一方、ゲームスレッド側の `Popup.AskString` に prefix を当てて文字列を直接返せば、長押し UI そのものが現れない。

同じ構造は他の分岐点にもある。Roleplay モードの死亡時は、`PickOption` で「Reload from checkpoint」を選ばせる（`D/XRL/CheckpointingSystem.cs:114`）。Modern UI の会話はすべて `Popup.ShowConversation` を通る（`D/XRL.UI/ConversationUI.cs:521`）。レベルアップの急速変異は `ShowYesNo` と `PickOption` を使う（`D/XRL.World.Parts/Leveler.cs:325,341`）。取引の確定は `ShowYesNo` である（`D/XRL.UI/TradeUI.cs:1307`）。これらをゲームスレッド上で、引数ごと同期的に受け取れること。それが P4 の求める性質である。

### 4.2 パッチ対象

prefix は 2 層で当てる。

**意味層（主）:** 戻り値の契約がはっきりした同期 API に当て、LLM か Steward の答えを直接返して元の処理を飛ばす（`return false`）。オーバーロードの取り違えを避けるため、引数型を明示して `AccessTools.Method` で解決する。

| 対象 | 行 | 戻り値 | LLM に見せる情報 |
|---|---|---|---|
| `Popup.ShowConversation(string, IRenderable, string, List<string>, bool, bool, bool)` | `D/XRL.UI/Popup.cs:1571` | `int`（-1 Escape、-2 Trade、-3 Look、0 以上は選択肢） | Title、Intro（ノード本文）、Options、`ConversationUI.Speaker`、`CurrentNode.ID`、`CurrentChoices[i]` の遷移先 |
| `Popup.PickOption(...)` | `:1650` | `int` | Title、Intro、Options、PopupID（例 `CmdMoveToPointOfInterestMenu`） |
| `Popup.ShowYesNo(string, string, bool, DialogResult, Action<DialogResult>)` | `:2251` | `DialogResult` | Message |
| `Popup.ShowYesNoCancel(...)` | `:2365` | `DialogResult` | Message |
| `Popup.AskString(...)` | `:1433` | `string` | Message、Default、`WantsSpecificPrompt` |
| `Popup.AskNumber(...)` | `:1191` | `int?` | Message、Start、Min、Max |
| `Popup.PickGameObject(...)` | `:1520` | `GameObject` | Title、候補の表示名 |
| `Popup.PickSeveral(...)` | `:2046` | `List<(int,int)>` | Title、Options、Stacks |
| `PickTarget.ShowPicker(...)` / `PickDirection` | `D/XRL.UI/PickTarget.cs:378`、`D/XRL.UI/PickDirection.cs:12` | 対象セル・方向 | 呼び出し元の能力名、候補実体 |

**網羅層（保険）:** `Popup.WaitNewPopupMessage` のゲームスレッド側の分岐に prefix を当てる（`:801-921`）。意味層を素通りした Modern ポップアップ（`ShowBlock`、`ShowSpace`、各種 `Show`）はここに落ちる。選択肢がなければ、メッセージをログに流し、既定ボタンを選んだものとして `callback` を同期で呼ぶ。未知の `PopupID` と選択肢つきのポップアップは、`UNKNOWN_MODAL` 事象として LLM に回す。

### 4.3 守るべき規則

1. **UI スレッドでは絶対にブロックしない。** prefix の先頭で `Thread.CurrentThread == GameManager.Instance.uiQueue.threadContext` なら何もせず素通しする（`WaitNewPopupMessage` 自身が同じ判定をしている、`Popup.cs:804`）。`NewPopupMessageAsync`（`:751`）では LLM 待ちをしない。UI スレッドを止めると Unity のフレームが止まり、配信が凍る。
2. **情報ポップアップは消さずに流す。** 元の `LogMessage` の意味を再現して `MessageQueue.AddPlayerMessage` に送る。`ShowFail` の本文はログに残らない（`Popup.cs:629-632`）ので、網羅層でイベントとして拾う。`Popup.Suppress` のグローバル切り替えには頼らない。ゲーム自身がこのフラグを立て下げしているためである（`D/XRL.Core/XRLCore.cs:2199-2201`、`D/XRL.World.Parts/Skills.cs:190-200`、`D/XRL.World.Conversations.Parts/EndGame.cs:470-533` ほか）。
3. **破壊的な確認は既定で拒否する。** `AskString` の `WantsSpecificPrompt` が `ABANDON`（`XRLCore.cs:1751`）、`RETIRE`（`CheckpointingSystem.cs:128-136`）なら、Steward が即座に空文字（キャンセル）を返す。LLM には「拒否した」とだけ伝える。エンディングの `RETURN` などは、LLM が直前に `ending` 意図を宣言していた場合に限って通す。
4. **元のメソッドの契約を守る。** 元の処理を飛ばす prefix でも、元のメソッドが呼ぶはずのコールバックは呼ぶ。`ShowYesNo` の `callback` と `PickOption` の `OnResult` がこれに当たる（`Popup.cs:2251,1650`）。
5. **会話で `-2`（Trade）を返さない。** `-2` は `Trade.ShowScreen()` を開く（`D/XRL.UI/ConversationUI.cs:528`）。UI スレッドの取引画面は P4 では操作できないので、取引は `trade` マクロだけで行う。
6. **網羅層で二重にログを書かない。** `ShowBlock` は `WaitNewPopupMessage` の前に自分で `AddPlayerMessage` を呼ぶ（`Popup.cs:1133-1138`）。網羅層はログを書かずに事象だけを出す。`ShowFail` の本文を拾えるのもこの事象である。
7. **サービスループに入るのは `CoreThread` のときだけ。** UI スレッドでもゲームスレッドでもない呼び出し（たとえば `RunCredits` は `Task.Run` の中で動く、`EndGame.cs:326-328`）では、Steward の既定の答えを返して台帳に残す。free クエリをゲームスレッド以外で処理すると、§5.1 の規則を自分で破ることになるためである。
8. **既定値で逃げない。** v1 は timeout 時に探索移動を返していた（01 §1.3）。P4 のモーダルは、LLM の答えが来るまでゲームスレッド上で待つ。待ち方は §5 のサービスループと同じである。

### 4.4 モーダル系統ごとの扱い

| 系統 | 検出 | 読み取り | 回答 | Harmony | Rosetta |
|---|---|---|---|---|---|
| `Popup.Show/ShowBlock/ShowSpace/ShowFail` | 網羅層 prefix | Message、Title | 既定ボタンを即答。ログに流す | 要 | 要 |
| `PickOption`、`PickGameObject`、`PickSeveral` | 意味層 prefix | Title、Intro、Options、PopupID | Steward の規則表（POI 選択、死亡時の Reload 等）→ 該当しなければ LLM | 要 | 要 |
| `ShowYesNo/YesNoCancel` | 意味層 prefix | Message | Steward の規則表（取引の確定は `trade` の意図があれば Yes、危険な液体は No）→ LLM | 要 | 要 |
| `AskString/AskNumber` | 意味層 prefix | Message、`WantsSpecificPrompt`、範囲 | §4.3 の規則 → LLM | 要 | 要 |
| 会話 `ShowConversation` | 意味層 prefix | 本文、選択肢、話者、ノード ID | LLM。ただし「同じノードで同じ選択肢を既に選んだ」ループは Steward が検出して `Escape` を提案する | 要 | 要 |
| ステータス画面（Inventory、Character、Skills など） | 開かない | §2 の直接 API で同じ情報を得る | §3 の UI 迂回マクロで操作する | 不要 | 不要 |
| 取引画面 | 開かない | `TradeUI.GetObjects/GetValue` | `TradeUI.PerformOffer`（§3.3） | 確定の YesNo だけ要 | 同左 |
| キャラクター作成 | `EmbarkBuilder` | LLM に XML 由来の候補（Genotypes、Subtypes、Mutations、Skills）を示す | LLM が作ったビルドコードを `EmbarkBuilder.FromCode`（`D/XRL.CharacterBuilds/EmbarkBuilder.cs:505-519`）で流し込む。`Begin` をどう差し替えるかは M3 以降に設計 | おそらく要 | 同左 |
| `PickTarget`/`PickDirection` | 意味層 prefix | 呼び出し元、候補 | `ability(cmd, target)` で指定済みの対象を返す。未指定なら LLM | 要 | 要 |
| メインメニュー、セーブ選択 | 起動スクリプト | — | `[ModSensitiveCacheInit]` から既知のセーブを `XRLGame.LoadGame` で開く（03 U11） | 不要 | 不要 |

### 4.5 Harmony を使わない代替経路

Rosetta が配信や安定性の点で受け入れられないと判明した場合に使う。

- **UI スレッド・ブローカー:** Modern のポップアップがゲームスレッドから開かれると、ゲームスレッドは `complete.Task.Wait()` で止まる（`Popup.cs:908`）。ウィンドウは共有インスタンス `UIManager.getWindow("PopupMessage")` である（`:826`）。`AskString` 系はコピー `copyWindow` を使い、`"PopupMessage #n"` の名前で `windowsByName` に登録される（`D/Qud.UI/UIManager.cs:323-342`）。ブリッジスレッドは `uiQueue` 経由でこれらを読み、`commandCallback`/`selectCallback`（`D/Qud.UI/PopupMessage.cs:22-24`）か `OnActivateCommand`/`OnSelect`（`:926-944`）で答える。ゲームスレッドは止まっているので、会話の文脈は `ConversationUI` の静的状態（`ConversationUI.cs:135-157`）から読める。長押しボタンの扱いは未検証である。
- **Legacy UI:** `OptionModernUI=No` にすれば、すべてのポップアップが `getvk` ループになり、`Keyboard.PushKey` が効く（03 §3.6）。見た目は配信向きではない。

どちらも M1 と M2 の妨げにはならない。M1 は、モーダルが出ない行動（移動）だけで達成できる。

---

## 5. スレッドと同期

### 5.1 3 本のスレッド

| スレッド | P4 での役割 | してはいけないこと |
|---|---|---|
| ゲームスレッド（`XRLCore.CoreThread`） | すべての状態の読み取りと行動の実行。CTA サービスループとモーダル prefix の待機 | UI スレッドへの `awaitTask`（01 K21、デッドロック） |
| UI スレッド（Unity メイン） | 描画。ゲーム側の UI 処理 | P4 のコードでブロックすること |
| ブリッジスレッド（専用、`ClientWebSocket`） | 送受信とキューへの出し入れだけ | ゲーム状態に触れること |

### 5.2 CTA サービスループ

LLM が考えている間、ゲームスレッドは CTA ハンドラの中で待つ。`PlayerTurn` のアイドルでは待たない。理由は 4 つある。

1. `PlayerTurn` は冒頭で `CallBeginPlayerTurnCallbacks()` を呼び（`D/XRL.Core/XRLCore.cs:693`）、そのあと `Keyboard.ClearMouseEvents(LeaveMovementEvents: true)` を呼ぶ（`:734`）。コールバックから積んだ非移動コマンドは消える。
2. `Keyboard.IdleWait` は、`DisableAllIdleTileAnimations` が有効だと `KeyEvent.WaitOne()` で無期限に待つ（`D/ConsoleLib.Console/Keyboard.cs:926-935`）。`KeyEvent.Set` がない限り `gameQueue` のタスクは流れない。
3. フォーカス喪失中の `PlayerTurn` は `while (!GameManager.focused) Thread.Sleep(200)` で止まる（`XRLCore.cs:737-740`）。さらに `focused` のセッターは false→true の遷移で入力キューを消す（`D/GameManager.cs:404-425`）。フォーカスを保つ仕掛けそのものが、こちらの積んだコマンドを消しうる。
4. CTA の中で待てば、free クエリ（`look`、`inventory`、`kb`）も同じループで、ゲームスレッド上で同期的に処理できる。

ループの中身は次のとおりである。

```text
OnCTA(player):
  keepFocusFlags()                      # §5.4
  if macro != null:
    if macro.delegatesAutoAct and AutoAct.ShouldHostilesInterrupt(): AutoAct.Interrupt(); macro.interrupt(NEW_HOSTILE)
    else: r = macro.Step(); if r in {Continue, Acted}: return exitNormal()
  if steward.Tick() == Acted: return exitNormal()
  emit(decision_request, sitrep)        # 1 回だけ送る
  loop:
    req = inbox.TryTake(100ms)
    GameManager.Instance.gameQueue.executeTasks()   # UI 側からの状態要求を流す（RenderBase と同じ処理、XRLCore.cs:2602-2605）
    heartbeat()
    if req is Free:   reply(runFree(req))            # ゲームスレッドで同期実行
    if req is Act:    macro = start(req); r = macro.Step(); if r in {Continue, Acted}: return exitNormal()
    if req is Yield:  return                          # 人間に PlayerTurn を渡す（台帳に記録）
    if gameOrPlayerChanged(): return                  # キュー処理でロードや終局が走った
  # exitNormal(): SkipPlayerTurn = true を立ててから抜ける（不変条件の保険）
  # エネルギーが残り、かつ AutoAct も非 active なら v1 の 3 層ドレイン（PassTurn → Energy.BaseValue=0）。発生したら HARNESS_DRAIN として記録
```

モーダル prefix の中の待機も同じループを使う。会話の途中で LLM が `look(e1)` を呼んでも、ゲームスレッド上で答えられる。

**CTA を抜けるときの不変条件。** CTA を抜けてよいのは、次の 3 つのどれかが成り立つときだけである。

- エネルギーを消費した
- AutoAct がまだ active である
- 意図的に `Yield` した

この条件を破る抜け方には穴がある。AutoAct の委任中に `:796` の敵対中断、`:810-830` のキー入力中断や端での中断が起きると、`:805` の `IsActive()` が偽になる。すると処理は `:1611` の `PlayerTurn()` まで落ちる。`Done` になったマクロや会話の終了が、エネルギーを 1000 以上残したまま戻る場合も同じである。対策は 2 段にする。

1. `Continue` の前に、ガードで敵対中断を先取りする（§3.4）。
2. `Yield` 以外で CTA を抜けるときは、常に `The.ActionManager.SkipPlayerTurn = true` を立てる。取りこぼしが出ても、`:1584-1588` で `continue` になり、内側ループの次の周回で CTA がもう一度発火するはずである。この「はず」は P3 で確かめる（§12 A4）。

**キューを流すことの危険。** `gameQueue` には重い処理も積まれる。たとえば終局では `EndGame.Start`（暗転、クレジット、コーダ）が積まれる（`D/XRL.World.Conversations.Parts/EndGame.cs:172`）。それが CTA ハンドラの中で入れ子に実行されうる。そこで `executeTasks()` のたびに、`The.Game` と `The.Player` の同一性と `Game.Running` を確かめる。変わっていたら、今の CTA フレームを捨てて何もせずに抜ける。チェックポイントの保存と復帰も、`SaveCommand/LoadCommand.Issue` を通る（`D/XRL/CheckpointingSystem.cs:24,41,256-264`）。それがどこで実行されるかは A3 の確認対象に含める。

### 5.3 タイムアウト、一時停止、切断、再開

- **LLM の応答待ちに、ゲーム側の timeout はない。** ターン制なので、待つこと自体は無害である。遅延の管理はゲートウェイ側で行い、1 呼び出しを 90 秒で打ち切って最大 2 回まで再試行する。それでも失敗したら、文脈を縮めて再送する。180 秒を超えたら overlay に `STALLED` を出す。既定行動は取らない。
- **一時停止**は、サービスループにとどまることと同じである。ゲートウェイの `pause` は「次の決定を送らない」だけで実現できる。
- **切断:** ブリッジスレッドが指数バックオフで再接続する。ゲームスレッドはループにとどまる。再接続したら、保留中の `decision_request` を同じ `seq` で再送する。ゲートウェイは `seq` で重複を除く。
- **wake:** CTA で待つ限り、v1 の `SkipPlayerTurn + KeyEvent.Set`（01 K20）は不要である。例外は `Yield` で人間に渡したあとで、人間から主導権を取り戻すときにだけ使う。

### 5.4 フォーカス

P4 は通常 `PlayerTurn` に入らないので、`XRLCore.cs:737-740` の停止は効かない。残る問題は AutoAct である。非フォーカス時の `Keyboard.kbhit()` は `KeyEvent.WaitOne(200)` を挟む（`Keyboard.cs:938-954`）。AutoAct は 1 歩ごとに `kbhit` を呼ぶ（`ActionManager.cs:810`）。したがって、背景での自動探索は約 5 歩/秒に落ちる。対策として、CTA のたびに `XRLCore.bThreadFocus = true` を書き戻す。`OnApplicationFocus` が false にするのはフォーカス変化の瞬間だけである（`GameManager.cs:1920-1924`）。`GameManager.focused` には触らない（入力クリアの副作用があるため）。`bThreadFocus` はマウスやスクロール処理でも参照されている（`GameManager.cs:1170,1267,1815,2165,3108`）ので、副作用は M1 前のプローブで確かめる（§11 の P4）。

### 5.5 セーブとロード

`IGameSystem` はセーブに含まれる（01 K18）。ソケットとスレッドは `[NonSerialized]` とし、`AfterLoad` で作り直す。コールバック登録は静的リストなので、二重登録を防ぐ（03 §4.3）。`[PlayerMutator]` は新規ゲームでしか呼ばれない（04 §6）。ロード経路では `AfterLoad` と `[CallAfterGameLoaded]` の両方で `RequireSystem` を確認する。

---

## 6. 通信と配置

### 6.1 構成

```text
[CoQ プロセス（Rosetta, x86_64）]                 [qud-gateway（Python 3.12 / uv）]
  LLMOfQud mod（Roslyn C#）                          ├─ WS サーバ 127.0.0.1:4040  ← mod が接続
   ├─ DirectorSystem（CTA サービスループ）            ├─ MCP サーバ（streamable HTTP 127.0.0.1:8787/mcp）
   ├─ WorldModel / Sitrep                            │     ← Claude Code / Codex（M1〜M2 の指揮者）
   ├─ MacroEngine / Guards                           ├─ Brain（Anthropic SDK、M3 以降の常駐指揮者）
   ├─ Steward（C#、決定的）                           ├─ Ledger（追記専用 JSONL + ハッシュ連鎖）
   ├─ ModalGate（Harmony prefix）                    ├─ Memory（notes/*.md、KB 索引）
   ├─ EventBus（メッセージ、IGameSystem、中断）       └─ Overlay（HTTP + WS 127.0.0.1:8790、OBS ブラウザソース）
   └─ Bridge（ClientWebSocket 専用スレッド）
```

### 6.2 なぜ in-process MCP にしないのか

オーナーは C# の in-process MCP に傾いている。P4 はそれを半分だけ採る。ツールの名前と入出力は MCP の形で定義する。ただし MCP サーバ本体はゲームの外、Python のゲートウェイに置く。理由は 3 つある。

- **実証済みの通信路に乗る。** mod がクライアントになる `ClientWebSocket` は v1 で p95 1 ms を出している（01 K19）。`HttpListener` を Mono/macOS でサーバとして使えるかは未検証である（03 U10）。
- **ゲームを再起動せずに頭脳側を作り直せる。** Rosetta での起動はネイティブより遅い（QudJP の検証レポートの比較）。指揮者のプロンプトやマクロ引数の検証ロジックは頻繁に変わるので、ゲームの外に置く。
- **台帳と overlay を 1 か所に集められる。** 証拠の完全性は、ゲームへ届いたすべての操作が 1 つのプロセスを通ることで担保しやすくなる。

C# 側のメッセージは MCP のツール呼び出しと同じ形（`name`、`arguments`、`call_id`）にしておく。後で C# 内に MCP を移したくなっても、移設は機械的に済む。

### 6.3 MCP のツール形（M1〜M2 で Claude Code を指揮者にする場合）

| ツール | 動作 |
|---|---|
| `observe()` | 最新の sitrep を返す（free） |
| `look/inventory/quest_log/journal/kb/look_map/path_estimate` | free クエリ |
| `act(macro, args, intent)` | マクロを開始する。**壁時計の上限（既定 20 秒）で必ず戻る。** 戻り値は `{status: done\|interrupted\|running, cursor, sitrep?}` |
| `wait_events(since=cursor, max_seconds)` | `running` の続き。次の起床事象か上限で戻る |
| `answer_modal(choice)` | 開いているモーダルに答える |
| `note(section, text)` | 記憶ファイルを更新する |

長いマクロをツール呼び出し 1 回で最後まで待たせない。MCP クライアント側のタイムアウトの既定値は製品ごとに異なり、ここでは前提にしない。上限つきで戻り、`wait_events` で続ける形にしておけば、どのクライアントでも動く。

### 6.4 直列化とポート

- JSON。mod 側は Newtonsoft.Json 13 を使う（ゲーム本体が 37 ファイルで `using` しており、ロード済み、03 §5）。コンパイルで参照できるかは P5 で確かめる。駄目なら v1 の手書き JSON（`SnapshotState.cs`）の知識を流用する。
- ポートは 4040（mod↔gateway）、8787（MCP）、8790（overlay）。すべて 127.0.0.1 にバインドし、MCP にはランダムトークンを付ける（RimMolt の 9/15 更新と同じ理由、02 §1.1）。

### 6.5 頭脳側の言語

ゲートウェイと常駐指揮者は Python（uv）にする。オーナーの他リポジトリと揃い、MCP と Anthropic の SDK が成熟していて、v1 の `protocol.py`（pydantic の封筒）と `db/writer.py` を流用できる（01 §4.2）。ゲーム側の判断の速さが要る部分（Steward、ガード、マクロ）は C# に置く。Python からは「方針」だけを送る。

---

## 7. 記憶・知識

### 7.1 何を誰が持つか

一番の記憶係はゲームそのものである。CoQ は、クエストの進行（`XRLGame.Quests`）、地図メモと観察記録（`JournalAPI`）、会話の履歴状態（ゲーム状態、`IfHaveState` 系の述語、04 §3.2）を自分で持ち、セーブに残す。P4 はこれを sitrep の `goals` と `place` に毎回写す。LLM は「どこに何があったか」を覚えなくてよい。

LLM が書くのは、ゲームが持たない 2 種類だけである。

| ファイル | 中身 | 上限 | 書き手 |
|---|---|---|---|
| `notes/run_state.md` | 今の長期目標、中期計画、未解決の疑問、次に試すこと | 約 1,500 トークン | LLM（`note` ツール） |
| `notes/lessons.md` | 周回をまたぐ教訓。「状況 → してはいけないこと/すべきこと → 根拠となった台帳の seq」 | 40 件（RimMolt の `ACTIVE_LESSONS` と同じ、02 §1.1.2） | LLM。追加時に根拠の seq を必須にする |

`run_state` は毎起床の sitrep に全文で入れる。`lessons` はキャッシュされるプロンプト側に入れる。周回の終わり（死亡、または 1 日の運用終わり）には、事後分析のパスを 1 回だけ回す。その出力は `lessons` への追記か、Steward 閾値の変更提案（台帳に残す）のどちらかに限る。「覚えておく」だけの振り返りは受理しない（02 P10、A7）。

### 7.2 知識ベースとネタバレ方針

知識には段階を設け、主張を行う走行でどの段階を使ったかを台帳の冒頭に固定する。

| 段階 | 中身 | 性格 |
|---|---|---|
| K0 | ゲーム内で人間が目にする文章だけ。`Manual.xml`（ゲーム内ヘルプ、約 6k トークン）、キャラクター作成で見える Skills/Mutations の説明、既に開始したクエストのステップ文（`Quests.xml` から、ゲーム内で開示済みのものだけ） | 人間の初見プレイと同等の情報 |
| K1 | K0 + 静的データ全体（`Conversations.xml` の遷移グラフ、`ObjectBlueprints`、未開始クエスト） | 攻略本相当 |
| K2 | K1 + 公式 Wiki（CC BY-NC-SA 4.0、04 §3.4） | 攻略サイト相当 |

**主張用の走行は K0 で行う。** 開発中の走行は K1 まで許す。K2 は使わない。ライセンスの制約があり、しかも「LLM が読んで解いた」のか「攻略を写した」のかの区別が付かなくなる。モデルが事前学習で CoQ の知識を持っていることは避けられない。その点は開示事項として明記する。

`kb(query)` は K0 の範囲だけを BM25 で引く小さな索引である（rimagent の skills 選択と同じ、02 §1.2）。

---

## 8. 評価と証拠

### 8.1 「すでにクリアされているか」「主張できることはあるか」「SOTA なら当然か」

**先行するクリア報告の有無は、まだ確認されていない。** 先行事例の調査（02 §2）が検索したのは Brogue・Cogmind・ADOM の LLM エージェントで、「LLM が Caves of Qud をプレイした」例そのものは検索していない。したがって「初のクリア」を名乗る前提条件として、次の検索を行い、否定結果を日付つきで台帳に残す必要がある。検索先は、英日の Web 検索、Steam Workshop とフォーラム、r/cavesofqud、GitHub、YouTube と Twitch のアーカイブ、arXiv である。本書は、この検索を実施していない。

**主張できることは、条件の組として定義する。** 「LLM が CoQ をクリアした」という一文は、何が手伝ったかを隠す。そこで P4 が支えられる主張の形を、次の組として固定する。

> 「ゲーム版 2.0.211.56、**モード** M、**チェックポイント復帰** R 回、**クラッシュ復帰** C 回、**人間の介入 0 回**、知識段階 K0、**画像入力なし**、マクロ種別 {人間と同じ自動化, UI 迂回・同一バックエンド, P4 独自}、モデル X、実時間 T、トークン N で、エンディング `EndType=E` に到達した」

これに、判断の分担率（agency share）を添える。

- 意思決定のうち、LLM が選んだものの割合
- 同じく Steward が選んだものの割合（規則ごとの内訳つき）
- ゲームターンのうち、エンジン自動行動が消費したものの割合

たとえば「LLM の決定 2,400 回、Steward 9,100 回、エンジン自動行動が全ターンの 81%」のように数値で開示する。この形なら、「画像を使わずにクリアした」「人間が一度も介入しなかった」という 2 点は、RimMolt 配信のクリア（スクリーンショット併用、人間の指示 1 回、02 §1.1.2）と比べて明確に強い主張になる。逆に「LLM が 1 手ずつ操作した」とは主張できない。

**SOTA モデルなら当然クリアできる、とは言えない。** 手元の証拠はすべて反対を向いている。

- BALROG の NetHack では進行度がごく低く、知識と行動のずれが観察されている（02 §1.5）。
- Gemini Plays Pokémon は長時間のループに陥った（02 §1.11）。
- RimMolt の成功例も、約 15 時間、画像あり、人間の指示 1 回という条件つきだった。

CoQ にはさらに固有の難しさがある。

- 数万ターンに及ぶ長さ
- Classic モードのパーマデス
- 会話の述語で分岐するクエスト網（203 会話、1,255 ノード、3,085 選択肢、04 §3.2）
- 終盤で自ら「End game?」に型を打って確定する手順

ハーネスを厚くすればクリアの確率は上がる。しかし、厚くした分だけ「LLM がやった」部分は薄まる。この綱引きを隠さず数値で出すことが、P4 の主張の中心になる。

### 8.2 進行度の指標

| 指標 | 取り方 |
|---|---|
| 主線クエスト到達段 | `Quests.xml` の 28 クエストから主線を順序づけた段数。暫定の並びは Fetch Argyve a Knickknack → Fetch Argyve Another Knickknack → Weirdwire Conduit... Eureka! → A Canticle for Barathrum → More Than a Willing Spirit → Decoding the Signal → The Earl of Omonporch → A Call to Arms → Pax Klanq, I Presume? → Tomb of the Eaters → … → We Are Starfreight / Reclamation。正確な順序と分岐は `Conversations.xml` の `IfFinishedQuest` 述語から機械抽出する（K1 データの開発用利用） |
| 終局 | ゲーム状態 `EndType ∈ {Brightsheol, Marooned, Return, Covenant, Accede, Launch}`（`EndGame.cs:67-77`）と `EndGrade`。副次的に `Achievement.CAVES_OF_QUD` の解除（`:247-249`） |
| 生存・効率 | レベル、ゲームターン、実時間、死亡数、チェックポイント復帰数、起床回数、トークン、費用 |
| 健全性 | マクロ中断の理由分布、`STUCK` と `UNKNOWN_MODAL` の件数、LLM の拒否された行動の割合 |

### 8.3 台帳（何を残すか）

ゲートウェイが追記専用の JSONL を書き、各行に前行のハッシュを含める。主要なレコードは次のとおりである。

- `run_header`: ゲーム版、mod のソースハッシュ、パッチ対象の一覧と適用結果、オプションの完全なスナップショット、モード、知識段階、モデル、プロンプトのハッシュ
- `wake`: sitrep の全文、LLM への入力のハッシュ、出力の全文、選んだ行動と `intent`
- `cmd`: ゲームに届いた操作 1 件ごと。出所（`llm`、`steward:<rule>`、`macro:<name>`、`engine_autoact`、`human`）、ターン、結果の状態差分
- `modal`: 種類、引数、回答、答えた主体
- `audit`: 次の 4 種類
  - ウィッシュの使用。`WishManager.HandleWish` に postfix を当てて記録する（`D/XRL.Wish/WishManager.cs:131-165`）。`goend`・`gocoda`・`gocredits` という終局ウィッシュが実在し（`EndGame.cs:276-325`）、しかもゲーム自身はウィッシュの使用を記録しない。そのため、この記録が必須になる。
  - `PlayerTurn` への進入。`Yield` を出していないのに入ったら、帰属不明の入力の可能性として記録する。
  - `QuickLoad` とチェックポイント復帰。
  - `HARNESS_DRAIN`（§5.2 の 3 層ドレインが発動した回）。

主張用の走行では、次を禁止する。

- `OptionAllowSaveLoad`（QuickSave/QuickLoad、04 §2.4）
- `OptionDisablePermadeath`
- `OptionAllowReallydie`
- ウィッシュと Debug 系のコマンド

これらが無効であることは、`run_header` のオプションスナップショットで示す。

複数日にまたがる走行は、再起動とクラッシュを必ず挟む。その扱いも先に決めておく。

- **計画的な中断:** ゲーム内の「Save and Quit」で終え、次回は同じセーブから再開する。`run_header` に `session_boundary` として記録する。
- **クラッシュ:** 最新の自動セーブ（`OptionAutosaveInterval`、04 §2.3）から再開する。これは `crash_restore` として回数を数え、失われたターン数とともに開示する。クラッシュ直前の数ターンを「やり直せた」ことになるためで、チェックポイント復帰と同じ扱いにする。

この規則がないと、クラッシュが 1 回起きただけで、主張が無効になるか、開示されない巻き戻しを抱えることになる。

### 8.4 再現性

戦闘の乱数はシードを固定しても再現しない（01 K27）。したがって再現性の目標は「同じ結果」ではなく「同じ判断が同じ入力から出たことを検証できる」である。台帳の `wake` には、LLM への入力と出力を全文で残す。第三者は、任意の起床について「この sitrep を見てこの行動を選んだ」ことを確認できる。配信の録画と台帳の `turn` を突き合わせる時刻表も台帳に含める。

### 8.5 ゲームモード

P4 の推奨は、**最初の主張用の走行を Roleplay モードで行い、復帰回数 R を開示する**ことである。Classic（パーマデス）での到達は、その次の目標に置く。

Classic のクリアが最も強い主張であることは変わらない。ただ、数万ターンの 1 回の死が全体を無にする条件で、しかも本書の見積もりが実測前である現状では、最初から Classic に賭けても証拠が溜まらない。Roleplay の復帰は、ゲームの公式モードの機能である。村でチェックポイントを取り（`CheckpointingSystem.ManualCheckpoint`、`D/XRL/CheckpointingSystem.cs:204-223`）、死亡時に `PickOption` で復帰する（`:114`）。どちらも台帳に数えられる。Wander モードは殺害で経験値が入らない（04 §2.6）。戦闘を避けやすい一方で、成長の経路が通常と異なる。このため主張の比較対象になりにくく、採らない。

いずれのモードでも、`OptionAllowSaveLoad` による任意のセーブ/ロード（セーブスカム）は禁止する（§8.3）。

---

## 9. 配信適性

視聴者が見るのは、ゲーム画面（tile モードの Modern UI）と、その右に置く overlay の 2 枚である。overlay の構成は次のとおりである。

- **現在の目標:** `run_state` の長期目標 1 行と、主線クエストの到達段
- **いまのマクロ:** 名前、引数、`intent`、経過歩数。ガードの状態（「敵対なし・HP 75%」）
- **直近の判断:** 起床理由と、LLM の判断理由の要約（出力の先頭 2 文）。「考え中」の表示と経過秒数
- **モーダル・カード:** prefix で横取りしたポップアップは**ゲーム画面には出ない**。そのため overlay に本文と選択肢と、選ばれた答えを必ず出す。会話は話者名と本文を字幕のように流す
- **台帳ティッカー:** 出所つきの操作ログ（`LLM` / `Steward` / `Engine` の色分け）

ペースは次のように決める。探索中はエンジンが速すぎる（01 K15）。そこで `OptionAutoexploreRate` を 8〜12 cells/sec に下げる（`ActionManager.cs:1567-1575` の sleep が効く）。直接 API で動く `fight` と `step` は、CTA サービスループで 1 手ごとに最低 150 ms 待つ。LLM の思考中はゲームが止まる。その間は overlay の「考え中」表示と、前回の判断理由を読ませる時間にする。

視聴者のチャットを LLM への指示として扱わない（02 A9）。視聴者が影響を与えられるのは、ゲートウェイのコマンドとして明示的に許可した範囲（例: 実況用の質問を指揮者に 1 日 1 回渡す）に限る。その場合も台帳上は `human` として記録し、主張用の走行では無効にする。

---

## 10. プラットフォームと更新耐性

### 10.1 Apple Silicon と Rosetta

ゲームのバイナリは x86_64 と arm64 のユニバーサルで、ランタイムは Mono である（03 §4.2）。P4 は、隔離プロファイルを x86_64 スライスで起動する。

```sh
export SteamAppId=333640 SteamGameId=333640
PROFILE="$HOME/Library/Application Support/Freehold Games/CavesOfQud-llm"
arch -x86_64 ".../CoQ.app/Contents/MacOS/CoQ" -savepath "$PROFILE" -logFile "$PROFILE/Player.log"
```

（04 §4.6, §4.9 のレシピに `arch -x86_64` を足したもの）

選択肢は 3 つあった。

- **Rosetta + 同梱 2.2.2:** オーナーの QudJP 検証レポート（`coq-japanese_stable/docs/reports/2026-05-12-harmony-2.4.2-native-arm64-verification.md`）が、同じ M4 機でこの構成が動くこと、ネイティブ + 2.2.2 が `EACCES` で失敗することを確かめている。起動はネイティブ + 2.4.2 より遅いが、更新で壊れない。`Player-prev.log` の「1,693 メソッド、約 62 秒」（03 §4.2）は、そのときのアーキテクチャと DLL の状態が不明なので、ここでは根拠にしない。
- **ネイティブ arm64 + `0Harmony.dll` を 2.4.2 に差し替え:** 起動は速い（QudJP の検証レポート）。ただし 2026-09-25 の Steam 更新で 2.2.2 に戻されていた。更新のたびに手作業が要る。
- **Harmony なし:** §4.5 の代替経路になる。

長時間の無人走行と配信を考えると、「更新で黙って壊れない」ことの方が起動の速さより重い。そこで P4 は、Rosetta + 2.2.2 を既定にする。起動スクリプトはリポジトリに置き、`arch` の結果（`Player.log` のプロセス情報）を `run_header` に残す。

### 10.2 ゲーム更新への備え

- **起動時の自己検査:** mod は起動時に、パッチ対象と写し元の関数が期待したシグネチャで存在するかを `AccessTools` で確認する。確認する関数は、§4.2 の全 prefix 対象、`AutoAct.Setting`、`TradeUI.PerformOffer`、`StatusScreen.BuyStat`、`SkillsAndPowersScreen.SelectNode` である。結果は `build_log` と台帳に出す。1 つでも欠けたら、主張用のモード（`claim_mode`）への切り替えを拒否する。
- **版の固定:** `run_header` に `AssemblyVersion` を記録する。主張用の走行の途中でゲームが更新されたら、その走行はそこで区切る。
- **写し元の追跡:** §3.3 の「エンジンの case 本体の写し」には、写し元の型・メソッド・行と、本体の正規化ハッシュをコメントで持たせる。ゲームが更新されたら、新しい逆コンパイルで同じハッシュを計算し、差分のあった写しだけを見直す。行番号ではなくシンボルを主キーにすることは、01 §2.2 の教訓でもある。
- **コンパイル記号:** `BUILD_2_0_211` が定義される（04 §4.4）。版で分岐が必要になったら `#if` で分ける。ただし分岐は作らないのが原則である。

### 10.3 QudJP との共存

主張用・開発用の走行は、隔離プロファイル（`-savepath`）で **QudJP を無効にし、英語で**行う。理由は 2 つある。

- 実行時テキストが日本語になると（04 §3.5）、K0 の知識源（`Manual.xml`、クエスト文）と文面が合わなくなる。台帳を第三者が検証するときの照合も難しくなる。
- QudJP は 1,693 メソッドにパッチを当てる。モーダル層の prefix と同じメソッドに当たる可能性があり、原因の切り分けが難しくなる。

日本語の配信が必要になったら、overlay 側で指揮者の出力を翻訳する。ゲーム画面は英語のままにする。オーナーの本番プロファイル（QudJP 有効、`Language=ja`）には手を触れない。mod の配置先は隔離プロファイルの `Mods/` への symlink に限る。

---

## 11. マイルストーン（最初の 3 週間）

### 11.1 先に済ませるランタイムプローブ

M1 に必要なのは P1a・P2・P5 だけで、Harmony にも Rosetta にも依存しない。Harmony の成否（P1b）は M2 の前提である。P1b が失敗しても M1 は着地し、その時点で §4.5 の代替経路に切り替える判断ができる。

| # | プローブ | 合格条件 | 関連する §12 の前提 |
|---|---|---|---|
| P1a | 隔離プロファイルで、Harmony を含まない最小 mod（`[PlayerMutator]` + `IPlayerSystem` + CTA フック）をビルド・起動する。Rosetta とネイティブの両方で試す | `build_log` に `Compiling N files...` と `Success :)`。`Player.log` に mod のログ。**M1 の前提はこれだけ** | — |
| P1b | P1a に何もしない Harmony prefix を `Popup.ShowYesNo` に 1 本足し、Rosetta で起動する | `build_log` に `Applying Harmony patches...` と `Success :)`（`D/XRL/ModInfo.cs:851,854`）。prefix が呼ばれたログ。**M2 の前提** | A1 |
| P2 | CTA で 120 秒ブロックし、その間 `gameQueue.executeTasks()` を回す | Unity のフレームが止まらない（UI のアニメーションが動き、ウィンドウが応答する）。ブロック明けにターンが正常に進む | A3 |
| P3 | CTA で `AutoAct.Setting="?"` / `"M x,y"` / `"r"`（フラグ込み）を設定して抜ける。探索中に敵対を出現させる | 同じセグメントで 1 歩進む。中断理由がガードの判定、`AutomoveInterruptBecause`、メッセージのいずれかで取れる。**探索中の敵対出現で、`PlayerTurn` に入らずに新しい CTA が発火する**（`SkipPlayerTurn` の保険込み） | A4 |
| P4 | ウィンドウを非フォーカスにして自動探索する。`bThreadFocus=true` の書き戻しあり/なしで比べる | 書き戻しありで 1 歩 200 ms の待ちが消える。マウスやスクロールの誤動作がない | A6 |
| P5 | `ClientWebSocket` + Newtonsoft.Json の参照でコンパイルし、ゲートウェイと往復させる | コンパイル成功。往復 p95 < 5 ms | — |
| P6 | `PickOption`・`ShowConversation`・`AskString`（`WantsSpecificPrompt` つき）の prefix が値を返し、UI を出さずに処理が続く | 3 種とも UI が出ずに戻る。会話が次のノードへ進む | A1, A2 |
| P7 | 商人に対して `TradeUI.PerformOffer` を画面なしで呼ぶ | 取引画面で同じ品を同じ数だけ売買したときと、水と品物の差分が一致する | A5 |
| P8 | `CommandEvent.Send(player, cmd, ref exit, Target: e)` を、ターゲットを取る能力 3 種で試す | 対象指定が効く能力と、`PickTarget` が開く能力の一覧ができる | A8 |

### 11.2 週ごとの計画

**第 1 週: M1「最初の自律ターン」**

- 1〜2 日目: P1a・P2・P5（並行して P1b）。
- 3 日目までに M1 を達成する。M1 の中身は小さく保つ。
  - CTA で 1 回止まる
  - 最小の sitrep（HP、位置、隣接 8 方向の通行可否、可視の敵対）をゲートウェイに送る
  - Claude Code が MCP の `observe` と `act(step, dir)` で 1 手を返す
  - `Move` が実行され、台帳に `wake` と `cmd` が 1 件ずつ残る
- 4〜5 日目: P3・P4・P6。`look`、`explore`、`goto`、`rest` を実装し、MCP の `act`/`wait_events` の上限つき戻りを入れる。

v1 は LLM を 1 度も呼ばないまま止まった（01 §5）。その轍を踏まないため、M1 にはモーダル、マクロ、記憶のどれも含めない。

**第 2 週: M2「30 分の無人走行」**

- マクロ: `fight`、`flee`、`stairs`、`leave_zone`、`talk`。CTA ガードの 5 項目。
- `EventBus`、重要度、起床の規則（§3.6）、`digest`。
- モーダル層の意味層（`ShowConversation`、`PickOption`、`ShowYesNo(Cancel)`、`AskString`、`AskNumber`）と網羅層。破壊的確認の拒否。
- 台帳のハッシュ連鎖と `run_header`。ウィッシュの監査 postfix。
- 合格条件:
  - Joppa で新規キャラクター（この段階では人間が作成し、台帳に `human:chargen` と記録）を使う。
  - 30 分間、人間の入力なしに進む。
  - Argyve との会話で「Fetch Argyve a Knickknack」を受注する。
  - 未知のモーダルで止まった回数を数え、0 でなければその一覧を得る。

**第 3 週: M3「クエスト 1 本の完遂」**

- Steward（§3.7 の全規則）、`travel`、`trade`、`level_up`、`item/equip`。P7・P8。
- 記憶: `run_state` と `lessons`、周回終わりの事後分析パス。K0 の `kb` 索引。
- 常駐の指揮者を Python の Brain に移す（Claude Code は開発用に残す）。
- overlay v0（目標、マクロ、判断理由、モーダル・カード、台帳ティッカー）。
- 合格条件:
  - 2 時間の無人走行で「Fetch Argyve a Knickknack」を完了する。
  - agency share と起床あたりのトークンを実測する。
  - §2.4 の見積もりを実測値で置き換える。

キャラクター作成の自動化（`EmbarkBuilder.FromCode`）と Roleplay のチェックポイント運用は、第 4 週以降の最初の作業とする。主張用の走行には LLM によるキャラクター作成が必須である。ただし、クエストを進める能力の検証をそれで遅らせない。

---

## 12. 最もリスクの高い前提

| # | 反証可能な主張 | 崩れたときの影響 | 疑う人が読むべき箇所 | 実機プローブ |
|---|---|---|---|---|
| A1 | Rosetta（x86_64）で起動した CoQ 2.0.211.56 では、Roslyn でコンパイルした mod の `[HarmonyPatch]` prefix が、同梱 Harmony 2.2.2 で `Popup` の同期 API（`ShowConversation`、`PickOption`、`ShowYesNo`、`AskString`）に適用され、`return false` で元の処理を置き換えられる | モーダル層の主経路が消える。§4.5 の UI スレッド・ブローカーか Legacy UI に落ち、終局の長押し確定の扱いが未解決になる | `D/XRL/ModInfo.cs:845-862`（`ApplyHarmonyPatches`）、`D/XRL.UI/Popup.cs:1433,1571,1650,2251`、`coq-japanese_stable/docs/reports/2026-05-12-harmony-2.4.2-native-arm64-verification.md`（Rosetta + 2.2.2 の実測）。03 §4.2 の `Player-prev.log:161` はアーキテクチャ不明なので補強にとどまる | 要（P1, P6） |
| A2 | 主線クエストからエンディングまでに LLM が答えるべき選択は、§4.2 の prefix 集合ですべて捕まる。とくに終局の `EndGame` は `Popup.AskString` を通り、prefix が返した文字列で `EndType` が設定される | 捕まらないモーダルでゲームスレッドが `Task.Wait` のまま止まり、無人走行が途切れる。終局を確定できない | `D/XRL.World.Conversations.Parts/EndGame.cs:148-172`、`D/XRL.UI/Popup.cs:1371-1442`（`AskStringAsync` と `WantsSpecificPrompt`）、`D/XRL/CheckpointingSystem.cs:85-136`、`D/XRL.UI/Popup.cs:801-921`（網羅層の対象） | 静的 + 要（P6、M2 の未知モーダル一覧） |
| A3 | ゲームスレッドを CTA ハンドラの中で 60 秒以上ブロックしても、Unity の UI スレッドと描画は止まらない。UI 側からゲームスレッドへの状態要求は、ループ内の `gameQueue.executeTasks()` で処理できる。キューに積まれた重い処理（ロード、終局）が入れ子で走っても、ゲームとプレイヤーの同一性の検査で検出してフレームを安全に捨てられる | P4 の同期モデル全体（§5.2）が崩れる。`PlayerTurn` のアイドル待ちに戻す必要があり、`ClearMouseEvents` とフォーカス停止の問題を正面から抱える | `D/XRL.Core/ActionManager.cs:789-798`、`D/XRL.Core/XRLCore.cs:2600-2605`、`D/XRL.UI/Look.cs:284,317`（UI からの `gameQueue.executeAsync`）、`gameQueue.queueTask` の全呼び出し元（例 `EndGame.cs:172`）と `CheckpointingSystem.cs:24,41,256-264`、v1 の `WebSocketPolicy.cs:25,49-81`（500 ms までしか実証していない） | 要（P2） |
| A4 | CTA で `AutoAct.Setting` を設定してエネルギーを使わずに抜けると、同じセグメントでエンジンが 1 歩実行し、以後の各歩の前に CTA が再発火する。エンジン側で中断されて AutoAct が止まっても、`SkipPlayerTurn=true` の保険で `PlayerTurn` に落ちずに CTA が再発火する。中断理由は、ガードの判定、`AutomoveInterruptBecause`、spot/「You stop … because」メッセージ、独自コードのいずれかで必ず回収できる | マクロ層の実行基盤が消え、経路探索と探索を自前で書くことになる。中断理由が取れなければ、LLM は「なぜ止まったか」を知らずに再計画する | `D/XRL.Core/ActionManager.cs:755-815, 839-1575, 1584-1611`、`D/XRL.World.Capabilities/AutoAct.cs:133-170, 419-490`、`D/XRL.Core/XRLCore.cs:1596-1606, 1920-1925`（写し元） | 要（P3） |
| A5 | `TradeUI.PerformOffer` を取引画面を開かずに呼んでも、画面経由の取引と同じ価格・水の授受・所持品の移動になる | `trade` マクロが使えず、取引画面（UI スレッドの `TradeScreen`）の操作が必要になる | `D/XRL.UI/TradeUI.cs:150-345`（`GetObjects`、`SetNumberSelected`、`UpdateTotals`、`ShowTradeScreen`）、`:1296-1540`（`PerformOffer`）、`:1613`（`CalculateTrade`） | 要（P7） |
| A6 | 非フォーカス時の AutoAct は `Keyboard.kbhit()` で 1 歩ごとに約 200 ms 待たされる。CTA ごとに `XRLCore.bThreadFocus=true` を書き戻せば、この待ちは副作用なしに消える | 配信中や背景での走行が 1 歩 200 ms に縛られ、長距離移動の実時間が数倍になる。書き戻しの副作用があれば、ゲームウィンドウを常に前面に置く運用が必要になる | `D/ConsoleLib.Console/Keyboard.cs:938-954`、`D/XRL.Core/ActionManager.cs:810`、`D/GameManager.cs:1170,1267,1815,1920-1924,2165,3108` | 要（P4） |
| A7 | エンディングの到達は、ゲーム状態 `EndType` がクレジットより前に設定され、その後も読めることで機械的に判定できる | 主張の最終判定を録画の目視に頼ることになる | `D/XRL.World.Conversations.Parts/EndGame.cs:67-120`（判定プロパティ）、`:166-172`（設定と `gameQueue.queueTask(Start)`）、`:247-290`（実績解除とクレジット） | 静的（実機では終盤まで確認できない） |
| A8 | ターゲットを取る能力の多くは `CommandEvent.Send` の `Target`/`TargetCell` 引数で対象を受け取り、`PickTarget` を開かない | `ability(cmd, target)` のたびに `PickTarget` の prefix が必要になり、能力ごとの対応表の保守コストが増える | `D/XRL.World/CommandEvent.cs:44`、`D/XRL.Core/XRLCore.cs:1806-1821, 2323-2334`、`D/XRL.UI/PickTarget.cs:378` | 要（P8） |

---

## 13. 引用の自己照合

03・04 の引用のうち、次を本書の執筆時に `D/`（2.0.211.56）で開いて照合した。行番号が報告と一致したものには ○、ずれていたものには新しい行を記す。

| 報告の引用 | 照合結果 |
|---|---|
| `XRLCore.cs:737-740`（フォーカス停止） | ○ |
| `XRLCore.cs:652-655, 657-680`（AfterRender と NewMessageLogEntry の登録） | ○ |
| `XRLCore.cs:2600-2618`（`RenderBase` の `gameQueue.executeTasks` と休息中の早期 return） | ○（定義は 2600、キュー処理は 2602-2605） |
| `XRLCore.cs:734`（`ClearMouseEvents`）、`:693`（`CallBeginPlayerTurnCallbacks`） | ○ |
| `XRLCore.cs:1920`（`CmdAutoExplore`）、`:1596`（`CmdWaitUntilHealed`）、`:1417/:1503`（`CmdMoveU/D`）、`:1326`（`CmdMoveToPointOfInterest`）、`:2323-2334`（`default:` の `CommandEvent.Send`） | ○ |
| `ActionManager.cs:789`（CTA Check）、`:796`（敵対中断）、`:805`（`AutoAct.IsActive`）、`:810`（`kbhit` 中断）、`:1584`（`SkipPlayerTurn`）、`:1611`（`PlayerTurn`）、`:1567-1575`（`AutoexploreRate` の sleep） | ○ |
| `GameObject.cs:16234`（`Move`）、`:18397`（`AttackDirection`）、`:18058`（`PassTurn`）、`:11424`（`IsHostileTowards`）、`:1176`（`hitpoints`）、`:3645`（`UseEnergy`） | ○ |
| `Popup.cs:658`（`Show`）、`:801-921`（`WaitNewPopupMessage`、`Task.Wait` は 908）、`:1433`（`AskString`）、`:1571`（`ShowConversation`）、`:1650`（`PickOption`）、`:2251`（`ShowYesNo`）、`:2365`（`ShowYesNoCancel`） | ○ |
| `PopupMessage.cs:926-944`（`OnActivateCommand`/`OnSelect`） | ○ |
| `Look.cs:239-251`（`GenerateTooltipContent`） | ○ |
| `ModInfo.cs:845-853`（`ApplyHarmonyPatches`） | ○（`Failure :(` の出力まで含めると 845-862） |
| `Keyboard.cs:938-954`（`kbhit` の 200 ms 待ち）、`:926-935`（`IdleWait`） | ○ |
| `GameManager.cs:404-425`（`focused` のセッター）、`:1920-1924`（`OnApplicationFocus`） | ○（`OnApplicationFocus` の定義は 1920） |

版の注記: 01 は `coq-decompiled_stable` を 2.0.211.50 と書いているが、現在のツリーは 2.0.211.56 である。03 が `NEW/`（scratchpad の `decomp-new`）として引いた行番号は、現在の `D/` の行番号と一致した。
