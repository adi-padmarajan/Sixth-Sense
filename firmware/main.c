#include <stdio.h>
#include <time.h>
#include <unistd.h>
#include "sensor.h"
#include "proximity_state.h"
#include "haptic_pattern.h"
#include "motor_driver.h"

static double now_s(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec / 1e9;
}

int main(void) {
    static proximity_state_t states[CHANNEL_COUNT];
    for (int i = 0; i < CHANNEL_COUNT; i++) {
        proximity_state_reset(&states[i]);
    }

    double start_s = now_s();

    for (;;) {
        channel_reading_t readings[CHANNEL_COUNT];
        read_all_channel_distances_mm(readings);

        // TEMPORARY TEST -- force a known reading, bypassing the real sensor.
        // Remove once you've confirmed the rest of the pipeline works.
        readings[4].valid = true;
        readings[4].distance_mm = 300;  // pretend "rear" is reading 300mm

        int filtered_mm[CHANNEL_COUNT];
        bool have_reading[CHANNEL_COUNT];
        for (int i = 0; i < CHANNEL_COUNT; i++) {
            filtered_mm[i] = proximity_state_update(&states[i], readings[i].valid, readings[i].distance_mm);
            have_reading[i] = states[i].band != BAND_UNKNOWN;
            printf("%-11s %-19s %d mm\n", readings[i].name, proximity_band_name(states[i].band), filtered_mm[i]);
        }
        printf("---\n");

        // Re-apply the haptic pattern much more often than sensors get
        // re-read, so fast pulse rates (near 0mm) still render distinctly.
        for (int tick = 0; tick < 20; tick++) {
            double elapsed_s = now_s() - start_s;
            for (int i = 0; i < CHANNEL_COUNT; i++) {
                bool motor_on = true;//haptic_pattern_is_on(have_reading[i], filtered_mm[i], elapsed_s);
                motor_set(CHANNELS[i].motor_pin, motor_on);
            }
            usleep(10000);  // 10ms -- ~20 ticks covers the old 200ms window
        }
    }
    return 0;
}