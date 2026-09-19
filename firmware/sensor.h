#ifndef SENSOR_H
#define SENSOR_H

#include <stdbool.h>

bool read_distance_mm(int trigger_pin, int echo_pin, int *out_distance_mm);

#endif