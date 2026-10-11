# R3 / R4: 背景動作と AutoAct の委任

固定版 `2.0.211.56`、Modern UI、Harmony なしの実機プローブ。通常のセーブとは別の `CavesOfQud-r34` プロファイルを使う。起動時のビルド・mod・オプション検査は [R0](../R0-runtime/README.md) が担当する。

## 現在の実測

| 検査 | 結果 | 範囲 |
|---|---|---|
| R4 `r4-auto-500` | 500 ターン、26,194 ms、23 判断、451 回の位置変化 | explore 6 回、goto 6 回、rest 11 回。PlayerTurn / EndPlayerTurn 0。通知 2 件を UI tick が自動応答。走行中の CUA・キーボード操作なし |
| R3 `r3-focused-60` | 60,013 ms、1,084 回の位置変化、18.063 回/秒 | 59 回すべての heartbeat で実フォーカスあり |
| R3 `r3-unfocused-60` | 60,011 ms、1,064 回の位置変化、17.730 回/秒 | 59 回すべてで実フォーカスなし。前面比 98.16% |
| OBS の実更新頻度 | 前面 59.900 fps、背景 54.780 fps | 録画内の Unity frameCount を復号。背景比 91.45%、内部欠落 0。短時間の結果 |
| R3 `r3-unfocused-hour-power` | 3,600,040 ms、65,011 回の位置変化、18.058 回/秒 | 移動速度は前面比 99.98%。約 1 分の全 60 区間で最低 99.18%。3,581 heartbeat がすべて非フォーカス、PlayerTurn / EndPlayerTurn 0。ログ・動画とも合格 |
| 同走行の OBS 実更新頻度 | 58.411 fps、前面比 97.51% | 10 秒区間の最低比率 91.99%、最長の同一フレーム継続 150 ms。内部のマーカー欠落なし |
| `r3-picker-transitions` | 10 / 10 が期待値 E、合計 25 回の実フォーカス変化 | すべて 1 回の PushKey で到達。模擬損失による再送は下記の別走行で確認 |
| R3 `r3-covered-hour-power` | 3,600,050 ms、65,351 回の位置変化、18.153 回/秒 | 移動速度は前面比 100.50%。約 1 分の全 60 区間で最低 99.94%。3,581 heartbeat がすべて非フォーカス、PlayerTurn / EndPlayerTurn 0。ログ・動画とも合格 |
| 同走行の OBS 実更新頻度 | 58.667 fps、前面比 97.94% | 10 秒区間の最低比率 93.66%、最長の同一フレーム継続 150 ms。内部のマーカー欠落なし |
| `r3-picker-retry-simulated` | 10 / 10 が E、最初の入力を 10 回捨て、再送 10 回で応答 | 18,135 ms、実フォーカス変化 33 回。各ピッカーで 3〜4 回の切替。投入前の模擬損失であり、実輸送での欠落の実測ではない |
| `r3-hover-no-pointer-control` | Inventory の表示・対象検出・20,005 ms での終了を確認 | ポインタを動かさない対照試験。`HOVER_NO_TOOLTIP` を記録し、偽のキュー投入を合格にしなかった。通常画面への復帰を確認 |
| `r3-hover-focused-pointer-20260927` | 前景で実ホバー成立 | 実ポインタの到達、tooltip、pointer exit、新しい `LookedAt` task の投入を確認。task の実行を証明するものではない |
| R3 の非フォーカス実ホバー | 未完了 | Finder を前面に出した試行でも Unity の実フォーカスが true のままになり、背景条件を確認できなかった。R3 全体を合格とはしない |
| `r3-hover-unfocused-pointer4-20260927` | 45,010 ms、`HOVER_NO_TOOLTIP` | 実フォーカスが true のまま、ゲーム窓も他アプリに覆われたため、ポインタ入力は実施しなかった。背景ホバーの合格証拠には含めない |

