// Startup reflection surface check (docs/exploration/06-recommendation.md section 1.5). Lists only the members that
// current production code reaches by name through reflection; public APIs are already checked by the fixed-DLL compile.
// Metadata only: never calls GetValue, never runs a type initializer, never mutates or reads game state.
using System;
using System.Collections.Generic;
using System.Reflection;
#if !LLMOFQUD_SURFACE_TESTS
// Same namespaces through which Runtime.cs and ModalDriver.cs resolve these types.
using ConsoleLib.Console;
using QupKit;
using Qud.UI;
using XRL;
using XRL.Core;
using XRL.UI;
using XRL.World;
#endif

namespace LlmOfQud
{
    internal static class SurfaceCheck
    {
        private const BindingFlags AnyField = BindingFlags.Instance | BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;

#if !LLMOFQUD_SURFACE_TESTS
        // Returns sorted descriptions of missing or incompatible members; empty when the surface matches.
        internal static string[] Validate()
        {
            const BindingFlags staticNonPublic = BindingFlags.Static | BindingFlags.NonPublic;
            const BindingFlags instanceNonPublic = BindingFlags.Instance | BindingFlags.NonPublic;
            // ModalDriver.Field(inst, type, "menucomplete")
            const BindingFlags screenField = BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public;
            return Collect(new[]
            {
                // Runtime.Register: typeof(XRLCore).GetField(name, Static|NonPublic) as IList<T>
                Field(typeof(XRLCore), "OnEndPlayerTurnCallbacks", staticNonPublic, typeof(IList<Action<XRLCore>>)),
                Field(typeof(XRLCore), "OnBeginPlayerTurnCallbacks", staticNonPublic, typeof(IList<Action<XRLCore>>)),
                Field(typeof(XRLCore), "OnNewMessageLogEntryCallbacks", staticNonPublic, typeof(IList<Action<string>>)),
                Field(typeof(XRLCore), "AfterRenderCallbacks", staticNonPublic, typeof(IList<Action<XRLCore, ScreenBuffer>>)),
                // Runtime.OnBeginTurn: stack frame DeclaringType == typeof(XRLCore) && Name == "PlayerTurn"
                DeclaredMethod(typeof(XRLCore), "PlayerTurn"),
                // Runtime.RecordQueue: QueueField / ActionField
                Field(typeof(ThreadTaskQueue), "taskQueue", instanceNonPublic, typeof(Queue<ThreadTaskQueueEntry>)),
                Field(typeof(ThreadTaskQueueEntry), "actionToTake", instanceNonPublic, typeof(Delegate)),
                // ModalDriver.TutInstance / TutCompletion (identity only) / TutShowing / TutText
                Field(typeof(TutorialManager), "instance", staticNonPublic, typeof(TutorialManager)),
                Field(typeof(TutorialManager), "PopupCompletion", staticNonPublic, typeof(object)),
                Field(typeof(TutorialManager), "ShowingPopup", instanceNonPublic, typeof(bool)),
                Field(typeof(TutorialManager), "PopupText", instanceNonPublic, typeof(string)),
                // ModalDriver.Field + Pending(tcs.GetType().GetProperty("Task"))
                Field(typeof(AskNumberScreen), "menucomplete", screenField, typeof(System.Threading.Tasks.TaskCompletionSource<>)),
                Field(typeof(BookScreen), "menucomplete", screenField, typeof(System.Threading.Tasks.TaskCompletionSource<>)),
                Field(typeof(PickGameObjectScreen), "menucomplete", screenField, typeof(System.Threading.Tasks.TaskCompletionSource<>)),
                Field(typeof(TradeScreen), "menucomplete", screenField, typeof(System.Threading.Tasks.TaskCompletionSource<>)),
                Field(typeof(StatusScreensScreen), "menucomplete", screenField, typeof(System.Threading.Tasks.TaskCompletionSource<>)),
            });
        }
#endif

        // Performs the same owner.GetField(name, flags) lookup as production, so inherited/private visibility matches the
        // runtime exactly. expected: the field type must be assignable to it, or, for a generic type definition, the
        // field type (or a base type) must be constructed from it. Returns null when compatible.
        internal static string Field(Type owner, string name, BindingFlags flags, Type expected)
        {
            string member = owner + "." + name;
            FieldInfo field = owner.GetField(name, flags);
            if (field == null)
            {
                // Diagnostic only: same owner, no FlattenHierarchy, so it cannot find anything the runtime would hide.
                FieldInfo other = owner.GetField(name, AnyField);
                if (other == null) return member + ": missing field (expected " + flags + ")";
                return member + ": found " + (other.IsStatic ? "static " : "instance ") + (other.IsPublic ? "public" : "nonpublic")
                    + " field declared on " + other.DeclaringType + ", expected " + flags;
            }
            if (!Accepts(expected, field.FieldType))
                return member + ": field type " + field.FieldType + " is not assignable to " + expected;
            return null;
        }

        // Production matches stack frames by method name and exact declaring type, so inherited methods do not count.
        internal static string DeclaredMethod(Type owner, string name)
        {
            MemberInfo[] found = owner.GetMember(name, MemberTypes.Method, AnyField | BindingFlags.DeclaredOnly);
            return found.Length > 0 ? null : owner + "." + name + ": missing method declared on " + owner;
        }

        internal static string[] Collect(IEnumerable<string> results)
        {
            var problems = new List<string>();
            foreach (string result in results) if (result != null) problems.Add(result);
            string[] sorted = problems.ToArray();
            Array.Sort(sorted, StringComparer.Ordinal);
            return sorted;
        }

        private static bool Accepts(Type expected, Type actual)
        {
            if (!expected.IsGenericTypeDefinition) return expected.IsAssignableFrom(actual);
            for (Type type = actual; type != null; type = type.BaseType)
                if (type.IsGenericType && type.GetGenericTypeDefinition() == expected) return true;
            return false;
        }
    }
}
