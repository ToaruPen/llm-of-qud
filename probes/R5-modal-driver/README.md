# R5 モーダル駆動プローブ（LlmOfQud.ProbeR5）

> 状態: 下書き。**未配置・未起動**。使った API は逆コンパイル結果（`/Users/sankenbisha/Dev/coq-decompiled_stable`、2.0.211.56）を grep して存在を確かめ、`ModalProbe.cs` のコメントに `file:line` で引いてある。構文は Roslyn（C# 9）の解析だけで確かめた（診断 0 件）。ゲームのアセンブリを参照した意味解析はしていない。最初の起動で出る `build_log.txt` が、実質的なコンパイル検査になる。

## 1. 目的

オーナー決定（2026-09-25）は次の三点である。

- Modern UI を画面に残す。
- Modern UI のモーダルは、ブリッジスレッドから `GameManager.uiQueue` 経由で検出し、読み、答える。
- Harmony は使わない。Harmony 2.2.2 は Apple Silicon のネイティブ起動で失敗するため。

R5 は、この方針（以下「方向 2」）が実機で成り立つかを確かめるプローブである。静的検証 F1〜F7 のレシピを、実際のゲームで一つずつ動かす。対応表は 08 §6.2 にある。

各プローブは次の順に動く。

1. wish がゲームスレッドでモーダルを開く。開く前に、背景の応答スレッド（answerer）を用意しておく。
2. answerer は約 1500 ms 後から UI スレッドでモーダルを分類し、Legacy 相当のテキストとして `[R5]` 付きでログに出す。
3. answerer はファミリーごとのレシピで答える。
4. ゲームスレッドは戻り値とビュースタックの復元を確かめ、`RESULT ... -> PASS|FAIL` を 1 行出す。

守っている規則は次のとおり。

- `Hide()` を先に呼ばない。例外は `probe:cancel`（R5-0d）だけで、非同期 void のキャンセル経路を観測するために、使い捨ての ShowYesNo に 1 回だけ意図して呼ぶ。
- 答える UI タスクの中で、トークンを確かめ直す。トークンは `onHide`、`commandCallback`、`selectCallback`、protected な `menucomplete`、チュートリアルの `PopupCompletion` のどれかである。
- 答えたトークンは全体の集合に登録し、同じモーダルに二度答えない。
- Unity のオブジェクトには UI タスクの中でしか触らない。例外は `probe:offthread`（R5-0e）で、観測のために 1 回だけ触る。

## 2. ファイル

| ファイル | 内容 |
|---|---|
| `manifest.json` | Mod マニフェスト。ID は `LlmOfQud.ProbeR5`。ゲームは `[^\w ]` を除いて正規化するので、実際の ID は **`LlmOfQudProbeR5`** になる（`XRL/ModInfo.cs:288`）。`ModSettings.json`、`ModAssemblies/`、`MOD_` シンボルはこちらの形を使う |
| `ModalProbe.cs` | プローブ本体（C# 9、Harmony なし）。`ProbeBootstrap`（UI tick の起動）、`Bridge`（UI 実行、分類、ログ）、`Answer`（レシピ）、`ProbeWishes`（wish） |
| `README.md` | 本書 |

実行時の仕組みは次のとおり。

- **UI tick**: `[ModSensitiveCacheInit]` が UI スレッドで `uiQueue` に自己再投入タスクを積む。タスクは 1 フレームに 1 回、`ConcurrentQueue` を排出する。同じフレームに 2 回走ったら `dupTicks` を数える（R5-0a）。
- **フォールバック**: tick が 2 秒以上動いていなければ、`gm.uiSynchronizationContext.Post` を 1 回ずつ使う（`EnsureTick` と同じ経路。`The.UiContext` はこのフィールド、`XRL/The.cs:41`）。ログの `via=tick` / `via=post` で、どちらを使ったかが分かる。ブリッジから `queueTask` / `executeAsync` は呼ばない（08 §3.1）。
- **`awaitTask` は使わない**（タイムアウトがないため）。

`// R5-UNCERTAIN: <claim id>` は、実機でしか決まらない点に依存している箇所の印である。11 か所ある。指す主張は 2 種類に限る。

- 08 §7 で「実機」の主張（7 か所）: C-F1-popup-21、C-F1-popup-17、C-F4-status-screens-21、C-F6-threads-hooks-12、C-F7-observation-11 / C-F3-pickers-26、C-F2-conversation-26、C-F7-observation-12。
- 08 §7 で「条件付き」で、その条件が実機でしか決まらない主張（4 か所）: C-F5-other-blocking-17、C-F1-popup-06、C-F3-pickers-23、C-F6-threads-hooks-14。印の本文に「条件付き」と書いてある。

## 3. ビルドと配置（隔離プロファイル）

手順は 04 §4.9 のレシピに従う。本番プロファイル（QudJP 有効、`Language=ja`）には触れない。

