# 06 推奨 — 何を作り、何を作らないか

> 作成: 2026-09-25（探索フェーズの締め）。比較と採点の根拠は `05-architecture-options.md` にある。
>
> - **引用**: 05 と同じ規約を使う。`D/` は `/Users/sankenbisha/Dev/coq-decompiled_stable`（2.0.211.56）、`Base/` はゲームの `StreamingAssets/Base` を指す。行番号は、本書の作成時に読み直したものに限って載せた。
> - **実機での確認**: 本書の主張はすべて静的な読みに基づく。実機での確認は §5 のプローブで行う。

## 0. 結論

v1 は、LLM を一度も呼ばないまま止まった。文書とコードの比は 4.5:1、ADR は 15 本、決定記録は 44 本あった。今回の探索では 5 案を 3 つのレンズで審査し、14 の主張を敵対的に検証した。その結果、書かれたままで作れる案は一つもなかった。ただし、どの致命傷も一つの層に閉じていた（05 §2.3）。そこで、層ごとに傷のない部品を選んで組む。

**作るもの: 「CTA ターンブリッジ＋外部台帳ハーネス」。** 骨格は P2 で、そこへ他の 4 案の部品を移植する。

- **ゲーム側。** arm64 ネイティブで動き、Modern UI のまま、Harmony を使わない薄い C# mod にする。プレイヤーの `CommandTakeActionEvent`（CTA）で止まり、1 回の呼び出しで 1 手だけ実行する。実行器は、直接 API、case 本体の shim（P5）、C# の 1 歩ガードつき AutoAct 委任（P4）の三つである。P2 の既定の実行器 E1 は使わない。
- **ハーネス側。** Python 3.12 と uv で書く。ゲームの ClientWebSocket の相手になり、ハッシュ鎖の台帳と `verify.py`（P5）を持つ。Claude Code と Codex には、P1 のツール契約を MCP（Streamable HTTP）で出す。これは interactive 走行で、主張には数えない。主張用の走行は、固定したプロトコルで SDK を直接回す protocol 走行にする。
- **観測。** P4 の sitrep の順序、P2 のグリフ地図、C13 の修正を組み合わせる。
- **モーダル。** 避ける、UI スレッドから駆動する、検出する、の三段で扱う。駆動のプローブ R5 が第 1 週の終わりまでに通らなければ、Legacy UI（Plan B）に切り替える。Harmony（Plan C）は、オーナーが決めた場合だけ使う。（2026-09-26 追記: R5 は実機で通った。`probes/R5-modal-driver/results/` と 08 §6.3。Plan B の条件は成立せず、方向 2 を採る。非フォーカスでのゲームスレッド進行も、同日のタイル表示の走行 4 で `probe:focus:play`（`GameManager._focused` の書き直しと毎秒の `CmdWait`）により確認した（30 秒で 28 ターン）。緩和策を長時間保ったときの安定性は R3 に残る。）
- **モードと主張。** Roleplay で A 段位のクリアを先に狙い、Classic の S 段位は計測の後に狙う。Wander は使わない。クリアに数えるのは Spindle 以降の 5 つのエンディングだけにする。主線の途中で退役を選ぶ Brightsheol は、別枠の成果として開示する（§4.5）。クラッシュからの再開でターンを失った走行は、S に残さない（§4.1）。
- **順序。** 本物を書く前にプローブ R0〜R4 を回し、3 日目に M1（最初の自律 LLM ターン）を通す。
- **作らないもの。** v1 の轍を踏まないために、書かない文書と置かないゲートを §7 に列挙する。

## 1. アーキテクチャ

### 1.1 構成

```text
CoQ.app（steamapps の外に固定したコピー、arm64 ネイティブ、隔離プロファイル、自作以外の mod なし、Modern UI）
 ├─ ゲームスレッド ── CTA ハンドラ: 前処理 → 観測を送る → 判断を同期で待つ → 1 手を実行
 ├─ UI スレッド ──── ModalDriver（uiQueue のタスク）: 表示中のポップアップを探し、答える
 └─ ブリッジスレッド ─ ClientWebSocket、2 秒ごとの心拍、フォーカス旗の保持、EndType の監視
          │  ws://127.0.0.1:4040（JSON、seq つき。ゲームはクライアントで、ポートを持たない）
qud-harness（Python 3.12 + uv、別プロセス）
 ├─ ledger.jsonl（ハッシュ鎖）と verify.py
 ├─ MCP サーバー（Streamable HTTP、127.0.0.1:8790/mcp、トークン必須）── Claude Code / Codex（interactive 走行）
 ├─ protocol ループ（LLM の SDK を直接呼ぶ。プロンプトとツール定義は固定）── 主張用の走行
 └─ overlay（SSE、127.0.0.1:8080）── OBS のブラウザソース
```

MCP サーバーと protocol ループは、同じツール定義と同じ台帳を共有する。ツール契約は一つしかない。

### 1.2 CTA の不変条件

1. **CTA を抜ける出口は三つだけにする。**
   - (a) 1 手を実行した。false を返す。エネルギーが 1000 未満ならループはそのまま終わり、残っていれば `CleanEffects` と `BeforeTakeActionEvent`（`ActionManager.cs:777-779`）を通ってから CTA が再発火する（`:789-791`）。判断が無効だったときも false を返し、理由を次の観測に載せる。
   - (b) AutoAct に委任した。同じ呼び出しで `SkipPlayerTurn=true` を立て、true を返す。中断されても `:1584-1588` で CTA に戻る。
   - (c) 人間に明示的に引き渡した。`SkipPlayerTurn` を下ろしてから true を返し、台帳に I4 として記録する。
2. **1 回の呼び出しで打つのは 1 手まで。** 2 手目は CTA の再発火を待つ。P1 の「ハンドラ内で 2 手目を打つ」穴（05 §1.1 の 5）はこれで消える。
3. **既定の行動はない。** 判断が来るまで待ち続ける。待機は `await` を使わない同期待ち（`Monitor.Wait` か `WaitHandle`）で書く。待っている間も、Free の問い合わせ（`describe`、`inventory` など）には、同じループの中でゲームスレッドから答える。
4. **`gameQueue` は、CTA ごとに 1 回だけ、バニラと同じ位置で回す。** 地図を描き直すため、CTA の入口で `RenderBase` を 1 回だけ呼ぶ。`RenderBase` は、ゲームスレッドから呼ばれるとキューを 1 回回す（`XRLCore.cs:2600-2605`）。バニラの PlayerTurn も、反復ごとに `RenderBase` を呼んでいる（`:2368,2373`）。したがって、UI 起点のタスクや、会話が積んだ `EndGame.Start`（`EndGame.cs:172`）が CTA ハンドラの中で走ることは、採用案でも起きる。P1 や P4 との違いは、入れ子かどうかではなく頻度にある。待機中に 100 ms ごとに回すか、CTA ごとに 1 回だけ回すかの違いである。そこで次の三つを足す。
   - **回す前に、キューの中身を台帳に書く。** `ThreadTaskQueue.taskQueue` は private なので、リフレクションで取り出す。列挙は、積む側と同じ `lock(taskQueue)` の下で行う（`QupKit/ThreadTaskQueue.cs:10,102-133`）。各エントリについて、`TaskID`（`queueTask` で積まれたものは null）と、実行する委譲の `Method.DeclaringType` と `Method.Name` を記録する。クロージャなら外側の型まで辿る。
   - **分類は許可リストで行い、TaskID には頼らない。** `EndGame.Start` と、既知のエンジンのタスクは `engine_task` とする。`Qud.UI.*` から積まれたものは `ui_task` とし、I4 に数える。ツールチップの `"LookedAt"+hash`（`BaseLineWithTooltip.cs:172-176`）や、近くの物の twiddle（`NearbyItemsWindow.cs:197`）がこれに当たる。`EndGame.Start` は TaskID を持たないので、「不明なら I4」という規則にすると、本物のクリアが I4 になってしまう。
   - **回した後で、`The.Game.Running` と `EndType` を読み直してから判断を求める。** 終局のタスクが走った後に、判断を要求しないためである。
5. **前処理の shim を、判断を求める前に 1 回呼ぶ。** 中身は `CallBeginPlayerTurnCallbacks`、`Messages.BeginPlayerTurn`、混乱度のリセット、忠誠の補修、`Sidebar.UpdateState` である（`XRLCore.cs:692-733` の写し。チュートリアル専用の `TutorialManager.GameSync` は除く）。これでメッセージログの切り詰めも走る。AutoAct の歩のあいだは shim を呼ばない。エンジン自身が歩ごとに `Sidebar.UpdateState` と `CallBeginPlayerTurnCallbacks` を呼んでおり（`ActionManager.cs:805-809`）、残りは AutoAct が止まって次に判断を求めるときの shim が拾う。
6. **`SkipPlayerTurn` は ActionManager の一回きりの旗で、AutoAct が続く間は消費されずに残る**（AutoAct の分岐の `continue` は `:1577` にあり、`:1584` より前にある）。人間に引き渡す前には必ず下ろす。
7. **EndPlayerTurn のコールバックを、センサー兼脱出口として登録する**（05 §3.3 の 5）。PlayerTurn に入ったら台帳に `sensor: player_turn_entered` を書き、`SkipPlayerTurn=true` を立てて CTA に戻す。`OptionDisableAllIdleTileAnimations` は既定の No のままにする。Yes にすると `IdleWait` が期限なしの待ちになり（`Keyboard.cs:926-935`）、この脱出口が `KeyEvent.Set` を必要とするからである。

### 1.3 実行器

| 行動の種類 | 実行器 | 例 | 出典 |
|---|---|---|---|
| 1 手の移動、攻撃、待機 | 直接 API と shim | `Move`、`AttackDirection`、`CmdWait` の本体（燃えていれば消火を試み、凍っていれば体温を上げ、それ以外は `Search` する。どの場合も `PassedTurn` を発火する。`XRLCore.cs:1517-1540`） | P2 の E0、P1 の失敗 3 の教訓 |
| 所持品、装備、能力値、技能 | 直接 API。能力値、技能、危険な液体は M2 から扱う（確認のポップアップを出すので、ModalDriver と staged answers が先に要る） | `InventoryAction.Process`、`EquipmentAPI`、`StatusScreen.BuyStat`（`StatusScreen.cs:75` の ShowYesNo）、`SkillsAndPowersScreen.SelectNode`（`SkillsAndPowersScreen.cs:212` の ShowYesNo）。Drink は、`OptionConfirmDangerousLiquid`（既定は Yes、`Base/Options.xml:148`）の下で確認を出しうる | P2 の E2、P4、C08 |
| PlayerTurn の短い case | case 本体の shim | `CommandGet`（`TargetCell` つき）、`ThrowWeapon`（`TargetCell` つき） | P5 §3.2 |
| 複数手の移動、探索、休息 | AutoAct の委任と C# の 1 歩ガード | `explore`（`"?"`）、`goto`（`"M x,y"`）、`rest`（`"r"`、`"z"`）、階段 | P4 §3.3–3.4、C07 |
| 方向と対象の選択 | ビューが出てから `Keyboard.PushKey` | PickDirection、PickTarget（射撃、対象を取る能力） | P1、C08 |
| Look | エンジンの InventoryAction。副作用があるので Act のツール `look` に分類し、台帳に残す。Free のツール `describe` は説明文を読むだけで、`AfterLookedAt` を発火しない。二つを同じ名前にしない | 対象の `GetInventoryActionsEvent` から Command が `"Look"` の項目を取り出し、`InventoryAction.Process(target, The.Player)` を呼ぶ。`Description` の処理が説明文のポップアップを出し、それが閉じた後に `LookedAt` と `AfterLookedAt` を発火する（`XRL.World.Parts/Description.cs:333-376`）。ポップアップは (a) 系統で、ドライバーは閉じるボタンだけを押し、本文を観測に載せる。"Recall Story" のボタン（`:350-364`。BookUI に進む）は押さない。`Process` は距離を検査しない（`WorksAtDistance` が効くのは列挙時の `IsUsable` だけ。`XRL.World/InventoryAction.cs:50-68,117-134`）。そのため、対象は `IsVisible()` の物体に限る | 05 C11(d)。主線の "Recover the Mark of Death" は、墓石が `AfterLookedAt` を受けたときにしか進まない（`RachelsTombstone.cs:88-92`） |
| 世界地図の移動 | 直接 API の `Move`。遠い地点へは AutoAct の `"M x,y"`（世界地図で効くかは未検証。R10） | 世界地図での 1 歩、遠い地点への移動、Lost からの回復 | 05 §1.2 の 6、R10 |

