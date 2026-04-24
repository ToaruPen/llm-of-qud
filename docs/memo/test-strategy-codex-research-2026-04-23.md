# Test Strategy Research — Codex (2026-04-23)

Researcher: Codex (advisor mode, read-only, reasoning=high)
Trigger: user challenged the Phase 0-A plan's "C# MODs cannot be unit-tested in isolation" claim as unverified.

---

## 1. Pure Logic Test の実現可能性

CoQ 内部には runtime 外でテストされている純粋ロジックが実在する。

- `decompiled/` の `.cs` は 5367 files
- `The.Game | XRLCore.Core | GameManager.Instance` を直接含む `.cs` は 569 files → direct global token を含まないのは 4798 files (ただし「純粋」とは限らない)
- **NUnit テストファイル 11 files 実在** ([GrammarTest.cs](../../decompiled/XRL.Language/GrammarTest.cs:1), [DieRollTests.cs](../../decompiled/XRL.Rules/DieRollTests.cs:1), [DrillTest.cs](../../decompiled/XRL.World.Parts/DrillTest.cs:1), [MarkupSmokeTest.cs](../../decompiled/ConsoleLib.Console/MarkupSmokeTest.cs:1), [PopulationManagerTest.cs](../../decompiled/XRL.World/PopulationManagerTest.cs:1) など)

**Phase 0-A の対象 (IPlayerSystem / GameObject / BeginTakeActionEvent / RequireSystem / reload lifecycle) は pure logic ではない。** Phase 0-A に「外部 unit test すべき pure logic」はほぼない。

## 2. Assembly-CSharp.dll 外部参照の実現可能性

**実現可能**。ローカルに実 DLL あり:
```
~/Library/Application Support/Steam/steamapps/common/Caves of Qud/CoQ.app/Contents/Resources/Data/Managed/Assembly-CSharp.dll
```

[Assembly-CSharp.csproj](../../decompiled/Assembly-CSharp.csproj:1) は `TargetFramework=net40`、Unity/CoQ bundled DLL を多数参照、**`nunit.framework.dll` も含む**。公式 Wiki も `Assembly-CSharp.dll` decompile + `Mods.csproj` 生成を案内: https://wiki.cavesofqud.com/wiki/Modding%3AC_Sharp_Scripting

推奨 test project 構造:

```xml
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>netstandard2.0</TargetFramework>
    <LangVersion>9</LangVersion>
    <GenerateAssemblyInfo>false</GenerateAssemblyInfo>
    <QudLibPath>$(HOME)/Library/Application Support/Steam/steamapps/common/Caves of Qud/CoQ.app/Contents/Resources/Data/Managed</QudLibPath>
  </PropertyGroup>
  <ItemGroup>
    <Reference Include="Assembly-CSharp" HintPath="$(QudLibPath)/Assembly-CSharp.dll" />
    <Reference Include="UnityEngine.CoreModule" HintPath="$(QudLibPath)/UnityEngine.CoreModule.dll" />
    <Reference Include="0Harmony" HintPath="$(QudLibPath)/0Harmony.dll" />
    <Reference Include="Newtonsoft.Json" HintPath="$(QudLibPath)/Newtonsoft.Json.dll" />
    <Reference Include="nunit.framework" HintPath="$(QudLibPath)/nunit.framework.dll" />
  </ItemGroup>
</Project>
```

**注意**: compile OK と runtime OK は別。`The.Game` / Unity object / static init / asset path 初期化に触る test は落ちる可能性あり。"compile/reference probe" と "runtime behavior test" を分ける必要あり。

## 3. CoQ 内部のテストインフラ

**あるもの**:
- NUnit テストコード 11 files
- [Properties/AssemblyInfo.cs](../../decompiled/Properties/AssemblyInfo.cs:6) に `InternalsVisibleTo("UnitTests")`
- Managed DLL に `nunit.framework.dll` + `UnityEngine.UnityTestProtocolModule.dll`

**ないもの**:
- `XRL.Testing` namespace
- CoQ 独自の CLI test runner
- `RunTests` / `TestRunner` の game-side 呼び出し経路
- `UnitTests.dll` 別 assembly (Managed 配下に見当たらず)

## 4. Headless 起動の可否

**決定的に: CoQ 独自の headless mod-load-and-exit 経路は存在しない**

検索クエリ: `GetCommandLineArgs|CommandLine|batchmode|nographics|static void Main|BootGame|LoadGame|RunTests|TestRunner`

