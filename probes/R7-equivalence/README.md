# R7: 直接 API と画面経由の同等性プローブ（LlmOfQud.ProbeR7）

> 状態: **9/10 件が一致、投擲は不一致**。2026-09-27、Look の実ジャーナル公開を含む9ケースで direct / ui の比較対象が一致した。投擲は両経路を実行できたが、消費エネルギーが957と1016で異なる。全体の判定は FAIL。直接投擲は本番の受入対象から外し、判定を緩めず原因調査の証拠を残す。

06-recommendation §5 の R7 を実装する、オペレーター専用の単独 mod と検証器。同じセーブから 2 回ロードし、同じ操作を直接 API（または shim）と画面経由で 1 回ずつ実行する。比較するのは、エネルギー、所持品、装備、能力値、技能、位置、ターン、乱数に左右されないメッセージとポップアップ本文の差分である。

## ファイル

| ファイル | 内容 |
|---|---|
| `mod/manifest.json` | ID `LlmOfQud.ProbeR7`（正規化後は `LlmOfQudProbeR7`）。Harmony なし |
| `mod/R7Probe.cs` | 本体。入口は `DataManager.SavePath("r7-command.json")` の 1 つだけ。待機中の EndPlayerTurn で読み、次の CTA で分岐を始める |
| `mod/R7Policy.cs` | ゲームに依存しない検査。ケース名、分岐、引数の許可リストと、答えてよいポップアップの規則 |
| `verify_r7.py` | Player.log の `[R7] {json}` を読み、ケースごとに direct と ui を比べる |
| `test_verify_r7.py` | 検証器のテスト（否定例を含む 47 件） |
| `tests/` | `R7Policy.cs` の C# テスト（62 項目） |
| `compile/` | mod のソースを固定版 DLL に対してコンパイルするだけのプロジェクト。配置しない |

## ケースと経路

| ケース | direct | ui | 比較から外すもの |
|---|---|---|---|
| BuyStat | `StatusScreen.BuyStat`（CTA 内。確認は UI tick が答える） | `Screens.ShowPopup` で Character ページを開き、`CharacterStatusScreen.HandleSelectPrimaryAttribute` | なし |
| Drink / Eat / Apply | `EquipmentAPI.GetInventoryActions` の `Command` 一致 1 件に `InventoryAction.Process` | Inventory ページを開き、`HandleQuickDrink` / `HandleQuickEat` / `HandleQuickApply` | なし |
| CommandGet | `FireEvent("CommandGet", TargetCell=自セル)` | `Keyboard.PushCommand("CmdGet")` をエンジンの PlayerTurn が処理 | なし |
| ThrowWeapon | `Combat.ThrowWeapon(p, null, TargetCell)` | `PushCommand("CmdThrow")` → `FireMissileWeapon`（PointerOver 2 回、CmdFire） | メッセージ、ポップアップ（命中とダメージは乱数） |
| CmdWait | 本番と同じ shim（`XRLCore.cs:1517-1540`） | `Keyboard.PushCommand("CmdWait")` | なし |
| SelectNode | `SkillsAndPowersScreen.SelectNode` | 生きた画面の該当行を選び、`SkillsAndPowersLine.Accept` | なし。技能の追加も必須 |
| EquipObject | `GameObject.EquipObject` → `CheckStacks` | 実際の所持品・装備欄に `HandleDragDrop` | なし。装備の追加も必須 |
| Look | `InventoryAction.Process:Look` | `CmdLook` → 対象セルを選択 → tooltip 確認 → Escape | ポップアップ。指定した実ジャーナル項目の追加は必須 |

10 ケースの経路は実装済み。投擲以外の9ケースは実機で比較対象の一致を確認した。投擲は消費エネルギーが不一致。Modern UI が無効など、必要条件を満たさない場合は `status:"unsupported"` と理由を記録する。検証器はこれを合格に数えない（`UNSUPPORTED`、全体は `INCOMPLETE`）。

