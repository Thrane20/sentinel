# SENTINEL

An iPhone-first Next.js console for the local IVSEC recorder, with an original cyberpunk-inspired acid yellow, cyan, charcoal, and surveillance-grid interface.

## Run locally

Requires Node.js 22+ and FFmpeg (including libx264).

```sh
npm ci
cp .env.example .env.local
# Edit .env.local: set IVSEC_USERNAME and IVSEC_PASSWORD.
npm run dev
```

Open http://localhost:3000, or http://YOUR-COMPUTER-LAN-IP:3000 from your iPhone on the same network. For development from an iPhone, set DEV_ALLOWED_ORIGINS to the computer’s LAN IP in .env.local and restart; production does not need this setting. The interface works before credentials are configured; opening a camera explains what is missing.

## Host on Linux

Docker Compose includes FFmpeg and starts automatically after a reboot when Docker itself is enabled:

```sh
cp .env.example .env.local
# Fill in your recorder credentials.
# Set SENTINEL_PUBLIC_URL to the LAN address used by your iPhone.
npm run docker
npm run docker:check
npm run docker:stream-check -- 01
npm run docker:animals-check
```

`npm run docker` builds the images and starts Sentinel in the background at port 3000. On its first run, model setup downloads the pinned 26 MB MegaDetector bundle, verifies its SHA-256 checksum, adapts its end-to-end output to Frigate's supported flat detector format, and saves it in the `animal-models` Docker volume. Later starts are fully local. The basic check confirms that FFmpeg is installed inside the running container and that the app loaded its server-side configuration. The stream check requests a real camera through the complete RTSP → FFmpeg → HLS path; pass another two-digit channel after `--` to test it. The animals check reports MQTT, Frigate, model, accelerator, and webhook status. Useful follow-up commands are:

```sh
npm run docker:status
npm run docker:logs
npm run docker:stop
```

Use `npm run docker:foreground` when diagnosing startup because it keeps the container logs attached to the terminal. After changing `.env.local`, run `npm run docker` again to recreate the container with the new values. A successful `docker:check` proves that FFmpeg and the app are available; open a camera to perform the actual authenticated RTSP connection.

The launcher requires the Docker Compose v2 plugin and checks it with `docker compose version` before startup. If Linux reports an unknown `-f` flag or the check fails, install the plugin from Docker's package repository:

```sh
sudo apt-get update
sudo apt-get install docker-compose-plugin
docker compose version
```

The older standalone `docker-compose` command is not used by this project.

Alternatively install Node.js 22 and FFmpeg (`sudo apt install ffmpeg` on Debian/Ubuntu), run `npm ci && npm run build && npm start`, and supervise the process with systemd. Allow inbound TCP 3000 from your trusted LAN. The Linux host needs outbound TCP 554 access to the recorder. Optional HTTPS can be supplied by a reverse proxy.

This initial scaffold has no application login: anyone who can reach port 3000 can watch cameras. Keep it on a trusted LAN; add authentication before exposing it beyond that boundary. Credentials are server-only and excluded from Git/Docker build context. They are supplied to FFmpeg as an RTSP URL, so privileged host users can see them in process arguments. Do not use a shared/untrusted server.

## Local animal detection

The Compose stack adds Frigate 0.17.2, an internal Mosquitto broker, a persistent alert worker, and a one-shot model installer. Frigate reads the six verified mobile RTSP streams continuously at two detection frames per second. Dashboard snapshots now come from those existing Frigate readers, so opening the dashboard does not create a second set of FFmpeg snapshot processes. Live HLS still uses the recorder's main stream on demand.

The detector uses Microsoft's MIT-licensed `MDV6-mit-yolov9-c` MegaDetector model and records only its broad `animal` class. Frigate now requires an 80% tracked score, ignores boxes below 0.7% of the frame, and uses stricter motion filtering. Sentinel then requires the tracked object to move across 2-4% of the frame diagonal before it keeps an event. Front Drive also rejects boxes larger than 10% of the frame to suppress the known gate-shaped false detection. Confidence, minimum and maximum area, minimum movement, and detection enablement can be adjusted per camera from the Animals screen.

