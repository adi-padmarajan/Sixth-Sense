#include <stdio.h>
#include "sensor.h"

int main(void) {
    channel_reading_t readings[CHANNEL_COUNT];
    read_all_channel_distances_mm(readings);

    for (int i = 0; i < CHANNEL_COUNT; i++) {
        if (readings[i].valid) {
            printf("%-11s %d mm\n", readings[i].name, readings[i].distance_mm);
        } else {
            printf("%-11s unknown\n", readings[i].name);
        }
    }
    return 0;
}