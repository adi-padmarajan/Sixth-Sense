#include "proximity_band.h"

// Bench thresholds -- provisional, from the project's documented bands.
#define URGENT_MAX_MM 400
#define NEAR_MAX_MM   800
#define MID_MAX_MM    1500
#define FAR_MAX_MM    3000

static proximity_band_t band_for_distance(int distance_mm) {
    if (distance_mm <= URGENT_MAX_MM) return BAND_URGENT;
    if (distance_mm <= NEAR_MAX_MM) return BAND_NEAR;
    if (distance_mm <= MID_MAX_MM) return BAND_MID;
    if (distance_mm <= FAR_MAX_MM) return BAND_FAR;
    return BAND_BEYOND;
}

proximity_band_t proximity_band_update(proximity_band_t current_band, bool valid, int distance_mm) {
    if (!valid) {
        return BAND_UNKNOWN;
    }

    proximity_band_t candidate = band_for_distance(distance_mm);

    // Escalating to a more urgent band: apply immediately, no delay.
    if (candidate > current_band) {
        return candidate;
    }

    // De-escalating to a calmer band: only accept it once the distance
    // would still classify as calmer even after backing off by the
    // hysteresis margin -- i.e. it has genuinely cleared the boundary,
    // not just brushed past it.
    if (candidate < current_band) {
        if (band_for_distance(distance_mm - HYSTERESIS_MM) < current_band) {
            return candidate;
        }
        return current_band;
    }

    return current_band;
}

const char *proximity_band_name(proximity_band_t band) {
    switch (band) {
        case BAND_UNKNOWN: return "unknown";
        case BAND_BEYOND:  return "beyond_alert_range";
        case BAND_FAR:     return "far";
        case BAND_MID:     return "mid";
        case BAND_NEAR:    return "near";
        case BAND_URGENT:  return "urgent";
    }
    return "unknown";
}
