# harness — ローカル MCP ゲームハーネス

ゲーム側 mod（WebSocket クライアント）と MCP クライアント（Claude Code など）の間に立つ Python プロセス。1 プロセスで 1 つのゲーム run だけを扱い、判断要求・判断・結果をハッシュ鎖の台帳に記録する。

**現状（2026-09-27）:** Python 196 テストが合格。M1 では Claude Code の Opus 5.5（`claude-opus-5-5`、`xhigh`）が待機を自分で選んで1手を実行した。その後、観測を拡張して R9 の実機監査を通し、モーダル応答用の4つ目のツール `respond` を追加した。本番ブリッジ経由でモーダル18ケース、60秒保持、不正・古い回答の拒否を実機確認した。セーブ／チェックポイントからの再開（`recovery`）と致命的なゲーム障害（`game_fault`）の処理を追加し、C# ブリッジ経由の実死亡・チェックポイント復帰、メニュー退出・再入場も [R6](../probes/R6-lifecycle/README.md) で確認した。致命的障害の細部と再送の組み合わせは偽ゲームの回帰テストで検証している。M1 の結果は [実行記録](../.codex/artifacts/claude-m1-play-20260927.md)、導入と制限は [mod README](../mod/README.md) にある。

2026-09-27 の追加走行では、Claude Code が16判断で200ターン進み、Red Rock 地下1層に到達した。HP 18/18、4種の介入カウンタ0を台帳で照合済み（[記録](../.codex/artifacts/claude-m1-macros-pilot-20260927.md)）。92.3秒の interactive 走行であり、無人1時間・SDK直接走行は未検証。以後、修正・検証はCodex、実プレイだけClaudeという分担にする。

続く30分18秒のクエスト試走では、374判断を受理し、373判断が完了、死亡による1判断の中断とチェックポイント復帰を記録した。完了した結果の前進ターンは合計1,037、復帰で失ったターンは413。Watervineを受注して探索したが、HP 4/25で終了し、クエスト完了には至っていない。運用者によるプレイ中の行動投入は0件で、台帳1,159行を別途照合した。旧modでの走行なので `stray_keys` は未計測。これも interactive 走行であり、M2・M3の達成には数えない（[呼び出し記録と照合結果](../.codex/artifacts/claude-m1-quest-pilot-20260927.md)）。

## 起動と停止

```sh
.venv/bin/python -m harness --run-dir .runtime/RUN [--ws-port 4040] [--mcp-port 8790]
```

- `--run-dir` には、存在しないディレクトリか空のディレクトリを指定する。0700 で作成され、中に次のファイルが排他的に作られる。
  - `token`: MCP 用のベアラートークン（0600）。ハーネス自身が生成する。表示もログ出力もせず、台帳にも入れない。
  - `ledger.jsonl`: 台帳（0600）。
  - `ready.json`: 両方のリスナーと MCP の lifespan が起動した後に作られる（0600）。内容は pid、`ws_url`、`mcp_url`、トークンと台帳のパス。`--episode-control` 有効時は監督用の `episode_control_file` も含む。正常に終了すると削除される。
- 標準出力には、起動時に `{"event":"ready","ws_port":…,"mcp_port":…,"ready_file":…}` を 1 行、終了時に `{"event":"stopped"}` を出す。ポート 0 を指定すると空いているポートが割り当てられ、実際の番号がここに出る。
- SIGINT / SIGTERM で待機中の MCP 呼び出しを起こしてから、両方のリスナーを閉じ、台帳を閉じて終了コード 0 で終わる。
- バインドするのは `127.0.0.1` だけ。

**再起動について:** 前回のゲーム制御の状態（seq・接続・未完了操作）は引き継がない。ハーネスを再起動したら、新しい run ディレクトリを使い、ゲーム側も新しく arm した run（seq 1 から）で接続し直す必要がある。前回の run の続き（seq が 1 でない最初の request）は接続ごと拒否する。プレイヤーの記憶を残す場合は、次節の `--memory-dir` を使う。

## 長期記憶とエピソード

`--memory-dir .runtime/<campaign>/memory` で、同じキャラクター用の記憶を有効にする。ハーネス再起動時は **新しいrunディレクトリと同じmemoryディレクトリ** を指定する。ゲームのseq・未完了操作は復元しない。異なるキャラクターや独立した実験には別のmemoryディレクトリを使う。

