/*
 * Copyright (c) 2024, BlackBerry Limited. All rights reserved.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */


#ifndef RPI_GPIO_API_H
#define RPI_GPIO_API_H

/* Return codes for client API */
#define GPIO_SUCCESS 0
#define GPIO_ERROR_NOT_CONNECTED -1
#define GPIO_ERROR_MSG_NOT_SENT -2
#define GPIO_ERROR_MSG_EVENT_NOT_REGISTERED -3
#define GPIO_ERROR_INPUT_OUT_OF_RANGE -4
#define GPIO_ERROR_CLEANING_UP -5

/* GPIO PIN codes */
#define GPIO_COUNT 28

#define GPIO0 0
#define GPIO1 1
#define GPIO2 2
#define GPIO3 3
#define GPIO4 4
#define GPIO5 5
#define GPIO6 6
#define GPIO7 7
#define GPIO8 8
#define GPIO9 9
#define GPIO10 10
#define GPIO11 11
#define GPIO12 12
#define GPIO13 13
#define GPIO14 14
#define GPIO15 15
#define GPIO16 16
#define GPIO17 17
#define GPIO18 18
#define GPIO19 19
#define GPIO20 20
#define GPIO21 21
#define GPIO22 22
#define GPIO23 23
#define GPIO24 24
#define GPIO25 25
#define GPIO26 26
#define GPIO27 27

/* GPIO pin configuration*/
enum gpio_config_t
{
    GPIO_IN,
    GPIO_OUT
};

/* GPIO pin pull direction */
enum gpio_pull_t
{
    GPIO_PUD_OFF,
    GPIO_PUD_UP,
    GPIO_PUD_DOWN
};

/* GPIO pin level */
enum gpio_level_t
{
    GPIO_LOW = 4,
    GPIO_HIGH = 8
};

/* GPIO pin level */
enum gpio_level_change_t
{
    GPIO_RISING = 1,
    GPIO_FALLING = 2,
};

/* PWM channel operation mode */
enum pwm_channel_op_mode_t
{
    GPIO_PWM_MODE_PWM = 0,
    GPIO_PWM_MODE_MS = 1
};

/**
 * Select GPIO configuration (input/output)
 *
 * @param    gpio_pin       GPIO pin
 * @param    configuration  pin configuration (@ref gpio_config_t)
 *
 * @returns  GPIO_SUCCESS                  on success
 *           GPIO_ERROR_NOT_CONNECTED      if the GPIO resource manager not available to connect to
 *           GPIO_ERROR_MSG_NOT_SENT       if command message is not sent to the GPIO resource manager
 *           GPIO_ERROR_INPUT_OUT_OF_RANGE invalid pin number or pin configuration provided
 */
int rpi_gpio_setup(int gpio_pin, unsigned configuration);

/**
 * Set pull-up/pull-down
 *
 * @param    gpio_pin       GPIO pin
 * @param    configuration  pin configuration (@ref gpio_config_t)
 * @param    direction      direction (@ref gpio_pull_t)
 *
 * @returns  GPIO_SUCCESS                  on success
 *           GPIO_ERROR_NOT_CONNECTED      if the GPIO resource manager not available to connect to
 *           GPIO_ERROR_MSG_NOT_SENT       if command message is not sent to the GPIO resource manager
 *           GPIO_ERROR_INPUT_OUT_OF_RANGE invalid pin number or pin configuration or direction provided
 */
int rpi_gpio_setup_pull(int gpio_pin, unsigned configuration, unsigned direction);

/**
 * Set up PWM with frequency and range
 *
 * @param    gpio_pin   GPIO pin
 * @param    frequency  PWM pulse frequency
 * @param    mode       hardware PWM mode (@ref pwm_channel_op_mode_t)
 *
 * @returns  GPIO_SUCCESS                  on success
 *           GPIO_ERROR_NOT_CONNECTED      if the GPIO resource manager not available to connect to
 *           GPIO_ERROR_MSG_NOT_SENT       if command message is not sent to the GPIO resource manager
 *           GPIO_ERROR_INPUT_OUT_OF_RANGE invalid pin number or pulse frequency or mode provided
 */