ui 分岐の記録には `uiReceipt`（`path`、`engineSteps`、`completed`、`handlerInvoked`）が付く。direct 分岐には付かない。`directCall:false` は mod の定数なので、証拠として数えない。検証器が照合するのは、mod が実際に書く手順の文字列である（`verify_r7.py` の `UI_MARKERS`）。

- キー投入のケース: `Keyboard.PushCommand(<Cmd>)` と `consumed_by_PlayerTurn` がそれぞれ 1 回。ThrowWeapon はさらに `FireMissileWeapon PointerOver(` が 2 回、`FireMissileWeapon CmdFire` が 1 回。
- 画面のケース: `<ui 経路> invoked on UI thread`、`completion_signal`、`StatusScreensScreen.Exit`、`ShowPopup returned` がそれぞれ 1 回。加えて `handlerInvoked:true`。
- ui の手順に `direct_call`、`actions=`、`deadline` が 1 つでもあれば不合格にする。direct 側には `direct_call` の手順が必須。
- ui の path が表の ui 経路と一致しない記録、receipt のない記録、receipt 付きの direct 記録も拒む。

すべての記録に `mutatesLoadedSave:true` が付く。

## 捕捉点

- before: 分岐を始める CTA の中。
- after:
  - direct は、呼び出しが戻った直後。
  - キー投入の ui は、同じ PlayerTurn の EndPlayerTurn で、エネルギーが before より減った時点。エネルギーを消費しない Look は Looker を閉じた後の EndPlayerTurn。
  - 画面の ui は、画面が閉じて `ShowPopup` が戻った時点。
- 画面の ui 分岐は、正の完了シグナルを見てから画面を閉じる。BuyStat では Yes に続く Accept への応答、Drink / Eat ではエネルギーの減少、Apply では指定品の消費またはエネルギーの減少、SelectNode は Yes 応答と技能の追加、EquipObject は指定装備欄への装着である。
- 期限は UI tick 側で 20 秒とする。ゲームスレッドが画面やピッカーで止まっていても働く。
  - 期限を過ぎると `UI_DEADLINE` を記録し、自分の開いたモーダルだけを安全に閉じる。状態画面は `Exit()`、射撃用照準画面と Looker は Escape で閉じる。
  - その後の結果は `error` になる。
- 答え方を知らないポップアップが 5 秒残れば `UNHANDLED_POPUP` を記録する。そのポップアップには答えない。
  - このときゲームスレッドは戻らないので、`branch_result` は出ない。
  - Player.log に `"kind":"unhandled_popup"` か `"kind":"deadline"` が出て結果が続かなければ、親はセーブせずに終了し、その分岐を失敗として記録する。
- arm 時だけ `SkipPlayerTurn` と `Keyboard.KeyEvent.Set()` で待機中の入力ループを抜け、エネルギーを消費せず次の CTA に入る。測定中は立てない。投入したコマンドを PlayerTurn が読む必要があるため。

## 治具（使い捨てセーブ）

開発プロファイルで使い捨てキャラクターを作り、次を満たしてからセーブして終了する。セーブを変えるのはこの準備だけである。準備の記録は `results/<fixture>/setup.md` に残す。中身は、wish を含む準備の手順、GameID、`.sav` の SHA-256、使った blueprint 名である。

- AP が 1 以上。
- 自セルに拾える物がちょうど 1 つ。`Options.AskForOneItem` は No。
- 投擲武器を装備し、`(dx,dy)` に空いた可視のセルがある。
- 所持品の中に、Drink / Eat / Apply に使う物がそれぞれ blueprint 1 件ずつある。
  - 固定版の `Base/ObjectBlueprints` に存在を確かめた候補は、`Waterskin`（真水を入れる）、`Starapple`、`Witchwood Bark`。空白を含む名前も引数で渡せる。
  - 今回の固定治具では Apply に `SalveTonic`、Drink に `FullWaterskin` を使う。注射型トニックは `Tonic.cs:185–201` の経路で品を消費し、エネルギーは減らない。
  - Drink は真水にする。危険な液体の確認が出ると `UNHANDLED_POPUP` になる。
  - 能力値の差分は厳密に比べるので、効果が乱数で決まらない物を選ぶか、HP が満タンの状態で使う。

