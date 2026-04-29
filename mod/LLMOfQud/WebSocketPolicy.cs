using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;

namespace LLMOfQud
{
    [Serializable]
    public sealed class DisconnectedException : Exception
    {
        public DisconnectedException(string message)
            : base(message)
        {
        }

        public DisconnectedException(string message, Exception innerException)
            : base(message, innerException)
        {
        }
    }

    [Serializable]
    public sealed class WebSocketPolicy : IDecisionPolicy
    {
        public const int TIMEOUT_MS = 500;

        private readonly string _endpoint;
        [NonSerialized] private BrainClient _client;

        public WebSocketPolicy(string endpoint, Action onReconnect)
        {
            _endpoint = endpoint ?? BrainClient.DefaultEndpoint;
            EnsureClient(onReconnect);
        }

        public void EnsureClient(Action onReconnect)
        {
            if (_client == null)
            {
                _client = new BrainClient(_endpoint, onReconnect);
            }
            else
            {
                _client.SetReconnectCallback(onReconnect);
            }
            _client.Start();
        }

        public Decision Decide(DecisionInput input)
        {
            if (_client == null)
            {
                throw new DisconnectedException("BrainClient is not initialized");
            }

            string requestJson = BuildDecisionInputJson(input);
            BrainClient.DecisionRequest request = _client.SendDecisionInput(requestJson, TIMEOUT_MS);
            try
            {
                if (!request.ResponseTask.Wait(TIMEOUT_MS))
                {
                    return BuildTimeoutFallback(input);
                }
                string responseJson = request.ResponseTask.Result;
                return ParseDecision(responseJson, input.Turn);
            }
            catch (AggregateException ex)
            {
                Exception inner = ex.InnerException ?? ex;
                if (inner is TimeoutException)
                {
                    return BuildTimeoutFallback(input);
                }
                DisconnectedException disconnected = inner as DisconnectedException;
                if (disconnected != null)
                {
                    throw disconnected;
                }
                throw new DisconnectedException("Brain decision request failed", inner);
            }
        }

        private static Decision BuildTimeoutFallback(DecisionInput input)
        {
            return new Decision
            {
                Intent = "explore",
                Action = "Move",
                Dir = FirstUnblockedDir(input),
                ReasonCode = "timeout_fallback",
                Error = "timeout",
            };
        }

        private static string FirstUnblockedDir(DecisionInput input)
        {
            HashSet<string> blocked = (input != null &&
                                       input.Adjacent != null &&
                                       input.Adjacent.BlockedDirs != null)
                ? new HashSet<string>(input.Adjacent.BlockedDirs)
                : new HashSet<string>();
            string[] order = new[] { "E", "SE", "NE", "S", "N", "W", "SW", "NW" };
            for (int i = 0; i < order.Length; i++)
            {
                if (!blocked.Contains(order[i]))
                {
                    return order[i];
                }
            }
            return "E";
        }

        private static string BuildDecisionInputJson(DecisionInput input)
        {
            StringBuilder sb = new StringBuilder(512);
            sb.Append('{');
            sb.Append("\"turn\":").Append(input.Turn.ToString(CultureInfo.InvariantCulture));
            sb.Append(",\"schema\":");
            SnapshotState.AppendJsonString(sb, "decision_input.v1");

            sb.Append(",\"player\":{\"hp\":");
            sb.Append(input.Player.Hp.ToString(CultureInfo.InvariantCulture));
            sb.Append(",\"max_hp\":");
            sb.Append(input.Player.MaxHp.ToString(CultureInfo.InvariantCulture));
            sb.Append(",\"pos\":{\"x\":");
            sb.Append(input.Player.Pos.X.ToString(CultureInfo.InvariantCulture));
            sb.Append(",\"y\":");
            sb.Append(input.Player.Pos.Y.ToString(CultureInfo.InvariantCulture));
            sb.Append(",\"zone\":");
            SnapshotState.AppendJsonStringOrNull(sb, input.Player.Pos.Zone);
            sb.Append("}}");

            sb.Append(",\"adjacent\":{\"hostile_dir\":");
            SnapshotState.AppendJsonStringOrNull(sb, input.Adjacent.HostileDir);
            sb.Append(",\"hostile_id\":");
            SnapshotState.AppendJsonStringOrNull(sb, input.Adjacent.HostileId);
            sb.Append(",\"blocked_dirs\":[");
            List<string> blockedDirs = input.Adjacent.BlockedDirs;
            if (blockedDirs != null)
            {
                for (int i = 0; i < blockedDirs.Count; i++)
                {
                    if (i > 0)
                    {
                        sb.Append(',');
                    }
                    SnapshotState.AppendJsonString(sb, blockedDirs[i]);
                }
            }
            sb.Append("]}");

            sb.Append(",\"recent\":{\"last_action_turn\":");
            sb.Append(input.Recent.LastActionTurn.ToString(CultureInfo.InvariantCulture));
            sb.Append(",\"last_action\":");
            SnapshotState.AppendJsonStringOrNull(sb, input.Recent.LastAction);
            sb.Append(",\"last_dir\":");
            SnapshotState.AppendJsonStringOrNull(sb, input.Recent.LastDir);
            sb.Append(",\"last_result\":");
            sb.Append(input.Recent.LastResult ? "true" : "false");
            sb.Append("}}");
            return sb.ToString();
        }

