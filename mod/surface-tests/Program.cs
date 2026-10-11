using System;
using System.Collections.Generic;
using System.Reflection;
using System.Threading.Tasks;
using LlmOfQud;
using SurfaceFixtures;

const BindingFlags StaticNonPublic = BindingFlags.Static | BindingFlags.NonPublic;
const BindingFlags InstanceNonPublic = BindingFlags.Instance | BindingFlags.NonPublic;
const BindingFlags InstanceAny = BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public;

int count = 0;
void Check(bool value, string label)
{
    if (!value) throw new Exception("FAIL: " + label);
    count++;
}
bool Has(string text, string part) { return text != null && text.IndexOf(part, StringComparison.Ordinal) >= 0; }

// ---- valid members (the production shapes) ----
Check(SurfaceCheck.Field(typeof(Engine), "OnTurnCallbacks", StaticNonPublic, typeof(IList<Action<Engine>>)) == null,
    "valid static nonpublic callback list");
Check(SurfaceCheck.Field(typeof(Engine), "OnMessageCallbacks", StaticNonPublic, typeof(IList<Action<string>>)) == null,
    "valid List<Action<string>> as IList");
Check(SurfaceCheck.Field(typeof(TaskQueue), "taskQueue", InstanceNonPublic, typeof(Queue<Entry>)) == null,
    "valid private instance queue");
Check(SurfaceCheck.Field(typeof(Entry), "actionToTake", InstanceNonPublic, typeof(Delegate)) == null,
    "Action field assignable to Delegate");
Check(SurfaceCheck.Field(typeof(Tutorial), "instance", StaticNonPublic, typeof(Tutorial)) == null, "static singleton field");
Check(SurfaceCheck.Field(typeof(Tutorial), "PopupCompletion", StaticNonPublic, typeof(object)) == null,
    "identity token accepts any field type");
Check(SurfaceCheck.Field(typeof(Tutorial), "ShowingPopup", InstanceNonPublic, typeof(bool)) == null, "bool field");
Check(SurfaceCheck.Field(typeof(Tutorial), "PopupText", InstanceNonPublic, typeof(string)) == null, "string field");
Check(SurfaceCheck.Field(typeof(Screen), "menucomplete", InstanceAny, typeof(TaskCompletionSource<>)) == null,
    "protected TaskCompletionSource<T> matches generic definition");
Check(SurfaceCheck.Field(typeof(PublicScreen), "menucomplete", InstanceAny, typeof(TaskCompletionSource<>)) == null,
    "public TaskCompletionSource<T> matches with Public|NonPublic flags");
Check(SurfaceCheck.Field(typeof(SubclassScreen), "menucomplete", InstanceAny, typeof(TaskCompletionSource<>)) == null,
    "TaskCompletionSource subclass matches generic definition");

// ---- missing member ----
string missing = SurfaceCheck.Field(typeof(Engine), "NoSuchCallbacks", StaticNonPublic, typeof(IList<Action<Engine>>));
Check(missing != null && Has(missing, "SurfaceFixtures.Engine.NoSuchCallbacks") && Has(missing, "missing"),
    "missing field reported with owner and name");

// ---- wrong member type ----
string notList = SurfaceCheck.Field(typeof(Engine), "NotAList", StaticNonPublic, typeof(IList<Action<Engine>>));
Check(notList != null && Has(notList, "System.Int32") && Has(notList, "not assignable"), "non-list field type reported");
string wrongArg = SurfaceCheck.Field(typeof(Engine), "OnMessageCallbacks", StaticNonPublic, typeof(IList<Action<Engine>>));
Check(wrongArg != null && Has(wrongArg, "not assignable"), "callback delegate type mismatch reported");
string notTcs = SurfaceCheck.Field(typeof(TaskScreen), "menucomplete", InstanceAny, typeof(TaskCompletionSource<>));
Check(notTcs != null && Has(notTcs, "not assignable"), "Task<T> is not a TaskCompletionSource<T>");
Check(SurfaceCheck.Field(typeof(Tutorial), "PopupText", InstanceNonPublic, typeof(bool)) != null, "string field is not bool");
Check(SurfaceCheck.Field(typeof(Tutorial), "ShowingPopup", InstanceNonPublic, typeof(string)) != null, "bool field is not string");

// ---- static versus instance, and visibility ----
string wasStatic = SurfaceCheck.Field(typeof(Engine), "StaticNotInstance", InstanceNonPublic, typeof(int));
Check(wasStatic != null && Has(wasStatic, "found static nonpublic field") && Has(wasStatic, "expected Instance, NonPublic"),
    "static field looked up as instance is reported as mismatch");
string wasInstance = SurfaceCheck.Field(typeof(Engine), "InstanceNotStatic", StaticNonPublic, typeof(int));
Check(wasInstance != null && Has(wasInstance, "found instance nonpublic field") && Has(wasInstance, "expected Static, NonPublic"),
    "instance field looked up as static is reported as mismatch");
string wasPublic = SurfaceCheck.Field(typeof(Engine), "PublicField", InstanceNonPublic, typeof(int));
Check(wasPublic != null && Has(wasPublic, "found instance public field"), "public field with NonPublic-only flags is reported");

