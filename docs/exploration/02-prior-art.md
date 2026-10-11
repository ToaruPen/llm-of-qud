# 02. 先行事例調査：LLM がゲームを自律プレイするためのインターフェース設計

> 担当：Assignment B（先行事例）／ 調査日：2026-09-25
> 対象：RimMolt とその周辺、RimWorld 系エージェント、NetHack／DCSS 系ベンチマークとエージェント、Pokémon 系ハーネス、Caves of Qud（以下 CoQ）の既存 mod
> 目的：llm-of-qud が「画像を使わず、CoQ 内部のテキストと状態から知覚する」設計を詰める前に、既存事例の実績と失敗を証拠つきで集めること。ここに挙げるパターンは採用の推奨ではなく、証拠に基づく選択肢である。

---

## 0. 前提、出典の扱い、証拠グレード

### 0.1 逆コンパイルソースの版

CoQ 内部に関する引用はすべて **stable 版の逆コンパイルツリー** `/Users/sankenbisha/Dev/coq-decompiled_stable` による。形式は `path:line` で、パスはこのツリーのルートからの相対パスとする。別担当が扱う新しい版のツリー（scratchpad の `decomp-new`）とは行番号が一致しない可能性がある。

### 0.2 証拠グレード

| 記号 | 意味 |
|---|---|
| **[A]** | 一次ソースのコード（clone して commit を固定したリポジトリ、または逆コンパイル）を直接読んだ |
| **[B]** | 一次ソースの文書（README、論文本文、Workshop 説明文、開発者自身のブログ、配信者自身の公開ドキュメント） |
| **[C]** | 二次情報（報道記事、第三者ブログ、WebFetch による要約、コメント欄） |
| **[推論]** | 上記から筆者が導いた推論。事実としては扱わない |

### 0.3 出典についての注意（読み違えやすい点）

- **RimMolt 本体のソースは公開されていない。** 下のツール一覧は Workshop 説明文、議論スレッド、配信者の学習ファイルに現れた名前から**再構成したもの**で、完全な一覧ではない。
- **rimagent について。** clone したのは `kodek/rimagent`（commit `85cb050dec47691f2a80096fdc8c8a8e2051bb13`）で、これは `zorrobyte/rimagent` の fork である。ゲーム側 mod の RimBridge は submodule（`zorrobyte/rimbridge`）で、**clone していない**。そのため RimBridge の内部構造は README と `docs/PAPER.md` の記述に依存している（グレード [B]）。
- **名前の衝突。** `pardeike/RimBridgeServer` は zorrobyte の RimBridge とは**別のプロジェクト**である。
- **固定 URL の基点。** 以下、相対パスで書いた外部リポジトリの引用は、次の commit 固定 URL を基点とする（例：`src/Speech.cs:147` は `https://github.com/BlindGuyNW/qud-accessibility/blob/a3ebd92498f2c8546a5a125ec6dd25e0ed1befc2/src/Speech.cs#L147`）。
  - qud-accessibility：https://github.com/BlindGuyNW/qud-accessibility/blob/a3ebd92498f2c8546a5a125ec6dd25e0ed1befc2/
  - rimworld-ai-manager：https://github.com/agulaya24/rimworld-ai-manager/blob/36c2bccb32388ac6634b78d0af4cb09f0c56a5f6/
  - rimagent：https://github.com/kodek/rimagent/blob/85cb050dec47691f2a80096fdc8c8a8e2051bb13/
  - BALROG：https://github.com/balrog-ai/BALROG/blob/b7afe79e3e4265811cfa985ed7c95c4d1a11e3f5/
  - dcss-ai：https://github.com/nkhoit/dcss-ai/blob/1d5c818ce7380ae1872f9a782a9be39186dda739/
  - Archipelago mod：https://github.com/lonesurv1vor/CavesOfQudArchipelagoRandomizer/blob/e893f023603df847e3e5e73e3c4620e77178e08a/
- **数値の出所。** WebFetch 経由で得た数値（BALROG の o1-preview 1.5%、NetPlay のスコアなど）は二次情報（[C]）として扱う。
- **Steam のボイラープレート。** Steam ページ上の「removed」などの文言はテンプレートである可能性があり、mod の状態を示す証拠としては扱わない。

---

## 1. プロジェクト別プロファイル

各プロファイルは次の 6 軸で整理する。

1. インターフェースの通信路（transport）
2. 観測の表現
3. 行動文法
4. 記憶と自己改善
5. 評価
6. 失敗モード

### 1.1 RimMolt（leopoko, RimWorld）

RimWorld を MCP サーバー化し、外部の LLM クライアント（Claude Code、Codex など）にコロニー運営をさせる mod。llm-of-qud の発想の直接の元である。ソースは非公開なので、公開文書と配信者の記録から外形を組み立てるしかない。

| 軸 | 内容 | 出典 |
|---|---|---|
| 通信路 | ゲーム内で動く MCP サーバー（HTTP）。既定の endpoint は `http://localhost:8787/mcp`、ポートは変更可。登録例は `claude mcp add --transport http rimmolt http://localhost:8787/mcp` と Codex 用の TOML。Harmony が必須。9/15 のアップデートでランダムキー認証が追加された。バインド先は localhost のみ | [B] https://steamcommunity.com/sharedfiles/filedetails/?id=3796006886 ／[C] 議論 https://steamcommunity.com/workshop/filedetails/discussion/3796006886/564793434686222170/ |
| 観測 | 構造化データを返すツール群。対象は健康、欲求、装備、資源、研究、電力、部屋、マップ、アラート、レター、クエスト。開発版の旧説明文には「v1 は読み取り専用ツール（colony status, colonists, resources, research, map, alerts, world）を公開」とあった | [B] 上記 Workshop ／ 開発版 https://steamcommunity.com/sharedfiles/filedetails/?id=3758380614 |
| 行動 | 管理系（作業優先度、スケジュール、ポリシー、建設、栽培、保管、エリア、生産、医療、動物、囚人、徴兵、戦闘、交易、キャラバン）と進行系（シナリオ／ストーリーテラー／ワールド生成、速度、セーブ／ロード、時間送り）。配信者のメモに現れたツール名は `set_speed`, `list_windows`, `window_action`, `save_game`, `inspect_thing`（`directionalHint`）, `order_pawn`, `build`, `do_thing_action`（`executed`／`openedWorldTargeter`）, `world_target`（`confirmed`）。**この一覧は再構成であり、網羅的ではない** | [B] Workshop ／ [B] 学習ファイル https://docs.google.com/document/d/1s0x0RkPiDrLgjVQDREnX4aPAR0VqR2aGhehYRhbuDXg |
| 記憶・自己改善 | mod 側には持たない。LLM クライアントと配信者が運用で補っている（1.1.2 節） | [B] |
| 評価 | 公式のベンチマークはない。配信者による「クリアまでの実時間」「全滅の回数」が事実上の指標 | [C] https://www.gamespark.jp/article/2026/09/07/171892.html |
| 失敗モード | ツールチップ（ムードの思考項目など）が読めない。開発モードのデバッグ操作が使えない。派閥画面や描画済みのステータスパネルが読めない。ロード時に停止しない。ターゲッターをキャンセルできない。ゴッドモードがない。エリアの作成／削除が一時期欠けていた（後に修正）。8GB GPU で動くローカルモデルは MCP ツールをほぼ使いこなせない | [C] Workshop コメント／議論 https://steamcommunity.com/workshop/filedetails/discussion/3796006886/581681621355472587/ |

#### 1.1.1 周辺ツール

- **Cinematic Camera**（https://steamcommunity.com/sharedfiles/filedetails/?id=3796009589）[B]
  - `cinematic_camera` という MCP ツールを公開する。F9 で切り替え、5〜15 秒ごとにカットし、日常モードと戦闘モードを持つ。
  - これは配信の見栄えのための機能で、エージェントの知覚には使われない。
