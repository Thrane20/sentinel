# IVSEC Local API and Stream Recon

Date: 2026-03-30
Target: `192.168.68.203`
Context: Local read-only inspection of an IVSEC unit owned by the operator.

## Summary

- Open ports confirmed: `80/tcp`, `443/tcp`, `554/tcp`
- The web UI is available over both HTTP and HTTPS.
- The root page is a Vue/SPA frontend that references internal `/API/...` endpoints.
- The web/API auth model is layered:
  - HTTP Digest auth is active on API endpoints.
  - `POST /API/Web/Login` succeeds and returns:
    - `X-csrftoken`
    - `Set-Cookie: session=...`
  - Replaying the authenticated session with a real cookie jar plus CSRF token is sufficient for at least some follow-up API calls.
- Public unauthenticated bootstrap endpoint exists:
  - `POST /API/Login/Range`
- RTSP is confirmed working on `554`.
  - `OPTIONS rtsp://192.168.68.203/ch01/0` returned `200 OK`
  - Authenticated `DESCRIBE rtsp://192.168.68.203/ch01/0` returned valid SDP for H.265 video plus PCMA audio

## Confirmed HTTP Behavior

### Root UI

- `GET http://192.168.68.203/` and `GET https://192.168.68.203/` both return the same login SPA.
- Response includes:
  - `Content-Security-Policy`
  - `X-Frame-Options: SAMEORIGIN`
  - `X-Robots-Tag: noindex`
  - `Strict-Transport-Security` on HTTPS

### Missing Paths

- Missing paths return structured JSON rather than HTML:

```json
{"version":"1.0","error_code":"not_found"}
```

### Login Bootstrap

- `POST /API/Login/Range` returns public login metadata.
- Observed response:

```json
{
  "result": "success",
  "data": {
    "username": {"type":"string","min_len":1,"max_len":16},
    "password": {"type":"string","min_len":8,"max_len":16},
    "pwd_tip": "nvr_tip",
    "first_login_flag": false,
    "password_enc": true,
    "http_api_version": "V2.0",
    "default_lang": "ENU",
    "custom_name": 189,
    "custom_logo": 189,
    "login_exclusivity": false,
    "use_recover_password": true,
    "site_version": "NR16-9000-4TB",
    "recover_password_need_authentication": true,
    "set_recover_password_flag": true,
    "set_recover_password_enable": false
  }
}
```

## Confirmed Login Flow

### Digest Challenge

- Direct POST attempts without digest returned:
  - `401 Unauthorized`
  - `WWW-Authenticate: Digest realm="device", ...`

### Working Login Request

- This worked:

```http
POST /API/Web/Login
Authorization: Digest ...
Content-Type: application/json

{}
```

- Successful response included:
  - `X-csrftoken: <token>`
  - `Set-Cookie: session=<value>; HttpOnly; Secure; path=/`

- Response body:

```json
{"result":"success","data":{"strength_need_check":false}}
```

## Recovered Frontend Route Map

Recovered from the public JS bundles:

### Login and bootstrap

- `Web/Login`
- `Login/Range`
- `Login/ChannelInfo/Get`
- `Login/DeviceInfo/Get`
- `Web/Get_Private_Key`

### Preview and playback

- `Preview/StreamUrl`
- `Playback/Record`
- `Playback/Picture/Get`
- `Playback/SearchMonth/Get`
- `Playback/SearchRecord/Search`
- `Playback/PlaybackPage/Range`
- `Playback/Tag`
- `/API/GetDashPlaybackUrl`

### Event and alarm configuration

- `Event`
- `AlarmConfig/EventPush`
- `AlarmConfig/IO`
- `AlarmConfig/Motion`
- `AlarmConfig/PIR`
- `AlarmConfig/Deterrence`
- `AlarmConfig/Exception`
- `AlarmConfig/VoicePrompts`
- `AlarmConfig/ManualPush`

### AI / analytics namespaces

The frontend also references many AI/event-like routes under `/API/AI/...`, including:

