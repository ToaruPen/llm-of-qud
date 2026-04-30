using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;

namespace LLMOfQud
{
    public sealed class ToolRouter
    {
        public const bool TerminalActionParallelDispatchEnabled = false;

        private readonly Func<int> _sessionEpochProvider;
        private readonly Dictionary<string, ToolResultEnvelope> _terminalActionCache =
            new Dictionary<string, ToolResultEnvelope>();
        private readonly Dictionary<string, ToolResultEnvelope> _terminalMessageCache =
            new Dictionary<string, ToolResultEnvelope>();
        private readonly HashSet<int> _completedTerminalStateVersions = new HashSet<int>();
        private int _expectedStateVersion;
        private string _expectedSnapshotHash;

        public ToolRouter() : this(() => 1)
        {
        }

        public ToolRouter(Func<int> sessionEpochProvider)
        {
            _sessionEpochProvider = sessionEpochProvider ?? (() => 1);
            _expectedStateVersion = 0;
            _expectedSnapshotHash = null;
        }

        public void SetExpectedTurnContext(int stateVersion, string snapshotHash)
        {
            _expectedStateVersion = stateVersion;
            _expectedSnapshotHash = snapshotHash;
        }

        public ToolResultEnvelope Dispatch(ToolCallEnvelope call)
        {
            if (call == null)
            {
                return ToolResultEnvelope.FromError(
                    null,
                    null,
                    null,
                    0,
                    "invalid_tool_call",
                    "Tool call envelope is required");
            }

            if (IsTerminalAction(call.Tool))
            {
                if (call.ActionNonce == null || !call.StateVersion.HasValue)
                {
                    return TerminalActionResult(
                        call,
                        TerminalActionOutput.Stale("stale"),
                        "terminal action requires action_nonce and state_version");
                }

                if (call.SessionEpoch != _sessionEpochProvider())
                {
                    return TerminalActionResult(
                        call,
                        TerminalActionOutput.Stale("stale_epoch"),
                        "terminal action belongs to a stale session epoch");
                }

                ToolResultEnvelope cached;
                if (_terminalMessageCache.TryGetValue(call.MessageId, out cached))
                {
                    return CloneForDuplicateRequest(cached, call);
                }

                string cacheKey = TerminalActionCacheKey(call.SessionEpoch, call.ActionNonce);
                if (_terminalActionCache.TryGetValue(cacheKey, out cached))
                {
                    return CloneForDuplicateRequest(cached, call);
                }

                if (call.StateVersion.Value != _expectedStateVersion)
                {
                    return TerminalActionResult(
                        call,
                        TerminalActionOutput.Stale("stale"),
                        "terminal action belongs to a stale state version");
                }

                if (ReadStringArgOrNull(call.Args, "snapshot_hash") != _expectedSnapshotHash)
                {
                    return TerminalActionResult(
                        call,
                        TerminalActionOutput.Stale("stale"),
                        "terminal action snapshot_hash does not match current state");
                }

                if (_completedTerminalStateVersions.Contains(call.StateVersion.Value))
                {
                    return TerminalActionResult(
                        call,
                        TerminalActionOutput.Stale("duplicate"),
                        "terminal action already completed for this state version");
                }

                ToolResultEnvelope result = TerminalActionResult(
                    call,
                    TerminalActionOutput.Accepted(call.Tool),
                    null);
                _terminalActionCache[cacheKey] = CloneForCache(result);
                _terminalMessageCache[call.MessageId] = CloneForCache(result);
                _completedTerminalStateVersions.Add(call.StateVersion.Value);
                return result;
            }

            return ToolResultEnvelope.FromError(
                call.CallId,
                call.Tool,
                call.MessageId,
                call.SessionEpoch,
                "unknown_tool",
                "Tool is not registered: " + (call.Tool ?? "<null>"));
        }

        public static bool CanDispatchInParallel(ToolCallEnvelope call)
        {
            if (call == null || !IsTerminalAction(call.Tool))
            {
                return true;
            }
            return TerminalActionParallelDispatchEnabled;
        }