- **Codex-RimMolt-Pause-Hook**（https://github.com/leopoko/Codex-RimMolt-Pause-Hook）[B]
  - Codex の `PreCompact` フックが、`/mcp` に JSON-RPC の `tools/call`（`set_speed {action:"pause"}`）を直接 POST する。
  - 結果のテキストは `{ok, message, paused, speed}` という JSON。
  - initialize ハンドシェイクを経ていないので、サーバーはステートレスな呼び出しを受け付けていると考えられる **[推論]**。
  - 目的は、LLM が文脈を圧縮している間にリアルタイムのゲームが進むのを止めることだった。

#### 1.1.2 配信者の実運用：アポクリトン氏の記録

RimMolt で「クリアできた」という報告は、画像なしの知覚で達成されたと読まれやすい。実際は違う。

- **成果**：GPT-6 Astra が自作の「攻略本」（学習ファイル）を使い、約 15 時間の実プレイで RimWorld をクリアした [C]。
  - 進行が完全に止まった場面で、人間が 1 回だけ指示を出し直している。
  - ルールは開発モード禁止、ファイル編集禁止、Commitment モード、Cassandra／Community Builder。
  - 出典：https://www.gamespark.jp/article/2026/09/07/171892.html
- **指示書はスクリーンショットを許可していた** [B]。
  - 通常はゲーム内で約 5 日ごと、加えて緊急時にも撮影する。
  - 同じ指示書は構造化データを優先するよう求め、戦闘中は積極的に停止するよう指示している。
  - 行動サイクル：状況確認 → 問題特定 → 短期目標 → まとめて実行 → 時間送り → 検証 → 修正。
  - 出典：https://docs.google.com/document/d/1KLIsBu1jJNAh3R-x_edxagCBZUhCnC1hrBPhhcC2yBM
  - つまり、この成功は**純粋な非視覚知覚の実証ではない**。テキストの方が画像より有効だという証拠は、BALROG や GPP から別途得る必要がある（1.5 節、1.10 節）。
- **進捗記録から読める知見** [B]（https://docs.google.com/document/d/1MKG6i5N_rgjs9hVZ5oagZSoCJJ4aY38nNsRQGUF51w8）
  - 指導なしでは 3 回失敗した。
  - 学習は外部ファイルに保存しないと残らなかった。
  - YouTube 動画から学ばせる試みは失敗した。
  - 文脈を圧縮すると戦略を忘れた。
  - 「岩壁を二重にする」のような具体的な指示は効いた。
  - 屋根のない電気設備が雨でショートするといった、AI 特有の見落としを収集していた。
  - 行動を小説風に語らせた。
  - 失敗時は自動でやり直させた。
  - YouTube コメント経由のプロンプトインジェクションを危険視していた。
- **視聴者との対話**：チャットを読ませ、`/装備` のようなコマンドを受け付けていた [B]。
  - 出典：https://www.youtube.com/watch?v=jcu52TV_F44 、https://www.youtube.com/watch?v=sUGGhYg1Oyk
  - 別の配信（GPT 5.6 Sol, Phoebe）では、smart speed、Declare Victory、research whatever などの補助 mod を併用していた：https://www.youtube.com/watch?v=IlzkUm2eFKE

学習ファイルの構造は、記憶を設計するうえでそのまま参考になる [B]。

- 変更しない `AGENTS.md` と、単一の `RIMWORLD_LEARNING.md` に分かれる。
- `RIMWORLD_LEARNING.md` の節は `PROJECT_STATE` / `ACTIVE_RUN` / `ACTIVE_LESSONS`（上限約 40 件）/ `RIMMOLT_NOTES` / `RUN_HISTORY`。
- 起動時に読むのは上位の節だけで、残りは必要なときに検索する。
- ツール一覧とスキーマの確認はセッションごとに 1 回だけ行う。
- 失敗したら、停止 → 状態の読み直し → 冪等なリトライを 1 回、という順で対処する。

`RIMMOLT_NOTES` の RM-001〜RM-022 は、**インターフェースの落とし穴の実地カタログ**になっている。CoQ に関係しそうなものを挙げる。

| ID | 内容 | CoQ で起こりうる類似（[推論]） |
|---|---|---|
| RM-004 | 命令は 2 段階：選択肢を列挙してから、ラベルかインデックスで選ぶ | 会話の選択肢、`Popup.PickOption`、インタラクションメニュー |
| RM-006 | 強制停止ダイアログが時間送りを塞ぐ | `Popup.Show` 系のモーダル |
| RM-012 | 導入の `Dialog_NodeTree` を閉じると停止が解除される | モーダルを閉じた副作用で状態が進む |
| RM-022 | 発射ギズモが成功を返しても、ワールドターゲティングは始まっていない | 「成功」の戻り値と実際の状態遷移のずれ（例：`PickTarget` 待ちになる） |
| その他 | 資源一覧に所持品が含まれない。`build` は設計図を置くだけ。同じ命令を出し直すと作業がやり直しになる。時間送りで UI が閉じる。スクリーンショットがカメラを動かす。外部の承認サービスが操作を拒否した。名前変更をまとめて実行すると固まった。Commitment モードでは `save_game` の名前が無視される。ギズモを連打したら最終値を読み直す必要がある。自動戦闘 AI が遮蔽物から出てしまう | 「戻り値だけでなく状態を読み直す」原則の根拠 |

### 1.2 rimagent と RimBridge（zorrobyte、fork 元は kodek）

非公開の RimMolt と違い、rimagent は設計と結果を論文形式で公開している。中身まで追える RimWorld 系の事例としては、今回見た中で最も詳しい。

| 軸 | 内容 | 出典 |
|---|---|---|
| 通信路 | RimBridge は Harmony mod で、`HttpListener` を `127.0.0.1:8765` で開く。リクエストはワーカースレッドで解析され、ゲームへの操作は `Root.Update` の postfix が消化するキューを通して Unity のメインスレッドに渡される。フレームごとに処理量の上限がある。`/events?since=` でイベントを取り出す | [B] https://github.com/kodek/rimagent/blob/85cb050dec47691f2a80096fdc8c8a8e2051bb13/docs/PAPER.md#L35-L50 |
| 観測 | 知覚の並び順は変化しやすい順：(1) 追跡値とトレンド（例：`food_days 0.9→0.6→0.7→0.3→0.0 ↓`）、(2) 前ステップとの差分、(3) 開いているダイアログ、イベント、アラート、(4) 基地をオブジェクト（部屋、役割、問題）として、(5) 入植者と生のサマリ。グリッドは要求時のみで、*building camera* は最大 60×60。列番号を振り、建物種別ごとに 1 文字、設計図は小文字、`*` がインタラクション地点。建設に失敗すると、X 印入りの 13×13 のカメラを返す。第 2 カメラによる PNG スクリーンショットも存在する | [B] 同 PAPER.md#L88-L100 、L39 |
| 行動 | `ui.*` がプレイヤーの動詞に当たる（右クリックメニュー `orders_at`/`order`、ギズモの `press`、`designate`、`build_many`）。`engine.*` は `get/set/call` の汎用リフレクションで、パス文法の例は `Find.CurrentMap...FreeColonists[2].health`。場所は名前で指定する：`Campfire39256 +E2 +N1`、`bedroom2:NW`、`bedroom2:inset:1`、`Room:12`、`home`。アンカーはゲームと一緒に保存される。`dev.*` を使うとその回は *assisted* と記録される | [B] PAPER.md#L37-L42 、#L100 ／ README https://github.com/kodek/rimagent/blob/85cb050dec47691f2a80096fdc8c8a8e2051bb13/README.md |
| 制御ループ | 3 つのストリームがある。<br>・play：1 ステップ最大 30 回のツール呼び出し。`end_turn(notes, wake_in_hours, wake_on)` で終える。<br>・improve：1 日目と、以降 3 日ごと。<br>・watchdog：6 時間ごと、エラーが 8 件以上のときだけ動く。触れてよいパスを限定し、コミット前に検証し、デプロイはしない。<br>起床ポリシー：平穏なら 3 倍速、緊急時は停止、ステップ中のイベントは差し込む、起床間隔は最短 8 時間 | [B] README ／ PAPER.md#L104 |
| 記憶・自己改善 | brain ディレクトリ（skills は markdown で BM25 選択、tools と watchers は Python でホットロード）を git で管理し、エージェント自身が編集する。オフラインのゲーム wiki（2,970 記事）と、インストール済みビルドの逆コンパイルソース（9,213 ファイル）を検索できる | [B] PAPER.md#L108 、#L125 |
| 評価 | 281 ステップ、6,335 回のツール呼び出し。エラー率 10.8%（32% から 9.2% に低下）。エージェントが書いたツールは 13 個、watcher は 14 個で、自作ツールが占める割合は 4.4% から 9.7% に上がった。エピソード 1 は 26 日目に木造基地の火災で敗北。エピソード 2 はメカノイドを見て勝てないと判断し、エージェント自身が放棄した | [B] PAPER.md#L131-L135 |
| 失敗モード | 観察で見つかったインターフェース欠陥：<br>(i) 考えるための停止が、人間には固まったように見えた<br>(ii) 建設失敗の判定が建物の損失として届いた<br>(iii) モーダルダイアログがゲームを**見えない形で**止めていた<br>(iv) 作業量ゼロの設計図が永遠に完成しなかった<br>(v) 単独の manhunter で警報が鳴らなかった<br>(vi) モデルが JSON を文字列で渡したり、引数名を別名で呼んだりした<br>(vii) LLM ソケットがハングした<br>(viii) スコアボードが過少に数えていた | [B] PAPER.md#L139 |

