#ifndef PROXIMITY_BAND_H
#define PROXIMITY_BAND_H

#include <stdbool.h>

// Ordered from calmest to most urgent -- comparisons like `candidate >
// current_band` rely on this ordering.
typedef enum {
    BAND_UNKNOWN = 0,
    BAND_BEYOND,
    BAND_FAR,
    BAND_MID,
    BAND_NEAR,
    BAND_URGENT,
} proximity_band_t;

#define HYSTERESIS_MM 50  // TODO: tune based on comfort/flicker testing

// Determines the proximity band for a filtered reading, given the
// channel's current band. Escalating to a more urgent band happens
// immediately; de-escalating to a calmer band only takes effect once the
// distance has cleared the boundary by HYSTERESIS_MM, so a reading sitting
// right at a threshold doesn't flicker back and forth.
proximity_band_t proximity_band_update(proximity_band_t current_band, bool valid, int distance_mm);

// Human-readable name for a band, for logging/printing.
const char *proximity_band_name(proximity_band_t band);

#endif
