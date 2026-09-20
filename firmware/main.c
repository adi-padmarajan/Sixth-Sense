#include <stdio.h>
#include <unistd.h>
#include "sensor.h"
#include "proximity_state.h"

int main(void) {
    static proximity_state_t states[CHANNEL_COUNT];
    for (int i = 0; i < CHANNEL_COUNT; i++) {
        proximity_state_reset(&states[i]);
    }

    for (;;) {
        channel_reading_t readings[CHANNEL_COUNT];
        read_all_channel_distances_mm(readings);

        for (int i = 0; i < CHANNEL_COUNT; i++) {
            int filtered_mm = proximity_state_update(&states[i], readings[i].valid, readings[i].distance_mm);
            printf("%-11s %-19s %d mm\n", readings[i].name, proximity_band_name(states[i].band), filtered_mm);
        }
        printf("---\n");

        usleep(200000);  // 200ms between full 8-channel passes
    }
    return 0;
}