| ツール | 内容 |
|---|---|
| `memory_status` | 最新の目標・計画・要約・教訓、現在観測の出典、要約の必要性 |
| `memory_write` | 出典付きのノートを保存。`plan/fact/hypothesis/lesson/summary`を区別し、同じsectionの旧版も保存 |
| `memory_search` | 台帳の公開観測・会話・結果をSQLite FTS5で検索。run・seq・turn・出典ハッシュを返す |
| `memory_read` | 検索結果または現在観測のハッシュから公開記録を読む |
| `memory_checkpoint` | 要約・現在の計画・危険・計画を見直す条件を各1,200文字以内で一括保存する。未変更の長期ノートは保持 |

- ノートはLLMの報告であり、ゲーム上の確定状態ではない。再起動・チェックポイント復帰後の旧ノートには `needs_revalidation` を付ける。教訓や目的も保存するが、所持品・位置・クエストは現在観測と照合する。古いitem IDやmodal tokenは使わない。
- `memory_status.lifecycle` は、ゲームの死亡通知・復帰記録から算出したキャンペーン累計と直近の出典を返す。LLMの要約と矛盾した場合はこちらを使う。通常のセーブ再読込を死亡とは推測しない。
- `fact` の保存には現在観測の出典を必須とし、別run・復帰前の出典だけで現在の事実に書き替えることは拒否する。
- 記憶は `memory.sqlite3` に保存する。元台帳は変更せず、検索索引をハッシュ鎖と照合して更新する。以前の台帳のパスも使うため、runディレクトリを移動・削除しない。異常時は `memory_error` を返す。
- 検索語・返した根拠・呼出し時の台帳ハッシュ・所要時間を `calls` に保存する。観測の地図と内部telemetry、私的な監査oracleは記憶ツールに含めない。同じmemoryディレクトリの同時利用は拒否する。
- 10回の受理済み判断で `episode_due` になる。LLMが短い要約を書き、次の文脈が `memory_status` と現在観測を読む。検索はキーワード方式で、Jev・Wiki接続はまだ含まない。
- 検索は実際の観測・結果・会話を対象とし、判断理由だけの行を除く。直前のresultと次のrequestが同じ観測ならresultへまとめる。`zone` に正確なゾーンID、`current_timeline:true` に現在run・復帰時点を指定して絞り込める。抜粋はHP・位置・脅威と関連メッセージを優先し、全文が必要なら `memory_read` を使う。最大200候補に達した場合は `candidate_limit_reached` を返す。
- `get_state.memory.focus` に現在の計画・危険・見直し条件を添える。いずれもLLMの報告であり、ゲーム状態や強制命令ではない。過去の成功例だけで危険な方針変更をせず、新しい観測を判断理由に残す。旧形式のノートはそのまま読め、旧 `memory_write` も引き続き使える。
- 検索語がクエスト本文や地面の品に含まれる場合も、一致箇所を短い抜粋に残す。選択画面が未解決の間は現在観測の出典を返さず、ノートの書込みを拒否する。ノート更新と呼出し監査は同じトランザクションで確定し、監査の保存失敗時にはノートも保存しない。

先にハーネスを `--memory-dir` と `--episode-control` 付きで起動し、ゲームが判断待ちになってから、明示的に承認されたClaudeプレイを次で実行する。指定時間は新しいエピソードの開始期限で、最後のエピソード完了には最大10分の余裕を置く。モデル指定を省略するとCLIの設定を使う。

```sh
uv run python -m harness.play --run-dir .runtime/<campaign>/run1 \
  --output-dir .runtime/<campaign>/play1 --duration-seconds 3600 \
  --model <approved-model> --effort xhigh
```

運転器は10判断ごとに新しいClaudeプロセスを使い、保存済みの記憶だけを引き継ぐ。最後の判断後の要約・判断数・操作完了を検査し、不一致やエラーなら停止する。Codexや運転器はゲーム行動を補わない。走行後の保存・終了はmodの背景運転手順で行う。Claude Codeによる試験であり、SDK直接呼出しの正式条件とは区別する。

改修後の運転器は最後に短い `memory_checkpoint` を1回保存し、地理・教訓は実質的な新発見があるときだけ更新する。10判断という区切りは維持して比較する。装備変更は `act(action="equip", item="iN")` で行い、必要な部位選択は通常の `respond` を使う。装備の成立は次の `kit.slot` で確認する。`executed:false` は目的が達成されなかったという意味で、無消費を保証しない。移動不成立でも時間・エネルギー消費を検出した場合は `blocked_after_effect` となる。旧台帳の `blocked` でも `turns_elapsed` と観測を確認する。