終了後にセーブのディレクトリ（`Saves/<GameID>/`）を丸ごと別の場所に写し、黄金コピーとする。`.sav` の SHA-256 を `shasum -a 256` で取る。**この値は親が申告するもので、mod は検証しない。** mod はロードの同一性として、GameID、ゾーン、ターン、`RandomSeed`、`NextRandomSeed` を記録する（`Stat.Rnd` には触れない。ロード時の再シードは `XRLGame.cs:1892-1897`）。

## 実機の手順（親が実行する）

1. R0 の隔離プロファイルで、`ModSettings.json` の `LlmOfQudProbeR7` だけを有効にする。本番の LlmOfQud、R5、R34、R12 は無効にする。これらもポップアップや CTA に応答するため、UI の証拠を汚す。
2. `ln -sfn "$REPO/probes/R7-equivalence/mod" "$PROFILE/Mods/LlmOfQudProbeR7"`。ディレクトリ全体ではなく `mod/` だけを置く。`tests/` と `compile/` の `.cs` をゲームにコンパイルさせないため。
3. 各ケースの各分岐で、次の順に行う。
   1. 黄金コピーをセーブのディレクトリへ戻し、SHA-256 を確かめる。
   2. R0 の起動器で起動し、Continue でロードする。
   3. ロード後は 1 手も動かさない。
   4. ゲームを前面に置いたまま（PlayerTurn は非フォーカスで止まる。`XRLCore.cs:737`）、`$PROFILE/r7-command.json` を 1 つ書く。

   ```json
   {"id":"r7-buystat-ui","case":"BuyStat","branch":"ui","saveSha256":"<64桁>","fixture":"r7-fixture-a","args":{"stat":"Strength"}}
   ```

   引数は、BuyStat が `stat`（主能力 6 種）、Drink / Eat / Apply が `blueprint`、ThrowWeapon が `dx` と `dy`（各 ±6 以内、両方 0 は不可）。SelectNode は `node`（技能クラス名）、EquipObject は `blueprint` と `bodyPart`、Look は `dx`、`dy`、`noteId` を渡す。そのほかのケースは `{}` とする。未知の欄は `control_error` になる。
   5. Player.log に `"kind":"branch_result"` が出たら、ログを写す。
   6. **セーブせずに終了する。**
4. 検証する。

   ```sh
   .venv/bin/python probes/R7-equivalence/verify_r7.py --player-log run1/Player.log --player-log run2/Player.log ...
   ```

   終了コード 0 は、10 件すべてが `EQUIVALENT` のときだけ。不足する分岐は `MISSING`、必要条件を満たさず実行されなかった分岐は `UNSUPPORTED` になり、全体は `INCOMPLETE` になる。`--case` で一部だけを指定した PASS（出力の `subset:true`）は、R7 の合格ではない。

## テスト（このリポジトリで実行済み）

```sh
cd probes/R7-equivalence && ../../.venv/bin/python -m unittest test_verify_r7   # 47 件 OK
dotnet run --project probes/R7-equivalence/tests/PolicyTests.csproj            # 62 項目 ALL PASS
dotnet build probes/R7-equivalence/compile/R7Compile.csproj                     # エラー 0（MSB3277 の警告 2 件のみ）
```

## 実装上の前提と確認範囲

- EndPlayerTurn が待機中にも呼ばれ、ポーリングが回る。R7 の上記8ケースでも確認した。
- `Screens.CurrentScreen=1` と `2` で、Modern の Character ページと Inventory ページが開く。BuyStat と所持品の各ケースで確認した。
- UI 分岐は、生きた画面の上で、エンジン自身の UI ハンドラを UI tick から呼ぶ。キー入力や NavigationController のイベントではない。要素は、エンジンと同じデータ型で組み立てる。
  - `CharacterAttributeLineData` のうち、ハンドラが読むのは `data.Name` だけである。
  - `InventoryLineData` は `go` と `category` を渡す。
