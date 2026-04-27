using System;
using System.Collections.Generic;

namespace LLMOfQud
{
    // IMPORTANT: Decide MUST NOT reference The.*, Cell.*, MetricsManager,
    // or any CoQ API outside the supplied DecisionInput. PROBE 2' (Task 4
    // Step 2) enforces this by grep.
    //
    // [Serializable]: LLMOfQudSystem holds an IDecisionPolicy field whose
    // concrete instance is this class. CoQ's save system serializes
    // [Serializable] system instances, so the concrete policy class must
    // also be [Serializable]. HeuristicPolicy is stateless (only static
    // readonly data); serialization is a no-op. Pattern matches
    // decompiled/XRL/CheckpointingSystem.cs:13 (system [Serializable] +
    // [NonSerialized] for fields whose types do not opt-in).
    [Serializable]
    public sealed class HeuristicPolicy : IDecisionPolicy
    {
        // Probe 3b uses 30% as the probe threshold; the policy may use any
        // threshold that satisfies the probe. 50% is a conservative midpoint
        // — passes 3b with margin.
        private const double LowHpRatio = 0.50;
        private const int LowHpFloor = 6;

        // Default explore direction priority. Any deterministic order works
        // as long as probe 3c passes (blocked-direction memory).
        private static readonly string[] ExploreOrder =
            new[] { "E", "SE", "NE", "S", "N", "W", "SW", "NW" };

        public Decision Decide(DecisionInput input)
        {
            string hostileDir = input.Adjacent.HostileDir;
            bool adjacentHostile = (hostileDir != null);

            int hp = input.Player.Hp;
            int maxHp = input.Player.MaxHp;
            int hurtThreshold = (int)System.Math.Max(LowHpFloor, System.Math.Floor(maxHp * LowHpRatio));
            bool lowHp = (hp <= hurtThreshold);

            if (adjacentHostile && lowHp)
            {
                return new Decision
                {
                    Intent = "escape",
                    Action = "Move",
                    Dir = OppositeDir(hostileDir),
                    ReasonCode = "low_hp_adj_hostile",
                    Error = null,
                };
            }

            if (adjacentHostile)
            {
                return new Decision
                {
                    Intent = "attack",
                    Action = "AttackDirection",
                    Dir = hostileDir,
                    ReasonCode = "adj_hostile",
                    Error = null,
                };
            }

            HashSet<string> blocked = (input.Adjacent.BlockedDirs == null)
                ? new HashSet<string>()
                : new HashSet<string>(input.Adjacent.BlockedDirs);

            foreach (string d in ExploreOrder)
            {
                if (!blocked.Contains(d))
                {
                    return new Decision
                    {
                        Intent = "explore",
                        Action = "Move",
                        Dir = d,
                        ReasonCode = (blocked.Count > 0) ? "blocked_dir" : "default_explore",
                        Error = null,
                    };
                }
            }

            // All 8 explore directions are in BlockedDirs. Don't return a
            // wait/PassTurn Decision — that would violate the locked
            // decision.v1 enum (intent ∈ {attack, escape, explore}, action ∈
            // {Move, AttackDirection}, both lock command_issuance.v1's
            // action set). Instead, return explore: Move ExploreOrder[0]
            // and let the 3-layer drain emit fallback="pass_turn" on the
            // [cmd] line.
            return new Decision
            {
                Intent = "explore",
                Action = "Move",
                Dir = ExploreOrder[0],
                ReasonCode = "blocked_dir",
                Error = null,
            };
        }

        private static string OppositeDir(string dir)
        {
            switch (dir)
            {
                case "N":  return "S";
                case "NE": return "SW";
                case "E":  return "W";
                case "SE": return "NW";
                case "S":  return "N";
                case "SW": return "NE";
                case "W":  return "E";
                case "NW": return "SE";
                default:   return null;
            }
        }
    }
}