`harness.play` で自律運転するときは、ハーネスに `--episode-control` を指定する。各文脈には開始seqと最後に許されるactのseqを明示し、監督プロセスがローカルの `episode.json` に10判断分の範囲を発行する。brokerは受理前に検査し、11回目を `episode_complete` で拒否する。記憶を書き直しても枠は増えない。範囲の欠落・破損・別run・終了後は `episode_unavailable` となる。最後の行動の結果待ち・モーダル応答・記憶保存は引き続き使える。

この制御ファイルと排他ロックは監督プロセスだけが操作し、プレイヤーのMCPには公開しない。文脈終了時に範囲を閉じ、実際のseq差と保存状態が正しい場合だけ次の文脈へ枠を発行する。`--episode-control` のない従来の手動MCP操作は変わらないが、`harness.play` はこのフラグのないサーバーで起動を拒否する。

運転器の開始時に未解決モーダルがある場合は起動を拒否する。前のクライアントが受理された行動を、新しい文脈の1判断目として数えないためである。

所持している容器は `act(action="open", item="iN")` で開く。`get` は容器そのものを拾い、`apply` は容器を開かない。`open` の後は中身の選択・操作メニューを通常の `respond` で完了させる。地面の容器を直接開く操作、容器への収納、取引は未対応。

2026-09-27の実機試験では62分13.5秒、270判断、27文脈を完走し、死亡復帰1回・356ターンの喪失を記録した。保存後にゲームとハーネスを再起動し、同じ記憶で追加10判断を完了した。全214テストも合格。死亡要約の誤記を補う修正、ロード時のHP・エネルギー差、停止通知の未到達などの限界は [試験記録](../.codex/artifacts/claude-memory-hour-20260927.md) を参照。

## OBS 用表示画面（overlay v0）

`--overlay-port 8080` を付けると、`http://127.0.0.1:8080/` に読み取り専用の表示画面を出す。ポート0では空きポートを選び、実際の URL を `ready.json` の `overlay_url` に記録する。既定では無効。OBS のブラウザソースへこの URL を指定できる。

HP・場所・直近のメッセージ、最後に受理した判断と処理結果、台帳の先頭ハッシュ64桁を表示する。次の判断要求が届いても最後の判断を保持し、切断後の観測には「古い情報」と表示する。MCPの任意の `rationale`（行動目的を簡潔に書く欄）を台帳から表示する。未指定は「未記録」とし、ゲーム側の結果理由とは別に表示する。上限2000字で、ゲームへ送る命令には含めない。SSE で更新し、ゲーム操作用の入口は持たない。Host / Origin の検査を通す同じ端末からの GET だけを受け付ける。

196テストのうち17件が表示画面の HTTP・SSE・終了処理などを検証する。実際の25判断の台帳を使ったオフライン表示で、内容・先頭ハッシュ・切断後の表示をブラウザで確認した。OBS への組込み、録画への焼込み、長時間の実ゲーム更新はまだ検証していない。

`.runtime/sensors-live-20260927/run1/` では、本番ブリッジの結果をブラウザに表示し、seq 3 の行動目的と結果を確認した。目的に含めた `<script>literal</script>` も文字列として表示された。4判断の決め打ち試験であり、長時間配信の証拠にはしない。

検証器は `external_answers`（ドライバーの成功応答がないまま閉じたモーダル）と `modal_watchdogs` も数える。前者は介入の可能性を保守的に記録する値で、人の入力と別のエンジン経路のどちらが閉じたかまでは断定しない。送信済みでも成功応答のない回答は、正常なドライバー応答に数えない。既存台帳の形式とハッシュは変えない。新しい `stray_keys` は、CTA入口と行動実行直前に残っていたキーを数えて破棄した累積値。検証区間の全観測にこの値がない古い台帳では、0ではなく `null`（未計測）を返す。

`.runtime/sensors-live-20260927/run2/` では、開発用の `Keyboard.PushKey` で実キューへ1件だけ投入し、計数・破棄、余計な移動がないこと、次の判断でも累積値が1のままであることを確認した。run1のネイティブキー操作はキューに入らなかったため、この陽性試験とは区別する。すべての物理入力経路の遮断を証明したものではない。

## ゲームとの WebSocket（`ws://127.0.0.1:4040`）

