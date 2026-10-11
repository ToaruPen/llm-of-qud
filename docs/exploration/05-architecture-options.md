# 05 アーキテクチャ案の比較 — 5 案、3 レンズの審査、14 主張の検証

> 作成: 2026-09-25（探索フェーズ）。推奨と実行計画は `06-recommendation.md` にある。本書には、そこへ至る比較と採点の根拠をまとめる。
>
> - **入力**: `proposals/P1`〜`P5` の全文。各案に対する 3 レンズ（engine-realist / agent-designer / operator-streamer）の採点と講評。5 案から統合した 14 の主張（C01〜C14）に対する 2 票ずつの敵対検証。
> - **引用**: `D/` は `~/Dev/coq-decompiled_stable`（AssemblyVersion 2.0.211.56）、`Base/` はゲームの `StreamingAssets/Base` を指す。**【本書確認】** を付けた行番号は、本書の作成時に逆コンパイル結果を読み直して確かめた。付いていない行番号は、審査と検証の記述から引いている。
> - **判定語**: 支持 / 部分支持 / 反証。いずれも静的解析による判定で、実機で確かめたという意味ではない。実機での確認は 06 §5 のプローブで行う。
> - **レビュー後の修正**: 批評を受けて、C01、C05、C11、C12 と §1.2 の 6、§3.3 の 6、§3.4 を直した。変更の一覧は 06 §11 にある。

## 0. 何が割れ、何が残ったか

5 案の違いは、見出しから受ける印象ほど大きくない。P3 を除く 4 案は、プレイヤーの `CommandTakeActionEvent`（以下 CTA。`D/XRL.Core/ActionManager.cs:789`【本書確認】）を判断の境界に選び、画面を開かずに済む操作は直接 API で行う。5 案すべてが、判断が遅れても既定の行動を打たず、英語の隔離プロファイルで QudJP を外して走らせる。通信には、P1 を除く 4 案が v1 で実証済みの ClientWebSocket（p95 1 ms）を使う。brain は、最終的には 5 案とも Python と uv で書く。

割れたのは次の点である。

| 争点 | P1 | P2 | P3 | P4 | P5 |
|---|---|---|---|---|---|
| ゲームスレッドが LLM を待つ場所 | CTA | CTA で判断し、PlayerTurn で実行（E1） | 待たない（キーを 1 つずつ注入し、PlayerTurn の `getvk` が受け取る） | CTA | CTA と、ゲームスレッド上のポップアップの入口 |
| モーダルへの答え方 | UI スレッドから `OnActivateCommand` | UI スレッドの監視（`ModalProbe.Scan`） | Legacy UI にしてキーで答える | Rosetta 上の Harmony prefix | Rosetta 上の Harmony prefix（M1 は人手） |
| MCP の置き場所 | ゲーム内の `HttpListener` | 外部（week 3 以降に薄い facade） | 外部（stdio adapter） | 外部 gateway | 外部ハーネス |
| 1 回の判断で進める量 | 1 手（AutoAct 系のツールあり） | 1 手 | 1 キー | マクロ（雑務は C# の Steward） | 1 手 |
| brain 側 | 最初はコードなし（Claude Code）、後で Python / uv | Python 3.12 / uv | Python / uv | Python 3.12 / uv と C# の Steward | Python 3.12 / uv |
| 最初の自律ターン / 完成（自己申告、週） | 1 / 3 | 0.5 / 1 | 1 / 3 | 1 / 3 | 1 / 2 |

審査の平均は、P2 が 60.33 で首位、P4 と P5 が 58.67 で並び、P1 が 56.33、P3 が 48.33 だった（90 点満点）。ところが、統合した 14 の主張のうち、2 票とも支持したものは 1 つもない。2 票とも反証したものが 2 つ（C03、C13）、票が割れたものが 1 つ（C05）、残る 11 は部分支持だった。反証と割れの 3 つは、どれもモーダルの検出か観測の完全性に関わる。どの案にも、モーダル層か CTA の出口のどちらかに、書かれたままでは止まる穴がある。

検証の結果を点数に戻すと（§2.3）、P2 60.17、P5 57.17、P4 56.67、P1 54.33、P3 45.00 になる。首位は動かない。ただし首位の P2 も、既定の実行器（E1）とフォーカス対策の置き場所に致命傷を抱えたままで、そのままでは作れない。06 は、P2 の骨格に他の 4 案の部品を移植した合成案を推す。

## 1. 各案の中身と、審査・検証で分かったこと

### 1.1 P1 — ゲーム内 MCP サーバー（"RimMolt for Qud"）

**何か。** C# の mod がゲームのプロセス内に MCP サーバーを開く。Mono の `System.Net.HttpListener` を `127.0.0.1:8787/mcp` に bind し、Streamable HTTP を POST だけ・JSON 応答だけ・ステートレスに絞って、`initialize`、`tools/list`、`tools/call`、`ping` の 4 メソッドを実装する。ゲームスレッドは CTA の中で「エージェントの手番」として止まり、Claude Code や Codex が brain のコードなしで最初のクライアントになる。行動は 45 秒で打ち切って `pending` を返し、`wait_for_turn` で続きを待つ。モーダルには Harmony を使わず、UI スレッドから `PopupMessage.OnActivateCommand` を呼んで答える。

**強み。**
- 最初の自律ターンまでが最も短い部類で（審査平均 8.33）、brain を書かずに Claude Code で遊べる。
- ツール契約がよくできている。Free / Act / Modal を分け、失敗は `ok:false` と理由で返し、黙って `PassTurn` しない。行動の後に読み直した状態を返し、再送は `expect_seq` で弾く。
- wish を「検出する」のではなく「届かない構造」で封じる。wish の入口は二つある。PlayerTurn の switch にある `CmdWish` と `CmdWishMenu`（case は `D/XRL.Core/XRLCore.cs:1883,1886`、呼び出しは `:1884,1887`【本書確認】）と、すべてのプレイヤーに付く `WishMenu` パーツが `CommandEvent` の `"CmdWishMenu"` を受けて開く wish メニューである（`D/XRL.World.Parts/WishMenu.cs:46,180-185`、`D/WishMenu_PlayerMutator.cs`【本書確認】）。P1 は、汎用のキー入力と wish をツールにせず、`use_ability` が受け付ける命令をプレイヤーに登録済みの能力に限る。これでどちらの入口にも、エージェントの経路からは届かない。
- 起動時にリフレクションで依存メンバーを確かめ、欠けたメンバーに依存するツールだけを止める SurfaceCheck は、更新への安い備えになる。
- ピッカーは Modern UI でもゲームスレッドの `getvk` ループなので（`D/XRL.UI/PickDirection.cs:54`、`D/XRL.UI/PickTarget.cs:164,791`【本書確認】）、`Keyboard.PushKey` で答えられると見抜いている。

**審査で見つかった致命傷。**
1. **非同期ポップアップの死角（3 票すべてが指摘）。** `AskString` と `AskNumber` は `NewPopupMessageAsync` を通り、ビュー名 `"DynamicPopupMessage"`（`D/XRL.UI/Popup.cs:755`【本書確認】）と `copyWindow` の複製（`:760`【本書確認】）を使う。P1 の検出規則（`CurrentGameView=="PopupMessage"` かつ `commandCallback!=null`）はこれを拾わない。水の量を聞く "How many drams?" など、ゲーム内の呼び出し元は約 26 箇所ある。主線の Mark of Death の刻印も `AskString` である（`D/XRL.World.Parts/TattooGun.cs:167`、`D/XRL.World.Parts/Engraver.cs:139`【本書確認】）。書かれたままなら、ゲートは `pending` のまま永久に止まる。直すこと自体は安い。
2. **応答済みの判定が `OnSelect` の経路で壊れる。** `OnSelect` が null にするのは `selectCallback` だけで（`D/Qud.UI/PopupMessage.cs:936-944`【本書確認】）、`commandCallback` は残る。入力欄つきの手順（`OnInputSubmit` から `OnSelect`）で答えた後も「未応答」に見え、二重に報告しうる。
3. **命令の再実装で意味がずれる。** `wait` を `PassTurn()` の 1 行で済ませているが、本物の `CmdWait` は、燃えていれば消火を試み、凍っていれば体温を上げ、それ以外では `Physics.Search()` を行い、どの場合も `PassedTurn` を発火する（`D/XRL.Core/XRLCore.cs:1517-1540`【本書確認】）。燃えている LLM が「待つ」と、消火を試みずに焼け死ぬ。
4. **AutoAct の中断で PlayerTurn に落ちる。** CTA ハンドラは `AutoAct.IsActive()` なら即 `true` を返す。ところが同じ反復の中で、敵対による中断（`D/XRL.Core/ActionManager.cs:794-797`【本書確認】）やキー入力による中断（`:810-813`【本書確認】）が AutoAct を止めることがある。そのとき `SkipPlayerTurn` が立っていないので、`:1584-1588` を素通りして `:1611` の `PlayerTurn()` に入る【本書確認】。フォーカス停止と入力クリアを避けるという設計の前提が、ここで崩れる。
5. **1 回のハンドラ呼び出しで 2 手目を打つ。** エネルギーが 2000 以上残ると、ハンドラ内のループで次の行動を打つ。その間の `CleanEffects` と `BeforeTakeActionEvent`（`:777-779`【本書確認】）、敵対による中断（`:793-797`）が飛ばされる。
6. **PlayerTurn の前処理が抜ける。** `TutorialManager.GameSync`、`CallBeginPlayerTurnCallbacks`、`Messages.BeginPlayerTurn`、`Sidebar.UpdateState`（`D/XRL.Core/XRLCore.cs:692-733`【本書確認】）が、CTA で待つ経路では呼ばれない。メッセージログの切り詰め（`D/XRL.Messages/MessageQueue.cs:94-104`【本書確認】）は `BeginPlayerTurn` の中にしかない。その呼び出し元は `XRLCore.cs:710` と、世界地図の移動を終えたとき（`D/XRL.World.Parts/TerrainTravel.cs:270-273`【本書確認】）の 2 か所だけなので、CTA で待つ経路では世界地図に出ないかぎりログが伸び続ける。
7. **長期走行の brain がない。** 数千〜1 万数千の判断を、Claude Code の汎用の文脈圧縮と、LLM が自分で書く `notes.md` だけで支える。進捗の監視、ループの検出、危機時のモデルの切り替えは、「後で作る brain」に先送りされている（agent-designer）。
8. **終盤の、ポップアップでない UI が未調査。** Book、CyberneticsTerminal、Cinematic は「3 週目に数える、暫定で Cancel」のままである。
9. **条件付き。** `OnActivateCommand` による応答が実機で失敗すると、会話、YesNo、PickOption、レベルアップの経路がまとめて失われ、退路は Harmony になる。案の中心にある「Harmony なし・arm64 ネイティブ」が崩れる。