- `FDGroup/Get`
- `FDGroup/GetId`
- `FDGroup/Add`
- `FDGroup/Remove`
- `FDGroup/Modify`
- `AddedFaces/Search`
- `AddedFaces/GetByIndex`
- `AddedFaces/GetById`
- `Faces/Add`
- `Faces/Modify`
- `Faces/Remove`
- `SnapedFaces/Search`
- `SnapedFaces/GetByIndex`
- `SnapedFaces/GetById`
- `SnapedObjects/Search`
- `SnapedObjects/GetByIndex`
- `SnapedObjects/GetById`
- `FaceStatistics/Get`
- `ObjectStatistics/Get`
- `PlateGroup/Get`
- `PlateGroup/GetId`
- `Plates/Add`
- `Plates/Modify`
- `Plates/Remove`

These strongly suggest that at least some event, analytics, or searchable object/face data can be queried through the web API after a valid full client session is established.

## API Calls Tested

### Worked

- `POST /API/Login/Range`
- `POST /API/Web/Login` with HTTP Digest auth
- `POST /API/Login/DeviceInfo/Get` with:
  - HTTP Digest auth
  - the session cookie captured from `Web/Login`
  - the `X-csrftoken` returned by `Web/Login`
- `POST /API/Login/ChannelInfo/Get` with:
  - HTTP Digest auth
  - the session cookie captured from `Web/Login`
  - the `X-csrftoken` returned by `Web/Login`

### Exists but requires session

- `GET /API/GetDashPlaybackUrl?...`
  - Returned `{"error_code":"no_login"}` before authentication

### Earlier `one_IE` Result

An earlier replay attempt returned `{"version":"1.0","error_code":"one_IE"}` for:

- `POST /API/Login/DeviceInfo/Get`
- `POST /API/Login/ChannelInfo/Get`
- `POST /API/AlarmConfig/EventPush/Range`
- `POST /API/AlarmConfig/EventPush/Get`

That result is no longer reproducible for `DeviceInfo/Get` and `ChannelInfo/Get` when the login flow is replayed with:

- `curl --digest`
- a cookie jar created from `Set-Cookie` on `Web/Login`
- `X-csrftoken` from the same login response
- browser-like request headers (`Origin`, `Referer`, `X-Requested-With`, `User-Agent`)

The `AlarmConfig/...` endpoints were not re-tested in this round.

Observed earlier response:

```json
{"version":"1.0","error_code":"one_IE"}
```

Interpretation:

- The API is sensitive to session replay details.
- For the endpoints above, the missing piece was likely how the cookie/session state was replayed rather than a hard browser-plugin gate.
- A real browser may still be needed for some configuration or event endpoints.

## Successful Authenticated API Responses

### `Login/ChannelInfo/Get`

- Returned `channel_param` for all 16 channels.
- Confirmed online channels:
  - `CH1` `Front Door`
  - `CH3` `Pool`
  - `CH4` `Garage`
  - `CH5` `Front Drive`
  - `CH6` `Backyard -Down`
  - `CH8` `Side Passage`
- Confirmed failed/offline channels:
  - `CH2` `Backyard - Up`
  - `CH7` `Boat Shed`
  - `CH9`
  - `CH10`
- Online channels advertise stream abilities including:
  - `Mainstream`
  - `Substream`
  - `Mobilestream`

### `Login/DeviceInfo/Get`

- Returned device metadata including:
  - `device_type`: `NR16-9000-4TB`
  - `software_version`: `8.2.4.1`
  - `local_ip`: `192.168.68.203`
  - `media_port`: `9000`
  - `default_stream`: `SubStream`
  - `support_seqshow_https_rtsp_port`: `true`
  - `show_rtsp_protocol_example`: `true`
  - `enable_encryption`: `true`

## RTSP Notes

- Port `554` is open.
- Public docs for IVSEC/X-range products suggest RTSP paths like:
  - `rtsp://<ip>/ch01/0`
  - `rtsp://<ip>/ch01/1`
  - `rtsp://<ip>/ch01/2`

