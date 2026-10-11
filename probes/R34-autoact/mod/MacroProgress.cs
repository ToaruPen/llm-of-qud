namespace LlmOfQud.ProbeR34
{
    public sealed class MacroProgress
    {
        public readonly string Kind;
        public readonly long StartTurn;
        public readonly int Budget;
        public readonly int TargetX;
        public readonly int TargetY;
        private long _lastTurn;
        private int _lastX;
        private int _lastY;
        private int _stationary;

        public MacroProgress(string kind, long turn, int x, int y, int budget, int targetX, int targetY)
        {
            Kind = kind; StartTurn = turn; Budget = budget;
            TargetX = targetX; TargetY = targetY;
            _lastTurn = turn; _lastX = x; _lastY = y;
        }

        public string Observe(long turn, int x, int y, bool active)
        {
            if (Kind == "goto" && x == TargetX && y == TargetY) return "ARRIVED";
            if (turn - StartTurn >= Budget) return "BUDGET";
            if (!active) return "ENGINE_STOP";
            if (turn > _lastTurn)
            {
                _stationary = x == _lastX && y == _lastY ? _stationary + 1 : 0;
                _lastTurn = turn; _lastX = x; _lastY = y;
            }
            if (Kind != "rest" && _stationary >= 6) return "STUCK";
            return null;
        }
    }
}
