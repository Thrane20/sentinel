# Home Assistant notifications and Sentinel playback

Home Assistant owns phone notifications and its saved notification entries. Sentinel supplies event details, snapshots and playback. No Sentinel browser notification permission is needed.

## Configure Home Assistant

1. Open Settings → Automations & scenes → Create automation → Create new automation, then its YAML editor.
2. Paste `examples/home-assistant/sentinel-animal-notification.yaml`.
3. Replace `REPLACE_WITH_A_LONG_RANDOM_PRIVATE_ID` with your own unique private webhook ID.
4. Both notification actions are configured as `notify.mobile_app_ians_iphone`. Change these only if the registered phone action changes.
5. Save and enable the automation.

The automation creates a persistent entry in Home Assistant with Play recording and Event details links, and sends an iPhone notification. Tapping the phone notification opens recorded playback directly. Repeated deliveries use the same event ID for the notification tag/ID to avoid duplicate entries.

## Configure Sentinel on Ubuntu

In `sentinel_web/.env.local`, set these two addresses for your network:

```dotenv
SENTINEL_PUBLIC_URL=http://192.168.68.202:3000
HA_ANIMAL_WEBHOOK_URL=http://192.168.68.201:8123/api/webhook/YOUR_PRIVATE_WEBHOOK_ID
```

`SENTINEL_PUBLIC_URL` must be reachable by your phone and Home Assistant. It is the Sentinel address, not the Home Assistant address. Use the URL of Home Assistant's actual HTTP/HTTPS listener for the webhook.

From `sentinel_web`, run:

```sh
pnpm docker
```

Then refresh Sentinel and choose Animals → Send test alert. This sends a synthetic test event even while Send alerts is off. The automation's test branch deliberately omits the synthetic snapshot, which does not exist. The test link opens camera 01 at the test timestamp; it is not an actual animal detection.

Once the test works, enable Animals → Send alerts. Existing camera filters, cooldown and hourly caps determine which events are accepted and sent. Home Assistant does not need to connect to Frigate or the recorder.

## Links and recording retention

Webhook payloads include:

- `snapshotUrl`: event image in Sentinel.
- `sentinelUrl`: event details, looked up by ID independently of the latest-40 list.
- `playbackUrl`: camera and original detection timestamp, opening recorder playback directly with the existing five-second pre-roll.

Playback links remain useful after Sentinel metadata is cleared or expires, provided the recorder still holds that camera/time. Expired recorder footage displays Recording unavailable. Event-details links show a clear expired/cleared message if the metadata is gone. A synthetic test event has no stored details or snapshot.

Invalid playback links display an error and never silently switch to current-time footage. The phone may still require a tap on Play if its browser blocks automatic media playback.

## Future reverse proxy

Use a dedicated HTTPS hostname, for example:

```dotenv
SENTINEL_PUBLIC_URL=https://sentinel.example.com
```

Point the reverse proxy at Sentinel port 3000 and forward normal HTTP/video streaming traffic. Configure access controls at the proxy before making this currently LAN-oriented app publicly reachable; this feature does not add application authentication. Use a dedicated hostname at `/`; hosting under a path prefix requires separate Next.js base-path configuration.

Update `.env.local` and redeploy to change URLs in new notifications. Existing notifications retain the address they were sent with. Home Assistant's own remote access does not proxy Sentinel links or snapshots; the phone must be able to reach Sentinel through LAN, VPN or the future proxy.

The Home Screen icon provides an app-like web experience but does not register a `sentinel://` URI scheme. Notification links use standard HTTP(S); iOS chooses the browser/web-app context, so launching the existing standalone Home Screen window is not guaranteed.

## Recorder arming control

The home screen's IVSEC control changes the recorder's global `disarming` flag. It preserves configured disarming channels, schedules and alarm actions. It does not change Sentinel's separate Frigate detection or Home Assistant alert settings.

A green Armed badge means IVSEC reported `disarming: false`; the red Disarmed banner means it reported `true`. Sentinel checks status every ten seconds, reads it back after each change, and shows Status unavailable if it cannot verify the flag. This describes IVSEC's global flag rather than independently checking every alarm schedule or channel.

Recorder credentials stay in the worker. Changes use an authenticated recorder session and a read/modify/write/read sequence. Access to Sentinel's existing LAN interface now also permits arming changes; keep it restricted to trusted users and protect it with authentication before external access. Deploy both Sentinel and its worker with `npm run docker:gpu` to install this feature.
