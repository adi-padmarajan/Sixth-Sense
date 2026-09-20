// Bring-up tool: hold one or more GPIO pins HIGH at the same time for a
// fixed duration, bypassing sensors, the haptic pattern, and everything
// else in main.c. Not part of the real program or the Makefile build --
// compile and run manually (see firmware/README.md "Motor GPIO bring-up
// test").
//
// Purpose: isolate whether a non-firing motor is a software problem
// (main.c's logic never calling motor_set with the values you expect) or
// a hardware problem (the GPIO toggles correctly but nothing downstream
// of the pin moves). If this test makes the motor(s) buzz, the firmware
// logic upstream (pin assignment, valid-reading gating, pulse pattern) is
// the next place to look. If it does NOT, the fault is between the pin(s)
// and the motor(s) -- most likely a missing/failed driver transistor
// stage, since a bare GPIO pin can only source a few mA and most
// vibration motors need far more current than that to spin.
//
// Pass multiple pins to test them simultaneously -- e.g. to check
// several motors wired to a shared ground at once, rather than one at a
// time. This only proves each GPIO pin's logic level changes (or that
// the driver call succeeded) -- it does not by itself prove
// voltage/current actually reached any given motor. Check with a
// multimeter across each motor's leads if it stays silent, not just by
// touch.

#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include "rpi_gpio.h"

#define MAX_PINS 32

int main(int argc, char **argv) {
    if (argc < 3) {
        fprintf(stderr, "usage: %s <hold_seconds> <bcm_pin> [bcm_pin ...]\n", argv[0]);
        fprintf(stderr, "example: %s 5 14              # rear only, hold 5s\n", argv[0]);
        fprintf(stderr, "example: %s 5 14 4 17 27       # four pins at once, hold 5s\n", argv[0]);
        return 1;
    }

    int hold_seconds = atoi(argv[1]);
    int pin_count = argc - 2;
    if (pin_count > MAX_PINS) {
        fprintf(stderr, "too many pins (max %d)\n", MAX_PINS);
        return 1;
    }

    int pins[MAX_PINS];
    bool ready[MAX_PINS] = {0};
    int ready_count = 0;

    for (int i = 0; i < pin_count; i++) {
        pins[i] = atoi(argv[i + 2]);
        int rc = rpi_gpio_setup(pins[i], GPIO_OUT);
        printf("rpi_gpio_setup(pin=%d, GPIO_OUT)   -> %d %s\n",
               pins[i], rc, (rc == GPIO_SUCCESS) ? "(ok)" : "(FAILED -- skipping this pin)");
        ready[i] = (rc == GPIO_SUCCESS);
        if (ready[i]) ready_count++;
    }

    if (ready_count == 0) {
        fprintf(stderr, "no pins set up successfully -- stopping\n");
        return 1;
    }

    // Set every ready pin HIGH back-to-back (not simultaneous at the
    // electrical level -- each is a separate resource-manager message --
    // but close enough in wall-clock time for a by-touch/multimeter check).
    for (int i = 0; i < pin_count; i++) {
        if (!ready[i]) continue;
        int rc = rpi_gpio_output(pins[i], GPIO_HIGH);
        printf("rpi_gpio_output(pin=%d, GPIO_HIGH) -> %d %s\n",
               pins[i], rc, (rc == GPIO_SUCCESS) ? "(ok)" : "(FAILED)");
        if (rc != GPIO_SUCCESS) ready[i] = false;
    }

    printf("%d pin(s) held HIGH for %d s -- check the motor(s) now "
           "(touch and multimeter across each motor's leads).\n", ready_count, hold_seconds);
    sleep(hold_seconds);

    for (int i = 0; i < pin_count; i++) {
        if (!ready[i]) continue;
        int rc = rpi_gpio_output(pins[i], GPIO_LOW);
        printf("rpi_gpio_output(pin=%d, GPIO_LOW)  -> %d\n", pins[i], rc);
    }

    return 0;
}
