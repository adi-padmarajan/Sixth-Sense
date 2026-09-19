from __future__ import annotations
import threading
import pigpio

from typing import Optional

class LinuxSensorDriver:
    def __init__(self):
        self._pi = pigpio.pi()
        if not self._pi.connected:
            raise RuntimeError(
                "Could not connect to pigpiod. Is it running?" 
            )

    def trigger(self, pin: int) -> None:
        self._pi.set_mode(pin, pigpio.OUTPUT)
        self._pi.gpio_trigger(pin, 10, 1)

    def wait_for_echo(self, pin:int, timeout_s: float) -> Optional[float]:
        self._pi.set_mode(pin,pigpio.INPUT)
        # Empty dict that will hold:
        #  {1: <timestamp when pin when high>, 0: <timestamp when pin went low>}
        ticks = {}
        done = threading.Event()

        def on_edge(gpio, level, tick):
            ticks[level] = tick
            if 1 in ticks and 0 in ticks:
                done.set()

        cb = self._pi.callback(pin, pigpio.EITHER_EDGE, on_edge)
        done.wait(timeout_s)
        cb.cancel()

        if 1 not in ticks or 0 not in ticks:
            return None
        
        # Convert to seconds
        return pigpio.tickDiff(ticks[1], ticks[0]) / 1_000_000