The startup script checks for `/dev/dri/renderD128`. When it exists, Compose exposes the Intel GPU and `FRIGATE_OPENVINO_DEVICE=AUTO` lets OpenVINO prefer it. When the device is absent, or `FRIGATE_OPENVINO_DEVICE=CPU` is set, startup automatically layers `compose.cpu.yaml` over the stack and removes the device mount. Video decoding remains on CPU so a detector fallback is not defeated by missing VAAPI support. The System and Animals screens report Frigate and event-bus health; live camera playback remains available if detection is offline.

Animal alerts begin in **shadow mode**. Detections and snapshots appear in Sentinel, but nothing is sent to Home Assistant until all of these steps are complete:

1. Set `SENTINEL_PUBLIC_URL` to the Linux host address reachable from Home Assistant and your iPhone.
2. Create a Home Assistant webhook trigger and put its complete URL in `HA_ANIMAL_WEBHOOK_URL`.
3. Run `npm run docker` again, then use **Animals → Send test alert**.
4. Review shadow detections for several days, adjust camera confidence, area, or minimum-movement filters, and enable **Send alerts**.

Movement is calculated from Frigate's retained object path. A live candidate is accepted as soon as its path passes the camera's minimum; otherwise Sentinel waits for the final event update and discards it. This intentionally delays stationary candidates while allowing a moving animal through promptly. Frigate's 80% confidence and 0.7% minimum-area limits are detector-wide baselines, so the per-camera controls can make filtering stricter but cannot restore candidates Frigate has already rejected.

Example Home Assistant automation, replacing the webhook ID and mobile service name:

```yaml
alias: Sentinel animal detected
mode: queued
trigger:
  - platform: webhook
    webhook_id: sentinel-animal-CHANGE-ME
    allowed_methods: [POST]
    local_only: true
condition:
  - condition: template
    value_template: "{{ trigger.json.type == 'sentinel.animal.detected' }}"
action:
  - service: notify.mobile_app_your_iphone
    data:
      title: "Animal at {{ trigger.json.camera.name }}"
      message: >-
        {{ (trigger.json.confidence * 100) | round(0) }}% confidence at
        {{ trigger.json.observedAt }}
      data:
        image: "{{ trigger.json.snapshotUrl }}"
        url: "{{ trigger.json.sentinelUrl }}"
```

Home Assistant receives no recorder credentials. Failed webhook requests retry after 1, 5, and 30 seconds. Event metadata and alert status live in a SQLite database using WAL mode; snapshots remain in Frigate for 30 days and the worker caps its history at 5,000 events. Detection controls persist across restarts and are synchronized to Frigate through retained MQTT commands.

The model artifact is pinned to SHA-256 `da4aa4505f8350dcb2cf2001bc329232e1f78188dc1614141a523ff9ef090655`. Before enabling alerts, use representative exported frames containing animals, empty scenes, people, vehicles, distant animals, and partial animals to confirm the model behaves appropriately for these cameras. Model updates require changing the URL and checksum, removing the `animal-models` volume, and repeating that review.

## What works