**依存する主張の検証。**
- C02（UI スレッドから答えられる）: 部分支持。駆動はできるが、`copyWindow` の複製も探すこと、`text` が null でない実物の項目を渡すことが条件になる。
- C03（誤検出ゼロの検出）: **反証**。P1 の述語は非同期ポップアップを見逃し、`OnSelect` の後に二重報告しうる。
- C14（ゲーム内ブリッジの長期安定）: 部分支持。`Managed/System.dll` に `HttpListener` の型があることまでしか言えず、`127.0.0.1` への bind、keep-alive、並行 long-poll、数時間の安定は未検証である。加えて、XRLCore のコールバックリストは hotload のたびに空になり（`D/XRL.Core/XRLCore.cs:252-273` の `[ModSensitiveStaticCache(true)]`【本書確認】）、mod の構成を変えるとプロセスが再起動して、新しいプロセスが古いプロセスより先にポートを取りにいく。ゲーム内のサーバーほど、この二つの影響を強く受ける。
- C12（クリアの述語）: 部分支持。P1 の「構造で封じる」方針は、wish を postfix で検出する方針より強い。一覧から漏れていた `gocreditscoda`（`D/XRL.World.Conversations.Parts/EndGame.cs:276`【本書確認】）も、構造で封じる論証の範囲に入るので実害はない。
- C01、C06、C07、C08: 部分支持（§3）。

**評価。** Claude Code を最初のクライアントにする発想、ツール契約、wish の構造的な封鎖は採る。ゲーム内の HTTP サーバーは採らない。

### 1.2 P2 — Lean Turn Bridge（CTA で判断し、PlayerTurn で実行する）

**何か。** v1 が実証した部品を残し、LLM を足し、工程を引く案である。残す部品は、CTA 同期の判断境界、ClientWebSocket、AfterRender と BackupChar によるグリフの取得、`SkipPlayerTurn` による起床の 4 つ。v1 の 500 ms で発動する代行と、工程の重さは捨てる。ゲームスレッドは CTA ハンドラの中で Python の brain の判断を待つ。行動は、既定では E1 で実行する。E1 は、EndPlayerTurn のコールバックから `Keyboard.PushCommand` で命令 ID を押し込み、PlayerTurn 自身の switch に実行させる方式である。所持品、装備、能力値の購入は E2（CTA 内でゲーム関数を直接呼ぶ）で行い、M1 の退路として E0（CTA 内で `Move` を直接呼ぶ）を持つ。モーダルは、ブリッジが RUNNING の間 150 ms ごとに `uiQueue.queueSingletonTask(ModalProbe.Scan)` を積み、UI スレッドで見つけて `OnActivateCommand` で答える。brain は Python 3.12 と uv で、ツールループ、記憶、費用の段階、証拠の台帳、オーバーレイを持つ。

**強み。**
- 審査平均が最も高い（60.33）。部品のほとんどに v1 で動いた実績があり、工程が最も軽い。
- 主張の段位（S = Classic、A = Roleplay でチェックポイントからの復帰回数を開示、B = 人間の関与を列挙）と、LLM が選ばなかった入力をすべて台帳に載せる方針（H1〜H7 の区分）を持つ。
- 行動文法の表が、実行器への写像と引用つきで書かれている。
- CTA の入口で `RenderBase` を 1 回呼ぶこと、結果を次の CTA の入口で確定すること、呼んではいけない API の一覧など、細部の判断が的確である。

**審査で見つかった致命傷。**
1. **フォーカス対策の置き場所が逆（2 票が致命と判定）。** P2 は、`GameManager.focused` と `XRLCore.bThreadFocus` の強制を EndPlayerTurn のコールバック（`D/XRL.Core/XRLCore.cs:2358`【本書確認】）に置いている。ところが PlayerTurn のフォーカス待ち `while (!GameManager.focused && Game.Running) Thread.Sleep(200)` は、同じ反復の先頭にある（`:737-740`【本書確認】）。判断中にウィンドウのフォーカスが外れると、PlayerTurn の最初の反復でスレッドが止まり、コールバックも起床も走らない。無人の配信では確実にデッドロックする。
2. **PickItem がモーダルの表にない。** `PickItem.ShowPicker` は、Modern UI では `PickGameObjectScreen.show(...).Result` でゲームスレッドを止める（`D/XRL.UI/PickItem.cs:285,307,319`【本書確認】）。呼び出し元は、複数の物を拾う操作（`D/XRL.World.Parts/Inventory.cs:1361`【本書確認】）、容器を開く操作（`D/XRL.World.Parts/Container.cs:153`【本書確認】）、液体を汲む操作（`D/XRL.World.Parts/LiquidVolume.cs:3363,6565`【本書確認】）である。自動探索も既定で容器を開ける（`Base/Options.xml:123` の `OptionAutoexploreChests` は既定で Yes、`ActionManager.cs:1061` で `FireEvent("Open")`【本書確認】）。どれも「未知のビュー → Cancel → 人手」に落ちる。
3. **遠隔攻撃と、対象を取る能力が week 3 に先送り。** 中盤以降の戦闘手段が欠けたままになる。
4. **Grit Gate の端末が主線の障害になる（agent-designer の指摘）。** これは本書の確認で**否定された**。端末は、Modern UI では `CyberneticsTerminalScreen.ShowGenericTerminal(this).Result` で開く（`D/XRL.UI/GenericTerminal.cs:81-84`【本書確認】）。しかし主線の進行は端末を必要としない。「A Call to Arms」は `EndTurnEvent` のたびに数を進め、250 ターンで襲撃隊を出し、襲撃隊がいなくなると `FinishQuestStep("A Call to Arms", "Defend Grit Gate")` と `ForceFinishQuest("Grave Thoughts")` を呼ぶ（`D/XRL.World.ZoneParts/ScriptCallToArms.cs:54,70-86`【本書確認】）。端末は任意である。
5. **条件付き。** UI スレッドからの応答と、フォーカスの強制は、どちらも実測前のまま、会話と E1 の両方を支えている。どちらかが崩れると、「Harmony なし・arm64 ネイティブ・Modern UI」という中核が成り立たない。
6. **世界地図の観測と移動が薄い。** 地名や地図ノートの座標が観測になく、世界地図用の移動も未検証である。本書の確認で、世界地図の移動には Lost の仕組みがあると分かった。移動すると Lost になりうる（`D/XRL.World.Parts/TerrainTravel.cs:201-206`、`D/XRL.World.Parts/TerrainTravelFungal.cs:55`【本書確認】）。Lost の間は世界地図に出られない（`D/XRL.World.Effects/Lost.cs:178-182` の "You are lost!"【本書確認】）。Lost は、既訪のゾーンに入る、新しいゾーンに入る（20%、Survival があれば 40%）、会話で道を聞く、のどれかで解ける（`Lost.cs:150-172`、`D/XRL.UI/ConversationUI.cs:452-461`【本書確認】）。自動探索は世界地図では効かない（`XRLCore.cs:1920-1926`）。どの案もこれを確かめていない。06 は R10 で確かめる。
7. **人間のキーが LLM の行動より先に走る。** `ClearMouseEvents`（`:734`）はキーのキューを消さない。ブロック中に押されたキーは、次の PlayerTurn の最初の反復で取り出され、E1 が押し込んだ命令より先に実行される。台帳はこれを検出できても防げず、S 段位の走行が偶然の入力で汚れる。

**依存する主張の検証。**
- C09（E1 の命令は確実に実行される）: 部分支持だが、成り立つ条件は狭い。押し込んだ命令が生き残るのは、同じ PlayerTurn の次の反復で取り出される場合に限られる。ビューが切り替わると UI スレッドが `ControlManager.ResetInput` を呼んでキューを消す（`D/GameManager.cs:3178-3182`、`D/ControlManager.cs:1491-1494`【本書確認】）。フォーカスの false から true への遷移も入力を消す（`D/GameManager.cs:412-417`【本書確認】）。PlayerTurn を一度抜けると、移動以外の命令は次の PlayerTurn の冒頭（`:734`）で消える。explore の `return` や、隣接していない `CmdMoveToBorder` の `break` は、コールバックを通らずに PlayerTurn を抜ける。
- C11（主線は行動文法とモーダル経路で足りる）: 部分支持。端末は任意だが、自由文字入力、色の選択、`ThinWorld` の生の `Keyboard.getch` ×8（`D/XRL.World.Parts/ThinWorld.cs:275-278`【本書確認】）、本物の Look が要る。
- C05（モーダルは少数の合流点を通る）: 票が割れた。P2 の表は PickItem などの専用画面を落としている。
- C13（観測の完全性）: **反証**。P2 の観測は有用だが、「人間に見える面だけで完全」とは言えない。
- C01、C02、C06、C08: 部分支持。

