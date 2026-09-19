# Project Spec: Haptic Echolocation Wearable

## Overview
A wearable device that grants users a form of "sixth sense" — spatial awareness through haptic (vibration) and auditory feedback — for navigating environments with poor visibility (smoke, murky water, darkness, debris). It combines proximity sensing, computer vision, and a voice assistant into a hands-free, head-worn form factor.

## Target Applications
- **Firefighting** — navigating smoke-filled structures
- **Wildland fire response** (e.g., FireSmart Canada-adjacent field work) — situational awareness in low-visibility, hazardous terrain
- **Underwater welding / diving** — sensing in low-visibility, high-risk environments
- Other candidates worth considering: search & rescue, mining, industrial confined-space work, assistive tech for the visually impaired

## Core Features

### 1. 360° Proximity Sensing & Haptic Feedback
- 8x distance sensors arranged radially around the headset for full 360° coverage
- Each sensor paired with a corresponding vibration motor, mapped directionally (e.g., a sensor on the left triggers the left motor)
- Sensing range: 3–4m (confirm this is sufficient for the use case — firefighting in zero-visibility smoke may need a shorter, higher-confidence range; underwater welding may need different sensor tech entirely, see Open Questions)
- Vibration intensity/frequency scales inversely with distance: slower pulses = far, faster pulses = close
- Consider a max-alert state (e.g., continuous vibration) for imminent-contact distances

### 2. Voice Assistant
- Voice-activated control to personalize/adjust haptic feedback sensitivity, motor mapping, and alert thresholds
- Voice queries can trigger an AI (API-based) description of surroundings — e.g., "what's in front of me?" — using camera input
- Should support fully hands-free operation (critical given gloved hands / task-loaded users)

### 3. Computer Vision for Environmental Audio Feedback
- Onboard camera feeds a CV model that identifies objects/obstacles/hazards and describes them via audio
- Distinct from the raw proximity sensors — this layer adds semantic understanding (e.g., "person on your left" vs. just "object 1.5m left")

### 4. Form Factor
- Worn as a helmet-mountable or standalone adjustable headband/hat
- Flexible/adjustable strap system to fit most head sizes and accommodate helmets (especially important for firefighting where this may need to integrate with existing PPE, not replace it)
- Integrated components: 8x proximity sensors, 8x vibration motors, 1x camera, 1x speaker (bone conduction may be worth considering over open-air speaker, so ambient hearing isn't blocked — important for firefighters who rely on radio comms and ambient sound cues)

## Open Questions / Gaps to Resolve
- **Power**: battery type, runtime target, charging method (must survive harsh conditions — heat, water)
- **Environmental sealing**: IP rating needed for fire (heat resistance) vs. underwater (waterproof to depth) — these are very different engineering requirements and may need separate hardware variants
- **Sensor technology**: ultrasonic, infrared, LiDAR, or sonar? Choice affects performance underwater vs. in smoke vs. in clear air — worth specifying per use case
- **Latency**: acceptable delay between sensing and haptic response (safety-critical in fast-moving hazards)
- **Connectivity**: does the AI/CV processing happen onboard (edge) or require a network connection? Firefighting environments often have no connectivity — onboard/edge processing is likely a hard requirement
- **Durability/certification**: what safety standards apply for firefighting gear (e.g., NFPA) or diving equipment?
- **Failure mode**: what happens if a sensor, motor, or the whole unit fails mid-use? Needs a safe default/degraded state
- **Weight & comfort**: total device weight budget for extended wear under a helmet
- **Speaker vs. bone conduction**: decide based on need to preserve ambient hearing
