// Experiment: does one rpi_gpio_add_event_detect() registration keep
// delivering pulses across multiple trigger cycles, or does it go stale
// after firing once? Not part of the real program -- delete once answered.

#include <stdio.h>
#include <stdint.h>
#include <time.h>
#include <unistd.h>
#include <sys/neutrino.h>
#include "rpi_gpio.h"

#define TRIGGER_PIN 11  // BCM 11 -- front/right/rear/left group trigger
#define ECHO_PIN    3   // BCM 3 -- right's echo pin (confirmed working earlier)

int main(void) {
    int chid = ChannelCreate(_NTO_CHF_PRIVATE);
    int coid = ConnectAttach(0, 0, chid, _NTO_SIDE_CHANNEL, 0);

    rpi_gpio_setup_pull(ECHO_PIN, GPIO_IN, GPIO_PUD_OFF);

    // Register ONCE, before the loop -- this is the thing we're testing.
    if (rpi_gpio_add_event_detect(ECHO_PIN, coid, GPIO_RISING | GPIO_FALLING, 0)) {
        printf("add_event_detect failed\n");
        return 1;
    }
    printf("Registered once. Triggering 5 times without re-registering...\n");

    for (int trial = 1; trial <= 5; trial++) {
        rpi_gpio_setup(TRIGGER_PIN, GPIO_OUT);
        rpi_gpio_output(TRIGGER_PIN, GPIO_HIGH);
        struct timespec pulse = { .tv_sec = 0, .tv_nsec = 10000 };
        nanosleep(&pulse, NULL);
        rpi_gpio_output(TRIGGER_PIN, GPIO_LOW);

        int edges_seen = 0;
        for (int i = 0; i < 2; i++) {  // expect one rising + one falling edge
            uint64_t ntime = 100000000ULL;  // 100ms timeout
            TimerTimeout(CLOCK_MONOTONIC, _NTO_TIMEOUT_RECEIVE, NULL, &ntime, NULL);

            struct _pulse p;
            if (MsgReceivePulse(chid, &p, sizeof(p), NULL) == -1) {
                printf("Trial %d: timed out waiting for edge %d\n", trial, i + 1);
                break;
            }
            edges_seen++;
        }
        printf("Trial %d: saw %d edge(s)\n", trial, edges_seen);

        usleep(300000);
    }

    return 0;
}
