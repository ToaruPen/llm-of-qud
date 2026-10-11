using System;
using System.Collections.Generic;

namespace LlmOfQud
{
    public static class ActionPolicy
    {
        private static readonly string[] Attributes = { "Strength", "Agility", "Toughness", "Intelligence", "Willpower", "Ego" };
        public static bool IsItemAction(string action) { return action == "eat" || action == "drink" || action == "apply" || action == "equip" || action == "get" || action == "open"; }

        public static bool IsSkillId(string skill)
        {
            if (string.IsNullOrEmpty(skill) || skill.Length > 200) return false;
            foreach (char c in skill)
                if (char.IsControl(c)) return false;
            return true;
        }

        public static string WithoutVisibleAdjective(string name, string baseName, string adjective)
        {
            if (string.IsNullOrEmpty(name) || string.IsNullOrEmpty(baseName) || string.IsNullOrEmpty(adjective))
                return name;
            int baseAt = name.IndexOf(baseName, StringComparison.Ordinal);
            int adjectiveAt = name.IndexOf(adjective + " ", StringComparison.Ordinal);
            if (adjectiveAt < 0 || baseAt < 0 || adjectiveAt >= baseAt ||
                (adjectiveAt > 0 && name[adjectiveAt - 1] != ' ')) return name;
            return name.Remove(adjectiveAt, adjective.Length + 1);
        }

        public static string FinalizeReason(bool executed, string reason, int energyBefore, int energyAfter, long turnsElapsed)
        {
            return !executed && reason == "blocked" && (energyAfter < energyBefore || turnsElapsed > 0)
                ? "blocked_after_effect" : reason;
        }

        public static bool CanReachCell(int x, int y, int targetX, int targetY)
        {
            return Math.Abs(x - targetX) <= 1 && Math.Abs(y - targetY) <= 1;
        }

        public static string Validate(string action, string direction, int budget, int? x = null, int? y = null,
            string until = null, string item = null, string skill = null, string attribute = null)
        {
            if (action != "move" && action != "attack" && action != "wait" && action != "explore" && action != "goto" && action != "rest" && action != "talk" &&
                action != "learn_skill" && action != "raise_attribute" && !IsItemAction(action))
                return "unsupported_action";
            if (action == "move" || action == "attack" || action == "talk")
            {
                bool compass = Array.IndexOf(new[] { "N", "NE", "E", "SE", "S", "SW", "W", "NW" }, direction) >= 0;
                if (!compass && !(action == "move" && (direction == "U" || direction == "D")))
                    return "invalid_direction";
            }
            else if (direction != null) return "unexpected_direction";
            if (budget < 1 || budget > 40 || (action != "explore" && action != "goto" && action != "rest" && budget != 1))
                return "invalid_budget";
            if (action == "goto")
            {
                if (!x.HasValue || !y.HasValue || x < 0 || x > 79 || y < 0 || y > 24) return "invalid_target";
            }
            else if (x.HasValue || y.HasValue) return "unexpected_target";
            if (until != null && (action != "rest" || (until != "healed" && until != "morning"))) return "invalid_until";
            if (IsItemAction(action))
            {
                bool known = false;
                string prefix = action == "get" ? "p" : "i";
                for (int n = 1; n <= 64; n++) if (item == prefix + n) { known = true; break; }
                if (!known) return "invalid_item";
            }
            else if (item != null) return "unexpected_item";
            if (action == "learn_skill")
            {
                if (!IsSkillId(skill)) return "invalid_skill";
            }
            else if (skill != null) return "unexpected_skill";
            if (action == "raise_attribute")
            {
                if (Array.IndexOf(Attributes, attribute) < 0) return "invalid_attribute";
            }
            else if (attribute != null) return "unexpected_attribute";
            return null;
        }

        public static char TerrainGlyph(bool visible, bool confused, bool solid, bool door, bool liquid, bool up, bool down)
        {
            if (!visible || confused) return '?';
            if (door) return '+';
            if (solid) return '#';
            if (liquid) return '~';
            if (up) return '<';
            if (down) return '>';
            return '.';
        }

        public static char Glyph(char rendered, char backup)
        {
            return rendered != '\0' ? rendered : backup != '\0' ? backup : ' ';
        }
    }

    public sealed class DecisionGate
    {
        private long _seq;
        private bool _accepted;
        public void Open(long seq) { _seq = seq; _accepted = false; }
        public void Close() { _accepted = true; }
        public bool Accept(long seq)
        {
            if (seq != _seq || _accepted) return false;
            _accepted = true;
            return true;
        }
    }

    public sealed class MessageDigest
    {
        private readonly Queue<string> _messages = new Queue<string>();
        public void Add(string text)
        {
            lock (_messages)
            {
                _messages.Enqueue(text ?? "");
                while (_messages.Count > 12) _messages.Dequeue();
            }
        }
        public string[] Snapshot() { lock (_messages) return _messages.ToArray(); }
        public void Clear() { lock (_messages) _messages.Clear(); }
    }

    public sealed class MacroGuard
    {
        private readonly long _start;
        private readonly int _budget;
        private readonly string _kind;
        private readonly int _targetX, _targetY;
        private int _hp;
        private long _lastTurn;
        private int _x, _y, _previousX, _previousY, _stationary, _alternating;
        public MacroGuard(long turn, int budget, int x, int y, string kind = "explore", int targetX = -1, int targetY = -1, int hp = -1)
        {
            _start = _lastTurn = turn; _budget = budget;
            _x = _previousX = x; _y = _previousY = y;
            _kind = kind; _targetX = targetX; _targetY = targetY; _hp = hp;
        }
        public static bool IsRoutineEffect(string name)
        {
            switch (name)
            {
                case "bloody": case "slimy": case "salty": case "wet": case "damp":
                case "oily": case "tarry": case "defensive stance": case "aggressive stance":
                case "dueling stance": case "wading": case "swimming": case "well fed":
                case "sated": case "quenched": case "recuperating": case "basking": case "meditating":
                    return true;
                default: return false;
            }
        }
        public string Observe(long turn, int x, int y, int hp, int maxHp, bool active, bool newHostile,
            bool zoneChanged = false, bool statusChanged = false)
        {
            if (zoneChanged) return "ZONE_CHANGED";
            if (_kind != "rest" && maxHp > 0 && hp * 4 <= maxHp) return "HP_CRITICAL";
            if (_hp >= 0 && hp < _hp) return "HURT";
            _hp = hp;
            if (statusChanged) return "STATUS_CHANGED";
            if (newHostile) return "NEW_HOSTILE";
            if (_kind == "goto" && x == _targetX && y == _targetY) return "ARRIVED";
            if (turn - _start >= _budget) return "BUDGET";
            if (!active) return "ENGINE_STOP";
            if (turn > _lastTurn)
            {
                bool moved = x != _x || y != _y;
                _alternating = moved && x == _previousX && y == _previousY ? _alternating + 1 : 0;
                _stationary = x == _x && y == _y ? _stationary + 1 : 0;
                _previousX = _x; _previousY = _y;
                _lastTurn = turn; _x = x; _y = y;
            }
            return _kind != "rest" && (_stationary >= 6 || _alternating >= 5) ? "STUCK" : null;
        }
    }
}
