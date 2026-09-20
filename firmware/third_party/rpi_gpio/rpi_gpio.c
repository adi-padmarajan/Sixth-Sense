/*
 * Copyright (c) 2024-2026, BlackBerry Limited. All rights reserved.
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

#include <fcntl.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/neutrino.h>
#include <sys/rpi_gpio.h>
#include "public/rpi_gpio.h"

// File descriptor to communicate with resource manager
static int gpio_fd = -1;

// Mutex protecting the GPIO message file descriptor
static pthread_mutex_t gpio_fd_mutex;

// Connect to the GPIO resource manager
static int gpio_msg_connect()
{
    int status = GPIO_SUCCESS;

    pthread_mutex_lock(&gpio_fd_mutex);

    if (gpio_fd == -1)
    {
        gpio_fd = open("/dev/gpio/msg", O_RDWR);
        if (gpio_fd == -1)
        {
            perror("open");
            status = GPIO_ERROR_NOT_CONNECTED;
        }
    }

    pthread_mutex_unlock(&gpio_fd_mutex);

    return status;
}

// Send a message to the GPIO resource manager
static int gpio_send_msg(void *buffer, size_t buffer_size)
{
    pthread_mutex_lock(&gpio_fd_mutex);

    int status = MsgSend(gpio_fd, buffer, buffer_size, NULL, 0);

    pthread_mutex_unlock(&gpio_fd_mutex);

    if (status != GPIO_SUCCESS)
    {
        perror("MsgSend");
        return GPIO_ERROR_MSG_NOT_SENT;
    }

    return GPIO_SUCCESS;
}

// Send a message to the GPIO resource manager and receive a reply in the same buffer
static int gpio_send_receive_msg(void *buffer, size_t buffer_size)
{
    pthread_mutex_lock(&gpio_fd_mutex);

    int status = MsgSend(gpio_fd, buffer, buffer_size, buffer, buffer_size);

    pthread_mutex_unlock(&gpio_fd_mutex);

    if (status != GPIO_SUCCESS)
    {
        perror("MsgSendReceive");
        return GPIO_ERROR_MSG_NOT_SENT;
    }

    return GPIO_SUCCESS;
}

// Register an event with the GPIO resource manager
static int gpio_msg_register_event(struct sigevent *event)
{
    pthread_mutex_lock(&gpio_fd_mutex);

    int status = MsgRegisterEvent(event, gpio_fd);

    pthread_mutex_unlock(&gpio_fd_mutex);

    if (status != GPIO_SUCCESS)
    {
        perror("MsgRegisterEvent");
        return GPIO_ERROR_MSG_EVENT_NOT_REGISTERED;
    }

    return GPIO_SUCCESS;
}

int rpi_gpio_cleanup()
{
    int status = GPIO_SUCCESS;

    pthread_mutex_lock(&gpio_fd_mutex);

    if (gpio_fd != -1)
    {
        status = close(gpio_fd);
        if (status)
        {
            perror("close");
            status = GPIO_ERROR_CLEANING_UP;
        }
    }

    pthread_mutex_unlock(&gpio_fd_mutex);

    return status;
}

int rpi_gpio_setup(int gpio_pin, unsigned configuration)
{
    // Connect to the GPIO resource manager, if not connected already
    if (gpio_msg_connect())
    {
        perror("gpio_msg_connect");
        return GPIO_ERROR_NOT_CONNECTED;
    }

    if (gpio_pin < 0 || gpio_pin >= GPIO_COUNT)
    {
        return GPIO_ERROR_INPUT_OUT_OF_RANGE;
    }

    // Configure as an input or output.
    rpi_gpio_msg_t msg = {
        .hdr.type = _IO_MSG,
        .hdr.subtype = RPI_GPIO_SET_SELECT,
        .hdr.mgrid = RPI_GPIO_IOMGR,
        .gpio = gpio_pin};

    switch (configuration)
    {
    case GPIO_IN:
        msg.value = RPI_GPIO_FUNC_IN;
        break;

    case GPIO_OUT:
        msg.value = RPI_GPIO_FUNC_OUT;
        break;

    default:
        return GPIO_ERROR_INPUT_OUT_OF_RANGE;
        break;
    };

    if (gpio_send_msg(&msg, sizeof(msg)))
    {
        perror("gpio_send_msg(inout)");
        return GPIO_ERROR_MSG_NOT_SENT;
    }

    return GPIO_SUCCESS;
}

int rpi_gpio_setup_pull(int gpio_pin, unsigned configuration, unsigned direction)
{
    // Configure as an input or output.
    if (rpi_gpio_setup(gpio_pin, configuration))
    {
        perror("rpi_gpio_setup");
        return GPIO_ERROR_NOT_CONNECTED;
    }

    if (gpio_pin < 0 || gpio_pin >= GPIO_COUNT)
    {
        return GPIO_ERROR_INPUT_OUT_OF_RANGE;
    }

    // Configure as pull up or down
    rpi_gpio_msg_t msg = {
        .hdr.type = _IO_MSG,
        .hdr.subtype = RPI_GPIO_PUD,
        .hdr.mgrid = RPI_GPIO_IOMGR,
        .gpio = gpio_pin};

    switch (direction)
    {
    case GPIO_PUD_OFF:
        msg.value = RPI_GPIO_PUD_OFF;
        break;

    case GPIO_PUD_UP:
        msg.value = RPI_GPIO_PUD_UP;
        break;

    case GPIO_PUD_DOWN:
        msg.value = RPI_GPIO_PUD_DOWN;
        break;

    default:
        return GPIO_ERROR_INPUT_OUT_OF_RANGE;
        break;
    };

    if (gpio_send_msg(&msg, sizeof(msg)))
    {
        perror("gpio_send_msg(pud)");
        return GPIO_ERROR_MSG_NOT_SENT;
    }

    return GPIO_SUCCESS;
}

int rpi_gpio_get_setup(int gpio_pin, unsigned *configuration)
{
    // Connect to the GPIO resource manager, if not connected already
    if (gpio_msg_connect())
    {
        perror("gpio_msg_connect");
        return GPIO_ERROR_NOT_CONNECTED;
    }

    if (gpio_pin < 0 || gpio_pin >= GPIO_COUNT)
    {
        return GPIO_ERROR_INPUT_OUT_OF_RANGE;
    }

    // Query whether pin is an input or output.
    rpi_gpio_msg_t msg = {
        .hdr.type = _IO_MSG,
        .hdr.subtype = RPI_GPIO_GET_SELECT,
        .hdr.mgrid = RPI_GPIO_IOMGR,
        .gpio = gpio_pin};

    if (gpio_send_receive_msg(&msg, sizeof(msg)))
    {
        perror("gpio_send_receive_msg(get_inout)");
        return GPIO_ERROR_MSG_NOT_SENT;
    }

    switch (msg.value)
    {
    case RPI_GPIO_FUNC_IN:
        *configuration = GPIO_IN;
        break;

    case RPI_GPIO_FUNC_OUT:
        *configuration = GPIO_OUT;
        break;

    default:
        return GPIO_ERROR_INPUT_OUT_OF_RANGE;
        break;
    };

    return GPIO_SUCCESS;
}

int rpi_gpio_output(int gpio_pin, unsigned level)
{
    // Connect to the GPIO resource manager, if not connected already
    if (gpio_msg_connect())
    {
        perror("gpio_msg_connect");
        return GPIO_ERROR_NOT_CONNECTED;
    }

    if (gpio_pin < 0 || gpio_pin >= GPIO_COUNT)
    {
        return GPIO_ERROR_INPUT_OUT_OF_RANGE;
    }

    // Set the pin high or low
    rpi_gpio_msg_t msg = {
        .hdr.type = _IO_MSG,
        .hdr.subtype = RPI_GPIO_WRITE,
        .hdr.mgrid = RPI_GPIO_IOMGR,
        .gpio = gpio_pin};

    switch (level)
    {
    case GPIO_LOW:
        msg.value = 0;
        break;

    case GPIO_HIGH:
        msg.value = 1;
        break;

    default:
        return GPIO_ERROR_INPUT_OUT_OF_RANGE;
        break;
    };

    if (gpio_send_msg(&msg, sizeof(msg)))
    {
        perror("gpio_send_msg(level)");
        return GPIO_ERROR_MSG_NOT_SENT;
    }

    return GPIO_SUCCESS;
}

int rpi_gpio_input(int gpio_pin, unsigned *level)
{
    // Connect to the GPIO resource manager, if not connected already
    if (gpio_msg_connect())
    {
        perror("gpio_msg_connect");
        return GPIO_ERROR_NOT_CONNECTED;
    }

    if (gpio_pin < 0 || gpio_pin >= GPIO_COUNT)
    {
        return GPIO_ERROR_INPUT_OUT_OF_RANGE;
    }

    // Query whether pin is high or low
    rpi_gpio_msg_t msg = {
        .hdr.type = _IO_MSG,
        .hdr.subtype = RPI_GPIO_READ,
        .hdr.mgrid = RPI_GPIO_IOMGR,
        .gpio = gpio_pin,
        .value = 1};

    if (gpio_send_receive_msg(&msg, sizeof(msg)))
    {
        perror("gpio_send_receive_msg(get_highlow)");
        return GPIO_ERROR_MSG_NOT_SENT;
    }

    switch (msg.value)
    {
    case 0:
        *level = GPIO_LOW;
        break;

    case 1:
        *level = GPIO_HIGH;
        break;

    default:
        return GPIO_ERROR_INPUT_OUT_OF_RANGE;
        break;
    };

    return GPIO_SUCCESS;
}

int rpi_gpio_add_event_detect(int gpio_pin, int coid, unsigned event, unsigned event_id)
{
    // Connect to the GPIO resource manager, if not connected already
    if (gpio_msg_connect())
    {
        perror("gpio_msg_connect");
        return GPIO_ERROR_NOT_CONNECTED;
    }

    if (gpio_pin < 0 || gpio_pin >= GPIO_COUNT)
    {
        return GPIO_ERROR_INPUT_OUT_OF_RANGE;
    }

    rpi_gpio_event_t event_msg = {
        .hdr.type = _IO_MSG,
        .hdr.subtype = RPI_GPIO_ADD_EVENT,
        .hdr.mgrid = RPI_GPIO_IOMGR,
        .gpio = gpio_pin};

    event_msg.detect = 0;
    if (event & GPIO_RISING)
    {
        event_msg.detect |= RPI_EVENT_EDGE_RISING;
    }
    if (event & GPIO_FALLING)
    {
        event_msg.detect |= RPI_EVENT_EDGE_FALLING;
    }

    if (event & GPIO_HIGH)
    {
        event_msg.detect |= RPI_EVENT_LEVEL_HIGH;
    }

    if (event & GPIO_LOW)
    {
        event_msg.detect |= RPI_EVENT_LEVEL_LOW;
    }

    if (event_msg.detect == 0)
    {
        return GPIO_ERROR_INPUT_OUT_OF_RANGE;
    }

    SIGEV_PULSE_INIT(&event_msg.event, coid, -1, _PULSE_CODE_MINAVAIL, event_id);
    if (gpio_msg_register_event(&event_msg.event))
    {
        perror("gpio_send_msg(event)");
        return GPIO_ERROR_MSG_EVENT_NOT_REGISTERED;
    }

    if (gpio_send_msg(&event_msg, sizeof(event_msg)))
    {
        perror("gpio_send_msg(event)");
        return GPIO_ERROR_MSG_NOT_SENT;
    }

    return GPIO_SUCCESS;
}

int rpi_gpio_setup_pwm(int gpio_pin, unsigned frequency, unsigned mode)
{
    // Connect to the GPIO resource manager, if not connected already
    if (gpio_msg_connect())
    {
        perror("gpio_msg_connect");
        return GPIO_ERROR_NOT_CONNECTED;
    }

    if (gpio_pin < 0 || gpio_pin >= GPIO_COUNT)
    {
        return GPIO_ERROR_INPUT_OUT_OF_RANGE;
    }

    // Configure as PWM
    rpi_gpio_pwm_t pwm_msg = {
        .hdr.type = _IO_MSG,
        .hdr.subtype = RPI_GPIO_PWM_SETUP,
        .hdr.mgrid = RPI_GPIO_IOMGR,
        .gpio = gpio_pin,
        .frequency = frequency,
        .range = 1024};

    switch (mode)
    {
    case GPIO_PWM_MODE_PWM:
        pwm_msg.mode = RPI_PWM_MODE_PWM;
        break;

    case GPIO_PWM_MODE_MS:
        pwm_msg.mode = RPI_PWM_MODE_MS;
        break;

    default:
        return GPIO_ERROR_INPUT_OUT_OF_RANGE;
        break;
    };

    if (gpio_send_msg(&pwm_msg, sizeof(pwm_msg)))
    {
        perror("gpio_send_msg(pwm)");
        return GPIO_ERROR_MSG_NOT_SENT;
    }

    return GPIO_SUCCESS;
}

int rpi_gpio_set_pwm_duty_cycle(int gpio_pin, float percentage)
{
    // Connect to the GPIO resource manager, if not connected already
    if (gpio_msg_connect())
    {
        perror("gpio_msg_connect");
        return GPIO_ERROR_NOT_CONNECTED;
    }

    if (percentage < 0.0 || percentage > 100.0)
    {
        return GPIO_ERROR_INPUT_OUT_OF_RANGE;
    }

    // Set duty cycle
    rpi_gpio_msg_t msg = {
        .hdr.type = _IO_MSG,
        .hdr.subtype = RPI_GPIO_PWM_DUTY,
        .hdr.mgrid = RPI_GPIO_IOMGR,
        .gpio = gpio_pin,
        .value = (int)(percentage * 1024.0 / 100.0)};

    if (gpio_send_msg(&msg, sizeof(msg)))
    {
        perror("gpio_send_msg(pwm_duty)");
        return GPIO_ERROR_MSG_NOT_SENT;
    }

    return GPIO_SUCCESS;
}