- Origin ヘッダー付きのハンドシェイクは 403 で拒否する（ブラウザ対策）。認証はしていないので、同じユーザー権限で動く悪意あるコードは防げない。
- テキストフレームだけを受け付ける。1 MiB を超えるフレームは 1009 で閉じる。NaN / Infinity、重複キー、契約外のキーは拒否する。
- `observation` は `vitals`・`threats`・`digest`（12 行以下）・`map`（25 行 × 80 文字）・`map_frame` が必須。任意の `kit`・`status`・`place`・`ground`・`goals` も形を検査する。それ以外の追加キーは認めない。`telemetry` は必須のカウンタと `game_queue` を検査したうえで、追加キーも台帳に残す。
- `goals` は `{text, truncated}`。Modern UIのクエスト表示と同じ選択・整形を使い、表示される進行状況と依頼者・場所を送る。非表示の段、完了済みクエスト、折り畳まれた完了段の本文は含めない。上限は16,384文字で、全行を収められなければ `truncated:true`。省略された項目の不在から完了を推測しない。上記run1の実機治具で表示・非表示・省略の6条件を検査し、ターンとエネルギーが変わらないことも確認した。従来のR9監査は追加前の観測が対象であり、`ground`・`goals` 全体の200ターン監査を済ませたとは扱わない。
- run の束縛: 最初に受け付けた `request`（seq 1）の `run_id` にプロセスを束縛する。heartbeat（seq は 0 以上）は束縛前でも受け付ける。
- 同時に使える接続は 1 本だけ。2 本目と、別の `run_id` の接続は 1008 で閉じる。このとき、束縛中の run の状態は変わらない。
- 同じ seq の `request` を同じバイト列で再送された場合は、台帳に行を追加しない。判断を受理済みなら、再送のたびにキャッシュした判断を同じバイト列で送り直す。送信と再送が競合すると同じ判断が 2 回届くことがあるが、seq が同じなのでゲーム側のゲートが 2 回目を捨てる。
- 次の場合は run を fault 状態にする。以後の接続はすべて拒否し、MCP は `faulted` を返す。
  - 同じ seq の request のバイト列が変わった。
  - 結果を記録した後で、その seq の request が再送された。
  - 結果が来る前に seq+1 の request が来た。
  - seq が飛んだ、または戻った。
  - 判断のない seq の結果が来た。
  - 結果の `action` が判断と違う。
  - 同じ seq の結果が異なる内容で送られた。
  - 束縛済みの接続から不正なフレームが来た。
  - 台帳の書き込みに失敗した。
- 同じバイト列の結果の重複は無視する。直前の seq の結果が重複した場合も同じ。
- 判断は、その run の有効なフレームを受け取った接続にだけ送る。形式は次のとおり（compact JSON、一度だけ直列化する）。

  ```json
  {"kind":"decision","run_id":"…","seq":1,"action":"move","dir":"N","budget":1}
  ```

- 既定の行動や代替の行動は生成しない。古い seq の判断は送らない。

### セーブ再開（`recovery`）とゲーム障害（`game_fault`）

ゲームがセーブやチェックポイントを読み直すと（例: Roleplay での死亡後にチェックポイントへ戻る）、その時点の request の操作は結果を持たないまま終わる。ハーネスはこれを完了扱いにしない。

```json
{"kind":"recovery","run_id":"…","seq":7,"recovery_id":"<UUID>","reason":"checkpoint_reload",
 "game_id":"…","save_file":"Checkpoint","save_sha256":"<64桁の小文字16進>",
 "turn_before":120,"loaded_turn":100,"lost_turns":20}
{"kind":"game_fault","run_id":"…","seq":7,"reason":"…"}
{"kind":"suspended","run_id":"…","seq":7,"reason":"game_not_running"}
```

- 形の検査（キーは完全一致）:
  - `reason` と `save_file` の組は `checkpoint_reload`→`Checkpoint`、`save_reload`→`Primary` だけを認める。
  - `game_id` は 1..128 文字。
  - `save_sha256` は 64 桁の小文字 16 進。
  - `turn_before` と `loaded_turn` は 0 以上の整数。`lost_turns` は `max(0, turn_before - loaded_turn)` と一致しなければならない。
  - `game_fault.reason` は 1..1024 文字。
- `recovery` は現在の request の seq にだけ、その結果より前に結び付く。受理すると台帳に `recovery` 行を追記して fsync する。その後、次の状態になる。
  - 受理済みの判断があれば、それは中断扱いになる。結果は作らない。
  - その seq の観測とモーダルは無効になり、行動には使えない。
  - まだ送信タスクが走っていない判断やモーダル回答は、送らずに捨てる。
  - run の束縛は同じまま。次に来てよいのは seq+1 の request だけで、中断した seq の結果は不要。