        private static ToolResultEnvelope TerminalActionResult(
            ToolCallEnvelope call,
            Dictionary<string, object> output,
            string errorMessage)
        {
            return new ToolResultEnvelope
            {
                CallId = call.CallId,
                Tool = call.Tool,
                Result = ToolResult.Ok(output),
                MessageId = ToolResultEnvelope.CreateMessageId(call.CallId, call.Tool, call.SessionEpoch),
                InReplyTo = call.MessageId,
                SessionEpoch = call.SessionEpoch,
                ActionNonce = call.ActionNonce,
            };
        }

        private static ToolResultEnvelope CloneForDuplicateRequest(
            ToolResultEnvelope cached,
            ToolCallEnvelope call)
        {
            return new ToolResultEnvelope
            {
                CallId = call.CallId,
                Tool = call.Tool,
                Result = cached.Result,
                MessageId = ToolResultEnvelope.CreateMessageId(call.CallId, call.Tool, call.SessionEpoch),
                InReplyTo = call.MessageId,
                SessionEpoch = call.SessionEpoch,
                ActionNonce = cached.ActionNonce,
            };
        }

        private static ToolResultEnvelope CloneForCache(ToolResultEnvelope result)
        {
            return new ToolResultEnvelope
            {
                CallId = result.CallId,
                Tool = result.Tool,
                Result = result.Result,
                MessageId = result.MessageId,
                InReplyTo = result.InReplyTo,
                SessionEpoch = result.SessionEpoch,
                ActionNonce = result.ActionNonce,
            };
        }

        private static bool IsTerminalAction(string tool)
        {
            switch (tool)
            {
                case "execute":
                case "navigate_to":
                case "choose":
                    return true;
                default:
                    return false;
            }
        }

        public static bool IsToolCallMessage(string json)
        {
            try
            {
                return ReadStringOrNull(json, ToolProtocolFields.FieldType) == ToolProtocolFields.TypeToolCall;
            }
            catch (DisconnectedException)
            {
                return false;
            }
        }

        public static bool IsSupervisorResponseMessage(string json)
        {
            try
            {
                return ReadStringOrNull(json, ToolProtocolFields.FieldType) ==
                    ToolProtocolFields.TypeSupervisorResponse;
            }
            catch (DisconnectedException)
            {
                return false;
            }
        }

        public static ToolCallEnvelope ParseToolCallEnvelope(string json)
        {
            RejectTopLevelField(json, ToolProtocolFields.FieldLegacyTid);
            return new ToolCallEnvelope
            {
                Type = ReadStringOrNull(json, ToolProtocolFields.FieldType),
                CallId = ReadRequiredString(json, ToolProtocolFields.FieldCallId),
                Tool = ReadStringOrNull(json, ToolProtocolFields.FieldTool),
                Args = ReadArgs(json),
                MessageId = ReadStringOrNull(json, ToolProtocolFields.FieldMessageId),
                SessionEpoch = ReadInt(json, ToolProtocolFields.FieldSessionEpoch),
                ActionNonce = ReadOptionalString(json, ToolProtocolFields.FieldActionNonce),
                StateVersion = ReadNullableInt(json, ToolProtocolFields.FieldStateVersion),
            };
        }

        public static int ReadTopLevelIntForTransport(string json, string name)
        {
            return ReadInt(json, name);
        }

        public static SupervisorResponseEnvelope ParseSupervisorResponseEnvelope(string json)
        {
            return new SupervisorResponseEnvelope
            {
                Type = ReadStringOrNull(json, ToolProtocolFields.FieldType),
                MessageId = ReadStringOrNull(json, ToolProtocolFields.FieldMessageId),
                InReplyTo = ReadStringOrNull(json, ToolProtocolFields.FieldInReplyTo),
                SessionEpoch = ReadInt(json, ToolProtocolFields.FieldSessionEpoch),
                Action = ReadStringOrNull(json, ToolProtocolFields.FieldAction),
                ChoiceId = ReadStringOrNull(json, ToolProtocolFields.FieldChoiceId),
                Reason = ReadStringOrNull(json, ToolProtocolFields.FieldReason),
            };
        }

