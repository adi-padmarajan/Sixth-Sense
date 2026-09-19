from __future__ import annotations 
from typing import Optional 
from .driver import SensorDriver
from .fakes import FakeSensorDriver

"""
https://www.qnx.com/developers/docs/qnxeverywhere/com.qnx.doc.interfacing/topic/rpi/rpi_GPIO_python_qnx.html
https://www.qnx.com/developers/docs/qnxeverywhere/com.qnx.doc.interfacing/topic/rpi/rpi_GPIO-apis.html

"""

""" 
Set off sensors
  Individual receiver and trigger for each sensor
  2 Group trigger GPIO pins that align the sensors at 90 degree angles
  Process should take less than 1/10 seconds to prevent lag
  Important Note: test sensors are not interfering with one another and implement sequential firing
  Time-division multiplexing
  Set them up to run on 90 degree angles
  Add timeout handling if a reading is missed
"""
SPEED_OF_SOUND_M_S = 343.0
MAX_ECHO_WAIT_S = 0.03


"""
Get data from HC-SR04 sensors and the front facing AJ-SR04M sensor 
"""
def read_distance_mm(driver:SensorDriver, trigger_pin: int, echo_pin: int) -> Optional[int]:
    driver.trigger(trigger_pin)
    duration_s = driver.wait_for_echo(echo_pin, MAX_ECHO_WAIT_S)
    if duration_s is None:
        return None
    distance_m = duration_s * SPEED_OF_SOUND_M_S / 2
    return round(distance_m * 1000)

"""
Method for using data
  Clean up data/ noise
    Apply a median filter

      Per sensor, over time (temporal median filter)
      Sensor keeps rolling buffer of last N readings (test to determine latency cost vs benefit) 
      and before reading takes the median of the sensors recent history
  Smooth over time
  Add a small buffer to on/off thresholds (hysteresis) to prevent flickering

  Important note: prioritize front facing sensor/ actuator
"""

"""
Test
"""
if __name__ == "__main__":
    driver = FakeSensorDriver()
    driver.set_distance(pin=17, meters=0.3)
    distance = read_distance_mm(driver, trigger_pin=27, echo_pin=99)
    print(distance)




