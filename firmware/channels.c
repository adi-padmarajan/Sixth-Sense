#include "channels.h"

#define TRIGGER_PIN_GROUP_A 11  // BCM 11 (physical pin 23) -- cardinals
#define TRIGGER_PIN_GROUP_B 5   // BCM 5  (physical pin 29) -- diagonals

#define ECHO_PIN_FRONT       17  // BCM 17 (physical pin 11)
#define ECHO_PIN_FRONT_RIGHT 2   // BCM 2  (physical pin 3)
#define ECHO_PIN_RIGHT       3   // BCM 3  (physical pin 5)
#define ECHO_PIN_REAR_RIGHT  4   // BCM 4  (physical pin 7)
#define ECHO_PIN_REAR        9   // BCM 9  (physical pin 21)
#define ECHO_PIN_REAR_LEFT   27  // BCM 27 (physical pin 13)
#define ECHO_PIN_LEFT        22  // BCM 22 (physical pin 15)
#define ECHO_PIN_FRONT_LEFT  10  // BCM 10 (physical pin 19)

// Motor pins -- from pin_map_pi.md's "pin: sensor" table, cross-checked
// against the echo/trigger table's sensor numbering (1=front_right,
// 2=right, 3=rear_right, 4=front, 5=rear_left, 6=left, 7=front_left,
// 8=rear). Not yet verified against real hardware -- confirm each motor
// fires on its intended channel with a stationary bring-up check before
// trusting this in a demo (AGENTS.md SS12: a driver ack doesn't prove
// physical vibration).
#define MOTOR_PIN_FRONT        7  // BCM 7  (physical pin 26)
#define MOTOR_PIN_FRONT_RIGHT 15  // BCM 15 (physical pin 10)
#define MOTOR_PIN_RIGHT        8  // BCM 8  (physical pin 24)
#define MOTOR_PIN_REAR_RIGHT  24  // BCM 24 (physical pin 18)
#define MOTOR_PIN_REAR        14  // BCM 14 (physical pin 8)
#define MOTOR_PIN_REAR_LEFT   18  // BCM 18 (physical pin 12)
#define MOTOR_PIN_LEFT        25  // BCM 25 (physical pin 22)
#define MOTOR_PIN_FRONT_LEFT  23  // BCM 23 (physical pin 16)

const channel_config_t CHANNELS[CHANNEL_COUNT] = {
    { "front",       0, "motor_0", SENSOR_GROUP_A, TRIGGER_PIN_GROUP_A, ECHO_PIN_FRONT,       MOTOR_PIN_FRONT },
    { "front_right",45, "motor_1", SENSOR_GROUP_B, TRIGGER_PIN_GROUP_B, ECHO_PIN_FRONT_RIGHT, MOTOR_PIN_FRONT_RIGHT },
    { "right",      90, "motor_2", SENSOR_GROUP_A, TRIGGER_PIN_GROUP_A, ECHO_PIN_RIGHT,       MOTOR_PIN_RIGHT },
    { "rear_right",135, "motor_3", SENSOR_GROUP_B, TRIGGER_PIN_GROUP_B, ECHO_PIN_REAR_RIGHT,  MOTOR_PIN_REAR_RIGHT },
    { "rear",      180, "motor_4", SENSOR_GROUP_A, TRIGGER_PIN_GROUP_A, ECHO_PIN_REAR,        MOTOR_PIN_REAR },
    { "rear_left", 225, "motor_5", SENSOR_GROUP_B, TRIGGER_PIN_GROUP_B, ECHO_PIN_REAR_LEFT,   MOTOR_PIN_REAR_LEFT },
    { "left",      270, "motor_6", SENSOR_GROUP_A, TRIGGER_PIN_GROUP_A, ECHO_PIN_LEFT,        MOTOR_PIN_LEFT },
    { "front_left",315, "motor_7", SENSOR_GROUP_B, TRIGGER_PIN_GROUP_B, ECHO_PIN_FRONT_LEFT,  MOTOR_PIN_FRONT_LEFT },
};