        public static string BuildUnsupportedSupervisorResponseJson(SupervisorRequestEnvelope request)
        {
            if (request == null)
            {
                request = new SupervisorRequestEnvelope
                {
                    Type = ToolProtocolFields.TypeSupervisorRequest,
                    MessageId = null,
                    SessionEpoch = 0,
                };
            }

            SupervisorResponseEnvelope envelope = new SupervisorResponseEnvelope
            {
                Type = ToolProtocolFields.TypeSupervisorResponse,
                MessageId = CreateSupervisorResponseMessageId(request.MessageId, request.SessionEpoch),
                InReplyTo = request.MessageId,
                SessionEpoch = request.SessionEpoch,
                Action = SupervisorResponseEnvelope.SupervisorActionResume,
                ChoiceId = null,
                Reason = "local transport does not provide supervisor UI; continue to final decision",
            };

            StringBuilder sb = new StringBuilder(256);
            sb.Append('{');
            AppendJsonProperty(sb, ToolProtocolFields.FieldType, envelope.Type);
            sb.Append(',');
            AppendJsonProperty(sb, ToolProtocolFields.FieldSessionEpoch, envelope.SessionEpoch);
            sb.Append(',');
            AppendJsonProperty(sb, ToolProtocolFields.FieldMessageId, envelope.MessageId);
            sb.Append(',');
            AppendJsonProperty(sb, ToolProtocolFields.FieldInReplyTo, envelope.InReplyTo);
            sb.Append(',');
            AppendJsonProperty(sb, ToolProtocolFields.FieldAction, envelope.Action);
            sb.Append(',');
            AppendJsonProperty(sb, ToolProtocolFields.FieldChoiceId, envelope.ChoiceId);
            sb.Append(',');
            AppendJsonProperty(sb, ToolProtocolFields.FieldReason, envelope.Reason);
            sb.Append('}');
            return sb.ToString();
        }

        public static string BuildToolResultJson(ToolResultEnvelope envelope)
        {
            if (envelope == null)
            {
                envelope = ToolResultEnvelope.FromError(
                    null,
                    null,
                    null,
                    0,
                    "invalid_tool_result",
                    "Tool result envelope is required");
            }
            if (envelope.Result == null)
            {
                envelope.Result = ToolResult.Error(
                    "invalid_tool_result",
                    "Tool result payload is required");
            }

            StringBuilder sb = new StringBuilder(256);
            sb.Append('{');
            AppendJsonProperty(sb, ToolProtocolFields.FieldType, envelope.Type);
            sb.Append(',');
            AppendJsonProperty(sb, ToolProtocolFields.FieldCallId, envelope.CallId);
            sb.Append(',');
            AppendJsonProperty(sb, ToolProtocolFields.FieldTool, envelope.Tool);
            sb.Append(',');
            AppendJsonProperty(sb, ToolProtocolFields.FieldMessageId, envelope.MessageId);
            sb.Append(',');
            AppendJsonProperty(sb, ToolProtocolFields.FieldInReplyTo, envelope.InReplyTo);
            sb.Append(',');
            AppendJsonProperty(sb, ToolProtocolFields.FieldSessionEpoch, envelope.SessionEpoch);
            if (envelope.ActionNonce != null)
            {
                sb.Append(',');
                AppendJsonProperty(sb, ToolProtocolFields.FieldActionNonce, envelope.ActionNonce);
            }
            sb.Append(',');
            AppendJsonPropertyName(sb, ToolProtocolFields.FieldResult);
            sb.Append('{');
            AppendJsonProperty(sb, ToolProtocolFields.FieldStatus, envelope.Result.Status);
            sb.Append(',');
            AppendJsonProperty(sb, ToolProtocolFields.FieldOutput, envelope.Result.Output);
            sb.Append(',');
            AppendJsonProperty(sb, ToolProtocolFields.FieldErrorCode, envelope.Result.ErrorCode);
            sb.Append(',');
            AppendJsonProperty(sb, ToolProtocolFields.FieldErrorMessage, envelope.Result.ErrorMessage);
            sb.Append('}');
            sb.Append('}');
            return sb.ToString();
        }