```sh
# 0) 変数
PROFILE="$HOME/Library/Application Support/Freehold Games/CavesOfQud-r5"
REPO="$HOME/Dev/llm-of-qud"
COQ="$HOME/Library/Application Support/Steam/steamapps/common/Caves of Qud/CoQ.app/Contents/MacOS/CoQ"

# 1) 隔離プロファイルの骨組み（Local は <savepath>/Local、Mods は <savepath>/Mods）
mkdir -p "$PROFILE/Local" "$PROFILE/Mods"

# 2) Mod フォルダは symlink にする（Roslyn が *.cs を再帰でコンパイルする。csproj や dll は置かない）
ln -sfn "$REPO/probes/R5-modal-driver" "$PROFILE/Mods/LlmOfQudProbeR5"

# 3) PlayerOptions.json（フラットな "キー": "値"。本番と同じ形式）
cat > "$PROFILE/Local/PlayerOptions.json" <<'JSON'
{
  "OptionAllowCSMods": "Yes",
  "OptionEnableMods": "Yes",
  "OptionShowAdvancedOptions": "Yes",
  "OptionModernUI": "Yes",
  "OptionModernCharacterSheet": "Yes",
  "OptionUseTiles": "No",
  "OptionAllowSaveLoad": "Yes",
  "OptionCapInputBuffer": "No",
  "OptionMusicBackground": "Yes",
  "OptionDisableAllIdleTileAnimations": "No",
  "OptionSifrahExamine": "No",
  "OptionSifrahRepair": "No",
  "OptionSifrahReverseEngineer": "No",
  "OptionSifrahDisarming": "No",
  "OptionSifrahHaggling": "No",
  "OptionSifrahRecruitment": "No",
  "OptionSifrahHacking": "No",
  "OptionSifrahItemNaming": "No",
  "OptionSifrahRealityDistortion": "No",
  "OptionSifrahPsychicCombat": "No",
  "OptionSifrahBaetylOfferings": "No",
  "OptionSifrahItemModding": "Never",
  "OptionSifrahWaterRitual": "Never",
  "OptionSifrahExamineAuto": "Never",
  "OptionSifrahRepairAuto": "Never",
  "OptionSifrahDisarmingAuto": "Never",
  "OptionSifrahRecruitmentAuto": "Never",
  "OptionSifrahHackingAuto": "Never",
  "OptionSifrahHackingLowLevel": "Never",
  "OptionSifrahRealityDistortionAuto": "Never",
  "OptionSifrahPsychicCombatAuto": "Never"
}
JSON

# 4) ModSettings.json（プローブだけを有効にする。本番の既知の Mod はすべて無効）
cat > "$PROFILE/Local/ModSettings.json" <<'JSON'
{
  "LlmOfQudProbeR5": { "Title": "LLM of Qud - R5 modal driver probe", "Enabled": true },
  "QudJP":          { "Enabled": false },
  "lang.japanese":  { "Enabled": false },
  "langjapanese":   { "Enabled": false },
  "QudJP_PoC":      { "Enabled": false },
  "LLMOfQud":       { "Enabled": false },
  "TW_Endless_EXP": { "Enabled": false },
  "1526211226":     { "Enabled": false },
  "2281179694":     { "Enabled": false },
  "2281679090":     { "Enabled": false },
  "2357196184":     { "Enabled": false }
}
JSON
```

各キーの意味と注意は次のとおり。

- **Modern UI**: `OptionModernUI` と `OptionModernCharacterSheet` は明示的に Yes にする（`Screens.cs:45`、`UIManager.cs:55`）。
- **C# Mod の許可**: `OptionAllowCSMods=Yes` がないと、`.cs` を含む Mod は Disabled になる（`ModInfo.cs:126-129`）。
- **入力とフォーカス**: `OptionCapInputBuffer=No` にすると、キューが 3 件以上でも入力を捨てない。`OptionMusicBackground=Yes` で `Application.runInBackground` が有効になる（C-F6-threads-hooks-10）。R5-0b では No でも 1 回走らせる。
- **IdleWait**: `OptionDisableAllIdleTileAnimations=No`（08 §3.9）。Yes だと PlayerTurn の `Keyboard.IdleWait()` に期限がなくなる。
- **Sifrah**: 08 §3.9 に合わせ、bool は `No`、文字列は `"Never"` にする。
  - 文字列のうち `SifrahItemModding` と `SifrahWaterRitual` は、空なら `"Never"` を返す（`XRL.UI/Options.cs:941-956, 1016-1031`）。
  - `*Auto` と `SifrahHackingLowLevel` は、`Yes` なら `"Always"`、`No` か空なら `"Ask"` に読み替え、それ以外の値はそのまま返す（`:755-770`、`:912-927`）。`"Never"` は `SifrahHackingLowLevel` の分岐に実在する（`XRL.World.Parts/CyberneticsTerminal2.cs:208-225`）。
  - `probe:talk` は任意の NPC の選択肢を選ぶ。`SifrahWaterRitual` が `"Always"` だと、問いなしで Sifrah に入る（C-F2-conversation-19）。既定値はコードからは読めない（08 §3.9）。
- **他の Mod**: 新しい Mod の既定は `Enabled=true` である。Workshop にはもう一つ、ID が不明のアイテム（`3386397574`）がある。初回起動の後に `build_log.txt` の `==== FINAL LOAD ORDER ====` を見て、プローブ以外が載っていれば `ModSettings.json` に false で追記して再起動する。QudJP が載ると Harmony の EACCES が出て、「例外なし」の基準を壊す。
- **未解決の問い**: 事前に書いた JSON が初回起動でそのまま採用されるかは、04 §6 で未解決の問いである。初回起動の後、Options 画面で次を目で確かめる。
  - Modern UI、Modern Character Sheet、C# Mod 許可、Cap Input Buffer、Music Background。
  - Disable All Idle Tile Animations が No であること。
  - Sifrah の各項目が No / Never であること。とくに水の儀式（Water Ritual）。

## 4. 起動

Harmony を使わないので、ネイティブ（arm64）で起動する。`arch -x86_64` は付けない。

```sh
export SteamAppId=333640 SteamGameId=333640
"$COQ" -savepath "$PROFILE" -logFile "$PROFILE/Player.log"
```

ログの置き場所は次のとおり。

- `Player.log`: `-logFile` を付けたので `$PROFILE/Player.log` に出る。付けなければ `~/Library/Logs/Freehold Games/CavesOfQud/Player.log` になる。
- `build_log.txt`: `$PROFILE/build_log.txt`（SavePath）。

起動直後のビルド確認:

```sh
grep -nE '=== LLM OF QUD - R5 MODAL DRIVER PROBE ===|Compiling [0-9]+ files?|Success :\)|COMPILER ERRORS|FINAL LOAD ORDER' "$PROFILE/build_log.txt"
grep -n 'INFO - \[R5\]' "$PROFILE/Player.log"
```

起動直後の `[R5]` に、`init thread=ui`、`tick seeded gen=1 onUI=True reason=init`、`tick alive gen=1 thread=ui ctl=... runInBackground=... focused=... bThreadFocus=...` の 3 行が出ることを期待する。`uiSynchronizationContext` の設定（`GameManager.cs:868-869`）は、同じ AwakeRoutine の `ModManager.Init()`（`:912`）より前にある。

- **最初の合格条件**は、起動時か最初の wish の時点（`tick seeded ... reason=wish:...`）で `tick alive` が出ることである。
- **R5-0c** は、この `tick alive` 行の `ctl=` で判定する。キーを押す前に出る行なので、人が触らない状態の値が読める。予想は `Mouse`（`ControlManager.cs:337`）。起動からこの行が出るまで、キーボードにもゲームパッドにも触らない。

## 5. ゲーム内の準備