**E1 を使わない理由は四つある。**

1. フォーカス停止は PlayerTurn のループの先頭にあり（`XRLCore.cs:737-740`）、E1 のコールバックより先に止まる。
2. ブロック中に人間が押したキーは、キューに残って E1 の命令より先に取り出される。PlayerTurn の入口の `ClearMouseEvents`（`:734`）は、キーのキューを消さない。
3. 押し込んだ命令は、ビューの切り替え（`GameManager.cs:3178-3182`）とフォーカスの遷移（`:412-417`）で消える。
4. explore の `return` のようにコールバックを通らずに PlayerTurn を抜ける経路があり、結果の帰属がぼやける。

shim で書けない命令が主線に現れたら、そのときに E1 と Harmony を比べて決める。今は用意しない。

**実行器の許可リスト。** 専用画面の `.Result` でゲームスレッドを止める操作は、実行器が受け付けない。
- 会話では、Trade のボタンを選択肢として LLM に出さない（TradeScreen、`TradeUI.cs:458`）。
- `InventoryAction` の `"Read"`（`Book.cs:45`、`MarkovBook.cs:66` → BookScreen、`BookUI.cs:429,466`）と、端末の使用（`CyberneticsTerminal.cs:201`、`GenericTerminal.cs:83`）は拒む。本の文章が要るときは、`Base/Books.xml` と `MarkovBook` の生成文から、テキストで渡す。読んだことの副作用（既読の印や秘密の開示）が主線に要る本が見つかったら、R5 で BookScreen の閉じ方を確かめてから Read を許す。
- ステータス画面（`Screens.cs:80,125`）と能力の管理画面（`AbilityManager.cs:149`）も開かない。

### 1.4 観測

- **形式。** P4 §2.2 の sitrep の順序を使う。wake（起こされた理由）、vitals、modal、threats、digest（12 行まで）、goals、place、kit、options の順に並べ、対象は `e3`、`p2`、`i7` のような短い ID で指す。M1 では vitals、threats、digest と地図だけを出す。
- **地図。** P2 のグリフ地図（AfterRender と BackupChar で取った 80×25 の文字）を添える。`OnPaint` 系の上書きで古い字が残ることがある（C13）ので、実体の位置は地図ではなく threats の座標を正とする。
- **C13 の修正。**
  - 表示名は `GetDisplayName(AsIfKnown:false)` だけを使う。
  - 他者の状態は `Strings.WoundLevel` の文言を使う。
  - 実体は `GameObject.IsVisible()` で絞る。
  - メッセージは `OnNewMessageLogEntry` のコールバックで逐次記録し、ポップアップの本文はモーダルを駆動したときに記録する。
  - 注釈はすべて捕獲時に台帳へ書く。後から再計算はしない。
- **場所。** place には、ゾーン名とゾーン ID を入れる。世界地図の上なら、世界地図の座標も入れる。Lost の効果の有無と、ジャーナルの地点メモ（`JournalAPI.MapNotes`、`Qud.API/JournalAPI.cs:33`）も載せる。
- **説明文。** Look のポップアップの本文は、台帳にも残す。刻印の AskString のように、説明文を写す必要がある判断で使う。
- **漏れの監査。** R9 で確かめる。

### 1.5 移植する部品

| 部品 | 出典 | 採る理由 | 最初に要るマイルストーン |
|---|---|---|---|
| CTA 境界、ClientWebSocket、BackupChar によるグリフ地図、SkipPlayerTurn による起床 | P2 §3–§5 | v1 で動いた | M1 |
| 行動文法の表と E0、E2 | P2 §3.1–§3.2 | 引用つきで実行器への写像が書かれている | M1（能力値、技能、危険な液体は M2） |
| AutoAct の結果を、止まった後の CTA で確定する | P2、C09 | 二重実行を防ぐ | M1 |
| ツール契約（Free / Act / Modal の区別、`ok:false` と理由、`expect_seq`、行動後の読み直し、`wait_for_turn` の 45 秒 long-poll） | P1 §3.1 | Claude Code と Codex がそのまま使える | M1 |
| wish の構造的な封鎖（汎用のキー入力と wish をツールにせず、能力の命令は登録済みのものに限る） | P1 §3.1、§8.1 | 検出より強い | M1 |
| SurfaceCheck（起動時のリフレクションでメンバーの有無を確かめる） | P1 §10.3 | 行番号の契約テストの代わりになる | M2 |
| sitrep の順序と ID | P4 §2.2 | 注意の配分 | M1（最小版） |
| C# の 1 歩ガード（HP_CRITICAL、NEW_HOSTILE〈`M`/`P`/`U`/`!` を含む〉、ENGINE_STOP、STUCK、BUDGET） | P4 §3.4 | エンジンの中断の穴を埋める | M1（explore を入れた日） |
| 起床の優先度 P0〜P3 と予算 | P4 §3.6 | 長期戦の費用 | M2 |
| マクロ（travel、fight、flee）と Steward | P4 §3.3、§3.7 | 長期戦の費用 | M3 以降（r と c を測ってから） |
| ハッシュ鎖の台帳、`verify.py`、介入の区分 I0〜I4 と X、protocol と interactive の区別 | P5 §6.3、§8.3 | 主張の骨格 | M1（1 行の形式と鎖の検査） |
| case 本体の shim | P5 §3.2 | E1 の代わり | M1 |
| staged answers | P5 §3.3 | 行動の範囲に限った自動応答 | M2 |
| エピソード（10 判断ごとの追記専用の会話）、外部ノート（`notes.md`）、境界での要約 | P5 §7.1 | protocol ループの文脈の方針になる。費用の試算（キャッシュされる先頭 R=20k）の前提でもある | M2 |
| ウォッチドッグ（ビュー名と心拍） | P5 §4.4 | 静かな停止を検出する | M2 |
| `stray_input` とエネルギーの突き合わせ | P5 §5.4 | 入力の手段に依存しない帰属 | M2 |
| 知識の開示方針 | P5 §7.2 | 主張の条件 | M3（manifest v0） |
| 入力を黙って消す 5 つの仕組みの表と、「落ち着いたフレーム 1 つに入力 1 つ」 | P3 | ピッカーへの PushKey に当てはめる | M1 |
| Legacy UI | P3、C10 | Harmony を使わない退路 | 第 1 週末（R5 が失敗したとき） |
| ポップアップの走査（UI スレッドのシングルトン・タスク） | P2 §4.1 | 検出の土台。複製の窓も探すよう広げる | M2 |
| フォーカスの 2 層（runInBackground と旗） | P2 §5.6 | 旗を書く場所はブリッジスレッドに移す | M1（R3） |

### 1.6 採らないもの

| 採らないもの | 出典 | 理由 |
|---|---|---|
| ゲーム内の `HttpListener` による MCP | P1 | Unity の Mono で一度も測っていない。brain を変えるたびにゲームの再起動が要る。台帳が、落ちうるプロセスの中に置かれる。再起動時にポートを奪い合う（C14） |
| E1 を既定の実行器にする | P2 | §1.3 の四つの理由 |
| 画面だけの観測と、キーだけの入力 | P3 | 入力モデルが実装と逆向きで、観測が貧しく、呼び出しが数万〜10 万回に達する |
| M1 に Steward とマクロを入れる | P4 | 観測と 1 手の制御が固まる前に入れると、失敗の原因を切り分けられない |
| Harmony をモーダルの主経路にする | P4、P5 | Rosetta が要り、Roslyn の経路は測っていない（C04）。終局の確認は Harmony なしで通る見込みである（05 §3.3 の 1） |
| 同梱の 0Harmony を 2.4.2 に差し替える | QudJP の知見 | ゲームの配布物を書き換えることになり、manifest と更新への耐性を損なう |
| CTA の待機中に、100 ms ごとに `gameQueue` を回す | P1、P4 | 判断を待つ間に、UI 起点のタスクや `EndGame.Start` が何度も走り、個別に捨てられない（C01）。採用案も CTA の入口で 1 回は回す（§1.2 の 4）。ただし、バニラと同じ頻度と位置に留め、回す前に中身を記録する |

## 2. brain 側の言語: Python 3.12 と uv

**決定。** brain とハーネスは Python 3.12 と uv で書く。C# は、観測、実行、モーダルの駆動、WebSocket のクライアントだけを受け持つ薄いアダプタにとどめる。ゲーム内の C# MCP サーバーは今は作らない。TypeScript も選ばない。

オーナーが C# のゲーム内 MCP に傾いている理由は、Claude Code や Codex を最初のクライアントにしたいことにある。この目的はそのまま満たせる。Python のハーネスは M1（3 日目）から MCP を Streamable HTTP で出し、Claude Code はそこへ `claude mcp add --transport http` で繋がる。変わるのは、MCP サーバーを置く場所だけである。MCP の Python SDK は、`run(transport="streamable-http")` と `run(transport="stdio")` を引数一つで切り替えられる（context7 で公式ドキュメントを確認、2026-09-25）。Codex の側で HTTP の接続に問題が出ても、同じコアを stdio で出せる。

**Python を選ぶ理由。**

1. **ゲーム内の `HttpListener` は、Unity の Mono で一度も測っていない。** `127.0.0.1` への bind、keep-alive、並行 long-poll、何時間もの安定が、すべて未知である（C14）。ClientWebSocket なら v1 で p95 1 ms を出している。
2. **brain を変えるたびにゲームを再起動せずに済む。** C# の mod は起動時に Roslyn でコンパイルされるので、変更を反映するにはプロセスの再起動か hotload が要る。hotload をするとコールバックリストが空になる（`XRLCore.cs:252-273`）。プロンプトやツール定義を少し直すたびにゲームを落とすのは、開発でも配信でも高くつく。
3. **台帳を、落ちうるプロセスの外に置ける。** ゲームがクラッシュしても、台帳と LLM の文脈は残る。
4. **再起動のときにポートを奪い合わない。** mod の構成を変えるとプロセスが再起動し、新旧のプロセスが重なる（C14）。ゲームを WebSocket のクライアントにすれば、ゲームはポートを持たない。
5. **道具がそろっている。** MCP と Anthropic の Python SDK、uv、v1 の pydantic モデルがあり、オーナーの他のリポジトリも Python と uv で書かれている。

