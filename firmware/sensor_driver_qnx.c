#include "sensor_driver.h"
#include <stdint.h>
#include <stdio.h>
#include <time.h>
#include <sys/neutrino.h>
#include "rpi_gpio.h"

#include <pthread.h>
#include <sched.h>

/*
* Send the ping
* Turn on the pin for a momment, then turn it off
*/

// Define possible event type as an echo.
enum sample_event_t {
    EVENT_ECHO,
};

// QNX channel/connection used to receive GPIO edge notifications.
// Created once on first use and reused for all subsequent calls.
static int chid = -1;
static int coid = -1;
static bool channel_ready = false;

// Initializes the communication channel for event handling. Creates a
// private message-passing channel (chid) and attaches a connection (coid)
// to it, used to receive GPIO edge notifications.
static bool init_channel(void) {
    chid = ChannelCreate(_NTO_CHF_PRIVATE);
    if (chid == -1) {
        return false;
    }

    coid = ConnectAttach(0, 0, chid, _NTO_SIDE_CHANNEL, 0);
    if (coid == -1) {
        return false;
    }

    return true;
}

// Current monotonic time in seconds, as a float.
static double now_s(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec / 1e9;
}

// Pulses the trigger pin high for 10us, then low, per the sensor's
// documented trigger duration.
void sensor_trigger(int pin) {
    rpi_gpio_setup(pin, GPIO_OUT);
    rpi_gpio_output(pin, GPIO_HIGH);
    struct timespec pulse = { .tv_sec = 0, .tv_nsec = 10000 };
    nanosleep(&pulse, NULL);
    rpi_gpio_output(pin, GPIO_LOW);
}

// Tracks whether the real-time priority has already been applied, so it's
// only set once rather than on every call.
static bool priority_set = false;

// Elevates this thread to the highest available SCHED_FIFO priority so the
// echo timing loop gets guaranteed CPU time even under competing load.
static void set_realtime_priority(void) {
    struct sched_param param;
    param.sched_priority = sched_get_priority_max(SCHED_FIFO);
    if (pthread_setschedparam(pthread_self(), SCHED_FIFO, &param) != 0) {
        // Elevation failed -- likely missing PROCMGR_AID_PRIORITY.
        // Falls back to whatever priority the process already had.
        fprintf(stderr, "sensor_driver_qnx: failed to set SCHED_FIFO priority\n");
    }
}

// Waits for the echo pin's high pulse and returns its duration. Returns
// false if no complete pulse is observed within timeout_s.
bool sensor_wait_for_echo(int pin, double timeout_s, double *out_duration_s) {
    if (!priority_set) {
        set_realtime_priority();
        priority_set = true;
    }

    if (!channel_ready) {
        if (!init_channel()) {
            return false;
        }
        channel_ready = true; // Prepare to listen
    }

    // Pull-down disabled so the sensor's own drive determines the level.
    rpi_gpio_setup_pull(pin, GPIO_IN, GPIO_PUD_OFF);

    // Register for both rising and falling edge notifications on this pin.
    if (rpi_gpio_add_event_detect(pin, coid, GPIO_RISING | GPIO_FALLING, EVENT_ECHO)) {
        return false;
    }

    double deadline = now_s() + timeout_s;
    bool have_high = false, have_low = false;
    double high_ts = 0, low_ts = 0;

    // Block until both edges have been observed or the deadline passes.
    while (!(have_high && have_low)) {
        double remaining = deadline - now_s();
        if (remaining <= 0) return false;

        // Bound the next receive call to the remaining timeout.
        uint64_t ntime = (uint64_t)(remaining * 1e9);
        TimerTimeout(CLOCK_MONOTONIC, _NTO_TIMEOUT_RECEIVE, NULL, &ntime, NULL);

        struct _pulse pulse;
        if (MsgReceivePulse(chid, &pulse, sizeof(pulse), NULL) == -1) {
            return false;  // timed out
        }

        // An edge fired; read the current level to determine which edge
        // this was and record its timestamp if not already captured.
        unsigned level;
        rpi_gpio_input(pin, &level);
        double t = now_s();
        if (level == GPIO_HIGH && !have_high) {
            high_ts = t;
            have_high = true;
        } else if (have_high && !have_low) {
            low_ts = t;
            have_low = true;
        }
    }

    *out_duration_s = low_ts - high_ts;
    return true;
}
