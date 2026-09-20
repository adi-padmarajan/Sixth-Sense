#ifndef MOTOR_DRIVER_H
#define MOTOR_DRIVER_H

#include <stdbool.h>

// Turns the motor on the given pin on or off. The pin is expected to be
// wired through a transistor/driver (e.g. an L298N ENA line), never
// directly to the motor.
void motor_set(int pin, bool on);

#endif
