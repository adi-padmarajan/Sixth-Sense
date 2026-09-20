#include "proximity_state.h"

void proximity_state_reset(proximity_state_t *state) {
    proximity_filter_reset(&state->filter);
    state->band = BAND_UNKNOWN;
}

int proximity_state_update(proximity_state_t *state, bool valid, int raw_distance_mm) {
    if (!valid) {
        // Don't push a fabricated value into the median history -- just
        // leave it untouched and report the band as unknown.
        state->band = proximity_band_update(state->band, false, 0);
        return 0;
    }

    int filtered_mm = proximity_filter_push(&state->filter, raw_distance_mm);
    state->band = proximity_band_update(state->band, true, filtered_mm);
    return filtered_mm;
}
