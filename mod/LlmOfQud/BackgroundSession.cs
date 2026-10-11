using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Security.Cryptography;
using System.Threading.Tasks;
using ConsoleLib.Console;
using Newtonsoft.Json.Linq;
using Qud.API;
using Qud.UI;
using XRL;
using XRL.UI.Framework;
using XRL.CharacterBuilds;
using XRL.CharacterBuilds.Qud;

namespace LlmOfQud
{
    // Local startup only; it drives the engine's Continue path, never OS input.
    internal sealed class BackgroundSession
    {
        internal readonly BackgroundStart Start;
        private readonly Stopwatch _clock = Stopwatch.StartNew();
        private Task<List<SaveGameInfo>> _saves;
        private SaveGameInfo _selected;
        private int _stage, _frames;
        private volatile bool _loaded;
        private bool _noticeDismissed;

        internal BackgroundSession(BackgroundStart start) { Start = start; }

        internal static string Hash(string path)
        {
            using (var stream = File.OpenRead(path))
            using (var hash = SHA256.Create())
                return BitConverter.ToString(hash.ComputeHash(stream)).Replace("-", "").ToLowerInvariant();
        }

        internal void Tick()
        {
            if (_loaded && (!Start.NewGame || _noticeDismissed)) return;
            if (_clock.Elapsed.TotalSeconds > (Start.NewGame ? 300 : 120)) throw new TimeoutException("Background startup did not reach a loaded game");
            var gm = GameManager.Instance;
            if (_stage == 0)
            {
                if (gm.CurrentGameView != "MainMenu" || UIManager.instance == null) return;
                var menu = SingletonWindowBase<MainMenu>.instance;
                if (menu == null || !menu.isCurrentWindow() || ++_frames < 10) return;
                if (Start.NewGame)
                {
                    if (Directory.Exists(DataManager.SavePath("Saves")) && Directory.GetDirectories(DataManager.SavePath("Saves")).Length != 0)
                        throw new InvalidDataException("New-game background profile must have no saves");
                    _stage = 1;
                    Keyboard.PushMouseEvent("Pick:New Game");
                    Runtime.Log(new { kind = "background_new_game", run_id = Start.RunId,
                        pregen = Start.Pregen, random_genotype = Start.RandomGenotype });
                    return;
                }
                if (_saves == null) _saves = SavesAPI.GetSavedGameInfo();
                if (!_saves.IsCompleted) return;
                foreach (SaveGameInfo save in _saves.GetAwaiter().GetResult())
                {
                    if (save.ID != Start.GameId) continue;
                    if (_selected != null) throw new InvalidDataException("Ambiguous background save ID");
                    _selected = save;
                }
                if (_selected == null || _selected.json == null) throw new InvalidDataException("Background save not found");
                ValidateSelected();
                _stage = 1;
                Keyboard.PushMouseEvent("Pick:Continue");
                Runtime.Log(new { kind = "background_continue", run_id = Start.RunId, game_id = Start.GameId });
            }
            else if (_stage == 1)
            {
                if (Start.NewGame)
                {
                    var builder = GameManager.Instance.gameObject.GetComponent<EmbarkBuilder>();
                    if (builder == null || builder.GetModule<QudPregenModule>() == null) return;
                    if (Start.Pregen != null && !builder.GetModule<QudPregenModule>().pregens.ContainsKey(Start.Pregen))
                        throw new InvalidDataException("Unknown pregen");
                    builder.GetModule<QudGamemodeModule>().SelectMode("Roleplay");
                    if (Start.RandomGenotype != null)
                    {
                        builder.GetModule<QudChartypeModule>().setData(new QudChartypeModuleData { type = "Random" });
                        builder.GetModule<QudGenotypeModule>().SelectGenotype(Start.RandomGenotype);
                        // The same native selectors used by Random, with genotype fixed.
                        // Draw each component once; do not reject builds for their strength.
                        foreach (string view in new[] { "Chargen/ChooseSubtypes", "Chargen/Mutations", "Chargen/PickAttributes" })
                        {
                            var descriptor = builder.GetWindowDescriptorByViewID(view);
                            if (descriptor == null || !descriptor.enabled)
                                throw new InvalidDataException("Random character module unavailable: " + view);
                            descriptor.getWindow().RandomSelectionNoUI();
                        }
                    }
                    else
                    {
                        builder.GetModule<QudChartypeModule>().setData(new QudChartypeModuleData { type = "Pregen" });
                        // Native selection initializes dependent modules and attributes.
                        builder.GetModule<QudPregenModule>().SelectPregen(Start.Pregen);
                    }
                    builder.GetModule<QudChooseStartingLocationModule>().setData(new QudChooseStartingLocationModuleData("Joppa"));
                    builder.GetModule<QudCustomizeCharacterModule>().setName(Start.CharacterName);
                    var attributes = builder.GetModule<QudAttributesModule>();
                    if (!attributes.enabled || attributes.data == null || attributes.data.apRemaining != 0)
                        throw new InvalidDataException("Character attributes were not initialized");
                    Runtime.Log(new { kind = "background_character", pregen = Start.Pregen,
                        random_genotype = Start.RandomGenotype,
                        subtype = builder.GetModule<QudSubtypeModule>().data.Subtype,
                        mutations = builder.GetModule<QudMutationsModule>().GetSummaryBlock().Description,
                        stats = attributes.GetFinalStats(builder), build_code = builder.generateCode() });
                    builder.info.modules.Add(new BackgroundEmbarkModule());
                    _stage = 2;
                    builder.exitWithInfo();
                    return;
                }
                var screen = SingletonWindowBase<Qud.UI.SaveManagement>.instance;
                if (screen == null || !screen.isCurrentWindow() || screen.completionSource == null ||
                    screen.completionSource.Task.IsCompleted) return;
                ValidateSelected();
                _stage = 2;
                screen.SelectedInfo(new SaveInfoData { SaveGame = _selected });
                Runtime.Log(new { kind = "background_save_selected", run_id = Start.RunId, save_sha256 = Start.SaveHash });
            }
            else if (_stage == 2 && Start.NewGame)
            {
                foreach (var window in UIManager.instance.windowsByName.Values)
                {
                    var popup = window as PopupMessage;
                    if (popup == null || popup.onHide == null || !popup.gameObject.activeSelf ||
                        popup.commandCallback == null || popup.controller == null) continue;
                    var buttons = popup.controller.bottomContextOptions;
                    if (buttons == null || buttons.Count != 1) continue;
                    string text = popup.Message == null ? "" : ModalPolicy.Strip(popup.Message.text).Trim();
                    if (!BackgroundStart.IsEmbarkNotice(text,
                        popup.inputBox != null && popup.inputBox.gameObject.activeSelf, buttons.Count, buttons[0].command)) continue;
                    Runtime.Log(new { kind = "background_embark_notice", run_id = Start.RunId, text });
                    popup.OnActivateCommand(buttons[0]);
                    _noticeDismissed = true;
                    return;
                }
            }
        }

