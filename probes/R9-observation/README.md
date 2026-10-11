# R9: 観測の漏れ監査（私的計測）

状態: **2026-09-27 に実機合格**。210 回の待機から 211 件の観測、208 回の世界ターン前進を記録した。未鑑定品・非可視の生物・Scanning なしの可視生物が各 211 件あり、検出した漏れは 0 件。送信フレームと台帳の照合で `r9_claimable:true` を確認した。決め打ちの監査走行であり、LLM のプレイ実績ではない。

実行 ID は `0e8d6800-c36a-4372-909c-ce9ffae04c44`。証拠は `.runtime/r9-live-20260927/` の `audit-verification.json`、`ledger-verification.json`、`driver-report.json`。使用ソースは `.runtime/r9-build-20260927/` に保存した。CTA は 211、PlayerTurn / EndPlayerTurn / ui_tasks / unknown_tasks はすべて 0。隔離ゲームとハーネスを停止し、MCP トークンも削除済み。

## 構成

- `mod/LlmOfQud/Observation.cs`: 本番の観測。M1 の `vitals/threats/digest/map/map_frame` に加え、任意キー `kit`（装備スロット付き所持品、`GetDisplayName(AsIfKnown:false)`、`iN` はその観測限りの ID）、`status`（キャラクター画面と同じ `GetDescription()` 非空の効果、HUD の食料/水）、`place`（HUD のゾーン名、世界地図か、Lost）。
- `mod/LlmOfQud/ObservationAudit.cs`: 私的 oracle。arm の制御ファイルで `"audit":true` のときだけ有効（既定 off、off 時は追加列挙なし）。同じ CTA のゲームスレッドで、送信する request 文字列そのもの（と SHA-256）と、本番と別経路（全セル走査、`Inventory.Objects`+`GetEquippedObjects`、Hitpoints stat、`ZoneManager.ActiveZone`、MessageQueue 末尾、独自 AfterRender カウンタ）で作った oracle を `<profile>/llm-r9/<run_id>.jsonl` に同期追記する。oracle には本名・blueprint・非可視体・数値 HP が入るので、**このファイルを LLM/MCP に渡さない**。ハーネスや MCP からは到達できない。
- `r9_verify.py`: 決定的検証器。件数は oracle 行から数える（mod の自己申告カウンタは使わない）。

## 実機手順（隔離プロファイルの使い捨て DEVELOPMENT 走行のみ）

1. `mod/LlmOfQud/` を隔離プロファイルの `Mods/LlmOfQud/` へ置き、R0 の `runtime.py check`/`launch` を `--allow-mod LlmOfQudM1` 付きで実行して起動する（mod README と同じ）。プロファイルのパスは M1 実走で使ったものを実行記録から取る（この文書では推測で書かない。R34 の記録は `CavesOfQud-r34` だった）。通常セーブでは行わない。**fixture はセーブを汚すので、使い捨てのキャラクター/セーブで行う**。arm 時に digest を空にするので、同一プロセスでの handoff→再 arm でも使える。
2. ハーネスを新しい run ディレクトリで起動する（harness/README.md）。
3. プロファイル直下の `llm-control.json` に、一時ファイル→rename で次を書く:
   `{"command":"arm","run_id":"<新UUID>","audit":true,"r9_fixture":true}`
   `r9_fixture` は arm 時に一度だけ、ゲームスレッドで (a) `Vibro Dagger` を所持品に追加、(b) 非可視・通行可能な空きセルに `Pig`、(c) 隣接空きセルに `Pig` を置く。結果（`Understood()`、可視性、Scanning）は最初の監査レコードの `fixture` にだけ記録される。ゲームログには `r9_audit_armed` が出る。
4. MCP の `act(wait)` を約 210 回呼ぶ（1 回 = 1 CTA = 通常 1 世界ターン）。explore を混ぜてもよいが、監査レコードは判断 1 回につき 1 件なので、wait が最も確実に 200 の「前進する異なるターン」を作る。
5. `{"command":"handoff"}` で終了（監査ファイルは閉じられる）。
6. 検証:
   ```sh
   .venv/bin/python probes/R9-observation/r9_verify.py \
     "<profile>/llm-r9/<run_id>.jsonl" --ledger <run-dir>/ledger.jsonl
   ```
   期待する証拠: `ok:true`、`advancing_turns >= 200`、`case_records` の 3 項目がすべて 1 以上、`r9_claimable:true`。ledger 照合は request 行の `frame_sha256` と監査の `request_sha256` を seq ごとに突き合わせ、監査の「actual」が実際の送信フレームであることを示す。

## 検査内容

- request がワイヤ契約に合う。SHA-256 が一致（ledger 指定時は ledger とも一致）。
- vitals 全項目が oracle と一致。
- threats の (x, y, 名前, wound, hostile) の多重集合が、oracle の可視体と一致。非可視体の座標・名前が threats に出ない。
- Scanning なしの可視体に数値 HP（`\d+/\d+` や hp/max）が出ない。Scanning ありの数値表示は許可。
- 未鑑定品/可視体で本名 ≠ 表示名のとき、本名が digest と地図以外の観測テキストに出ない。
- kit・place・status.effects が oracle と一致。
- digest は 12 件以下で、MessageQueue の末尾と同順（modal 通知文は除外して比較）。
- `map_frame` が単調増加し、監査の AfterRender カウンタが捕獲区間で進む（地図の字は実体の証明に使わない）。
- 前進する異なる世界ターン ≥ 200、3 ケース（未鑑定品、非可視の生物、Scanning なしの可視生物）が各 1 件以上。

## 限界・未検証の前提

- `Vibro Dagger` が未鑑定になるかはキャラクターの理解度次第。鑑定済みなら `unidentified_item` が 0 になり、検証は正しく失敗する。そのときは別の Examiner 品で再試行する。
- 非可視セルの Pig は歩いて視界に入ることがある。必要なのは 1 件以上であり、自然に存在する非可視の村人も数える。
- digest の oracle は arm 以後の MessageQueue 末尾。8192 件超過時の切り詰めは扱わない。
- `status.food_water` は HUD の文字列そのものであり、oracle 比較の対象外。
- 監査中は毎 CTA で全セル走査と同期書き込みを行う。監査 off 時は `_audit == null` の分岐だけ。
- `kit` は最大 64 件、`status.effects` は最大 32 件。上限超過時の完全な一覧を保証しない。

```sh
.venv/bin/python -m unittest discover -s probes/R9-observation -p 'test_*.py'
```
