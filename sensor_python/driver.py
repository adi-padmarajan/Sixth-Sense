from __future__ import annotations
from typing import Optional, Protocol

class SensorDriver(Protocol):
    def trigger(self, pin: int) -> None:
        """
        Pulse 'pin' high for the sensor's documented trigger duration,
        then return it low. Starts one measurement; does not block for a result.
        """
        ...

    def wait_for_echo(self, pin: int, timeout_s: float) -> Optional[float]:
        """
        Block until 'pin' transitions high then low, and return the
        elapsed high duration in seconds.

        Returns None if no echo is observed within 'timeout_s'. A None
        result indicates an unknown reading, not the absence of an
        obstacle, and must be propagated as such by callers
        """
        ...
    