短時間の前面・背景の経路は、ともに Joppa の `(40,23)` と `(44,23)` の往復。世界のターンは異なる。R4 の 1 判断あたりのターン数は最小 2、中央値 20、p95 40、最大 40。判断と終了記録の対応、ターン数の連続性を検証器で確認した。

非フォーカス 1 時間の開始時の両端は `(47,24)` と `(51,24)`、被覆試験は `(48,23)` と `(52,23)` で、同じ Joppa ゾーン内の別の開始点である。各回の開始地点から、固体と液体のない横 4 マスを選ぶ方式なので、厳密に同じ経路を再生した速度比較ではない。位置変化数は CTA 間の座標変更回数であり、厳密な移動距離ではない。

被覆条件は、同じディスプレイの空の Finder 窓を「画面全体に表示」で配置し、前面に置いて作った。開始後・途中・終了直前に窓のタイトルと 2560×1345 の寸法を確認した（`results/r3-covered-hour-power/coverage-setup.json` と `coverage-observations.jsonl`）。全時点の重なり順や完全な被覆を独立に連続計測したものではない。

動画の検証は `results/<run-id>/capture-verification.json` に保存する。前面 60 秒と両方の 1 時間走行では、コンテナの申告フレーム数が復号可能数より 1 多い警告が出た。ffprobe と実際の RGB 復号のフレーム数は一致し、判定対象期間内のマーカー欠落はなかった。

**これは決め打ちのプローブであり、LLM のプレイ実績ではない。** R3 では空腹通知と速度低下を測定から除くため、走行中だけ Stomach の CookingCounter を 0、水分を 30000 に保つ。終了時に保存したフィールド値へ戻すが、空腹エフェクトなどを含む状態全体の完全復元は保証しない。この隔離セーブを通常のプレイ実績に使わない。R4 にはこの処理を適用しない。

## 実装と証拠

ゲームスレッドの CTA が `AutoAct.Setting` を設定し、毎 CTA で `SkipPlayerTurn` を立て直す。エンジン停止、到達、歩行停止、ターン上限を次の CTA で記録する。UI tick は実フォーカスとフレームを毎秒記録し、入力欄や選択肢がなく Accept が一つだけの通知に応答する。複数のモーダルや選択入力には答えない。別スレッドは 100 ms ごとに既存のフォーカス旗を維持する。

同じ起動で R5 もロードしているが、この起動の R5 ログは初期化と tick 開始の 3 行だけで、focus 試験の開始記録はない。R5 の書換え旗は既定で false であり、明示的な focus 試験でだけ有効になる（`../R5-modal-driver/ModalProbe.cs:159,270,2276,2375`）。この静的条件と実行ログを照合し、R5 の focus 試験との同時実行を除外した。

`BeginPlayerTurn` コールバックのスタックを調べ、AutoAct 内の同名コールバックと `XRLCore.PlayerTurn` の進入を区別する。後者はフォーカス待機より手前で数える。EndPlayerTurn も別に数える。画面左上の検証用マーカーは Unity の frameCount 下位 16 bit で、OBS の設定 fps と実際に届いたゲームの更新を区別する。

`results/<run-id>/receipt.json` にソースのハッシュ、実行結果、動画のパスを保存する。同じディレクトリにソースの写し、`runner.jsonl` にフォーカス切り替えと OBS 統計を保存する。長い動画は `results/clips/` にあり Git 対象外。Player.log は receipt が指す R0 の起動ディレクトリにある。

外部の人間の入力をログだけで完全には否定できないので、検証器の `external_input_unverified` は true のまま。`r4-auto-500` では本セッションの操作履歴と runner の入力なし記録を併用する。主張用走行の入力機器の運用規則を置き換えない。

## 再実行

検証用ゲームを起動してセーブをロードし、OBS の専用プロファイル・シーン `Qud probe 20260926` と `Qud probe window` 入力を用意する。通常の OBS 録画が動いている場合、runner は開始を拒否する。既存のローカル OBS 認証情報をプロセス内で読み、出力しない。

