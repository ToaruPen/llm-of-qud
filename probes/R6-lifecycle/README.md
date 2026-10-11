# R6 ライフサイクル検証

固定版 `2.0.211.56`、Modern UI、Harmony なし。本番ブリッジと R0 に加え、`mod/` だけを `LlmOfQudProbeR6` として隔離プロファイルへ置く。開発用の死・保存・reload wish を使うため、プレイの達成実績には数えない。

| 検査 | 2026-09-27 時点の実測 |
|---|---|
| 明示保存 | 成功。desktop の同期 `SaveGame` は null を返す |
| reload wish | 成功。置換されたコールバックを各1本に再登録し、ブリッジ1個と次 CTA を確認 |
| Roleplay の実死亡 | 成功。古いチェックポイントへ TurnSystem を再登録し、seq 4→5、ターン3→0の復帰を台帳と照合 |
| メニューへの退出・再入場 | 成功。同一プロセスで seq 2→3、Primary の SHA-256 とターン3を照合 |
| 正常終了・プロセス再起動 | 成功。終了コード0、新しいプロセス・run の seq 1、保存ターン4を照合 |
| 実クラッシュからの復旧 | 成功。通常のゾーン移動で生じた自動保存から再開。SIGKILL 前13→保存9の4ターン喪失を照合 |

5経路は、同一プロセスの死亡・hotload と、3プロセスの退出・再起動・クラッシュの2系列で検証した。各境界の最初の CTA で、各コールバックが1本、ブリッジが1個、要求が1件であることを確認している。セーブ選択とプロセス起動、初回 arm は運用者が行った。完全無人の起動・復旧を意味しない。

停止通知を追加した現行版は、旧版の上記合格と区別する。build8 / run10 ではメニューで48.5秒待ち、観測・行動・応答の拒否、台帳不変、誤ったモーダル警告がないこと、表示の「ゲーム停止中」を確認した。保存からの再入場は合格し、両復帰経路を含む19行・4判断で PlayerTurn / EndPlayerTurn は0だった。ただし死亡後は保存ターン9に対して最初の CTA が10となり、ライフサイクル検証器は不合格とした。証拠は `.runtime/r6-live-20260927/run10/`。修正前の run9 で起きた PlayerTurn への1回の進入と、この初回不合格の結果は両方保持している。

run11 では計測だけを追加し、ロード直後のエネルギー138・セグメント位置8から、9回の速度加算を経てエネルギー1038・セグメント位置6の最初の CTA に届くことを確認した。ゲームのセグメント位置は static でロードをまたぐため、世界ターンは9→10となる。検証器の「ロード時エネルギーは必ず1000」という前提を修正し、`loaded_turn` と `load_to_cta_turns` を記録する。保存ハッシュ、最初の要求、コールバック数の照合は維持し、PlayerTurn / EndPlayerTurn が0であることも必須にした。51テストが合格し、run11 の両復帰経路が合格、古い run9 は PlayerTurn=1 で引き続き不合格となる。ゲームのエネルギーやターン数は書き換えていない。

run10 の終了時はローカル `handoff` の記録を確認してからゲームを終了し、終了コード0・`game_fault` なしを確認した。制御中に直接終了して例外が記録された run9 の証拠も削除していない。

| 証拠 | 内容 |
|---|---|
| `.runtime/r6-live-20260927/run5/checkpoint-hotload-verification.json` | チェックポイント復帰・hotload が PASS。対応ソースは `r6-build-5-20260927` |
| `.runtime/r6-live-20260927/process-claims-verification.json` | メニュー再入場・正常再起動・クラッシュ復帰が PASS。対応ソースは `r6-build-6-20260927` |
| `.runtime/r6-live-20260927/process-recovery-ledger.jsonl` | プロセスをまたぐ検証済み復旧記録。元のゲーム台帳とは別の検証器出力 |
| `.runtime/r6-live-20260927/run7/automatic-save-provenance.json` | 保存治具なしで5回のゾーン境界通過。Roleplay の Checkpoint と Primary が一致。専用 AutoSaveCommand 経路の区別までは測っていない |

初回の `save_quit` 治具は `Running=false` だけを設定したため、ゲームの死亡処理で隔離セーブが削除された。この失敗を `run5/menu-failure.json` に保存し、通常の Save and Quit と同じ `<nodeath>`・`DeathCategory=exit`・`forceNoDeath` を設定するよう修正した。run6以降では保存が保持され、再入場・再起動の検証が通った。復元に使った検証用バックアップも保持している。

## 入口と証拠

プロファイル直下の `r6-dev-optin.json` は、`v:1`、`development:true`、`disposable:true`、そのプロファイルの絶対パス `savepath`、32〜64文字の小文字16進 `nonce` を持つ。権限は0600。別プロファイルへコピーした opt-in は拒否する。

本番を `development:true` で arm した後にローカルの `llm-control.json` から治具を起動する。MCP には公開しない。

```sh
.venv/bin/python probes/R6-lifecycle/r6_operator.py --profile /absolute/disposable/profile fixture save --receipt /absolute/results/save.json
.venv/bin/python probes/R6-lifecycle/r6_operator.py --profile /absolute/disposable/profile fixture reload --receipt /absolute/results/reload.json
.venv/bin/python probes/R6-lifecycle/r6_operator.py --profile /absolute/disposable/profile fixture death --receipt /absolute/results/death.json
```

`save_quit` は保存してメニューへ戻す。`autosave` は明示保存の別名であり、ゾーン移動による自動保存ではない。結果は `r6-evidence/*.jsonl` の `fixture_done` または `fixture_error` で確認する。制御ファイルの書き込み成功だけでは完了ではない。

実クラッシュ試験は、同じ opt-in と nonce、PID、起動引数、5秒以内の心拍を照合してから、当該プロセスだけへ SIGKILL を送る。

```sh
.venv/bin/python probes/R6-lifecycle/r6_operator.py --profile /absolute/disposable/profile crash --evidence /absolute/disposable/profile/r6-evidence/session.jsonl --receipt /absolute/results/crash.json
```

各プロセスの証拠ファイルは追記専用の SHA-256 鎖。ゲームID、保存候補のハッシュ・ターン、コールバック数、ブリッジ数、最初の CTA を記録する。復帰元を一意に照合できない証拠は検証器が拒否する。

```sh
.venv/bin/python probes/R6-lifecycle/r6_verify.py --evidence-dir /absolute/results/evidence --ledger /absolute/run/ledger.jsonl --receipts-dir /absolute/results/receipts --cases hotload,checkpoint_reload
.venv/bin/python -m unittest discover -s probes/R6-lifecycle -p 'test_*.py' -q
dotnet build probes/R6-lifecycle/compile/R6Compile.csproj
```

`--cases` の部分合格は R6 全体の合格ではない。失敗した初回試験も `.runtime/r6-live-20260927/run1/` と `run2/` に保存している。`r6_scenario.py` は検証器用の合成データであり、実機証拠ではない。