- Raw RTSP negotiation confirms the server is active on `ch01/0`.
  - `OPTIONS rtsp://192.168.68.203/ch01/0` returned:
    - `RTSP/1.0 200 OK`
    - `Public: OPTIONS, DESCRIBE, PLAY, PAUSE, SETUP, TEARDOWN, SET_PARAMETER, GET_PARAMETER`
  - unauthenticated `DESCRIBE rtsp://192.168.68.203/ch01/0` returned:
    - `RTSP/1.0 401 Unauthorized`
    - `WWW-Authenticate: Digest realm="device", nonce="..."`
  - authenticated digest `DESCRIBE rtsp://192.168.68.203/ch01/0` returned `RTSP/1.0 200 OK` with SDP:
    - video codec: `H265/90000`
    - advertised frame rate: `20`
    - advertised dimensions: `3840x2160`
    - audio codec: `PCMA/8000`

Interpretation:

- RTSP is the practical live-stream path.
- `ch01/0` is a valid authenticated stream URL for channel 1 main stream.
- The earlier reset was caused by using the wrong client behavior, not by RTSP being unavailable.

## Practical Next Steps

1. Test RTSP with a real client.
   - VLC
   - `ffprobe`
   - `gst-launch-1.0`
   - ONVIF Device Manager
   - starting point confirmed:
     - `rtsp://192.168.68.203/ch01/0`

2. Probe additional RTSP variants for the online channels.
   - likely candidates:
     - `rtsp://192.168.68.203/ch01/0`
     - `rtsp://192.168.68.203/ch01/1`
     - `rtsp://192.168.68.203/ch01/2`
     - repeat for `ch03`, `ch04`, `ch05`, `ch06`, `ch08`

3. Try ONVIF discovery and media/event queries.
   - This may expose stream URIs and event subscriptions more cleanly than the web API.

4. Reproduce the browser login flow in a real browser.
   - Capture network traffic from DevTools.
   - Compare the browser's preview requests against the working RTSP path and the now-working `DeviceInfo/Get` and `ChannelInfo/Get` calls.

5. Check whether the frontend opens a long-link or websocket-style event channel.
   - The JS bundle references long-link style message names.

6. Re-test additional authenticated API namespaces:
   - `Login/DeviceInfo/Get`
   - `Login/ChannelInfo/Get`
   - `AlarmConfig/EventPush/Get`
   - `GetDashPlaybackUrl`
   - `/API/AI/...` analytics/event routes

## ONVIF Events

- Standard ONVIF device endpoint is present:
  - `http://192.168.68.203/onvif/device_service`
  - `https://192.168.68.203/onvif/device_service`
- `GetServices` on `2026-03-30` returned an Events service:
  - namespace: `http://www.onvif.org/ver10/events/wsdl`
  - XAddr: `http://192.168.68.203/onvif/events_service`
- Reported event capabilities:
  - `WSPullPointSupport="true"`
  - `MaxPullPoints="8"`
  - `PersistentNotificationStorage="false"`
  - `WSSubscriptionPolicySupport="false"`
  - `WSPausableSubscriptionManagerInterfaceSupport="false"`
- `GetCapabilities` also reported:
  - `<tt:Events><tt:XAddr>http://192.168.68.203/onvif/events_service</tt:XAddr>`
  - `<tt:WSPullPointSupport>true</tt:WSPullPointSupport>`

### Practical Status

- Service-level ONVIF Events support is confirmed.
- A direct call to `GetServiceCapabilities` on `http://192.168.68.203/onvif/events_service` returned `200 OK`.
- However, higher-value event operations did not succeed in this round:
  - `GetEventProperties`
  - `CreatePullPointSubscription`
- Those calls returned `401 Unauthorized` with:
  - `WWW-Authenticate: Digest realm="device", ... , userhash="true"`
- Replaying HTTP Digest auth manually was still rejected, so practical event polling is not yet proven.

### Current Interpretation

- The NVR advertises ONVIF pull-point events.
- The event service is live and responds for capability queries.
- Actual subscription/property calls likely require a more exact ONVIF auth pattern than the simple HTTP Digest flow used here.
- Plausible next checks:
  - ONVIF WS-Security `UsernameToken`
  - testing with a dedicated ONVIF client library or tool
  - comparing behavior from an ONVIF Device Manager style client

## Notes for Project Setup

- Do not store live credentials in this repository.
- The working assumptions for implementation are:
  - stream access will likely come from RTSP and/or ONVIF
  - richer metadata, playback, and analytics may be available from the web API
  - the web API likely needs a more faithful browser-session emulation than plain `curl`