- `suspended` はゲームが終了してから再ロードされるまでの要求を無効にする。理由は `game_not_running` のみ。現在の request に結果より前に一度だけ記録し、同じバイト列の再送は無視する。
  - `get_state` は観測を含まない `not_ready` と `suspended_seq` を返す。`act` と `respond` も拒否し、送信前の判断・モーダル回答を破棄する。
  - 既に受理した操作の結果は作らない。`recovery` が届けば中断、`game_fault` が届けば障害として扱う。
  - モーダルの自動応答記録は引き続き受け付ける。ゲーム内の死亡メニューの規則を止めず、外部からの回答だけを拒否する。
  - その後の新しい判断・結果・request は拒否する。再開には同じ seq の `recovery` と seq+1 の request が必要。
  - 配信用表示では「ゲーム停止中（セーブ再読込待ち）」と古い観測を示し、直前の完了済み判断は保持する。build8 / run10 の実ブラウザで確認した。R6 run11 で死亡後の自然な1ターン進行も計測し、保存時点と最初の判断時点を別々に照合した。
- 次の場合は fault にする。
  - 現在より先の seq の `recovery`（まだ届いていない request の観測はでっち上げない）。
  - 古い seq の `recovery`。
  - 結果を記録済みの seq の `recovery`。
  - 中断済みの seq に対する、別の `recovery_id` の `recovery`。
  - `lost_turns` の計算が合わない、または `reason` と `save_file` の組が不正。
  - 中断した seq の `result`。
  - `recovery` の後に seq+1 以外の request が来た。
- 同じ `recovery_id` の `recovery` を同じバイト列で再送された場合は何もしない。後の seq に進んだ後や再接続の後でも同じ。ID は正規化した UUID で索引する。同じ ID でバイト列が違えば fault。
- 中断した seq の request を同じバイト列で再送された場合は無視する。中断した判断は再送しない。
- モーダルは重複排除の索引（token・回答・イベント）を残す。
  - 中断した seq の過去フレームと完全に同じ再送は無視する。そのモーダルは現在のモーダルに戻らない。
  - その seq の新しいモーダルデータ（新しい token、`modal_result`、`modal_clear`、`modal_auto`、`modal_watchdog`）は fault にする。
  - 待機中の `respond` は `status:"interrupted"` で即座に返る。
  - 前の seq の UI 応答が遅れて届いた場合は、これまでどおり受け付ける。
- `game_fault` は現在の seq に対してだけ受け付ける。受け付けると台帳に追記し、run を終端の fault にする。
  - 同じ接続で同じバイト列が再送された場合は何もしない。それ以外のフレームはすべて接続ごと閉じる。
  - fault 後の再接続は、ほかの fault と同じく拒否する（1008）。
  - 理由の文字列は制御文字を置き換えてから、ログと MCP の `reason` に出す。
  - fault 後は、`get_state`・`act`・`respond`・`wait_for_turn` のすべてが `faulted` を返す。`ok:true` を含む値は返さない。fault 前の `last_modal_result` も付けない。
  - 送信タスクがまだ走っていない判断やモーダル回答は捨てる。これはプロトコル違反による fault でも同じ。
- ハーネスが再接続時に想定する C# ブリッジの順序は、最新の `recovery` を再送してから最新の request を再送する、というもの。`recovery` の索引は同じハーネスプロセスの中だけで保持する。プロセスを再起動した後に台帳から再開する機能はない。
- 束縛前の `recovery` と `game_fault` は、ほかのフレームと同じく拒否する。最初のフレームは request seq 1 でなければならない。

## MCP（`http://127.0.0.1:8790/mcp`、Streamable HTTP）

- 認証: `Authorization: Bearer <token>` がちょうど 1 個ある場合だけ通す。ヘッダーがない、値が違う、複数ある場合は、SDK に渡す前に 401 を返す。
- Host は `127.0.0.1:PORT` と `localhost:PORT` だけを許す（それ以外は 421）。Origin はあれば `http://127.0.0.1:PORT` と `http://localhost:PORT` だけを許す（それ以外は 403）。これは SDK の保護で、実際のポート番号を指定して設定している。
- 公開するツールは次の 4 つだけ。

