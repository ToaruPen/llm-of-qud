from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_disconnect_pause_does_not_emit_decision_channel() -> None:
    source = (ROOT / "mod/LLMOfQud/LLMOfQudSystem.cs").read_text()
    match = re.search(
        r"catch \(DisconnectedException ex\)\s*\{(?P<body>.*?)\n\s*\}\n\s*catch \(Exception ex\)",
        source,
        flags=re.DOTALL,
    )
    assert match is not None
    body = match.group("body")

    assert "[LLMOfQud][decision]" not in body
    assert "[LLMOfQud][disconnect_pause]" in body


def test_brainclient_response_log_includes_round_trip_elapsed_ms() -> None:
    source = (ROOT / "mod/LLMOfQud/BrainClient.cs").read_text()

    assert "Stopwatch.StartNew()" in source
    assert "elapsed_ms=" in source


def test_reconnect_wake_skips_player_turn_without_key_command() -> None:
    source = (ROOT / "mod/LLMOfQud/LLMOfQudSystem.cs").read_text()

    assert "SkipPlayerTurn = true" in source
    assert "Keyboard.KeyEvent.Set()" in source
    assert "Keyboard.PushKey(UnityEngine.KeyCode.None)" not in source
