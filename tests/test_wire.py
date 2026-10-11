import json
import unittest

from harness import wire
from tests.support import (RUN_ID, heartbeat_frame, make_observation, make_telemetry,
                           request_frame, result_frame)


def _request(**changes):
    message = json.loads(request_frame(1))
    for path, value in changes.items():
        target = message
        keys = path.split("__")
        for key in keys[:-1]:
            target = target[int(key)] if isinstance(target, list) else target[key]
        last = keys[-1]
        if value is _DELETE:
            del target[last]
        elif isinstance(target, list):
            target[int(last)] = value
        else:
            target[last] = value
    return json.dumps(message, ensure_ascii=False)


_DELETE = object()


class ParseFrameTests(unittest.TestCase):
    def test_realistic_request_parses(self):
        message = wire.parse_game_frame(request_frame(1))
        self.assertEqual(message["kind"], "request")
        self.assertEqual(message["seq"], 1)
        self.assertEqual(len(message["observation"]["map"]), 25)

    def test_bridge_compact_suspended_frame_parses(self):
        # Bridge.cs serializes it with JsonConvert.SerializeObject (compact, this key order).
        frame = '{"kind":"suspended","run_id":"%s","seq":4,"reason":"game_not_running"}' % RUN_ID
        message = wire.parse_game_frame(frame)
        self.assertEqual((message["kind"], message["seq"], message["reason"]),
                         ("suspended", 4, "game_not_running"))

    def test_realistic_result_and_heartbeat_parse(self):
        self.assertEqual(wire.parse_game_frame(result_frame(1, "wait"))["kind"], "result")
        self.assertEqual(wire.parse_game_frame(heartbeat_frame(0))["seq"], 0)

    def test_rejects_malformed_json_and_constants(self):
        bad_frames = [
            "not json",
            "[]",
            '{"kind":"heartbeat","run_id":"%s","seq":NaN}' % RUN_ID,
            '{"kind":"heartbeat","run_id":"%s","seq":1,"seq":2}' % RUN_ID,
            b'{"kind":"heartbeat"}',
            '{"kind":"hello","run_id":"%s","seq":1}' % RUN_ID,
            heartbeat_frame(1, run_id="not-a-uuid"),
        ]
        for frame in bad_frames:
            with self.subTest(frame=frame[:60]):
                with self.assertRaises(wire.WireError):
                    wire.parse_game_frame(frame)

    def test_rejects_oversized_frame(self):
        frame = request_frame(1)
        frame = frame[:-1] + ', "pad": "' + "x" * wire.MAX_FRAME_BYTES + '"}'
        with self.assertRaises(wire.WireError):
            wire.parse_game_frame(frame)

    def test_rejects_shape_violations(self):
        cases = {
            "seq bool": _request(seq=True),
            "seq zero": _request(seq=0),
            "extra envelope key": _request(extra=1),
            "missing telemetry": _request(telemetry=_DELETE),
            "extra observation key": _request(observation__hp_numbers=[1]),
            "extra vitals key": _request(observation__vitals__armor=3),
            "hp bool": _request(observation__vitals__hp=True),
            "hp string": _request(observation__vitals__hp="14"),
            "zone int": _request(observation__vitals__zone=3),
            "threat extra key": _request(observation__threats__0__hp=10),
            "threat hostile string": _request(observation__threats__0__hostile="yes"),
            "digest too long": _request(observation__digest=["m"] * 13),
            "digest non string": _request(observation__digest=[1]),
            "map rows": _request(observation__map=make_observation()["map"][:24]),
            "map width": _request(observation__map__3="#" * 79),
            "map_frame float": _request(observation__map_frame=1.5),
            "counter negative": _request(telemetry__end_player_turns=-1),
            "counter bool": _request(telemetry__player_turn_entries=False),
            "queue entry missing": _request(telemetry__game_queue=[{"task_id": None}]),
            "queue task_id int": _request(telemetry__game_queue=[
                {"task_id": 3, "type": "t", "method": "m", "classification": "ui_task"}]),
        }
        for name, frame in cases.items():
            with self.subTest(case=name):
                with self.assertRaises(wire.WireError):
                    wire.parse_game_frame(frame)

    def test_extra_telemetry_keys_are_retained(self):
        telemetry = make_telemetry()
        telemetry["focus_flag"] = True
        message = wire.parse_game_frame(request_frame(1, telemetry=telemetry))
        self.assertTrue(message["telemetry"]["focus_flag"])

    def test_result_shape_violations(self):
        base = json.loads(result_frame(1, "move"))
        cases = {
            "executed int": dict(base, executed=1),
            "unknown action": dict(base, action="wish"),
            "negative steps": dict(base, steps=-1),
            "reason missing": {k: v for k, v in base.items() if k != "reason"},
            "energy string": dict(base, energy_after="0"),
        }
        for name, message in cases.items():
            with self.subTest(case=name):
                with self.assertRaises(wire.WireError):
                    wire.parse_game_frame(json.dumps(message))


