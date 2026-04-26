using System.Collections.Generic;

namespace LLMOfQud
{
    public sealed class Pos
    {
        public int X;
        public int Y;
        public string Zone;
    }

    public sealed class DecisionInput
    {
        public int Turn;
        public string Schema = "decision_input.v1";
        public PlayerSnapshot Player;
        public AdjacencySnapshot Adjacent;
        public RecentHistory Recent;
    }

    public sealed class PlayerSnapshot
    {
        public int Hp;
        public int MaxHp;
        public Pos Pos;
    }

    public sealed class AdjacencySnapshot
    {
        public string HostileDir;
        public string HostileId;
        public List<string> BlockedDirs;
    }

    public sealed class RecentHistory
    {
        public int LastActionTurn;
        public string LastAction;
        public string LastDir;
        public bool LastResult;
    }

    public sealed class Decision
    {
        // Intent enum: "attack" | "escape" | "explore"
        // Action enum: "Move" | "AttackDirection"
        // Locked together with command_issuance.v1's action enum;
        // PassTurn is engine bookkeeping (3-layer drain fallback),
        // never a Decision.Action. Adding wait/PassTurn requires a
        // joint decision.v2 + command_issuance.v2 bump per spec.
        public string Intent;
        public string Action;
        public string Dir;
        public string ReasonCode;
        public string Error;
    }

    // IDecisionPolicy.Decide MUST NOT reference The.*, Cell.*,
    // MetricsManager, or any CoQ API outside the supplied DecisionInput.
    // PROBE 2' (Task 4 Step 2) enforces this by grep.
    public interface IDecisionPolicy
    {
        Decision Decide(DecisionInput input);
    }
}