1. New Game → **Roleplay**（Tutorial は選ばない）→ 任意のキャラクターで Joppa から始める。Pregen でよい。Roleplay はチェックポイントが有効なので、`probe:death` の前提になる（`XRL/CheckpointingSystem.cs:165-173`）。
2. 開始後、所持品が 2 個以上あることを確かめる（`probe:pickitem` の前提）。
3. プローブ中は、ゲームのウィンドウにフォーカスを置く。例外は `probe:focus` / `probe:focus:force` / `probe:focus:play` の間で、指示に従ってフォーカスを外す。
   - フォーカスを置く運用は、プローブを安定させるためだけのものである。無人のエージェントはフォーカスなしで動くので、R5-0b が方向 2 の前提を判定する（§10.3）。
   - **マウスカーソルは地図の外**（画面の端や HUD の上）に置く。`"PickTarget"` ビューは WantsTileOver が真で、実マウスの `PointerOver` がカーソルを動かす（F3 §3.0）。
4. wish は `Ctrl+W`（CmdWish、既定のキー）で入力欄を開き、文字列を打って Enter で確定する。
   - 打鍵は InputSystem を通るので、`ControlManager._activeControllerType` が Keyboard になる（`ControlManager.cs:846-861, 809-835`）。この値は、別の機器が使われるまで Keyboard のままである（`:848-851, 811`）。
   - 人が触らないエージェントでは Mouse のままなので、AskNumber は別の表面に入る。M の AskNumber は `probe:asknumber:mouse` で確かめる（§10.1）。

## 6. wish の実行順

一つ打つたびに、`RESULT` 行が出るまで待つ（最長で約 25 秒）。その後、1 マス移動して UI が応答することを確かめてから次へ進む。どの wish も `BEGIN r5=<ID>` を出すので、ログを 08 §6.2 の ID に対応付けられる。

### 6.1 R5-0（ゲート。08 §6.1: R5-0 が不合格なら、ほかのプローブは数えない）

| # | wish | R5 ID | 何をするか |
|---|---|---|---|
| 0-1 | （起動するだけ） | R5-0c | `tick alive ... ctl=<値>` を読む。キーに触る前の値 |
| 0-2 | `probe:reload` | R5-0a | エンジンの wish `reload` で hotload を起こす（`XRL.World.Capabilities/Wishing.cs:1006-1013`）。3 秒後に世代番号と `dupTicks` を比べる |
| 0-3 | `probe:offthread` | R5-0e | UI タスクで `PopupMessage` の窓を取り、ブリッジスレッドから `activeSelf` を 1 回読む（try/catch） |
| 0-4 | `probe:focus` | R5-0b（基準） | wish の後 5 秒以内にフォーカスを外し、35 秒外したままにする。緩和策なし |
| 0-5 | `probe:focus:force` | R5-0b（緩和策） | フォーカスがあるうちに UI タスクで `runInBackground=true` にし、毎 tick `XRLCore.bThreadFocus=true` に書き直す。その後フォーカスを外す |
| 0-5a | `probe:focus:play` | R5-0b-play（非フォーカスでの進行） | `probe:focus:force` の緩和策に加え、毎 tick `GameManager._focused=true` をフィールドへ直接書く（setter を通さないので `ClearInput` が走らない）。wish の後 12 秒以内にフォーカスを外し、`RESULT` 行（wish から約 35 秒後）まで外したままにする。非フォーカスの間、1 秒に 1 回だけ UI タスクから `CmdWait` を積み（モーダルなし、P' が真、入力キューが空のときだけ）、`XRLGame.Turns` が進むかを数える。敵が見えない場所で、捨ててよいゲームで行う。終わったら `mitigation off; ...` 行を待って再フォーカスし、1 マス動く |
| 0-6 | 0-4 と 0-5 を `OptionMusicBackground=No` で繰り返す | R5-0b | Options 画面で切り替える。切り替えが効かないときは PlayerOptions.json を書き換えて再起動する |
| 0-7 | `probe:cancel` | R5-0d | 使い捨ての ShowYesNo を開き、UI タスクで `Hide()` を先に 1 回だけ呼ぶ。**最後に単独で実行し、その後ゲームを再起動する**（プロセスが落ちうるうえ、`"PopupMessage"` がスタックに残る） |

### 6.2 ファミリーのプローブ

