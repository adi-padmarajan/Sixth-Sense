#ifndef SENSOR_DRIVER_H
#define SENSOR_DRIVER_H

#include <stdbool.h>

void sensor_trigger(int pin);
bool sensor_wait_for_echo(int pin, double timeout_s, double *out_duration_s);
bool sensor_wait_for_echoes(const int *pins, int count, double timeout_s, double *out_durations, bool *out_valid);
#endif