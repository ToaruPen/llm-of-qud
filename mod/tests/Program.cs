using LlmOfQud;

int count = 0;
void Check(bool value, string label)
{
    if (!value) throw new Exception(label);
    count++;
}

Action own = () => { }, foreign = () => { };
var callbacks = new List<Action> { foreign };
CallbackRegistration.Ensure(callbacks, own);
CallbackRegistration.Ensure(callbacks, own);
Check(callbacks.Count(x => x == own) == 1 && callbacks.Contains(foreign), "idempotent registration preserves foreign callback");
callbacks = new List<Action> { foreign }; // engine replaces the list at hotload
CallbackRegistration.Ensure(callbacks, own);
Check(callbacks.Count(x => x == own) == 1, "registration restored after cache replacement");
callbacks.Add(own);
CallbackRegistration.Ensure(callbacks, own);
Check(callbacks.Count(x => x == own) == 1 && callbacks.Contains(foreign), "only own duplicates removed");

Check(ActionPolicy.Validate("wait", null, 1) == null, "wait");
Check(ActionPolicy.Validate("wish", null, 1) != null, "reject arbitrary command");
Check(ActionPolicy.Validate("attack", "U", 1) != null, "attack directions");
Check(ActionPolicy.Validate("move", "U", 1) == null, "stairs");
Check(ActionPolicy.Validate("wait", "E", 1) != null, "reject irrelevant direction");
Check(ActionPolicy.Validate("explore", null, 41) != null, "bounded explore");
Check(ActionPolicy.Validate("wait", null, 20) != null, "one direct action");
Check(ActionPolicy.Validate("rest", null, 20) == null, "bounded rest");
Check(ActionPolicy.Validate("goto", null, 12, 40, 10) == null, "goto coordinates");
Check(ActionPolicy.Validate("goto", null, 12) == "invalid_target", "goto requires coordinates");
Check(ActionPolicy.Validate("goto", null, 12, 80, 10) == "invalid_target", "goto bounds");
Check(ActionPolicy.Validate("wait", null, 1, 40, 10) == "unexpected_target", "old actions reject target");
Check(ActionPolicy.Validate("rest", null, 40, until: "morning") == null, "rest morning");
Check(ActionPolicy.Validate("rest", null, 41) == "invalid_budget", "rest budget bounded");
Check(ActionPolicy.Validate("rest", null, 20, until: "forever") == "invalid_until", "rest mode bounded");
foreach (string action in new[] { "eat", "drink", "apply", "equip", "open" })
{
    Check(ActionPolicy.Validate(action, null, 1, item: "i1") == null, "item action allowed");
    Check(ActionPolicy.Validate(action, null, 1) == "invalid_item", "item action requires handle");
}
Check(ActionPolicy.Validate("eat", null, 1, item: "i01") == "invalid_item", "noncanonical handle rejected");
Check(ActionPolicy.Validate("eat", null, 1, item: "i65") == "invalid_item", "unobserved handle range rejected");
Check(ActionPolicy.Validate("wait", null, 1, item: "i1") == "unexpected_item", "old action rejects item");
Check(ActionPolicy.Validate("talk", "NE", 1) == null, "talk adjacent direction");
Check(ActionPolicy.Validate("talk", "U", 1) == "invalid_direction", "talk cannot cross levels");
Check(ActionPolicy.Validate("talk", null, 1) == "invalid_direction", "talk requires direction");
Check(ActionPolicy.Validate("get", null, 1, item: "p2") == null, "get a selected ground item");
Check(ActionPolicy.Validate("get", null, 1, item: "i1") == "invalid_item", "get cannot use a kit handle");
Check(ActionPolicy.Validate("eat", null, 1, item: "p1") == "invalid_item", "eat cannot use a ground handle");
Check(ActionPolicy.Validate("equip", null, 2, item: "i1") == "invalid_budget", "equip requires one-action budget");
Check(ActionPolicy.Validate("equip", "N", 1, item: "i1") == "unexpected_direction", "equip has no direction");
Check(ActionPolicy.Validate("equip", null, 1, item: "p1") == "invalid_item", "equip cannot use a ground handle");
Check(ActionPolicy.Validate("open", null, 1, item: "p1") == "invalid_item", "open requires a carried handle");
Check(ActionPolicy.Validate("learn_skill", null, 1, skill: "Acrobatics") == null, "skill purchase accepts a native id");
Check(ActionPolicy.Validate("learn_skill", null, 1) == "invalid_skill", "skill purchase requires an id");
Check(ActionPolicy.Validate("learn_skill", null, 1, skill: new string('x', 201)) == "invalid_skill", "skill id is bounded");
Check(ActionPolicy.Validate("learn_skill", null, 1, skill: "Axe:Cudgel_ChargingStrike") == null, "power id includes parent class");
Check(ActionPolicy.Validate("learn_skill", null, 1, skill: "Acrobatics", item: "i1") == "unexpected_item", "skill purchase excludes item");
Check(ActionPolicy.Validate("wait", null, 1, skill: "Acrobatics") == "unexpected_skill", "old action excludes skill");
Check(ActionPolicy.Validate("raise_attribute", null, 1, attribute: "Strength") == null, "attribute purchase accepts primary stat");
Check(ActionPolicy.Validate("raise_attribute", null, 1, attribute: "HP") == "invalid_attribute", "attribute purchase excludes secondary stat");
Check(ActionPolicy.Validate("wait", null, 1, attribute: "Strength") == "unexpected_attribute", "old action excludes attribute");
Check(ActionPolicy.Validate("raise_attribute", "N", 1, attribute: "Strength") == "unexpected_direction", "allocation excludes direction");
Check(ActionPolicy.Validate("learn_skill", null, 2, skill: "Acrobatics") == "invalid_budget", "allocation is one action");
Check(ActionPolicy.WithoutVisibleAdjective("acid-covered steel helmet [2 AV]", "steel helmet", "acid-covered") ==
    "steel helmet [2 AV]", "coating removal preserves public armor value");
