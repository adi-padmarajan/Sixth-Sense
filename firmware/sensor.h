#ifndef SENSOR_H
#define SENSOR_H

#include <stdbool.h>
#include "channels.h"

bool read_distance_mm(int trigger_pin, int echo_pin, int *out_distance_mm);

typedef struct {
    const char *name;
    bool valid;
    int distance_mm;
} channel_reading_t;

bool read_all_channel_distances_mm(channel_reading_t out_readings[CHANNEL_COUNT]);

#endif