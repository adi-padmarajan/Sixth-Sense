#include "sensor.h"
#include "sensor_driver.h"

#define SPEED_OF_SOUND_M_S 343.0
#define MAX_ECHO_WAIT_S 0.03

bool read_distance_mm(int trigger_pin, int echo_pin, int *out_distance_mm) {
    double duration_s;

    sensor_trigger(trigger_pin);
    if (!sensor_wait_for_echo(echo_pin, MAX_ECHO_WAIT_S, &duration_s)) {
        return false;
    }

    double distance_m = duration_s * SPEED_OF_SOUND_M_S / 2;
    *out_distance_mm = (int)(distance_m * 1000 + 0.5);
    return true;
}