| # | wish | R5 ID | 何をするか |
|---|---|---|---|
| 1 | `probe:yesno` | R5-F1a | `Popup.ShowYesNo`（同期経路 S）。No と答える |
| 2 | `probe:askstring` | R5-F1d | `Popup.AskString(..., WantsSpecificPrompt:"RETIRE")`（非同期の複製経路 A）。入力欄に RETIRE を入れて `OnInputSubmit` |
| 3 | `probe:pickoption` | R5-F1b | `Popup.PickOption` の 4 択。`option:2` を選ぶ |
| 4 | `probe:stale` | R5-F1b（古いトークンの拒否） | 同期の PickOption を 2 回続けて開く。#1 に `option:1` で答えた後、#1 の Snap を #2 に当て直し、`token-mismatch` で拒否されることを確かめる。その後 #2 に `option:2` で答える |
| 5 | `probe:asknumber:mouse` | R5-F1e（エージェントの表面） | UI タスクで `_activeControllerType=Mouse` にしてから `Popup.AskNumber(Start 3, 0..10)` → **AskNumberScreen**。7 と答える。終わったら finally の UI タスクで元に戻す |
| 6 | `probe:asknumber:kb` | R5-F1e（複製の表面） | Keyboard に強制する → 複製ポップアップの経路 |
| 7 | `probe:asknumber` | R5-F1e | 強制しない。wish を打鍵した直後なので Keyboard になり、複製の経路に入る（参考） |
| 8 | `probe:asknumber:pad` | R5-F1e | Gamepad に強制する → AskNumberScreen の経路。ボタンの表記も変わる（`PopupMessage.cs:363-372, 555-`） |
| 9 | `probe:pickitem` | R5-F3e | `PickItem.ShowPicker(所持品)`（PickGameObjectScreen）。最後の品を選ぶ |
| 10 | `probe:pickdir` | R5-F3a | `PickDirection.ShowPicker`。`Keypad6` を 1 回押して "E" |
| 11 | `probe:picktarget` | R5-F3b | `PickTarget.ShowPicker`。`PointerOver` を 2 回送り、`CmdFire` で東隣（なければ西隣）のセルを選ぶ |
| 11a | `probe:imposter` | R5-F3c | 前提: `OptionUseTiles=Yes` と imposter 有効（`Options.UseImposters`）。ASCII の起動では `RESULT FAIL precondition: needs tiles and imposters ...` になる。`probe:picktarget` と同じ PickTarget を開き、同じ手順で東隣（なければ西隣）へ `PointerOver` を 2 回送る。`CmdFire` の前に、UI タスクで `TextConsole.CurrentBuffer` を `TextConsole.BufferCS` のロック下で走査し、`Prefabs/Imposters/TargetReticle` を持つセルが 1 つだけで、押し付けた座標と一致することを確かめる。AfterRender のコールバックでも 1 回数える（参考。AfterRender は PickTarget が照準を足す前に走るので 0 が予想） |
| 12 | `probe:field` | R5-F3d | `PickTarget.ShowFieldPicker`（public static。Force Projector は要らない）。`Keypad5` で開始、`Keypad6` で 1 マス延ばし、`Keypad5` で確定 |
| 13 | `probe:field:cancel` | R5-F3d | `Keypad5` で開始、`Escape` で消去、もう一度 `Escape` で中止 → null |
| 14 | `probe:conv` | R5-F2b（一部） | `Popup.ShowConversation` の合成ノード。`option:1` を選ぶ |
| 15 | `probe:status` | R5-F4a | `Screens.ShowPopup("Factions")`（StatusScreensScreen）。`Exit()` で閉じる |
| 16 | `probe:book` | R5-F5b | `BookUI.ShowBook("page", "title")`（BookScreen）。ページ数を読んで `Cancel()` |
| 17 | `probe:talk` | R5-F2a | 同じゾーンの `Mehmet` の隣へ移動し、`AttemptConversation()`。最初の 3 回は Target が空でも `End` でもない選択肢を選び、次のノードで token と `LastChoice` を検証する。その後は Cancel。見つからなければ `probe:talk:<Blueprint>` |
| 18 | `probe:trade` | R5-F5a（取消だけ） | 同じゾーンの `Tam` の隣へ移動し、`TradeUI.ShowTradeScreen`。中身を読んで `Cancel()` で閉じる。見つからなければ `probe:trade:<Blueprint>` |
| 19 | `probe:conv:<ConversationID>`（任意） | R5-F2a | エンジンの wish `conv:` で会話を開く（話者は地図の外）。答え方と検証は `probe:talk` と同じ |
| 20 | `probe:tutorial` | R5-F5d | `TutorialManager.ShowIntermissionPopupAsync`（終局のコーダと同じ呼び出し）を開き、ゲームスレッドが Task を待つ。answerer はトークンごとに 1 回だけ Accept を押す |
| 21 | `probe:endturn` | R5-F6a | EndPlayerTurn のコールバックを 1 回だけ登録し、次の反復（`Energy >= 1000`）で `Command:CmdWish` を積む。wish の入力欄が出れば「読まれた」 |
| 22 | `probe:endturn:spent` | R5-F6a | 仕掛けた後、オペレーターが 1 マス移動する。エネルギーを使った反復で積み、捨てられることを確かめる |
| 23 | `probe:endturn:run:<probe>`（任意） | 08 §6.1 のトリガー | 次の EndPlayerTurn（`Energy >= 1000`）で `probe:<probe>` をコールバックから起動する |
| 24 | `probe:map` | R5-F7a | AfterRender のコールバックを 1 回だけ登録し、次の描画でバッファの字数を数える。何も出なければ 1 マス動く |
| 25 | `probe:all` | — | 1〜6、9〜18 を続けて実行し、最後に `[all] SUMMARY pass=N/16` を出す |
| 26 | `probe:death` | R5-F1f | `CheckpointingSystem.ShowDeathMessage`。"Retire character" → RETIRE の入力欄を Cancel → メニューに戻る → "Reload from checkpoint"。**チェックポイントを読み直すので、最後に実行する** |

補足:

- `Mehmet` と `Tam` は、コードではなくデータ（ブループリント ID）の推定である。見つからないときは `RESULT FAIL precondition` になる。そのプローブは、正しいブループリントを引数にして打ち直す。
- `probe:talk` の選択肢は、クエストの開始などの副作用を持ちうる。捨ててよいゲームで実行する。
- 以前の失敗でモーダルが残っていると、次のプローブが汚れる。`TIMEOUT` が出たら §8 の手当てをしてから次へ進む。
- R5-F7b（UI スレッドでの読み取りの負荷）は、専用の wish を持たない。すべての `DETECT` 行に `readMs=` が付き、`answerer exit` 行に `uiread maxMs=` が出る。

### 6.3 実装しない R5 ID（範囲外）

| R5 ID | 理由 |
|---|---|
| R5-F1c（UI スレッドの PickOptionAsync で出る複製） | インベントリ画面の操作が要る。複製の窓 `"PopupMessage #N"` の検出と応答は、`probe:askstring` と `probe:asknumber:kb` が同じ窓で確かめる |
| R5-F2b の残り（`AllowTrade:true` と `Look` の -3） | Trade と Look は会話から別の画面に進むので、F5 と Looker の確認が先に要る。`probe:conv` は `option:N` の戻り値だけを確かめる |
| R5-F3f（Looker、FireMissileWeapon） | 08 §8.1(3) の運用では、エージェントはこれらの画面を開かず、API を直接呼ぶ。別のプローブで扱う |
| R5-F4b（BuyStat の確認） | 答え方は ShowYesNo の `No` と同じで、`probe:yesno` が同じ経路を確かめる。AP を持たせる準備が要る |
| R5-F4c（キー割り当ての捕捉） | 手動の準備が要り、エージェントはこの画面を開かない運用にする（08 §1） |
| R5-F5a の申し出（数量の設定と HandleOfferTrade） | 取引を成立させると、ゲームの状態が変わる。`probe:trade` は読み取りと `Cancel()` だけを確かめる |
| R5-F5c（端末） | Joppa の初期状態では開けない（08 §6.2） |
| R5-F5e（終局のコーダ） | 遅い段階でしか開けない。同じ `ShowIntermissionPopupAsync` の応答は `probe:tutorial` が確かめる |
| R5-F5f（EmbarkBuilder と主メニュー） | ゲームの外（主メニュー）にいる間は wish を打てない。起動時に `[ModSensitiveCacheInit]` から仕掛ける別の起動方式が要る |
| R5-F6b（mod の MonoBehaviour の Update） | 第二案である。UI tick が R5-0 を通れば要らない（08 §6.2） |

