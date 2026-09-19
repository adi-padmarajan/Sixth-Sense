from __future__ import annotations

import unittest

from controller_link.protocol import SCHEMA_VERSION, ChannelState, HealthEvent
from controller_link.state import ControllerState


class FakeClock:
    def __init__(self, start=0.0):
        self.now = start

    def __call__(self):
        return self.now


def channel_state(session_id="s1", sequence=1, channel="front", **overrides):
    fields = dict(
        schema_version=SCHEMA_VERSION, msg_type="channel_state",
        source_id="fake-controller", session_id=session_id, sequence=sequence,
        source_mode="simulated", ts_mono_ms=0, channel=channel, distance_mm=1200,
        age_ms=10, health="ok", band="mid", config_version=1,
    )
    fields.update(overrides)
    return ChannelState(**fields)


class ControllerStateTests(unittest.TestCase):
    def test_apply_and_read_a_channel(self):
        state = ControllerState(clock=FakeClock())
        self.assertTrue(state.apply_channel_state(channel_state()))
        reading = state.channel("front")
        self.assertIsNotNone(reading)
        self.assertEqual(reading.state.distance_mm, 1200)

    def test_unknown_channel_never_seen_reads_as_none(self):
        state = ControllerState(clock=FakeClock())
        state.apply_channel_state(channel_state(channel="front"))
        self.assertIsNone(state.channel("rear"))

    def test_out_of_order_sequence_is_rejected(self):
        state = ControllerState(clock=FakeClock())
        self.assertTrue(state.apply_channel_state(channel_state(sequence=5)))
        self.assertFalse(state.apply_channel_state(channel_state(sequence=3, distance_mm=99)))
        # The stale, out-of-order reading must not have overwritten the newer one.
        self.assertEqual(state.channel("front").state.distance_mm, 1200)

    def test_duplicate_sequence_is_rejected(self):
        state = ControllerState(clock=FakeClock())
        self.assertTrue(state.apply_channel_state(channel_state(sequence=5)))
        self.assertFalse(state.apply_channel_state(channel_state(sequence=5, distance_mm=999)))

    def test_new_session_clears_prior_readings(self):
        state = ControllerState(clock=FakeClock())
        state.apply_channel_state(channel_state(session_id="s1", sequence=1, channel="front"))
        state.apply_channel_state(channel_state(session_id="s1", sequence=2, channel="rear"))
        self.assertEqual(set(state.channels()), {"front", "rear"})
        # A new session_id (controller restart) starts clean: 'rear' from the
        # old session must not linger as if it were current.
        state.apply_channel_state(channel_state(session_id="s2", sequence=1, channel="front"))
        self.assertEqual(set(state.channels()), {"front"})

    def test_new_session_resets_sequence_bookkeeping(self):
        state = ControllerState(clock=FakeClock())
        state.apply_channel_state(channel_state(session_id="s1", sequence=100))
        # Sequence 1 would be rejected as stale under the old session, but a
        # session change means sequence numbering restarted too.
        self.assertTrue(state.apply_channel_state(channel_state(session_id="s2", sequence=1)))

    def test_total_age_combines_source_age_and_receipt_delay(self):
        clock = FakeClock(start=100.0)
        state = ControllerState(clock=clock)
        state.apply_channel_state(channel_state(age_ms=50))  # received at t=100.0
        clock.now = 100.25  # 250 ms have passed since receipt
        age_s = state.total_age_s(state.channel("front"))
        self.assertAlmostEqual(age_s, 0.05 + 0.25, places=6)

    def test_reset_drops_everything(self):
        state = ControllerState(clock=FakeClock())
        state.apply_channel_state(channel_state())
        state.reset()
        self.assertEqual(state.channels(), {})
        self.assertIsNone(state.channel("front"))

    def test_health_events_apply_the_same_way(self):
        state = ControllerState(clock=FakeClock())
        event = HealthEvent(
            schema_version=SCHEMA_VERSION, msg_type="health_event",
            source_id="fake-controller", session_id="s1", sequence=1,
            source_mode="simulated", ts_mono_ms=0, subsystem="controller",
            state="ready", reason="", detected_age_ms=0, recovered=True,
        )
        self.assertTrue(state.apply_health_event(event))
        self.assertIn("controller", state.health())


if __name__ == "__main__":
    unittest.main()