```sh
uv run --python 3.12 --with websockets python probes/R34-autoact/run_probe.py \
  --id r4-new-trial --mode r4 --log "$PLAYER_LOG"

uv run --python 3.12 --with websockets python probes/R34-autoact/run_probe.py \
  --id r3-new-focused --mode r3 --seconds 60 --focus focused --log "$PLAYER_LOG"

uv run --python 3.12 --with websockets python probes/R34-autoact/run_probe.py \
  --id r3-new-unfocused --mode r3 --seconds 60 --focus unfocused --log "$PLAYER_LOG"

uv run --python 3.12 python probes/R34-autoact/verify_run.py \
  --player-log "$PLAYER_LOG" --run-id r4-new-trial

uv run --python 3.12 python probes/R34-autoact/verify_run.py \
  --player-log "$PLAYER_LOG" --run-id r3-new-unfocused --expected-focus unfocused \
  --baseline-run-id r3-new-focused

uv run --python 3.12 python probes/R34-autoact/verify_capture.py \
  --clip "$RECORDING" --baseline-json "$FOCUSED_CAPTURE_JSON"

uv run --python 3.12 --with websockets python -m unittest discover -s probes/R34-autoact -p 'test_*.py'
dotnet run --project probes/R34-autoact/tests/PolicyTests.csproj
```

`--mode picker --focus mixed` は 10 回の方向ピッカーを開き、AppleScript で前面を往復する。フォーカス切り替えはユーザー許可済みの方式。前面の速度計測中にアプリを切り替えると、その走行を前面の基準値として使えない。

`--background-app Finder`（既定）または `OBS` は、非フォーカス試験の開始後に指定アプリを前面へ出す。被覆試験の窓はあらかじめ UI で配置する。この引数自体は窓の被覆を証明しない。

移動速度の比較では全体平均に加えて、実 heartbeat を端点にした約 60 秒の連続区間を検査する。末尾も 10 秒以上なら前面の平均速度の 80% 以上を要求する。録画の検証は別に行い、実更新頻度を全体と各 10 秒・60 秒区間で比較する。

長時間測定では `caffeinate -dis` と `NSAppSleepDisabled` を用いる。変更前の値とプロセス ID は `results/power-context.json` に残した。今回の検証終了後、元のキーがない状態に戻し、所有したゲーム・caffeinate・OBS の終了を確認した。OBS の元のプロファイル・シーン・動画設定・保存先も復元済み（`results/obs-restoration.json`）。再実行用の専用プロファイルとシーンは残している。現在の手順は起動済みプロセスに defaults を適用したことを記録しており、App Nap 内部状態の独立計測はしていない。


`--mode picker --focus mixed --drop-first-picker-push` が模擬損失の試験である。`verify_events.py --mode picker-retry` が、各回の損失・実投入・結果の対応とフォーカス変化を照合する。

`--mode hover --seconds 20 --focus unfocused` は、CTA から Modern Inventory を同期表示し、UI tick が所有する画面を期限で閉じる。実ホバーを試す場合は、実際のポインタ移動後に `verify_events.py --mode hover --expected-focus unfocused` で検査する。`hover_target` の座標は Unity のクライアント領域であり、ネイティブ窓全体の座標へ変換する。`hover_pointer.swift` はユーザーの明示許可を受けて実行済みで、クリックを発生させず、到達位置を測り、元のポインタ位置へ戻す。前景の証拠は `results/r3-hover-focused-pointer-20260927/`。背景の失敗試行も `results/r3-hover-unfocused-*/` に残している。

追加コードをゲーム内で再コンパイルした起動は `probes/R0-runtime/results/20260926T144927.722908Z-98528-steam/`。保存した `build_log.txt` と `Player.log` による R0 検証も合格した。Python 42 テストと C# の既存・追加ポリシーチェックが合格している。主メニューの Continue、隔離セーブの選択、現在の mod 構成でのロード、導入通知への Space は各プローブ開始前に CUA で行った（同起動の `bootstrap-inputs.json`）。開始手順全体の無人化を実証したものではない。

## 失敗・補助つき走行も保存する

