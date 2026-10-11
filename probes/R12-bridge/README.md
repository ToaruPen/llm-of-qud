# R1 / R2 実機プローブ

既存 R5 の隔離セーブを複製し、Modern UI・タイル表示・arm64・Harmony なしで、06 §5 の R1 / R2 を測る。これは検証用コードで、本番のハーネスではない。

| 対象 | 条件 | 合格条件 |
|---|---|---|
| R1 | CTA 内で 60 秒 / 600 秒 × 実フォーカスあり / なし | UI タスクの応答が 1 秒未満、解放後の PassTurn が 1 回、次 CTA 到達、EndPlayerTurn が 0 |
| R2 | 1,000 往復、seq=501 の応答前に接続を強制切断 | p95 < 5 ms、接続を張り直し、保留中の seq と本文が完全一致 |

R1 は `gameQueue` を回さない同期待機。UI tick が `ConcurrentQueue` の要求を処理し、ブリッジスレッドが 100 ms ごとに `bThreadFocus`、`_focused`、`focusedEvent` を維持する。Unity の `runInBackground` と実フォーカスの読取は UI スレッドで行う。実フォーカス判定は切替用の冒頭 3 秒を除外する。待機終了時の PassTurn は実験で明示した 1 手であり、本番のタイムアウト既定行動ではない。

R2 はゲームスレッドで固定した turn・名前・位置・zone と、明示的な合成文字列（`界` × 1,024、UTF-8 で約 3 KB）を使う。毎回ゲーム状態を観測したり、1,000 ターン進めたりする試験ではない。要求を一度シリアライズし、接続を失っても同じバイト列を再送する。サーバーは要求本文の SHA-256 と接続番号を記録する。切断後 2 秒の応答停止は最大 RTT に含まれ、失敗した送信試行は成功 RTT の分布に含めない。

実行用ファイルは次のとおり。

- `BridgeProbe.cs` / `manifest.json`: ゲームが起動時に Roslyn でコンパイルする mod。
- `r2_server.py`: Python 3.12 / websockets 16.0 の実験用 peer。
- `test_r2_server.py`: seq の飛越・重複・本文変更・不正 envelope を拒否する検査。
- `test_verify_run.py`: 再起動をまたぐ証拠の統合、不足条件、プローブ中の例外、標本の空白期間を検査。
- `verify_run.py`: ゲームとサーバー双方の生ログから全条件を再判定する。条件が欠けていれば失敗する。
- `results/runtime-manifest.json`: 固定コピーの Managed DLL と Base ファイルのハッシュ。R0 全体の完了を意味しない。

## 実行

配置先は `~/Library/Application Support/Freehold Games/CavesOfQud-r12/Mods/LlmOfQudProbeR12` からこのディレクトリへの symlink。R5 mod も元セーブの互換性のため有効にする。他の mod は無効。本体は `~/Games/CavesOfQud-probe-2.0.211.56-build25520692/CoQ.app`。本番プロファイルと元 R5 セーブは検証用に変更しない。

ゲームは `SteamAppId=333640 SteamGameId=333640` を設定し、`-savepath` と `-logFile` を明示して起動する。`build_log.txt` の Success と FINAL LOAD ORDER を確認する。Continue で Yruula / Joppa / turn 0 を選び、mod 差分画面では現在の mod 構成を維持してロードする。

```sh
uv run --python 3.12 python -m unittest discover -s probes/R12-bridge -p 'test_*.py'
uv run --python 3.12 --with websockets==16.0 python probes/R12-bridge/r2_server.py \
  --output probes/R12-bridge/results/r2-server.jsonl
```

サーバーの出力ファイルは上書きしない。再実行時は別名を指定する。

wish は `probe12:r2`、`probe12:r1:60:focused` など。UI 自動入力で Ctrl+W が通らない場合は、隔離プロファイル直下の `r12-command.txt` に `r2` または `r1:60:focused` と書く。ゲームスレッドの EndPlayerTurn コールバックが読み、ファイルを削除して 1 回実行する。1 本の完了前に次を投入しない。R1 の残りは `r1:60:unfocused`、`r1:600:focused`、`r1:600:unfocused`。非フォーカス条件は開始直後に別アプリを前面にする。

非フォーカス試験では、ゲームを前面にしてコマンドを投入し、ログの `r1_begin` を確認してから `osascript -e 'tell application "Finder" to activate'` で切り替えた（ユーザー許可済み）。OS の前面アプリだけで判断せず、UI tick が読む `Application.isFocused` が冒頭 3 秒後の各標本で false になることを確認する。`r1_result` が出るまでゲームを前面に戻さない。切替の記録は `results/focus-control.jsonl`。

```sh
uv run --python 3.12 python probes/R12-bridge/verify_run.py \
  probes/R12-bridge/results/Player.log probes/R12-bridge/results/r2-server.jsonl \
  --additional-player-log probes/R12-bridge/results/Player-unfocused.log
```

再起動ごとの Player.log は原本を別名で保存する。検証器は各ファイルの最初の R1 / R2 開始以降を例外検査し、起動前段の既知の GOG 初期化例外と、意図的切断の `r2_reconnect` 記録を区別する。約 1 秒ごとの UI 標本について、先頭・末尾を含む間隔が 2 秒未満であることも確認する。停止後のまとめ採りで標本数だけを満たす走行は合格にしない。

## 実測の範囲

| 日付 | 対象 | 結果 | 証拠 |
|---|---|---|---|
| 2026-09-26 | R1 | 60 秒 / 600 秒 × フォーカスあり / なしの 4 条件が合格。UI 最大 14.6956 ms、全条件で 1 手・次 CTA 到達・EndPlayerTurn 0 | `results/Player.log`、`results/Player-unfocused.log`、`results/full-summary.json` |
| 2026-09-26 | R2 | 1,000 往復、p95 0.406 ms。切断後の seq=501 と本文ハッシュの一致を両側ログで確認 | `results/Player.log`、`results/r2-server.jsonl`、`results/full-summary.json` |

R1 / R2 は実機ログをもって判定する。コードのコンパイルだけでは合格にしない。R3 の AutoAct・1 時間運転・OBS、R9 の観測網羅、主張用台帳、MCP 接続は別途必要。

後続の最初の自律ターンは、ユーザー指定の Claude Code / `claude-opus-5-5` / `xhigh` を使う。2026-09-26 にツールなしの最小呼び出しが成功し、返却されたモデル名も一致した。ゲームへの MCP 接続はまだ行っていない。
