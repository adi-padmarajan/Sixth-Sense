#include "haptic_pattern.h"
#include <math.h>

// Pulse rate ranges continuously with distance: fastest right at 0mm,
// dropping to MIN_HZ as an object first enters range, silent at
// MAX_RANGE_MM and beyond. TODO: tune once tested on skin -- these are
// first-guess values, not measured for comfort.
#define MAX_RANGE_MM 3500.0
#define MAX_HZ       10.0
#define MIN_HZ       1.0

// Fraction of each pulse period the motor is actually on, keeping pulses
// short and distinct rather than a 50/50 on/off square wave.
#define ON_FRACTION 0.3

static double hz_for_distance(int distance_mm) {
    if (distance_mm <= 0) {
        return MAX_HZ;
    }
    if (distance_mm >= MAX_RANGE_MM) {
        return 0.0;
    }
    double frac = 1.0 - distance_mm / MAX_RANGE_MM;
    return MIN_HZ + (MAX_HZ - MIN_HZ) * frac;
}

bool haptic_pattern_is_on(bool valid, int distance_mm, double elapsed_s) {
    if (!valid) {
        return false;
    }

    double hz = hz_for_distance(distance_mm);
    if (hz <= 0.0) {
        return false;
    }

    double period_s = 1.0 / hz;
    double phase = fmod(elapsed_s, period_s) / period_s;
    return phase < ON_FRACTION;
}