R5-F3c（照準 imposter の走査）は、当初は「実行プロファイルが ASCII で imposter が出ない」として範囲外だったが、2026-09-26 に `probe:imposter`（§6.2 の 11a）として実装し、タイル表示の走行 4 で PASS した（`results/2026-09-26-run4.md`）。

## 7. 合否基準

### 7.1 全プローブ共通

次の四つがすべて成り立てば PASS とする（R5-0 の行は §7.3 の基準を使う）。

1. `RESULT expected=<期待値> got=<期待値> value=ok views=restored ... targetMatched>=1 answers>=1 blockedDouble=0 timedOut=False -> PASS` が出る。
2. `BEGIN` から `RESULT` までの間に、`Player.log` に `Exception`、`NullReferenceException`、`AggregateException`、`UI work threw`、`answerer EXCEPTION`、`ERROR:` がない。
3. `RESULT` の後、1 マスの移動と `Ctrl+W` の入力欄の開閉が普通にできる（UI が応答している）。
4. 画面にモーダルが残っていない。これはオペレーターの目視メモで確かめる。

各項目の意味:

- `views=restored`: 開く前と戻った後で、ビュースタックが一致する。`LEAKED` は、async void のキャンセル（`Popup.cs:801,908-910`）で `"PopupMessage"` が残った印である（C-F1-popup-06）。
- `targetMatched>=1`: answerer が目的のモーダルを認識した。0 なら、プローブの述語が外れている（プローブ側の不具合）。
- `blockedDouble=0`: すべてのガードを通った後で、答え済みのトークンにもう一度答えようとしたことがない。トークンの登録は、ガードをすべて通った直後、UI タスクの中で行う。
- `answers>=1`: 返り値が answerer の応答によるものであり、黙った既定値ではない。
- `outcome=accepted`: 同じ UI タスクの中で `onHide` がトークンでなくなった（08 §2.0 tok(w)）。後ろに付く `cbNulled=True` / `selNulled=True` は、呼んだコールバックが null になったことを示す同値の確認である。

ログは次の順に出る。

1. `BEGIN r5=<ID>`（ゲームスレッド、`[<名前>][game]`）
2. `answerer armed`
3. `DETECT kind=... readMs=<n>`（複数行。読み取ったテキストが続く。ポップアップは `token=#<n>` と `D(w) candidates=...` を含む）
4. `ANSWER ... outcome=accepted`（ピッカーは `PUSH ... outcome=pushed`）
5. `target answered`
6. `answerer exit ... uiread maxMs=<n>`
7. `RESULT`

### 7.2 プローブ別