**評価。** 骨格としては最良である。ただし、致命傷のほとんどは、既定の実行器 E1 とフォーカス対策の置き場所から出ている。E1 を既定から外し、CTA 内での実行を既定にすれば、骨格の長所だけが残る。

### 1.3 P3 — Player Parity, Text Only（Legacy 画面とキーだけ）

**何か。** `OptionModernUI=No` と `OptionUseTiles=No` を設定し、ゲーム画面、ポップアップ、会話、取引、ステータス画面、Pick*、Look、レベルアップを、すべて `TextConsole.CurrentBuffer` への描画と `Keyboard.getvk` の入力待ちという一つの型に畳む案である。mod の仕事は、画面を取ること、キーを入れること、画面が落ち着いたかを判定することの三つに限られる。ゲームスレッドは LLM を待たず、人間を待つときと同じ `GetNextKey` で待つ。LLM は 80×25 の文字画面を読み、キーを 1 つずつ押す。観測は L0（文字画面）、L1（決定的な注釈つき）、L2（キーだけで組んだマクロつき）の 3 段で公開し、`verify_parity.py` が LLM に渡したプロンプトを記録済みのフレームからバイト単位で再生成して照合する。MCP は外部の stdio アダプタに置く。

**強み。**
- プラットフォームの面では最も誠実である。Harmony も Rosetta も使わず、ゲームスレッドは人間と同じ場所で待つ。そのため v1 の CTA ブロック、デッドロック（K21）、「タイムアウトしたら東へ歩く」問題が、構造ごと消える。
- 「人間と同じ画面、同じ入力」という主張を、第三者がログだけで検証できる。`verify_parity.py` と、LLM の経路から物理的に分けた監査チャネルがそれを支える。
- Legacy UI は、全モーダルを一つの型に畳む退路として、どの案でも使える（C10 は部分支持）。
- 入力を黙って消す 5 つの仕組みの表と、「落ち着いたフレーム 1 つにつき入力は 1 つ」という規則がある。5 つとは、Popup の ClearInput、PlayerTurn の ClearMouseEvents、AutoAct の kbhit による中断、focused の setter の ClearInput、ビュー切り替え時の ResetInput である。
- `CurrentGameView` と `ViewTag` の監視で Modern UI の漏れを検出し、`interventions.jsonl` に記録する。

**審査で見つかった致命傷。**
1. **入力経路のモデルが実装と逆向き（engine-realist）。** 2.0.211.56 では、人間が束縛キーを押すと ControlManager を経て `Keyboard.PushCommand` が積まれる。生の `PushKey(bAllowMap:true)` に流れるのは、束縛されていないキーと、Legacy で `OptionPushAZHotkeys` が有効なときの A〜Z だけである（`D/GameManager.cs:1898-1912`【本書確認】）。P3 は `PushCommand` を「人間と違う経路」として禁じ、束縛コマンドを `PushKey` で送る。これでは入力の等価性を確かめる監査が、誤ったモデルを合格させてしまう。直すこと自体は小さい。
2. **`press(cmd)` が何もしない恐れ（operator-streamer）。** `press` はキーを `CommandBindingManager.GetKeyFromCommand` で引くが、これが読むのは旧式の int キーマップである（`D/XRL.UI/CommandBindingManager.cs:954-975`【本書確認】）。審査員の調べでは、オーナーの `Keymap2.json` の既定レイヤーは 0 件で、新しい `-savepath` プロファイルも空のキーマップから始まる。そうだとすると、Stage 画面での行動はすべて空振りになる。空であることは実機で確かめる必要がある。
3. **取引が動かない。** Legacy の ConsoleTrade は、`Command:CmdTrade*` と `Command:CmdVendor*` のイベントしか受け付けない（`TradeUI.cs:780-1092`）。会話から取引を開くのも `Command:CmdStartTrade` だけである（`ConversationUI.cs:289-291`）。`PushKey` だけでは、水の経済も修理も鑑定もできない。
4. **方向キーの再マップを通らない。** 人間の入力は `PushKey(..., bAllowMap:true)` を通る（`GameManager.cs:1912`）。P3 の `PushKey(new XRLKeyEvent(...))` は既定の `allowmap=false` なので、`Keyboard.cs:1218` の再マップを通らない。
5. **落ち着き判定の偽陽性（条件付き）。** 判定の一つ `WaitSleepJoin` は、`WaitOne(20)`、フォーカス待ちの `Sleep(200)`、AutoAct のペース調整のどれでも真になる。偽陽性はキーの消失や AutoAct の誤った中断に直結する。正確にするには `GetNextKey` への Harmony prefix が要り、そうなると arm64 ネイティブという前提が崩れる。
6. **観測が貧しい。** 実体に名前がなく、正体は毎回 Look で調べる。CP437 のグリフをどう写すかも決まっていない。サイドバーを隠すとゾーン名、空腹、能力値が見えない。1 フレームが 1.5k〜3k トークンで、行動のたびにキーと落ち着き判定を往復する。審査員の推定では、LLM の呼び出しは数万から 10 万回に達する。
7. **キャラクター作成は Legacy でも UGUI。** `EmbarkBuilder.cs:61-87` のため、新しいキャラクターのたびにオペレーターの入力が要る。Classic のパーマデス走行は無人で再挑戦できない。

**依存する主張の検証。**
- C03（誤検出ゼロの検出）: **反証**。Legacy の 4 条件は経験則にすぎず、フォーカス喪失時の停止（`XRLCore.cs:737-740`）や、終局演出の長い `Thread.Sleep`（`EndGame.cs:288`【本書確認】）で偽陽性を出す。
- C10（Legacy なら全部が CurrentBuffer と getvk に乗る）: 部分支持。`OptionUseTiles` は経路に関係しない。例外は、ロード時の mod 構成不一致の確認（`XRLCore.cs:3428,3448`）、カスタム代名詞の作成、Legacy のキー再割り当て画面で、どれも運用で避けられる。終局のクレジットとコーダは Unity の canvas 演出で、文字画面には載らない（入力は要らない）。
- C13: **反証**。C06、C07、C14: 部分支持。

**評価。** 主張の強さと引き換えに、クリアへの到達確率を大きく削った案である。しかも背骨の入力モデルが実装と逆向きになっている。一方で、Legacy UI を「モーダルを一つの型に畳む退路」として使う発想と、`verify_parity` の考え方は、どの案にも持ち込める。06 は Legacy UI を Plan B として採る。

### 1.4 P4 — World Model + Macro（指揮者 LLM と決定的な執事 Steward）

**何か。** LLM は「指揮者」として状況報告（sitrep）を読み、マクロを 1 つ選ぶ。マクロの中身は、エンジンの AutoAct、経路探索、休息と直接 API で実行する。C# のガードが 1 歩ごとに HP_CRITICAL、NEW_HOSTILE（エンジンが見逃す `M`/`P`/`U`/`!` の自動移動を含む）、ENGINE_STOP、STUCK、BUDGET を確かめ、引っかかったらマクロを止めて LLM を起こす。起床は事象の重要度（P0〜P3）と予算で制御する。飲食や休息のような雑務は、C# の規則表 Steward が決定的に片づける。ゲームスレッドは CTA の「サービスループ」で待ち、100 ms ごとに `gameQueue.executeTasks()` を回す。モーダルは、Rosetta 上の Harmony prefix で、Popup の同期 API（意味の層）と `WaitNewPopupMessage`（網羅の層）を押さえる。見積もりは、1 回の起床が約 8k トークン（うち約 4k がキャッシュ）、起床が 1,000〜3,000 回である。

**強み。**
- 長期戦のコストと注意の配分に、最もまともに答えている（コストの審査平均 8.00、観測 7.67）。sitrep は `e3`、`p2`、`i7` のような ID で対象を指し、digest を 12 行以内に畳む。
- マクロの表に「人間も同じ自動化を持つか」の列があり、そのまま主張の範囲の議論に使える。
- エンジンの敵対中断（`ActionManager.cs:794`【本書確認】）が `M`/`P`/`U`/`!` を対象外にしていることを見抜き、CTA ガードで補っている。
- 引用の密度と自己照合は、5 案の中で抜きん出ている（engine-realist）。