§8 には運用で見つかった欠陥も書かれている [B]（PAPER.md 157–205 行付近）。

- **Steward の導入で LLM の仕事が減った。**
  - エージェントは watcher 8 個（416 行）を自分で削除した。
  - ステップあたりのツール呼び出しは中央値 20 回になり、`ui_set_work` は 307 回から 2 回に減った。
- **実行中の欠陥**：
  - セーブ／ロードで `MissingMethodException` が起き、ターゲット値が 0 になった。
  - 初期の doctrine に `find(def=...)` の SyntaxError があった。
  - マップを持たない Thing で NRE が起きた。
  - 70 セルの半径上限が隠れていた。
  - **doc string が嘘をついていた。** モデルはエラーメッセージより doc string を信じた。

システムプロンプトは "director, not foreman"（現場監督ではなく指揮者）を掲げ、どの高度で判断するかの段階（altitude ladder）、ツールの予算、作業を細かく設定しないことを指示している [B]（https://github.com/kodek/rimagent/blob/85cb050dec47691f2a80096fdc8c8a8e2051bb13/agent/rimagent/prompts/system.md）。

### 1.3 pardeike のエコシステム（RimBridgeServer、GABS、Lib.GAB）

Harmony の作者 pardeike による、ゲームと AI をつなぐための汎用部品群。どれも llm-of-qud の通信路の候補になりうる。

| 部品 | 内容 | 出典 |
|---|---|---|
| Lib.GAB | netstandard2.0、Unity/Mono 向け。TCP `127.0.0.1` 上でトークン認証を行い、スキーマつきの `tools/list`、events、attention を提供する | [B] https://github.com/pardeike/Lib.GAB |
| GABS | 設定ファイル中心の MCP サーバー。ゲームのプロセスを監視し、GABP ブリッジのツールを MCP 側にミラーする | [B] https://github.com/pardeike/GABS |
| RimBridgeServer | RimWorld 向けの GABP ブリッジ（zorrobyte の RimBridge とは別物） | [B] https://github.com/pardeike/RimBridgeServer |
| DecompilerServer | 逆コンパイル結果をエージェントに提供するサーバー | [B] https://github.com/pardeike/DecompilerServer |

参考として、codexvn の RimWorld MCP もある（localhost:9877、21 ツール、skills を .md で配布）[C]：https://lobehub.com/mcp/codexvn-rimworldmod_rimworldmcp

**[推論]** Lib.GAB は netstandard2.0 の Unity/Mono 向けなので、CoQ の mod から読み込める可能性がある。ただし CoQ の mod は Roslyn で実行時にコンパイルされる（`XRL/ModManager.cs:116-135`）。外部 DLL を参照するには、Archipelago mod と同じように `Assembly.LoadFrom` とリフレクションを使う必要があるかもしれない（1.12.2 節）。

### 1.4 rimworld-ai-manager と RIMAPI

rimagent の Steward と同じ発想を、LLM の外に置いた例である。常駐デーモンが恒常性（homeostasis）を保ち、LLM は戦略だけを担当する。

| 軸 | 内容 | 出典 |
|---|---|---|
| 通信路 | RIMAPI（GPLv3、REST と SSE、`localhost:8765`）。191 エンドポイント（RIMAPI 1.10.0）。応答の封筒は `{success,data,errors,warnings,timestamp}`。`map_id=0` の指定が必須 | [B] https://github.com/IlyaChichkov/RIMAPI ／ リポジトリ内のリファレンス |
| 観測 | `colony_daemon.py` が LLM を使わずに 8 秒ごとにポーリングする。「真の状態」を読むことにこだわり、`pawn/edit/needs` が嘘の値を返すことを文書化している | [A] https://github.com/agulaya24/rimworld-ai-manager/blob/36c2bccb32388ac6634b78d0af4cb09f0c56a5f6/colony_daemon.py#L171 |
| 行動 | デーモンは食料を (s,S) 発注方式（食事換算）で補充する。危機はエッジトリガーで扱う：1 回だけ停止し、統合し、1 回だけエスカレーションし、その後は手を出さない。LLM は `daemon_escalations.log` を読み、再開の判断を持つ | [A] colony_daemon.py#L1-L35 、#L72 、#L103 、#L263-L282 |
| 記憶・自己改善 | `POSTMORTEM.md` の 5 つの問い（欠けていたのはセンサーか、ルールか、閾値か）。振り返りは必ず機械的な修正で終える（「X を覚えておく」は失敗扱い）。死亡以外は 2 回以上起きてから規則にする。誤検知のコストを明記する。一度も発火しない規則は削除する | [B] https://github.com/agulaya24/rimworld-ai-manager/blob/36c2bccb32388ac6634b78d0af4cb09f0c56a5f6/POSTMORTEM.md |
| 評価 | `review.py` がゲーム内 1 日あたりのエスカレーション数などを数える | [A] colony_daemon.py#L103-L106 |
| 失敗モード | `REGRESSION_CHECKLIST`（https://github.com/agulaya24/rimworld-ai-manager/blob/36c2bccb32388ac6634b78d0af4cb09f0c56a5f6/REGRESSION_CHECKLIST.md）：動物がフィルタで除外されていて manhunter が見えなかった。火災が監視されていなかった。`except:pass` がアクチュエータの失敗を隠した。最初の交易商人がゲームを永久に停止させた。<br>`SPEC_FINDINGS`（https://github.com/agulaya24/rimworld-ai-manager/blob/36c2bccb32388ac6634b78d0af4cb09f0c56a5f6/SPEC_FINDINGS.md）：座標系が (x,y) と (x,z) で食い違っていた。優先度の setter が N を無視した。`add_bill` に個数の指定がない | [B] |

`FACTORIO_AUTOMATION_LESSONS.md`（https://github.com/agulaya24/rimworld-ai-manager/blob/36c2bccb32388ac6634b78d0af4cb09f0c56a5f6/FACTORIO_AUTOMATION_LESSONS.md）は 11 の原則を挙げている（バッファを持つ、最も深い不足から直す、安定が成長の引き金になる、など）[B]。

### 1.5 BALROG（NetHack などのベンチマーク）