| wish | 期待する DETECT | 期待する ANSWER / PUSH | RESULT の expected |
|---|---|---|---|
| `probe:yesno` | `kind=popup`、`window=PopupMessage path=S`、`Buttons: [Yes <Yes/..>] [No <No/..>]` | `ANSWER popup command=No ... outcome=accepted cbNulled=True` | `No`（黙ったキャンセルなら Yes が返る） |
| `probe:askstring` | `kind=popup`、`window=PopupMessage #N path=A`、`Input: "" ... WantsSpecificPrompt=RETIRE`、ボタンは `keep/Submit`、`Cancel`、`CmdOptions` | `ANSWER popup input="RETIRE" ... outcome=accepted selNulled=True readBack="RETIRE"` | `RETIRE`（キャンセルなら `""`、失敗なら null） |
| `probe:pickoption` | `kind=popup path=S PopupID=null`、`<option:0>`〜`<option:3>`、`Cancel` ボタン | `command=option:2 ... accepted` | `2`（既定なら 0、Escape なら -1） |
| `probe:stale` | `probe:stale #1` と `probe:stale #2` の二つの `kind=popup path=S`。token の値が違う | `command=option:1 ... accepted`、続いて `stale-answer rejected outcome=token-mismatch(onHide) oldToken=#a newToken=#b`、最後に `command=option:2 ... accepted` | `1,2,stale=token-mismatch`。`STALE ANSWER NOT REJECTED` が出たら FAIL |
| `probe:asknumber:mouse` | `controller ... expectedSurface=AskNumberScreen`。`kind=asknumberscreen`（`isCurrentWindow=True`）。その前に `asknumberscreen-notready` が出てもよい | `ANSWER AskNumberScreen n=7 ... accepted` | `7`。`controller restored=<元の値>` が出ること |
| `probe:asknumber:kb` | `expectedSurface=copy-popup`。`kind=popup path=A`、`RestrictChars="0123456789"`、`Input: "3"` | `input="7" ... accepted` | `7`。`controller restored=...` |
| `probe:asknumber` | 打鍵の直後なので `expectedSurface=copy-popup`（`controller before=Keyboard`） | `input="7" accepted` | `7` |
| `probe:asknumber:pad` | `kind=asknumberscreen` | `AskNumberScreen n=7 accepted` | `7`。`controller restored=...` |
| `probe:pickitem` | `kind=pickgameobject`、`raw=N`、品のブループリントの一覧。`pickgameobject-notready` が先に出てもよい | `PickGameObject target=<bp> ... accepted` | 最後の品の `<bp>` |
| `probe:pickdir` | `kind=picker mode=PickDirection text="[R5] probe:pickdir | [Select a direction]" P=True inputEmpty=True` | `PUSH Keypad6 ... outcome=pushed` | `E` |
| `probe:picktarget` | `kind=picker mode=PickCells P=True` | `PUSH PointerOver#1(x,y)`、`PUSH PointerOver#2(x,y)`、`PUSH Command:CmdFire` がどれも `pushed` | `(x,y)`（`player=... target=...` の行と一致） |
| `probe:imposter` | `player=(px,py) target=(x,y) UseTiles=True UseImposters=True`、`kind=picker mode=PickCells P=True`、`IMPOSTER-INITIAL cells=1 at=(px,py) expected=(px,py) ...`（参考） | `PUSH PointerOver#1(x,y)`、`PUSH PointerOver#2(x,y)` が `pushed`、`IMPOSTER cells=1 at=(x,y) expected=(x,y) ... -> ok`、`IMPOSTER-AFTERRENDER cells=0 ... (informational; cells=0 expected: ...)`（`UNEXPECTED:` が出たら所見として報告）、`PUSH Command:CmdFire ... pushed` | `RESULT expected=(x,y) got=(x,y) imposter=ok value=ok ...`。`imposter=MISMATCH` か `imposter=none` なら FAIL。前提不成立は `RESULT FAIL precondition: needs tiles and imposters ...` |
| `probe:field` | `kind=picker mode=PickField`。text が `Escape-Cancel` から `Escape-Clear` に変わる | `PUSH Keypad5(start)`、`PUSH Keypad6(extend)`（西なら Keypad4）、`PUSH Keypad5(end)` | `[(自分),(隣)]` |
| `probe:field:cancel` | 同上。`Escape-Clear` の後に `Escape-Cancel` に戻る | `PUSH Keypad5(start)`、`PUSH Escape(clear)`、`PUSH Escape(abort)` | `null` |
| `probe:conv` | `kind=popup path=S PopupID=Conversation:[R5] probe:conv`、`<option:0..2>`、ボタン `Look` と `Cancel` | `command=option:1 accepted` | `1`（既定なら 0） |
| `probe:status` | `status-notready` の後に `kind=status`、`StatusScreens CurrentScreen=... navActive=True`（Factions タブ。F4 C-F4-status-screens-09 の対応では index 6） | `ANSWER Status Exit ... accepted` | `returned` |
| `probe:book` | `kind=book`、`Book title="[R5] probe:book" ... pages=N pending=True isCurrentWindow=True navActive=True`。`book-notready` が先に出てもよい | `ANSWER Book Cancel ... accepted` | `returned` |
| `probe:talk` | `kind=popup PopupID=Conversation:<名前>`、`conv node=<id> lastChoice=...`、`choice[i] id=... target=...`（入れ子のポップアップは `NESTED popup -> Accept/No/Cancel`） | ノードごとに 1 回の `accepted` と `conv answered node=<id> with option:k choice=<id>`。次のノードで `conv node=<id> token-changed=True ... lastChoice=<id> expected=<id> -> ok` | `nodeOk>=1 nodeBad=0`。`-> BAD` が 1 回でもあれば FAIL |
| `probe:conv:<ID>` | `probe:talk` と同じ（話者が地図の外なので Trade ボタンはない） | `probe:talk` と同じ | `nodeOk>=1 nodeBad=0`。最初のノードに Target が空でも `End` でもない選択肢がなければ `nodeOk=0` で FAIL になる。その場合は別の ID で打ち直す |
| `probe:trade` | `kind=trade`、`side0(trader) goods=N`、`side1(player) goods=M`、`navActive=True busy=False`。busy の間は `trade busy or navigation inactive, not read`。前に `NESTED popup` が出てもよい | `ANSWER Trade Cancel ... accepted` | `returned` |
| `probe:tutorial` | `precheck activeSelf=... activeInHierarchy=...` の後に `kind=tutorial`、`token=#n popupAcceptPressed=False activeInHierarchy=True` | `ANSWER tutorial overlay token=#n ... outcome=accept-pressed ...` がトークンごとに 1 回 | `released`。`tutorial Update not running` が出たら FAIL（`RECOVERY tutorial (probe-only)` で後始末する） |
| `probe:endturn` | `pushed Command:CmdWish from EndPlayerTurn mode=waiting energy=<1000 以上>` の後に、`Your wish is my command!` の `kind=popup` | `command=Cancel accepted` | `RESULT r5=R5-F6a endturn push consumed=True ... expected=True -> PASS` |
| `probe:endturn:spent` | `pushed ... mode=spent energy=<1000 未満>` の後、wish の入力欄が出ない | なし | `consumed=False expected=False -> PASS` |
| `probe:map` | なし | なし | `[map][<スレッド>] RESULT r5=R5-F7a size=80x25 glyphs(Char)=<n> glyphs(BackupChar)=<m> ...`。n>0 か m>0 なら PASS。ASCII では Char、タイル表示では BackupChar に字形が入る（`Zone.Render` が Char を 0 にして退避する） |
| `probe:death` | `kind=popup` で 4 択（Reload / View / Retire / Quit）、`[a] Retire character` などの文字列 | `command=option:<Retire>` → RETIRE の入力欄に `command=Cancel` → `retire-loop ok newToken=True` → `command=option:<Reload>` | `true step=3` |

補足:

- M の AskNumber は、`probe:asknumber:mouse`（AskNumberScreen）と `probe:asknumber:kb`（複製ポップアップ）の**両方**の PASS を求める（§10.1）。`controller before=... effective=... expectedSurface=...` の行で、どちらに入る設定だったかを確かめる。強制した値が `AskNumberAsync` より先に上書きされていたら（DETECT が `expectedSurface` と違う）、それは C-F3-pickers-23 の実機での答えとして記録する。その場合は FAIL として扱い、原因を監督者に渡す。
- `probe:all` の合格は `[all] SUMMARY pass=16/16`。

### 7.3 R5-0 の合否

| wish | PASS の条件 | 記録すべき所見 |
|---|---|---|
| （起動） R5-0c | `tick alive` 行が出て、`ctl=` に値がある | `ctl=Mouse` かどうか |
| `probe:reload` R5-0a | `RESULT r5=R5-0a gen before=1 after=1 dupTicksDelta=0 tickAlive=True -> PASS`。その前に `tick already alive gen=1 reason=init` が出る | hotload は同じアセンブリの `[ModSensitiveCacheInit]` を呼び直すだけで、再コンパイルしない（`XRL.Core/XRLCore.cs:575-577`、`XRL/ModManager.cs:340-372`）。したがって世代番号は増えないのが正しい |
| `probe:offthread` R5-0e | `RESULT r5=R5-0e offthread activeSelf=<ok:...|exception:...>` が出て、プロセスが生きている | 例外になるかどうか。設計は UI タスクでしか読まないので、どちらでも合格 |
| `probe:focus:force` R5-0b | `RESULT r5=R5-0b unfocusedSamples>=20 avgTickHz>=3.5 P'TrueSamples>=1 -> PASS` を、`OptionMusicBackground=Yes` と `=No` の**両方**で満たす | 基準の `probe:focus` の Hz と `rib`。`=No` の基準で `tickHz=0` が続けば、Update が止まっている |
| `probe:focus:play` R5-0b-play | `RESULT r5=R5-0b-play unfocusedSamples>=10 turnsAdvanced>=8 -> PASS`（毎秒の行は `appFocused=False focused=True bThreadFocus=True P'=True ... dTurns=1(counted) push=pushed`。フォーカス中の標本は `push=none(focused)`） | `focusRewrites>=1`（本当に非フォーカスになった裏付け）、`pushes` と `turnsAdvanced` の差（`CmdWait` の欠落か遅延）、積まなかった理由 `skip(P'-false)` / `skip(input-not-empty)` / `skip(modal=<kind>)` / `skip(view=<v>)` / `ui-task-failed`、最後の `mitigation off; runInBackground=<元の値> _focused=<Application.isFocused>` |
| `probe:cancel` R5-0d | `RESULT r5=R5-0d ... tickAliveAfter3s=True -> PASS` が出る（プロセスが落ちていない） | `got=Yes`、`views=LEAKED`、`thrownToCaller`、`BEGIN` の後の `ERROR:` / `Exception` の行。行が出ないままゲームが消えたら F-2 |

