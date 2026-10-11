# 04. CoQ データ面・行動語彙・Mod ビルド/デプロイ

> 調査担当: Opus 5.5 読み手エージェント D (2026-09-25)。エージェント自身はレポートファイルの書き込みをハーネスに拒否されたため、返り値 (key_findings) を監督者 (Fable) がそのまま書き起こした。判断や要約は加えていない。
>
> 引用の基準: 逆コンパイルは `coq-decompiled_stable` (調査時点 2.0.211.50。引用した `CommandBindingManager` / `XRLCore` / `ModManager` / `ModInfo` / `Options` / `Keyboard` / `GameManager` / `DataManager` は 2.0.211.56 とバイト一致を確認済み。`ConsoleLib.Console/ScreenBuffer.cs` は 211.56 で変更あり)。`Base/` は `CoQ.app/Contents/Resources/Data/StreamingAssets/Base` (2026-09-25 更新後)。
>
> 付属データ: [data/cmd_table.md](data/cmd_table.md) (全 201 コマンド)、[data/opt_table.md](data/opt_table.md) (全 194 オプション)、[data/hidden.md](data/hidden.md) (Commands.xml に無い隠しコマンド)、[data/gen_tables.py](data/gen_tables.py) (再生成スクリプト)。

## 1. 行動語彙 (Commands.xml と XRLCore のディスパッチ)

### 1.1 仕組み

- `Commands.xml` は `[ModSensitiveCacheInit]` の `LoadCommands` が `DataManager.YieldXMLStreamsWithRoot("commands")` で読み込む。Mod から追加・上書きできる。
- 読む属性: `ID` / `Category` / `DisplayText` / `Layer` (既定 `*default`) / `Auto` / `Required` / `CanShareBindsWith` / `Type` / `UpgradeFrom` / `RequiresCapability`。キー定義は `keyboardBind` (Key, Modifier, Set=default|hjkl) / `gamepadBind` / `mouseBind`。
- `navcategory` ごとに有効な Layer が決まる。Adventure = System, UI, Adventure, AdventureNav, AdventureLooker, AdventureTargeting, Dynamic。ほかに Menu / StatusScreens / Popup / Chargen / Looker / Targeting / Conversation / Trade / Keybind。
- 出典: `XRL.UI/CommandBindingManager.cs:94-106,1219-1237,1288-1336,1821-1840`、`Base/Commands.xml:1-105`。

### 1.2 件数

`<command>` は 201 件。内訳: Basic Move/Attack 30、Adventuring 37、Advanced Adventuring 9、Targeting 8、Ability Bar 19、Shortcuts to Character Sheet 12、Character Sheet 6、Trade 11、Character Creation 5、Menus 31、UI 5、System 4、Mouse-specific 9、Debug 12、InternalUI 3。全行の表は `data/cmd_table.md`。出典: `Base/Commands.xml:107-875`。

### 1.3 ディスパッチ

`XRLCore.PlayerTurn` はプレイヤーの Energy が 1000 以上の間ループし、`GetNextCommand(CoreLoopExcludes)` でキーをコマンド ID に変換して巨大な switch で処理する。どの case にも当たらない ID は `default:` 分岐で `CommandEvent.Send(The.Player, id)` される。したがって任意の能力コマンド文字列がそのまま行動になる。出典: `XRL.Core/XRLCore.cs:690-736,902,981,2323-2334`、`XRL.UI/CommandBindingManager.cs:928-931`。

### 1.4 モーダルを開くコマンド (コード確認済み)

| 種類 | コマンド | ハンドラ (XRLCore.cs 行) |
|---|---|---|
| PickTarget | CmdMoveTo / CmdAttackCell / CmdTarget | 1237 / 1405 / 1826 |
| PickDirection | CmdAttackDirection / CmdWalk / CmdOpen / CmdTalk (Talk は会話 UI に続く) | 1393 / 2110 / 2176 / 2214 |
| PickOption | CmdWaitMenu / CmdMoveMenu / CmdMoveToPointOfInterest | 929 / 967 / 1347 |
| AskNumber | CmdWaitN | 1559 |
| Look | CmdLook = `Look.ShowLooker` | 1697 |
| その他 | CmdHelp (1701)、CmdAbilities = `AbilityManager.Show` (1806)、CmdInventory / Equipment / Character / SkillsPowers / Quests / Journal / Tinkering / LastStatusPage = `Screens.Show` (1706-1919)、CmdFactions = ShowPopup (1889)、CmdActiveEffects (1896)、CmdMessageHistory (2296)、CmdCompanions = PickGameObject (2299)、CmdWish = テキスト入力 (1883)、CmdSystemMenu (983-1136)、CmdSave / CmdLoad / CmdQuit = Yes/No (1784 / 1792 / 1727) | |