| ツール | 返り値 |
|---|---|
| `get_state()` | `{ok:true, seq, observation}`。それ以外は `ok:false` と `status`（`not_ready` / `disconnected` / `pending` / `unhandled_modal` / `recovering` / `faulted` / `shutdown`）、`reason`。ゲームは進めない。telemetry は出さない。`recovering` の場合は `interrupted_seq`、`interrupted_op`（判断がなければ null）、`recovery`（`recovery_id`・`reason`・`save_file`・`turn_before`・`loaded_turn`・`lost_turns`）を返し、観測は返さない。`game_id` と `save_sha256` は台帳にだけ入れる。`faulted` の後は観測を返さず、ゲーム障害なら `game_fault:{seq, reason}` も付ける。 |
| `act(expect_seq, action, dir=None, budget=20, target=None, until=None, item=None, rationale=None)` | seq ごとに一度だけ受理する。受理した判断は、台帳に追記して fsync してから送信する。約 2 秒以内に結果が出れば `{ok:true, completed:true, op_id, result, next_seq}`、出なければ `{ok:true, pending:true, op_id}` を返す。古い seq、二重の act、不正な引数、切断中は `ok:false` と理由を返し、ターンは進めない。`budget` は explore / goto / rest（1..40）に使い、ほかの行動は常に 1 手で送る。goto は既知セルの `target:{x,y}`、rest は `until:healed`（既定）または `morning`。talk は8方向の dir、eat / drink / apply は現在の `kit` の `item` ID、get は現在の `ground` の `item` ID が必須。 |
| `wait_for_turn(op_id, timeout_s=45)` | 受理済みの同じ操作を待つだけで、行動はしない。0..45 秒。中断した操作に対しては、次の request が来た後でも常に `{ok:false, status:"interrupted", completed:false, op_id, recovery, next_seq}` を返す（`next_seq` は次の request が来るまで null）。成功とは報告しない。fault 後は、fault 前に記録した結果があっても `faulted` を返す。 |
| `respond(expect_seq, token, response)` | 現在のモーダルに答える。台帳へ同期記録してから送信し、UI の応答結果を返す。約2秒で返らなければ `pending:true, answer_id`。その後は `get_state` の `last_modal_result` を読む。ゲーム行動の seq は消費しない。`recovering` の間は拒否する。待機中にセーブ再開が起きると `interrupted`、ゲーム障害が起きると `faulted` で即座に返る。 |

`act` は `recovering` の間、`expect_seq` の値にかかわらず `recovering` で拒否する。新しい request が来た後に古い seq を指定すると `stale_seq` になる。

`get_state` は行動が保留中でもモーダルがあれば `ok:true` と `modal` を返す。`modal` の文面・選択肢 ID・`input_kind`・`constraints` に従い、`response` には `choice` / `text` / `number` / `direction` / `target` / `field` / `cancel:true` のいずれか1つを指定する。モーダルが開いている間の `act` は `modal_required` で拒否する。未知の画面のウォッチドッグは `unhandled_modal` として返す。古い token や seq、不正な入力、保留中の回答への二重送信は拒否する。

- ツール呼び出しがキャンセルされても、受理済みの操作は取り消さず、自動で再試行もしない。
- SDK の引数検査で弾かれた場合（`action` が 11 種以外、`expect_seq` が真偽値や文字列など）は、`ok:false` ではなく MCP の `isError` として返る。
- 汎用のキー入力、wish、ファイル、シェルのツールはない。

## 台帳と検証

各行は `index`・`kind`・`seq`・`run_id`・`body`・`prev_hash`・`hash` のフィールドだけを持つ。

- 行動の `kind` は `request` / `decision` / `result`。その間に `modal` / `modal_answer` / `modal_result` / `modal_clear` / `modal_auto` / `modal_watchdog` が入る。さらに `recovery` と `game_fault` が入ることがある。
- 正準形は、キーをソートし、区切りを `(",", ":")` とした UTF-8 の JSON（ASCII エスケープなし、NaN 禁止）。
- `hash` は、`hash` を除いた行の正準形の SHA-256。
- 先頭行の `prev_hash` は 64 個の `0`。
- 判断の body の `request_hash` が request 行を、結果の body の `decision_hash` が判断の行を指す。
- request と結果の body には、受信したフレームの `frame_sha256`、`observation`、`telemetry` を入れる。
- モーダル回答は `modal_hash`、応答結果は `answer_hash` で元の行へつなぐ。検証器は token・seq・回答 ID と入力の形も照合する。同じフレームの再送は重複記録せず、閉じたモーダルへの回答を再送しない。
- `recovery` の body には、フレームから `kind`・`run_id`・`seq` を除いた全フィールドを入れる。加えて `frame_sha256`、`request_hash`（中断した request）、`decision_hash`（中断した判断。なければ null）を入れる。
- `game_fault` の body は `reason`・`frame_sha256`・`request_hash`・`decision_hash` だけ。`decision_hash` はその seq の判断を指し、なければ null。中断済みの判断や結果済みの判断も指す。