- Responsive live-view dashboard with camera search, zone filters, and optional historically offline channels.
- Eight camera slots are visible by default. Known online cameras refresh a low-bandwidth JPEG snapshot every second; previously offline channels remain visible and clearly labelled.
- Accessible camera dialog and real on-demand RTSP → H.264 HLS playback. hls.js where media extensions are available, with native HLS fallback for Safari. Video is muted, inline, and video-only in this release.
- One selected player per browser to limit phone bandwidth. Up to four shared server transcoders; unused workers and temporary files expire after 45–55 seconds. HLS adds several seconds of latency. Closing one viewer does not stop another viewer of the same channel.
- Playback opens a local exported clip with native seeking/fullscreen controls and lists new IVSEC alerts with their recorder timestamp and camera. Selecting an alert opens that camera's live view. Files stay in the browser and are not uploaded.
- IVSEC alerts are backfilled for the last seven days through `POST /API/Playback/SearchRecord/Search`, followed live through `POST /API/Event/Check`, and retained in Sentinel for 30 days, up to 5,000 entries. Set `IVSEC_HISTORY_DAYS` from 1–30 to change the startup backfill. The guarded clear action removes this local alert list and metadata without deleting recorder footage or recorder-side events.
- Read-only system screen with credential configuration status, setup steps, and saved camera/device inventory.
- Local animal-event screen with snapshots, acknowledgement, persistent camera controls, tuning, detector health, and optional Home Assistant delivery.
- Guarded bulk clearing of Sentinel event metadata and the corresponding Frigate event snapshots without changing detector settings.
- Linux Docker deployment with FFmpeg, process supervision, non-root runtime, and ephemeral HLS storage.

## Recorder assumptions and pending work

Source: `../IVSEC_FINDINGS.md`, dated 30 March 2026. Configured channels: 1 Front Door, 3 Pool, 4 Garage, 5 Front Drive, 6 Backyard - Down, 8 Side Passage. Channels 2 and 7 can also be opened via the inactive filter. Historical states are never presented as current online states. Card artwork is CSS illustration, not recorder imagery.

Only `ch01/0` is confirmed by the findings. Other channel URLs follow that path pattern and need live verification. `IVSEC_STREAM_INDEX=0` uses the confirmed main-stream variant; values 1 and 2 are available for testing sub/mobile streams. H.265 main stream is transcoded to 720p H.264 at 15fps for browser compatibility. CPU load depends on the Linux machine and concurrent viewers. FFmpeg stderr is suppressed to avoid leaking RTSP credentials; errors shown to the browser are sanitized.

Dashboard snapshots use `IVSEC_SNAPSHOT_STREAM_INDEX=2`, the recorder's mobile stream, through Frigate's continuous camera readers. Stream index 2 was verified on channels 1, 3, 4, 5, 6, and 8 on 7 September 2026. Frigate resizes detector input to 640×360 and runs inference at 2 fps; actual CPU, memory, and inference latency must be measured on the target Linux host.

Sentinel now performs read-only alert archive searches and live metadata polling. It first authenticates with HTTP Digest at `/API/Web/Login` and retains the session cookie and CSRF token. The archive collector queries the verified `SearchRecord/Search` date-range schema for alert-class recordings across all channels, backfills the configured number of days at startup, and refreshes the current day every five minutes. The live collector subscribes to all events, discards the initial state snapshot, and advances the recorder's `reader_id`, `sequence`, and `lap_number` cursor.

Playing or downloading an IVSEC recording directly from an alert, editable device settings, audio, PTZ, and ONVIF control are not implemented. Sentinel sends no write request to the recorder; clearing IVSEC alerts deletes Sentinel's local copies and records a local cutoff so those older entries stay hidden during later archive refreshes.

Host health means credentials are configured, not that the recorder is online or authenticated. Opening a camera performs the real connection attempt. Authentication/network/codec errors are reported in the player. Channel 1 was verified end to end through the Docker container on 7 September 2026: the app generated HLS segments and played the real camera at 1280×720. The remaining inferred channel paths still need individual checks on the target Linux host.

## Development checks

```sh
npm run lint
npm run typecheck
npm run build
npm run animal-worker:test
npx playwright install chromium
npm test
```

Fonts are bundled locally through Fontsource; the UI and streaming require no internet access. Relevant implementation references: [Next.js route handlers](https://nextjs.org/docs/app/getting-started/route-handlers), [hls.js](https://github.com/video-dev/hls.js), [FFmpeg HLS muxer](https://ffmpeg.org/ffmpeg-formats.html#hls-2).
