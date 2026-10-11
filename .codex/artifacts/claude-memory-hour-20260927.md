# 長期記憶・無人プレイ・再起動試験 — 2026-09-27

依頼は「長期記憶部分の実装→1時間ほどの無人プレイ→実地試験」。過去チャット `01a0dd63-9381-7bf3-95be-7d491590a1e6` と `01a0e055-54e9-7621-9c24-5f5d3ad84b48` を参照し、Codexが実装と検証、Claudeが全ゲーム判断を担当した。実装、62分13.5秒の無人走行、保存・ハーネス再起動後の10判断まで完了した。最初のクエストは未完了。

## 実装

- SQLiteに出典付きの目標・計画・事実・仮説・教訓・要約を保存。公開台帳をFTS5で検索し、元の出典を読み返せる4つの記憶MCPツールを追加した。
- 10回の判断ごとにClaudeの文脈を終了し、新しいプロセスが記憶と現在観測から続行する。最後の判断後の要約と、操作・会話の完了を運転器が検査する。
- 再起動・死亡復帰後の古いノートには再確認が必要であることを明示する。事実の保存には現在観測の引用を要求する。旧台帳のハッシュ鎖、索引、参照時点、同時書込みも検査する。
- 死亡復帰を含むエピソード16でClaudeが「死亡なし」と報告したため、走行後にゲームの死亡通知・復帰記録から累計を直接返す `memory_status.lifecycle` を追加した。通常のセーブ再読込を死亡と数えない。修正後の再起動試験では「今回0回、キャンペーン累計1回」を正しく区別した。