Check(ActionPolicy.WithoutVisibleAdjective("masterwork acid-covered steel helmet [2 AV]", "steel helmet", "acid-covered") ==
    "masterwork steel helmet [2 AV]", "coating removal preserves item modifier");
Check(ActionPolicy.WithoutVisibleAdjective("wet towel [1 AV]", "wet towel", "wet") ==
    "wet towel [1 AV]", "ambiguous base word is retained");
Check(ActionPolicy.Validate("open", "N", 1, item: "i1") == "unexpected_direction", "open has no direction");
Check(ActionPolicy.Validate("get", null, 1, item: "p65") == "invalid_item", "ground handle bounded");
Check(ActionPolicy.FinalizeReason(false, "blocked", 1000, 900, 0) == "blocked_after_effect", "failed action with spent energy is distinct");
Check(ActionPolicy.FinalizeReason(false, "blocked", 1000, 1000, 1) == "blocked_after_effect", "failed action with elapsed world turn is distinct");
Check(ActionPolicy.FinalizeReason(false, "blocked", 1000, 1000, 0) == "blocked", "no-effect block stays blocked");
Check(ActionPolicy.FinalizeReason(true, "executed", 1000, 900, 1) == "executed", "objective success is preserved");
Check(ActionPolicy.FinalizeReason(false, "item_unavailable", 1000, 1000, 0) == "item_unavailable", "specific no-effect refusal is preserved");
Check(ActionPolicy.CanReachCell(10, 10, 11, 11), "adjacent ground reachable");
Check(ActionPolicy.CanReachCell(10, 10, 10, 10), "same cell reachable");
Check(!ActionPolicy.CanReachCell(10, 10, 12, 10), "distant ground not reachable");
var gate = new DecisionGate();
gate.Open(7);
Check(!gate.Accept(6), "stale rejected");
Check(gate.Accept(7), "current accepted");
Check(!gate.Accept(7), "duplicate rejected");
gate.Open(8);
Check(!gate.Accept(7) && gate.Accept(8), "generation changes");
gate.Open(9);
gate.Close();
Check(!gate.Accept(9), "load boundary rejects old unconsumed decision");
gate.Open(10);
Check(!gate.Accept(9) && gate.Accept(10), "fresh CTA accepts only post-load decision");
var messages = new MessageDigest();
for (int i = 0; i < 14; i++) messages.Add(i.ToString());
Check(messages.Snapshot().SequenceEqual(Enumerable.Range(2, 12).Select(i => i.ToString())), "last twelve in order");
messages.Clear();
messages.Add("fresh");
Check(messages.Snapshot().SequenceEqual(new[] { "fresh" }), "digest cleared at arm");
Check(ActionPolicy.Glyph('\0', '@') == '@', "tile backup");
Check(ActionPolicy.Glyph('.', '@') == '.', "rendered char wins");
Check(ActionPolicy.Glyph('\0', '\0') == ' ', "empty glyph");
char Terrain(bool visible, bool confused, bool solid, bool door, bool liquid, bool up, bool down)
    => ActionPolicy.TerrainGlyph(visible, confused, solid, door, liquid, up, down);
