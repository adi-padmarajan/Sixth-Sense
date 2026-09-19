from __future__ import annotations
from typing import Dict, Optional

SPEED_OF_SOUND_M_S = 343.0

class FakeSensorDriver:
    """Deterministic stand-in for SensorDriver, for development and tests
    without hardware. Implements the same interface as SensorDriver by
    structural typing (Protocol) -- no inheritance needed.
    """

    def __init__(self):
        self._distance_m: Dict[int, Optional[float]] = {}

    def trigger(self, pin: int) -> None:
        pass

    def wait_for_echo(self, pin: int, timeout_s: float) -> Optional[float]:
        meters = self._distance_m.get(pin)

        if meters is None:
            return None

        return 2 * meters / SPEED_OF_SOUND_M_S 
    def set_distance(self, pin: int, meters: Optional[float]) -> None:
        """
        Configure what 'pin' reports on it's next echo read
        Pass None to simulate no echo returning (out of range/ disconnected)
        """
        self._distance_m[pin] = meters