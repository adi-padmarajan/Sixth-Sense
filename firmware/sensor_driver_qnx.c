#include "sensor_driver.h"
#include <stdint.h>
#include <stdio.h>
#include <time.h>
#include <sys/neutrino.h>
#include "rpi_gpio.h"

#include <pthread.h>
#include <sched.h>

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

// Applies the one-time setup both sensor_wait_for_echo and
// sensor_wait_for_echoes need before they can listen for edges: real-time
// priority elevation and the message-passing channel. Safe to call every
// time; each step only actually runs once. Returns false if the channel
// could not be created.
static bool ensure_ready(void) {
    if (!priority_set) {
        set_realtime_priority();
        priority_set = true;
    }
    if (!channel_ready) {
        if (!init_channel()) {
            return false;
        }
        channel_ready = true;
    }
    return true;
}

// Tracks which pins already have an active edge-detection registration.
// Confirmed by test (see test_registration.c): a single registration
// keeps delivering pulses for every future edge on that pin, so each pin
// only needs to be registered once, ever -- re-registering on every
// reading exhausts the resource manager's registration table over time.
static bool pin_event_registered[GPIO_COUNT];

// Configures a pin as an input and registers it for edge notifications,
// but only the first time it's called for a given pin. Later calls for
// the same pin are no-ops. Returns false if registration fails.
static bool ensure_pin_registered(int pin, unsigned event_id) {
    if (pin < 0 || pin >= GPIO_COUNT) {
        return false;
    }
    if (pin_event_registered[pin]) {
        return true;
    }

    rpi_gpio_setup_pull(pin, GPIO_IN, GPIO_PUD_OFF);
    if (rpi_gpio_add_event_detect(pin, coid, GPIO_RISING | GPIO_FALLING, event_id)) {
        return false;
    }

    pin_event_registered[pin] = true;
    return true;
}

// Waits for the echo pin's high pulse and returns its duration. Returns
// false if no complete pulse is observed within timeout_s.
bool sensor_wait_for_echo(int pin, double timeout_s, double *out_duration_s) {
    if (!ensure_ready()) {
        return false;
    }

    if (!ensure_pin_registered(pin, EVENT_ECHO)) {
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

// Watches multiple echo pins at once (used when several sensors share one
// trigger pin and fire together). Reports each pin's pulse duration
// independently -- out_valid[i] is false if that pin never completed a
// full pulse within timeout_s. Returns true if at least one pin succeeded;
// callers must still check out_valid[] per pin rather than trusting the
// overall return value alone.
bool sensor_wait_for_echoes(const int *pins, int count, double timeout_s, double *out_durations, bool *out_valid) {
    // Assume unknown for every pin until proven otherwise.
    for (int i = 0; i < count; i++) out_valid[i] = false;

    if (!ensure_ready()) {
        return false;
    }

    // Per-pin versions of the same tracking variables sensor_wait_for_echo
    // uses for a single pin. pending counts how many pins still need a
    // complete high-then-low pulse.
    bool have_high[count], have_low[count];
    double high_ts[count], low_ts[count];
    int pending = count;

    // Configure every pin as an input and register it for edge
    // notifications, using its array index as the event ID so we can tell
    // which pin fired when a notification arrives on the shared channel.
    for (int i = 0; i < count; i++) {
        have_high[i] = have_low[i] = false;
        high_ts[i] = low_ts[i] = 0;
        if (!ensure_pin_registered(pins[i], (unsigned)i)) {
            pending--;  // this pin can never complete; stop waiting on it
        }
    }

    // Keep receiving notifications until every pin has a complete pulse or
    // the shared deadline passes.
    double deadline = now_s() + timeout_s;
    while (pending > 0) {
        double remaining = deadline - now_s();
        if (remaining <= 0) break;  // any pins still pending stay unknown

        uint64_t ntime = (uint64_t)(remaining * 1e9);
        TimerTimeout(CLOCK_MONOTONIC, _NTO_TIMEOUT_RECEIVE, NULL, &ntime, NULL);

        struct _pulse pulse;
        if (MsgReceivePulse(chid, &pulse, sizeof(pulse), NULL) == -1) break;  // timed out

        // The event ID we registered each pin with comes back here,
        // telling us exactly which pin this notification belongs to.
        int idx = pulse.value.sival_int;
        if (idx < 0 || idx >= count) continue;  // unexpected, ignore

        // Same rising/falling detection as the single-pin version, just
        // applied to this specific pin's tracking variables.
        unsigned level;
        rpi_gpio_input(pins[idx], &level);
        double t = now_s();
        if (level == GPIO_HIGH && !have_high[idx]) {
            high_ts[idx] = t;
            have_high[idx] = true;
        } else if (have_high[idx] && !have_low[idx]) {
            low_ts[idx] = t;
            have_low[idx] = true;
            out_durations[idx] = low_ts[idx] - high_ts[idx];
            out_valid[idx] = true;
            pending--;
        }
    }

    // Report success if at least one pin got a real reading; individual
    // results are still in out_valid[], which callers must check per pin.
    bool any_valid = false;
    for (int i = 0; i < count; i++) any_valid = any_valid || out_valid[i];
    return any_valid;
}