- `HandleSelectPrimaryAttribute` は、`APIDispatch.RunAndWaitAsync`（`Task.Run`）の上で BuyStat を走らせる。direct 側はゲームスレッドで走る。
- `HandleQuick*` は `InventoryActionEvent.Check` を直接呼ぶ。そのため、`InventoryAction.Process` が発火する `InvCommandActivating` は発火しない。差が出ても正規化せず、そのまま不一致として報告する。
- BuyStat の確認は `Yes` / `No` の PopupMessage、結果の通知は `Accept` 1 つの PopupMessage として出る（R5 と R34 の観測による）。
- 治具の各物に、`Command` が `Drink` / `Eat` / `Apply` の InventoryAction がちょうど 1 つある。
- CmdWait の `Search` と ThrowWeapon は乱数を使う。同じシードからでも、UI が余分に乱数を使えば結果がずれうる。ThrowWeapon ではメッセージを比較しない。CmdWait では、メッセージの差をそのまま不一致として扱う。
- 画面側の ui 分岐は、非同期ハンドラの終了を直接には観測していない。完了シグナルの後、ポップアップがなく 300 ms 静かなことを確かめてから閉じる。
- 投擲は `FireMissileWeapon` を使う。build 8 で照準・確定・結果取得を実機確認した。期限取消の再検証は未実施。

## Look の治具

固定版の `RevealNoteOnLook` を使い、未公開の実ジャーナル項目が公開されることを両経路で比べる。`branch:"setup"` と `case:"Look"` で `noteId` を省くと未公開項目の候補だけを記録する。候補を選んで `noteId` と隣接セル `dx` / `dy` を渡すと、そのセルの唯一の可視 Description 物体へ part を追加する。準備後に保存し、同じ黄金コピーから両分岐を開始する。準備のログはゲームプレイの観測には渡さない。

## 共通治具の準備

`case:"CmdWait", branch:"setup", args:{}` は、隔離した使い捨てセーブ専用の固定治具を準備し、Primary へ保存する。AP=1、SP=1000、FullWaterskin・Starapple・SalveTonic・Leather Cap、装備済み ThrowingAxe、自セルの Dagger、未公開の実ジャーナル項目を RevealNoteOnLook で結んだ隣接 Dagger2 を作る。隣接する空いた可視セルを2つ要求し、既存の頭・投擲装備や同名所持品があれば拒否する。途中失敗後も同じロード状態での再実行を拒否するため、変更前にマーカーを付ける。ログは開発用の非公開証拠であり、LLM の観測に渡さない。保存後に終了して黄金コピーを作り、各分岐はそこからロードする。準備そのものは同等性の証拠に含めない。

## 実機結果（2026-09-27）

| ケース | 結果 | 証拠 |
|---|---|---|
| CmdWait | direct / ui の全比較差分が一致 | `.runtime/r7-live-20260927/wait-verification.json` |
| BuyStat | AP 1→0、Strength 22→23。エネルギー・通知・メッセージを含む全比較差分が一致 | `.runtime/r7-live-20260927/BuyStat-verification.json` |

BuyStat 初回は、画面の Exit によってゲーム側が再開し、UI の Exit 記録より先に結果のスナップショットが確定する競合で不合格だった。Exit／ポップアップ応答とその記録を、結果の収集と同じロックで囲んで修正した。初回の失敗は `receipt-race-BuyStat-*` に保存し、修正版 `.runtime/r7-build-3-20260927` で両分岐を同じ黄金セーブから再実行した。検証器の条件は緩めていない。

## 2026-09-27 の実機比較と修正

