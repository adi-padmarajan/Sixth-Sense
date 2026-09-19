#include "sensor_driver.h"

#include <hw/gpio_api.h>
#include <time.h>

// "/dev/gpio" is the single shared GPIO device on this board (confirmed via
// `find /dev -iname "*gpio*"`) -- gpio_fd identifies the device, not a pin.
static int32_t gpio_fd = -1;

static void ensure_open(void) {
    if (gpio_fd == -1) {
        gpio_fd = gpio_open("/dev/gpio");
    }
}

// TODO: unconfirmed -- how a gpio_header_t is actually obtained for a given
// pin number. Guessing it's just the pin number itself until we can check
// the real header/ask the mentor.
static gpio_header_t header_for_pin(int pin) {
    return (gpio_header_t)pin;
}

static double now_s(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec / 1e9;
}

void sensor_trigger(int pin) {
    ensure_open();
    gpio_header_t hdr = header_for_pin(pin);

    gpio_set_dir(gpio_fd, hdr, GPIO_DIR_OUT);
    gpio_set_level(gpio_fd, hdr, GPIO_LEVEL_HIGH);
    struct timespec pulse = { .tv_sec = 0, .tv_nsec = 10000 };
    nanosleep(&pulse, NULL);
    gpio_set_level(gpio_fd, hdr, GPIO_LEVEL_LOW);
}

bool sensor_wait_for_echo(int pin, double timeout_s, double *out_duration_s) {
    ensure_open();
    gpio_header_t hdr = header_for_pin(pin);
    gpio_set_dir(gpio_fd, hdr, GPIO_DIR_IN);

    double deadline = now_s() + timeout_s;

    while (gpio_get_level(gpio_fd, hdr) != GPIO_LEVEL_HIGH) {
        if (now_s() > deadline) return false;
    }
    double high_ts = now_s();

    while (gpio_get_level(gpio_fd, hdr) == GPIO_LEVEL_HIGH) {
        if (now_s() > deadline) return false;
    }
    double low_ts = now_s();

    *out_duration_s = low_ts - high_ts;
    return true;
}