「テキストは画像に勝るか」という問いに、今回の事例の中で最も直接に答えている。

| 軸 | 内容 | 出典 |
|---|---|---|
| 通信路 | Python で環境をラップする。ゲームは NLE | [A] https://github.com/balrog-ai/BALROG/tree/b7afe79e3e4265811cfa985ed7c95c4d1a11e3f5 |
| 観測 | VLM でないモデルには `prompt_mode="hybrid"` を使う。中身は、text_glyphs による方角つきの記述、`tty_chars` から作った ASCII マップ、カーソル座標。language モードでは、長期側に message、glyphs、cursor を、短期側に blstats と inventory を置く | [A] https://github.com/balrog-ai/BALROG/blob/b7afe79e3e4265811cfa985ed7c95c4d1a11e3f5/balrog/environments/nle/base.py#L25-L28 、https://github.com/balrog-ai/BALROG/blob/b7afe79e3e4265811cfa985ed7c95c4d1a11e3f5/balrog/environments/nle/base.py#L161-L205 |
| 行動 | 言語で表した行動空間。**無効な行動は `default_action` に置き換え**、`failed_candidates` に記録する。`--More--` は `auto_more.py` が自動で送る | [A] https://github.com/balrog-ai/BALROG/blob/b7afe79e3e4265811cfa985ed7c95c4d1a11e3f5/balrog/environments/env_wrapper.py#L82-L89 、https://github.com/balrog-ai/BALROG/blob/b7afe79e3e4265811cfa985ed7c95c4d1a11e3f5/balrog/environments/nle/auto_more.py |
| 記憶 | `max_text_history: 16` | [A] https://github.com/balrog-ai/BALROG/blob/b7afe79e3e4265811cfa985ed7c95c4d1a11e3f5/balrog/config/config.yaml#L4 |
| 評価 | NetHack の進行度。o1-preview で 1.5%。VLM に画像を与えると、テキストのみより成績が下がった。**knowing-doing gap**：ダンジョンから出ると死ぬと知っているのに出てしまう | [C] https://arxiv.org/abs/2411.13543 （WebFetch による要約） |
| 失敗モード | 知識と行動の乖離。長期の計画が立てられない | [C] |

### 1.6 NLE とその言語ラッパー

| 項目 | 内容 | 出典 |
|---|---|---|
| NLE の観測キー | `glyphs, chars, colors, specials, blstats, message, inv_*, tty_chars, tty_colors, tty_cursor, screen_descriptions` | [B] https://github.com/NetHack-LE/nle （`nle/env/base.py`） |
| nle-language-wrapper | text_glyphs（例："tame kitten adjacent northeast"）、text_blstats、text_message（メニューの内容も含む） | [B] https://github.com/ngoodger/nle-language-wrapper |

**[推論]** CoQ で ASCII マップに当たるものは `ConsoleLib.Console/ScreenBuffer.cs:15`（`public class ScreenBuffer`）である可能性がある。ただしこれは描画用のバッファで、エンティティや地形の意味づけを含むかどうかは確認していない。

### 1.7 NetPlay（NetHack、GPT-4）

| 軸 | 内容 | 出典 |
|---|---|---|
| 観測 | 部屋と通路に ID をつけ、歩数での距離を示す。モンスターは近い／遠いで分ける | [B] https://arxiv.org/abs/2403.00690 |
| 行動 | 約 20 のスキル（マクロ行動）。イベントが起きたときやメニューが出たときにスキルを**中断**する | [B] https://github.com/CommanderCero/NetPlay |
| 記憶 | 500 トークン | [B] |
| 評価 | 指導なしのスコアは 284.85。ルールベースの autoascend は 11341.94。まともに動いたのは GPT-4 だけだった | [C] |
| 失敗モード | メニュー（5 件中 1 件）、店主とのキャンセルの繰り返し、メニューを閉じ忘れる、杖を自分に向けて使う | [C] |

### 1.8 dcss-ai（Dungeon Crawl Stone Soup）

CoQ に最も近いジャンル（ターン制ローグライク、メニューあり）で、コードまで読めた事例である。

| 軸 | 内容 | 出典 |
|---|---|---|
| 通信路 | webtiles への WebSocket | [B] https://github.com/nkhoit/dcss-ai |
| 観測 | `get_state_text()` が `=== DCSS State ===`、ステータス、直近 5 件のメッセージを組み立てる | [A] https://github.com/nkhoit/dcss-ai/blob/1d5c818ce7380ae1872f9a782a9be39186dda739/dcss_ai/game/state.py#L421-L423 |
| 行動 | 39 ツール（`get_landmarks, write_note, examine, move, navigate, auto_explore, auto_fight, rest, respond, read_ui, select_menu_item, dismiss, narrate` など）。**ターンを消費しないツール（`FREE_ACTIONS`）とターンを消費するツールを分けている。** 後者の結果には `[Game State]` を自動で付け、場所が変わったときは `[Knowledge]` も付ける | [A] https://github.com/nkhoit/dcss-ai/blob/1d5c818ce7380ae1872f9a782a9be39186dda739/dcss_ai/tools.py#L215-L219 、https://github.com/nkhoit/dcss-ai/blob/1d5c818ce7380ae1872f9a782a9be39186dda739/dcss_ai/tools.py#L745-L775 |
| 記憶 | 1 ゲームを 1 セッションで扱う。`learnings.md`、信頼度つきの知識 JSON、`deaths.jsonl` | [B] README |
| 評価・失敗 | 公式の評価はない | — |

### 1.9 CDDAi（Cataclysm: DDA）

ASCII 端末の出力と、JSON のセーブデータの解析を組み合わせる小規模なプロジェクト [B]（https://github.com/rekon307/CDDAi）。「セーブファイルを状態のソースにする」という選択肢の実例になる。

### 1.10 Claude Plays Pokémon

| 軸 | 内容 | 出典 |
|---|---|---|
| 観測 | スクリーンショットと、RAM から読んだ状態 | [B] https://github.com/davidhershey/ClaudePlaysPokemonStarter |
| 行動 | `use_emulator`, `update_knowledge_base`, `navigator` | [B] 同上 |
| 記憶 | 知識ベースと、約 30 アクションごとの要約。Sonnet 3.5 は記録を文字起こしのように書いたが、Opus 4.6 はメモリをディレクトリに整理した | [B] https://claude.com/blog/harnessing-claudes-intelligence |
| 失敗モード | オツキミやまで行き詰まった。**画面を正しく読めないこと**が主な原因として挙がっている。作者はポケモン固有の知識をハーネスから取り除いている | [C] https://arstechnica.com/ai/2025/03/why-anthropics-claude-still-hasnt-beaten-pokemon/ 、https://michaelyliu6.github.io/posts/claude-plays-pokemon/ 、https://home.mlops.community/public/videos/claude-plays-pokemon-a-conversation-with-the-creator 、https://www.wired.com/story/anthropic-new-model-launch-claude-4/ |

### 1.11 Gemini Plays Pokémon（GPP）と Continual Harness

| 軸 | 内容 | 出典 |
|---|---|---|
| 観測 | RAM から抽出したテキストと、フォグ・オブ・ウォーつきの JSON ミニマップ（**見たタイルしか知らない**）。到達可能な未探索タイルの一覧。スクリーンショットも併用していたと理解しているが、画像がどれだけ寄与したかは本調査で確認していない | [B] https://blog.jcz.dev/the-making-of-gemini-plays-pokemon ／ https://blog.jcz.dev/gemini-3-pro-vs-25-pro-in-pokemon-crystal |
| 行動 | Pathfinder と岩押し用のサブエージェント。方向ボタンとアクションボタンを 1 ターンに混ぜない。後期には `define_agent`／`run_code` というメタツールを持つ | [B] 同上 |
| 記憶 | 100 ターンごとに要約する。目標は 3 層。批評役（critic）を置く。知識グラフは廃止した | [B] |
| 失敗モード | 約 10 万トークンを超えるとループする。裏庭で 8 時間ループした。PP を幻覚した。別のゲームにある「おいしいみず（TEA）」を探した。パニック状態になった。探索に固執した | [B]／[C] https://www.lesswrong.com/posts/7mqp8uRnnPdbBzJZE/is-gemini-now-better-than-claude-at-pokemon 、https://www.dbreunig.com/2025/06/17/an-agentic-case-study-playing-pok%C3%A9mon-with-gemini.html |
| Continual Harness | Karten らによる Pokémon エージェントのハーネス研究。「ハーネス自体を継続的に改善する」という方向性はタイトルからの **[推論]** で、本文は精読していない | [C] https://arxiv.org/html/2605.09998 |

