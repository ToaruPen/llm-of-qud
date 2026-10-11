using System;
using LlmOfQud;
using Newtonsoft.Json.Linq;

internal static class BackgroundTests
{
    public static void Run()
    {
        const string run = "11111111-1111-4111-8111-111111111111";
        const string game = "22222222-2222-4222-8222-222222222222";
        string hash = new string('a', 64);
        JObject config = new JObject { ["run_id"] = run, ["game_id"] = game,
            ["save_sha256"] = hash, ["save_turn"] = 9 };
        BackgroundStart start = BackgroundStart.Parse(config);
        var fresh = new JObject { ["run_id"] = run, ["new_game"] = new JObject {
            ["pregen"] = "Praetorian", ["name"] = "Jev trial" } };
        if (BackgroundStart.Parse(fresh) == null) throw new Exception("FAIL: new-game startup intent");
        var random = new JObject { ["run_id"] = run, ["new_game"] = new JObject {
            ["random_genotype"] = "Mutated Human", ["name"] = "Random trial" } };
        bool randomAccepted;
        try { randomAccepted = BackgroundStart.Parse(random).NewGame; }
        catch (ArgumentException) { randomAccepted = false; }
        if (!randomAccepted) throw new Exception("FAIL: native random Mutated Human must start a new game");
        var both = (JObject)random.DeepClone(); both["new_game"]["pregen"] = "Praetorian";
        Refuses(() => BackgroundStart.Parse(both), "random and preset are mutually exclusive");
        var unsupported = (JObject)random.DeepClone(); unsupported["new_game"]["random_genotype"] = "Unknown";
        Refuses(() => BackgroundStart.Parse(unsupported), "unsupported random genotype");
        var mixed = (JObject)config.DeepClone(); mixed["new_game"] = fresh["new_game"].DeepClone();
        Refuses(() => BackgroundStart.Parse(mixed), "cannot mix new game and load identity");
        var unnamed = (JObject)fresh.DeepClone(); unnamed["new_game"]["name"] = "";
        Refuses(() => BackgroundStart.Parse(unnamed), "new game name required");
        if (!BackgroundStart.IsEmbarkNotice("You embark for the caves of Qud.", false, 1, "Accept") ||
            BackgroundStart.IsEmbarkNotice("Delete character?", false, 1, "Accept") ||
            BackgroundStart.IsEmbarkNotice("You embark for the caves of Qud.", true, 1, "Accept"))
            throw new Exception("FAIL: only the exact non-input embark notice may be dismissed");
        start.ValidateSave(game, 9, hash, new[] { "M1", "R0" }, new[] { "R0", "M1" });
        Refuses(() => start.ValidateSave(game, 9, new string('b', 64), new[] { "M1" }, new[] { "M1" }), "changed save");
        Refuses(() => start.ValidateSave(run, 9, hash, new[] { "M1" }, new[] { "M1" }), "wrong game");
        Refuses(() => start.ValidateSave(game, 10, hash, new[] { "M1" }, new[] { "M1" }), "wrong turn");
        Refuses(() => start.ValidateSave(game, 9, hash, new[] { "M1" }, new[] { "M1", "R0" }), "mod mismatch");
        foreach (var entry in new[] {
            new JProperty("run_id", "bad"), new JProperty("save_turn", -1),
            new JProperty("save_sha256", "bad"), new JProperty("save_turn", "9"),
            new JProperty("development", "true"), new JProperty("unexpected", true) })
        {
            var invalid = (JObject)config.DeepClone(); invalid[entry.Name] = entry.Value;
            Refuses(() => BackgroundStart.Parse(invalid), entry.Name);
        }
        var stop = new JObject { ["command"] = "save_and_quit", ["run_id"] = run, ["expect_seq"] = 2 };
        BackgroundStart.ValidateStop(stop, run, 2, true);
        Refuses(() => BackgroundStart.ValidateStop(stop, game, 2, true), "foreign stop");
        Refuses(() => BackgroundStart.ValidateStop(stop, run, 3, true), "stale stop");
        Refuses(() => BackgroundStart.ValidateStop(stop, run, 2, false), "in-flight stop");
        Console.WriteLine("background policy tests passed (including new-game startup)");
    }

    private static void Refuses(Action action, string label)
    {
        try { action(); }
        catch (ArgumentException) { return; }
        throw new Exception("FAIL: did not reject " + label);
    }
}