```sh
.venv/bin/python -m harness.verify .runtime/RUN/ledger.jsonl [--require-completed 1] [--m1]
```

- 次の項目を検査し、JSON の要約を出力する。成功なら終了コード 0、失敗なら 1。
  - ハッシュ鎖
  - 行の順序（seq 1 から request → decision → result）
  - body の形とリンク
  - run_id が 1 つであること
  - 末尾の行の切れ
  - `recovery` について、次の項目。
    - 現在の request の後、結果より前に 1 回だけあること。
    - 次の行動の行が seq+1 の request であること（中断した seq の判断や結果は認めない）。
    - `recovery_id` が正規化した UUID として一意であること。
    - `lost_turns` の計算、`reason` と `save_file` の組、ハッシュのリンク。
    - 中断した seq にモーダルの行がそれ以上ないこと。
  - `game_fault` について、現在の seq であること、リンクと body の形、そして終端であること（後ろに行が 1 行でもあれば失敗）。
  - `suspended` について、現在の request とのリンク、結果より前に一度だけあること、復帰まで新しい行動の行がないこと。
- 末尾が request だけ、または判断だけで止まっている状態も認める。これは `pending` として報告する。
- 要約に次のキーを追加した。既存のキーは変えていない。
  - `recoveries`
  - `interrupted_decisions`（判断を中断した recovery の数）
  - `lost_turns`（合計）
  - `recovering_seq`（末尾が recovery で、新しい request を待っている seq。なければ null）
  - `game_fault`（`{seq, reason}` または null）
  - `suspensions`（停止の回数）、`suspended_seq`（復帰待ちの seq または null）
- `game_fault` がある場合、`pending` は null になる。
- 旧形式の台帳（recovery と game_fault の行がないもの）は、これまでどおり検証を通る。
- 鎖が正しいことは M1 の達成を意味しない。既定の出力は `"m1": null` になる。
- `--m1` を付けると、次の条件もすべて要求する。
  - 実行された行動（`executed:true`）の結果がある。
  - その次の seq の request がある。
  - すべての telemetry で `end_player_turns` と `player_turn_entries` が 0 である。

`--m1` が検査するのは台帳にある条件だけであり、呼び出し元が本物の LLM かどうかは判別しない。M1 の達成を報告するときは、Claude の呼び出し記録、対象 seq、実機ログを別に照合する。偽ゲームのテストや決め打ちの行動だけでは、この条件を満たしたことにはしない。

## Claude計画 / Jev操作の試走

`harness.hybrid` は、Claudeの短期計画に従ってJevが具体的な操作を選ぶ有限のプレイヤーである。
現行modの `item_details` を必須とし、所持品の可視説明・ネイティブ操作、実行結果、送信した会話回答を入力に含める。
行動の担当を[行動分類](../docs/jev-action-ownership.md)で分ける。確認済みの通常移動・単独近接戦などは、候補分布が正しく現状と方針に合えば、低い選択確率だけでは移譲しない。
危険・方針衝突・未知の消耗品・会話分岐は高確率でもClaudeへ渡す。残る条件付き操作には基準 `0.5` から状況別に調整した閾値を使う。確率自体を書き換えたり、安全確率と解釈したりはしない。応答不正、反復失敗、計画期限なども上位判断の対象になる。
Claudeが明示許可した既知目標へのgotoは、各区切りで安全と進捗を確認して計画実行器が継続する。到着で許可を消費し、再訪には新しい上位計画を要する。
依頼の受諾・完了・アーティファクト引き渡しはClaudeが判断する。通常の会話でも同じ分岐を反復したら上位へ戻す。
移動に限定した相談はスキル一覧を省き、短い更新を既存戦略へ反映する。条件と検証限界は[移譲・移動方針](../docs/jev-navigation-policy.md)を参照。
`confidence` は確率と別に記録する。詳細と調査出典は [設計記録](../docs/jev-hybrid.md) を参照。

成長対応modでは `character` にレベル、XP、未使用SP/AP、能力値、習得済みスキル、公開スキル一覧を含める。
変異観測対応版は、標準キャラクター画面由来の `genotype`、`subtype`、`mutation_points`、`mutations`、`mutations_truncated` を追加する。このフィールド群のない旧観測も受理する。変異一覧には名前・ランク・現在ランクの説明・欠点区分を含むが、能動能力の発動やMP消費の操作を提供するものではない。
Claudeが初回の安全な局面、成長、新しい装備候補、装備変更を確認し、`strategy` と `tactics` を更新する。
ポイントを温存する判断も許容する。敵や危険な状態異常が見えている間は任意の育成を保留する。
`learn_skill(skill=...)` と `raise_attribute(attribute=...)` は現在観測の費用・前提条件を照合し、
ゲーム標準の確認・購入処理を通す。購入・装備の確認画面はClaudeが担当する。
次の観測で確定した変更を再評価し、Jevには現在の能力・装備と更新した方針を渡す。
Jevの候補に購入・装備変更は含めず、未習得一覧とClaudeの自由文の記憶も渡さない。

