# Claude M1 actual game turn — lifecycle

Transport: `claude-cli`, foreground print. Exact requested model: `claude-opus-5-5`; effort: `xhigh`. This attempt was explicitly authorized by the user. No fallback or automatic retry.

Original task: perform exactly one actual Claude-chosen game action through the authorized MCP. Task prompt: [claude-m1-prompt-play-20260927.txt](claude-m1-prompt-play-20260927.txt); replacement system prompt: [claude-m1-system-play-20260927.txt](claude-m1-system-play-20260927.txt). Both mode 0600.

```json
{
  "status": "completed",
  "pid": 18988,
  "startedUtc": "2026-09-26T23:21:21Z",
  "elapsedSeconds": 20.3,
  "deadlineSeconds": 600,
  "exitCode": 0,
  "models": [
    "claude-opus-5-5"
  ],
  "effortRequested": "xhigh",
  "events": {
    "system": 8,
    "stream_event": 152,
    "assistant": 6,
    "rate_limit_event": 1,
    "user": 3,
    "result": 1
  },
  "tools": {
    "mcp__qud__get_state": 2,
    "mcp__qud__act": 1
  },
  "subtype": "success",
  "is_error": false,
  "turns": 4,
  "permissionDenialCount": 0,
  "survivingInvocationPids": [],
  "stderrPresent": false,
  "rawOutputRetained": false
}
```

Raw transcript was not requested and was not retained. Only allowlisted lifecycle metadata is saved here. Secret-like values are redacted before displaying candidate result text. A supervisor-reviewed synthesis will be appended separately. CLI completion alone does not prove gameplay; the supervisor must verify the ledger and game logs. The game session uses restricted mode, no built-in tools, no user/project/local settings, disabled hooks/skills/memory, and only the explicitly authorized local qud MCP. Safe mode disables MCP and cannot serve this game-playing contract. No global setting was changed.

## 実機との照合結果

M1 を達成した。Claude Code が実際に公開された3つの MCP ツールへ接続し、get_state を2回、act を1回呼んだ。使用モデルは `claude-opus-5-5`、指定 effort は `xhigh`。20.3秒で正常終了し、権限拒否は0、呼び出しに属するプロセスは残っていない。Claude が選んだ行動は `wait` で、可視の8体がすべて非敵対、HP が満タンであることを理由に挙げた。

ゲームログと台帳の両方で seq 1 の実行成功と次の CTA を確認した。世界ターンは3から4、CTA は1から2へ進み、位置 (37,22) と HP 18/18 は変わらなかった。行動直前のエネルギーは1076、直後は55。次の CTA での値は1055であり、直後の値とは別に記録される。PlayerTurn、EndPlayerTurn、UI タスク、未分類タスクのカウンタはすべて0だった。

台帳は request / decision / result / 次の request の4行。最後の seq 2 は判断待ちであり、未完の行動ではない。実際の LLM による判断は seq 1 の1回だけである。これより前の決め打ち待機は別の run と台帳に保存した。測定前にはロード画面の操作、I4 handoff、arm 後の入力待ちを解く KP_5 を使用している。新規開始や介入のない protocol 走行を実証したものではない。

証拠の場所:

- [照合結果](../../.runtime/m1-claude-20260927/verification.json)
- [台帳](../../.runtime/m1-claude-20260927/ledger.jsonl)
- [使用した Python ソースのハッシュ](../../.runtime/m1-claude-20260927/python-sources.json)
- [ゲームへ読み込んだ C# ソース](../../.runtime/m1-build-2/)
- [実機ログ](../../.runtime/launches/20260926T231303.930210Z-15767-steam/Player.log)
- [固定版・mod・設定の検証](../../.runtime/launches/20260926T231303.930210Z-15767-steam/verification.json)
- [別 run の決め打ち疎通](../../.runtime/m1-20260927/supervisor-wait.json)

Python の89テスト、C# ポリシーの32項目、固定版 DLL 参照のコンパイル、実機での Roslyn コンパイルが成功した。固定版の待機前処理に合わせた ConfusionLevel / FuriousConfusion には既存 API の obsolete 警告が2件ある。

ゲーム用の CLI 呼び出しには、MCP を無効にする safe-mode に代わり、restricted、組み込みツールなし、空の setting-sources、hooks / skills / auto memory 無効、明示した qud MCP だけを読む strict-mcp-config を使った。起動時に実際のツール一覧が3つだけであることを検査した。これはユーザーが承認した MCP ゲーム操作のための設定であり、グローバル設定は変更していない。根拠は [Claude Code の CLI リファレンス](https://code.claude.com/docs/en/cli-reference)。

R3 の実ホバー、R6 の hotload・復帰、R9 の200ターン観測監査、選択肢を持つ ModalDriver の移植は未完了である。今回の実 Claude は wait のみを選んだため、ほかの3行動を実 Claude で確認したとはしない。M1 としての達成範囲をこれらへ広げない。

Ledger head SHA-256: `cd4f6e8d67354e80b72b530f66f20fdea84618e333436d6b4fc33212f1e90550`

検証終了後、I4 handoff を記録し、所有するゲームとハーネスを終了した。Claude の2プロセスも終了済み。4040 / 8790 のリスナーが閉じたことを確認し、一時トークンと MCP 設定を削除した。通常プロファイルへの変更、コミット、push は行っていない。