### 1.12 CoQ 固有の先行事例

#### 1.12.1 qud-accessibility（BlindGuyNW）

CoQ の UI を、画像を使わずに読み上げるために作られた mod。llm-of-qud の知覚層とほぼ同じ問題、つまり「画面の代わりに何を読むか」を、別の目的で既に解いている。commit `a3ebd92498f2c8546a5a125ec6dd25e0ed1befc2` を読んだ [A]（https://github.com/BlindGuyNW/qud-accessibility 、固定基点 https://github.com/BlindGuyNW/qud-accessibility/blob/a3ebd92498f2c8546a5a125ec6dd25e0ed1befc2/ ）。

- **仕組み**：Harmony の prefix／postfix で UI メソッドに割り込み、ゲームに同梱されている `WindowsTTS` で読み上げる。
  - `src/Speech.cs:26-29` は、`WindowsTTS.instance` がなければ `UAP_AudioQueue.InitializeWindowsTTS()` と同じ手順で作る。
  - `Speech.cs:229` などで `WindowsTTS.Speak` を呼ぶ。
- **テキストの整形**：`Speech.Clean` は `ConsoleLib.Console.ColorUtility.StripFormatting` で色マークアップを除き、コマンド名を解決し、サニタイズする（https://github.com/BlindGuyNW/qud-accessibility/blob/a3ebd92498f2c8546a5a125ec6dd25e0ed1befc2/src/Speech.cs#L147-L160 ）。
  - 表示名の取得には `GetDisplayName(Stripped: true)` を使っている（`src/ScreenReader.cs:267` など）。
  - 同じ文を繰り返し読まないように `SayIfNew` で重複を除く（`src/ChargenPatches.cs:145`、`:151` のコメントには「Update() は毎フレーム呼ばれる」とある）。
- **補助機能**：
  - F3/F4 で情報ブロックを巡回する（Stats、Condition、Location、直近 5 件のメッセージ、Abilities）。`src/ScreenReader.cs:19`、`:230-233`。
  - `NearbyScanner` は周囲のものをカテゴリ別に一覧し、距離と方角を読み上げ、対象まで歩く（https://github.com/BlindGuyNW/qud-accessibility/blob/a3ebd92498f2c8546a5a125ec6dd25e0ed1befc2/src/NearbyScanner.cs#L17 、`:120`、`:152-154`）。

| 軸 | 内容 |
|---|---|
| 通信路 | プロセス内の Harmony フックから TTS へ直接渡す。外部とのプロセス間通信（IPC）はない |
| 観測 | フックで捕まえた UI テキスト（ポップアップ、スクローラーの選択項目、交易、書物、ステータス画面など）と、`NearbyScanner` による周囲の一覧（カテゴリ、距離、方角） |
| 行動 | 人間のキーボード操作が主体。mod 側の行動は `WalkToCurrentResult`（スキャン結果まで歩く）程度 |
| 記憶・自己改善 | なし |
| 評価 | なし（人間向けのアクセシビリティ mod） |
| 失敗モード・欠落 | `ConversationUI` 専用のパッチが見つからない。TTS は Windows 側の実装に依存しているとみられる **[推論]**（1.12.3 節）。Harmony に依存するため Apple Silicon 上のリスクを負う **[推論]**（1.12.4 節） |

フックの一覧と、stable 版の逆コンパイルでの対応箇所（「クラス」とある行はクラス定義の位置で、メソッドの行は未確認）：

