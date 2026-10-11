# R0: 固定ビルド・隔離プロファイル・mod のロード

このディレクトリは `docs/exploration/06-recommendation.md` の R0 用の小さな実験です。`InitProbe.cs` と `manifest.json` を隔離プロファイルの `Mods/LlmOfQudProbeR0/` に配置します。ゲームが読む ID は句読点を除いた `LlmOfQudProbeR0` です。他の自作プローブを同時に使う場合だけ、その ID も許可します。自作以外の mod は `Local/ModSettings.json` で明示的に `Enabled:false` にします。未知の Workshop mod は既定で有効なので、事前検査が拒否します。

以下の例は R3/R4 と R5 を同時に読み込む隔離プロファイルです。`$PROFILE` は対象の隔離プロファイル、`$LOGS` は結果の保存先です。いずれのコマンドも、R12 で採取した固定ゲームのハッシュ一覧を読み取り専用で使います。

```sh
GAME="$HOME/Games/CavesOfQud-probe-2.0.211.56-build25520692/CoQ.app"
PROFILE="$HOME/Library/Application Support/Freehold Games/CavesOfQud-r34"
BASELINE="probes/R12-bridge/results/runtime-manifest.json"
APPMANIFEST="$HOME/Library/Application Support/Steam/steamapps/appmanifest_333640.acf"
LOGS="probes/R0-runtime/results"

python3 probes/R0-runtime/runtime.py check \
  --game "$GAME" --profile "$PROFILE" --baseline "$BASELINE" \
  --expected-buildid 25520692 --appmanifest "$APPMANIFEST" \
  --allow-mod LlmOfQudProbeR0 --allow-mod LlmOfQudProbeR34 \
  --allow-mod LlmOfQudProbeR5
```

事前検査は `Managed/*.dll` と `StreamingAssets/Base` の全ファイル集合および SHA-256 を固定一覧と比較し、欠落・追加・変更を拒否します。`ModSettings.json` と実際に発見できる mod の ID を照合し、許可外の有効 mod を拒否します。`PlayerOptions.json` と `Base/Options.xml` の既定値から 12 項目の実効値を予測し、§3.1 の指定と違えば拒否します。結果の `assembly_version` はハッシュに結び付いた固定一覧のラベルです。実際のアセンブリ版数は起動後の `[R0]` ログで独立に確認します。コピー内に Steam の buildid は埋め込まれていないため、`--appmanifest` は外部 Steam manifest の buildid を照合し、コピーとの結び付きは保護ファイルのハッシュで確認します。

起動をこの CLI に任せる場合は、同じ引数で `launch` を使います。`--dry-run` は起動せず計画だけを出します。Steam モードは `SteamAppId` と `SteamGameId` に `333640` を設定し、非 Steam モードは両方を消して `STEAM:NO` を付けます。実起動では毎回一意のディレクトリに `Player.log`、`launcher.log`、`launch-report.json` を作り、更新された `build_log.txt` を終了後にコピーします。`launch-report.json` は起動直後に PID と事前検査結果を保存します。

