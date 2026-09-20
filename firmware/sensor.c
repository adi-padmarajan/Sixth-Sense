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

bool read_all_channel_distances_mm(channel_reading_t out_readings[CHANNEL_COUNT]) {
    bool any_valid = false;

    for (int g = 0; g < SENSOR_GROUP_COUNT; g++) {
        int echo_pins[CHANNELS_PER_GROUP];
        int indices[CHANNELS_PER_GROUP];
        int n = 0, trigger_pin = -1;

        for (int i = 0; i < CHANNEL_COUNT; i++) {
            if (CHANNELS[i].group != (sensor_group_t)g) continue;
            trigger_pin = CHANNELS[i].trigger_pin;
            echo_pins[n] = CHANNELS[i].echo_pin;
            indices[n] = i;
            n++;
        }

        double durations[CHANNELS_PER_GROUP];
        bool valid[CHANNELS_PER_GROUP];

        sensor_trigger(trigger_pin);
        sensor_wait_for_echoes(echo_pins, n, MAX_ECHO_WAIT_S, durations, valid);

        for (int k = 0; k < n; k++) {
            int ch = indices[k];
            out_readings[ch].name = CHANNELS[ch].name;
            out_readings[ch].valid = valid[k];
            out_readings[ch].distance_mm = valid[k]
                ? (int)((durations[k] * SPEED_OF_SOUND_M_S / 2) * 1000 + 0.5)
                : 0;
            any_valid = any_valid || valid[k];
        }
    }
    return any_valid;
}