非モーダル: CmdMove*、CmdAttack{Dir}、CmdWait / 20 / 100 / UntilHealed / UntilMorning、CmdMoveFar*、CmdAutoExplore、CmdAutoAttack、CmdToggleMessageVerbosity。出典: `XRL.Core/XRLCore.cs:929,967,983-1136,1237,1347,1393,1405,1559,1697-1713,1727,1784-1795,1806-1919,2105-2238,2296-2321`。

### 1.5 隠しコマンド (Commands.xml に無く XRLCore にだけ case がある: 27 件)

CmdUse{N,S,E,W,NE,NW,SE,SW} (1655-1678)、CmdGetFrom{8 方向} (2150-2173)、CmdAutoMove{8 方向} (1138-1161)、CmdMoveDirection (1223、ピッカーあり)、CmdSaveAndQuit (1718、Yes/No の後 `SaveGame("Primary")`)、CmdShowEffects (1823)。さらに前方一致の `CmdMoveToBorder:x,y` (908-919)。方向を ID に含むためピッカーを経ずに 1 手で撃てる。LLM 向きの行動 ID である。出典: `XRL.Core/XRLCore.cs:908-919,1138-1161,1223,1655-1678,1718-1726,1823,2150-2173`、`data/hidden.md`。

### 1.6 AutoAct

自動行動は文字列 `AutoAct.Setting` で表される: `?` = 自動探索 (ワールドマップでは無効)、`a` = 自動攻撃 (Target が必要)、`M{x},{y}` = 座標への自動移動、`ReopenMissileUI`。出典: `XRL.Core/XRLCore.cs:787-790,895-899,914-916,1920-1940`。

### 1.7 能力語彙 (confidence: medium)

`Base/ActivatedAbilities.xml` には `<ability Command=...>` が 187 件あり、説明文 (description 約 28.7k 文字) も付く。例: CommandFlyToggle、CommandTeleport、CommandBreathe_FireBreather、GasGenerationCommandSleepGas。CmdAbilities の選択結果と `default:` 分岐はどちらも `CommandEvent.Send` でこの ID を送る。スキル・変異・装備の能力はこの ID の送信で発動すると推定する (能力によっては対象選択 UI が出る)。出典: `Base/ActivatedAbilities.xml`、`XRL.World.Parts/ActivatedAbilities.cs:108`、`XRL.Core/XRLCore.cs:1806-1821,2323-2334`、`Local/PlayerOptions.json` の AbilityListOrder。

### 1.8 注入

`Keyboard.PushCommand(cmd)` は `'Command:'+cmd` をマウスイベントとして積み、PlayerTurn がそれを `text2=cmd` に変換する。キーコードを介さずに任意のコマンド ID を注入できる。ただし `PushMouseEvent` / `PushKey` は `GameManager.bCapInputBuffer` が真でキューが 3 件以上あると黙って捨てる。`bCapInputBuffer` は `OptionCapInputBuffer` (既定 Yes) に連動する。出典: `ConsoleLib.Console/Keyboard.cs:128,723-726,787-794,825-830`、`XRL.Core/XRLCore.cs:763-780`、`XRL.UI/Options.cs:1279-1286`、`Base/Options.xml:42`。

### 1.9 Modern UI 専用

CmdAbility1-10 は `Qud.UI.AbilityBar.hotkeyAbilityCommands` で解決され、`GameManager` が `TrySendCommandEventOnPlayer` を呼ぶ。XRLCore の switch には case が無い。CmdAbilityBar1-5 は `CurrentGameView=="Stage"` のときにしか効かない。GameManager は `CmdAbilityNextPage` / `CmdAbilityPrevPage` を参照するが、Commands.xml の ID は `Ability Page Up` / `Ability Page Down` で一致しない。Navigate Vertical / Horizontal は Legacy UI 向けと DisplayText に明記されている。出典: `Qud.UI/AbilityBar.cs:168-170,587-590`、`GameManager.cs:2389-2426`、`Base/Commands.xml:524-525,645-652`。

### 1.10 キー

既定キーの一次情報は Commands.xml (`keyboardBind`、KeybindSet オプションで default / hjkl を選ぶ)。`Base/DefaultKeymap.json` は旧形式の整数コード (Keys.cs の値 + Shift 0x10000 / Control 0x20000 / Alt 0x40000) で、`RestoreDefaults` の中でだけ読まれる。不一致は CmdSkillsPowers (xml は k、旧は P) と CmdTinkering (xml は n、旧は K) の 2 件だけ。ユーザーの現行キーマップは `Synced/<User>.Keymap2.json`。出典: `XRL.UI/CommandBindingManager.cs:984-987,1031-1055,1489-1499`、`ConsoleLib.Console/Keys.cs:199-201`、`Base/DefaultKeymap.json`、`Base/Commands.xml:675,690`。