// ---- private / inherited lookup matches Type.GetField exactly ----
var matrix = new (Type owner, string name, BindingFlags flags, bool found)[]
{
    (typeof(Derived), "basePrivate", InstanceNonPublic, false),
    (typeof(Derived), "baseProtected", InstanceNonPublic, true),
    (typeof(Derived), "baseProtected", InstanceAny, true),
    (typeof(Derived), "basePrivateStatic", StaticNonPublic, false),
    (typeof(Derived), "baseProtectedStatic", StaticNonPublic, false),
    (typeof(Derived), "baseProtectedStatic", StaticNonPublic | BindingFlags.FlattenHierarchy, true),
    (typeof(Derived), "ownPrivate", InstanceNonPublic, true),
    (typeof(Base), "basePrivate", InstanceNonPublic, true),
    (typeof(Engine), "PublicField", InstanceNonPublic, false),
    (typeof(Engine), "PublicField", InstanceAny, true),
};
foreach (var row in matrix)
{
    string label = row.owner.Name + "." + row.name + " " + row.flags;
    bool runtime = row.owner.GetField(row.name, row.flags) != null;
    Check(runtime == row.found, "fixture expectation matches runtime: " + label);
    Check((SurfaceCheck.Field(row.owner, row.name, row.flags, typeof(object)) == null) == runtime,
        "validator agrees with Type.GetField: " + label);
}
string privateBase = SurfaceCheck.Field(typeof(Derived), "basePrivate", InstanceNonPublic, typeof(object));
Check(Has(privateBase, "missing"), "private base field is missing through the derived type");

// ---- declared method (stack-frame name match) ----
Check(SurfaceCheck.DeclaredMethod(typeof(Engine), "PlayerTurn") == null, "private instance method declared on owner");
Check(SurfaceCheck.DeclaredMethod(typeof(Engine), "Overloaded") == null, "overloads do not throw");
Check(SurfaceCheck.DeclaredMethod(typeof(Derived), "BaseTurn") != null, "inherited method does not satisfy DeclaringType match");
string noMethod = SurfaceCheck.DeclaredMethod(typeof(Engine), "RenamedTurn");
Check(noMethod != null && Has(noMethod, "SurfaceFixtures.Engine.RenamedTurn") && Has(noMethod, "missing"), "missing method reported");
Check(SurfaceCheck.DeclaredMethod(typeof(Engine), "PlayerTurnField") != null, "a field is not a method");

// ---- metadata only: no static initializer, no value read ----
Check(SurfaceCheck.Field(typeof(Guarded), "Callbacks", StaticNonPublic, typeof(IList<Action<Engine>>)) == null
      && SurfaceCheck.DeclaredMethod(typeof(Guarded), "PlayerTurn") == null, "guarded fixture validates");
Check(!Flag.Value, "type initializer never ran (no GetValue)");
typeof(Guarded).GetField("Callbacks", StaticNonPublic).GetValue(null);
Check(Flag.Value, "control: reading the value does run the initializer");

// ---- deterministic collection ----
string[] collected = SurfaceCheck.Collect(new[] { "b: x", null, "B: y", "a: z", null });
Check(string.Join("|", collected) == "B: y|a: z|b: x", "ordinal sort, nulls removed");
Check(SurfaceCheck.Collect(new string[] { null, null }).Length == 0, "all valid yields empty array");
Check(string.Join("|", SurfaceCheck.Collect(new[] { "b: x", "a: z" })) == string.Join("|", SurfaceCheck.Collect(new[] { "a: z", "b: x" })),
    "input order does not change output");

Console.WriteLine($"PASS: {count} surface checks");

// Fixture fields exist only to be found by reflection.
#pragma warning disable CS0649, CS0169
namespace SurfaceFixtures
{
    internal sealed class Engine
    {
        private static List<Action<Engine>> OnTurnCallbacks = new List<Action<Engine>>();
        private static List<Action<string>> OnMessageCallbacks = new List<Action<string>>();
        private static int NotAList;
        private static int StaticNotInstance;
        private int InstanceNotStatic;
        public int PublicField;
        private int PlayerTurnField;
        private void PlayerTurn() { }
        private void Overloaded() { }
        private void Overloaded(int value) { }
        internal static int Use(Engine e) { return NotAList + StaticNotInstance + e.InstanceNotStatic + e.PlayerTurnField + OnTurnCallbacks.Count + OnMessageCallbacks.Count; }
    }
    internal sealed class Entry { private Action actionToTake; internal Action Use() { return actionToTake; } }
    internal sealed class TaskQueue { private Queue<Entry> taskQueue = new Queue<Entry>(); internal int Use() { return taskQueue.Count; } }
    internal sealed class Tutorial
    {
        private static Tutorial instance;
        private static TaskCompletionSource<bool> PopupCompletion;
        private bool ShowingPopup;
        private string PopupText;
        internal static string Use(Tutorial t) { return instance + "" + PopupCompletion + t.ShowingPopup + t.PopupText; }
    }
    internal class Screen { protected TaskCompletionSource<int?> menucomplete = new TaskCompletionSource<int?>(); }
    internal sealed class PublicScreen { public TaskCompletionSource<string> menucomplete = new TaskCompletionSource<string>(); }
    internal sealed class Completion : TaskCompletionSource<bool> { }
    internal class SubclassScreen { protected Completion menucomplete = new Completion(); }
    internal class TaskScreen { protected Task<int> menucomplete = Task.FromResult(0); }
    internal class Base
    {
        private int basePrivate;
        protected int baseProtected;
        private static int basePrivateStatic;
        protected static int baseProtectedStatic;
        protected void BaseTurn() { }
        internal int Use() { return basePrivate + baseProtected + basePrivateStatic + baseProtectedStatic; }
    }
    internal sealed class Derived : Base { private int ownPrivate; internal int Own() { return ownPrivate; } }
    // Explicit static constructor (not beforefieldinit): any static member access or GetValue runs it.
    internal static class Guarded
    {
        private static List<Action<Engine>> Callbacks;
        static Guarded() { Flag.Value = true; Callbacks = new List<Action<Engine>>(); }
        private static void PlayerTurn() { }
        internal static bool Unused() { return Callbacks == null; }
    }
    internal static class Flag { internal static bool Value; }
}