def _with_optional(**extra):
    observation = make_observation()
    observation.update({
        "kit": [{"id": "i1", "name": "bronze dagger", "slot": "Hand"},
                {"id": "i2", "name": "{{c|weird knife}}", "slot": None}],
        "status": {"effects": ["{{r|bleeding}}"], "food_water": "Sated Quenched"},
        "place": {"name": "Joppa", "world_map": False, "lost": False},
    })
    observation.update(extra)
    return observation


class OptionalObservationTests(unittest.TestCase):
    """kit/status/place are optional additive keys; old M1 observations stay valid."""

    def test_optional_player_visible_keys_parse(self):
        message = wire.parse_game_frame(request_frame(1, observation=_with_optional()))
        self.assertEqual(message["observation"]["kit"][1]["slot"], None)
        wire.parse_game_frame(result_frame(1, "wait", observation=_with_optional()))

    def test_old_m1_observation_without_optional_keys_still_parses(self):
        wire.validate_observation(make_observation())

    def test_optional_key_shape_violations(self):
        cases = {
            "kit not list": _with_optional(kit={}),
            "kit extra key": _with_optional(kit=[{"id": "i1", "name": "x", "slot": None, "blueprint": "Dagger"}]),
            "kit slot int": _with_optional(kit=[{"id": "i1", "name": "x", "slot": 3}]),
            "kit id pattern": _with_optional(kit=[{"id": "e1", "name": "x", "slot": None}]),
            "kit duplicate id": _with_optional(kit=[{"id": "i1", "name": "x", "slot": None}] * 2),
            "kit too long": _with_optional(kit=[{"id": f"i{n}", "name": "x", "slot": None}
                                                for n in range(1, wire.KIT_MAX + 2)]),
            "status extra": _with_optional(status={"effects": [], "food_water": "", "hp": 3}),
            "status effect int": _with_optional(status={"effects": [1], "food_water": ""}),
            "place missing lost": _with_optional(place={"name": "Joppa", "world_map": False}),
            "place world_map str": _with_optional(place={"name": "Joppa", "world_map": "no", "lost": False}),
            "unknown optional key": _with_optional(true_names=["vibro dagger"]),
        }
        for name, observation in cases.items():
            with self.subTest(case=name):
                with self.assertRaises(wire.WireError):
                    wire.parse_game_frame(request_frame(1, observation=observation))


class DecisionTests(unittest.TestCase):
    def test_serialization_is_exact_compact_contract(self):
        frame = wire.serialize_decision(RUN_ID, 7, "move", "NE", 1)
        self.assertEqual(
            frame,
            '{"kind":"decision","run_id":"%s","seq":7,"action":"move","dir":"NE","budget":1}' % RUN_ID,
        )
        self.assertEqual(
            wire.serialize_decision(RUN_ID, 8, "explore", None, 20),
            '{"kind":"decision","run_id":"%s","seq":8,"action":"explore","dir":null,"budget":20}' % RUN_ID,
        )

    def test_normalize_maps_default_budget_to_one_for_direct_actions(self):
        self.assertEqual(wire.normalize_decision("move", "N", 20), ("move", "N", 1))
        self.assertEqual(wire.normalize_decision("move", "U", 20), ("move", "U", 1))
        self.assertEqual(wire.normalize_decision("attack", "SW", 5), ("attack", "SW", 1))
        self.assertEqual(wire.normalize_decision("wait", None, 20), ("wait", None, 1))
        self.assertEqual(wire.normalize_decision("explore", None, 40), ("explore", None, 40))
        self.assertEqual(wire.normalize_decision("explore", None, 1), ("explore", None, 1))

    def test_normalize_rejects_invalid(self):
        cases = [
            ("wish", None, 1),
            ("move", None, 20),
            ("move", "n", 20),
            ("move", "NNE", 20),
            ("attack", "U", 20),
            ("attack", None, 20),
            ("wait", "N", 20),
            ("explore", "N", 20),
            ("explore", None, 0),
            ("explore", None, 41),
            ("explore", None, True),
            ("move", "N", "1"),
        ]
        for case in cases:
            with self.subTest(case=case):
                with self.assertRaises(wire.WireError):
                    wire.normalize_decision(*case)

    def test_wire_decision_validation_requires_budget_one_for_direct_actions(self):
        wire.validate_wire_decision("move", "N", 1)
        wire.validate_wire_decision("explore", None, 33)
        with self.assertRaises(wire.WireError):
            wire.validate_wire_decision("move", "N", 20)


if __name__ == "__main__":
    unittest.main()
