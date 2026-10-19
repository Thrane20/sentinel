# IVSEC event inspection and Home Assistant routing

In Playback → IVSEC alerts, use **Inspect** beside an event. The inspector shows the camera, exact Sentinel event key, recorder time, whether it came from the live feed or historical recordings, raw IVSEC data (with credentials redacted), and routed delivery history. **Create notification rule** preselects that event's camera and key. A recording-type label can be broader than the live event subtype; inspect a live event to identify `perimeter_intrusion` (`int_subtype: pid`). Sentinel does not infer intrusion from a generic Motion or Perimeter alert.

Rules are saved under **Home Assistant notification rules**. For example:

| Setting | Value |
| --- | --- |
| Notification ID | `garage_intrusion` |
| Camera | Garage · CH 04 |
| IVSEC event key | `perimeter_intrusion` |
| Message | Something is moving in the garage |
| Rule cooldown | 60 seconds |

New rules default to disabled. Enable automatic delivery and save when ready. Editing an existing notification ID updates that rule. Notification IDs and event keys are lowercase letters, numbers and underscores, starting with a letter, up to 64 characters. Camera and event key are exact matches. Time windows, sounds and escalation belong in Home Assistant; rules work independently of Sentinel's animal alert switch and the IVSEC disarming control.

## Home Assistant setup

1. Create an automation from `examples/home-assistant/sentinel-ivsec-receiver.yaml`, giving it a separate private webhook ID. Keep the existing animal receiver unchanged.
2. Add the matching URL to Ubuntu's `sentinel_web/.env.local`:

   ```dotenv
   HA_IVSEC_WEBHOOK_URL=http://192.168.68.201:8123/api/webhook/YOUR_PRIVATE_IVSEC_WEBHOOK_ID
   SENTINEL_PUBLIC_URL=http://192.168.68.202:3000
   ```

3. Deploy with `npm run docker:gpu` from `sentinel_web`.
4. Save a rule matching an inspected event. Reopen its inspector and select **Send HA test**. This queues a marked test, including a recording link to that event's actual camera/time. Check the inspector's delivery history after reopening it and Home Assistant's saved notification. A delivered HTTP request does not itself prove HA ran its automation; check HA's trace too.
5. The receiver fires `sentinel_ivsec_test` for manual tests and `sentinel_ivsec` for real rule matches. In HA Developer Tools → Events, listen for either name to inspect the payload. Tests do not trigger the normal `sentinel_ivsec` automation.
6. Use `examples/home-assistant/garage-intrusion-notification.yaml` as a separate phone automation. Its trigger matches `notification_id: garage_intrusion`, `camera_id: "04"` and `event_key: perimeter_intrusion`. Adjust its example 22:00–07:00 time window before enabling. The window uses HA's configured local time at delivery. iOS Critical Alerts permission must be enabled for critical sounds to bypass mute/Focus; select a supported custom sound in the HA Companion app if desired.

The receiver also creates a persistent Home Assistant notification with **Play recording** and **Inspect event** links. No recorder credentials are sent to HA. Links use `SENTINEL_PUBLIC_URL`, so phones need LAN/VPN access until a protected HTTPS reverse proxy is configured.

## Delivery semantics

Only newly ingested live events with a valid recorder timestamp within the last two minutes (up to one minute of clock skew ahead) and after rule creation can trigger automatic delivery. Historical imports, old cursor data and events with missing recorder times do not alert. Clearing the event list does not reset rule cooldowns or delivery deduplication. Different event subtypes at the same camera/time are retained independently; archive imports no longer overwrite specific live events.

Deliveries are stored in SQLite, survive worker restarts, retry up to four attempts (1/5/30 seconds between attempts), and expire after five minutes. Duplicate camera/time/event/rule combinations use a stable delivery ID. Cooldown is per rule; 0 disables cooldown while preserving event deduplication. Editing, disabling or deleting a rule cancels its pending deliveries; a request already in flight may finish. Terminal delivery records are retained for 30 days. Delivery is at least once: a lost HTTP acknowledgement can cause a retry. HA's persistent notification ID and the phone notification tag use the delivery ID to replace duplicates; custom HA actions requiring stricter deduplication should retain/check that ID.

The event inspector's detail link needs retained Sentinel metadata; playback links carry the camera/time directly and continue working while the recorder retains that footage. Rule tests can use historical events deliberately and are clearly marked as tests. No snapshots are claimed for IVSEC events.