        private static Dictionary<string, object> ReadArgs(string json)
        {
            int index = FindTopLevelValue(json, ToolProtocolFields.FieldArgs);
            while (index < json.Length && char.IsWhiteSpace(json[index]))
            {
                index++;
            }
            if (StartsWith(json, index, "null"))
            {
                return new Dictionary<string, object>();
            }
            if (index >= json.Length || json[index] != '{')
            {
                throw new DisconnectedException("JSON field is not an object/null: " + ToolProtocolFields.FieldArgs);
            }

            Dictionary<string, object> args = new Dictionary<string, object>();
            int end = FindMatchingJsonDelimiter(json, index);
            index++;
            while (index < end)
            {
                while (index < end && (char.IsWhiteSpace(json[index]) || json[index] == ','))
                {
                    index++;
                }
                if (index >= end)
                {
                    break;
                }
                if (json[index] != '"')
                {
                    throw new DisconnectedException("JSON args key is not a string");
                }
                int keyEnd = FindStringEnd(json, index + 1);
                string key = UnescapeSimple(json.Substring(index + 1, keyEnd - index - 1));
                index = keyEnd + 1;
                while (index < end && char.IsWhiteSpace(json[index]))
                {
                    index++;
                }
                if (index >= end || json[index] != ':')
                {
                    throw new DisconnectedException("JSON args key has no value: " + key);
                }
                index++;
                while (index < end && char.IsWhiteSpace(json[index]))
                {
                    index++;
                }
                int valueEnd = FindJsonValueEnd(json, index, end);
                args[key] = ReadSimpleJsonValue(json.Substring(index, valueEnd - index));
                index = valueEnd;
            }
            return args;
        }

        private static object ReadSimpleJsonValue(string raw)
        {
            raw = raw.Trim();
            if (raw.Length == 0)
            {
                throw new DisconnectedException("JSON args value type is unsupported: <empty>");
            }
            if (raw == "null")
            {
                return null;
            }
            if (raw == "true")
            {
                return true;
            }
            if (raw == "false")
            {
                return false;
            }
            if (raw[0] == '"')
            {
                if (raw.Length < 2 || raw[raw.Length - 1] != '"')
                {
                    throw new DisconnectedException("JSON string value is unterminated");
                }
                return UnescapeSimple(raw.Substring(1, raw.Length - 2));
            }
            if (raw[0] == '{' || raw[0] == '[')
            {
                throw new DisconnectedException("JSON args value type is unsupported: " + raw);
            }
            int integer;
            if (int.TryParse(raw, NumberStyles.Integer, CultureInfo.InvariantCulture, out integer))
            {
                return integer;
            }
            throw new DisconnectedException("JSON args value type is unsupported: " + raw);
        }

        private static int ReadInt(string json, string name)
        {
            int index = FindTopLevelValue(json, name);
            int sign = 1;
            if (json[index] == '-')
            {
                sign = -1;
                index++;
            }
            int start = index;
            long value = 0;
            long maxMagnitude = sign == -1 ? -(long)int.MinValue : int.MaxValue;
            while (index < json.Length && json[index] >= '0' && json[index] <= '9')
            {
                value = (value * 10) + (json[index] - '0');
                if (value > maxMagnitude)
                {
                    throw new DisconnectedException("JSON field integer is out of Int32 range: " + name);
                }
                index++;
            }
            if (index == start)
            {
                throw new DisconnectedException("JSON field is not an integer: " + name);
            }
            while (index < json.Length && char.IsWhiteSpace(json[index]))
            {
                index++;
            }
            if (index < json.Length &&
                json[index] != ',' &&
                json[index] != '}' &&
                json[index] != ']')
            {
                throw new DisconnectedException("JSON field is not a strict integer: " + name);
            }
            return (int)(value * sign);
        }

