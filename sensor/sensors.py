sensors.py
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


"""
Get data from HC-SR04 sensors and the front facing AJ-SR04M sensor 
"""

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





