from __future__ import annotations

import unittest

from controller_link.protocol import (
    SCHEMA_VERSION,
    ChannelState,
    ConfigAck,
    ConfigRequest,
    HealthEvent,
    decode,
    encode,
)

ENVELOPE = dict(
    schema_version=SCHEMA_VERSION, source_id="fake-controller", session_id="s1",
    sequence=1, source_mode="simulated", ts_mono_ms=1000,
)


def channel_state(**overrides):
    fields = dict(
        **ENVELOPE, msg_type="channel_state", channel="front", distance_mm=1200,
        age_ms=10, health="ok", band="mid", config_version=1,
    )
    fields.update(overrides)
    return ChannelState(**fields)


class ChannelStateTests(unittest.TestCase):
    def test_round_trip(self):
        msg = channel_state()
        decoded = decode(encode(msg).decode("utf-8").strip())
        self.assertEqual(decoded, msg)

    def test_rejects_zero_as_missing_sentinel(self):
        with self.assertRaises(ValueError):
            channel_state(distance_mm=0)

    def test_rejects_negative_distance(self):
        with self.assertRaises(ValueError):
            channel_state(distance_mm=-1)

    def test_unknown_band_cannot_carry_a_distance(self):
        with self.assertRaises(ValueError):
            channel_state(band="unknown", distance_mm=1200)

    def test_unknown_channel_rejected(self):
        with self.assertRaises(ValueError):
            channel_state(channel="north")

    def test_missing_measurement_is_null_not_a_sentinel(self):
        msg = channel_state(distance_mm=None, band="unknown", health="unknown")
        self.assertIsNone(msg.distance_mm)


class HealthEventTests(unittest.TestCase):
    def test_round_trip(self):
        msg = HealthEvent(
            **ENVELOPE, msg_type="health_event", subsystem="motor_driver",
            state="fault", reason="overcurrent", detected_age_ms=5, recovered=False,
        )
        decoded = decode(encode(msg).decode("utf-8").strip())
        self.assertEqual(decoded, msg)

    def test_unknown_state_rejected(self):
        with self.assertRaises(ValueError):
            HealthEvent(
                **ENVELOPE, msg_type="health_event", subsystem="motor_driver",
                state="on_fire", reason="", detected_age_ms=0, recovered=False,
            )


class ConfigMessageTests(unittest.TestCase):
    def test_config_request_round_trip(self):
        msg = ConfigRequest(
            **ENVELOPE, msg_type="config_request", request_id="r1",
            base_config_version=3, intent="set_alert_distance_mm",
            param_name="alert_distance_mm", param_value_num=2000.0,
            param_value_str=None, ttl_ms=1500,
        )
        decoded = decode(encode(msg).decode("utf-8").strip())
        self.assertEqual(decoded, msg)

    def test_ttl_must_be_positive(self):
        with self.assertRaises(ValueError):
            ConfigRequest(
                **ENVELOPE, msg_type="config_request", request_id="r1",
                base_config_version=3, intent="pause_feedback",
                param_name=None, param_value_num=None, param_value_str=None, ttl_ms=0,
            )

    def test_rejected_ack_requires_a_reason(self):
        with self.assertRaises(ValueError):
            ConfigAck(
                **ENVELOPE, msg_type="config_ack", request_id="r1",
                result="rejected", reason=None, active_config_version=3,
            )

    def test_config_ack_round_trip(self):
        msg = ConfigAck(
            **ENVELOPE, msg_type="config_ack", request_id="r1",
            result="accepted", reason=None, active_config_version=4,
        )
        decoded = decode(encode(msg).decode("utf-8").strip())
        self.assertEqual(decoded, msg)


class DecodeRobustnessTests(unittest.TestCase):
    def test_unknown_msg_type_rejected(self):
        with self.assertRaises(ValueError):
            decode('{"msg_type": "not_a_real_type"}')

    def test_not_a_json_object_rejected(self):
        with self.assertRaises(ValueError):
            decode("[1, 2, 3]")

    def test_missing_field_rejected(self):
        with self.assertRaises(ValueError):
            decode('{"msg_type": "channel_state", "schema_version": 1}')

    def test_unknown_field_rejected(self):
        raw = encode(channel_state()).decode("utf-8").strip()
        import json
        payload = json.loads(raw)
        payload["extra_field"] = "nope"
        with self.assertRaises(ValueError):
            decode(json.dumps(payload))

    def test_oversized_line_rejected(self):
        with self.assertRaises(ValueError):
            decode("x" * 5000)


if __name__ == "__main__":
    unittest.main()