        private static string ReadStringOrNull(string json, string name)
        {
            int index = FindTopLevelValue(json, name);
            if (StartsWith(json, index, "null"))
            {
                return null;
            }
            if (json[index] != '"')
            {
                throw new DisconnectedException("JSON field is not a string/null: " + name);
            }
            int end = FindStringEnd(json, index + 1);
            return UnescapeSimple(json.Substring(index + 1, end - index - 1));
        }

        private static string ReadOptionalString(string json, string name)
        {
            try
            {
                return ReadStringOrNull(json, name);
            }
            catch (DisconnectedException ex)
            {
                if (ex.Message == "JSON field missing: " + name)
                {
                    return null;
                }
                throw;
            }
        }

        private static int? ReadNullableInt(string json, string name)
        {
            try
            {
                return ReadInt(json, name);
            }
            catch (DisconnectedException ex)
            {
                if (ex.Message == "JSON field missing: " + name)
                {
                    return null;
                }
                throw;
            }
        }

        private static string ReadRequiredString(string json, string name)
        {
            string value = ReadStringOrNull(json, name);
            if (value == null)
            {
                throw new DisconnectedException("JSON field is required: " + name);
            }
            return value;
        }

        private static void RejectTopLevelField(string json, string name)
        {
            try
            {
                FindTopLevelValue(json, name);
            }
            catch (DisconnectedException ex)
            {
                if (ex.Message == "JSON field missing: " + name)
                {
                    return;
                }
                throw;
            }
            throw new DisconnectedException("Unsupported legacy tool_call field: " + name);
        }

        private static string TerminalActionCacheKey(int sessionEpoch, string actionNonce)
        {
            return sessionEpoch.ToString(CultureInfo.InvariantCulture) + ":" + actionNonce;
        }

        private static string ReadStringArgOrNull(Dictionary<string, object> args, string name)
        {
            if (args == null || !args.ContainsKey(name))
            {
                return null;
            }
            return args[name] as string;
        }

        private static int FindTopLevelValue(string json, string name)
        {
            if (json == null)
            {
                throw new DisconnectedException("JSON message is null");
            }

            int depth = 0;
            bool inString = false;
            bool escaping = false;
            string lastString = null;

            for (int i = 0; i < json.Length; i++)
            {
                char c = json[i];
                if (inString)
                {
                    if (escaping)
                    {
                        escaping = false;
                    }
                    else if (c == '\\')
                    {
                        escaping = true;
                    }
                    else if (c == '"')
                    {
                        int start = FindStringStart(json, i);
                        lastString = UnescapeSimple(json.Substring(start + 1, i - start - 1));
                        inString = false;
                    }
                    continue;
                }

                if (c == '"')
                {
                    inString = true;
                    continue;
                }
                if (c == '{' || c == '[')
                {
                    depth++;
                    continue;
                }
                if (c == '}' || c == ']')
                {
                    depth--;
                    continue;
                }
                if (depth == 1 && c == ':' && lastString != null)
                {
                    bool expectingValueForLastString = (lastString == name);
                    lastString = null;
                    if (expectingValueForLastString)
                    {
                        int valueIndex = i + 1;
                        while (valueIndex < json.Length && char.IsWhiteSpace(json[valueIndex]))
                        {
                            valueIndex++;
                        }
                        if (valueIndex >= json.Length)
                        {
                            throw new DisconnectedException("JSON field has no value: " + name);
                        }
                        return valueIndex;
                    }
                }
            }

            throw new DisconnectedException("JSON field missing: " + name);
        }