**TypeScript を選ばない理由。** MCP の SDK は TypeScript にもあるが、v1 の資産もオーナーの習慣も Python にあり、TypeScript にしても得るものがない。

**見直す条件。** 二つある。一つは、ハーネスなしで配れる単体の mod（誰でも自分の CoQ に Claude Code を繋げる mod）が目標に加わった場合である。もう一つは、WebSocket の往復が判断の遅れの原因になると実測された場合だが、LLM の応答は秒単位、WebSocket は 1 ms 単位なので、起こる見込みは薄い。

## 3. モーダル UI の戦略

モーダルは、どの案でも書かれたままでは止まる層だった（05 §2.3）。そこで、なるべく出さない、出たら UI スレッドから答える、答えられなかったら必ず気づく、の三段で扱う。

### 3.1 避ける

- **オプションを固定する。** 隔離プロファイルで、次のように設定する。
  - `OptionAutoexploreChests=No`（`Base/Options.xml:123`。既定は Yes）。自動探索が宝箱を開けて PickItem の画面で止まる経路（05 §1.4 の 2）が消える。
  - `OptionAbilityCooldownWarningAsMessage=Yes` と `OptionShowScavengeItemAsMessage=Yes`（`:152-153`）。これらの通知を、ポップアップではなくメッセージログに出す。
  - `OptionPopupJournalNote=No`（`:154`）。ジャーナルに書き込むたびに出るポップアップを止める。
  - `OptionDisplayHPWarning=No Warning`（`:150`。既定は 40%）。遊んでいる間に低 HP の旗を下ろすのは、PlayerTurn（`XRLCore.cs:748-752`）と世界地図の移動（`TerrainTravel.cs:254-261`）の 2 か所である。CTA で完結させると、ローカルの地図で立った旗が次の世界地図の移動まで残り、そこで古い警告の YesNo が 1 回出る。`No Warning` は数値として読めないので閾値が `int.MinValue` になり、旗そのものが立たなくなる（`Options.cs:1339-1346`）。HP は sitrep の vitals と HP_CRITICAL のガードで扱う。
  - `:150-154` の項目には `Requires="OptionShowAdvancedOptions==Yes"` が付いている。ただし `Requires` を読むのは設定画面（`OptionsUI.cs:24`、`Qud.UI/OptionsDataRow.cs:85`）だけで、値の読み出し（`Options.cs:1100-1120`）は `Requires` を見ない。値が効いたかは R0 で確かめる。
  - `OptionDisableTextAnimationEffects=Yes`（`:47`）。フレームの揺れを減らす。
  - `OptionMusicBackground=Yes`（`:180`）。非フォーカスでも Unity を動かす（R3）。
  - `OptionAllowCSMods=Yes`（`:160`）と `OptionModernUI=Yes`（`:53`）。
  - `OptionSessionBackups=None`（`:181`。既定は 3 で、`XRLGame.cs:2164` で読まれる）。主張用のプロファイルでは、ローリングバックアップを作らない。manifest で検査する。
  - `OptionAutosaveInterval`（`:125`。既定は 5）は既定のまま残す。これは、ゾーンの移動 5 回ごとに自動でセーブする設定である（`ZoneManager.cs:1962-1966`）。クラッシュから復旧するのに要る。巻き戻しに使われる恐れは、§4.1 の規則で扱う。
- **画面を開かない。** 所持品、装備、能力値、技能は直接 API で扱う（C08）。インベントリ、ステータス、本、端末、取引の画面は開かない。これは運用の約束ではなく、実行器の許可リスト（§1.3）で閉じる。
- **拾うときは場所を指定する。** `CommandGet` には `TargetCell` か方向を渡す。候補が複数あるなら、1 件ずつ拾う。
- **取引は 3 週間の範囲に入れない。** 価格の前処理を再現しないと結果がずれる（C08）。会話の Trade のボタンは、選択肢として出さない。
- **投げるときは対象セルを渡す。** `ThrowWeapon` に `TargetCell` を渡せばピッカーは開かない。射撃と、対象を取る能力はピッカーに答える（§3.2）。

### 3.2 駆動する

**対象は四つある。**
- (a) ポップアップ。`WaitNewPopupMessage` の単体の窓と、`NewPopupMessageAsync` の複製の窓の両方を含む。
- (b) getvk のピッカー。PickDirection と PickTarget がこれに当たる。
- (c) 専用画面の `.Result`。PickGameObjectScreen は、答えずに `Cancel()` する。それ以外の画面は、許可リストで開かせない。TradeScreen（`TradeUI.cs:458`）、BookScreen（`BookUI.cs:429,466`）、StatusScreensScreen（`Screens.cs:80,125`）、AbilityManagerScreen（`AbilityManager.cs:149`）、CyberneticsTerminalScreen（`CyberneticsTerminal.cs:201`、`GenericTerminal.cs:83`）、GameSummaryScreen（`GameSummaryUI.cs:32`）がこれに当たる。それでも開いてしまったときの閉じ方（各画面の Cancel か Back の経路）は、M2 の前に静的に調べ、R5 に 1 件ずつ加える。
- (d) ThinWorld の生の getch ×8。

**保留中の判定。** ブリッジが走行中で、窓がアクティブで、`commandCallback` と `selectCallback` がどちらも null でないときに、そのポップアップを「答えを待っている」とみなす。トークンには `commandCallback` の参照を使う。ポップアップを出すたびに新しいクロージャが作られるので、同じポップアップに二度答えることはない。

**答え方。**
- 本文の選択肢は `OnSelect` に、下段のボタンは `OnActivateCommand` に渡す。入力欄つきのものは、`inputBox.text` を設定してから `OnInputSubmit` を呼ぶ。終局の確認語もこの方法で確定する（05 §3.3 の 1）。
- 渡すのは実物の項目だけにする。`Hide` を先に呼ばない。
- UI スレッドへは `uiQueue.queueTask` だけで送り、`awaitTask` は使わない。
- ピッカーと getch には、ビューが出てから `Keyboard.PushKey` で答える。ビューが切り替わると UI スレッドが入力を消すからである（`GameManager.cs:3178-3182`）。`getvk` がキーを取らなければ、送り直す。

**誰が答えるか。**
- **staged answers。** 行動の引数から作った答えを、その行動が出すと分かっているプロンプトにだけ使う（P5 §3.3）。能力値を上げるときの確認（`StatusScreen.cs:75`）や、技能を買うときの確認（`SkillsAndPowersScreen.cs:212`）、方向を取る行動の方向がこれに当たる。
- **LLM。** それ以外は LLM が答える。AskString の自由文字入力（刻印、ENTOMB、ASCEND、終局の確認語）も、LLM が自分で書く。
- **ハーネスの規則。** 規則で答えるのは、選択の余地がないものと、走行そのものを終わらせる確認だけにする。
  - 選択肢のないお知らせは閉じ、本文を次の観測に載せる。
  - キーを待つだけの演出には、キーを送って進める。ThinWorld の getch ×8 がこれに当たる（`ThinWorld.cs:275-278`。ビュー名は `"GameSummary"` なので、ウォッチドッグの例外に入れる）。
  - 死亡時のメニューでは、Roleplay なら "Reload from checkpoint" を、**index ではなくラベルの文字列で**選ぶ。選択肢の並びは `OptionDefaultDeathToViewFinalMessages`（既定は Yes、`Base/Options.xml:156`）で入れ替わり、index で答えると "View final messages" のループに入る（`CheckpointingSystem.cs:113-123`）。復帰の回数は数えて開示する（`:111-153`）。
  - wish のプロンプトは、LLM に渡さずに Cancel し、`wish_prompt` として台帳に記録する。wish のプロンプトとは、`WishManager.cs:109` の AskString（"Your wish is my command!"）と、`WishMenu.cs:146` の PickOption（"Wish Menu"）である。
  - ABANDON、RETIRE、CROSS の AskString には、常に Cancel を返す。CROSS は Brightsheol へ渡る確認で（`ThinWorld.cs:62`）、キャラクターを退役させる。選択肢には `[lesser victory]` の札が付いている（`CrossIntoBrightsheol.cs:18`）ので、LLM が勝ちと読んで選びうる。Classic では、選べば走行が終わり、セーブも消える。

### 3.3 検出する

- **ウォッチドッグ。** ブリッジスレッドが 2 秒ごとに心拍を送る。中身は、`CurrentGameView`、ゲームスレッドの状態（CTA で待機中、モーダルの駆動中、走行中）、表示中のポップアップのトークンである。次の二つのどちらかが 30 秒続いたら、`unhandled_modal` として台帳に記録する。
  - ビュー名がモーダルなのに、駆動できるポップアップがない。
  - 判断の要求も心拍の変化もない。

  記録した後は、PickGameObjectScreen なら `Cancel()` し、それ以外は人間に引き渡して I4 として数える。

  `EndType` が空でなくなった後は、`unhandled_modal` を立てない。`EndGame.Start` の 11 秒の Sleep、最大 145 秒のクレジット、期限のないコーダの待ち（`EndGame.cs:288,415,495`）が、CTA ハンドラの中で走るからである。これを例外にしないと、本物のクリアが I4 になり、B 段位に落ちる。
- **センサー。**
  - EndPlayerTurn のカウンタ。PlayerTurn に入った回数を開示する（§1.2 の 7）。PlayerTurn で消費されたコマンドの ID は局所変数（`XRLCore.cs:757` の `text2`）にしかなく、Harmony なしでは読めない。そのため、wish に届いていないことは、wish のプロンプトの側で確かめる（§3.2、§4.5）。
  - エネルギーの突き合わせ。CTA の入口でエネルギーの減少を直前の行動と照らし、合わないものを `unattributed` として I4 に記録する（P5 §5.4）。
  - `stray_input`。CTA の入口でキーのキューを数えてから捨てる。
  - `gameQueue` の中身。CTA の入口で回す前に記録し、`ui_task` を I4 に数える（§1.2 の 4）。人間がマウスをツールチップに乗せるだけで、`AfterLookedAt` がキューに積まれる。それが主線のクエストの段を進めうる（Mark of Death）。
  - `external_answer`。ドライバーが答えていないのに保留中のトークンが消えたら、人間がポップアップを直接クリックして答えたとみなし、I4 として記録する。
  - EndType の監視。ブリッジスレッドが 100 ms ごとに `EndType` と `EndGrade` を読む。Classic の Brightsheol ではセーブが消えるので、その場で捕まえる必要がある（C12）。
- **入力機器の運用規則。** 主張用の走行では、配信機のマウスとキーボードを物理的に外す。確かな防ぎはこれだけである。非フォーカスで止まるのは `ControlManager.GetButton*` の経路だけで（`ControlManager.cs:642-690`）、EventSystem のポインタのイベントは止まらない見込みが高い。ツールチップのホバー（Mark of Death の経路）はポインタのイベントなので、非フォーカスのウィンドウでも発火しうる。非フォーカスで防げるかは未検証として、R3 で測る。

### 3.4 切り替えの規則