Check(Terrain(false, false, true, false, false, false, false) == '?', "hidden solids stay unknown");
Check(Terrain(true, true, true, false, false, false, false) == '?', "confusion does not reveal true terrain");
Check(Terrain(true, false, true, false, false, false, false) == '#', "visible solid blocks");
Check(Terrain(true, false, true, true, false, false, false) == '+', "door remains an interaction");
Check(Terrain(true, false, false, false, true, false, false) == '~', "liquid differs from clear floor");
Check(Terrain(true, false, false, false, false, true, false) == '<', "stairs survive display overlays");
Check(Terrain(true, false, false, false, false, false, true) == '>', "down stairs");
Check(Terrain(true, false, false, false, false, false, false) == '.', "no visible static obstruction");
var macro = new MacroGuard(20, 3, 10, 10);
Check(macro.Observe(20, 10, 10, 10, 20, true, false) == null, "guard initial");
Check(macro.Observe(21, 10, 10, 10, 20, true, true) == "NEW_HOSTILE", "visible hostile stop");
Check(macro.Observe(21, 10, 10, 4, 20, true, false) == "HP_CRITICAL", "low HP stop");
Check(macro.Observe(23, 12, 10, 20, 20, true, false) == "BUDGET", "budget stop");
Check(macro.Observe(21, 11, 10, 20, 20, false, false) == "ENGINE_STOP", "engine stop");
var stuck = new MacroGuard(0, 40, 10, 10);
for (int i = 1; i < 6; i++) Check(stuck.Observe(i, 10, 10, 20, 20, true, false) == null, "not stuck yet");
Check(stuck.Observe(6, 10, 10, 20, 20, true, false) == "STUCK", "stuck stop");
var oscillating = new MacroGuard(0, 40, 10, 10);
for (int i = 1; i < 6; i++) Check(oscillating.Observe(i, 10 + i % 2, 10, 20, 20, true, false) == null, "oscillation grace");
Check(oscillating.Observe(6, 10, 10, 20, 20, true, false) == "STUCK", "two-cell oscillation stop");
var walking = new MacroGuard(0, 10, 10, 10, "goto", 14, 10);
var hurtWalking = new MacroGuard(0, 12, 10, 10, "goto", 14, 10, hp: 20);
Check(hurtWalking.Observe(1, 11, 10, 19, 20, true, false) == "HURT", "goto stops even on noncritical damage");
Check(MacroGuard.IsRoutineEffect("slimy") && MacroGuard.IsRoutineEffect("defensive stance"), "routine coatings and stance do not interrupt");
Check(!MacroGuard.IsRoutineEffect("acid-covered") && !MacroGuard.IsRoutineEffect("unknown curse"), "dangerous and unknown new effects require review");
var effectWalking = new MacroGuard(0, 12, 10, 10, "goto", 14, 10, hp: 20);
Check(effectWalking.Observe(1, 11, 10, 20, 20, true, false, statusChanged: true) == "STATUS_CHANGED", "new public effect stops travel before another turn");
Check(walking.Observe(1, 11, 10, 20, 20, true, false) == null, "goto continues before destination");
Check(walking.Observe(4, 14, 10, 20, 20, true, false) == "ARRIVED", "goto stops at destination");
Check(walking.Observe(2, 12, 10, 20, 20, true, false, true) == "ZONE_CHANGED", "macro cannot cross zones");
var resting = new MacroGuard(0, 10, 10, 10, "rest", hp: 4);
for (int i = 1; i <= 6; i++) Check(resting.Observe(i, 10, 10, 4, 20, true, false) == null, "low HP stationary rest is allowed");
Check(resting.Observe(7, 10, 10, 3, 20, true, false) == "HURT", "rest stops on damage");
Check(resting.Observe(10, 10, 10, 5, 20, true, false) == "BUDGET", "rest cannot exceed budget");
await BridgeShutdownTests.Run(Check);
Console.WriteLine($"PASS: {count} policy checks");
