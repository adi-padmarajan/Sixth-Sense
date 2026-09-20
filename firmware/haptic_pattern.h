#ifndef HAPTIC_PATTERN_H
#define HAPTIC_PATTERN_H

#include <stdbool.h>

// Returns whether a channel's motor should be on right now, given the
// channel's current filtered distance (mm) and how many seconds have
// elapsed since some fixed reference point (e.g. program start). Encodes
// distance as pulse rate, continuously: faster as distance approaches
// 0mm, silent at/beyond the sensor's max range. valid=false (unknown
// reading) always means silence. Pure function -- holds no state of its
// own, safe to call as often as needed.
bool haptic_pattern_is_on(bool valid, int distance_mm, double elapsed_s);

#endif