見つかった CLI args:
- `NOMETRICS` ([GameManager.cs:785](../../decompiled/GameManager.cs:785))
- `-SAVEPATH`, `-SHAREDPATH`, `-SYNCEDPATH` ([XRLCore.cs:3515](../../decompiled/XRL.Core/XRLCore.cs:3515))
- `STEAM:NO` ([SteamManager.cs:185](../../decompiled/Steamworks/SteamManager.cs:185))
- `GALAXY:NO` ([GalaxyManager.cs:165](../../decompiled/Galaxy/GalaxyManager.cs:165))

Unity `-batchmode -nographics` は player に渡せるが、CoQ 側の「MOD load → log 確認 → quit」経路がない。**Phase 0-A の自動 headless smoke は採用不可。**

## 5. 既存 Mod のテストパターン

GitHub / Wiki 調査:
- [公式 Wiki "C# Scripting"](https://wiki.cavesofqud.com/wiki/Modding%3AC_Sharp_Scripting): runtime compile, generated `Mods.csproj`, Player.log での debugging を案内
- [Modding Overview](https://wiki.cavesofqud.com/Modding%3AOverview): example mods list
- 公開 MOD で `Mods.csproj` / `Assembly-CSharp.dll` 参照の実例あり:
  - `Kizby/Clever-Girl`: `Mods.csproj` で `Assembly-CSharp.dll`, `0Harmony.dll`, `nunit.framework.dll` 参照
  - `HeladoDeBrownie/Caves-of-Qud-Minimods`: `netstandard2.0` で `Assembly-CSharp.dll` + `0Harmony.dll` 参照
- **しかし調査範囲で MOD 側の NUnit/xUnit 実テストは見つからず**。主流は IDE compile + in-game/log verification。

## 6. Phase 0-A 計画への提案 — **E (限定組合せ)**

- **Phase 0-A / 0-A2 acceptance**: **A (manual in-game verification) を維持**
- **C (compile/reference probe)**: 非ブロッキングで追加してよい
- **B (pure logic unit test)**: Phase 0-A では不要。Phase 0-B 以降、snapshot shaping / protocol parsing / candidate scoring 等の pure logic が出た時点で導入
- **D (headless batch smoke)**: 現時点で採用不可。CoQ 独自 headless が存在しないため

## 7. Phase 0-A Plan Redline 案

```diff
- **Testing reality for this plan:** C# MODs cannot be unit-tested in isolation — every type we touch (`GameObject`, `IPlayerSystem`, `BeginTakeActionEvent`) only exists at runtime inside CoQ's process. Each task therefore ends with **manual in-game verification** against a specific, narrow acceptance criterion. The spec is detailed enough that we do not need exploratory work; we just need to watch one log line appear or disappear.
+ **Testing reality for this plan:** Do not treat all CoQ C# as untestable: the
+ decompiled game contains NUnit tests for pure/string/parser/math helpers, and
+ external projects can reference `Assembly-CSharp.dll` plus bundled DLLs for
+ compile/reference probes. However, Phase 0-A's behavioral surface is not pure
+ logic. The code under test is MOD loading, `IPlayerSystem` registration,
+ player `GameObject` event registration, `BeginTakeActionEvent`, and reload
+ lifecycle inside CoQ. Those acceptance criteria require in-game verification
+ against `Logger.buildLog` / `Player.log`.
+
+ For Phase 0-A / 0-A2, external unit tests are not required because there is
+ no coupling-free project logic yet. Add pure unit tests starting in Phase
+ 0-B or later when the MOD introduces self-owned pure logic such as snapshot
+ shaping, protocol parsing, scoring, or serialization helpers. A non-blocking
+ external compile/reference probe may be added to validate local
+ `Assembly-CSharp.dll` references, but it must not replace the in-game
+ acceptance checks.

- Verification: manual via game launch, reading `Logger.buildLog` output and in-game mod list
+ Verification: manual via game launch, reading `Logger.buildLog` / `Player.log`
+ and in-game mod list. Optional non-blocking check: external compile/reference
+ probe against CoQ's bundled `Assembly-CSharp.dll`; this only proves reference
+ compatibility, not MOD runtime behavior.

+ **Non-blocking reference probe (optional):** Create a throwaway test/compile
+ project that references CoQ's `Managed/Assembly-CSharp.dll`,
+ `UnityEngine.CoreModule.dll`, `0Harmony.dll`, `Newtonsoft.Json.dll`, and
+ `nunit.framework.dll`. Limit any executable tests to methods known not to
+ touch `The.Game`, `XRLCore.Core`, `GameManager.Instance`, Unity objects, or
+ asset/path initialization.
```

## 最終判断

現計画の acceptance は manual のままでよい。ただし**前提文は修正すべき**。CoQ 全体には unit-testable な純粋ロジックがあり、`Assembly-CSharp.dll` 参照も現実的。Phase 0-A の対象はそのカテゴリではないだけ。