        private static int FindJsonValueEnd(string json, int start, int limit)
        {
            if (start >= limit)
            {
                throw new DisconnectedException("JSON value is empty");
            }
            if (json[start] == '"')
            {
                return FindStringEnd(json, start + 1) + 1;
            }
            if (json[start] == '{' || json[start] == '[')
            {
                return FindMatchingJsonDelimiter(json, start) + 1;
            }
            int index = start;
            while (index < limit && json[index] != ',' && json[index] != '}' && json[index] != ']')
            {
                index++;
            }
            return index;
        }

        private static int FindMatchingJsonDelimiter(string json, int start)
        {
            char open = json[start];
            char close = open == '{' ? '}' : ']';
            int depth = 0;
            bool inString = false;
            bool escaping = false;
            for (int i = start; i < json.Length; i++)
            {
                char c = json[i];
                if (inString)
                {
                    if (escaping)
                    {
                        escaping = false;
                    }
                    else if (c == '\\')
                    {
                        escaping = true;
                    }
                    else if (c == '"')
                    {
                        inString = false;
                    }
                    continue;
                }
                if (c == '"')
                {
                    inString = true;
                    continue;
                }
                if (c == open)
                {
                    depth++;
                }
                else if (c == close)
                {
                    depth--;
                    if (depth == 0)
                    {
                        return i;
                    }
                }
            }
            throw new DisconnectedException("JSON delimiter is not closed");
        }

        private static int FindStringEnd(string json, int start)
        {
            bool escaping = false;
            for (int i = start; i < json.Length; i++)
            {
                if (escaping)
                {
                    escaping = false;
                }
                else if (json[i] == '\\')
                {
                    escaping = true;
                }
                else if (json[i] == '"')
                {
                    return i;
                }
            }
            throw new DisconnectedException("JSON string unterminated");
        }

        private static int FindStringStart(string json, int endQuote)
        {
            int i = endQuote - 1;
            while (i >= 0)
            {
                if (json[i] == '"' && !IsEscaped(json, i))
                {
                    return i;
                }
                i--;
            }
            throw new DisconnectedException("JSON parser lost string start");
        }

        private static bool IsEscaped(string json, int quoteIndex)
        {
            int slashCount = 0;
            for (int i = quoteIndex - 1; i >= 0 && json[i] == '\\'; i--)
            {
                slashCount++;
            }
            return (slashCount % 2) == 1;
        }

        private static string UnescapeSimple(string value)
        {
            if (value == null || value.Length == 0)
            {
                return value;
            }

            StringBuilder sb = new StringBuilder(value.Length);
            for (int i = 0; i < value.Length; i++)
            {
                char c = value[i];
                if (c != '\\')
                {
                    sb.Append(c);
                    continue;
                }
                if (i + 1 >= value.Length)
                {
                    throw new DisconnectedException("JSON string has trailing escape");
                }

                i++;
                char escaped = value[i];
                switch (escaped)
                {
                    case '"': sb.Append('"'); break;
                    case '\\': sb.Append('\\'); break;
                    case '/': sb.Append('/'); break;
                    case 'b': sb.Append('\b'); break;
                    case 'f': sb.Append('\f'); break;
                    case 'n': sb.Append('\n'); break;
                    case 'r': sb.Append('\r'); break;
                    case 't': sb.Append('\t'); break;
                    case 'u':
                        if (i + 4 >= value.Length)
                        {
                            throw new DisconnectedException("JSON unicode escape is incomplete");
                        }
                        string hex = value.Substring(i + 1, 4);
                        if (!int.TryParse(hex, NumberStyles.HexNumber, CultureInfo.InvariantCulture, out var codepoint))
                        {
                            throw new DisconnectedException("JSON unicode escape is invalid: " + hex);
                        }
                        sb.Append((char)codepoint);
                        i += 4;
                        break;
                    default:
                        throw new DisconnectedException("JSON string has unsupported escape: " + escaped);
                }
            }
            return sb.ToString();
        }

