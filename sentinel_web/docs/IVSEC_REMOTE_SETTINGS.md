# IVSEC remote event settings

Open **System → IVSEC remote settings** in Sentinel (or `/?tab=system`). Select a recorder camera and event type. **Perimeter intrusion (PID)** matches the perimeter-intrusion entries in Playback; **Intrusion** is a different IVSEC detector.

These settings are read from and written directly to IVSEC using the existing server-side credentials. There is no Sentinel scheduler to keep running: IVSEC stores and executes the saved schedules. The recorder reports supported controls and value ranges for each camera. Unsupported/offline configurations are shown without editable controls.

## Controls

- **Event detection:** enable/disable the selected detector, sensitivity and supported target filters. Existing polygons, crossing lines, and other native configuration are preserved. This editor does not create detection zones; events that need them must already have zones configured in IVSEC.
- **Event notifications & recording:** supported HTTP notification, recorder popup, recording channels, email, buzzer, relay and upload options. Their destinations still need to be configured on the recorder. Sentinel's existing collector already listens for all IVSEC event types; enabling HTTP notification is not a subscription filter for Sentinel. Home Assistant routing remains in Playback → IVSEC alerts.
- **Camera light / strobe:** the camera-wide light switch, warning light switch, light mode (`Warninglight` or `Strobe` where supported), duration and frequency.
- **Camera siren:** the camera-wide siren switch, sound, volume and duration. Saving configuration does not explicitly trigger a siren test.
- **Light / strobe schedule**, **Warning light schedule**, **Siren schedule:** independent output triggers for the selected camera and event, each with its own enable flag and seven-day timetable. An output needs both its camera-wide switch and event schedule enabled. IVSEC's global disarming state can suppress outputs as well.

The available catalog covers motion, perimeter intrusion, line crossing, human/vehicle detection, intrusion, entrance/exit, face, stationary object, cross counting, crowd/queue, rare sound, occlusion, sound, PIR, alarm input, sabotage, licence plate, video quality, and littering. Availability depends on the camera and firmware. Recorder-wide faults such as disk errors and video loss are not editable here.

## Weekly schedules

IVSEC uses **48 half-hour slots per calendar day**, in the recorder's local time. Each weekday accepts comma-separated on periods, for example:

```text
00:00-06:00, 19:00-24:00
```

This means on before 06:00 and from 19:00 onward, off during the daytime. Blank means off all day; `00:00-24:00` means on all day. Multiple intervals are supported. Overnight shorthand such as `19:00-06:00` fills the early and late slots of that same calendar day; use separate day rows for a Friday-night-only schedule continuing into Saturday. Preset buttons replace all seven day rows but do not save until you press the section's Save button. Presets retain the event trigger's enable/disable flag.

Example: Garage → Perimeter intrusion (PID): enable **Camera light / strobe**, select `Strobe`; enable its **Light / strobe schedule** with night periods. Set the siren's master switch and **Siren schedule** separately. Light/strobe mode is camera-wide, so the recorder cannot use steady light for one event and strobe for another through these APIs.

## Saving and deployment

Each section saves independently. Sentinel rereads the configuration before every write, refuses stale revisions, changes only the selected fields / event schedule, and confirms the requested values with a second read. Other channels, event schedules, areas and opaque firmware fields are preserved. A failed confirmation is not a successful save: reload that section to see the actual recorder state. Each save authenticates again before reading the current configuration. If IVSEC explicitly rejects an expired or replaced login (including its HTTP 400 authentication responses), Sentinel renews the session once. A write is never automatically replayed after a timeout or ambiguous transport failure. Switching camera/event discards unsaved edits.

Deploy the updated web and worker images from `sentinel_web` using your normal `pnpm docker:gpu` (or `pnpm docker`). No new environment variables are required. The browser only calls Sentinel; recorder credentials, cookies and CSRF tokens remain server-side.

Validation included live reads of Garage PID's seven sections and same-value saves/readback for actions, detection, light, siren and siren schedule. Full before/after configurations remained identical. Unit and browser tests cover preservation, validation, stale revisions, unconfirmed writes, schedules and cross-origin requests. No output activation test was run.