int rpi_gpio_setup_pwm(int gpio_pin, unsigned frequency, unsigned mode);

/**
 * Set PWM duty cycle
 *
 * @param    gpio_pin    GPIO pin
 * @param    percentage  percentage of the pulse width when the voltage is high
 *
 * @returns  GPIO_SUCCESS                  on success
 *           GPIO_ERROR_NOT_CONNECTED      if the GPIO resource manager not available to connect to
 *           GPIO_ERROR_MSG_NOT_SENT       if command message is not sent to the GPIO resource manager
 *           GPIO_ERROR_INPUT_OUT_OF_RANGE invalid pin number or percentage provided
 */
int rpi_gpio_set_pwm_duty_cycle(int gpio_pin, float percentage);

/**
 * Read GPIO configuration (input/output)
 *
 * @param    gpio_pin       GPIO pin
 * @param    configuration  pin configuration (output) (@ref gpio_config_t)
 *
 * @returns  GPIO_SUCCESS                  on success
 *           GPIO_ERROR_NOT_CONNECTED      if the GPIO resource manager not available to connect to
 *           GPIO_ERROR_MSG_NOT_SENT       if command message is not sent to the GPIO resource manager
 *           GPIO_ERROR_INPUT_OUT_OF_RANGE invalid pin number provided
 */
int rpi_gpio_get_setup(int gpio_pin, unsigned *configuration);

/**
 * Turn GPIO PIN on/off
 *
 * @param    gpio_pin  GPIO pin
 * @param    level     voltage level (@ref gpio_level_t)
 *
 * @returns  GPIO_SUCCESS                  on success
 *           GPIO_ERROR_NOT_CONNECTED      if the GPIO resource manager not available to connect to
 *           GPIO_ERROR_MSG_NOT_SENT       if command message is not sent to the GPIO resource manager
 *           GPIO_ERROR_INPUT_OUT_OF_RANGE invalid pin number or voltage level provided
 */
int rpi_gpio_output(int gpio_pin, unsigned level);

/**
 * Read GPIO PIN level
 *
 * @param    gpio_pin  GPIO pin
 * @param    level     voltage level (output)
 *
 * @returns  GPIO_SUCCESS                  on success
 *           GPIO_ERROR_NOT_CONNECTED      if the GPIO resource manager not available to connect to
 *           GPIO_ERROR_MSG_NOT_SENT       if command message is not sent to the GPIO resource manager
 *           GPIO_ERROR_INPUT_OUT_OF_RANGE invalid pin number provided
 */
int rpi_gpio_input(int gpio_pin, unsigned *level);

/**
 * Report on a GPIO event asynchronously
 *
 * @param    gpio_pin  GPIO pin
 * @param    coid      communication ID
 * @param    event     GPIO event of interest
 *                     (combination of flags from @ref gpio_level_change_t and  @ref gpio_level_t) 
 * @param    event_id  event ID for notification
 *
 * @returns  GPIO_SUCCESS                  on success
 *           GPIO_ERROR_NOT_CONNECTED      if the GPIO resource manager not available to connect to
 *           GPIO_ERROR_MSG_NOT_SENT       if command message is not sent to the GPIO resource manager
 *           GPIO_ERROR_INPUT_OUT_OF_RANGE invalid pin number or voltage level provided
 */
int rpi_gpio_add_event_detect(int gpio_pin, int coid, unsigned event, unsigned event_id);

/**
 * Cleanup GPIO API resources
 *
 * @returns  GPIO_SUCCESS                  on success
 *           GPIO_ERROR_NOT_CONNECTED      if resource manager not available to connect to
 *           GPIO_ERROR_CLEANING_UP        if there is a failure disconnecting from the resource manager
 */
int rpi_gpio_cleanup();

#endif