        private static string CreateSupervisorResponseMessageId(string inReplyTo, int sessionEpoch)
        {
            return "supervisor_response:" +
                (inReplyTo ?? "no_request") + ":" +
                sessionEpoch.ToString() + ":" +
                System.Guid.NewGuid().ToString("N");
        }

        private static bool StartsWith(string value, int index, string expected)
        {
            if (index + expected.Length > value.Length)
            {
                return false;
            }
            for (int i = 0; i < expected.Length; i++)
            {
                if (value[index + i] != expected[i])
                {
                    return false;
                }
            }
            return true;
        }

        private static void AppendJsonPropertyName(StringBuilder sb, string name)
        {
            AppendJsonString(sb, name);
            sb.Append(':');
        }

        private static void AppendJsonProperty(StringBuilder sb, string name, string value)
        {
            AppendJsonPropertyName(sb, name);
            if (value == null)
            {
                sb.Append("null");
            }
            else
            {
                AppendJsonString(sb, value);
            }
        }

        private static void AppendJsonProperty(StringBuilder sb, string name, int value)
        {
            AppendJsonPropertyName(sb, name);
            sb.Append(value.ToString(CultureInfo.InvariantCulture));
        }

        private static void AppendJsonProperty(StringBuilder sb, string name, object value)
        {
            AppendJsonPropertyName(sb, name);
            AppendJsonValue(sb, value);
        }

        private static void AppendJsonValue(StringBuilder sb, object value)
        {
            if (value == null)
            {
                sb.Append("null");
                return;
            }
            string stringValue = value as string;
            if (stringValue != null)
            {
                AppendJsonString(sb, stringValue);
                return;
            }
            if (value is bool)
            {
                sb.Append((bool)value ? "true" : "false");
                return;
            }
            if (value is int)
            {
                sb.Append(((int)value).ToString(CultureInfo.InvariantCulture));
                return;
            }
            Dictionary<string, object> map = value as Dictionary<string, object>;
            if (map != null)
            {
                sb.Append('{');
                bool first = true;
                foreach (KeyValuePair<string, object> entry in map)
                {
                    if (!first)
                    {
                        sb.Append(',');
                    }
                    first = false;
                    AppendJsonPropertyName(sb, entry.Key);
                    AppendJsonValue(sb, entry.Value);
                }
                sb.Append('}');
                return;
            }
            AppendJsonString(sb, value.ToString());
        }

        private static void AppendJsonString(StringBuilder sb, string value)
        {
            sb.Append('"');
            if (value != null)
            {
                for (int i = 0; i < value.Length; i++)
                {
                    char c = value[i];
                    switch (c)
                    {
                        case '\\': sb.Append("\\\\"); break;
                        case '"': sb.Append("\\\""); break;
                        case '\b': sb.Append("\\b"); break;
                        case '\f': sb.Append("\\f"); break;
                        case '\n': sb.Append("\\n"); break;
                        case '\r': sb.Append("\\r"); break;
                        case '\t': sb.Append("\\t"); break;
                        default:
                            if (c < 0x20)
                            {
                                sb.Append("\\u").Append(((int)c).ToString("x4", CultureInfo.InvariantCulture));
                            }
                            else
                            {
                                sb.Append(c);
                            }
                            break;
                    }
                }
            }
            sb.Append('"');
        }
    }

    public sealed class ToolProtocolFields
    {
        public const string FieldType = "type";
        public const string FieldCallId = "call_id";
        public const string FieldTool = "tool";
        public const string FieldArgs = "args";
        public const string FieldResult = "result";
        public const string FieldMessageId = "message_id";
        public const string FieldInReplyTo = "in_reply_to";
        public const string FieldSessionEpoch = "session_epoch";
        public const string FieldActionNonce = "action_nonce";
        public const string FieldStateVersion = "state_version";
        public const string FieldStatus = "status";
        public const string FieldOutput = "output";
        public const string FieldErrorCode = "error_code";
        public const string FieldErrorMessage = "error_message";
        public const string FieldAction = "action";
        public const string FieldChoiceId = "choice_id";
        public const string FieldReason = "reason";
        public const string FieldLegacyTid = "tid";

