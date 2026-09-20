#ifndef PROXIMITY_STATE_H
#define PROXIMITY_STATE_H

#include <stdbool.h>
#include "proximity_filter.h"
#include "proximity_band.h"

// Everything one channel needs to remember between readings: its rolling
// history for the median filter, and its current proximity band.
typedef struct {
    proximity_filter_t filter;
    proximity_band_t band;
} proximity_state_t;

// Resets a channel's state, e.g. when its sensor reconnects.
void proximity_state_reset(proximity_state_t *state);

// Runs one raw reading through the median filter and band classification.
// Returns the filtered distance in mm (meaningless if the reading was
// invalid) and updates state->band in place.
int proximity_state_update(proximity_state_t *state, bool valid, int raw_distance_mm);

#endif