        private static Decision ParseDecision(string json, int expectedTurn)
        {
            RequireTopLevelProperty(json, "turn");
            RequireTopLevelProperty(json, "schema");
            RequireTopLevelProperty(json, "input_summary");
            RequireTopLevelProperty(json, "intent");
            RequireTopLevelProperty(json, "action");
            RequireTopLevelProperty(json, "dir");
            RequireTopLevelProperty(json, "reason_code");
            RequireTopLevelProperty(json, "error");

            string schema = ReadStringOrNull(json, "schema");
            if (schema != "decision.v1")
            {
                throw new DisconnectedException("Unsupported decision schema: " + (schema ?? "<null>"));
            }

            int turn = ReadInt(json, "turn");
            if (turn != expectedTurn)
            {
                throw new DisconnectedException(
                    "Decision turn mismatch: expected " +
                    expectedTurn.ToString(CultureInfo.InvariantCulture) +
                    " got " + turn.ToString(CultureInfo.InvariantCulture));
            }

            string intent = ReadStringOrNull(json, "intent");
            string action = ReadStringOrNull(json, "action");
            string dir = ReadStringOrNull(json, "dir");
            ValidateDecisionFields(intent, action, dir);

            return new Decision
            {
                Intent = intent,
                Action = action,
                Dir = dir,
                ReasonCode = ReadStringOrNull(json, "reason_code"),
                Error = ReadStringOrNull(json, "error"),
            };
        }

        private static void ValidateDecisionFields(string intent, string action, string dir)
        {
            if (intent != "attack" && intent != "escape" && intent != "explore")
            {
                throw new DisconnectedException("Unsupported decision intent: " + (intent ?? "<null>"));
            }
            if (action != "Move" && action != "AttackDirection")
            {
                throw new DisconnectedException("Unsupported decision action: " + (action ?? "<null>"));
            }
            if (!IsDirection(dir))
            {
                throw new DisconnectedException("Unsupported decision dir: " + (dir ?? "<null>"));
            }
        }

        private static bool IsDirection(string dir)
        {
            switch (dir)
            {
                case "N":
                case "NE":
                case "E":
                case "SE":
                case "S":
                case "SW":
                case "W":
                case "NW":
                    return true;
                default:
                    return false;
            }
        }

        private static void RequireTopLevelProperty(string json, string name)
        {
            FindTopLevelValue(json, name);
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
            int value = 0;
            while (index < json.Length && json[index] >= '0' && json[index] <= '9')
            {
                value = (value * 10) + (json[index] - '0');
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
            return value * sign;
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
            index++;
            StringBuilder sb = new StringBuilder();
            while (index < json.Length)
            {
                char c = json[index++];
                if (c == '"')
                {
                    return sb.ToString();
                }
                if (c == '\\')
                {
                    if (index >= json.Length)
                    {
                        throw new DisconnectedException("JSON string escape truncated: " + name);
                    }
                    char esc = json[index++];
                    switch (esc)
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
                            if (index + 4 > json.Length)
                            {
                                throw new DisconnectedException("JSON unicode escape truncated: " + name);
                            }
                            string hex = json.Substring(index, 4);
                            sb.Append((char)int.Parse(hex, NumberStyles.HexNumber, CultureInfo.InvariantCulture));
                            index += 4;
                            break;
                        default:
                            throw new DisconnectedException("JSON string escape unsupported: " + name);
                    }
                }
                else
                {
                    sb.Append(c);
                }
            }
            throw new DisconnectedException("JSON string unterminated: " + name);
        }

        private static int FindTopLevelValue(string json, string name)
        {
            if (json == null)
            {
                throw new DisconnectedException("JSON response is null");
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
            return value.Replace("\\\"", "\"").Replace("\\\\", "\\");
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
    }
}
