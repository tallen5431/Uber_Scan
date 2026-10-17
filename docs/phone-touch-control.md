# Phone touch-control experiment

## Goal

Test whether the Raspberry Pi dashboard touchscreen can become the single manual control surface for both Uber Scan and the mounted Android phone.

The phone remains the device running delivery apps. Uber Scan already publishes a perspective-corrected, high-resolution phone-screen view for the rig display. This experiment adds an explicit manual-control path from touches on that view to ordinary Android HID pointer input.

This is intentionally **not** offer automation. No OCR result, recommendation, timer, or screen content may generate a click. Every pointer action sent to Android must originate from a current physical user gesture.

## Why a separate branch

The input experiment has hardware and Bluetooth dependencies that CI cannot reproduce. Keep it isolated from the reliability/refactor work until it proves useful on the rig.

Suggested branch: `experiment/phone-touch-control`.

## Architecture

```text
Pi touchscreen
      |
      v
live.html phone-screen view
      |
      | physical pointer/touch gesture only
      v
local input endpoint / Unix-side helper
      |
      v
Bluetooth HID mouse service
      |
      v
Android phone
```

The camera/phone warp remains display-only. OCR and offer analysis never call the HID layer.

## Stages

### Stage 0 — capability probe

Before changing the dashboard behavior, add a diagnostic helper that reports:

- Linux touchscreen input devices and event capabilities
- Bluetooth adapter presence/state
- whether the required HID transport is available
- configured Android target, if any

Failure must leave the existing dashboard untouched.

### Stage 1 — touch instrumentation

Add an opt-in `Phone control` mode to the phone-screen view. While enabled, pointer/touch events over the phone image are captured and logged/posted as normalized coordinates plus gesture phase (`down`, `move`, `up`).

No Android output yet. This proves that the browser can distinguish dashboard controls from touches intended for the phone and lets us measure latency and coordinate behavior on the real display.

Requirements:

- OFF by default
- visible armed/disarmed state
- only the phone image captures events
- existing dashboard buttons remain local
- leaving phone view disarms forwarding
- Escape/cancel action immediately disarms it
- no synthetic click generated from OCR or scanner state

### Stage 2 — relative pointer forwarding

Implement Android output as a normal HID mouse and initially treat the phone image like a trackpad:

- one-finger drag -> relative pointer movement
- short tap -> left click
- two-finger vertical drag -> wheel/scroll, if reliable

Relative mode is the first hardware test because it does not depend on exact camera crop, phone resolution, Android display scaling, or perspective calibration.

### Stage 3 — direct mapped touch

Once relative forwarding is reliable, optionally map a touch on the perspective-corrected phone image to the corresponding Android pointer location.

This needs an explicit calibration step and must account for:

- image element letterboxing/object-fit
- perspective-warp crop
- Android screen resolution and orientation
- pointer coordinate range
- camera/mount movement

Do not infer or click UI controls from image content. Mapping only transforms a physical touch supplied by the user.

### Stage 4 — usability/recovery

Add:

- obvious Phone Control ON/OFF indicator
- reconnect/status indication
- configurable sensitivity and tap threshold
- emergency local-only gesture/button to disarm forwarding
- optional startup preference, defaulting to OFF until the feature is proven

## Safety boundaries

1. HID output is only produced from a live physical input gesture.
2. Scanner/OCR/advice code cannot call the click/keypress API.
3. Phone control is opt-in and visibly armed.
4. Loss of the browser session, Bluetooth link, or input source releases buttons and disarms control.
5. Existing dashboard controls are excluded from forwarding.
6. The first implementation uses generic Android HID behavior; it does not use ADB, Accessibility APIs, screen-coordinate scripting, or app-specific automation.

## Test plan

1. Test against Android home screen/Settings first.
2. Verify move, tap, drag and scroll behavior without a delivery app open.
3. Verify disconnect/reconnect never leaves a mouse button held.
4. Verify dashboard controls never forward to Android.
5. Verify switching Scene/Map/Phone view disarms or gates forwarding correctly.
6. Measure touch-to-visible-cursor latency from the rig display.
7. Only after generic Android behavior is reliable, manually test ordinary pointer interaction in the delivery app.

## First implementation slice

The first code slice should contain only:

- a small, separately testable gesture/coordinate module
- dashboard UI for arming phone control
- event capture over the phone image
- a diagnostic/logging transport that does not control Android
- unit tests for normalization, tap-vs-drag classification, cancellation and disarm behavior

Bluetooth HID output comes in the next slice after the real Pi touchscreen behavior is observed.