同じMacでの並行作業には **`launch-background`** を使います。この入口はUnityの `-batchmode` を必ず追加し、`launch_mode:batchmode` を起動記録へ保存します。事前検査・Steam設定・プロセスとログの管理は既存の `launch` と共通です。`launch --batchmode` も引き続き使え、既定の `launch` は従来のウィンドウ起動です。`-nographics` は追加していません。`check`・`verify`・各起動の `--dry-run` はゲームを起動しません。自動ロードの `llm-start.json` と保存終了の手順は [modの運用条件](../../mod/README.md#起動と終了)を参照してください。

```sh
python3 probes/R0-runtime/runtime.py launch \
  --game "$GAME" --profile "$PROFILE" --baseline "$BASELINE" \
  --expected-buildid 25520692 --appmanifest "$APPMANIFEST" \
  --allow-mod LlmOfQudProbeR0 --allow-mod LlmOfQudProbeR34 \
  --allow-mod LlmOfQudProbeR5 --steam-mode steam --log-dir "$LOGS"

python3 probes/R0-runtime/runtime.py launch \
  --game "$GAME" --profile "$PROFILE" --baseline "$BASELINE" \
  --expected-buildid 25520692 --appmanifest "$APPMANIFEST" \
  --allow-mod LlmOfQudProbeR0 --allow-mod LlmOfQudProbeR34 \
  --allow-mod LlmOfQudProbeR5 --steam-mode no-steam --log-dir "$LOGS"
```

各起動の直後に、その起動だけの `Player.log` と、その起動を含む `build_log.txt` を指定して検証します。`build_log.txt` は追記されるので、検証器は最後の `BuildLogger initialized` 以降を使います。

```sh
python3 probes/R0-runtime/runtime.py verify \
  --player-log "$PLAYER_LOG" --build-log "$BUILD_LOG" \
  --allow-mod LlmOfQudProbeR0 --allow-mod LlmOfQudProbeR34 \
  --allow-mod LlmOfQudProbeR5

python3 -m unittest discover -s probes/R0-runtime -p 'test_*.py' -v
```

検証器は最新のビルド区間で R0 の `Compiling 1 file...`、`Success :)`、最終ロード順に許可 ID だけがあることを求めます。`Player.log` の `[R0]` JSON から実際のアセンブリ版数、ロード済み ID、`Options.GetOption` の 12 項目を比較します。`init_error` や不一致は失敗です。R0 の完了判定には、**Steam と `STEAM:NO` の両方を実機で起動**し、各回の事前検査・ビルド・初期化ログを残す必要があります。事前検査や単体テストの成功だけでは、Workshop の実ロード挙動は証明できません。

API 根拠: `GameManager.cs:902-915` はオプションを先にロードし、続いて `ModManager.Init` を呼びます。`XRL/ModManager.cs:595-661` は設定、ローカル・埋込・Workshop の mod を読み、ロード順を出してから `[ModSensitiveCacheInit]` を呼びます。`XRL/ModInfo.cs:281-306` は ID の句読点を除き、`XRL/ModSettings.cs:16` は新規 mod を既定で有効にします。`XRL.UI/Options.cs:1095-1120` は保存値または既定値を返します。いずれも固定版 `2.0.211.56` の decompiled source に基づきます。

## 2026-09-26 の実機結果

両方の起動を終了させ、各回の `Player.log` と `build_log.txt` に対する `runtime.py verify` が合格した。Python 3.12.12 の 14 テストも合格した。

| 条件 | Workshop の検出 | 実際のロード | 証拠ディレクトリ |
|---|---|---|---|
| `STEAM:NO`、Steam 環境変数なし | steam isn't connected と明記し、購読情報を取得しない | R0 / R34 / R5 のみ | `results/20260926T120834.369589Z-91910-no-steam/` |
| `SteamAppId=SteamGameId=333640` | Steam API 初期化成功、購読 6 件を検出 | R0 / R34 / R5 のみ | `results/20260926T120918.776323Z-91951-steam/` |

各ディレクトリに起動計画・事前検査・生ログ・`verification.json` を保存した。両条件とも実行時のアセンブリ版数は `2.0.211.56`、12 項目の設定が一致し、R0 の 1 ソースの Roslyn コンパイルが成功した。事前検査は保護対象 613 ファイルと、外部 Steam manifest の buildid `25520692` を照合している。コピーと元の Steam インストール、通常のセーブ用プロファイルは変更していない。

これは起動構成の検査であり、新規キャラクター作成や主メニュー全体の無人操作を証明するものではない。生ログはローカルの `results/` にあり、Git の対象外。

## 2026-09-27 画面なしの起動から終了まで

固定版のUnity Player 6000.0.77f1で `--batchmode` を実機確認した。Unityの [Standalone Player仕様](https://docs.unity3d.com/6000.0/Documentation/Manual/PlayerCommandLineArguments.html) は、このモードで表示とユーザー入力を行わないとしている。ゲーム内のModern UIとそのコールバックは動作し、MCP経由で操作できた。Macの前面化については、別途 [読取専用の観測器](observe_background.swift) で起動前から終了まで測定した。対象ゲームの前面化通知、前面状態、画面上の窓数だけを記録し、他アプリの名称・画面内容・入力は保存しない。

| 検証 | 結果 |
|---|---|
| 自動起動・ロード・初回判断 | セーブID・ターン・SHA-256・mod構成を照合し、補助キーなしで最初のCTAへ到達。 |
| モーダル | 本番18ケースすべて合格。Yes/Noを60.260秒保持し、入力・取消・ピッカー・通常行動への復帰を確認。 |
| 保存・終了・再起動 | 正常走行3回。保存15→再ロード15→保存19、さらに同じ19ターンでの再保存と正常終了を確認。保存データのハッシュも照合。 |
| 通常操作と台帳 | 最初の2走行で11行動完了。各台帳の検証が合格し、PlayerTurn / EndPlayerTurn / UIタスク / 未知タスク / 残留キー / 未応答終了 / watchdogは0。 |
| Macへの干渉 | 正常3走行の2,697観測で対象の前面状態と画面上の窓数は0、前面化通知も0。OS入力は送信していない。最後の観測器では窓一覧取得の失敗も0として記録。 |
| 不正指示 | 異なるrun IDの終了要求を拒否。壊れた起動JSONは消費してエラーを記録し、判断要求を出さずプロセスを終了。 |

総合結果は [verification.json](../../.runtime/background-live-20260927/verification.json)。run2は開発モーダル試験、run3とrun5-idle-saveは開発モードなし。run1は保存後の終了フラグ不足で終了できなかった失敗記録を残し、正常走行には含めない。通常の非死亡終了と同じフラグ・ゾーンキャッシュ保存を追加し、後続3走行で正常終了した。run4-invalidは不正指示の負例である。これは決め打ちの統合試験で、LLMプレイ・M2の無人1時間の達成ではない。

検証器は `swiftc probes/R0-runtime/observe_background.swift -o /path/to/observer` でコンパイルし、ゲームの実行ファイルの絶対パス、起動後のPIDを書き込むファイル、結果JSONのパスを渡す。ゲーム起動前に開始し、結果JSONの作成を待ってから起動する。起動からPID記録までの前面化通知は実行ファイルのパスで照合する。結果は終了確認と各カウンタの0を照合する。窓一覧の取得不能・期限切れ・未観測は成功としない。観測器には入力や前面化の機能はない。

Pythonハーネス196件、R0ランチャー16件、C#基本76項目・モーダル134項目・背景起動ポリシー15項目と固定版DLLコンパイルが合格。RuffとSwiftLintも合格。Roslynは既存の非推奨API2件と状態・スレッド間変更に関する4件を保持し、新規候補の空配列割当て2件は除去した。実機のR0検査も正常走行ごとに合格した。

長時間走行では観測器の第4引数に監視秒数を指定できる（既定900秒、上限43,200秒）。期限だけで停止した場合は、ゲーム終了を確認した成功には数えない。

## 背景運転の再利用と証拠の再検査

セーブの隔離だけでは、OSの入力やフォーカスは隔離されません。並行作業中は画面なしの入口を使い、実ポインタ・キー入力・前面化を伴う試験は独立した実験環境か、操作を止められる時間に分けます。修正と検証はCodex、実際のプレイはClaudeという分担です。到達点は [06の現在地表](../../docs/exploration/06-recommendation.md) に照らし、起動成功・決め打ち試験・LLM走行の達成を分けます。

背景用のプロファイル、ハーネス、起動指示を準備した後、従来の起動引数を `launch-background` に渡します。次はR0・M1・R6を含む検証プロファイルの例です。許可modは実際の構成に合わせます。まず `--dry-run` で内容を確認できます。

```sh
python3 probes/R0-runtime/runtime.py launch-background --dry-run \
  --game "$GAME" --profile "${BACKGROUND_PROFILE:?背景用プロファイルを指定}" \
  --baseline "$BASELINE" --expected-buildid 25520692 \
  --appmanifest "$APPMANIFEST" --allow-mod LlmOfQudProbeR0 \
  --allow-mod LlmOfQudM1 --allow-mod LlmOfQudProbeR6 \
  --steam-mode steam --log-dir "$LOGS"
```

この入口が行うのは起動です。プロファイルの配備、ハーネスの起動、保存終了の指示、観測器の起動は [既存の運用手順](../../mod/README.md#起動と終了) に従います。前面化の観測器はゲーム起動前から開始し、今回のPIDを渡して終了まで測定します。通常起動を試すために、実行中の別のゲームを停止しません。

再検査に必要なファイルは、走行ごとに明示して保存します。`llm-start.json` は消費される前のコピー、`launch-report.json` と `Player.log` は同じ起動ディレクトリのもの、保存ファイルは終了後の `Primary.sav.gz` です。起動レポートとログは同じディレクトリに保ったままアーカイブ先を変更できます。検証器は記録中の `run_dir` と `-logFile` も照合します。最新時刻のディレクトリを自動選択すると並行走行を混ぜるため、パスを明示します。次のコマンドはファイルを読むだけで、ゲームや入力ツールを起動しません。

```sh
python3 probes/R0-runtime/verify_background.py \
  --start "$RUN/start.json" \
  --launch-report "$LAUNCH/launch-report.json" \
  --player-log "$LAUNCH/Player.log" \
  --desktop-observation "$RUN/desktop-observation.json" \
  --saved-game "$RUN/save-after/Primary.sav.gz" \
  --previous-player-log "$PREVIOUS_LAUNCH/Player.log"
```

`--previous-player-log` は前の走行から再開した場合だけ指定します。保存ID・ターン・ハッシュを次の起動指示と照合し、各走行のロード→保存→終了の順序、保存ファイルの実ハッシュ、プロセス終了、PIDの一致、前面化と窓の観測を検査します。行動回数と世界ターン差の一致は要求しません。ロード直後と最初の判断時点も区別します。同じターンで保存し直した場合は、保存内容のハッシュ更新で確認します。

窓一覧の取得失敗を記録しない旧観測器のログは、新しい検査では証拠不足になります。欠損を0に置き換えず、過去の結果も上書きしません。この検査は保存記録間の整合性を確かめるもので、記録自体の真正性は証明しません。起動・保存・終了の検査が通っても、台帳検証、R0の実行時検査、1時間のLLM走行が通ったことにはなりません。それぞれの結果を合わせて受入判定します。