### 1.11 行動文法案 (confidence: medium)

- 移動: CmdMove{Dir} (U / D を含む)
- 自動移動: CmdMoveFar* / CmdAutoMove* / `CmdMoveToBorder:x,y` / CmdMoveToEdge
- 攻撃: CmdAttack{Dir} / CmdAttackNearest / CmdAutoAttack
- 待機: CmdWait / 20 / 100 / UntilHealed / UntilMorning
- 探索: CmdAutoExplore
- 相互作用: CmdUse{Dir} / CmdGetFrom{Dir} / CmdGet / CmdTalk / CmdOpen
- 遠隔: CmdFire / CmdThrow / CmdReload (Targeting 内で CmdAltFire1-5 / CmdTargetSelf / CmdMarkTarget)
- 能力: ActivatedAbilities の Command ID
- 状態画面: Screens.Show 群 (画面内では InventoryQuickDrop / Eat / Drink / Apply)
- UI ナビ: Accept / Cancel / UI:Navigate/* / Page * / Category * / Submit
- 取引: CmdTrade* / CmdVendor* / CmdStartTrade
- メタ: CmdSave / CmdLoad / CmdSaveAndQuit / CmdSystemMenu / CmdWish

`WishCommands.xml` にはデバッグ用のウィッシュ 13 件 (godmode、xp:N、item:BP、checkpointon など) がある。出典: `Base/Commands.xml:107-875`、`Base/WishCommands.xml:1-17`、`XRL.Core/XRLCore.cs:1162-1222,1417-1628`。

## 2. Options.xml (非視覚プレイ・決定性・速度に関係するもの)

### 2.1 仕組み (confidence: medium)

オプション値は `Local/PlayerOptions.json` (NameValueBag) に保存され、`GetOption` は Bag → Defaults の順に参照する。`Requires="OptionShowAdvancedOptions==Yes"` は UI の表示制御にしか使われず、実行時の値には効かない。よって事前に書いた JSON の値が有効になると推定する。Options.xml は 194 件、全件は `data/opt_table.md`。出典: `XRL.UI/Options.cs:1100-1120,1127-1150,1495-1537`、`Qud.UI/OptionsScreen.cs:260-262`。

### 2.2 表示

`OptionUseTiles` (既定 Yes、`Options.xml:22`) は `Globals.RenderMode` を Tiles / Text に切り替える。tile モードでは `Zone.Render` が `ConsoleChar._Char` を `'\0'` にし、ASCII は `BackupChar` に退避される (v1 の発見)。`BackupChar` は `ScreenBuffer` / `ConsoleChar.Copy` でコピーされないため `CurrentBuffer` 上では失われる。Text モードなら ASCII のまま読めると推定する。関連: `OptionModernUI` (Yes, :53)、`OptionStripUIColorText` (No, :196)、VFX 系 `OptionUseOverlayCombatEffects` / DamageText / ParticleVFX / TextParticleVFX (Yes, :25-28)、Accessibility の各種 Disable* (No, :45-50)、`OptionThrottleAnimation` (No, :175)、`OptionDrawStepImmediately` (Yes, :176)、`OptionDisplayFramerate` (VSync, :21。Unlimited で `targetFrameRate=0`、`Options.cs:1456-1460`)。出典: `Base/Options.xml:21-32,45-53,175-176,196`、`XRL.UI/Options.cs:606,1288-1295`、`archives/llm-of-qud-v1/docs/memo/phase-0-b-tile-mode-finding-2026-04-25.md`。

### 2.3 自動化・確認プロンプト

- 自動化: `OptionAutoexploreRate` (既定 20 cells/sec、0 で無制限、:126)、`OptionAutoexploreMode` (Standard / Performance、:112)、自動探索の敵無視閾値 (:117-119)、`OptionInterruptHeldMovement` (Yes, :120)、AutoSip / AutoTorch / AutoexploreChests / DigOnMove (Yes)、Autoget 14 件 (:129-142)、`OptionAutosaveInterval` (5, :125)。
- 確認プロンプト: AskForWorldmap (No)、AskAutostair (Yes)、ConfirmSwimming (Yes)、ConfirmDangerousLiquid (Yes)、AskForOneItem (No) (:145-149)。`OptionDisplayHPWarning` (40%, :150) は HP 警告の popup (`XRLCore.cs:747-751`)。
- popup をメッセージログに回す設定: DismemberAsPopup / AbilityCooldownWarningAsMessage / ShowScavengeItemAsMessage / PopupJournalNote (:151-154)。`OptionLogTurnSeparator` (:90)。メッセージの Terse 表示はオプションではなく CmdToggleMessageVerbosity で切り替える (`XRLCore.cs:2240`)。
- 出典: `Base/Options.xml:90,112-126,129-142,145-156`、`XRL.Core/XRLCore.cs:747-751,2240-2250`。

### 2.4 デバッグ・決定性

`OptionAllowSaveLoad` (No, :191。CmdSave / CmdLoad の Quick.sav に必要、`XRLCore.cs:1785,1793`)、`OptionDisablePermadeath` (No, :190)、`OptionAllowReallydie` (No, :192)、`OptionEnableSeed` (No, :193、実験的)、`OptionShowQuickstart` (No, :199)、`OptionDisablePlayerbrain` (No, :200)、`OptionDebugShowConversationNode` (No, :211)、`OptionDebugInternals` / Attitude (:219-220)、`OptionMusicBackground` (No, :180。`Application.runInBackground` に連動、`Options.cs:1445-1454`)。Mod 関連: `OptionEnableMods` (Yes, :159)、`OptionAllowCSMods` (既定 No, :160)、`OptionOutputModAssembly` (Yes, :161)、`OptionHarmonyDebug` (No, :162)。出典: `Base/Options.xml:159-162,180,190-200,211,219-220`、`XRL.UI/Options.cs:1367,1445-1454`。

### 2.5 スクリーンリーダーは無い

Options.xml の Accessibility カテゴリにあるのは視覚効果の抑制 6 件だけ。逆コンパイル結果に UAP (`UAP_AccessibilityManager`、`MacOSTTS`、`Accessible*`) は同梱されているが、呼び出しているのはプラグイン付属のサンプルスクリプト (`gameplay.cs` の match-3 サンプルなど) だけ。XRL* / Qud* / ConsoleLib* / GameManager.cs からの参照は 0 件。出典: `Base/Options.xml:45-50`、`gameplay.cs:5,67`、`mainmenu.cs:16`、`gameover.cs:78`。

### 2.6 難易度とゲームモード

難易度スライダーは無い。ゲームモードは Tutorial / Classic (パーマデス) / Roleplay (Checkpointing=Enabled) / Wander (中立スタート、殺害 XP なし、チェックポイントあり) / Daily (固定キャラ + 固定シード、Editable=False) の 5 つ。出典: `Base/EmbarkModules.xml:16-60`。

## 3. エージェントの知識源

### 3.1 小規模・高価値 (system prompt や構造化 KB にそのまま使える)

`Manual.xml` (25KB、topic 12、約 6k トークン、ローダー `XRLManual.cs:33`)、`Quests.xml` (28KB、quest 28 / step 84、XP・派閥報酬付き、`QuestLoader.cs:308`)、`Skills.xml` (53KB、skill 21 / power 123、情報はすべて属性、`SkillFactory.cs:154`)、`Mutations.xml` + `HiddenMutations.xml` (mutation 82 + 50、`MutationFactory.cs:238`)、`ActivatedAbilities.xml` (ability 187)。

### 3.2 中〜大規模

`Conversations.xml` は 647KB (conversation 203 / node 1255 / choice 3085、約 100k トークン)。述語 (IfHaveActiveQuest 123、IfHaveState 94、IfFinishedQuest 78 …) とアクション (CompleteQuestStep 53、StartQuest 32、GiveItem 24、FinishQuest 24) を含み、クエストの遷移グラフを抽出できる。ただし本文には `=subject.*=` のような変数が残り、実行時の生成テキストとは異なる。`ObjectBlueprints/*.xml` は 2.8MB・object 5224 件で `Inherits` の解決が必要 (Description Short は 2384 件・約 367k 文字)。`Books.xml` は 53 冊 / 210 ページ (約 36k トークン、大半は世界観の文章)。Factions / PopulationTables (850KB) / Worlds / ZoneTemplates は属性中心で構造化 KB 向き。出典: `XRL.World.Conversations/ConversationLoader.cs:19-30`、`XRL.World.Loaders/ObjectBlueprintLoader.cs:882`、`XRL.UI/BookUI.cs:92`。

### 3.3 低価値・注意点

`LibraryCorpus.json` (2.4MB) は order-2 のマルコフ連鎖データ (keys 84006) で、ランダム書籍や落書きの生成に使われる。攻略知識ではない。`Corpus/*.txt` (3 本、119KB、パブリックドメインの抜粋) はファイル名で直接読む箇所が見つからず、その原文と推定する。`Base/Mods.xml` (mod 59 件) は Mod のメタデータではなく、アイテム改造 (ModLacquered など) の定義である。出典: `XRL/GameText.cs:412-423`、`XRL.World.Parts/MarkovBook.cs:122-131`、`XRL.World/ModificationFactory.cs:88`。

### 3.4 Wiki

公式 Wiki は MediaWiki 1.43.1 で、記事 3557 / ページ 15483 / 約 85 万語。API で取得できる。ライセンスは CC BY-NC-SA 4.0 で、オフライン KB 化の際の制約になる (可否の判断は保留)。出典: `https://wiki.cavesofqud.com/api.php?action=query&meta=siteinfo&siprop=statistics%7Crightsinfo&format=json`。

### 3.5 言語

利用者の本番プロファイルは `PlayerOptions.json` の `Language=ja` で、QudJP (Workshop 3718988020) が有効。実行時に読み取るテキストは日本語になる。Base の XML は英語の原本だが、Mod が同じルート名の XML を合成するため、実行時の実効データは Base + Mod になる。出典: `~/Library/Application Support/Freehold Games/CavesOfQud/Local/PlayerOptions.json`、`Local/ModSettings.json`、`XRL.UI/CommandBindingManager.cs:1827`。

## 4. Mod のビルドとデプロイ (macOS)

### 4.1 Mod ルートとスキャン順

1: `StreamingAssets/DLC`、2: OSX の `CoQ_Data/StreamingAssets/DLC`、3: `StreamingAssets/Mods` (Embedded、常にスキャン。QudJP の sync_mod の既定配置先)。ここから下は `OptionEnableMods` が有効なときだけ: 4: `SavePath/Mods` = `~/Library/Application Support/Freehold Games/CavesOfQud/Mods` (v1 の配置先、現在は空)、5: `LocalPath/Mods` = `…/Local/Mods`、6: Workshop 購読 (`PlatformManager.IsInitialized()` が偽ならスキップ)。ID が重複すると後着がスキップされる。有効/無効は `Local/ModSettings.json` に保存され、新規 Mod の既定は `Enabled=true`。出典: `XRL/ModManager.cs:249,509-515,552,579,590-641`、`XRL/DataManager.cs:335-369`、`XRL/ModSettings.cs:17`。

### 4.2 C# Mod の既定は無効

`.cs` を含む Mod は IsScripting になり、`OptionAllowCSMods` が No (既定) だと `ModState.Disabled` になる。実機では AllowCSMods=Yes だが、`Local/ModSettings.json` は `"LLMOfQud": {"Enabled": false}`、QudJP は true になっている。出典: `XRL/ModInfo.cs:126-129,476-478`、`Base/Options.xml:160`、`Local/ModSettings.json`。

### 4.3 manifest.json

`ModManifest` のフィールド: `ID` (`[^\w ]` を除去して正規化)、`LoadOrder` (非推奨の警告あり)、`Title`、`Description`、`Tags` (カンマ区切り可)、`Version`、`Author`、`PreviewImage`、`Directories` (ModDirectory: Paths / Version / Build / Options / Dependencies / Exclusions)、`Dependencies`、`LoadBefore`、`LoadAfter`、`Dependency`。同じディレクトリの `config.json` (旧式)、`workshop.json` (WorkshopId / Title / Description / Tags / Visibility / ImagePath)、`modconfig.json` も読まれる。出典: `XRL/ModManifest.cs:9-42`、`XRL/ModInfo.cs:288,292-331`、`XRL/ModDirectory.cs:7-66`、`XRL/SteamWorkshopInfo.cs:8-21`。

### 4.4 Roslyn コンパイル

`BuildMods` は Mod ごとに `InitializeFiles` (`.cs` を再帰探索、隠しファイルは除外) → `TryBuildAssembly` (全 `.cs` を `RoslynCSharpCompiler.CompileFromFiles` に渡す) → `ApplyHarmonyPatches` の順に処理する。`build_log.txt` に `Compiling N files...` / `Success :)` / `== COMPILER ERRORS ==` を出力する。定義されるシンボルは `VERSION_1_0` / `BUILD_2_0_211` / `MOD_<ID>`。`OptionOutputModAssembly=Yes` なら `SavePath/ModAssemblies/<ID>.dll` と `.pdb` を出力する。言語水準は C# 9 / netstandard2.0 相当 (テンプレートと QudJP の記録)。`Base/Mods.csproj.template.txt` は Mod Toolkit の `csproj` 項目 (`WriteCSProj`) が `$MANAGED_PATH$` / `$REFERENCES` を埋め込んで `SavePath/Mods.csproj` を生成するためのもので IDE 用。ゲームのビルドには使われない。出典: `XRL/ModManager.cs:115-135,436-467`、`XRL/ModInfo.cs:460-481,755-820`、`Qud.UI/ModToolkit.cs:111-139`、`Base/Mods.csproj.template.txt`、`coq-japanese_stable/docs/deployment.md:131`。

### 4.5 Bootstrap + DLL 方式の制約

Mod フォルダの `.dll` を自動でロードする経路は無い。QudJP は Roslyn でコンパイルされる `Bootstrap.cs` から `Assembly.LoadFrom(<mod>/Assemblies/QudJP.dll)` している。`ModManager.ActiveTypes` は `ActiveModules` (Roslyn でビルドしたアセンブリだけ) を列挙し、`GetTypesWithAttribute` もそれを走査する。そのため LoadFrom した DLL 内の `[PlayerMutator]` / `[HasWishCommand]` / `[ModSensitiveCacheInit]` などは発見されない。QudJP がこれらを `Bootstrap.cs` に置いているのはこのため。`ApplyHarmonyPatches` もコンパイル済みアセンブリにしか `PatchAll` しないので、DLL 側で Harmony を自前適用する必要がある。出典: `XRL/ModManager.cs:86-98,449-452,1206-1219`、`XRL/ModInfo.cs:845-853`、`workshop/content/333640/3718988020/Bootstrap.cs`、`archives/llm-of-qud-v1/mod/AGENTS.md:7-18`。

### 4.6 Rosetta と EACCES

同梱の `0Harmony.dll` は Version=2.2.2.0 で、Apple Silicon のネイティブ起動では `PatchAll` が `mprotect returned EACCES` で失敗し、パッチは 0 件になる。QudJP のスクリプトは原因を MonoMod の MAP_JIT への mprotect が W^X で拒否されるためと説明している。回避策は 2 つ。

- (a) Universal バイナリを x86_64 で起動する: `arch -x86_64 "$HOME/Library/Application Support/Steam/steamapps/common/Caves of Qud/CoQ.app/Contents/MacOS/CoQ"` (`SteamAppId=333640` / `SteamGameId=333640` を export する。Steam の Rosetta チェックボックスや `arch -x86_64 %command%` は確実には効かない)。
- (b) `Managed/0Harmony.dll` を Harmony 2.4.2 の net48 版に差し替える (ネイティブで成功する)。ただし 2026-09-25 の Steam 更新で 2.2.2.0 に戻っており、更新のたびに差し替えは失われる。

Rosetta が必要なのは Harmony を使う場合 (QudJP の併用を含む) だけ。v1 は Harmony も Rosetta も使っていなかった。出典: `coq-japanese_stable/README.md:29-59`、`coq-japanese_stable/scripts/launch_rosetta.sh:6-33`、`coq-japanese_stable/docs/reports/2026-05-12-harmony-2.4.2-native-arm64-verification.md:12-20,72`、workshop 3718988020 `Launch CavesOfQud (Rosetta).command`。

### 4.7 QudJP のビルドと出荷 (参考)

`just build` = `dotnet build Mods/QudJP/Assemblies/QudJP.csproj` (net48、GameDir の既定はバージョン固定の参照コピー `~/Games/CavesOfQud-stable-ref/CoQ.app/…/Data`、Assembly-CSharp と 0Harmony は Private=false で参照)。`build-dev` は `-p:QudJPDevBuild=true`、`rebuild` は clean と `--no-incremental`。`deploy-mod` = rebuild + sync-mod (`uv run python scripts/sync_mod.py`、既定の配置先は `StreamingAssets/Mods/QudJP`)。配置するのは manifest.json / preview.png / Bootstrap.cs / Assemblies/QudJP.dll / Localization / Fonts だけで、他の `.cs` を置くとコンパイルエラーになる。`dotnet-tools.json` には csharp-ls 0.24.0 (LSP 用) しか無い。Workshop へは `dist/workshop` と `workshop_item.vdf` を生成し、`steamcmd +workshop_build_item` で出す (人手のゲートあり)。ゲーム内の Mod Toolkit にも SteamWorkshopUploader がある。出典: `coq-japanese_stable/justfile:14-31,305-347`、`Mods/QudJP/Assemblies/QudJP.csproj:1-80`、`docs/deployment.md:105-140`、`docs/release.md:62-65,333-35`。

### 4.8 v1 の配置

v1 は `mod/LLMOfQud` (manifest.json と `*.cs` だけ、csproj / dll は置かない) への symlink を `$MODS_DIR/LLMOfQud` に張り、Roslyn にコンパイルさせていた。`$MODS_DIR = ~/Library/Application Support/Freehold Games/CavesOfQud/Mods`。起動フックは `[PlayerMutator]` の `mutate` で `The.Game.RequireSystem<LLMOfQudSystem>()` を呼ぶ形で、呼び出し元は `QudGameBootModule` の embark 時。検証は build_log の `Compiling / Success :)` と Player.log の `INFO - [LLMOfQud]`。現在その symlink は無い。出典: `archives/llm-of-qud-v1/docs/memo/phase-0-a-exit-2026-04-23.md:20-45,222`、`archives/llm-of-qud-v1/mod/AGENTS.md:5-77`、`archives/llm-of-qud-v1/mod/LLMOfQud/LLMOfQudBootstrap.cs`、`XRL.CharacterBuilds.Qud/QudGameBootModule.cs`。

### 4.9 最小レシピ (ソース方式、Harmony なし。未起動検証、confidence: medium)

1. `PROFILE=~/Library/Application Support/Freehold Games/CavesOfQud-llm` を作り、その下に `Local/` と `Mods/` を作る。
2. `mod/LLMOfQud/manifest.json` に `{"ID":"LLMOfQud","Title":"LLM of Qud","Version":"0.0.1","Author":"you","Tags":"Script"}` を書き、`Bootstrap.cs` には `[PlayerMutator] class : IPlayerMutator { mutate(){ MetricsManager.LogInfo("[LLMOfQud] mutate"); } }` を C# 9 以下で書く。
3. `ln -sfn <repo>/mod/LLMOfQud "$PROFILE/Mods/LLMOfQud"`。
4. `$PROFILE/Local/PlayerOptions.json` に `{OptionAllowCSMods:Yes, OptionShowAdvancedOptions:Yes, OptionUseTiles:No, OptionAllowSaveLoad:Yes, OptionCapInputBuffer:No, OptionMusicBackground:Yes}` を、`$PROFILE/Local/ModSettings.json` に `{"LLMOfQud":{"Title":"LLM of Qud","Enabled":true}}` を書く。
5. `export SteamAppId=333640 SteamGameId=333640` してから `"…/CoQ.app/Contents/MacOS/CoQ" -savepath "$PROFILE" -logFile "$PROFILE/Player.log"` で起動する (Harmony を使う場合や QudJP と併用する場合は先頭に `arch -x86_64`)。
6. 検証: `grep -E '=== LLM OF QUD ===|Compiling [0-9]+ files?|Success :\)|COMPILER ERRORS' "$PROFILE/build_log.txt"` と `grep 'INFO - \[LLMOfQud\]' "$PROFILE/Player.log"`。

出典: `XRL.Core/XRLCore.cs:458-496,3510-3526`、`XRL/ModInfo.cs:126-129`、`XRL/ModManifest.cs:17-18`、`archives/llm-of-qud-v1/mod/AGENTS.md:65-77`、Unity 6000.0 Player command line arguments。

## 5. ヘッドレス / 高速テストループの材料

### 5.1 起動引数

`-savepath` / `-sharedpath` / `-syncedpath <dir>` でセーブ・オプション・Mod 設定を隔離できる (Local は既定で `<savepath>/Local`、Synced は `<savepath>/Synced`)。`NOMETRICS` を含む引数で `Globals.ForceMetricsOff` になる。`STEAM:NO` で Steam の初期化を省ける (Workshop Mod が読まれなくなるかは PlatformManager 次第)。Unity 標準の `-logFile` / `-screen-width` / `-screen-height` / `-screen-fullscreen` / `-batchmode` / `-nographics` も使える。直接起動すると Steam は `No appID found` で初期化に失敗する (Player.log で確認)。出典: `XRL.Core/XRLCore.cs:458-496,3505-3535`、`GameManager.cs:805-817`、`Steamworks/SteamManager.cs:185-193`、`XRL/ModManager.cs:509-515`。

### 5.2 最大リスク: フォーカス待機 (confidence: medium)

`PlayerTurn` は `while(!GameManager.focused && Game.Running) Thread.Sleep(200)` で、ウィンドウが非フォーカスの間ブロックする。`focused` は Unity の `OnApplicationFocus` / `OnApplicationPause` で更新される。`OptionMusicBackground` は `Application.runInBackground` を立てるだけなので、`focused` は解除されないと推定する。無人ループでは Mod から `focused` を維持するか、Harmony でこの待機を無効化する必要があると推定する。出典: `XRL.Core/XRLCore.cs:737-740`、`GameManager.cs:405-425,1920-1929`、`XRL.UI/Options.cs:1445-1454`。

### 5.3 セーブ・開始の短縮

`XRLGame.LoadGame(Path)` は `Path+'.sav.gz'` を読む。QuickSave / QuickLoad は `Quick.sav.gz` を使う (CmdSave / CmdLoad は `OptionAllowSaveLoad` が必須)。セーブは `Synced/Saves/<GUID>/`。新規開始の短縮手段: `OptionShowQuickstart` で `_Quickstart` モードが出る (CmdDebugQuickstart もある)。キャラタイプ `Last` は `SavePath/lastcharacter.txt` のビルドコードから BuildSummary に直行する。メインメニューの Continue は ModernSaveManagement を経由するので、特定のセーブを自動ロードするにはフックが要る (推定)。出典: `XRL/XRLGame.cs:1677-1681,2028-2045`、`XRL.Core/XRLCore.cs:1784-1800,3730-3800`、`XRL.CharacterBuilds.Qud/QudGamemodeModule.cs:186-197`、`XRL.CharacterBuilds.Qud/QudChartypeModule.cs:84-97`、`XRL.CharacterBuilds/EmbarkBuilder.cs`。

### 5.4 ログ

`Player.log` (+ `Player-prev.log`) は `~/Library/Logs/Freehold Games/CavesOfQud/` にあり、Unity の Debug.Log が出る。`MetricsManager.LogInfo` は `INFO - ` を付ける。パスの初期化・Steam・Harmony の結果もここに出る (前回は `[QudJP] Harmony patching complete: 1693 method(s) patched.`)。`build_log.txt` (+ `.prev`) は SavePath にあり、Mod の依存解決・ビルド・シンボル・ロード順・コンパイルエラーが出る。`game_log.txt` は SavePath にあり NLog の GameLog (実機では 4 行)。QudJP の QudTest の結果は `Local/QudTest/results.json`。出典: `MetricsManager.cs:411-414`、`Logger.cs:32-36`、`XRL/ModManager.cs:469-475`。

### 5.5 ループ構成の候補

1. Unity 外テスト: QudJP の `QudTestHeadless` (net10 の CLI が `AssemblyLoadContext.Resolving` でゲームの `Managed/*.dll` を解決する)。Unity を起動せずにゲームのアセンブリ上でロジックを検証できる。
2. 隔離プロファイルでの実機起動と `PushCommand` による注入。
3. `[HasWishCommand]` の wish で実行時テストを起動し、結果を JSON に出す (QudJP の qudtest)。
4. 実行中の Mod 再読み込みは v1 で未検証で、プロセス再起動が前提になる。

出典: `coq-japanese_stable/scripts/tools/QudTestHeadless/Program.cs:64-79`、`coq-japanese_stable/justfile:353-356`、workshop 3718988020 `Bootstrap.cs` (QudJPQudTestWishBridge)、`archives/llm-of-qud-v1/docs/memo/phase-0-a-exit-2026-04-23.md:142-168`。

### 5.6 実機状態 (2026-09-25)

`ModAssemblies/` には 1526211226 / 2281679090 / QudJP / TW_Endless_EXP / langjapanese の 5 組 (`.dll` + `.pdb`) がある。`workshop/content/333640` にはインストール済みアイテムのフォルダが 6 つある (購読の証明ではない)。`StreamingAssets/Mods` と `DisabledMods` は空。`Local/Mods` には `lang.japanese` だけがある。CoQ バイナリは Universal (x86_64 + arm64)、Unity は 6000.0.77f1、更新前の Player.log ではゲーム Version 2.0.211.51。

## 6. 未解決の問い (エージェント D)

- フォーカス待機 (`XRLCore.cs:737`): `OptionMusicBackground` / `runInBackground` を有効にしても、非フォーカス時に `GameManager.focused` が false のままで PlayerTurn が止まるか。空の起動で確認が必要。
- `-batchmode` / `-nographics` で CoQ のメインループ (GameManager の Update、UI スレッド、PlayerTurn) が動くか。未検証。
- 事前に書いた `Local/PlayerOptions.json` と `Local/ModSettings.json` (`-savepath` による新規プロファイル) が初回起動でそのまま採用されるか。ファイルの上書きや初回ウィザードで失われないか。
- `[PlayerMutator]` は embark (`QudGameBootModule.cs:300-303`) でしか呼ばれないように見える。セーブをロードしたときにブリッジを起動する経路 (IPlayerSystem のデシリアライズ、ModSensitiveCacheInit など) は何か。
- `PlatformManager.IsInitialized()` (`ModManager.cs:511`) は Steam の初期化と等価か。`STEAM:NO` や SteamAppId 未設定で直接起動した場合、Workshop Mod が本当に読まれないか。
- ActivatedAbilities の Command ID を `CommandEvent.Send` で送ったとき、能力ごとにどのピッカーや popup が出るか (モーダルの有無の一覧化)。