- **Plan B。** R5 が第 1 週の終わりまでに通らなければ、Legacy UI（`OptionModernUI=No`）に切り替える。Legacy では、ゲーム中の入力要求の主な経路が文字画面と getvk に乗る（C10）。答えるときは、束縛されたコマンドを `PushCommand` で、束縛されていないキーを `PushKey(bAllowMap:true)` で送り、人間の入力経路（`GameManager.cs:1898-1912`）に合わせる。代わりに、配信の見た目が落ちる。
- **Plan C。** Harmony（Rosetta で起動）は、オーナーが決めた場合だけ使う。R8 は、その判断の材料を並行して集めるためだけに回す。
- **キャラクター作成。** LLM がテキストでビルド（ジェノタイプ、職業、能力値、変異）を選び、ビルドコードとして出す。人間はそれを打ち込むだけにし、入力の代行として I0 に開示する。これで、戦略上の判断を人間に委ねずに済む。前回のビルドは `SavePath/lastcharacter.txt` に残り、`QudChartypeModule` の `Last` で再利用できる（04:193）。3 週間の範囲では自動化しない。

## 4. ゲームモードと主張の戦略

### 4.1 段位

| 段位 | 条件 | 主張の言い方 |
|---|---|---|
| S | Classic、チェックポイントからの復帰 0 回、ターンを失った I1 の復旧 0 回、介入は I0 と I1 だけ、protocol 走行 | 最も強い。「パーマデスで、人間の判断の介入なし」 |
| A | Roleplay の走行か、ターンを失った I1 の復旧がある Classic の走行。チェックポイントからの復帰回数、ターンを失った復旧の回数、失ったターン数を開示する。介入は I0〜I2 を開示、protocol 走行 | 「チェックポイントからの復帰 N 回、復旧による巻き戻し M 回」を併記した別の主張 |
| B | I3（助言）か I4（代行）が 1 件でもある | assisted。「LLM を用いたクリア」にとどまる |
| X | wish、デバッグ機能、セーブの巻き戻しのどれかを使った。巻き戻しとは、台帳が最後に記録した保存と違うセーブをロードすること、`death` の行の後にチェックポイントの復帰以外のロードをすることで、セーブファイルの複製や差し替えも含む。チェックポイントからの復帰と、最後の保存からの I1 の再開は除く | 無効 |

介入の区分は P5 §8.3 に従う。I0 は準備（キャラクター作成の入力の代行、起動、接続）、I1 は基盤の復旧（クラッシュ後の再起動と、直前の正規セーブからの再開）、I2 はハーネスの変更（セッション境界での修正。差分を同梱し、攻略知識を含むものは I3 とみなす）である。

**死と I1 の巻き戻し規則。** 自動セーブの下では、死ぬ直前にプロセスを落として最後のセーブから再開すれば、I1 の体裁で死を消せる。台帳は、クラッシュが偶然か意図かを区別できない。セーブのハッシュを並べても、どのファイルをロードしたかは示せるが、失われたターンは示せない。そこで、次の四つを `verify.py` の検査にする。
1. **死を台帳に書き、死の後のロードを X にする。** プレイヤーの死は、どのモードでも `CheckpointingSystem.ShowDeathMessage` を通る（呼び出しは `GameObject.cs:4065,4082,15059`）。Classic では "DeathMessage" のポップアップ、Roleplay では死亡時のメニューになる（`CheckpointingSystem.cs:85-153`）。ドライバーがこれを見た時点で、台帳に `death` の行を書く。ゲームのスレッドが終わるときに `DeathReason` が `"<nodeath>"` でなく、`EndType` が空であることでも確かめる（`XRLCore.cs:3031-3038`。Brightsheol は `DeathReason` を書くが、`EndType` も書く）。`death` の行の後のロードは、Classic ならすべて X とする。Roleplay なら、死亡時のメニューからのチェックポイントの復帰だけを許し、それ以外は X とする。死亡時のメニューでプロセスを落とし、チェックポイントより新しい自動セーブを読む抜け道を塞ぐためである。
2. **失ったターンを数える。** ブリッジは CTA ごとに `XRLGame.Turns`（`XRLGame.cs:58`）を台帳に書く。この値はゲームのターンごとに 1 つ増え（`ActionManager.cs:1664`）、セーブの情報にも入る（`XRLGame.cs:2243`）。I1 の後の最初の CTA で読んだ `Turns` と、クラッシュ前の台帳の最後の `Turns` の差を、失ったターンとして記録する。この規則が掛かるのは、直前に `death` の行がない復旧だけである。差が 0 の復旧だけを S に残す。差があれば、Classic の走行でも A として扱い、チェックポイントの復帰と同じ欄に数える。Roleplay でも同じ欄に数える。死の前にプロセスを落とせば、チェックポイントの復帰回数を少なく見せられるからである。偶然のクラッシュも区別せずに数える。
3. **セーブの連続性を確かめる。** セーブが書き終わるたびに、ロード元になりうるファイルの SHA-256 を台帳に書く。対象は `Synced/Saves/<GUID>/` の Primary と、Roleplay のチェックポイントである（`CheckpointingSystem.cs:31-34,61-71`）。書き込みは Task で進むので、完了を待ってからハッシュを取る。次の CTA の入口で mtime の変化を見るのが簡単である。ロードのたびに、ロードしたファイルのハッシュも書く。ロードしたハッシュが、台帳の最後の保存（チェックポイントからの復帰なら、最後のチェックポイントの保存）と違えば X とする。
4. **バックアップを作らない。** 主張用のプロファイルは `OptionSessionBackups=None` にし、manifest で検査する（§3.1）。

### 4.2 Roleplay の A から始める

Classic は 1 回のミスで終わる。一方、CoQ には、ガス、液体、遠隔の集中砲火、伝説個体のような瞬間的な大ダメージが多い（05 §1.4 の 8）。最初から S を狙うと、どこで死ぬのかが分からないまま費用を積むことになる。Roleplay では、Joppa や Grit Gate のような拠点のゾーン（`Worlds.xml` で `IsCheckpoint` を持つのは 7 拠点、10 ゾーンである。拠点は YdFreehold、Stilt、Kyakukya、Joppa、Grit Gate、Ezra、Arrivarium）に出入りするたびに、チェックポイントが自動で取られる（`CheckpointingSystem.cs:236-254`、`Zone.cs:2272-2280`）。死んでも、死亡時のメニューから最後の拠点に戻れ、戻った回数は台帳に残して開示できる。ダンジョンの奥で死ねば拠点からやり直しになるので、Roleplay でも死は安くない。終盤の目的地（Golgotha、Bethesda Susa、Tomb、Omonporch）は拠点のゾーンではないので、そこで死ぬと戻る距離が長い。まず A 段位で最後まで通し、区間ごとの死亡率、r、c、1 時間あたりの費用を測る。その数字から Classic のクリアが予算内に収まると見えた時点で、S を狙う。

Wander は使わない。Wander もチェックポイントを持つ（`CheckpointingSystem.cs:165-177`）が、多くの生物が中立から始まる遊び方なので、クリアしても「易しいモードでのクリア」と読まれ、主張が弱くなる。

### 4.3 知識の段

| 段 | LLM に見せるもの |
|---|---|
| K0 | ゲーム内で読める文章だけ（Manual、本、会話、Look の説明、ジャーナル） |
| K1 | K0 に、過去の走行から持ち越したメモを足す |
| K2 | K1 に、wiki のスナップショットを足す。URL、revid、ハッシュを manifest に記録する |

どの段でも、事前学習に含まれる知識は消せない。主張にはそのことを書く。

### 4.4 走行の種類

- **protocol 走行（主張できる）。** Python のループが LLM の SDK（まずは Anthropic の SDK）を直接呼ぶ。プロンプト、ツール定義、モデル ID、effort は固定し、ハッシュを manifest に入れる。LLM が行動ツールを呼ばずにテキストだけで応答を終えたら、固定の 1 行の催促を返し、その回数を数える。
- **protocol ループの文脈。** P5 §7.1 のエピソード（10 判断ごとの追記専用の会話）と、外部ノート（`notes.md`）を使う。エピソードの境界で、LLM が要約とノートを書き、新しいエピソードを始める。履歴を無制限には積まない。費用の試算（§6、§8 の 6）は、この設計を前提にしている。
- **API の障害。** 過負荷やタイムアウトのときは、判断を保留したまま指数バックオフで再試行する。ゲームは CTA で待ち続ける。人手を要しないので介入には数えず、`api_retry` として回数と待ち時間を開示する。人間がハーネスのプロセスを再起動した場合は I1 とする。
- **interactive 走行（主張しない）。** Claude Code や Codex が MCP 経由で遊ぶ。開発と配信の演出には使うが、主張には数えない。ヘッドレスの Claude Code で回した走行も、ループとプロンプトの一部を Claude Code 側が持つので、数えないことを推す（§8 の 11）。

### 4.5 クリアの述語（Harmony なし）

次の五つがすべて成り立ったとき、その走行はクリアしたとみなす。`verify.py` が機械的に判定する。

1. ブリッジスレッドの監視が、`EndType` が空から Spindle 以降の 5 値（Return / Covenant / Accede / Launch / Marooned）のどれかに変わったことを捕まえた。`EndGrade` も台帳に記録する。`Super` なら、Ultra の終わり方である（`EndGame.cs:97`）。
2. wish に届いていない。wish の入口は二つしかない（`HandleWish` の呼び出し元を全件調べた）。一つは、PlayerTurn の switch にある `CmdWish` と `CmdWishMenu` である（case は `XRLCore.cs:1883,1886`、呼び出しは `:1884,1887`）。もう一つは、すべてのプレイヤーに付く `WishMenu` パーツが、`CommandEvent` の `"CmdWishMenu"` を受けて開く wish メニューである（`WishMenu.cs:46,180-185`）。どちらも、願いをポップアップで受ける（`WishManager.cs:109` の AskString、`WishMenu.cs:146` の PickOption）。台帳が次の二つを示せば、この条件を満たす。
   - (i) エージェントの経路に、どちらの入口もない。汎用のキー入力と wish をツールにせず、能力の実行器は、プレイヤーに登録済みの能力の命令しか受け付けない。
   - (ii) wish のプロンプトが一度も出ていないか、出たものをすべてドライバーが Cancel した（§3.2）。人間が答えた wish のプロンプト（`external_answer`）が 1 件でもあれば X とする。

   PlayerTurn に入った回数（EndPlayerTurn のカウンタ）は開示するが、0 であることは条件にしない。想定外の経路で 1 回入っただけで、数日の走行全体が無効になるのを避けるためである。
3. ロードされた mod が自作の mod だけで、`Managed/*.dll` と `StreamingAssets/Base` のハッシュが manifest と一致する。mod の一覧は `build_log.txt` から抽出する（`ModInfo.cs:767,772` の出力）。
4. 台帳のハッシュ鎖、介入の一覧、センサーの集計、セーブの連続性（§4.1）を `verify.py` が検査し、OK を出した。
5. 走行の前に公開した manifest のハッシュと、走行中に外部へ出した台帳の先頭ハッシュ（§6 の第 2 週と第 3 週）が、手元の台帳と一致する。