        private void ValidateSelected()
        {
            Start.ValidateSave(_selected.ID, _selected.json.Turn,
                Hash(Path.Combine(_selected.Directory, "Primary.sav.gz")), _selected.ModsEnabled, ModManager.GetRunningMods());
        }

        internal JObject Loaded()
        {
            if (Start.NewGame)
            {
                if (_stage != 2 || _loaded || The.Player?.CurrentCell == null || The.Game.Turns > 1)
                    throw new InvalidDataException("Unexpected new-game startup state");
                _loaded = true;
                Start.GameId = The.Game.GameID;
                return new JObject { ["command"] = "arm", ["run_id"] = Start.RunId,
                    ["audit"] = Start.Audit, ["development"] = Start.Development };
            }
            if (_stage != 2 || _loaded || The.Game.GameID != Start.GameId || The.Game.Turns != Start.SaveTurn)
                throw new InvalidDataException("Unexpected background load");
            ValidateSelected();
            _loaded = true;
            return new JObject { ["command"] = "arm", ["run_id"] = Start.RunId,
                ["audit"] = Start.Audit, ["development"] = Start.Development };
        }

    }

    // The native game-start event runs on the game thread after the player is placed,
    // before RunSegment can wait for the first keyboard event in Modern UI.
    internal sealed class BackgroundEmbarkModule : AbstractEmbarkBuilderModule
    {
        public override void InitFromSeed(string seed) { }

        public override object handleBootEvent(string id, XRLGame game, EmbarkInfo info, object element = null)
        {
            if (id == QudGameBootModule.BOOTEVENT_GAMESTARTING) Runtime.Loaded();
            return element;
        }
    }
}