**審査で見つかった致命傷。**
1. **網羅の層が一つの合流点にしか掛かっていない（3 票すべて）。** `Popup.WaitNewPopupMessage` を押さえても、Modern の AskString、AskNumber、ShowAsync、ShowYesNoAsync と、`NewPopupMessageAsync(...).Result` の直接呼び出し（`Description.cs:361` など）は通らない。Popup ですらない同期画面、すなわち PickItem から `PickGameObjectScreen.show().Result`（`PickItem.cs:285,307,319`【本書確認】）、BookUI（`BookUI.cs:429,466`）、`GenericTerminal.cs:83`【本書確認】、`CyberneticsTerminal.cs:201`、`TradeUI.ShowTradeScreen` も、どの prefix にも掛からない。提案書はこれらを「開かない」と分類しているが、自動探索の既定動作が開く。
2. **自動探索が宝箱で凍る。** `OptionAutoexploreChests` は既定で有効で（`Base/Options.xml:123`【本書確認】）、素の `explore` が `FireEvent("Open")`（`ActionManager.cs:1061`【本書確認】）から `PickItem.ShowPicker`（`Container.cs:153`【本書確認】）へ進む。ゲームスレッドはサービスループの外の `.Result` で止まり、事象もタイムアウトも出ない。無人走行は静かに凍り、M2 の指標「未知モーダルの回数」も測れない。
3. **ウォッチドッグがない。** ブリッジスレッドに、`CurrentGameView` と心拍を見る仕組みがない。
4. **終局の確定には Harmony が要る（engine-realist、条件付き）。** これは本書の確認で**否定された**。終局の確認は、`WantsSpecificPrompt` つきの AskString と「長押しで確定」のボタンでできている。ところが Harmony なしでも、UI スレッドで `inputBox.text` を設定して `OnInputSubmit` を呼べば確定できる。これはエンジン自身の長押し処理が 2 秒後に行うことと同じである（`D/Qud.UI/PopupMessage.cs:1007-1031`【本書確認】）。`OnInputSubmit` は、下段の選択肢のうち hotkey が Submit、Accept、CmdOptions の最初のものに `OnSelect` を呼ぶ。PC ではそれが command `"keep"` の Submit ボタンになる（`:599-606`、`:946-958`【本書確認】）。`NewPopupMessageAsync` は、入力欄があれば `inputBox.text` を結果に写す（`D/XRL.UI/Popup.cs:782-784`【本書確認】）。実機での確認は 06 の R5 で行う。
5. **キャラクター作成が未設計。** キャラクター作成は UI スレッドの `Popup.*Async` で動く（`QudCustomizeCharacterModuleWindow.cs:123,162`）。UI スレッドを素通しする prefix の方針では駆動できず、`EmbarkBuilder` の差し替えは M3 以降に先送りされている。
6. **A3（条件付き）。** 同期モデル全体が、「CTA の中で 60 秒以上ブロックしつつ、`gameQueue.executeTasks` を入れ子で回しても安全」という前提に立つ。v1 が実証したのは 500 ms までである。入れ子の中では `EndGame.Start`（11 秒の Sleep、クレジット、プレイヤーの体の差し替え）まで走りうる。
7. **A1（条件付き）。** モーダルの主経路が、Roslyn でコンパイルした mod から Rosetta 上の Harmony 2.2.2 が効くことに依存している。QudJP の実測は `LoadFrom` 経由で、ModInfo の Roslyn 経由ではない。
8. **Classic に弱い。** `fight` マクロは近接攻撃と経路探索だけで、LLM は HP の閾値でしか起こされない。ガス、液体、遠隔の集中砲火、伝説個体のような瞬間的な大ダメージには、1 歩ごとのガードでは間に合わないことが多い。提案自身も Roleplay を推している。

**依存する主張の検証。**
- C01（CTA 内の長時間ブロック）: 部分支持。デッドロックは静的には起きない。ただし、回したキューのタスクは個別に捨てられず（`ThreadTaskQueue` には `clear()` しかない）、入れ子で最後まで走る。`The.Game` は終局をまたいでも同じオブジェクトなので、P4 の「game と player の同一性検査」は終局を検出できない。一方、キューを回さない P5 の方式も安全と判定された。本書は回さない側に与する（§3.2）。
- C04（Rosetta 上の Harmony）: 部分支持。Roslyn の経路は未実測である。
- C05（モーダルは少数の合流点を通る）: 票が割れた。P4 の一覧は PickItem などを落としている。
- C07（AutoAct の委任）: 部分支持。1 判断あたりのターン数に下限はない。視界に敵がいれば 0 歩で止まり、`.N` は N−1 ターンになる。
- C08、C12: 部分支持。

**評価。** 長期戦の頭脳としては最良で、sitrep の順序、ガード、起床の優先度と予算は移植する。モーダル層とキューを回す同期モデルは採らない。Steward とマクロの大半は、観測と 1 手の制御が固まった M2 以降に回す。

### 1.5 P5 — Evidence-First（台帳つきターンブリッジ）

**何か。** 判断点を CTA とポップアップの入口の 2 か所に絞り、ハッシュ鎖の台帳を最初のコミットに入れる案である。行動は、PlayerTurn の switch にある 1〜3 行の case 本体を CTA 内で同じように呼ぶ「case 本体の shim」で実行し、どの shim にも写し元の行を記す。モーダルは、第 2 週から Rosetta 上の Harmony prefix でゲームスレッド側の合流点（`WaitNewPopupMessage` と `NewPopupMessageAsync`）を押さえる。M1 では人間が答え、介入として数える。行動の引数から作った答えは、その行動が出すと分かっているプロンプトにだけ使う（staged answers）。AskString と AskNumber には決して自動で答えない。2 秒ごとの心拍でウォッチドッグを回し、CTA の入口ではキューに溜まったキーを数えてから捨て（`stray_input`）、エネルギーの減少を直前の行動と突き合わせる。介入は I0〜I4 と X に分類し、主張用の protocol 走行と、開発用の interactive 走行を分ける。

**強み。**
- 主張の強さで 3 票とも 9 点をつけた。証拠と帰属の設計が最も厚い。
- タイムアウトしても代わりの行動を打たない。protocol と interactive を分け、台帳を初日から持つ。
- case 本体の shim、staged answers、`stray_input`、エネルギーの突き合わせは、入力の手段に依存しない帰属の仕組みで、どの骨格にも移植できる。
- 自分の最大のリスク（R1〜R3）を、実測が要るものとして隠さず書いている。
- 知識の開示方針とコストモデルがある。中心の試算は、ゲームターン G=120k、1 判断あたり r=8 ターン、1 判断あたり c=1.5 呼び出しで、約 2.25 万回の呼び出しになる。1 呼び出しの単価は Opus 5 で約 $0.056、Opus 5.5 で約 $0.041、Sonnet 5 で約 $0.022 と見積もられ、総額はそれぞれ約 $1.3k、$0.9k、$0.5k、1 呼び出し 12 秒なら約 75 時間になる。

**審査で見つかった致命傷。**
1. **AutoAct 中の早期 return（engine-realist、修正は 1 行）。** CTA ハンドラは `AutoAct.IsActive()` なら何も決めずに戻る。ところが、敵対による中断（`ActionManager.cs:794-797`）とキーや端による中断（`:810-830`【本書確認】）は CTA の後に走る。中断されると `:1584-1588` を素通りして `:1611` の `PlayerTurn()` に入り、人間のキー待ちとフォーカス停止に落ちる。「起床は不要」という P5 の主張もこの場合は成り立たない。早期 return のたびに `SkipPlayerTurn=true` を立てれば直る。
2. **R2 の網羅性の過大評価（3 票すべて）。** Modern UI の PickItem（`PickItem.cs:285,307,319`【本書確認】）は、2 つの Popup 合流点のどちらも通らない。宝箱（`Container.cs:153`）、複数の物を拾う操作（`Inventory.cs:1361`）、水の容器を満たす操作（`LiquidVolume.cs:3363,6565`）から到達する。P5 はこれを PickOption、つまり合流点 1 に誤って分類している。書かれたままでは、拾う、漁る、水を扱うたびに `unhandled_modal`（I4）が立ち、主張用の走行は assisted に落ちる。
3. **R1（条件付き）。** Rosetta 上の Harmony 2.2.2 が、async void の `WaitNewPopupMessage` と `Task` を返す `NewPopupMessageAsync` に prefix を当てられなければ、会話、YesNo、AskString（終局の確認そのもの）に自動で答えられない。代替の Legacy UI と PushKey は、名前が挙がっているだけで設計されていない。
4. **Steam の自動更新（条件付き）。** 75〜330 時間の Classic 走行の途中で Steam が自動更新すると、P5 自身の buildid と AssemblyVersion のゲートが主張用の起動を拒む。証拠のセーブも同じビルドと mod を要求する。自動更新を止める手順がない。
5. **行動ツールを呼ばない応答の扱いが未定義。** LLM がテキストだけで応答を終えたときの再プロンプト経路がない（`tool_choice` の強制は 400 になると提案自身が書いている）。判断点で無期限に止まるか、費用のループになる。
6. **R3（条件付き）。** CTA 内で `gameQueue` を回さずに数十秒から数分止めても Modern UI が健全でいられるかは、v1 では 500 ms までしか確かめていない。静的な根拠は成り立つ。

**依存する主張の検証。**
- C01: 部分支持。2 票とも「回さない方式は安全」と判定した。エンジン自身も `Popup.cs:908`【本書確認】の `Task.Wait` などで、キューを回さずにゲームスレッドを無期限に止めている。この点では P5 が正しい。
- C12（クリアの述語）: 部分支持。P5 の述語は `UnlockAchievement` への Harmony prefix に依存している。さらに、CAVES_OF_QUD 実績は解除済みなら何もしないので証拠にならない。Classic の Brightsheol ではセーブが消えるので、EndType はその瞬間に捕まえる必要がある。`HandleWish` への postfix は、C# からの `[WishCommand]` メソッドの直接呼び出しを捕まえられない。
- C05: 票が割れた。P5 は PickItem を落としている。C13: **反証**。C04、C06、C07、C08: 部分支持。

**評価。** 証拠の設計はほぼそのまま採る。台帳と `verify.py`、I0〜I4 と X、protocol と interactive の区別、`stray_input`、エネルギーの突き合わせ、ウォッチドッグ、staged answers、case 本体の shim がそれに当たる。Harmony を主経路にするモーダル層は採らない。クリアの述語は、Harmony なしで判定できる形に書き直す（06 §4）。

## 2. 採点

### 2.1 審査員の採点（平均と 3 票）

票は engine-realist / agent-designer / operator-streamer の順に並べる。各基準は 10 点満点、合計は 90 点満点である。