```sh
uv run python -m harness.hybrid \
  --run-dir /absolute/path/to/harness-run \
  --output-dir /absolute/path/to/new-player-output \
  --jev-env /absolute/path/to/private.env \
  --duration-seconds 600 --max-actions 150 --max-claude-calls 30 --threshold 0.5
```

セーブから再開する際は、任意で `--resume-plan /absolute/path/to/previous/player/report.json` を加える。
前回の目標・記憶・ビルド方針と、出典付きの `verified_events` を引き継ぐが、初回は現在の観測によるClaudeの再確認を必ず行う。過去の許可だけでは操作しない。
会話で提示された依頼と選択、公開クエストログの変化、ゾーン入場、確認済みの到着を最大128件保持し、各結果の確定後に `verified-events.json` へ原子的に保存する。
これは過去の観測であり、応答の受理やクエスト欄からの消失だけを「完了」とは扱わない。復帰で時間が巻き戻った場合は破棄する。
`lost` は移動制約として別に渡す。安全な到着・移動制約の変化・無被害の `ENGINE_STOP` は限定的な相談にできるが、未知の効果や敵・被害を同じ扱いにはしない。

同じゲームを操作する別プレイヤーを停止し、episode controlを有効にせずに起動する。
Jevキーは環境変数 `TYPESAFE_API_KEY` / `TYPESAFEAI_API_KEY` または明示したenvファイルから読む。
Claudeはインストール済み公式CLIのサブスクリプション認証を使い、safe mode・空のツール集合・置換システムプロンプトで計画だけを返す。
上位Claudeはユーザー指定の `opus` を既定とし、CLIにも `--model opus` を明示する。試走の起動時には `--claude-model opus` を指定し、失敗時に別モデルへ切り替えない。記録の `requested_model` と応答の `models`（modelUsage）を別々に確認する。認証やCLI失敗を自動再試行しない。
同一CLI呼び出し内の構造化出力修正は最大2回とする。推論全体・無応答の独自タイムアウトは既定で設けず、API待機時間もCLI標準／既存環境に従う。指定された試走時間と明示的な中止は維持する。形式エラー件数と最終利用量を記録し、エラー本文や思考内容は保存しない。

状態・液体は [wiki分類表](../docs/jev-status-catalog.md) に対応したカタログを使い、成立する条件をClaudeとJevへ渡す。回復と回復阻害、複合危険、身体・装備・地形・携帯容器を分ける。所持トニックの注意点は判断材料として添え、携帯だけでは危険度を上げない。

`decision-*.json` に入力・候補・選択確率・移譲理由・送信結果、`outcome-*.json` に実際の行動結果、
`claude-*.json` に計画と処理時間、`report.json` に停止理由と件数を残す。
上限に達したら受理済み操作のモーダルと結果を処理して停止する。保存・ゲーム終了は、このプロセスの終了後に上記modの運用経路で行う。

## テスト

```sh
.venv/bin/python -m unittest discover -s tests -t .
```

現在の `.venv` には pytest が入っていないため、`python -m pytest tests` は動かない。上の unittest のコマンドを使う。セーブ再開とゲーム障害の回帰テストは `tests/test_lifecycle.py` にある。

テストはすべて一時ディレクトリと `127.0.0.1` の空きポートで動き、終了時にすべて閉じる。偽のゲームのフレームは、非 ASCII のグリフを含む実物に近い観測を使っている。

2026-09-27 の追加試走では、Claude Code（Opus 5.5 / xhigh）に4つのゲーム用 MCP ツールだけを渡し、25 判断を無人で完了した。23 move・2 explore、seq 1→26、世界ターン9→28、HP 18/18。台帳77行（通知の自動応答1件を含む）の鎖・判断・結果・次 CTA を照合した。開発用プロファイルの短い interactive 試走であり、M2 の1時間や SDK 直接走行の証拠ではない。記録: [.codex/artifacts/claude-m1-interactive-pilot-20260927.md](../.codex/artifacts/claude-m1-interactive-pilot-20260927.md)。