## 8. TIMEOUT のときの手当て

`TIMEOUT after 20000ms with the modal still open: answer it manually. Hide() was NOT called.` が出たら、次のように手当てする。

- **ポップアップ系・画面系**: オペレーターが手で答える（クリックかキー）。`RESULT` の `timedOut=True` で FAIL として残る。
- **ピッカー**: answerer が `RECOVERY picker Escape` を 1 回送る。それでも残れば手で Escape を押す。PickField は開始済みなら 1 回目の Escape が消去になるので、もう一度押す。
- **チュートリアルのオーバーレイ**: `probe:tutorial` は、ゲームスレッドの待ちが時間切れになると `RECOVERY tutorial (probe-only)` を実行する。latch と `ShowingPopup` を下ろし、`PopupCompletion` を完了させる。これはプローブ専用の後始末で、エージェントの設計には含めない。
- 手で答えても閉じない場合、またはゲームが応答しない場合は、「ハング」として記録する（§10 の判定に効く）。

## 9. 監督者（Fable）に渡すもの

1. `$PROFILE/Player.log` の全体と、`grep -n 'INFO - \[R5\]' -A12 "$PROFILE/Player.log"` の出力。DETECT のテキストは複数行なので `-A` を付ける。
2. `$PROFILE/build_log.txt`（とくに `FINAL LOAD ORDER` と、`LlmOfQudProbeR5` のビルド結果）。
3. 使った `Local/PlayerOptions.json` と `Local/ModSettings.json`。起動後にゲームが書き換えていれば、その版も渡す。
4. `Player.log` 冒頭のゲームバージョンと Unity バージョン。
5. オペレーターのメモを wish ごとに付ける。内容は次のとおり。
   - 画面に残ったものの有無
   - 手で答えたかどうか
   - 移動と `Ctrl+W` の応答
   - 所要時間の体感
   - `probe:focus` の間にフォーカスを外していた時間
6. `grep -nE 'Exception|EACCES|Harmony|ERROR:' "$PROFILE/Player.log"` の出力。
7. `tick seeded` / `tick alive` / `tick already alive` / `tick gen=... retired` の行と、各 ANSWER の `via=` の値。
   - `via=post` は、tick が止まったときの比較用のフォールバックである。R5 では tick と比べるためだけに使う。`via=post` でだけ PASS した場合は、tick の起動か維持の問題として扱う（§10.2）。

## 10. 判定規則（方向 2 か、Legacy UI への後退か）

「FAIL」は、同じ wish を新しいゲームで 2 回試しても FAIL だったものを指す。1 回目の FAIL は、原因（オペレーターの操作、マウス、前のプローブの残り）を除いてから再試行する。

### 10.1 Legacy UI へ全面後退させる失敗（方向 2 を棄却）

中心集合 **M = { `probe:yesno`, `probe:askstring`, `probe:pickoption`, `probe:stale`, `probe:asknumber:mouse`（エージェントが入る AskNumberScreen の表面）, `probe:asknumber:kb`（複製ポップアップの表面）, `probe:conv` }** のどれかで、次のいずれかが起きた場合に後退する。

1. `Hide()` を使わずには答えられない。つまり `outcome=not-accepted`、`token-mismatch`、`commandCallback-null`、`selectCallback-null` が再現し、正しい値で戻らない。
2. `views=LEAKED` になる（ビュースタックが漏れる）。
3. ハングする（TIMEOUT の後、手で答えても戻らない）。
4. 二重応答が起きて誤った値が返る（`value=MISMATCH`）。または `probe:stale` で `STALE ANSWER NOT REJECTED` が出る。`blockedDouble>0` はプローブ自身の仕組みの指標で、それだけでは後退の根拠にしない。
5. UI tick と Post の**両方**で UI タスクが実行されない（`classify ... TIMEOUT` が続く）。

ただし、数えるのは次のどちらかに当たる FAIL だけである。

- その wish のログに、目的のモーダルへの `ANSWER` / `PUSH` 行があり、`targetMatched>=1` である。
- ハングかビューの漏れである。

`DETECT` では目的のモーダルが見えているのに、`targetMatched=0` のまま `NESTED popup` として答えられた FAIL は、プローブの述語の不具合である。述語を直して再試行する。

M は、PopupMessage 系（F1 / F2）の入口である。ゲームのほぼすべての確認、選択、入力、会話がここを通る。ここで Modern UI を Harmony なしで駆動できなければ、方向 2 は成り立たない。

さらに、08 §8.2 の次の三つは、R5-0 の段階で後退の引き金になる。

| # | 引き金 | 確かめる wish | 判断（08 §8.2） |
|---|---|---|---|
| F-1 | `runInBackground` を mod が真に書き直しても、非フォーカスで Unity の Update が止まる。あるいは UI tick が実用に足る頻度で回らない | `probe:focus:force`（Yes / No の両方）、基準の `probe:focus` | ウィンドウを常にフォーカスさせる運用が取れないなら、Legacy を検討する。Legacy も getvk の待ちでフォーカスの影響を受けるので、差があるかを先に測る |
| F-2 | async void の WaitNewPopupMessage がプールで例外を再送出したとき、Mono がプロセスを落とす | `probe:cancel` | トークンと成功確認で「キャンセルを起こさない」設計にすれば避けられる。ただし、人の操作やエンジン自身の onHide（`ShowPopup` の健全性チェック、`Qud.UI/PopupMessage.cs:722-735`）でも起きるので、Modern のポップアップは不安定とみなして Legacy を検討する |
| F-3 | UI タスクの中で Unity の API を読むことや、`OnActivateCommand` / `OnInputSubmit` を直接呼ぶことが、例外や表示の崩れを起こす。あるいは NavigationController の状態を壊す | M のすべて、`probe:talk` | PopupMessage への直接応答が成り立たないので、Legacy を採る |