実装と使用法は [harness/README.md](../../harness/README.md#長期記憶とエピソード)。Jev、埋込み検索、Wiki接続は今回の実装に含めていない。

## 実測

| 項目 | 1時間走行 | 修正後の再起動試験 |
|---|---:|---:|
| 実時間 | 3,733.513秒 | 104.299秒 |
| 新しいClaude文脈 | 27 | 1 |
| 受理された判断 | 270 | 10 |
| 完了した判断 | 269 | 10 |
| 中断した判断 | 1（死亡復帰） | 0 |
| 結果に記録された前進ターン | 601 | 9 |
| ゲームターン | 19→264 | 264→273 |
| 死亡・チェックポイント復帰 | 各1回 | 各0回 |
| 巻き戻り | 380→24、356ターン喪失 | なし |
| 最終HP | 14/18 | 17/18 |
| 前面化通知・前面状態・画面上のゲーム窓 | すべて0 | すべて0 |

Watervineクエストを受注し、Red Rockへの到達段階を完了した。地下3層でhorned chameleonに倒され、復帰後に再探索した。最終保存はRed Rock地下2層、座標(6,16)、ターン273。クエストの「害獣発見・死体取得・持ち帰り」は未完了。

記憶の最終監査は866件の台帳記録、112版のノート、検索17回、出典の全文読出し1回を照合した。検索の最大実測は19.263ms。古い根拠による不正な事実保存2件を拒否し、記憶内部エラーはなかった。将来の記録の先取り、存在しない引用、別の復帰時点の事実引用は監査で検出されなかった。これは引用構造の検査であり、ノートの文章全体の真実性や記憶による攻略改善の証明ではない。

両走行とも `game_fault`、外部モーダル回答、modal watchdog、残留キー、PlayerTurn、EndPlayerTurnは0。画面観測はそれぞれ35,152・2,270サンプルで、窓照会失敗は0。保存更新とゲームexit 0を確認し、ゲーム、ハーネス、観測器、運転器、28回のClaude呼出しのプロセス群が残っていないことも確認した。

## 再起動で確認した限界

同じPrimaryセーブのハッシュ、キャラクターID、ターン264、位置、クエストを引き継いだ。旧ノート7節はすべて `needs_revalidation` となり、新しいrunのseq 1から開始した。死亡1回・復帰1回・喪失356ターンも旧台帳から読めた。

ただし再ロード直後は、保存前のHP14・energy1087からHP15・energy1187へ変化した。固定版2.0.211.56の `ActionManager.RunSegment` はCTA前に速度分のエネルギー加算と `BeginTakeActionEvent` を実行し、`Stomach` はそこで自然回復を処理する。この順序と整合するが、今回の走行で直接因果を計測したものではない。サブターン状態の完全一致は未保証で、変更していない。

また再起動試験の台帳はseq 11のrequestで終わり、`suspended` が届いていない。行動途中ではなく次の判断待ちだった。ゲーム側の `background_saved`（turn273、保存ハッシュ一致）・`background_quit` とexit 0で保存終了は確認したが、停止通知の到達保証は残件。台帳へ停止行を補作していない。終了後ログのThreadAbortExceptionとPlatformService Shutdown例外も残しており、全例外0とは主張しない。

## 検証・再現情報

Python全214テスト、記憶・運転器の18テスト、変更PythonのRuff、観測器のSwiftLintが合格。C#の通常ポリシー76項目・背景運転15項目・モーダル134項目、R0起動16テスト、固定版DLLでのコンパイルも合格した。コンパイルには既存のobsolete警告2件が残る。死亡集計の2回帰テストは修正前の失敗を確認した。

証拠の起点は [.runtime/memory-live-20260927](../../.runtime/memory-live-20260927/)。キャラクターの元プロファイルはコピーして使い、試験前後のセーブを `save-before`、`save-after-run1`、`save-after-run2` に保存した。

| 証拠 | 相対パス（証拠の起点から） |
|---|---|
| 1時間走行の要約・各呼出し | `play1/report.json`、`play1/episode-*.json` |
| 再起動試験の要約・呼出し | `play2/report.json`、`play2/episode-001.json` |
| 正式台帳 | `run1/ledger.jsonl`、`run2/ledger.jsonl` |
| 記憶と参照監査 | `memory/memory.sqlite3`、`memory-audit-final.json` |
| 現在観測・記憶 | `field/initial-state.json`、`field/initial-memory.json`、`field/final-state.json`、`field/final-memory.json` |
| フォーカス・窓 | `desktop.json`、`field/desktop.json` |
| 固定ビルド照合 | `runtime-verify-run1.json`、`field/runtime-verification.json` |
| 保存・正常終了 | `launch/*/Player.log`、`field/launch/*/Player.log`、各`launcher.log` |
| 終了プロセスとセーブ照合 | `completion-check.json` |
| 最終Pythonテスト | `tests-final.log` |

1時間走行は修正前の記憶実装を使い、ソースを `source-run1`、ハッシュを `source-hashes.json` に保存した。死亡集計を加えた後の実地試験は `field/source-hashes.json` の実装を使った。修正後の実装で1時間を再走したわけではない。

Claudeのtransportは `claude-cli`、各呼出しは有限時間のforeground print子プロセス。モデルは継続承認された `claude-opus-5-5`、effortは `xhigh`。全28回の初期化記録で同モデルとゲームMCPの8ツールだけが提示されたことを確認した。OAuthを使い、組込みツール、ローカル設定・hooks・plugins・他のMCPを与えていない。MCPプレイの承認済み手順として `--restricted` と厳格なMCP構成を使用した。一般的なask-claudeの `--safe-mode` はMCPも無効化するため、このプレイでは使用していない。

置換system promptは `play1/system.txt` と `play2/system.txt`。各回のuser promptは `Play episode N. Read persistent memory, then the current game. Execute ten accepted decisions, save the handoff summary, and end.`。プロセスIDは各 `episode-*.json` に保存した。認証付き一時MCP設定は終了後削除済み。保存した出力はツール呼出し・公開最終報告・使用量等で、思考内容や生の全ストリームは保存していない。使用したワークフローは [ask-claude](/Users/sankenbisha/.codex/skills/ask-claude/SKILL.md)。

今回の達成はClaude Codeによる無人開発試験と記憶の実機継続である。SDK直接走行、正式なM2/M3の全条件、OBS焼込み、クエスト完了、検索方式の比較評価は未達のまま。