| ケース | 結果 | 証拠（`.runtime/r7-live-20260927/`） |
|---|---|---|
| CmdWait | 比較対象すべて一致 | `wait-verification.json` |
| BuyStat | Strength 22→23、AP 1→0、全比較一致 | `BuyStat-verification.json` |
| SelectNode | Acrobatics 追加、全比較一致 | `SelectNode-verification.json` |
| EquipObject | 頭に Leather Cap を装備、全比較一致 | `EquipObject-verification.json` |
| Drink / Eat / Apply | 消費とメッセージを含め全比較一致 | 各ケースの `*-verification.json` |
| CommandGet | 同じ床上の品を取得、全比較一致 | `CommandGet-verification.json` |
| ThrowWeapon | 両経路を実行。消費エネルギー957 / 1016が不一致。他の比較対象は一致 | `ThrowWeapon-verification.json`、`ThrowWeapon-direct/`、`ThrowWeapon-ui/` |
| Look | 実ジャーナル項目の追加、エネルギー1100不変、通知等が一致 | `Look-verification.json` |

技能一覧は可視範囲だけを行として生成するため、画面自身の `scrollContext.SelectIndex` で対象行を表示してから Accept する。StatusScreensScreen.Exit とポップアップ応答はゲームスレッドを再開させるので、その受領記録と完了処理の競合を防いだ。注射型トニックは品の消費を完了シグナルとして扱う。投擲は `Combat.ThrowWeapon` が `MissileWeapon.ShowPicker` を開くため、`PickTarget` ではなく `FireMissileWeapon` を駆動する。判定の項目・一致条件・必要な操作回数は緩めていない。

初期化直後に EndPlayerTurn がもう一度呼ばれると、測定前の `armed` 状態で `Before` を読んで例外になる問題も発見した。上記の旧ログには開始前エラーが1件ずつある。比較結果は次の CTA で取得した before / after に基づくが、エラーのない起動の証拠とはしない。build 7 では `armed` / `done` のコールバックを早期終了する。実機での例外解消は再検証待ち。失敗ログと各配布ソースの固定コピーを保存している。

全ケースを指定した最新集計は `.runtime/r7-live-20260927/all-cases-build8-progress-20260927.json`。9件が `EQUIVALENT`、投擲が `NOT_EQUIVALENT`、全体は `FAIL`（終了コード1）。旧8件の結果と開始前エラーも保存している。

build 7 の早期終了だけでは、入力待ちから次の CTA に入れず arm 状態で停止した。失敗を `armed-stall-ThrowWeapon-ui/` に保存し、build 8 で arm 時の明示的な入力ループ脱出を追加した。投擲とLookの4分岐で MODERROR・control_error がないことを `build8-startup-check.json` に記録した。

固定版 `GameObject.UseEnergy` は最終コストを乱数で±10%変動させる。初回比較では、投擲の差がこの範囲に入ることだけを確認し、乱数前のコストや着弾セルは未測定だった。Claude Opus 5.5（xhigh）の独立確認も踏まえ、失敗を保持し、直接投擲を本番受入から外した。当時の公開操作は move / attack / wait / explore のため、既存操作の削除はなかった。詳細は `.codex/artifacts/claude-m1-planning-throw-review-20260927.md`。一致までの反復や判定条件の緩和は行っていない。

## 消費エネルギーと着弾位置の追加測定

2026-09-27、同じ黄金セーブから各経路を1回ずつ実行した。`GetEnergyCostEvent` の観測点では、両経路とも基礎値・Amountが1000、割合・固定減算が0だった。`UseEnergyEvent` の実消費は直接957、画面1016で、以前の差を再現した。装備していたThrowingAxeは、どちらも指定したJoppaの(36,22)へ落ちた。両起動のR0検査は合格した。

証拠は `.runtime/r7-energy-live-20260927/{direct,ui}/events.json` と `verification.json`。固定版の `GameObject.UseEnergy` はイベントでのコスト計算後に乱数変動を加え、差し引いた後に `UseEnergyEvent` を送る。ただし、今回のコスト観測点より後に動くハンドラの変更や、乱数系列が分かれる箇所までは捕捉していない。乱数変動と整合する結果として記録し、完全な原因特定とはしない。乱数の読み出し・再シード・消費値の補正は加えておらず、厳密な同等性判定は引き続きFAIL。