### 10.2 全面後退の根拠にしない失敗（局所的な代替で扱う）

- **ピッカー**（`probe:pickdir` / `probe:picktarget` / `probe:field`）: Legacy でも同じ getvk ループと `Keyboard.Push*` を使う。失敗は入力注入の問題で、UI の選択とは独立している。前提 P' や入力キューの扱いを直す（08 §8.2 F-4 / F-5）。
- **ステータス画面**（`probe:status`）: 失敗したら `OptionModernCharacterSheet=No` で、その画面だけを Legacy に戻す（`Screens.cs:45`）。
- **PickGameObject / 取引 / 本**（`probe:pickitem` / `probe:trade` / `probe:book`）: 個別に調べる。失敗の形が 10.1 の 1〜4（Hide が必要、漏れ、ハング、二重）と同じなら、M と同じ扱いに格上げして監督者が判断する。
- **実際の会話**（`probe:talk` / `probe:conv:<ID>`）: `probe:conv` が PASS なら、会話の選び方の問題として扱う。ただし `-> BAD`（`LastChoice` の不一致）が出たら、`OnActivateCommand` の経路が `ConversationUI.Select` まで届いていない疑いがあるので、F-3 として監督者が判断する。
- **チュートリアルのオーバーレイ**（`probe:tutorial`）: `tutorial Update not running` なら、Legacy でも同じ UGUI の面が残る（08 §8.1(4)）。後退の理由にはならず、GameObject を active に保つ手段を探す。
- **EndPlayerTurn と地図**（`probe:endturn*` / `probe:map`）: ゲームスレッドの仕組みで、UI の選択とは独立している。
- **tick だけの失敗**: UI tick が起動しなくても `via=post` で PASS するなら、tick の起動と維持を直す案件として扱う。後退ではない。R5 の `via=post` は、tick と比べるためだけにある。

### 10.3 方向 2 を採る条件

次のすべてを満たすこと。

1. R5-0a〜R5-0e が §7.3 の条件で PASS する。R5-0b は `OptionMusicBackground=Yes` と `=No` の両方で PASS する。例外は一つだけで、`=No` でだけ落ちる場合は、`OptionMusicBackground=Yes` を実行プロファイルで固定する前提を明記したうえで、監督者が R5-0b を条件付きの PASS と判断してよい。
2. M がすべて PASS する。`views=restored`、例外なし、UI が応答すること。
3. §10.1 の F-1〜F-3 のどれにも当たらない。

10.2 の失敗は、局所的な代替を添えて報告する。

### 10.4 判定の記録（2026-09-26）

- 判定: 方向 2 を採る。§10.3 の 1〜3 をすべて満たした（R5-0a〜0e PASS、R5-0b は Music=Yes と No の両方で force PASS、M は全件 PASS、F-1〜F-3 なし）。証拠は `results/2026-09-26-run1.md`〜`run3.md` と各 Player.log。
- §10.2 で発動した項目: なし。`probe:trade`（既定 Tam）は前提不成立（`FindAndApproach` が null。隣接セルが空でない可能性が高い）で、`probe:trade:Mehmet` は PASS。
- 再試行した FAIL: `probe:death` の 1 回目は応答 3 回とも accepted でチェックポイントも読み直されたが、`Step` を応答の後に書く記録の競合で `step=2 -> FAIL`。Step を先に書く修正の後、再起動して PASS。§10.1 の「新しいゲームで 2 回」には当たらない（再起動して同じセーブを読んだ）。
- §7.1(1) の `targetMatched>=1` は `probe:tutorial` で 0 のまま PASS が印字された。`Finish` がこの条件を合否に入れておらず、tutorial の経路は `TargetMatches` を増やさない。機能上は解放（`answers=1 released=True`）。プローブ側の会計の穴として記録する。
- タイル表示（`OptionUseTiles=Yes`）の走行 4（`results/2026-09-26-run4.md`、`run4-Player.log`、`run4b-Player.log`）: R5-0a〜0e と実装済みの全ファミリーを再実行し、駆動の失敗は 0。走行 3 で未実行だった `probe:asknumber`、`probe:conv:Mehmet`、`probe:endturn:run:yesno` も PASS。`probe:map` はタイル表示では `glyphs(Char)=0 glyphs(BackupChar)=756`（字形は BackupChar に入る）。判定は変わらない。
- R5-F3c（`probe:imposter`）: タイル表示で PASS。照準の imposter は UI タスクで `TextConsole.CurrentBuffer` から読め、押し付けた座標 (43,18) と一致した。F-4 の「照準 imposter の走査も使えない」は成立しない。
- R5-0b-play（`probe:focus:play`）: 非フォーカス 30 秒で 28 ターン進行（`pushes=30`、143 Hz、`focusRewrites=1`）。独立検証が最上位の残課題とした「非フォーカスでのゲームスレッド進行」は、`runInBackground=true`、毎 tick の `bThreadFocus=true`、`GameManager._focused=true`（フィールドへ直接）の 3 点で成立する。
- R5 が示していないこと: 緩和策を長時間保ったときの安定性（`runInBackground` はエンジンが `Options.UpdateFlags` で書き直す。ブリッジは周期的に再設定する）、エンジンや人の操作による onHide のキャンセル、実際の死亡、F1c / F5c / F5e / F5f、ASCII 描画での照準 imposter の有無。
- 運用の規則: wish は貼り付ける（`pbcopy` → cmd+v）。自動化ツールの Escape は届かない。`probe:cancel` は最後に実行し、その後再起動する。ModalProbe.cs を直したら再起動する（hotload は再コンパイルしない）。 走行 4 では貼り付け入力だけで余計な画面は一度も開かなかった。フォーカスを外す操作は背景のタイマー（`osascript` で Finder を前面に → 一定秒後にゲームの pid を前面に）で行う。