| 基準 | P1 | P2 | P3 | P4 | P5 |
|---|---|---|---|---|---|
| feasibility_on_this_machine | 6.67 (7/6/7) | 7.00 (7/7/7) | 6.67 (7/7/6) | 6.33 (7/6/6) | 7.00 (7/7/7) |
| nonvisual_observation_completeness | 7.00 (7/7/7) | 7.00 (7/7/7) | 5.67 (6/5/6) | 7.67 (8/8/7) | 7.00 (8/6/7) |
| control_coverage_and_robustness | 4.67 (4/5/5) | 5.67 (5/6/6) | 4.67 (4/6/4) | 5.00 (5/5/5) | 5.33 (5/6/5) |
| time_to_first_autonomous_turn | 8.33 (8/9/8) | 8.33 (8/9/8) | 7.00 (8/7/6) | 7.67 (8/8/7) | 7.67 (7/8/8) |
| path_to_clearing_the_game | 4.33 (4/4/5) | 5.00 (5/5/5) | 3.00 (3/3/3) | 6.00 (7/5/6) | 5.00 (5/5/5) |
| streaming_fitness | 6.67 (7/6/7) | 6.67 (6/8/6) | 5.00 (5/5/5) | 6.67 (7/7/6) | 6.00 (6/6/6) |
| research_claim_strength | 7.33 (7/8/7) | 7.67 (8/8/7) | 7.33 (6/8/8) | 6.33 (6/6/7) | 9.00 (9/9/9) |
| maintainability_across_updates | 6.33 (5/7/7) | 7.00 (7/7/7) | 6.00 (6/6/6) | 5.00 (6/5/4) | 6.00 (6/7/5) |
| cost_and_latency | 5.00 (5/4/6) | 6.00 (7/6/5) | 3.00 (3/3/3) | 8.00 (8/8/8) | 5.67 (5/6/6) |
| **合計** | **56.33** (54/56/59) | **60.33** (60/63/58) | **48.33** (48/50/47) | **58.67** (62/58/56) | **58.67** (58/60/58) |

### 2.2 検証を受けて点を動かす規則と、動かした箇所

点を動かす規則は三つに限った。

1. 3 票の差が 2 点以上ある基準では、根拠が検証を生き残った側の票に合わせる。検証がその根拠に触れていなければ、平均のまま残す。
2. 点の前提になっていた主張が検証で崩れたら、下げる。
3. 点を下げていた致命傷が検証で否定されたら、上げる。

差が 2 点以上あっても、検証が根拠に触れなかったので平均のまま残した基準は、次の 5 つである。P1 cost（5/4/6）、P2 cost（7/6/5）、P3 time（8/7/6）、P4 maint（6/5/4）、P5 obs（8/6/7）。動かしたのは次の 12 箇所である。

| 案 | 基準 | 票 | 平均 → 調整後 | 規則 | 与した票と理由 |
|---|---|---|---|---|---|
| P1 | feasibility | 7/6/7 | 6.67 → 6.00 | 2 | 実現性の前提だった検出述語が C03 で反証された。ゲーム内の `HttpListener` も未実測のままである（C14）。 |
| P1 | maintainability | 5/7/7 | 6.33 → 5.00 | 1 | engine-realist に与する。7 点の 2 票は SurfaceCheck を更新への備えとして評価したが、SurfaceCheck が確かめるのはメンバーの有無で、振る舞いではない。一方、コールバックリストが hotload で空になること（`XRLCore.cs:252-273`【本書確認】）と、再起動時にポートを奪い合うこと（C14）は、ゲーム内サーバーにいちばん強く効く。 |
| P2 | path | 5/5/5 | 5.00 → 5.50 | 3 | Grit Gate の端末が主線の障害だという指摘は否定された（`ScriptCallToArms.cs:54,70-86`【本書確認】）。PickItem と遠隔戦闘の穴が残るので、上げ幅は 0.5 に留める。 |
| P2 | streaming | 6/8/6 | 6.67 → 6.00 | 1 | engine-realist と operator-streamer に与する。書かれたままでは、フォーカス停止（`XRLCore.cs:737-740`【本書確認】）のため無人配信がデッドロックする。8 点はこれを勘定していない。 |
| P3 | feasibility | 7/7/6 | 6.67 → 6.00 | 2 | 入力モデルが実装と逆向きであること（`GameManager.cs:1898-1912`【本書確認】）が確認された。`press` が何もしない恐れも残る。 |
| P3 | observation | 6/5/6 | 5.67 → 5.00 | 2 | C13 の反証が P3 の中核に当たる。L1 の注釈とメッセージは、L0 と履歴から後で再計算できない。 |
| P3 | control | 4/6/4 | 4.67 → 4.00 | 1 | engine-realist と operator-streamer に与する。取引には Command イベントが要り、`allowmap` の再マップも通らず、落ち着き判定は偽陽性を出す（C03 反証）。 |
| P3 | claim | 6/8/8 | 7.33 → 6.00 | 1 | engine-realist に与する。「人間と同じ入力」という主張は書かれたままでは偽であり、パリティ監査は誤ったモデルを合格させる。支えの C13 も反証された。 |
| P4 | path | 7/5/6 | 6.00 → 5.00 | 1 | agent-designer に与する。7 点はモーダル層が主線を覆う前提に立っていたが、3 票すべてが合流点 1 つだけの網羅と宝箱での停止を見つけた。「終局に Harmony が要る」の否定は条件付きの穴を 1 つ消すだけで、網羅を回復しない。 |
| P4 | cost | 8/8/8 | 8.00 → 7.00 | 2 | 起床 1,000〜3,000 回という見積もりは、1 判断あたりのターン数に下限があることを前提にしている。C07 はその下限がないことを示した。それでも 5 案の中では最良である。 |
| P5 | maintainability | 6/7/5 | 6.00 → 5.00 | 1 | operator-streamer に与する。Steam の自動更新を止める手順がなく、shim 表と行ハッシュの CI 照合は行番号の契約になり、モーダルの主経路は Rosetta 上の Harmony に依存する。 |
| P5 | claim | 9/9/9 | 9.00 → 8.50 | 2 | 述語が Harmony（`UnlockAchievement` の prefix と `HandleWish` の postfix）に依存し、CAVES_OF_QUD 実績は解除済みなら何もしない。C# からの `[WishCommand]` の直接呼び出しも捕まえられない（C12）。それでも 5 案の中では最高である。 |

### 2.3 調整後の行列

↓ と ↑ は §2.2 で動かした箇所を示す。

| 基準 | P1 | P2 | P3 | P4 | P5 |
|---|---|---|---|---|---|
| feasibility_on_this_machine | 6.00 ↓ | 7.00 | 6.00 ↓ | 6.33 | 7.00 |
| nonvisual_observation_completeness | 7.00 | 7.00 | 5.00 ↓ | 7.67 | 7.00 |
| control_coverage_and_robustness | 4.67 | 5.67 | 4.00 ↓ | 5.00 | 5.33 |
| time_to_first_autonomous_turn | 8.33 | 8.33 | 7.00 | 7.67 | 7.67 |
| path_to_clearing_the_game | 4.33 | 5.50 ↑ | 3.00 | 5.00 ↓ | 5.00 |
| streaming_fitness | 6.67 | 6.00 ↓ | 5.00 | 6.67 | 6.00 |
| research_claim_strength | 7.33 | 7.67 | 6.00 ↓ | 6.33 | 8.50 ↓ |
| maintainability_across_updates | 5.00 ↓ | 7.00 | 6.00 | 5.00 | 5.00 ↓ |
| cost_and_latency | 5.00 | 6.00 | 3.00 | 7.00 ↓ | 5.67 |
| **合計** | **54.33**（−2.00） | **60.17**（−0.17） | **45.00**（−3.33） | **56.67**（−2.00） | **57.17**（−1.50） |

順位は P2、P5、P4、P1、P3 になった。P5 と P4 の差は 0.5 点しかない。審査員 1 人が 1 基準で 1 点動かすと平均は 0.33 点動くので、2 人が 1 点ずつ動かせば入れ替わる。この 2 案は実質的に並んでいる。

点数より意味があるのは、致命傷がどの層に集まっているかである。

| 層 | 書かれたままで止まる案 | 止まる理由 |
|---|---|---|
| モーダル | P1、P2、P3、P4、P5（全案） | 非同期ポップアップの見逃し（P1）、PickItem の欠落（P2、P4、P5）、Legacy の取引（P3） |
| CTA の出口 | P1、P5 | AutoAct が中断されると PlayerTurn に落ちる |
| フォーカス | P2 | 停止がループの先頭にあり、対策はループの末尾にある |
| 入力モデル | P3 | 束縛キーの経路が実装と逆向き |
| キャラクター作成 | P3、P4、P5 | UGUI と UI スレッドの `*Async` で動くので、無人では作れない |
| brain | P1 | 長期走行の監視、ループ検出、費用の段階がない |

どの案も書かれたままでは作れない。ただし、どの致命傷も一つの層に閉じている。だから、各層で傷のない案の部品を選べば合成できる。骨格に P2 を選ぶのは、P2 の傷が差し替えのきく部品（既定の実行器 E1 と、フォーカス対策の置き場所）に集中し、骨格そのもの（CTA 境界、ClientWebSocket、BackupChar によるグリフの取得、SkipPlayerTurn による起床、軽い工程）は v1 で動いた実績があるからである。

## 3. エンジンに関する主張の検証

### 3.1 統合した 14 の主張と判定

「2 票」は敵対検証の 2 票の判定を示す。「本書の判定」は、票が割れた点や本書で読み直した点を反映したものである。

