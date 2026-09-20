#include "motor_driver.h"
#include "rpi_gpio.h"

// Tracks which motor pins have already been configured as outputs, so
// rpi_gpio_setup only runs once per pin instead of on every call.
static bool motor_pin_configured[GPIO_COUNT];

void motor_set(int pin, bool on) {
    if (pin >= 0 && pin < GPIO_COUNT && !motor_pin_configured[pin]) {
        rpi_gpio_setup(pin, GPIO_OUT);
        motor_pin_configured[pin] = true;
    }
    rpi_gpio_output(pin, on ? GPIO_HIGH : GPIO_LOW);
}
