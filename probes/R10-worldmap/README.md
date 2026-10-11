# R10 世界地図と Lost

固定版 `2.0.211.56`、Modern UI、隔離した Roleplay セーブを使い、本番 MCP と mod を経由して検証する。以下は運用者の決め打ち試験で、Claude の自律プレイ実績には数えない。

| 日付 | 結果 | 証拠 |
|---|---|---|
| 2026-09-27 | 直接 `Move("U")` は空へ移動して落下していた。上下移動を標準コマンドの階段・世界地図処理へ修正。世界地図への出入り、降下取消、階段なしの拒否を確認 | `.runtime/r10-live-20260927/worldmap-ascent-build8-red.json`、`run1/`、`.runtime/r10-build-1-20260927/` |
| 2026-09-27 | 世界地図の内部 CTA が行動完了前に結果を送る失敗を修正。Joppa→Red Rock→Grit Gate の地上への出入り、Lost 通知、隣接ゾーン探索による Lost 解消を確認。21操作、PlayerTurn / EndPlayerTurn / UIタスク / 未知タスクは0 | `run1/worldmap-step-red.json`、`run2/acceptance-ledger.jsonl`、`run2/cta-invariant-verification.json`、`.runtime/r10-build-2-20260927/` |
| 2026-09-27 | Lost・遭遇で地上へ移っても blocked とする結果を修正。遭遇 Yes、自然な Lost、Lost 中の上昇拒否と理由、地上の次の移動が合格。24操作、内部 travel CTA 7,575回、上記4カウンタは0 | `run2/lost-outcome-red.json`、`run3/worldmap-outcome-green.json`、`run3/acceptance-ledger.jsonl`、`.runtime/r10-build-3-20260927/` |

表の `runN/` は `.runtime/r10-live-20260927/runN/`。各回のソース SHA-256、開始前セーブ、台帳、ゲームログを保持する。旧失敗記録は上書きしない。build3 の固定 DLL コンパイルは成功。静的解析の既存6警告は、旧API2件とコールバック・スレッド間の状態変更を解析が追えない4件として保持している。

世界地図の AutoAct `goto` は未検証。本番では当面1マスずつの `move` を使う（06 の R10 の退路）。階段の鍵、地下での上下移動、世界地図へ出る確認設定の分岐は残る。build3 の Lost 解消は未再測定であり、解消の証拠は build2 に限る。
