#ifndef CHANNELS_H
#define CHANNELS_H

typedef enum { SENSOR_GROUP_A = 0, SENSOR_GROUP_B = 1, SENSOR_GROUP_COUNT} sensor_group_t;

#define CHANNELS_PER_GROUP 4
#define CHANNEL_COUNT (SENSOR_GROUP_COUNT * CHANNELS_PER_GROUP)

typedef struct {
  const char *name;
  int bearing_deg;
  const char *motor;
  sensor_group_t group;
  int trigger_pin;
  int echo_pin;
} channel_config_t;

extern const channel_config_t CHANNELS[CHANNEL_COUNT];

#endif