| ID | 主張の要約 | 依存する案 | 2 票 | 本書の判定 | 設計への帰結 |
|---|---|---|---|---|---|
| C01 | CTA 内で数十秒〜数分ブロックしても安全。gameQueue は回しても回さなくてもよい | P1, P2, P4, P5 | 部分支持 / 部分支持 | 部分支持。回さない側に与する | 待機は `await` を使わない同期待ち。`gameQueue` は回さない。入口で `RenderBase` を 1 回だけ呼ぶ |
| C02 | Harmony なしで、UI スレッドから Modern のポップアップに答えられる | P1, P2 | 部分支持 / 部分支持 | 部分支持 | 実物の項目を渡し、`copyWindow` の複製も探す。`Hide` を先に呼ばない。R5 で実測する |
| C03 | Harmony なしで、入力待ちを誤検出ゼロで判定できる | P1, P3 | **反証 / 反証** | **反証** | 「ゼロ」は求めない。ゲームスレッド側の自己申告と、UI 側の保留述語とトークンで、二重応答を防ぐ |
| C04 | Rosetta 上の Harmony 2.2.2 で、Popup への prefix が効く | P4, P5 | 部分支持 / 部分支持 | 部分支持（Roslyn の経路は未実測） | Plan C に格下げし、R8 で並行して測るだけにする |
| C05 | Modern のモーダルは、列挙できる少数の合流点を通る | P2, P4, P5 | **反証** / 部分支持 | 部分支持（2 票目に与する） | 合流点は 4 系統ある。専用画面は開かないか、Cancel する |
| C06 | runInBackground とフラグの書き込みで、フォーカスの問題が消える | 全案 | 部分支持 / 部分支持 | 部分支持 | 書き込みはブリッジスレッドから行う。`focused` は入力を積む前に立てる。R3 で実測する |
| C07 | AutoAct の委任と SkipPlayerTurn で制御が戻り、1 判断が 5 ターン以上になる | P1, P3, P4, P5 | 部分支持 / 部分支持 | 部分支持（下限はない） | 中断理由はガードで自前に作る。ポップアップで止まる区間はウォッチドッグが拾う |
| C08 | 直接 API は画面経由と同じ結果になる | P1, P2, P4, P5 | 部分支持 / 部分支持 | 部分支持 | 能力値、技能、装備、所持品の操作は直接呼ぶ。取引は 3 週間の範囲外。対象を取る能力はピッカーに答える |
| C09 | E1 で押し込んだ命令は確実に実行される | P2 | 部分支持 / 部分支持 | 部分支持（成立条件が狭い） | E1 を既定から外す |
| C10 | Legacy UI なら、ゲーム中の UI はすべて文字画面と getvk に乗る | P3 | 部分支持 / 部分支持 | 部分支持 | Plan B として使える。例外は運用で避ける |
| C11 | 主線は、行動文法とモーダル経路の外の入力面を必要としない | P2 | 部分支持 / 部分支持 | 部分支持（端末は任意） | 自由文字入力、色の選択、ThinWorld の getch ×8、本物の Look を道具に加える |
| C12 | クリアの述語は機械で判定できる | P1, P4, P5 | 部分支持 / 部分支持 | 部分支持 | 実績は証拠にしない。EndType の遷移をその場で捕まえ、wish への経路が構造上ないことと合わせて判定する。クリアに数えるのは Spindle 以降の 5 値で、Brightsheol は別枠にする |
| C13 | 観測は、人間に見える面だけで完全に作れる | P2, P3, P5 | **反証 / 反証** | **反証** | 「完全」を主張しない。漏れの監査（R9）と、捕獲時点での記録に置き換える |
| C14 | プロセス内のブリッジは長期に安定する | P1, P3 | 部分支持 / 部分支持 | 部分支持（2 票目に与する） | コールバックは init のたびに無条件で登録する。ゲーム内の HTTP サーバーは採らない |

### 3.2 各主張の正しい言い方

- **C01（部分支持）。** CTA ハンドラの中でゲームスレッドを長くブロックしても、静的にはデッドロックしない。UI スレッドはゲームスレッドを同期で待たない（`gameQueue.awaitTask` の呼び出し元は 0 件）。エンジン自身も、`Popup.cs:908` の `Task.Wait()` や `EndGame.cs:288,328,495`【本書確認】で、キューを回さずにゲームスレッドを長く止めている。回さなければ、UI 起点のタスク（ツールチップ、アビリティバーのクリック）が CTA を抜けた後に遅れて走るだけで済む。回すと、積まれたタスクは個別に捨てられず、入れ子のまま最後まで走る。その中には `EndGame.Start` も入りうる（`queueTask` は `EndGame.cs:172`【本書確認】）。`The.Game` は終局をまたいで同じオブジェクトなので、同一性の検査ではこれを検出できない。チェックポイントのロードは `gameQueue` ではなく `ActionManager` のコマンドキューを通る（`CheckpointingSystem.cs:37-72`【本書確認】）。待機ループは `await` を使わずに書く。ゲームスレッドの `SynchronizationContext` は素のもので、継続がスレッドプールに移るからである。`RenderBase` はキューを回す（`XRLCore.cs:2600-2605`【本書確認】）ので、地図を描き直すための呼び出しは CTA の入口で 1 回だけにする。バニラの PlayerTurn も反復ごとに `RenderBase` を呼ぶ（`XRLCore.cs:2368,2373`【本書確認】）。したがって、会話が積んだ `EndGame.Start` は、キューを回さない方式でも CTA ハンドラの中で走る。回す方式と回さない方式の本当の違いは、入れ子かどうかではなく頻度（待機中に 100 ms ごとか、CTA ごとに 1 回か）である。06 は、回す前にキューの中身を記録し、回した後で `Running` と `EndType` を読み直す（06 §1.2 の 4）。
- **C02（部分支持）。** Harmony なしで、UI スレッド（`uiQueue.queueTask`）から PopupMessage 系のポップアップに答えられる見込みは高い。条件は五つある。
  1. `getWindow("PopupMessage")` の単体だけでなく、`copyWindow` の複製 "PopupMessage #N" も探す（`UIManager.cs:323-342`【本書確認】）。
  2. 本文の選択肢は `OnSelect` に、下段のボタンは `OnActivateCommand` に渡す。渡すのは text が null でない実物の項目に限る。`WaitNewPopupMessage` の `commandCallback` は `text.Replace` を呼ぶので、null なら例外になる（`Popup.cs:834-852`【本書確認】）。
  3. 入力欄つきのポップアップは、`inputBox.text` を先に設定してから `OnInputSubmit` を呼ぶ。
  4. `CmdOptions` の項目と、チュートリアルのゲート中は、`OnActivateCommand` が何もしない（`PopupMessage.cs:926-933`【本書確認】）。
  5. `Hide` を先に呼ぶと、`onHide` がキャンセルを立て（`Popup.cs:776-778,873-877`、`PopupMessage.cs:1083-1104`【本書確認】）、ゲームスレッドの `Task.Wait` が例外になる。

  `Keyboard.PushKey` は Modern のポップアップには届かない。ゲームパッド時の AskNumberScreen と PickGameObjectScreen は別に扱う。
- **C03（反証）。** Harmony なしのポーリングで作れるのは、部分的な検出器にとどまる。`CurrentGameView=="PopupMessage"` かつ `commandCallback!=null` で分かるのは、同期の `WaitNewPopupMessage` 系だけである。`OnSelect` で答えた後は `commandCallback` が残る（`PopupMessage.cs:936-944`【本書確認】）。そこで `selectCallback!=null` も条件に加え、`commandCallback` の参照をトークンにして、同じポップアップに二度答えないようにする。`"DynamicPopupMessage"` の複製、PickTarget と PickDirection、会話、取引、PickGameObject には別の述語が要る。PickTarget と PickDirection は同じ `"PickTarget"` ビューを使うので、`PickTargetWindow.currentMode` で区別する（`PickDirection.cs:30-31`【本書確認】）。Legacy の 4 条件は、フォーカス喪失時の停止や終局演出の Sleep で偽陽性を出す。確実な入力待ちは、ゲームスレッドが自分から申告する場合（CTA で待つ場合）にしか得られない。
- **C04（部分支持）。** ModInfo は、Roslyn でコンパイルした mod に `[HarmonyAttribute]` の派生を持つ型があれば、同梱の Harmony 2.2.2 で `PatchAll` を呼ぶ（`ModInfo.cs:849-854`【本書確認】）。失敗しても例外は握りつぶされ、build_log に "Failure :(" と出るだけである（`:857-860`【本書確認】）。arm64 ネイティブでは mprotect の EACCES で失敗し、Rosetta では成功する。ただし成功の実測は QudJP の `LoadFrom` 経路のもので、Roslyn 経路では測っていない。prefix で元の処理を飛ばすには、async void の `WaitNewPopupMessage` では prefix の中で callback を同期的に呼び、`NewPopupMessageAsync` では `__result = Task.FromResult(item)` を返す。両方を押さえないと AskString が漏れる。
- **C05（票が割れた。2 票目に与する）。** 1 票目は Launch の経路に AskString がないとしたが、`ShevaStarshipControl` は発射を始める前に `Popup.AskString` で確認語を求める（`ShevaStarshipControl.cs:94`【本書確認】）。終局の 4 経路は、どれも AskString を通る（`EndGame.cs:162`、`AscensionCable.cs:95,124`、`ShevaStarshipControl.cs:94`、`ThinWorld.cs:62`【本書確認】）。ゲームスレッドを止める Modern の入力待ちは、次の 4 系統に合流する。
  - (a) ポップアップ。`WaitNewPopupMessage` の `Task.Wait` と、`NewPopupMessageAsync` の `.Result` である。AskString は `Popup.cs:1442`、AskNumber は `:1200`【本書確認】。
  - (b) ゲームスレッドの getvk / getch ループ。PickDirection、PickTarget、射撃、Look、ThinWorld の getch がこれに当たる。
  - (c) 専用画面の `.Result`。PickGameObjectScreen（`PickItem.cs:285,307,319`）、TradeScreen（`TradeUI.cs:458`）、StatusScreensScreen（`Screens.cs:80,125`）、BookScreen（`BookUI.cs:429,466`）、AbilityManagerScreen（`AbilityManager.cs:149`）、CyberneticsTerminalScreen（`CyberneticsTerminal.cs:201`、`GenericTerminal.cs:83`）、GameSummaryScreen（`GameSummaryUI.cs:32`）がある【本書確認】。06 は、PickGameObjectScreen を `Cancel()` し、それ以外を実行器の許可リストで開かせない。
  - (d) 入力の要らない長いブロック。`EndGame.Start` の 11 秒、クレジットの最大 145 秒（`EndGame.cs:415`）、コーダの期限なしの待ち（`:495`）がある【本書確認】。

  「少数の合流点」とは言えるが、P2、P4、P5 の一覧は、どれも (c) を欠いていた。