| mod 側のパッチ | 対象 | 逆コンパイルでの定義 |
|---|---|---|
| [PopupPatches.cs:21](https://github.com/BlindGuyNW/qud-accessibility/blob/a3ebd92498f2c8546a5a125ec6dd25e0ed1befc2/src/PopupPatches.cs#L21) | `Popup.ShowYesNoCancel` | `XRL.UI/Popup.cs:2365` |
| `src/PopupPatches.cs:44` | `PopupMessage.ShowPopup` | `Qud.UI/PopupMessage.cs:721` |
| `src/GameplayPatches.cs:29,36` | `Look.ShowLooker` | `XRL.UI/Look.cs:405` |
| [GameplayPatches.cs:49](https://github.com/BlindGuyNW/qud-accessibility/blob/a3ebd92498f2c8546a5a125ec6dd25e0ed1befc2/src/GameplayPatches.cs#L49) | `XRLCore.PlayerTurn` | `XRL.Core/XRLCore.cs:690` |
| `src/ScrollerPatches.cs:61` | `FrameworkScroller.UpdateSelection` | `XRL.UI.Framework/FrameworkScroller.cs:443` |
| `src/TradePatches.cs:34,50,78` | `TradeScreen.showScreen/UpdateTotals/Update` | `Qud.UI/TradeScreen.cs:18`（クラス） |
| `src/TerminalPatches.cs:15` | `CyberneticsTerminalScreen.Show` | `Qud.UI/CyberneticsTerminalScreen.cs:14`（クラス） |
| `src/BookPatches.cs:29,39,50` | `BookScreen.showScreen`（2 種）、`UpdateViewFromData` | `Qud.UI/BookScreen.cs:15`（クラス） |
| `src/CharacterSheetPatches.cs:20` | `StatusScreensScreen.UpdateActiveScreen` | `Qud.UI/StatusScreensScreen.cs:15`（クラス） |
| `src/ChargenPatches.cs:28,121,155,176,202` | キャラクター作成（`EmbarkBuilderModuleWindowDescriptor.show`、`HorizontalScroller.UpdateSelection` ほか） | `XRL.CharacterBuilds/EmbarkBuilderModuleWindowDescriptor.cs:8`、`XRL.UI.Framework/HorizontalScroller.cs:10`（`: FrameworkScroller`） |
| `src/AbilityBarPatches.cs:27,35` | `AbilityBar.MoveSelection/MovePage` | `Qud.UI/AbilityBar.cs:20`（クラス） |
| `src/TutorialPatches.cs:30-67` | `TutorialManager` | `TutorialManager.cs:18`（クラス） |
| `src/ScrollerPatches.cs:32,115,153,160,188` | `MainMenu.Show`、`KeybindsScreen.Show`、`AbilityManagerScreen`、`SaveManagement.Show` | `Qud.UI/MainMenu.cs:18`、`Qud.UI/KeybindsScreen.cs:19`、`Qud.UI/AbilityManagerScreen.cs:21`、`Qud.UI/SaveManagement.cs:15`（いずれもクラス） |
| その他（`src/GameSummaryPatches.cs:15` ほか） | `GameSummaryScreen.Show`、`OptionsScreen`、`HelpScreen`、`ModManagerUI`、`ModToolkit`、`WorldCreationProgress.NextStep`、`WorldGenerationScreen` | `Qud.UI/GameSummaryScreen.cs:18`、`Qud.UI/OptionsScreen.cs:17`、`Qud.UI/HelpScreen.cs:15`、`Qud.UI/ModManagerUI.cs:14`、`Qud.UI/ModToolkit.cs:16`、`XRL.UI/WorldCreationProgress.cs:10`、`Qud.UI/WorldGenerationScreen.cs:17`（いずれもクラス） |

ターゲット選択は `ScreenReader.cs:166-179`（`InPickTargetMode`、`PickTarget.PickStyle`）で扱っている。対応するゲーム側は `XRL.UI/PickTarget.cs:378`（`ShowPicker`）と `XRL.UI/PickDirection.cs:12`。

**会話 UI（`ConversationUI`）専用のパッチは見つからなかった**（`grep -rln Conversation src` の結果は 0 件）。grep による否定結果なので、汎用スクローラー経由で会話が読み上げられている可能性は残る。

**[推論]** CoQ で知覚すべき UI の範囲について、このフック一覧は実証済みのチェックリストとして使える。一方、Harmony を大量に使うことは Apple Silicon 上のリスク（1.12.4 節）と引き換えになる。

#### 1.12.2 Archipelago Randomizer mod（lonesurv1vor）

CoQ の mod から外部のネットワークに接続している実例である [A]（commit `e893f023603df847e3e5e73e3c4620e77178e08a`）。

| 軸 | 内容 |
|---|---|
| 通信路 | Archipelago サーバーへのネットワーク接続（外部 DLL の MultiClient 経由）。受信したイベントは `ConcurrentQueue` でゲーム側へ渡す |
| 観測・行動・記憶・評価 | 対象外（LLM エージェントではなく、ランダマイザー） |
| 失敗モード | キャラクター作成時に接続が失敗するとゲームがハングする |

- **外部 DLL の読み込み**：`Assembly.LoadFrom` で `Archipelago.MultiClient.Net.dll` を読み込み、リフレクションで呼び出す（https://github.com/lonesurv1vor/CavesOfQudArchipelagoRandomizer/blob/e893f023603df847e3e5e73e3c4620e77178e08a/src/APSession.cs#L10 、https://github.com/lonesurv1vor/CavesOfQudArchipelagoRandomizer/blob/e893f023603df847e3e5e73e3c4620e77178e08a/src/APStaticData.cs#L34 ）。
- **スレッド間の受け渡し**：ネットワーク側のイベントは `ConcurrentQueue`（https://github.com/lonesurv1vor/CavesOfQudArchipelagoRandomizer/blob/e893f023603df847e3e5e73e3c4620e77178e08a/src/APEvents.cs#L9-L10 ）に積まれ、ゲーム側が取り出す。
- **既知の問題**：キャラクター作成時に接続が失敗すると、ゲームがハングする [B]（README／issue）。
- 出典：https://github.com/lonesurv1vor/CavesOfQudArchipelagoRandomizer

#### 1.12.3 公式のアクセシビリティ基盤（UAP）とスクリーンリーダー対応

CoQ には、Unity 向けのアクセシビリティプラグイン UAP（UI Accessibility Plugin）が同梱されている。

- `UAP_AccessibilityManager.cs:10`（クラス）、`:185`（`private static bool m_IsEnabled = false;`）、`:1430`（`EnableAccessibility`）、`:2955`（`Say`）。
- `UAP_AudioQueue.cs:169`（`InitializeWindowsTTS`）。
- `MacOSTTS.cs:8` と `WindowsTTS.cs:3` は `MonoBehaviour` として存在する。

ただし、**XRL／Qud のゲームコードから UAP や WindowsTTS を呼んでいる箇所は、stable 版にも decomp-new にも grep では見つからなかった**。逆コンパイルには UAP のサンプルスクリプト（gameplay.cs、mainmenu.cs など）も含まれているが、ゲーム本体のコードからの呼び出しは見つかっていない。

この否定結果を「公式のスクリーンリーダー対応はない」とまでは言えない。言えるのは「公式対応の証拠は見つからなかった」までである。コミュニティの報告もこれと矛盾しない：Steam 議論 https://steamcommunity.com/app/333640/discussions/0/4209245440575246500/ （スクリーンリーダーで読めるテキスト出力がない）、旧コンソール版についての開発者のコメント https://www.reddit.com/r/roguelikes/comments/9n1zoe/ 。

**[推論]** macOS 版の逆コンパイルでは `WindowsTTS` の中身が空に近い。しかし qud-accessibility は `WindowsTTS.Speak` を呼んでいるので、Windows 版のアセンブリでは実装が異なると考えられる。

#### 1.12.4 CoQ の mod フックと、Apple Silicon 上の Harmony

**Harmony を使わずに済むフック** [A]：

| フック | 逆コンパイルでの定義 |
|---|---|
| `IGameSystem` | `XRL/IGameSystem.cs:12` |
| `IPlayerSystem : IGameSystem` | `XRL/IPlayerSystem.cs:7`。`RegisterPlayer` は L38、`AfterPlayerBodyChangeEvent` は L12/L42 |
| `IScribedSystem : IGameSystem` | `XRL/IScribedSystem.cs:7` |
| `WishCommand`／`HasWishCommand` 属性 | `XRL.Wish/WishCommand.cs:6`、`XRL.Wish/HasWishCommand.cs:6` |
| `PlayerMutator` 属性 | `XRL/PlayerMutator.cs:6` |
| `CallAfterGameLoaded`／`HasCallAfterGameLoaded` 属性 | `XRL/CallAfterGameLoadedAttribute.cs:6`、`XRL/HasCallAfterGameLoadedAttribute.cs:6` |

**Harmony 本体の扱い** [A]：

- ゲームは `new Harmony("com.freeholdgames.cavesofqud")` を持つ（`XRL/ModManager.cs:70`）。
- 各 mod には `ApplyHarmonyPatches` → `Harmony.PatchAll(Assembly)` が適用される（`XRL/ModInfo.cs:819`、`:845-853`）。
- mod のコードは Roslyn によってメモリ上でコンパイルされる（`XRL/ModManager.cs:116-135`）。

**スレッド** [A]：

- `GameManager` は `uiQueue` と `gameQueue`（どちらも `ThreadTaskQueue`）を持つ（`GameManager.cs:148`、`:150`）。
- `gameThreadSynchronizationContext` を持ち（`:174`）、`runPlayerTurnOnUIThread` という切り替えもある（`:372`、`:603`）。
- **[推論]** RimBridge が「Unity のメインスレッドへ渡す」のに対して、CoQ では「ゲームスレッドのキューへ渡す」のが対応する操作になる可能性が高い。

**公式 wiki の方針** [B]（scratchpad に保存した raw ページ）：

- Modding:Harmony：Harmony はゲーム本体に含まれるが、最後の手段として扱う。postfix を優先する。フックが必要なら開発者に依頼する。
- Modding:Scripting：C# 9 で書き、実行時にコンパイルされる。
- Modding:Wishes：`[HasWishCommand]` と `[WishCommand(Command=...)]` を使う。
- Serialization：207.69 以降は IScribed* を使う。Best practices は IGameSystem より IScribed* を推奨している。
- 補足：「More Modding Goodies」（https://steamcommunity.com/workshop/filedetails/?id=3403942187）。

**Apple Silicon 上の Harmony**：

- 同梱されている `0Harmony.dll` は 2.2.2.0 だった（`CoQ.app/Contents/Resources/Data/Managed/0Harmony.dll` から UTF-16 文字列を抽出して確認）[A]。
- arm64／Apple Silicon への対応は Harmony 2.4.0 からである [B]：https://github.com/pardeike/Harmony/releases
- 過去には "mprotect returned EACCES" の問題が報告されている：https://github.com/pardeike/Harmony/issues/424 （2023-06-17 にクローズ）。
- CoQ の Harmony パッチが Apple Silicon でクラッシュするという報告もある [C]：https://www.reddit.com/r/cavesofqud/comments/1e10jk4/
- QudJP（ToaruPen）は、Rosetta で起動するラッパーと、CoQ 1.0.5 向けの任意の Harmony 2.4.2 差し替えを提供している。Windows では起動時のパッチ処理が 72.6 秒から 9.4 秒に短縮されたと報告している [C]。
  - https://steamcommunity.com/sharedfiles/filedetails/?id=3718988020
  - https://steamcommunity.com/workshop/filedetails/discussion/3718988020/572669660098532087/
- 既存の llm-of-qud v1 のアーキテクチャ文書（`archives/llm-of-qud-v1/docs/architecture-v5.md`）は、IGameSystem を主体にしつつ、`AutoAct.TryToMove` に Harmony の prefix を当てる方針を採っていた [A]。

---

## 2. 探して見つからなかったもの（否定結果）

| 探したもの | 方法 | 結果 |
|---|---|---|
| Brogue の LLM エージェント | 検索："Brogue LLM agent GPT Claude plays Brogue github" | 該当なし |
| Cogmind／ADOM の LLM エージェント | 検索："Cogmind LLM plays OR ADOM LLM agent plays" | 該当なし |
| qud-accessibility の `ConversationUI` パッチ | `grep -rln Conversation src` | 0 件 |
| CoQ の UAP／TTS の呼び出し元 | stable 版と decomp-new の XRL／Qud コードを grep | 0 件 |

いずれも検索に基づく否定結果で、存在しないことの証明ではない。

---

## 3. 横断的な教訓と CoQ への対応

### 3.1 モーダル UI は、ターン制でも問題として残る

CoQ はターン制なので、RimWorld 系の事例に多い「考えている間にゲームが進む」問題の大半は消える。RimMolt の Pause Hook、rimagent の起床ポリシー、rimworld-ai-manager の停止制御は、どれもリアルタイムの時間を相手にした工夫であり、そのままでは CoQ に移す価値が小さい [推論]。

消えない問題もある。**モーダル UI が見えない形で進行を止める**ことである。

- RimMolt の RM-006（強制停止ダイアログが時間送りを塞ぐ）と RM-012（閉じると停止が解除される）
- rimagent の欠陥 (iii)（モーダルダイアログがゲームを見えない形で止めていた）
- rimworld-ai-manager の「最初の交易商人がゲームを永久に停止させた」
- NetPlay の「メニューを閉じ忘れる」

これらはどれも、ゲームの時間の扱いとは無関係に起きている。原因は、UI の状態がエージェントに観測されていないことにある。

CoQ で該当しそうな入り口（[A] 定義位置、影響範囲は [推論]）：

| 種類 | 入り口 |
|---|---|
| メッセージ／確認 | `XRL.UI/Popup.cs:658`（`Show`）、`:639`（`ShowAsync`）、`:801`（`WaitNewPopupMessage`）、`:2365`（`ShowYesNoCancel`） |
| 選択肢の一覧 | `XRL.UI/Popup.cs:1645`（`ShowOptionList`）、`:1650`（`PickOption`） |
| 新 UI のポップアップ | `Qud.UI/PopupMessage.cs:721`（`ShowPopup`） |
| 会話 | `XRL.UI/ConversationUI.cs:15`。静的状態として `CurrentNode`（`:149`）、`CurrentChoices`（`:153`）、`SelectedChoice`（`:157`）を持つ |
| 方向・対象の選択 | `XRL.UI/PickDirection.cs:12`、`XRL.UI/PickTarget.cs:378`、`XRL.UI/Look.cs:405` |
| 交易 | `Qud.UI/TradeScreen.cs:18` |

**[推論]** 「今どのモーダルが開いていて、どんな選択肢があるか」を毎回の観測の先頭近くに置くこと（rimagent の知覚順の (3)）は、CoQ でもそのまま役に立つ。会話は選択肢の列挙と選択の 2 段階（RM-004）と相性がよく、`CurrentChoices` のような静的状態があるなら、読み上げに頼らず直接列挙できる可能性がある。

### 3.2 ターン消費とマクロ行動

dcss-ai は、ターンを消費しないツール（`FREE_ACTIONS`）と、消費するツールを明確に分けている（https://github.com/nkhoit/dcss-ai/blob/1d5c818ce7380ae1872f9a782a9be39186dda739/dcss_ai/tools.py#L215-L219 ）。後者の結果には、最新の状態を自動で付ける（https://github.com/nkhoit/dcss-ai/blob/1d5c818ce7380ae1872f9a782a9be39186dda739/dcss_ai/tools.py#L745-L775 ）。LLM が「行動したのに状態を読み直さない」ことを、構造の側で防いでいる。

NetPlay はマクロ行動（スキル）を使い、イベントやメニューの出現でそれを中断する。CoQ には `AutoAct`（`XRL.World.Capabilities/AutoAct.cs:13`、`TryToMove` は `:815` と `:963`）があり、自動探索や自動移動が既に中断条件を持っている [推論]。rimagent の Steward や rimworld-ai-manager のデーモンが示したのは、定型の仕事を LLM の外に出すと、LLM の呼び出し回数と誤りが減るということだった（`ui_set_work` が 307 回から 2 回）。CoQ でいえば、ゲーム自身の自動行動に任せる範囲を広げることがこれに当たる [推論]。

### 3.3 観測の表現：テキスト、ASCII マップ、オブジェクト

- **テキストの優位性**：BALROG の結果は、VLM に画像を与えると成績が下がるというものだった [C]。Claude Plays Pokémon の主な失敗も、画面の読み違いだった [C]。どちらも「画像を使わない」という方針と整合する。ただし RimMolt のクリア事例は画像を併用していたので、この方針の根拠には使えない（1.1.2 節）。
- **ASCII マップの位置づけ**：BALROG の hybrid モードは、方角つきの文章と ASCII マップを併用する [A]。rimagent も、グリッドは要求されたときだけ出し、通常はオブジェクトとして渡している [B]。**[推論]** CoQ では、「近くにいる敵対的な生物、北東 3 マス」のような方角つきの記述を常に渡し、グリッドは戦闘や地形の判断が必要なときだけ出す、という 2 層の構成が選択肢になる。
- **変化を先に見せる**：rimagent の「追跡値 → 差分 → ダイアログ → イベント → オブジェクト → 生データ」という順は、決定を変えやすい情報ほど前に置く設計である。
- **ゲーム内テキストの整形**：CoQ のメッセージは色マークアップを含む。qud-accessibility は `ColorUtility.StripFormatting` で除いている（`src/Speech.cs:152`）。メッセージの取得元の候補は `XRL.Messages/MessageQueue.cs:14`、`:106`（`AddPlayerMessage`）、`:138`（`Add`）である。

### 3.4 行動文法とエラーへの応答

- **場所の文法**：rimagent は `bedroom2:NW` や `Campfire39256 +E2 +N1` のように、名前で場所を指定させる。座標を直接扱わせないのは、LLM が座標を間違えやすいからである。rimworld-ai-manager でも座標系の食い違い（(x,y) と (x,z)）が欠陥として記録されている。
- **成功の戻り値を信じない**：RM-022（発射ギズモが成功を返しても、ワールドターゲティングは始まっていない）と、rimagent の「doc string が嘘をついた」は同じ構造をしている。成功の戻り値や説明文と、実際の状態が食い違う。**[推論]** 行動の結果は、戻り値ではなく、行動後の状態として返すのがよい。
- **無効な行動の扱い**：BALROG は無効な行動を既定の行動に置き換えて記録する [A]。rimagent は、モデルが JSON を文字列で渡したり引数名を別名で呼んだりするのを欠陥として挙げている [B]。スキーマに寛容な受け口を作るか、明確にエラーを返すかは、選択肢として両方ある。

### 3.5 記憶と学習

- **外部ファイルに書かせる**：RimMolt の配信者の運用では、学習を外部ファイルに保存しないと残らなかった [B]。文脈を圧縮すると戦略を忘れた [B]。GPP も約 10 万トークンを超えるとループした [B]。
- **起動時に読む範囲を絞る**：`RIMWORLD_LEARNING.md` は上位の節だけを起動時に読み、残りを検索させる [B]。rimagent は skills を BM25 で選ぶ [B]。
- **振り返りを機械的な修正で終える**：rimworld-ai-manager の POSTMORTEM 規則（「X を覚えておく」は失敗扱い）[B]。rimagent の watchdog（エラーが閾値を超えたときだけ動き、パスを限定し、コミット前に検証する）[B]。
- **ローグライクの長期進行**：CoQ はキャラクターの成長、クエスト、会話の履歴が長く続く。1 ゲーム 1 セッションの dcss-ai や、`deaths.jsonl` のような死亡記録は、周回をまたいで学習するための形として参考になる [推論]。

### 3.6 通信路とスレッド

事例ごとの通信路：

| 事例 | 通信路 |
|---|---|
| RimMolt | ゲーム内の MCP サーバー（HTTP） |
| rimagent | HTTP と独自の RPC |
| RIMAPI | REST と SSE |
| Lib.GAB | TCP とトークン認証 |
| dcss-ai | WebSocket |

どの事例も、ネットワークを受けるスレッドとゲームを進めるスレッドを分け、キューで受け渡している。RimBridge は `Root.Update` の postfix でキューを消化し、Archipelago mod は `ConcurrentQueue` を使う。

CoQ では、`GameManager` が `uiQueue` と `gameQueue` を持つ（`GameManager.cs:148`、`:150`）。**[推論]** 「どのスレッドで状態を読み、どのスレッドで行動を実行するか」を最初に決める必要がある。

外部 DLL（MCP の SDK など）の取り込みは、Roslyn による実行時コンパイル（`XRL/ModManager.cs:116-135`）の制約を受ける可能性がある。Archipelago mod の `Assembly.LoadFrom` は、その回避策の実例である [A]。

### 3.7 プラットフォームのリスク

- 同梱の Harmony 2.2.2.0 は、arm64 に対応した 2.4.0 より古い [A]/[B]。
- Apple Silicon でのクラッシュ報告がある [C]。
- QudJP は Rosetta と Harmony の差し替えで回避している [C]。
- **[推論]** Harmony への依存を減らせば、このリスクを避けられる。フックは IGameSystem、wish、イベントなど公式のものを優先し、Harmony は最後の手段にする。この方針は公式 wiki の推奨とも一致する。

---

## 4. 取り入れる価値のある設計パターン（選択肢）

| # | パターン | 根拠 | CoQ での適用先の例（[推論]） |
|---|---|---|---|
| P1 | 観測の先頭に「開いているモーダルと、その選択肢」を置く | rimagent の知覚順 (3)、欠陥 (iii)、RM-006/012 | `Popup` 系と `ConversationUI.CurrentChoices` |
| P2 | 選択は「列挙 → ラベルかインデックスで選ぶ」の 2 段階にする | RM-004、NetPlay のメニュー失敗 | 会話、`PickOption`、インタラクションメニュー |
| P3 | ターンを消費しない行動と消費する行動を分け、後者には最新の状態を自動で付ける | dcss-ai `tools.py#L215-L219`、`#L745-L775` | 移動、攻撃、アイテム使用の結果 |
| P4 | 行動の結果は、戻り値ではなく行動後の状態として返す | RM-022、rimagent の doc string 問題 | `AutoAct` や `PickTarget` 待ちの検出 |
| P5 | 変化の大きい情報から順に並べる（トレンド、差分、イベント） | rimagent PAPER.md#L88-L96 | HP、空腹、敵の出現、メッセージの差分 |
| P6 | 場所は名前と相対表現で指定する（アンカー、方角） | rimagent PAPER.md#L100、NLE 言語ラッパー | 「北東 3 マス」、ゾーン名、ランドマーク |
| P7 | 定型の仕事は LLM の外（ゲームの自動行動や常駐のデーモン）に任せる | Steward の効果（`ui_set_work` が 307 回から 2 回）、rimworld-ai-manager | `AutoAct` の自動探索、休息、自動戦闘 |
| P8 | 危機への対応はエッジトリガーにし、1 回だけ止めてエスカレーションする | `colony_daemon.py#L263-L282` | 敵の出現、HP の急減 |
| P9 | 学習ファイルは「変更しない規約」と「更新する学習」に分け、起動時に読む範囲を絞る | `RIMWORLD_LEARNING.md` の構造 | 周回をまたぐ攻略メモ |
| P10 | 振り返りは機械的な修正（センサー、ルール、閾値）で終える | rimworld-ai-manager POSTMORTEM | 死因の分析からツールや watcher を直す |
| P11 | watchdog は閾値と許可パスで制限し、コミット前に検証する | rimagent README | エージェントが自分の道具を改修する場合 |
| P12 | 色マークアップを除き、重複を除いてからテキストを渡す | qud-accessibility `Speech.cs:147-160`、`SayIfNew` | メッセージログ、ポップアップ本文 |
| P13 | ネットワークとゲームのスレッドを分け、キューで受け渡す | RimBridge、Archipelago `APEvents.cs:9-10` | `GameManager.gameQueue` |
| P14 | ゲームの公式な知識源（wiki、逆コンパイル）を検索できるようにする | rimagent PAPER.md#L125 | CoQ の wiki と逆コンパイル |

---

## 5. 避けるべきパターン（アンチパターン）

| # | アンチパターン | 根拠 |
|---|---|---|
| A1 | UI の状態を観測に含めず、モーダルで進行が止まっても気づかない | rimagent 欠陥 (iii)、RM-006、rimworld-ai-manager の交易商人 |
| A2 | 成功の戻り値や doc string を、実際の状態の確認なしに信じる | RM-022、rimagent の doc string 問題 |
| A3 | `except:pass` で失敗を握りつぶす | rimworld-ai-manager `REGRESSION_CHECKLIST` |
| A4 | フィルタで重要な対象（動物、火災など）を観測から落とす | 同上（manhunter が見えなかった、火災が監視されていなかった） |
| A5 | 生の座標を LLM に扱わせ、座標系を統一しない | `SPEC_FINDINGS`（(x,y) と (x,z) の食い違い） |
| A6 | 学習を文脈の中だけに持ち、圧縮で失う | RimMolt 配信者の記録、GPP の 10 万トークン超でのループ |
| A7 | 「X を覚えておく」で振り返りを終える | rimworld-ai-manager POSTMORTEM |
| A8 | LLM に作業を細かく設定させ続ける（Steward なし） | rimagent の `ui_set_work` 307 回 |
| A9 | 外部の入力（視聴者のコメントなど）をそのまま指示として扱う | RimMolt 配信者が指摘したプロンプトインジェクションの危険 |
| A10 | ゲームに固有の知識を持たない小さなローカルモデルにツールを使わせる | RimMolt 議論（8GB GPU では使えない）、NetPlay（GPT-4 のみ） |

---

## 6. 未解決の問い

1. `ConversationUI` の静的状態（`CurrentNode`、`CurrentChoices`）を、会話中に安全に読み書きできるか。新 UI 側の会話画面との関係はどうなっているか。
2. `GameManager` の `uiQueue`／`gameQueue` のどちらで状態を読み、行動を実行すべきか。`runPlayerTurnOnUIThread` がどう影響するか。
3. MCP サーバーを CoQ のプロセス内で動かせるか。Roslyn による実行時コンパイルのもとで、外部 DLL（HTTP サーバー、MCP SDK）をどう取り込むか。
4. Apple Silicon 上で、Harmony を使わずに必要なフックをどこまで賄えるか（IGameSystem、wish、イベント）。
5. `ScreenBuffer` を ASCII マップの元として使えるか。使えるなら、意味づけ（エンティティ、地形）をどう付けるか。
6. `AutoAct` の中断条件を、LLM への起床条件（NetPlay の中断、rimagent の起床ポリシーに当たるもの）として公開できるか。
7. RimMolt 本体の内部構造（ツールの全一覧、スレッド処理、モーダルの扱い）。ソースが非公開なので確認できない。