**Brightsheol はクリアに数えない。** Brightsheol は、主線の途中で自分から退役を選ぶ終わり方である。
- Tomb of the Eaters の段 "Ascend the Tomb and Cross into Brightsheol"（`Base/Quests.xml:389`）で着くセラフの会話が、「Salum に戻るか、Brightsheol へ渡るか」を問う（`Base/Conversations.xml:10568-10587`）。
- 渡る側の選択肢は `CrossIntoBrightsheol` パーツを通り（`D/XRL.World.Conversations.Parts/CrossIntoBrightsheol.cs:24`）、確認の AskString は "Crossing into Brightsheol will retire your character" と告げる（`ThinWorld.cs:62`）。
- この段は "Disable the Spindle's Magnetic Field"（`Quests.xml:393`）と "Return to Grit Gate"（`:397`）より手前にある。その先に、Reclamation（`:475`）と We Are Starfreight（`:466`）が続く。
- ゲーム自身も、この選択肢に `[lesser victory]` の札を付けている（`CrossIntoBrightsheol.cs:18`）。会話で終える終局の選択肢には `[victory]` か `[greater victory]` を付ける（`EndGame.cs:144`）。ただし、AscensionCable、Sheva、`CheckMarooned` の経路は、札なしで `Start()` を呼ぶ。

ハーネスは、CROSS の確認に常に Cancel を返す（§3.2）。セラフの会話で "Cross" を選んでも、確認で止まって会話に戻る。これで、LLM が札を勝ちと読んで走行を終わらせることを防ぐ。オーナーが Brightsheol を数えると決めた場合（§8 の 2）は、この規則を外し、Brightsheol に着いた走行を「Brightsheol で退役」という別の成果として台帳に残す。主張文にもその名で書く。

CAVES_OF_QUD 実績は、解除済みなら何もしないので証拠に使わない（C12）。

## 5. 本物を書く前に回すプローブ

R0 から R7 までをこの順に回す。R9 は R2 の後ならいつでもよく、R8 は並行して回す。R10 は第 3 週に回す。どのプローブも、R0 で作る隔離プロファイル（§3.1 のオプション）の上で行う。結果は README の表に 1 行ずつ書く（日付、結果、証拠のファイル名）。プローブごとのメモは書かない。

| ID | 確かめること | 手順 | 期待する証拠 | 失敗したら |
|---|---|---|---|---|
| R0 | ビルドの固定、プロファイル、mod のロード | `steamapps` の外にコピーした CoQ.app から起動する。前例は QudJP の `~/Games/CavesOfQud-stable-ref` である（04:164）。隔離プロファイルの `Local/ModSettings.json` を事前に書き、自作以外の mod の ID をすべて `Enabled:false` にする。対象は Workshop の 6 件（04:210）と、`StreamingAssets/Mods`、`Local/Mods` の中身である。新しい mod は既定で `Enabled=true` になる（`XRL/ModSettings.cs:16`）。SteamAppId を export した起動と、`STEAM:NO` の起動の両方で、Workshop の mod が読まれるかを実測する（04:218 の未確認点）。`OptionAllowCSMods=Yes` にして、空の mod を入れる | build_log.txt に "Compiling 1 ..."（`ModInfo.cs:767`）と "Success :)"（`:772`）が出て、mod の一覧が自作だけである。起動スクリプトが、AssemblyVersion、buildid、`Managed/*.dll` と `StreamingAssets/Base` のハッシュを許可リストと照合し、合わなければ起動を拒む。QudJP の Harmony の差し替え（03:302）もここで検出される。Player.log に mod の初期化ログが出る。init で §3.1 の各オプションを `Options.GetOption` で読んでログに出し、すべて設定どおりである | Workshop の mod が止まらなければ、読まれない起動の形に固定する。それでも読まれるなら、許可リストの検査で起動を拒む |
| R1 | CTA の長時間ブロック（2×2） | CTA で {60 秒, 10 分} × {フォーカスあり, なし} の四通りに止める。`gameQueue` は回さない | ブロック中も、ブリッジから `uiQueue` に積んだ空のタスクが 1 秒以内に戻る。解放後に 1 手だけ実行され、次の CTA が来る。Player.log に例外がない。EndPlayerTurn カウンタが 0 | 設計の要なので、第 1 週のうちに見直す。待つ場所を PlayerTurn の getvk に移し、P3 の入力モデルを直したものを候補にする |
| R2 | ClientWebSocket と Newtonsoft | 観測と判断の往復を 1,000 回。途中で接続を切り、繋ぎ直す | 往復の p95 が 5 ms 未満（v1 は 1 ms）。繋ぎ直した後、保留中の判断要求が同じ seq で送り直される | v1 の実装をそのまま使う |
| R3 | ブリッジスレッドからのフォーカス維持 | フォーカス中に `OptionMusicBackground=Yes` を設定しておく。ブリッジスレッドが 100 ms ごとに `XRLCore.bThreadFocus=true`、`GameManager._focused=true`、`focusedEvent.Set()` を書く。ウィンドウのフォーカスを外して AutoAct を歩かせる | 非フォーカス時の AutoAct の毎秒の歩数が、フォーカス時の 80% 以上。PlayerTurn のフォーカス停止（`XRLCore.cs:737-740`）に一度も入らない。フォーカスを行き来しても、ピッカーへの PushKey が再送を含めて必ず届く。加えて、macOS 側の眠りを確かめる（推論にもとづく追加で、実機でしか分からない）。ウィンドウを他のウィンドウで覆った状態と、別のアプリをアクティブにした状態で、1 時間ずつ走らせる。`caffeinate -dis` を併用し、CoQ の App Nap を `defaults write <bundle id> NSAppSleepDisabled -bool YES` で止める。アプリの Info.plist は書き換えない。1 時間を通して、AutoAct の歩数と OBS のウィンドウ取り込みのフレームレートが落ちない。非フォーカスのウィンドウで、マウスのホバーがツールチップを出して `gameQueue` にタスクを積むかも記録する（§3.3） | 配信機ではゲームのウィンドウを常に前面に置く運用にし、フォーカスを失った時間を台帳に記録する（§8 の 10） |
| R4 | AutoAct の委任と SkipPlayerTurn | Joppa の周りで explore、goto、rest を 500 ターン回す | 500 ターンを通して EndPlayerTurn カウンタが 0。中断のたびに CTA に戻り、理由（ガード名かエンジンのメッセージ）が台帳に残る。1 判断あたりのターン数の分布が取れる | `SkipPlayerTurn` を立てる場所とガードを直す。直らなければ EndPlayerTurn の脱出口で拾い、回数を数える |
| R5 | モーダルの駆動（4 系統） | 開発プロファイルの使い捨てキャラクターで試す。(a) ShowYesNo、PickOption、会話、お知らせ。(b) 終局と同じ `WantsSpecificPrompt` つきの AskString（Classic の ABANDON `XRLCore.cs:1751`、Roleplay の死亡時の RETIRE `CheckpointingSystem.cs:135`）に、違う語、Cancel、正しい語の三通りで答える。刻印の AskString には自由な文字列を返す。(c) PickDirection と PickTarget に PushKey で答える。(d) 宝箱の PickGameObjectScreen を `Cancel()` する。(e) §3.2 の (c) で閉じ方を静的に調べた専用画面を、1 件ずつ開いて閉じる。(f) wish のプロンプトを出し、ドライバーが Cancel する | トークン 1 つにつき応答がちょうど 1 回。Player.log に AggregateException がない。ゲームスレッドが、人間が選んだときと同じ結果で再開する（違う語と Cancel ではゲームに戻り、正しい語では確定する）。ビューが Stage に戻る | 第 1 週の終わりに Plan B（Legacy UI）へ切り替える |
| R6 | セーブ、終了、ロード、hotload、死亡からの復帰、クラッシュからの再開 | セーブして終了し、ロードする。メインメニューに戻って再開する。開発プロファイルで `reload` の wish を使う。Roleplay で死亡し、死亡時のメニューで "Reload from checkpoint" をラベルで選んで復帰する。この経路では、`LoadCommand.Execute` → `XRLGame.LoadCurrentGame("Checkpoint")` と進み、走行中に ActionManager のコマンドとしてゲームが差し替わる（`CheckpointingSystem.cs:37-72`）。最後に、プロセスを kill して再起動し、自動セーブから再開する（I1 の経路） | どの時点でも、各コールバックリストに自分の登録がちょうど 1 本ある（リフレクションで数える）。ブリッジが 1 インスタンス。ロード、復帰、再開の後の最初の CTA で、判断要求がちょうど 1 回出る。保留中の seq と台帳の game ID が食い違わない。台帳に、復帰や再開の行、ロードしたセーブの SHA-256、失ったターン数が書かれる | 登録を init のたびに無条件で行う形に直す |
| R7 | 直接 API と shim の同等性 | 同じセーブを 2 回ロードし、同じ操作を直接 API（または shim）と画面経由で 1 回ずつ行う。対象は `BuyStat`、`SelectNode`、`EquipObject`、`InventoryAction.Process`（Drink、Eat、Apply）、`CommandGet`（`TargetCell` つき）、`ThrowWeapon`（`TargetCell` つき）、`CmdWait` の shim、Look の InventoryAction（`Look.cs` の画面での Look と比べ、`RevealNoteOnLook` などを持つ物体で同じジャーナルの変化が起きるか）。ロード時に乱数が再シードされる（`XRLGame.cs:1892-1897`）ので、同じセーブからなら結果を比べやすい。ただし画面を開く側が乱数を余分に使えば、命中やダメージのような乱数の結果はずれうる。乱数で決まる結果は比較から外す | エネルギー、所持品、能力値の差分と、乱数に左右されないメッセージが一致する | 一致しない操作は、画面経由（ピッカーへの PushKey）に回すか、範囲から外す |
| R8 | （任意、並行）Rosetta 上の Harmony | 開発用の別の mod に `[HarmonyPatch]` の prefix を 1 本だけ入れ、Rosetta で起動する | build_log に "Applying Harmony patches..."（`ModInfo.cs:851`）に続いて "Success :)"（`:854`）が出て、prefix が発火する | Plan C を捨てる |
| R9 | 観測の漏れ | 200 ターン分の観測を、人間に見える述語（`GetDisplayName(AsIfKnown:false)`、`Strings.WoundLevel`、`IsVisible()`）で作り直した値と突き合わせる | 未鑑定品の本名が 0 件、見えないセルの実体が 0 件、Scanning なしでの他者の数値 HP が 0 件 | protocol 走行の前に観測器を直す |
| R10 | 世界地図の移動と Lost | Joppa から Red Rock と Grit Gate まで、世界地図で移動する | 世界地図の上で、`Move` と AutoAct の `"M x,y"` が進む（自動探索は世界地図では効かない。`XRLCore.cs:1920-1926`）。遭遇の YesNo と "You're lost!"（`TerrainTravel.cs:201-206`）を、ドライバーが閉じる。Lost の間は世界地図へ出られず（`Lost.cs:178-182`）、その理由が観測に載る。Lost は、既訪のゾーンに入る、新しいゾーンに入る（20%、Survival があれば 40%）、会話で道を聞く（`ConversationUI.cs:452-461` の `CheckLost`）のどれかで解ける（`Lost.cs:150-172`） | 世界地図の移動を 1 歩ずつの `Move` に限る。Lost の解き方を、sitrep に文章で書く |

## 6. 3 週間の計画

