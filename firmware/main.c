#include <stdio.h>
#include "sensor.h"

int main(void) {
    int distance_mm;
    if (read_distance_mm(2, 3, &distance_mm)) {
        printf("%d\n", distance_mm);
    } else {
        printf("unknown\n");
    }
    return 0;
}