- **C06（部分支持）。** `OptionMusicBackground=Yes` で `Application.runInBackground` を真にすると（`Options.cs:1447,1452`【本書確認】）、非フォーカスでも Unity の Update は走る。`uiQueue.executeTasks()`（`GameManager.cs:2963`【本書確認】）は `bThreadFocus` のゲート（`:3108`【本書確認】）より前にあるので処理される。ただしゲートが閉じている間は、毎フレーム Sleep(250) が入る。Unity 本体の挙動なので、実機で確かめる。
  - `OnApplicationFocus(false)` は `bThreadFocus` を上書きする（`GameManager.cs:1920-1922`【本書確認】）。CTA のたびに書き戻すだけでは、PlayerTurn の停止（`XRLCore.cs:737-740`）に入った後で戻れないので、書き込みはブリッジスレッドから周期的に行う。
  - `focused` の setter は false→true の遷移で入力を消す（`GameManager.cs:412-417`【本書確認】）。入力を積む前に立てる。
  - `ControlManager.GetButton*` は本物の `Application.isFocused` で門番されている（`ControlManager.cs:642-690`【本書確認】）。フラグを偽っても、Rewired 経由の UI 操作は非フォーカスでは動かない。
- **C07（部分支持）。** CTA で `AutoAct.Setting` を置き、エネルギーを使わずに true を返すと、同じ反復の AutoAct 分岐（`ActionManager.cs:805-839`【本書確認】）で 1 歩目が進む。以後は、歩ごとに CTA が先に再発火する。同じ呼び出しで `SkipPlayerTurn=true` を立てておけば、中断されても `:1584-1588` で CTA に戻る。1 判断あたりのターン数に下限はない。視界に敵がいれば 0 歩で止まり、`.N` は N−1 ターンになる。経路がない、探索先がないといった理由で AutoAct 分岐が `Popup.Show` を呼ぶと、ゲームスレッドはポップアップで止まり、CTA は来ない。中断理由は、`AutomoveInterruptBecause`、"You stop" のメッセージ、Setting の変化を組み合わせて、ベストエフォートで回収するしかない。
- **C08（部分支持）。** Modern の画面は同じ static API を `APIDispatch` 経由で呼ぶだけである。したがって、`StatusScreen.BuyStat`、`MutationsAPI.BuyRandomMutation`、`SkillsAndPowersScreen.SelectNode`、`EquipmentAPI` の装備操作、`GetInventoryActions` で列挙した `InventoryAction.Process` は、CTA から直接呼んでも同じ効果になる（コード上の推論）。例外は三つある。
  - 取引: `TradeUI.PerformOffer` は決済しかせず、価格を計算しない。`ShowTradeScreen` の前処理（戦闘中などの拒否、`GetTradePerformanceEvent`、`GetObjects`、`UpdateTotals`、`CalculateTrade`）を再現しないと、価格がずれる。
  - case 本体: 許可した case 本体の多くは UI を開く。`CmdTalk` は PickDirection を、引数なしの `ThrowWeapon` は射撃のピッカーを、候補が複数ある `CommandGet` は PickGameObjectScreen を開く。
  - 対象を取る能力: 多くは、プレイヤーに対して `Target` と `TargetCell` を無視し、必ずピッカーを開く。
- **C09（部分支持。成立条件が狭い）。** EndPlayerTurn のコールバック（`XRLCore.cs:2356-2358`【本書確認】）は、入力のない待機の反復も含めて、反復ごとに呼ばれる。そこで押し込んだ命令が次の反復で取り出されるのは、次の三つがそろう場合に限られる。
  1. エネルギーが 1000 以上残っている。
  2. 同じコールバックで `SkipPlayerTurn` を立てていない。
  3. 押し込みと取り出しの間に、ビューの切り替え（`GameManager.cs:3178-3182`【本書確認】）もフォーカスの遷移（`:412-417`）も割り込まない。

  `:734` の `ClearMouseEvents` は、PlayerTurn の入口で 1 回だけ走り、移動系以外を消す（`XRLCore.cs:734-740`【本書確認】）。explore の `return` のようにコールバックを通らない抜け方では、結果は AutoAct が止まった後の CTA でしか確定しない。
- **C10（部分支持）。** `OptionModernUI=No` にすると `UIManager.UseNewPopups` が偽になり、キャラクター作成後の入力要求の主な経路は、文字画面と getvk（AskString は getch）に乗る。`OptionUseTiles` は経路に関係しない。例外は、メインメニューからロードしたときの mod 構成不一致の確認（`XRLCore.cs:3428,3448`）、ステータス画面でのカスタム代名詞の作成、Legacy のキー再割り当てで、どれも進行には要らない。終局の暗転、クレジット、コーダは文字画面に載らない Unity の演出で、入力は求めない。
- **C11（部分支持。端末は任意）。** 主線の必須ステップは、端末 UI、Tinkering 画面でのクラフト、Sifrah（既定で無効）を必要としない。Grit Gate の端末も任意で、襲撃は `ScriptCallToArms` のタイマーで進む（`ScriptCallToArms.cs:54,70-86`【本書確認】）。ただし、行動文法と番号で選ぶモーダルだけでは足りず、次の四つが要る。
  - (a) 自由文字入力。Mark of Death の刻印（`TattooGun.cs:167`、`Engraver.cs:139`【本書確認】）、ENTOMB、ASCEND、各エンディングの確認語がこれに当たる。
  - (b) 色の選択と、自分を対象にする PickDirection。
  - (c) ThinWorld への移送中に、Popup を通らない生の `Keyboard.getch` ×8 に答えること（`ThinWorld.cs:275-278`。getch は `:278`、その前に `:260` でビューを `"GameSummary"` にする【本書確認】）。
  - (d) `AfterLookedAt` を発火させる本物の Look。"Recover the Mark of Death" は、墓石が `AfterLookedAt` を受けたときにしか進まない（`D/XRL.World.Parts/RachelsTombstone.cs:88-92`【本書確認】）。`AfterLookedAt` を発火するのは、Look の画面（`D/XRL.UI/Look.cs:304,324,397,534`）、Modern のツールチップ（`D/Qud.UI/BaseLineWithTooltip.cs:172-176`）、`Description` の InventoryAction の Look（`D/XRL.World.Parts/Description.cs:333-376`）である【本書確認】。最後のものは、説明文のポップアップを出してから `LookedAt` と `AfterLookedAt` を発火する。06 はこれを Look の実行器に採る（06 §1.3）。ツールチップの経路は、人間のマウスのホバーだけで `gameQueue` にタスクを積むので、帰属のセンサーが要る（06 §3.3）。

  ワールドマップでは自動探索が効かない（`XRLCore.cs:1920-1926`【本書確認】）。
- **C12（部分支持）。** 実在するエンディングは 5 系統ある。どれも EndType を 6 値（Brightsheol / Marooned / Return / Covenant / Accede / Launch）のどれかに設定してから、`EndGame.UnlockAchievement()` を通る。
  - 会話パーツは `queueTask(Start)` を積む（`EndGame.cs:148-176`【本書確認】）。
  - AscensionCable、ShevaStarshipControl、`CheckMarooned` は `Start()` を直接呼ぶ（`AscensionCable.cs:128-133`、`ShevaStarshipControl.cs:221-231`、`EndGame.cs:812`【本書確認】）。
  - ThinWorld は `Start` を通らない。`UnlockAchievement` と `RunCredits` を呼んで `Running=false` にする（`ThinWorld.cs:71-82`【本書確認】）。

  CAVES_OF_QUD 実績は、解除済みなら何もしないので証拠にならない。Classic の Brightsheol ではセーブが消える（`XRLCore.cs:3031-3038`）ので、EndType はその瞬間に捕まえる。EndType は wish で偽装できるので、正規の経路を通ったことと突き合わせる。ゲームにはチート使用のフラグがない。

  6 値のうち Brightsheol だけは、主線の途中で自分から退役を選ぶ終わり方である。Tomb of the Eaters の段 "Ascend the Tomb and Cross into Brightsheol"（`Base/Quests.xml:389`）で着くセラフの会話が、Salum に戻るか Brightsheol へ渡るかを問う（`Base/Conversations.xml:10568-10587`）。渡る確認は "Crossing into Brightsheol will retire your character" である（`ThinWorld.cs:62`）【本書確認】。この段は Spindle の段（`Quests.xml:393,397`）より手前にある。ゲーム自身も、この選択肢に `[lesser victory]` の札を付けている（`D/XRL.World.Conversations.Parts/CrossIntoBrightsheol.cs:18`）。会話で終える終局には `[victory]` か `[greater victory]` を付ける（`EndGame.cs:144`【本書確認】）。そこで 06 は、クリアを Spindle 以降の 5 値に限り、Brightsheol は別枠で開示する（06 §4.5）。