| 走行 | 除外理由 |
|---|---|
| `r4-smoke-50` | 50 ターンだけなので R4 合格の証拠にしない |
| `r4-500` | 開始地点に試験用の 4 マス通路がなく、開始前に失敗 |
| `r4-500-fresh` | 500 ターン完走だが、通知へ CUA の Space を 2 回投入した補助つき走行 |
| `r3-short-focused` | 26 秒ごろから実フォーカスが外れた |
| `r3-short-unfocused` | 最初は実フォーカスあり。後に空腹通知でゲームが停止し、完了まで 111.9 秒かかった |
| `r3-baseline-20` | ラベルは focused でも全 heartbeat が実フォーカスなし。前面の基準値から除外 |
| `r3-unfocused-hour` | 最初の caffeinate プロセスが消えたため、23.9 秒で明示停止した設定確認の試行 |

runner は締切で停止を要求する。OBS のリクエストには 5 秒の期限を付け、録画停止が確認できない場合も receipt にエラーを残す。未対応のモーダルがゲームスレッドを塞いだ場合、停止要求ファイルは次の CTA まで読まれない。タイムアウト後にゲーム側の解除や Stomach の復元を成功とみなしてはいけない。画面を確認してモーダルを閉じるか、対象の隔離ゲームを終了し、当該走行を失敗として残す。


## 本番実行器への移植（2026-09-27）

goto / rest を本番ブリッジへ追加した。`.runtime/macros-live-20260927/run1/` の14操作で、到着、予算、未知セル、世界地図の拒否、既存exploreの継続を確認した。ガードの予算は歩数ではなく経過ゲームターンなので、移動速度によって1ターンに複数歩進む。

その後のClaude Code実プレイは16判断・200前進ターン・92.3秒で、地下1層まで進んだ。`.runtime/macros-live-20260927/claude-pilot/` に49行の台帳と検証結果を保存した。これは短いinteractive走行で、上記の決め打ち500ターンや無人1時間の合格とは区別する。非フォーカスの実ホバーは引き続き未達。

## 操作干渉を避けたホバー再試験（2026-09-27）

ユーザーがPCの操作を止めた後、同一プロセス・同じ所持品行・同じ座標へ5秒間ポインタを置き、非フォーカスと前面の2条件を各50秒測定した。両試行で、対象位置の最前面の通常窓がゲームであること、ポインタの到達と復元、クリック0件を確認した。測定中のheartbeatは各49件で、すべて指定したフォーカス条件を満たした。ゲームターン・移動・PlayerTurn・EndPlayerTurnは0のまま、R0検査も合格した。

| 条件 | 実測結果 | 証拠（`results/`） |
|---|---|---|
| 非フォーカス | tooltipは出ず、ホバーによるキュー投入を観測しなかった。成功を要求する既存検証器では `HOVER_NO_TOOLTIP`。 | `r3-hover-unfocused-pointer7-20260927/` |
| 前面の対照試験 | tooltip表示、実際のpointer exit、新しい `LookedAt` タスクの投入を確認。既存検証器も合格。 | `r3-hover-focused-control7-20260927/` |

比較記録は [r3-hover-comparison7-20260927.json](results/r3-hover-comparison7-20260927.json)。同じ座標と操作は前面で働くため、今回の非フォーカスの陰性結果を、窓の被覆やポインタ復元失敗と区別できる。ただし、Unity側のpointer enterは独立計測しておらず、別の画面・OS・フォーカス遷移での入力遮断を保証する結果ではない。非フォーカスでのキュー投入は再現していない。主張用走行の入力機器の運用規則は維持する。前面の試験が確かめたのもタスクの投入までで、タスクの実行やクエスト更新ではない。

直前のpointer5はFinderによる被覆、pointer6はポインタ復元失敗と途中のフォーカス変化があり、対照比較には使わない。ユーザーから、その時間帯にPCを操作していたとの申告があった。失敗ログは削除せず保存した。今回OBSの設定・録画には触れていない。