2026-09-27の最新状況は次表のとおり。下の追記は達成時点の履歴として残す。修正・検証はCodexが担当し、Claude CodeのOpus 5.5（xhigh）は実際のプレイにだけ呼ぶ。

| 項目 | 現在の証拠と残件 |
|---|---|
| R0〜R2、R4、R5、R6 | 固定版検査、CTA長時間待機、通信・再接続、AutoAct、本番モーダル18ケース、ライフサイクル5経路を実機確認。各READMEに適用版と未検証の組合せを記録。 |
| R3 | 非フォーカス・被覆下の長時間運転とピッカーは確認済み。操作干渉を避けた実ホバー再試験では、前面でtooltipとLookedAt投入を確認し、同じ位置の非フォーカス試験ではtooltipが出なかった。入力遮断全般の保証にはしない。[比較記録](../../probes/R34-autoact/results/r3-hover-comparison7-20260927.json)。 |
| R7 | 9/10ケースが一致。投擲はコストイベント観測点の1000と着弾セルが一致しても、実消費957/1016の差が再現した。厳密な同等性はFAIL、直接投擲は本番受入外。 |
| R9・観測 | 従来の211観測監査は合格。追加したgroundは拾得の6ケース、goalsは表示・非表示・省略の6条件を実機確認した。追加欄の200ターン監査は別途必要。 |
| R10 | Red Rock・Grit Gate、世界地図の出入り、遭遇、Lost時の地上移動を確認。世界地図のgotoなど未対応・未検証の分岐は残る。 |
| M1以後の実プレイ | 200ターンの短い試走に続き、30分18秒で374判断受理・373完了・1,037前進ターンを記録。実死亡からの復帰1回、413ターン喪失。最初のクエストは未完了。[実行記録とCodexの照合](../../.codex/artifacts/claude-m1-quest-pilot-20260927.md)。 |
| 長期記憶・1時間走行 | 出典付きの永続ノート・台帳検索・10判断ごとの文脈交代を実装。62分13.5秒で270判断受理、27文脈を完走。死亡復帰1回・356ターン喪失。死亡累計の提示を補強後、保存・再起動して追加10判断を継続した。クエストは未完了。[試験記録と残件](../../.codex/artifacts/claude-memory-hour-20260927.md)。 |
| 長期記憶・改修後の実地試験 | 検索・危険と計画の提示・短い一括保存を改善。4走行計30分42.4秒、151判断受理・完了、追加死亡0。途中で判明した10判断超過、終了通知欠落、モーダル中の誤起動を修正し再試験した。equipと所持容器のopenも追加し、装備・容器の開閉・取出しを複製セーブで確認。文脈末尾の時間比率は34.7%→15.6%（場面が違うため因果比較ではない）。Watervine・Argyveは未完了。Python229、C# policy/bridge107項目と固定DLLコンパイルが合格。[改修・試験報告](../../.codex/artifacts/claude-memory-improvement-20260927.md)。 |
| M2・M3 | 正式条件は未達。SDK直接走行は資格情報待ちで保留し、ユーザー指定でClaude Codeを先行。エピソード・ノートは実装済み。EndType/EndGrade、エネルギー帰属、staged answers、OBSへの焼込みなどは残件。今回のClaude Code無人走行をSDK protocolの全条件達成やクエスト達成に数えない。 |
| 同じMacでの並行作業 | `--batchmode` とmodの起動フックで、既存セーブの自動ロード→操作→保存→正常終了→再起動を実機確認。正常3走行で前面化通知・前面状態・画面上の窓は0。モーダル18ケースと60秒保持も合格。並行作業中はこのモードを使う。実入力・フォーカス切替の試験、キャラ作成、ロック・スリープ中の継続、ゲーム窓のOBS録画は対象外。[結果](../../probes/R0-runtime/README.md)・[運用条件](../../mod/README.md#起動と終了)。 |

監視の追加では、未応答で閉じたモーダルの集計、残留キーの計数・破棄、行動目的の台帳保存とブラウザ表示を実装した。残留キーは実キューへ1件投入する治具で、計数後に移動せず次の判断も1回だけ実行することを確認した。古い走行の `stray_keys` は未計測としてnullを返す。詳細は [ハーネスREADME](../../harness/README.md)。

> 2026-09-26 引き継ぎ実測: R1 / R2 は実機で合格した。R1 は 60 秒 / 600 秒 × 実フォーカスあり / なしの 4 条件を確認し、UI 最大 14.6956 ms、全条件で解放後 1 手・次 CTA 到達・EndPlayerTurn 0。非フォーカスへの切替はユーザー許可の AppleScript で行った。R2 は 1,000 往復、p95 0.406 ms、切断後の同一 seq・本文再送を確認した。既知の起動時 GOG 例外と意図的切断の記録を除き、プローブ開始後の新しい例外は 0。結果と証拠は [R1 / R2 README](../../probes/R12-bridge/README.md)。
>
> 同日追記: R0 は固定版 `2.0.211.56` の 613 ファイルのハッシュ、許可した mod、12 オプションを検査し、Steam 有効 / 無効の両起動で実機確認した（[R0 README](../../probes/R0-runtime/README.md)）。R4 は explore / goto / rest を 500 ターン、23 判断で完走し、PlayerTurn / EndPlayerTurn はともに 0。通知 2 件も UI tick で応答した。R3 の 60 秒比較は移動速度が前面比 98.16%、OBS の実更新頻度が 91.45%、フォーカス切替中の方向ピッカーは 10 / 10 到達。非フォーカス 1 時間は 3,600,040 ms・65,011 回の位置変化で、移動速度は前面比 99.98%、OBS の実更新頻度は 97.51% を確認した。被覆用 Finder 窓を配置した別の 1 時間も 3,600,050 ms・65,351 回で、移動速度は前面比 100.50%、OBS の実更新頻度は 97.94% だった。被覆窓は開始・途中・終了付近に確認したが、重なり順の連続測定はしていない。方向ピッカーの最初の入力を投入前に捨てる模擬損失でも、10 / 10 を再送で完了した。実ホバーによるキュー投入は未確認であり、R3 全体の合格とはしない（[R3 / R4 README](../../probes/R34-autoact/README.md)）。これらは決め打ちのプローブで、R9、MCP 接続、M1 の自律 LLM ターンは未完了。R9 の静的監査では、v1 の他者数値 HP と、可視性検査のない隣接敵 ID の経路を確認したため、そのまま移植しない（[監査メモ](../../.codex/artifacts/r9-observation-audit-20260926.md)）。

### 第 1 週: M1「最初の自律 LLM ターン」を 3 日目に

> 2026-09-27 の追加検証: R9 は実機で 210 回の待機、211 観測、208 前進ターンを記録し、未鑑定品・非可視の生物・Scanning なしの可視生物の漏れは 0 件。台帳の送信フレーム照合も通り、`r9_claimable:true` を確認した（[R9 README](../../probes/R9-observation/README.md)）。R3 の実ホバーは前景で tooltip → pointer exit → 新しい LookedAt タスクの投入を確認したが、背景条件は未成立。MCP は `respond` を含む4ツールへ拡張済みで、ModalDriver の本番経路の実機試験、R6・R7・M2 は引き続き未完了。以下の M1 記録は達成時点の3ツール構成を示す。 その後、本番 ModalDriver の18ケースを MCP 経由で実測し、60秒保持・不正回答拒否・通常ターン復帰と52行の台帳照合が通った。実死亡・復帰と専用画面の残件は R6 などで続ける。SDK 直接走行は保留し、ユーザー指定で Claude Code 経由の無人試験を先行する（interactive として記録する）。

> 2026-09-27 追記: M1 を実機で達成した。Claude Code の Opus 5.5（`claude-opus-5-5`、`xhigh`）へゲーム用 MCP の3ツールだけを渡し、`get_state` → `act(wait)` → `get_state` を実行した。seq 1 の判断要求・判断・結果と seq 2 の要求が台帳に残り、ハッシュ鎖・リンク・次 CTA を確認した。世界ターンは3→4、PlayerTurn / EndPlayerTurn はともに0。Python 89テスト、C# ポリシー32項目、固定版 DLL 参照と実機 Roslyn のコンパイルも成功した。実装は [harness](../../harness/README.md) と [mod](../../mod/README.md)、Claude の呼び出しと実機照合は [実行記録](../../.codex/artifacts/claude-m1-play-20260927.md)。これは interactive の限定走行であり、R3 の実ホバー、R6、R9 の200ターン監査や M2 の達成を意味しない。

- **1 日目。** R0（ビルドの固定と mod の許可リストを含む）、R1、R2。
- **2 日目。** R3 と、explore だけの最小版の R4。最小の観測（vitals、threats、digest、グリフ地図）。台帳の 1 行の形式と、鎖だけを検査する `verify.py`。
- **3 日目: M1。** MCP で繋いだ Claude Code が `get_state` を読み、`act` を 1 回呼ぶ。CTA ハンドラが 1 手だけ実行する。台帳に判断要求、判断、行動の結果の 3 行が残り、`verify.py` が OK を返し、EndPlayerTurn カウンタが 0 のままである。これを満たせば M1 とする。M1 の実行器は、移動、攻撃、待機、explore に限る。
- **4〜5 日目。** explore、goto、rest、wait の shim と C# のガード。Joppa で 200 ターンの interactive 走行。R5 を回し、週末に Plan B へ切り替えるかを決める。

2026-09-27 追記: R6 の5経路を実機で検証した。死亡・チェックポイント復帰と hotload は run5、メニュー再入場・正常終了・クラッシュ再開は run6〜8 の別系列で確認。クラッシュ前13→自動保存9の4ターン喪失を照合した。起動・セーブ選択・初回 arm は運用者補助であり、無人起動の達成ではない。詳細と失敗履歴は [R6 README](../../probes/R6-lifecycle/README.md)。

### 第 2 週: M2「無人で 1 時間」

- SDK を直接呼ぶ protocol ループ。行動ツールを呼ばずに終わった応答には固定の 1 行の催促を返し、回数を数える。
- ModalDriver（§3.2 の 4 系統）、staged answers、ウォッチドッグ、センサー（EndPlayerTurn、エネルギー、`stray_input`、`gameQueue` の中身、`external_answer`、EndType）。
- 能力値、技能、危険な液体の操作（ModalDriver の後）。
- エピソードと外部ノート（P5 §7.1）。
- overlay v0。sitrep の要約、最後の判断と理由、台帳の先頭ハッシュを出す。先頭ハッシュは常に画面に出し、VOD に焼き込む。
- Roleplay の死亡時の規則（復帰を選び、数える）。
- R6、R7、R9。
- **終了条件。** protocol 走行が無人で 1 時間続き、`verify.py` が OK を返し、EndPlayerTurn センサーが 0 で、`unhandled_modal` がすべて台帳に記録されている。

### 第 3 週: M3「最初のクエスト」

- protocol 走行で、Joppa の最初のクエスト（"What's Eating the Watervine?" か "Fetch Argyve a Knickknack"）を完了させる。
- 無人で 2〜4 時間の走行を回し、r（1 判断あたりのゲームターン）、c（1 判断あたりの呼び出し）、1 呼び出しあたりの秒数、キャッシュの読み出し率、思考トークンの量、1 時間あたりの費用を測る。P5 のコストモデル（中心の試算で Opus 5.5 なら約 $0.9k、約 75 時間）の仮定を、実測値で置き換える。この試算は、エピソードと外部ノートの設計と、1 呼び出し 12 秒を前提にしている。effort や思考の量しだいで秒数が数倍に伸びれば、走行時間、更新のリスク、配信の長さが一緒に膨らむ。
- R10（世界地図の移動と Lost）。
- manifest v0。中身は、ゲームのビルド（AssemblyVersion と Steam の buildid）、`Managed/*.dll` と `StreamingAssets/Base` のハッシュ、ロードされた mod（build_log から抽出）、`ModSettings.json`、ハーネスの commit、プロンプトとツール定義のハッシュ、モデル ID と effort、プロファイルのオプション（`OptionSessionBackups=None` を含む）である。
- 外部への固定。主張用の走行を始める前に、manifest を公開リポジトリに push して時刻を固定する。走行中は、30 分ごとに台帳の先頭ハッシュを同じリポジトリに push する。VOD はローカルでも録画し、配信サービスとは別の場所に保存する。配信サービスの VOD には保存期限がある。
- r が小さければ、起床の優先度と予算（P4 §3.6）を入れる。マクロと Steward は、この計測を見てから決める。

## 7. 作らないもの、書かないもの

v1 が止まった原因は、コードより先に文書とゲートが育ったことにある。次のものは意図して作らない。

- **ADR、決定記録、仕様の凍結は書かない。** 決めたことはコードとコミットメッセージに残す。この 05 と 06 が、探索フェーズの最後の文書になる。
- **envelope の層や冪等性の層は作らない。** 古い seq とトークンを捨てるだけにする。
- **SafetyGate の分類体系は作らない。**
- **証拠パッケージの梱包、墨消し、ablation、セグメント評価は M3 まで作らない。** 台帳の 1 行の形式と `verify.py` の鎖の検査だけは、M1 から持つ。外部への固定（manifest と先頭ハッシュの push）は梱包ではなく push の繰り返しなので、M3 の manifest v0 に含める。
- **grep で行番号を確かめる契約テストや、行番号の対応表は作らない。** 更新への備えは、起動時の SurfaceCheck だけにする。
- **PR ごとのレビューゲートや、プローブごとのメモは作らない。** プローブの結果は README の表に 1 行ずつ書く。
- **本体の mod に Harmony のコードを入れない。**
- **取引、Tinkering、キャラクター作成の自動化は、3 週間の範囲に入れない。**

ゲートは二つだけ置く。一つは `verify.py` の OK、もう一つは主張用の走行を始める前の manifest の検査である。

## 8. オーナーだけが決められること

1. **主張のモードの順序。** Roleplay の A から始めるか、Classic の S を最初から狙うか。2026-09-21 の NetHack の ascension を受けて、他のチームが CoQ に来る時期をどう見るかで答えが変わる。推奨は A から（§4.2）。
2. **どのエンディングをクリアに数えるか。** 推奨は、Spindle 以降の 5 値（Return / Covenant / Accede / Launch / Marooned）だけを数えることである。Brightsheol は主線の途中で退役を選ぶ終わり方で、ゲーム自身も `[lesser victory]` と札を付けている。そこで「Brightsheol で退役」として別枠で開示する（§4.5）。ハーネスは CROSS の確認に常に Cancel を返す。Brightsheol も数えるなら、この規則を外し、主張文にそう書く。
3. **Harmony（Plan C）を受け入れるか。** 受け入れると Rosetta での起動になり、manifest に x86_64 と書くことになる。
4. **Plan B（Legacy UI）になったとき、配信の見た目を受け入れるか。**
5. **知識の段。** K0、K1、K2 のどれで走るか（§4.3）。
6. **ゲームで使うモデルと予算。** Opus 5.5 を基準にするか、Sonnet 5 で安く回すか。P5 の試算では、通しで Opus 5.5 が約 $0.9k、Sonnet 5 が約 $0.5k になる。この試算は、エピソードと外部ノートの設計と、1 呼び出し 12 秒を前提にしている。M3 の実測で置き換える。
7. **キャラクター作成の I0。** 推奨は、LLM がビルドを選び、人間は打ち込むだけにする形である（§3.4）。人間が選ぶ形を許すかを決める。
8. **ゲームのビルドの固定。** 推奨は、主張用の走行を `steamapps` の外にコピーした CoQ.app から起動し、Steam の更新と切り離すことである（R0）。コピーの置き場所と、更新が出たときに主張用のビルドを上げるかどうかを決める。
9. **公開するときの「初」の言い方と、公開前の再検索の範囲**（§10.1）。
10. **配信の言語、開始日、チャットの扱い。** チャットの助言を LLM に見せれば I3 になる。R3 が失敗したときに、配信機のゲームのウィンドウを常に前面に置けるかもここで決める。主張用の走行で配信機の入力機器を外せるか（§3.3）も決める。
11. **ヘッドレスの Claude Code で回した走行を、主張に数えるか。** 推奨は数えない（§4.4）。
12. **I1 の扱い。** 推奨は、ターンを失った I1 が 1 件でもあれば、Classic でも A に落とし、失ったターン数を開示することである。死の後のロードは、チェックポイントの復帰を除いて X とする（§4.1）。偶然のクラッシュも区別しないので、S の難度は上がる。
13. **外部への固定の手段。** 推奨は、公開リポジトリへの push である（manifest は走行前に、台帳の先頭ハッシュは 30 分ごとに）。時刻証明（RFC 3161 の TSA など）を足すか、VOD をどこに保存するかを決める。

## 9. 審査員の意見が割れた点と、本書が与した側

| 争点 | 割れ方 | 与した側 | 理由 |
|---|---|---|---|
| E1（PlayerTurn に命令を実行させる） | P2 は既定の実行器にした。審査員は懐疑的 | 使わない | §1.3 の四つの理由 |
| CTA の待機中に `gameQueue` を回すか | P1、P4 は待機中に 100 ms ごとに回す。P5 は回さない | 待機中は回さない（P5）。CTA の入口で 1 回だけ、中身を記録してから回す | C01 の 2 票とも、回さない方式を安全と判定した。入口の `RenderBase` はバニラの PlayerTurn と同じ頻度でキューを回すので、違いは頻度と記録の有無である（§1.2 の 4） |
| モーダルの主経路 | P1、P2 は UI スレッド。P4、P5 は Harmony。P3 は Legacy | UI スレッド。Plan B に Legacy、Plan C に Harmony | arm64 のまま動き、終局の確認も Harmony なしで通る見込みがある（05 §3.3 の 1） |
| MCP の置き場所 | P1 はゲーム内。他は外部 | 外部 | §2 |
| マクロか 1 手か | P4 はマクロ。他は 1 手 | 1 手と AutoAct の委任から始め、マクロは計測の後 | 観測と 1 手の制御を先に固めないと、失敗の原因を切り分けられない |
| Grit Gate の端末（C11） | agent-designer は主線の障害と指摘 | 障害ではない | 襲撃は `ScriptCallToArms` のタイマーで進む |
| 終局に Harmony が要るか | engine-realist は P4 について「要る」と指摘 | 要らない見込み | `OnInputSubmit` の経路がある。R5 で確かめる |
| C05 | 反証と部分支持 | 部分支持（2 票目） | Sheva の経路も AskString を通る |
| C14 | 「コールバックはクリアされない」と「reload で空になる」 | 空になる（2 票目） | `[ModSensitiveStaticCache(true)]` |
| P1 の保守性 | 5 / 7 / 7 | 5（engine-realist） | 05 §2.2 |
| P2 の配信適性 | 6 / 8 / 6 | 6（engine-realist と operator-streamer） | フォーカス停止のため、書かれたままでは無人配信がデッドロックする |
| P3 の主張の強さ | 6 / 8 / 8 | 6（engine-realist） | 入力モデルが実装と逆向き |
| P4 のクリアへの道筋 | 7 / 5 / 6 | 5（agent-designer） | 網羅の穴と、宝箱での停止 |
| P5 の保守性 | 6 / 7 / 5 | 5（operator-streamer） | 自動更新の手順がなく、行ハッシュの照合と Harmony に依存する |

## 10. ユーザーの問いへの答え

問いは三つあった。すでにクリアされた、あるいは LLM に挑戦させた人はいるのか。いないなら、クリアまで導けたときに何を主張できるのか。今の SOTA モデルなら、クリアできて当然なのか。

### 10.1 先例は見つからなかった

LLM が Caves of Qud をクリアした記録も、LLM に挑戦させた公開の記録も、見つからなかった。調べた範囲は次のとおりである。

- 2026-09-25 に、Brave で CoQ の名前を含む語を 6 本（英語 5 本、日本語 1 本）検索した。
- P1 の 5 本の検索（P1 §8.5）と、P4 の審査員の 3 本の検索も、同じ結果だった。

検索で見つかったのは、人間の攻略、日本語化の mod、LLM でコードを書くことへの注意喚起だった。CoQ の既存の mod で最も近いのはアクセシビリティの mod と Archipelago の mod だが（02 §1.12）、どちらも LLM のプレイではない。近い事例は他のゲームにあり、RimWorld の RimMolt（モデルは GPT-6 Astra）、NetHack の GPT 6 Astra（kenforthewin の nethack_astra）、ポケモンの Claude と Gemini がそれに当たる（02 §1）。Astra はモデルの名前で、二つのゲームで別々の人が使った。

ただし、これは弱い否定である。検索エンジンは Discord を拾わないし、配信の中だけで試された挑戦は見落としうる。公開の前に、Steam の Workshop と議論、r/cavesofqud、YouTube、Twitch、GitHub、X、arXiv、公式 Discord を調べ直し、その記録を証拠に添える（§8 の 9）。

### 10.2 主張できること

主張は、条件を並べた一文にする。

> 「LLM エージェント〈モデル ID〉が、人間の書いたハーネス〈commit〉と、走行前に公開して固定したプロトコルのもとで、Caves of Qud〈ビルド〉の〈モード〉を〈Spindle 以降のエンディング名〉まで進めた。知識の段は〈K0／K1／K2〉、チェックポイントからの復帰は〈N〉回、復旧による巻き戻しは〈M〉回（失ったターン〈T〉）、人間の介入は〈I0〜I2 の一覧〉。台帳と VOD を公開する。私たちの検索の範囲では、LLM による初めてのクリアである。」

先行事例と比べて、次の三点を差として言える。

- **画像を使わない。** RimMolt で配信者が RimWorld をクリアしたとき（モデルは GPT-6 Astra）は、スクリーンショットを使い、人間が 1 回だけ指示を出し直していた（02 §1.1.2）。ポケモンの 2 例も、スクリーンショットを観測に含めていた（Gemini は RAM から取ったテキストが中心で、画像の寄与は確かめていない。02 §1.10–§1.11）。本設計の観測は、ゲーム内部のテキストと状態だけである。
- **ゲームが違う種類の難しさを持つ。** CoQ には、会話と派閥で分岐するクエストの網、確認語を打ち込む終局、多数のモーダルがある。
- **手順が事前に固定され、公開される。** GPT 6 Astra による NetHack の ascension では、ハーネスをエージェント自身が走行中に書き、コーディングエージェントのセッションが推論と文脈の管理を担った（nethack_astra の README）。本設計では、人間の書いたハーネスとプロトコルを走行の前に公開リポジトリへ push して時刻を固定し、台帳の先頭ハッシュも走行中に外へ出す（§6 の第 3 週）。

主張できないこともはっきりさせておく。

- **ハーネスなしで解いた、とは言えない。** ハーネスが観測を整え、AutoAct がターンの大半を歩く。
- **ネタバレなしで解いた、とは言えない。** 事前学習に wiki や攻略が入っている可能性を消せない。
- **再現できる、とは言えない。** 乱数と LLM の出力が決定的でない（05 §3.3 の 9）。
- **安定して解ける、とは言えない。** 1 回のクリアは割合を示さない。

### 10.3 SOTA なら当然か

当然とは言えない。ただし、ハーネスが堅く、複数回挑戦できるなら、現実に届く目標である。根拠は次のとおり。

- **近い課題でも、到達はまれである。** BALROG のリーダーボード（LLM の表）で、NetHack の進行度が最も高いのは GPT-6-Astra-Max の 13.2 ± 2.7%（2026-09-18 の提出）である。Claude-Opus-5-Max は 7.3 ± 1.6%（2026-09-20 の提出）にとどまる。これは平均の進行度で、勝率ではない（https://balrogai.com/ 。2026-09-25 に一次のページを WebFetch で確認した。02:36 の規約に従い [C] とする）。
- **初めての成功にも、補助と試行の回数が要った。** NetHack で LLM エージェントが初めて ascension したのは 2026-09-21 で、モデルは GPT 6 Astra だった。それより前に、2 回の走行が失敗している。ハーネスはエージェント自身が走行中に書き、コーディングエージェントのセッションが推論、ツールの編成、文脈の管理を担った。README は、BALROG のプロトコルによる評価でも勝率の研究でもないと断っている。そのため、上の 13.2% と並べて比べることはできない（https://github.com/kenforthewin/nethack_astra 。同日に WebFetch で確認、[C]）。3 回の挑戦にかかった日数は、一次情報で確かめられなかった。Gemini Plays Pokémon も、人間がハーネスを磨き続けたうえで Blue、Yellow Legacy、Crystal を最後まで進めたと報じられている（二次情報。02 §1.11 の出典）。
- **CoQ は長く、止まる場所が多い。** 人間でも Roleplay で約 60 時間かかるという目安がある（P1 §8.5 が引く攻略サイト。二次情報）。クエストの網、終局の確認語、モーダルの多さ、パーマデスが重なる。
- **詰みの多くは、モデルの知能よりハーネスの穴から来る。** 今回の検証では、5 案すべてがモーダルの層に「書かれたままでは止まる」穴を抱えていた（05 §2.3）。答えられないモーダルが一つあれば、どれほど賢いモデルでもそこで止まる。
- **有利な点もある。** クエストのジャーナルが行き先を文章で示す。ターン制なので考える時間の制約がない。Roleplay ならチェックポイントがある。

したがって「当然か」には、1 回のクリアでは答えられない。区間ごとの通過率を測るのが正直な答え方になる。M3 の後、Joppa、Grit Gate、Tomb の入口などの標準セーブから、同じプロトコルで各区間を 5 回以上走らせ、通過率と費用を出す。

## 11. レビュー後の修正

批評（2026-09-25）を受けて、本書と 05 を直した。骨格（CTA ターンブリッジ、Harmony なしの arm64、外部の Python ハーネス、UI スレッドからのモーダルの駆動と Plan B）は変えていない。変えたのは、主張の定義と、実行器、センサー、プローブの穴である。指摘された行番号は、逆コンパイル結果と `Base/` で読み直してから直した。

### 11.1 変えたこと

| 指摘 | 重さ | 直した箇所 | 中身 |
|---|---|---|---|
| Brightsheol を「クリア」に数えていた | 高 | §0、§4.5、§8 の 2、§10.2 | クリアは Spindle 以降の 5 値に限った。Brightsheol は「Brightsheol で退役」として別枠で開示する。ゲーム自身の札（`[lesser victory]`、`CrossIntoBrightsheol.cs:18`。`[victory]` と `[greater victory]`、`EndGame.cs:144`）を根拠に加えた。`EndGrade` も記録する |
| S 段位の I1 が巻き戻しの抜け道になる | 高 | §3.1、§4.1、§8 の 12 | 失ったターンを `XRLGame.Turns` の差で数え、差のある復旧は Classic でも A にした。Roleplay でも同じ欄で数える。セーブの SHA-256 は、書き込みの完了後に取る。`OptionSessionBackups=None` にした |
| 本物の Look の実行器がない | 中 | §1.3、§1.4、R7 | 批評の案は、イベントを直接発火する shim だった。本書は、エンジン自身の InventoryAction の Look（`Description.cs:333-376`）を採った。説明文のポップアップの本文が観測に載るので、刻印に要る文字列も手に入る。"Recall Story" は押さない |
| UI 起点のタスクと、人間のクリックがセンサーに掛からない | 中 | §1.2 の 4、§3.3 | `gameQueue` の中身を回す前に記録する。分類は委譲の型で行い、`Qud.UI.*` は I4 とする。`EndGame.Start` は許可リストに入れる。TaskID で判定すると、本物のクリアが I4 になるからである。`external_answer` と、入力機器の運用規則も加えた |
| PickGameObjectScreen 以外の `.Result` 画面 | 中 | §1.3 の許可リスト、§3.1、§3.2、R5 | Trade のボタン、Read、端末の使用、ステータスと能力の画面を、実行器が受け付けない。開いてしまったときの閉じ方は、R5 に 1 件ずつ加える |
| 世界地図と Lost | 中 | §1.3、§1.4、R10、§6 の第 3 週 | R10 を加え、観測に世界地図の座標、Lost、地点メモを入れた |
| Roleplay の死亡からの復帰が R6 にない | 中 | §3.2、R6 | 復帰とクラッシュからの再開を R6 に入れた。死亡時のメニューには、ラベルの文字列で答える |
| QudJP と Workshop の mod | 中 | R0、§4.5 の 3、manifest | `ModSettings.json` を事前に書き、`STEAM:NO` での読み込みを実測する。起動のたびに mod とハッシュを許可リストと照合する |
| ゲームのビルドを固定する手段がない | 中 | §1.1、R0、§8 の 8 | `steamapps` の外にコピーした CoQ.app から起動する |
| 費用の前提になった記憶の設計が移植されていない | 中 | §1.5、§4.4、§6 の第 3 週、§8 の 6 | P5 のエピソードと外部ノートを M2 の部品にした。`api_retry` の区分を決めた。秒数、キャッシュの読み出し率、思考の量を M3 で測る |
| 台帳を外部に固定する手段がない | 中 | §4.5 の 5、§6、§7、§8 の 13、§10.2 | manifest は走行前に、台帳の先頭ハッシュは 30 分ごとに、公開リポジトリへ push する。先頭ハッシュを VOD に焼き込み、VOD は別の場所にも保存する |
| §10.3 の出典が 02 にない | 中 | §10.1、§10.2、§10.3 | BALROG の表と nethack_astra の README を、2026-09-25 に WebFetch で確かめた（[C]）。13.2 ± 2.7% と、2026-09-21 の ascension（それより前に 2 回の失敗）は一次のページと合っていた。Claude-Opus-5-Max の 7.3 ± 1.6% を加えた。README の「BALROG のプロトコルによる評価ではない」という断りも加えた。「約 12 日」は確かめられなかったので消した |
| macOS の App Nap とスリープ | 中 | R3 | 覆った状態と非アクティブの状態で 1 時間ずつ走らせる。`caffeinate` と `NSAppSleepDisabled` を使い、OBS のフレームレートも測る |
| §1.6 の gameQueue の理由 | 低 | §1.2 の 4、§1.6、§9 | 違いは入れ子かどうかではなく頻度である、と書き直した。回した後で `Running` と `EndType` を読み直してから判断を求める |
| 能力値と技能を M1 に置いていた | 低 | §1.3、§1.5、§6 | M2 に移した。M1 の実行器は、移動、攻撃、待機、explore に限る |
| EndPlayerTurn のカウンタ 0 は壊れやすい | 低 | §3.3、§4.5 の 2 | カウンタは開示だけにした。wish のプロンプトの側で確かめる |
| （再点検で追加）死の後のロードが A に数えられる | 高 | §4.1 の規則 1 | 批評の案の「失ったターンで A に落とす」だけでは、Classic で本当に死んだ後に直前のセーブを読み直しても A になる。`death` の行を台帳に書き、その後のロードを X にした。Roleplay では、チェックポイントの復帰だけを許す |
| （再点検で追加）LLM が Brightsheol を選べてしまう | 高 | §3.2、§4.5、§8 の 2 | クリアから外しても、選択肢に `[lesser victory]` の札があり、LLM が確認語を自分で書く。CROSS を ABANDON、RETIRE と同じく常に Cancel にした |
| （再点検で追加）Free と Act の Look の混同 | 低 | §1.2 の 3、§1.3 | Free を `describe`、Act を `look` と呼び分けた |
| 拠点の数とキャラクター作成 | 低 | §4.2、§3.4、§8 の 7 | 「7 拠点（10 ゾーン）」に直した。キャラクター作成は、LLM がビルドを選び、人間は打ち込むだけにした |

### 11.2 退けたこと、直したこと

- **EndPlayerTurn のコマンド ID を読んで述語を緩める案（低）。** 案のままでは実装できない。PlayerTurn で消費されたコマンドは局所変数 `text2`（`XRLCore.cs:757`）にしかなく、EndPlayerTurn のコールバックに渡らない。Harmony なしでは読めないので、代わりに wish のプロンプト（`WishManager.cs:109`、`WishMenu.cs:146`）の側で確かめる形にした。
- **Look の実装方法（中）。** 批評は `AfterLookedAt` と `LookedAt` を直接発火する shim を勧めた。本書は、エンジン自身の InventoryAction を採った。人間が Look したときと同じ処理が走り、説明文の本文も観測に載るからである。直接の発火は、InventoryAction の経路が R7 で使えなかったときの退路として残す。
- **自動セーブの頻度（事実の訂正）。** 批評は「ゾーンを移るたびの自動セーブ」と書いたが、正しくは、ゾーンの移動を数え、5 回に達するごとに 1 回セーブする（`ZoneManager.cs:1962-1966`）。頻度は低くなるが、抜け道であることは変わらない。
- **`Popup.cs:1200` の行ずれ（事実の訂正）。** 批評は、1200 は `if` の行で `.Result` は 1202 にあるとした。読み直すと、1200 が `AskNumberAsync(...).Result` の行で、1201 が `if` だった。05 の記述は正しいので直していない。
- **`ModSettings.cs` の行。** `Enabled = true` は 17 行目ではなく 16 行目だった。本書では 16 と書いた。
- **02 への追記と、02:80 の Astra の帰属（中の一部）。** 本書の作業範囲は 05 と 06 に限られるので、02 は直していない。食い違いに見えたのは名前の誤読である。GPT 6 Astra はモデルの名前で、RimMolt の RimWorld のクリアと、kenforthewin の NetHack の ascension で、別々の人が使っていた。06 の書き方をそれに合わせた。02 に一次情報の確認結果を足す作業は残っている。
