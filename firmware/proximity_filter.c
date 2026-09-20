#include "proximity_filter.h"

void proximity_filter_reset(proximity_filter_t *filter) {
    filter->history_count = 0;
    filter->next_index = 0;
}

int proximity_filter_push(proximity_filter_t *filter, int raw_distance_mm) {
    // Write the new sample into the circular buffer, wrapping back to the
    // start once it's full.
    filter->history[filter->next_index] = raw_distance_mm;
    filter->next_index = (filter->next_index + 1) % MEDIAN_WINDOW;
    if (filter->history_count < MEDIAN_WINDOW) {
        filter->history_count++;
    }

    // Copy and sort the recorded samples to find the median.
    int sorted[MEDIAN_WINDOW];
    for (int i = 0; i < filter->history_count; i++) {
        sorted[i] = filter->history[i];
    }
    for (int i = 1; i < filter->history_count; i++) {
        int key = sorted[i];
        int j = i - 1;
        while (j >= 0 && sorted[j] > key) {
            sorted[j + 1] = sorted[j];
            j--;
        }
        sorted[j + 1] = key;
    }

    return sorted[filter->history_count / 2];
}
