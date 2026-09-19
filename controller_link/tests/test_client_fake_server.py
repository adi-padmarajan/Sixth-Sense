"""Integration tests over real loopback TCP sockets (no external hardware,
no network, deterministic and offline in the sense CLAUDE.md means by it --
this exercises the actual socket code path, not a mock of it)."""
from __future__ import annotations

import time
import unittest

from controller_link.client import ControllerLinkClient
from controller_link.config import ControllerLinkConfig
from controller_link.fake_server import FakeControllerServer


def wait_until(predicate, timeout_s=2.0, interval_s=0.02):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval_s)
    return predicate()


class ControllerLinkIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.server = FakeControllerServer(
            "127.0.0.1", 0, telemetry_interval_s=0.02, health_interval_s=0.2
        )
        self.server.start()
        self.config = ControllerLinkConfig(
            host="127.0.0.1", port=self.server.port, source_id="test-host",
            connect_timeout_s=1.0, read_idle_timeout_s=0.2,
            reconnect_backoff_min_s=0.1, reconnect_backoff_max_s=0.2,
            stale_after_ms=500, default_config_request_ttl_ms=500,
        )
        self.client = ControllerLinkClient(self.config)
        self.client.start()

    def tearDown(self):
        self.client.close()
        self.server.close()

    def test_client_reaches_ready_and_receives_telemetry(self):
        self.assertTrue(wait_until(lambda: self.client.status == "ready"))
        self.assertTrue(wait_until(lambda: self.client.state.channel("front") is not None))
        reading = self.client.state.channel("front")
        self.assertEqual(reading.state.source_mode, "simulated")

    def test_left_channel_reports_unknown_never_a_fabricated_distance(self):
        self.assertTrue(wait_until(lambda: self.client.state.channel("left") is not None))
        reading = self.client.state.channel("left")
        self.assertIsNone(reading.state.distance_mm)
        self.assertEqual(reading.state.band, "unknown")

    def test_health_event_arrives(self):
        self.assertTrue(wait_until(lambda: "controller" in self.client.state.health(), timeout_s=3.0))

    def test_config_request_round_trip_and_acknowledgement(self):
        self.assertTrue(wait_until(lambda: self.client.status == "ready"))
        outcome = self.client.send_config_request("pause_feedback", base_config_version=1)
        self.assertEqual(outcome.status, "acked")
        self.assertEqual(outcome.ack.result, "accepted")
        self.assertEqual(outcome.ack.active_config_version, 2)

    def test_stale_base_version_is_rejected_not_silently_applied(self):
        self.assertTrue(wait_until(lambda: self.client.status == "ready"))
        first = self.client.send_config_request("pause_feedback", base_config_version=1)
        self.assertEqual(first.ack.result, "accepted")
        second = self.client.send_config_request("pause_feedback", base_config_version=1)
        self.assertEqual(second.ack.result, "rejected")
        self.assertEqual(second.ack.reason, "version_conflict")

    def test_outage_is_detected_and_state_does_not_linger(self):
        # A single dropped TCP connection while the server keeps listening
        # reconnects on loopback faster than any poll loop can observe the
        # transient "disconnected" state -- that's the desired behavior, not
        # something to race. An actual outage (nothing to reconnect to) is
        # the case that must be detected and held.
        self.assertTrue(wait_until(lambda: self.client.state.channel("front") is not None))
        self.server.close()
        self.assertTrue(wait_until(lambda: self.client.status == "disconnected", timeout_s=2.0))
        # Still disconnected a bit later -- not a one-tick flicker before a
        # phantom reconnect -- and not showing the last-known reading as current.
        time.sleep(0.3)
        self.assertEqual(self.client.status, "disconnected")
        self.assertIsNone(self.client.state.channel("front"))

    def test_client_reconnects_to_a_restarted_server(self):
        self.assertTrue(wait_until(lambda: self.client.status == "ready"))
        port = self.server.port
        self.server.close()
        self.assertTrue(wait_until(lambda: self.client.status == "disconnected", timeout_s=2.0))
        self.server = FakeControllerServer("127.0.0.1", port, telemetry_interval_s=0.02, health_interval_s=0.2)
        self.server.start()
        self.assertTrue(wait_until(lambda: self.client.status == "ready", timeout_s=3.0))
        self.assertTrue(wait_until(lambda: self.client.state.channel("front") is not None))

    def test_client_survives_a_single_dropped_connection(self):
        # Telemetry keeps flowing (via automatic reconnect) rather than the
        # client getting stuck after one connection reset.
        self.assertTrue(wait_until(lambda: self.client.state.channel("front") is not None))
        before = self.client.state.channel("front").state.sequence
        self.server.drop_connection()
        self.assertTrue(wait_until(
            lambda: (r := self.client.state.channel("front")) is not None and r.state.sequence > before,
            timeout_s=2.0,
        ))

    def test_send_with_no_link_is_reported_not_blocked_forever(self):
        self.client.close()
        outcome = self.client.send_config_request("pause_feedback", base_config_version=1)
        self.assertEqual(outcome.status, "link_unavailable")


if __name__ == "__main__":
    unittest.main()
