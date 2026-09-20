#ifndef PROXIMITY_FILTER_H
#define PROXIMITY_FILTER_H

#include <stdbool.h>

#define MEDIAN_WINDOW 3  // TODO: tune once you can measure real noise vs. lag

typedef struct {
    int history[MEDIAN_WINDOW];
    int history_count;  // how many samples recorded so far (caps at MEDIAN_WINDOW)
    int next_index;      // where the next sample gets written
} proximity_filter_t;

// Clears a channel's history. Call this when a sensor reconnects or a
// session resets, so stale readings don't linger in the filter.
void proximity_filter_reset(proximity_filter_t *filter);

// Records one new raw reading and returns the median of the samples seen
// so far (up to MEDIAN_WINDOW of them).
int proximity_filter_push(proximity_filter_t *filter, int raw_distance_mm);

#endif