- **C13（反証）。** 観測は人間に見える面から作れるが、既定のままでは完全でも再現可能でもない。
  - 表示名: `GetDisplayName(AsIfKnown:false)` を通せば、未鑑定品の本名は漏れない（`Examiner.cs:341-374`）。
  - 他者の状態: `Strings.WoundLevel` の出力を使う。Scanning を持つと数値になり、`NoDamageReadout` なら空になる。
  - 実体: `Cell.Objects` 全体ではなく、`GameObject.IsVisible()` か描画の条件で絞る。
  - 注釈とメッセージ: 後から再計算できないので、捕獲時に記録する。メッセージ履歴は、Suppress 中の出力と `LogMessage:false` のポップアップを含まない。
  - `BackupChar`: `OnPaint` 系の上書きで古い字が残ることがある。
- **C14（部分支持。2 票目に与する）。** Roslyn はロード済みのアセンブリを参照に加える。Newtonsoft.Json は `ModManager` が先にロードする（`ModManager.cs:47`【本書確認】）ので参照できる。`Managed/System.dll` に `HttpListener` の型はある。しかし Unity の Mono で `127.0.0.1` に bind できるか、keep-alive と並行 long-poll が何時間ももつかは、確かめられていない。
  - `[ModSensitiveCacheInit]` は、起動時と hotload のたびに呼ばれる。new game、load、メインメニューへの復帰では呼ばれない。
  - 1 票目は「コールバックリストはクリアされない」とした。実際には、XRLCore のコールバックリスト 6 本はすべて `[ModSensitiveStaticCache(true)]` で、hotload のたびに空になる（`XRLCore.cs:252-273`【本書確認】）。そのため、登録は init のたびに無条件で行い、static bool のガードは使わない。ガードを使うと、reload の後にコールバックが消える。
  - mod の構成を変えるとプロセスが再起動し、新しいプロセスは古いプロセスの終了を待たない。ゲーム内で待ち受けるサーバーには、bind のリトライが要る。
  - セーブ本体には何も残らないが、mod の ID はセーブのヘッダーに記録される。

### 3.3 本書の確認で新たに分かったこと（静的）

1. **終局の確認は Harmony なしで確定できる。** PC で `WantsSpecificPrompt` つきの AskString が出すボタンは、Submit（command `"keep"`）、Cancel、「長押しで確定」（`CmdOptions`）の三つである（`Popup.cs:1375-1380`、`PopupMessage.cs:599-619`【本書確認】）。`OnActivateCommand` は `CmdOptions` を拒むが、`OnInputSubmit` は下段の最初の Submit / Accept / CmdOptions に `OnSelect` を呼ぶ（`PopupMessage.cs:946-958`【本書確認】）。エンジン自身の長押し処理も、2 秒たつと `inputBox.text` に確認語を入れて `OnInputSubmit` を呼ぶだけである（`:1024-1031`【本書確認】）。結果の文字列は `inputBox.text` から写される（`Popup.cs:782-784`【本書確認】）。したがって、UI スレッドで `inputBox.text` を設定して `OnInputSubmit` を呼べば、人間が長押ししたときと同じ経路で確定する。長押しが途中で離されたとき以外、Update は入力欄を消さない（`:1009-1015`【本書確認】）。死亡メニューの "RETIRE" は、語が違えばループに戻るので（`CheckpointingSystem.cs:126-141`【本書確認】）、同じ仕組みを安全に試す場所として使える。
2. **`Hide` は `onHide` を同期で呼ぶ**（`PopupMessage.cs:1098-1103`【本書確認】）。選択のコールバックが先に `onHide` を「結果を立てる」処理に差し替えてから `Hide` を呼ぶ、という順序が、正しく答えるための条件になる。
3. **`ControlManager.WaitForKeyup` はブロックしない**（`ControlManager.cs:704-713`【本書確認】）。リストに ID を足すだけなので、UI スレッドから `OnInputSubmit` を呼んでも止まらない。
4. **複製ウィンドウは "PopupMessage #N" の名前で `windowsByName` に登録され、解放時はプールに戻って非アクティブになる**（`UIManager.cs:323-352`【本書確認】）。`windowsByName` のうち "PopupMessage" で始まり、アクティブなものを列挙すれば、表示中のポップアップがすべて見つかる。
5. **EndPlayerTurn のコールバックは、PlayerTurn に入ったことのセンサーであり、脱出口でもある。** 呼び出し元は `XRLCore.cs:2356-2358` だけで、PlayerTurn の反復ごとに呼ばれる。CTA で完結する設計では、このカウンタは 0 のままであるはずである。ただし、クリアの述語の条件にはしない（想定外の 1 回で走行全体が無効になるため。06 §4.5 の 2）。1 以上になったら台帳に記録して開示し、同じコールバックで `SkipPlayerTurn=true` を立てれば、`IdleWait` の直後に抜けて CTA に戻る（`:2390-2397`【本書確認】）。ただし、ループ先頭のフォーカス停止（`:737-740`）で止まった場合はコールバックまで届かない。そのためウォッチドッグとフォーカスの維持（06 の R3）が別に要る。
6. **チェックポイントは PlayerTurn なしで動く。** `SaveCommand` と `LoadCommand` は `ActionManager` のコマンドキューに積まれ（`CheckpointingSystem.cs:18-72`【本書確認】）、`RunSegment` の終わりの `RunCommands()` で実行される（`ActionManager.cs:1672,1680-1700`【本書確認】）。死亡時のメニューは `Popup.PickOption` のループなので（`CheckpointingSystem.cs:111-153`、選択肢は `:114`【本書確認】）、モーダルの駆動で答えられる。ただし、選択肢の並びは `OptionDefaultDeathToViewFinalMessages`（既定は Yes）で入れ替わる（`:113-123`【本書確認】）。index で答えると "View final messages" のループに入るので、ラベルの文字列で答える。
7. **PlayerTurn の前処理は短いリストで、エンジン自身も PlayerTurn を通らない手番でその一部を呼んでいる。** 前処理は `TutorialManager.GameSync`、`CallBeginPlayerTurnCallbacks`、混乱度のリセット、忠誠の補修、`Messages.BeginPlayerTurn`、`Sidebar.UpdateState` である（`XRLCore.cs:692-733`【本書確認】）。AutoAct の分岐は 1 歩ごとに `Sidebar.UpdateState`、`CallBeginPlayerTurnCallbacks`、`RenderBase` を呼び（`ActionManager.cs:805-809`【本書確認】）、世界地図の移動は終わりに `Messages.BeginPlayerTurn` を呼ぶ（`TerrainTravel.cs:270-273`【本書確認】）。`TutorialManager.GameSync` はチュートリアルの現在の手順に同期するだけなので（`TutorialManager.cs:844-852`【本書確認】）、チュートリアルの外では要らない。PlayerTurn の末尾で呼ばれる `EnqueuePlayerCell` と `CheckPlayerLocations` は物理状態の整合をログに出すだけなので、省いてよい（`GamePlayer.cs:32-61`【本書確認】）。
8. **`PickGameObjectScreen.Cancel()` がある**（`Qud.UI/PickGameObjectScreen.cs:512-516`【本書確認】）。入力をリセットし、画面を隠し、既定の結果で完了させるので、ゲームスレッドの `.Result` が解ける見込みがある。UI スレッドから呼んで安全かは、06 の R5 で確かめる。
9. **同じ走行は再現できない。** 乱数はシードなしで初期化され（`Stat.cs:26-36`【本書確認】）、ロード時にアクティブなゾーンの ID とゲーム状態の値で再シードされる（`XRLGame.cs:1892-1897`【本書確認】）。行動が一つ違えば以後の乱数列は分かれ、LLM の出力も決定的でない。

### 3.4 実機でしか答えが出ない問い

| 問い | 関係する主張 | 06 のプローブ |
|---|---|---|
| gameQueue を回さずに CTA で数分止めても、Unity と UI が健全か | C01 | R1 |
| UI スレッドからの駆動が、4 系統のモーダルに 1 回ずつ正しく答えるか。Submit で終局の確認が通るか | C02、C03、C05 | R5 |
| ブリッジスレッドからフラグを書けば、非フォーカス時の停止と 200 ms の待ちが消えるか | C06 | R3 |
| AutoAct の委任が PlayerTurn に落ちないか。1 判断あたりのターン数はどう分布するか | C07 | R4 |
| 直接 API と shim が、画面経由と同じ状態の差分を生むか | C08 | R7 |
| hotload、ロード、メニュー復帰の後も、コールバックがちょうど 1 本ずつ残るか | C14 | R6 |
| Roslyn でコンパイルした mod から、Rosetta 上で Harmony が効くか | C04 | R8（任意） |
| Roleplay の死亡からチェックポイントへ復帰した後、クラッシュから再開した後も、判断要求とコールバックが 1 つずつに保たれるか | C14 | R6 |
| Look の InventoryAction が、Look の画面と同じジャーナルの変化を起こすか | C11 | R7 |
| 世界地図の上で `Move` と AutoAct の移動が進み、Lost から回復できるか | C11 | R10 |
| 観測に、人間に見えない情報が漏れていないか | C13 | R9 |