        public const string TypeToolCall = "tool_call";
        public const string TypeToolResult = "tool_result";
        public const string TypeSupervisorRequest = "supervisor_request";
        public const string TypeSupervisorResponse = "supervisor_response";

        private ToolProtocolFields()
        {
        }
    }

    public sealed class ToolCallEnvelope
    {
        public string Type = ToolProtocolFields.TypeToolCall;
        public string CallId;
        public string Tool;
        public Dictionary<string, object> Args;
        public string MessageId;
        public int SessionEpoch;
        public string ActionNonce;
        public int? StateVersion;
    }

    public sealed class SupervisorRequestEnvelope
    {
        public string Type = ToolProtocolFields.TypeSupervisorRequest;
        public string MessageId;
        public int SessionEpoch;
    }

    public sealed class SupervisorResponseEnvelope
    {
        public const string SupervisorActionResume = "resume";

        public string Type = ToolProtocolFields.TypeSupervisorResponse;
        public string MessageId;
        public string InReplyTo;
        public int SessionEpoch;
        public string Action;
        public string ChoiceId;
        public string Reason;
    }

    public sealed class ToolResultEnvelope
    {
        public string Type = ToolProtocolFields.TypeToolResult;
        public string CallId;
        public string Tool;
        public ToolResult Result;
        public string MessageId = CreateMessageId(null, null, 0);
        public string InReplyTo;
        public int SessionEpoch;
        public string ActionNonce;

        public static ToolResultEnvelope FromError(
            string callId,
            string tool,
            string inReplyTo,
            int sessionEpoch,
            string errorCode,
            string errorMessage)
        {
            return new ToolResultEnvelope
            {
                CallId = callId,
                Tool = tool,
                Result = ToolResult.Error(errorCode, errorMessage),
                MessageId = CreateMessageId(callId, tool, sessionEpoch),
                InReplyTo = inReplyTo,
                SessionEpoch = sessionEpoch,
            };
        }

        public static string CreateMessageId(string callId, string tool, int sessionEpoch)
        {
            return "tool_result:" +
                (callId ?? "no_call") + ":" +
                (tool ?? "no_tool") + ":" +
                sessionEpoch.ToString() + ":" +
                System.Guid.NewGuid().ToString("N");
        }
    }

    public sealed class ToolResult
    {
        public const string StatusOk = "ok";
        public const string StatusError = "error";

        // Wire contract: ToolResult is nested under top-level "result" and
        // serialized with status/output/error_code/error_message keys.
        public string Status;
        public object Output;
        public string ErrorCode;
        public string ErrorMessage;

        public static ToolResult Ok(object output)
        {
            return new ToolResult
            {
                Status = StatusOk,
                Output = output,
                ErrorCode = null,
                ErrorMessage = null,
            };
        }

        public static ToolResult Error(string errorCode, string errorMessage)
        {
            return new ToolResult
            {
                Status = StatusError,
                Output = null,
                ErrorCode = errorCode,
                ErrorMessage = errorMessage,
            };
        }
    }

    public static class TerminalActionOutput
    {
        public static Dictionary<string, object> Accepted(string actionKind)
        {
            Dictionary<string, object> output = Base(actionKind, true, "accepted");
            output["execution_status"] = "accepted";
            return output;
        }

        public static Dictionary<string, object> Stale(string acceptanceStatus)
        {
            Dictionary<string, object> output = Base("terminal_action", false, acceptanceStatus);
            output["execution_status"] = "rejected";
            return output;
        }

        private static Dictionary<string, object> Base(
            string actionKind,
            bool accepted,
            string acceptanceStatus)
        {
            return new Dictionary<string, object>
            {
                { "accepted", accepted },
                { "turn_complete", accepted },
                { "action_kind", actionKind },
                { "acceptance_status", acceptanceStatus },
                { "safety_decision", accepted ? "pass" : "block" },
            };
        }
    }
}
