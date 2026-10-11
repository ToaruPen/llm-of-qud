using LlmOfQud.ProbeR34;

void Equal(string expected, string actual)
{
    if (expected != actual) throw new Exception($"Expected {expected ?? "continue"}, got {actual ?? "continue"}");
}

var arrival = new MacroProgress("goto", 10, 1, 1, 30, 4, 1);
Equal(null, arrival.Observe(11, 2, 1, true));
Equal("ARRIVED", arrival.Observe(13, 4, 1, false));

var stuck = new MacroProgress("goto", 0, 1, 1, 30, 4, 1);
for (int i = 0; i < 20; i++) Equal(null, stuck.Observe(0, 1, 1, true));
for (int i = 1; i < 6; i++) Equal(null, stuck.Observe(i, 1, 1, true));
Equal("STUCK", stuck.Observe(6, 1, 1, true));

var resting = new MacroProgress("rest", 0, 1, 1, 20, -1, -1);
for (int i = 1; i < 20; i++) Equal(null, resting.Observe(i, 1, 1, true));
Equal("BUDGET", resting.Observe(20, 1, 1, true));

var explore = new MacroProgress("explore", 0, 1, 1, 40, -1, -1);
Equal("ENGINE_STOP", explore.Observe(2, 2, 2, false));
Console.WriteLine("PASS: arrival precedence, same-turn reentry, stuck movement, resting budget, engine stop");


static void Expect(bool condition, string name)
{
    if (!condition) throw new Exception(name);
}

Expect(!ProbePolicy.DiscardPickerAttempt(false, 0), "normal first attempt must enqueue");
Expect(ProbePolicy.DiscardPickerAttempt(true, 0), "fault-injected first attempt must be discarded");
Expect(!ProbePolicy.DiscardPickerAttempt(true, 1), "fault-injected retry must enqueue");
Expect(ProbePolicy.NewTaskAppeared(new[] { "Other" }, new[] { "Other", "LookedAt42" }, "LookedAt42"),
    "actual tooltip exit must add the expected queued task");
Expect(!ProbePolicy.NewTaskAppeared(new[] { "LookedAt42" }, new[] { "LookedAt42" }, "LookedAt42"),
    "preexisting task must not count as a new tooltip effect");
Expect(!ProbePolicy.NewTaskAppeared(new[] { "Other" }, new[] { "Other" }, "LookedAt42"),
    "missing task must not count as a tooltip effect");
Console.WriteLine("PASS: picker loss/retry policy and newly queued hover task");
