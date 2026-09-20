# Builds the sixth-sense sensor -> haptic firmware for the QNX Spidey
# Sense Raspberry Pi: main.c + sensor.c + sensor_driver_qnx.c + channels.c
# + the proximity_* policy files, linked against the vendored rpi_gpio
# resource-manager client in third_party/rpi_gpio/.
#
# Requires the QNX Software Development Platform: either `qcc`/`q++` on
# PATH with QNX_HOST set (cross build from Linux/macOS/Windows), or a
# self-hosted QNX target with clang. See third_party/config.mk for how
# the toolchain is selected. sensor_driver_qnx.c includes QNX-only
# headers (<sys/neutrino.h>, the rpi_gpio resource-manager protocol), so
# this cannot be compiled with a plain host gcc/clang.
#
# This Makefile has not been exercised against a real QNX SDP in this
# environment -- verify `make` succeeds on your actual toolchain before
# relying on it, and report back if paths/flags need adjusting.
#
# Usage:
#   make                              # build build/<platform>-<profile>/sixth_sense_firmware
#   make PLATFORM=armv7le BUILD_PROFILE=release
#   make clean
#   make rebuild

include third_party/config.mk

ifndef BUILD_QNX
$(warning BUILD_QNX is not set. This firmware needs QNX headers (sys/neutrino.h, \
the rpi_gpio resource-manager protocol) from the QNX SDP toolchain -- set QNX_HOST \
or build on a QNX host. Continuing with a plain host compiler will fail.)
endif

# Build architecture/variant string, possible values: aarch64le, armv7le, ...
PLATFORM ?= aarch64le

# Build profile, possible values: release, debug
BUILD_PROFILE ?= debug

CONFIG_NAME = $(PLATFORM)-$(BUILD_PROFILE)
OUTPUT_DIR = build/$(CONFIG_NAME)
TARGET = $(OUTPUT_DIR)/sixth_sense_firmware

RPI_GPIO_DIR = third_party/rpi_gpio
RPI_GPIO_LIB = $(RPI_GPIO_DIR)/build/$(CONFIG_NAME)/librpi_gpio.a

CCFLAGS_release += -O2
CCFLAGS_debug += -g -O0 -fno-builtin
CCFLAGS_all += -Wall -fmessage-length=0 $(CCFLAGS_$(BUILD_PROFILE))

# public/ has the rpi_gpio.h client API sensor_driver_qnx.c includes;
# system_gpio/ has the sys/rpi_gpio.h resource-manager protocol header
# rpi_gpio.c itself needs (built by RPI_GPIO_DIR's own Makefile).
INCLUDES += -I. -I$(RPI_GPIO_DIR)/public

SRCS = main.c sensor.c sensor_driver_qnx.c channels.c proximity_band.c proximity_filter.c proximity_state.c haptic_pattern.c motor_driver_qnx.c
OBJS = $(addprefix $(OUTPUT_DIR)/,$(SRCS:.c=.o))
DEPS = -Wp,-MMD,$(@:%.o=%.d),-MT,$@

LIBS_all += -lpthread

all: $(TARGET)

$(OUTPUT_DIR)/%.o: %.c
	-@mkdir -p $(OUTPUT_DIR)
	$(CC) -c $(DEPS) -o $@ $(INCLUDES) $(CCFLAGS_all) $(CCFLAGS) $<

$(TARGET): $(RPI_GPIO_LIB) $(OBJS)
	-@mkdir -p $(OUTPUT_DIR)
	$(LD) $(LDFLAGS_exe) $(TARGET) $(LDFLAGS_all) $(LDFLAGS) $(OBJS) -L$(dir $(RPI_GPIO_LIB)) -lrpi_gpio $(LIBS_all) $(LIBS)

# Always delegates to the vendored Makefile so its own object/dependency
# tracking decides whether a rebuild is actually needed.
.PHONY: $(RPI_GPIO_LIB)
$(RPI_GPIO_LIB):
	$(MAKE) -C $(RPI_GPIO_DIR) PLATFORM=$(PLATFORM) BUILD_PROFILE=$(BUILD_PROFILE)

clean:
	rm -rf build
	$(MAKE) -C $(RPI_GPIO_DIR) clean

rebuild: clean all

-include $(OBJS:%.o=%.d)

.PHONY: all clean rebuild
