import json
from cpu_monitor import CpuMonitor
import os
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import hashlib
import math
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import paho.mqtt.client as mqtt
import requests
from requests.auth import HTTPDigestAuth
from recorder_security import RecorderSecurity, RecorderSecurityError, StateChanged
from ivsec_notifications import IvsecNotifications, observed_at
from recorder_events import RecorderEvents, EVENTS

CPU_MONITOR = CpuMonitor()

DB_PATH = os.getenv("ANIMAL_DB_PATH", "/data/animals.db")
FRIGATE_URL = os.getenv("FRIGATE_URL", "http://frigate:5000").rstrip("/")
MQTT_HOST = os.getenv("MQTT_HOST", "mqtt")
PUBLIC_URL = os.getenv("SENTINEL_PUBLIC_URL", "http://localhost:3000").rstrip("/")
WEBHOOK_URL = os.getenv("HA_ANIMAL_WEBHOOK_URL", "")
IVSEC_WEBHOOK_URL = os.getenv("HA_IVSEC_WEBHOOK_URL", "")
IVSEC_HOST = os.getenv("IVSEC_HOST", "192.168.68.203")
IVSEC_USERNAME = os.getenv("IVSEC_USERNAME", "")
IVSEC_PASSWORD = os.getenv("IVSEC_PASSWORD", "")
IVSEC_HISTORY_DAYS = min(30, max(1, int(os.getenv("IVSEC_HISTORY_DAYS", "7"))))
RECORDER_TIMEZONE = timezone(timedelta(hours=10))
PLAYBACK_PREROLL_SECONDS = 5
PLAYBACK_DURATION_SECONDS = 30
MODEL_NAME = "MDV6-mit-yolov9-c"
CAMERAS = {
    "ch01": {"id": "01", "name": "Front Door", "enabled": True},
    "ch03": {"id": "03", "name": "Pool", "enabled": True},
    "ch04": {"id": "04", "name": "Garage", "enabled": True},
    "ch05": {"id": "05", "name": "Front Drive", "enabled": True},
    "ch06": {"id": "06", "name": "Backyard - Down", "enabled": True},
    "ch08": {"id": "08", "name": "Side Passage", "enabled": True},
    "ch02": {"id": "02", "name": "Backyard - Up", "enabled": False},
    "ch07": {"id": "07", "name": "Boat Shed", "enabled": False},
}
DB_LOCK = threading.RLock()
MQTT_CLIENT = None
MQTT_ONLINE = False
FRIGATE_ONLINE = False
IVSEC_EVENTS_ONLINE = False
IVSEC_EVENTS_ERROR = "Waiting for recorder"
IVSEC_EVENTS_LAST_POLL = None
SUPPRESSED_EVENT_IDS = set()
SUPPRESSED_LOCK = threading.RLock()


def connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    return db


def initialize():
    with DB_LOCK, connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
              id TEXT PRIMARY KEY,
              camera TEXT NOT NULL,
              started_at REAL NOT NULL,
              ended_at REAL,
              confidence REAL NOT NULL,
              box TEXT NOT NULL,
              has_snapshot INTEGER NOT NULL DEFAULT 0,
              alert_status TEXT NOT NULL DEFAULT 'shadow',
              alert_attempts INTEGER NOT NULL DEFAULT 0,
              alert_error TEXT,
              suppressed INTEGER NOT NULL DEFAULT 0,
              acknowledged_at REAL,
              travel REAL NOT NULL DEFAULT 0,
              path_points INTEGER NOT NULL DEFAULT 0,
              updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS animal_admissions (
              id TEXT PRIMARY KEY,
              camera TEXT NOT NULL,
              accepted_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS animal_admissions_camera_time
              ON animal_admissions(camera, accepted_at);
            CREATE INDEX IF NOT EXISTS events_started_idx ON events(started_at DESC);
            CREATE TABLE IF NOT EXISTS ivsec_events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              fingerprint TEXT NOT NULL UNIQUE,
              camera TEXT NOT NULL,
              camera_name TEXT NOT NULL,
              event_type TEXT NOT NULL,
              source_time TEXT NOT NULL,
              details TEXT NOT NULL,
              captured_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ivsec_events_captured_idx
              ON ivsec_events(captured_at DESC);
            """
        )
        IVSEC_NOTIFICATIONS.initialize(db)
        defaults = {
            "globalEnabled": True,
            "alertsEnabled": False,
            "cooldownSeconds": 120,
            "maxEventsPerHour": 20,
            "retentionDays": 30,
            "maxEvents": 5000,
            "ivsecClearedBefore": 0,
            "cameras": {
                data["id"]: {
                    "enabled": data["enabled"],
                    "threshold": 0.65,
                    "minArea": 0.007,
                    "maxArea": 0.10 if data["id"] == "05" else 0.99,
                    "minTravel": 0.02 if data["id"] == "06" else 0.04 if data["id"] == "05" else 0.03,
                }
                for data in CAMERAS.values()
            },
        }
        for key, value in defaults.items():
            db.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)",
                (key, json.dumps(value)),
            )
        columns = {row["name"] for row in db.execute("PRAGMA table_info(events)")}
        if "travel" not in columns:
            db.execute("ALTER TABLE events ADD COLUMN travel REAL NOT NULL DEFAULT 0")
        if "path_points" not in columns:
            db.execute("ALTER TABLE events ADD COLUMN path_points INTEGER NOT NULL DEFAULT 0")
        # Migrate untouched camera defaults while retaining deliberate per-camera tuning.
        camera_row = db.execute("SELECT value FROM settings WHERE key='cameras'").fetchone()
        saved_cameras = json.loads(camera_row["value"])
        changed = False
        for data in CAMERAS.values():
            camera_id = data["id"]
            item = saved_cameras.setdefault(camera_id, defaults["cameras"][camera_id].copy())
            if item.get("minArea") == 0.005:
                item["minArea"] = 0.007
                changed = True
            for key in ("maxArea", "minTravel"):
                if key not in item:
                    item[key] = defaults["cameras"][camera_id][key]
                    changed = True
        if changed:
            db.execute(
                "UPDATE settings SET value=? WHERE key='cameras'",
                (json.dumps(saved_cameras),),
            )
        # Connection status belongs in health, not in the playback alert history.
        db.execute(
            "DELETE FROM ivsec_events WHERE event_type IN ('Camera online','Camera offline')"
        )
        db.execute(
            """DELETE FROM ivsec_events
               WHERE id IN (
                 SELECT live.id
                 FROM ivsec_events AS live
                 JOIN ivsec_events AS archive
                   ON archive.camera=live.camera AND archive.source_time=live.source_time
                 WHERE archive.details LIKE '%\"record_id\"%'
                   AND live.details NOT LIKE '%\"record_id\"%'
               )"""
        )
        # Frigate publishes transient object tracks that may never become retained
        # events. They have no event-time image and should not appear as detections.
        db.execute("DELETE FROM events WHERE has_snapshot=0")


def settings():
    with DB_LOCK, connect() as db:
        return {row["key"]: json.loads(row["value"]) for row in db.execute("SELECT * FROM settings")}


CONFIDENCE_LOCK = threading.Lock()


def apply_frigate_filters(changes):
    """Apply object filters live; roll back earlier cameras if a later save fails."""
    try:
        with urllib.request.urlopen(f"{FRIGATE_URL}/api/config", timeout=3) as response:
            live = json.load(response)["cameras"]
    except Exception:
        raise ValueError("Frigate is unavailable. Object filter settings were not saved; retry when it is online.") from None
    applied = []

    def send(slug, filters):
        body = {
            "requires_restart": 0,
            "update_topic": f"config/cameras/{slug}/objects",
            "config_data": {"cameras": {slug: {"objects": {"filters": {"animal": filters}}}}},
        }
        request = urllib.request.Request(
            f"{FRIGATE_URL}/api/config/set", data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"}, method="PUT",
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            if not json.load(response).get("success"):
                raise ValueError("Frigate rejected the confidence setting")

    try:
        for camera_id, filters in changes.items():
            slug = f"ch{camera_id}"
            if slug not in live:
                continue
            old = live[slug]["objects"]["filters"]["animal"]
            previous = {key: old.get(key, [] if key == "mask" else None) for key in filters}
            applied.append((slug, previous))
            send(slug, filters)
    except Exception:
        rollback_failed = False
        for slug, previous in reversed(applied):
            try:
                send(slug, previous)
            except Exception:
                rollback_failed = True
        if rollback_failed:
            raise ValueError("Frigate update failed and some cameras could not be restored. Check Frigate before retrying.") from None
        raise ValueError("Frigate object filters could not be applied. Settings were not saved; check Frigate and retry.") from None


def apply_frigate_confidence(changes):
    return apply_frigate_filters({key: {"threshold": value, "min_score": min(0.50, value)}
                                  for key, value in changes.items()})


def validate_object_masks(masks):
    if not isinstance(masks, list) or len(masks) > 20:
        raise ValueError("Use at most 20 masks per camera")
    cleaned = []
    for mask in masks:
        if not isinstance(mask, str):
            raise ValueError("Each mask must be a coordinate polygon")
        try:
            values = [float(part) for part in mask.split(",")]
        except ValueError:
            raise ValueError("Invalid mask coordinates") from None
        if len(values) < 6 or len(values) > 128 or len(values) % 2:
            raise ValueError("Each mask needs 3 to 64 points")
        if any(not math.isfinite(v) or not 0 <= v <= 1 for v in values):
            raise ValueError("Mask coordinates must be between 0 and 1")
        points = list(zip(values[::2], values[1::2]))
        if len(set(points)) != len(points):
            raise ValueError("Mask points must be distinct")
        def cross(a, b, c):
            return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
        edges = list(zip(points, points[1:]+points[:1]))
        for i,(a,b) in enumerate(edges):
            for j,(c,d) in enumerate(edges):
                if j <= i + 1 or (i == 0 and j == len(edges)-1):
                    continue
                if cross(a,b,c)*cross(a,b,d) < 0 and cross(c,d,a)*cross(c,d,b) < 0:
                    raise ValueError("Mask edges must not cross")
        area = abs(sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(points, points[1:]+points[:1]))) / 2
        if area < 0.000001:
            raise ValueError("Mask must enclose an area")
        cleaned.append(",".join(f"{value:.6f}" for value in values))
    return cleaned


def camera_object_masks(camera_id):
    if f"ch{camera_id}" not in CAMERAS:
        raise ValueError("Unknown camera")
    try:
        with urllib.request.urlopen(f"{FRIGATE_URL}/api/config", timeout=3) as response:
            config = json.load(response)["cameras"][f"ch{camera_id}"]
        masks = config["objects"]["filters"]["animal"].get("mask") or []
        if isinstance(masks, str):
            masks = [masks]
        # Frigate's API exposes the original mask coordinates, including legacy pixels.
        normalized = []
        for mask in masks:
            values = [float(v) for v in mask.split(",")]
            if any(v > 1 for v in values):
                values = [v / config["detect"]["width" if i % 2 == 0 else "height"]
                          for i,v in enumerate(values)]
            normalized.append(",".join(str(v) for v in values))
        return {"masks": validate_object_masks(normalized)}
    except Exception:
        raise ValueError("Could not read camera masks from Frigate. Retry when it is online.") from None


def save_object_masks(camera_id, masks):
    masks = validate_object_masks(masks)
    with CONFIDENCE_LOCK:
        # Require the camera to exist in Frigate before changing its saved masks.
        camera_object_masks(camera_id)
        apply_frigate_filters({camera_id: {"mask": masks}})
        with DB_LOCK, connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key='cameras'").fetchone()
            cameras = json.loads(row["value"])
            cameras[camera_id]["objectMasks"] = masks
            db.execute("UPDATE settings SET value=? WHERE key='cameras'", (json.dumps(cameras),))
    return {"masks": masks}


DETECTION_PROFILES = {"360p": (640, 360), "720p": (1280, 720), "1080p": (1920, 1080)}


def detection_source(camera_id, stream):
    host = os.getenv("IVSEC_HOST", "192.168.68.203")
    if not all(c.isalnum() or c in ".-" for c in host):
        raise ValueError("Invalid recorder host")
    username, password = os.getenv("IVSEC_USERNAME"), os.getenv("IVSEC_PASSWORD")
    if not username or not password:
        raise ValueError("Recorder credentials are not configured")
    # Same raw RTSP construction as model-init: Frigate performs password escaping.
    return f"rtsp://{username}:{password}@{host}:554/ch{camera_id}/{stream}"


def detection_quality(camera_id):
    if f"ch{camera_id}" not in CAMERAS:
        raise ValueError("Unknown camera")
    try:
        with urllib.request.urlopen(f"{FRIGATE_URL}/api/config", timeout=3) as response:
            camera = json.load(response)["cameras"][f"ch{camera_id}"]
        detect = camera["detect"]
        profile = next((key for key, size in DETECTION_PROFILES.items()
                        if size == (detect["width"], detect["height"])), None)
        # Return source index only; recorder URLs and credentials never reach the browser.
        if len(camera["ffmpeg"]["inputs"]) != 1:
            raise ValueError("Custom multi-input camera configuration")
        input_index, detect_input = next((index, item) for index, item in enumerate(camera["ffmpeg"]["inputs"]) if "detect" in item["roles"])
        path = detect_input["path"]
        stream = path.rsplit("/", 1)[-1]
        return {"profile": profile, "fps": detect["fps"], "width": detect["width"],
                "height": detect["height"], "stream": stream, "inputIndex": input_index}
    except Exception:
        raise ValueError("Could not read detection quality from Frigate. Retry when it is online.") from None


def save_detection_quality(camera_id, body):
    profile, fps = body.get("profile"), body.get("fps")
    if not isinstance(profile, str) or profile not in DETECTION_PROFILES or type(fps) is not int or fps not in (2, 5):
        raise ValueError("Choose 360p, 720p or 1080p and 2 or 5 FPS")
    with CONFIDENCE_LOCK:
        previous = detection_quality(camera_id)
        if previous["stream"] not in ("0", "1", "2"):
            raise ValueError("This camera uses a custom stream. Update it in Frigate instead.")
        stream = os.getenv("IVSEC_SNAPSHOT_STREAM_INDEX", "2") if profile == "360p" else "0"
        if stream not in ("0", "1", "2"):
            raise ValueError("Invalid detection stream index")
        width, height = DETECTION_PROFILES[profile]
        def write_config(w, h, rate, source_stream):
            # Frigate 0.17.2 cannot update list-element paths through dotted keys.
            # Keep this generated stack's single input and its options intact.
            with urllib.request.urlopen(f"{FRIGATE_URL}/api/config", timeout=3) as response:
                inputs = json.load(response)["cameras"][f"ch{camera_id}"]["ffmpeg"]["inputs"]
            if len(inputs) != 1:
                raise ValueError("Custom multi-input camera configuration")
            inputs[0]["path"] = detection_source(camera_id, source_stream)
            data = {"cameras": {f"ch{camera_id}": {
                "detect": {"width": w, "height": h, "fps": rate},
                "ffmpeg": {"inputs": inputs},
            }}}
            request = urllib.request.Request(
                f"{FRIGATE_URL}/api/config/set", data=json.dumps({"requires_restart": 1, "config_data": data}).encode(),
                headers={"Content-Type": "application/json"}, method="PUT",
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                if not json.load(response).get("success"):
                    raise ValueError("Frigate rejected detection quality")
        try:
            write_config(width, height, fps, stream)
            with DB_LOCK, connect() as db:
                row = db.execute("SELECT value FROM settings WHERE key='cameras'").fetchone()
                cameras = json.loads(row["value"])
                cameras[camera_id]["detectionProfile"] = profile
                cameras[camera_id]["detectionFps"] = fps
                db.execute("UPDATE settings SET value=? WHERE key='cameras'", (json.dumps(cameras),))
        except Exception:
            try:
                write_config(previous["width"], previous["height"], previous["fps"], previous["stream"])
            except Exception:
                raise ValueError("Detection quality update failed and could not be restored. Check Frigate configuration before restarting.") from None
            raise ValueError("Detection quality could not be saved. Original configuration restored.") from None
        restarted = False
        try:
            request = urllib.request.Request(f"{FRIGATE_URL}/api/restart", method="POST")
            with urllib.request.urlopen(request, timeout=5) as response:
                restarted = bool(json.load(response).get("success"))
        except Exception:
            pass
        return {"profile": profile, "fps": fps, "width": width, "height": height,
                "stream": stream, "restartRequested": restarted,
                "message": "Saved. Frigate is restarting; allow up to a minute for detection and thumbnails to return."
                if restarted else "Saved, but automatic restart failed. Restart Frigate to apply these settings."}


def update_settings(body):
    with CONFIDENCE_LOCK:
        return _update_settings(body)


def _update_settings(body):
    current = settings()
    confidence_changes = {}
    if "globalEnabled" in body:
        current["globalEnabled"] = bool(body["globalEnabled"])
    if "alertsEnabled" in body:
        current["alertsEnabled"] = bool(body["alertsEnabled"])
    if "maxEventsPerHour" in body:
        value = float(body["maxEventsPerHour"])
        if not math.isfinite(value) or not value.is_integer() or not 0 <= value <= 10000:
            raise ValueError("Hourly limit must be a whole number from 0 to 10000")
        current["maxEventsPerHour"] = int(value)
    if "cameras" in body and isinstance(body["cameras"], dict):
        for camera_id, patch in body["cameras"].items():
            if camera_id not in current["cameras"] or not isinstance(patch, dict):
                continue
            item = current["cameras"][camera_id]
            if "enabled" in patch:
                item["enabled"] = bool(patch["enabled"])
            if "threshold" in patch:
                value = float(patch["threshold"])
                if not math.isfinite(value) or not 0.10 <= value <= 0.99:
                    raise ValueError("Confidence must be between 10% and 99%")
                item["threshold"] = value
                confidence_changes[camera_id] = value
            if "minArea" in patch:
                item["minArea"] = min(0.25, max(0.0001, float(patch["minArea"])))
            if "maxArea" in patch:
                item["maxArea"] = min(0.99, max(0.001, float(patch["maxArea"])))
            if "minTravel" in patch:
                item["minTravel"] = min(0.25, max(0, float(patch["minTravel"])))
            if item.get("maxArea", 0.99) < item.get("minArea", 0.0001):
                item["maxArea"] = item["minArea"]
    if confidence_changes:
        apply_frigate_confidence(confidence_changes)
    with DB_LOCK, connect() as db:
        for key in ("globalEnabled", "alertsEnabled", "maxEventsPerHour", "cameras"):
            db.execute("UPDATE settings SET value=? WHERE key=?", (json.dumps(current[key]), key))
    sync_detection(current)
    return current


def sync_detection(current=None):
    if not MQTT_CLIENT:
        return
    current = current or settings()
    for slug, data in CAMERAS.items():
        enabled = current["globalEnabled"] and current["cameras"][data["id"]]["enabled"]
        MQTT_CLIENT.publish(f"frigate/{slug}/detect/set", "ON" if enabled else "OFF", qos=1, retain=True)


FRAME_SIZE_LOCK = threading.Lock()
FRAME_SIZE_CACHE = {}
FRAME_SIZE_CHECKED = 0.0


def detection_frame_size(slug):
    global FRAME_SIZE_CHECKED
    with FRAME_SIZE_LOCK:
        if time.monotonic() - FRAME_SIZE_CHECKED > 5 or slug not in FRAME_SIZE_CACHE:
            try:
                with urllib.request.urlopen(f"{FRIGATE_URL}/api/config", timeout=3) as response:
                    cameras = json.load(response)["cameras"]
                FRAME_SIZE_CACHE.update({key: (item["detect"]["width"], item["detect"]["height"])
                                         for key, item in cameras.items()})
                FRAME_SIZE_CHECKED = time.monotonic()
            except Exception:
                pass
        if slug in FRAME_SIZE_CACHE:
            return FRAME_SIZE_CACHE[slug]
    profile = settings()["cameras"].get(camera_data(slug)["id"], {}).get("detectionProfile", "360p")
    return DETECTION_PROFILES.get(profile, (640, 360))


def normalize_box(box, slug=None):
    if not isinstance(box, list) or len(box) != 4:
        return [0, 0, 0, 0]
    x1, y1, x2, y2 = (float(value) for value in box)
    if max(box) <= 1:
        return [round(x1, 5), round(y1, 5), round(x2 - x1, 5), round(y2 - y1, 5)]
    width, height = detection_frame_size(slug) if slug else (640, 360)
    return [round(x1 / width, 5), round(y1 / height, 5), round((x2 - x1) / width, 5), round((y2 - y1) / height, 5)]


def camera_data(slug):
    return CAMERAS.get(slug, {"id": slug, "name": slug, "enabled": False})


def event_payload(row):
    camera = camera_data(row["camera"])
    return {
        "id": row["id"],
        "cameraId": camera["id"],
        "cameraName": camera["name"],
        "startedAt": row["started_at"],
        "endedAt": row["ended_at"],
        "confidence": row["confidence"],
        "boundingBox": json.loads(row["box"]),
        "travelPercent": row["travel"],
        "pathPoints": row["path_points"],
        "hasSnapshot": bool(row["has_snapshot"]),
        "snapshotUrl": f"/api/animals/events/{urllib.parse.quote(row['id'])}/snapshot",
        "alertStatus": row["alert_status"],
        "alertAttempts": row["alert_attempts"],
        "suppressed": bool(row["suppressed"]),
        "acknowledgedAt": row["acknowledged_at"],
    }


def alert_body(row, test=False):
    camera = camera_data(row["camera"])
    event_id = row["id"]
    playback_query = urllib.parse.urlencode({
        "tab": "animals", "event": event_id, "playback": "1",
        "camera": camera["id"], "at": int(row["started_at"]),
    })
    return {
        "schemaVersion": 1,
        "type": "sentinel.animal.test" if test else "sentinel.animal.detected",
        "eventId": event_id,
        "camera": {"id": camera["id"], "name": camera["name"]},
        "observedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(row["started_at"])),
        "confidence": row["confidence"],
        "boundingBox": json.loads(row["box"]),
        "movement": row["travel"],
        "snapshotUrl": f"{PUBLIC_URL}/api/animals/events/{urllib.parse.quote(event_id, safe='')}/snapshot",
        "sentinelUrl": f"{PUBLIC_URL}/?{urllib.parse.urlencode({'tab': 'animals', 'event': event_id})}",
        "playbackUrl": f"{PUBLIC_URL}/?{playback_query}",
    }


def post_webhook(payload, destination=None):
    destination = WEBHOOK_URL if destination is None else destination
    if not destination:
        return False, "HA_ANIMAL_WEBHOOK_URL is not configured"
    request = urllib.request.Request(
        destination,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "Sentinel/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            if 200 <= response.status < 300:
                return True, None
            return False, f"Home Assistant returned HTTP {response.status}"
    except Exception as error:
        return False, str(error)[:240]


IVSEC_NOTIFICATIONS = IvsecNotifications(connect, DB_LOCK, camera_data, PUBLIC_URL,
                                       lambda: bool(IVSEC_WEBHOOK_URL),
                                       lambda payload: post_webhook(payload, IVSEC_WEBHOOK_URL))


def wait_for_snapshot(event_id):
    deadline = time.time() + 5
    url = f"{FRIGATE_URL}/api/events/{urllib.parse.quote(event_id)}/snapshot.jpg"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    response.read(1)
                    return
        except Exception:
            time.sleep(0.5)


def deliver(event_id):
    wait_for_snapshot(event_id)
    delays = (0, 1, 5, 30)
    for attempt, delay in enumerate(delays, 1):
        if delay:
            time.sleep(delay)
        with DB_LOCK, connect() as db:
            row = db.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
        if not row:
            return
        ok, error = post_webhook(alert_body(row))
        with DB_LOCK, connect() as db:
            db.execute(
                "UPDATE events SET alert_status=?, alert_attempts=?, alert_error=?, updated_at=? WHERE id=?",
                ("sent" if ok else "retrying" if attempt < 4 else "failed", attempt, error, time.time(), event_id),
            )
        if ok:
            return


def event_track_metrics(event_id):
    url = f"{FRIGATE_URL}/api/events/{urllib.parse.quote(event_id)}"
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            details = json.load(response)
    except Exception:
        return None
    raw_path = ((details.get("data") or {}).get("path_data") or [])
    points = []
    for entry in raw_path:
        try:
            point = entry[0]
            x, y = float(point[0]), float(point[1])
            if math.isfinite(x) and math.isfinite(y):
                points.append((x, y))
        except (IndexError, TypeError, ValueError):
            continue
    if len(points) < 2:
        return 0.0, len(points)
    furthest = max(
        math.hypot(x1 - x2, y1 - y2)
        for index, (x1, y1) in enumerate(points)
        for x2, y2 in points[index + 1 :]
    )
    return min(1.0, furthest / math.sqrt(2)), len(points)


def passes_camera_filter(slug, confidence, box, travel):
    current = settings()
    camera = camera_data(slug)
    specific = current["cameras"].get(camera["id"], {})
    if not current["globalEnabled"] or not specific.get("enabled"):
        return False
    return matches_measurement_filter(specific, confidence, box, travel)


def matches_measurement_filter(specific, confidence, box, travel):
    area = max(0, box[2]) * max(0, box[3])
    return (
        confidence >= specific.get("threshold", 0.65)
        and area >= specific.get("minArea", 0.007)
        and area <= specific.get("maxArea", 0.99)
        and travel >= specific.get("minTravel", 0.03)
    )


def should_alert(slug, confidence, box, travel):
    current = settings()
    if not passes_camera_filter(slug, confidence, box, travel):
        return False, "filtered"
    if not current["alertsEnabled"]:
        return False, "shadow"
    cutoff = time.time() - current["cooldownSeconds"]
    with DB_LOCK, connect() as db:
        recent = db.execute(
            "SELECT 1 FROM events WHERE camera=? AND alert_status IN ('pending','retrying','sent') AND started_at>? LIMIT 1",
            (slug, cutoff),
        ).fetchone()
    return (False, "cooldown") if recent else (True, "pending")


def camera_event_in_cooldown(slug, event_id):
    cutoff = time.time() - settings()["cooldownSeconds"]
    with DB_LOCK, connect() as db:
        return bool(
            db.execute(
                "SELECT 1 FROM events WHERE camera=? AND id<>? AND started_at>? LIMIT 1",
                (slug, event_id, cutoff),
            ).fetchone()
        )


def admit_hourly_event(slug, event_id):
    """Reserve one rolling-hour slot, independently of event history clearing."""
    limit = settings()["maxEventsPerHour"]
    now = time.time()
    with DB_LOCK, connect() as db:
        db.execute("DELETE FROM animal_admissions WHERE accepted_at<=?", (now - 3600,))
        if db.execute("SELECT 1 FROM animal_admissions WHERE id=?", (event_id,)).fetchone():
            return True
        count = db.execute(
            "SELECT COUNT(*) FROM animal_admissions WHERE camera=?", (slug,)
        ).fetchone()[0]
        if limit and count >= limit:
            return False
        db.execute("INSERT INTO animal_admissions VALUES (?,?,?)", (event_id, slug, now))
        return True


def delete_frigate_event(event_id):
    request = urllib.request.Request(
        f"{FRIGATE_URL}/api/events/{urllib.parse.quote(event_id, safe='')}",
        method="DELETE",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return 200 <= response.status < 300
    except urllib.error.HTTPError as error:
        return error.code == 404
    except Exception:
        return False


def reconcile_existing_events():
    # Give Frigate time to start before enriching records created by older worker
    # versions. Rows are removed only when their Frigate metadata is reachable.
    time.sleep(10)
    with DB_LOCK, connect() as db:
        rows = db.execute("SELECT * FROM events").fetchall()
    current = settings()
    for row in rows:
        metrics = event_track_metrics(row["id"])
        if metrics is None:
            continue
        camera = camera_data(row["camera"])
        specific = current["cameras"].get(camera["id"], {})
        box = json.loads(row["box"])
        with DB_LOCK, connect() as db:
            if matches_measurement_filter(specific, row["confidence"], box, metrics[0]):
                db.execute(
                    "UPDATE events SET travel=?, path_points=?, updated_at=? WHERE id=?",
                    (metrics[0], metrics[1], time.time(), row["id"]),
                )
            else:
                db.execute("DELETE FROM events WHERE id=?", (row["id"],))


def handle_event(message):
    try:
        payload = json.loads(message)
        after = payload.get("after") or {}
        if after.get("label") != "animal" or after.get("false_positive"):
            return
        event_id = str(after["id"])
        slug = str(after["camera"])
        confidence = float(after.get("top_score") or after.get("score") or 0)
        box = normalize_box((after.get("snapshot") or {}).get("box") or after.get("box"), slug)
        has_snapshot = bool(after.get("has_snapshot"))
        ended = after.get("end_time") is not None
        now = time.time()
        with DB_LOCK, connect() as db:
            existed = db.execute("SELECT 1 FROM events WHERE id=?", (event_id,)).fetchone()
        with SUPPRESSED_LOCK:
            already_suppressed = event_id in SUPPRESSED_EVENT_IDS
        if already_suppressed:
            if ended:
                with SUPPRESSED_LOCK:
                    SUPPRESSED_EVENT_IDS.discard(event_id)
                threading.Thread(
                    target=delete_frigate_event, args=(event_id,), daemon=True
                ).start()
            return
        if not has_snapshot and not existed:
            return
        # Apply the camera cooldown to retained history as well as notifications.
        # This stops a noisy scene from creating hundreds of event cards and
        # snapshots while alerts are disabled in shadow mode.
        if not existed and camera_event_in_cooldown(slug, event_id):
            if ended:
                threading.Thread(
                    target=delete_frigate_event, args=(event_id,), daemon=True
                ).start()
            else:
                with SUPPRESSED_LOCK:
                    SUPPRESSED_EVENT_IDS.add(event_id)
            return
        metrics = event_track_metrics(event_id) if has_snapshot else None
        # A live track can qualify as soon as it has travelled far enough. If it
        # has not, wait for later MQTT updates or the final event path.
        if not existed:
            if metrics is None or not passes_camera_filter(slug, confidence, box, metrics[0]):
                if after.get("end_time") is not None:
                    print(f"Rejected stationary/filtered animal candidate {event_id}", flush=True)
                return
        if not existed and not admit_hourly_event(slug, event_id):
            if ended:
                threading.Thread(target=delete_frigate_event, args=(event_id,), daemon=True).start()
            else:
                with SUPPRESSED_LOCK:
                    SUPPRESSED_EVENT_IDS.add(event_id)
            return
        travel, path_points = metrics or (0.0, 0)
        with DB_LOCK, connect() as db:
            db.execute(
                """INSERT INTO events(id,camera,started_at,ended_at,confidence,box,has_snapshot,travel,path_points,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET ended_at=excluded.ended_at,
                     confidence=MAX(events.confidence,excluded.confidence), box=excluded.box,
                     has_snapshot=MAX(events.has_snapshot,excluded.has_snapshot),
                     travel=MAX(events.travel,excluded.travel), path_points=MAX(events.path_points,excluded.path_points),
                     updated_at=excluded.updated_at""",
                (event_id, slug, float(after.get("start_time") or now), after.get("end_time"), confidence, json.dumps(box), int(has_snapshot), travel, path_points, now),
            )
        if not existed:
            allowed, status = should_alert(slug, confidence, box, travel)
            with DB_LOCK, connect() as db:
                db.execute(
                    "UPDATE events SET alert_status=?, suppressed=? WHERE id=?",
                    (status, int(status in {"cooldown", "filtered"}), event_id),
                )
            if allowed:
                threading.Thread(target=deliver, args=(event_id,), daemon=True).start()
    except Exception as error:
        print(f"Unable to process Frigate event: {error}", flush=True)


def cleanup():
    while True:
        current = settings()
        cutoff = time.time() - current["retentionDays"] * 86400
        with DB_LOCK, connect() as db:
            db.execute("DELETE FROM events WHERE started_at < ?", (cutoff,))
            db.execute(
                "DELETE FROM events WHERE id IN (SELECT id FROM events ORDER BY started_at DESC LIMIT -1 OFFSET ?)",
                (current["maxEvents"],),
            )
            db.execute("DELETE FROM ivsec_events WHERE captured_at < ?", (cutoff,))
            db.execute(
                "DELETE FROM ivsec_events WHERE id IN (SELECT id FROM ivsec_events ORDER BY captured_at DESC LIMIT -1 OFFSET ?)",
                (current["maxEvents"],),
            )
        time.sleep(86400)


EVENT_LABELS = {
    "motion_alarm": "Motion",
    "io_alarm": "I/O alarm",
    "videoloss": "Video loss",
    "pir_alarm": "PIR",
    "sound_alarm": "Sound detection",
    "occlusion_alarm": "Camera occlusion",
}

INTELLIGENT_EVENT_LABELS = {
    "pid": "Perimeter intrusion",
    "lcd": "Line crossing",
    "fd": "Face detection",
    "pvd": "Person / vehicle detection",
    "intrusion": "Intrusion detection",
    "regionentrance": "Region entrance",
    "regionexiting": "Region exit",
}

RECORD_LABELS = {
    2: "Alarm recording",
    4: "Motion recording",
    8: "I/O alarm recording",
    16: "Perimeter alert",
    32: "Video analytics alert",
    64: "Scene-change alert",
    128: "Smart detection",
    256: "Sensor recording",
    512: "Perimeter-area alert",
    1024: "Object-count alert",
    2048: "Network interruption",
    65536: "PIR recording",
    131072: "Sound detection",
    1048576: "Camera occlusion",
    2097152: "Person detection",
}

# IVSEC's NVR record-type bitmask, excluding ordinary continuous recordings.
IVSEC_ALERT_RECORD_MASK = sum(RECORD_LABELS)


def readable_event_type(key):
    if key in EVENT_LABELS:
        return EVENT_LABELS[key]
    return key.replace("linkage_", "").replace("_alarm", "").replace("_", " ").strip().title()


def channel_event_types(channel):
    found = []
    ignored = {"channel", "channel_name", "camera_connect_status", "record_flag", "Floodlight_AudioAlarm"}
    for key, value in channel.items():
        if key in ignored:
            continue
        if value is True:
            found.append(readable_event_type(key))
        elif isinstance(value, dict) and ("alarm" in key.lower() or "intelligent" in key.lower()):
            if value.get("alarm_val") is True:
                subtype = str(value.get("int_subtype") or "").lower()
                found.append(INTELLIGENT_EVENT_LABELS.get(subtype, "Smart detection"))
                continue
            for nested_key, nested_value in value.items():
                if nested_value is True:
                    found.append(readable_event_type(nested_key))
    return list(dict.fromkeys(found))


def store_ivsec_alarms(alarm_list, sequence):
    stored = 0
    now = time.time()
    cleared_before = float(settings().get("ivsecClearedBefore", 0))
    for alarm in alarm_list or []:
        source_time = str(alarm.get("time") or "")
        source_timestamp = observed_at({"source_time": source_time})
        if source_timestamp is not None and source_timestamp <= cleared_before:
            continue
        for channel in alarm.get("channel_alarm") or []:
            raw_channel = str(channel.get("channel") or "")
            digits = "".join(char for char in raw_channel if char.isdigit())
            slug = f"ch{int(digits):02d}" if digits else raw_channel.lower()
            known = camera_data(slug)
            camera_name = str(channel.get("channel_name") or known["name"] or raw_channel)
            for event_type in channel_event_types(channel):
                detail = json.dumps(channel, sort_keys=True, separators=(",", ":"))
                material = f"{sequence}|{source_time}|{raw_channel}|{event_type}|{detail}"
                fingerprint = hashlib.sha256(material.encode()).hexdigest()
                with DB_LOCK, connect() as db:
                    if db.execute(
                        "SELECT 1 FROM ivsec_events WHERE camera=? AND source_time=? AND event_type=?",
                        (slug, source_time, event_type),
                    ).fetchone():
                        continue
                    result = db.execute(
                        """INSERT OR IGNORE INTO ivsec_events
                           (fingerprint,camera,camera_name,event_type,source_time,details,captured_at)
                           VALUES(?,?,?,?,?,?,?)""",
                        (fingerprint, slug, camera_name, event_type, source_time, detail, now),
                    )
                stored += result.rowcount
                if result.rowcount:
                    IVSEC_NOTIFICATIONS.enqueue(result.lastrowid)
    return stored


def recorder_timestamp(date_value, time_value):
    value = f"{date_value} {time_value}"
    try:
        parsed = datetime.strptime(value, "%m/%d/%Y %H:%M:%S")
        return value, parsed.replace(tzinfo=RECORDER_TIMEZONE).timestamp()
    except ValueError:
        return value, time.time()


def store_ivsec_records(record_groups):
    stored = 0
    cleared_before = float(settings().get("ivsecClearedBefore", 0))
    for group in record_groups or []:
        for record in group or []:
            record_type = int(record.get("record_type") or 0)
            if record_type not in RECORD_LABELS:
                continue
            raw_channel = str(record.get("channel") or "")
            digits = "".join(char for char in raw_channel if char.isdigit())
            slug = f"ch{int(digits):02d}" if digits else raw_channel.lower()
            known = camera_data(slug)
            source_time, captured_at = recorder_timestamp(
                str(record.get("start_date") or ""),
                str(record.get("start_time") or ""),
            )
            if captured_at <= cleared_before:
                continue
            detail = json.dumps(record, sort_keys=True, separators=(",", ":"))
            material = "|".join(
                (
                    "archive",
                    raw_channel,
                    source_time,
                    str(record_type),
                    str(record.get("record_id") or ""),
                    str(record.get("disk_event_id") or ""),
                )
            )
            fingerprint = hashlib.sha256(material.encode()).hexdigest()
            with DB_LOCK, connect() as db:
                if db.execute(
                    "SELECT 1 FROM ivsec_events WHERE fingerprint=?", (fingerprint,)
                ).fetchone():
                    continue
                if db.execute("SELECT 1 FROM ivsec_events WHERE camera=? AND source_time=? AND event_type=?", (slug, source_time, RECORD_LABELS[record_type])).fetchone():
                    continue
                result = db.execute(
                    """INSERT OR IGNORE INTO ivsec_events
                       (fingerprint,camera,camera_name,event_type,source_time,details,captured_at)
                       VALUES(?,?,?,?,?,?,?)""",
                    (
                        fingerprint,
                        slug,
                        known["name"],
                        RECORD_LABELS[record_type],
                        source_time,
                        detail,
                        captured_at,
                    ),
                )
            stored += result.rowcount
    return stored


def ivsec_events(limit=100):
    with DB_LOCK, connect() as db:
        rows = db.execute(
            "SELECT id,camera,camera_name,event_type,source_time,captured_at FROM ivsec_events ORDER BY captured_at DESC,id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "cameraId": camera_data(row["camera"])["id"],
            "cameraName": row["camera_name"],
            "eventType": row["event_type"],
            "sourceTime": row["source_time"],
            "capturedAt": observed_at(row) or row["captured_at"],
        }
        for row in rows
    ]


def clear_ivsec_events():
    with DB_LOCK, connect() as db:
        count = db.execute("SELECT COUNT(*) FROM ivsec_events").fetchone()[0]
        db.execute("DELETE FROM ivsec_events")
        db.execute(
            "INSERT OR REPLACE INTO settings(key,value) VALUES('ivsecClearedBefore',?)",
            (json.dumps(time.time()),),
        )
    return {"cleared": count}


def ivsec_event_health():
    return {
        "online": IVSEC_EVENTS_ONLINE,
        "configured": bool(IVSEC_USERNAME and IVSEC_PASSWORD),
        "lastPoll": IVSEC_EVENTS_LAST_POLL,
        "error": None if IVSEC_EVENTS_ONLINE else IVSEC_EVENTS_ERROR,
    }


def ivsec_session():
    base = f"http://{IVSEC_HOST}"
    session = requests.Session()
    session.auth = HTTPDigestAuth(IVSEC_USERNAME, IVSEC_PASSWORD)
    session.headers.update(
        {
            "Origin": base,
            "Referer": f"{base}/",
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent": "Sentinel/1.0",
            "Content-Type": "application/json",
        }
    )
    login = session.post(f"{base}/API/Web/Login", json={}, timeout=10)
    login.raise_for_status()
    token = login.headers.get("X-csrftoken")
    if not token or not session.cookies.get("session"):
        raise RuntimeError("Recorder login did not return a session")
    session.headers["X-csrftoken"] = token
    return base, session


RECORDER_SECURITY = RecorderSecurity(ivsec_session, lambda: bool(IVSEC_USERNAME and IVSEC_PASSWORD))
RECORDER_EVENTS = RecorderEvents(ivsec_session, lambda: bool(IVSEC_USERNAME and IVSEC_PASSWORD))


def ivsec_playback_params(camera_id, detected_at):
    """Build a short, read-only recorder download beginning before an event."""
    camera = next(
        (data for data in CAMERAS.values() if data["id"] == camera_id), None
    )
    if camera is None:
        raise ValueError("Unknown camera")
    timestamp = float(detected_at)
    start = datetime.fromtimestamp(
        timestamp - PLAYBACK_PREROLL_SECONDS, RECORDER_TIMEZONE
    )
    end = start + timedelta(seconds=PLAYBACK_DURATION_SECONDS)
    return {
        "start_time": start.strftime("%Y%m%d%H%M%S"),
        "end_time": end.strftime("%Y%m%d%H%M%S"),
        "channel": str(int(camera_id) - 1),
        "record_type": str(0xFFFFFFFF),
        "stream_type": "1",
        "record_id": "0",
        "disk_event_id": "0",
        "download_type": "1",
    }


def stream_ivsec_playback(handler, camera_id, detected_at):
    if not IVSEC_USERNAME or not IVSEC_PASSWORD:
        return handler.send_json(503, {"error": "IVSEC credentials are not configured"})
    try:
        timestamp = float(detected_at)
        if timestamp <= 0 or timestamp > time.time() + 60:
            raise ValueError("Invalid playback time")
        params = ivsec_playback_params(camera_id, timestamp)
    except (TypeError, ValueError, OverflowError):
        return handler.send_json(400, {"error": "Invalid camera or playback time"})

    try:
        base, session = ivsec_session()
        with session.post(
            f"{base}/download.mp4",
            params=params,
            stream=True,
            timeout=(10, 45),
        ) as response:
            if response.status_code != 200:
                try:
                    reason = response.json().get("reason") or response.json().get("error_code")
                except (ValueError, AttributeError):
                    reason = None
                status = 404 if reason == "no data" else 409 if reason == "playback_mutex" else 502
                message = (
                    "No recorder footage is available for that time"
                    if status == 404
                    else "The recorder is already serving another playback"
                    if status == 409
                    else "The recorder could not provide playback"
                )
                return handler.send_json(status, {"error": message})

            handler.send_response(200)
            handler.send_header("Content-Type", "video/mp4")
            handler.send_header("Cache-Control", "private, no-store, max-age=0")
            handler.end_headers()
            try:
                for chunk in response.iter_content(64 * 1024):
                    if chunk:
                        handler.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError, requests.RequestException):
                pass
    except requests.RequestException:
        return handler.send_json(502, {"error": "The recorder playback service is unavailable"})


def sync_ivsec_history(session, base, days):
    recorder_today = datetime.now(RECORDER_TIMEZONE).date()
    channels = [f"CH{data['id'].lstrip('0') or '0'}" for data in CAMERAS.values()]
    stored = 0
    for offset in range(days):
        day = (recorder_today - timedelta(days=offset)).strftime("%m/%d/%Y")
        payload = {
            "channel": channels,
            "start_date": day,
            "start_time": "00:00:00",
            "end_date": day,
            "end_time": "23:59:59",
            "stream_mode": "Mainstream",
            "record_type": IVSEC_ALERT_RECORD_MASK,
            "record_type_ex": [],
            "enable_smart_search": 0,
            "smart_region": [],
            "record_type_arr": [],
        }
        response = session.post(
            f"{base}/API/Playback/SearchRecord/Search",
            json={"version": "1.0", "data": payload},
            timeout=45,
        )
        response.raise_for_status()
        body = response.json()
        if body.get("result") != "success":
            raise RuntimeError("Recorder archive search failed")
        stored += store_ivsec_records((body.get("data") or {}).get("record"))
    return stored


def ivsec_history_collector():
    if not IVSEC_USERNAME or not IVSEC_PASSWORD:
        return
    first_run = True
    while True:
        try:
            base, session = ivsec_session()
            sync_ivsec_history(session, base, IVSEC_HISTORY_DAYS if first_run else 1)
            first_run = False
        except Exception as error:
            print(f"Unable to refresh IVSEC alert history: {str(error)[:180]}", flush=True)
        time.sleep(300)


def ivsec_event_collector():
    global IVSEC_EVENTS_ONLINE, IVSEC_EVENTS_ERROR, IVSEC_EVENTS_LAST_POLL
    if not IVSEC_USERNAME or not IVSEC_PASSWORD:
        IVSEC_EVENTS_ERROR = "IVSEC credentials are not configured"
        return

    while True:
        try:
            base, session = ivsec_session()

            subscribe = {
                "plus_eventchk": "eventAiPushPic",
                "ext_data": {"subscribe_type": [{"event": ["all"]}]},
            }
            baseline = session.post(
                f"{base}/API/Event/Check",
                json={"version": "1.0", "data": subscribe},
                timeout=15,
            )
            baseline.raise_for_status()
            data = baseline.json().get("data") or {}
            cursor = {key: data[key] for key in ("reader_id", "sequence", "lap_number")}
            IVSEC_EVENTS_ONLINE = True
            IVSEC_EVENTS_ERROR = ""
            IVSEC_EVENTS_LAST_POLL = time.time()

            while True:
                response = session.post(
                    f"{base}/API/Event/Check",
                    json={"version": "1.0", "data": cursor},
                    timeout=20,
                )
                response.raise_for_status()
                data = response.json().get("data") or {}
                if all(key in data for key in ("reader_id", "sequence", "lap_number")):
                    cursor = {key: data[key] for key in ("reader_id", "sequence", "lap_number")}
                store_ivsec_alarms(data.get("alarm_list"), cursor.get("sequence"))
                IVSEC_EVENTS_ONLINE = True
                IVSEC_EVENTS_ERROR = ""
                IVSEC_EVENTS_LAST_POLL = time.time()
                time.sleep(0.1)
        except Exception as error:
            IVSEC_EVENTS_ONLINE = False
            IVSEC_EVENTS_ERROR = str(error)[:180]
            time.sleep(5)


def reset_hourly_counts():
    """Release all hourly allowances without removing accepted events."""
    with DB_LOCK, connect() as db:
        count = db.execute("SELECT COUNT(*) FROM animal_admissions").fetchone()[0]
        db.execute("DELETE FROM animal_admissions")
    return {"reset": count}


def clear_events():
    """Remove animal history, reset hourly allowances, and delete snapshots."""
    with DB_LOCK, connect() as db:
        event_ids = [row["id"] for row in db.execute("SELECT id FROM events").fetchall()]
        db.execute("DELETE FROM events")
        db.execute("DELETE FROM animal_admissions")

    snapshots_deleted = 0
    snapshot_failures = 0
    for event_id in event_ids:
        if delete_frigate_event(event_id):
            snapshots_deleted += 1
        else:
            snapshot_failures += 1

    return {
        "cleared": len(event_ids),
        "frigateEventsDeleted": snapshots_deleted,
        "frigateDeleteFailures": snapshot_failures,
    }


def frigate_health():
    global FRIGATE_ONLINE
    try:
        with urllib.request.urlopen(f"{FRIGATE_URL}/api/stats", timeout=2) as response:
            stats = json.load(response)
        FRIGATE_ONLINE = True
        detector = next(iter((stats.get("detectors") or {}).values()), {})
        return {"online": True, "inferenceSpeedMs": detector.get("inference_speed")}
    except Exception:
        FRIGATE_ONLINE = False
        return {"online": False, "inferenceSpeedMs": None}


def health():
    detector = frigate_health()
    current = settings()
    return {
        "online": True,
        "mqttOnline": MQTT_ONLINE,
        "frigateOnline": detector["online"],
        "model": MODEL_NAME,
        "provider": os.getenv("FRIGATE_OPENVINO_DEVICE", "AUTO").upper(),
        "inferenceSpeedMs": detector["inferenceSpeedMs"],
        "alertsConfigured": bool(WEBHOOK_URL),
        "alertsEnabled": current["alertsEnabled"],
        "enabledCameras": sum(1 for item in current["cameras"].values() if item["enabled"]) if current["globalEnabled"] else 0,
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"worker http: {format % args}", flush=True)

    def send_json(self, status, data):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):
        if self.path == "/ivsec-remote/catalog":
            return self.send_json(200, {"events": [{"id": e[0], "label": e[1]} for e in EVENTS]})
        if self.path.startswith("/ivsec-remote?"):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            try:
                return self.send_json(200, RECORDER_EVENTS.read(*(query.get(k, [None])[0] for k in ("camera", "event", "section"))))
            except (ValueError, TypeError):
                return self.send_json(400, {"error": "Invalid recorder settings selection."})
            except Exception:
                return self.send_json(503, {"error": "IVSEC settings unavailable. Check camera connectivity and retry."})
        if self.path == "/ivsec-notification-rules":
            return self.send_json(200, IVSEC_NOTIFICATIONS.rules())
        if self.path.startswith("/ivsec-events/"):
            try:
                return self.send_json(200, IVSEC_NOTIFICATIONS.inspect(int(self.path.split("/")[-1])))
            except KeyError:
                return self.send_json(404, {"error": "Event was cleared or is no longer available."})
            except ValueError:
                return self.send_json(400, {"error": "Invalid event ID."})
        if self.path == "/ivsec-security":
            try:
                return self.send_json(200, RECORDER_SECURITY.read())
            except (RecorderSecurityError, requests.RequestException, ValueError, RuntimeError):
                return self.send_json(503, {"online": False, "armed": None, "disarming": None,
                                            "error": "IVSEC status unavailable. Check recorder connectivity and credentials."})
        if self.path == "/system/cpu":
            return self.send_json(200, CPU_MONITOR.payload())
        if self.path.startswith("/quality/"):
            try:
                return self.send_json(200, detection_quality(self.path.split("/")[-1]))
            except ValueError as error:
                return self.send_json(503, {"error": str(error)})
        if self.path.startswith("/masks/"):
            try:
                return self.send_json(200, camera_object_masks(self.path.split("/")[-1]))
            except ValueError as error:
                return self.send_json(503, {"error": str(error)})
        path = urllib.parse.urlparse(self.path)
        if path.path == "/health":
            return self.send_json(200, health())
        if path.path == "/settings":
            return self.send_json(200, settings())
        if path.path == "/ivsec-events":
            query = urllib.parse.parse_qs(path.query)
            limit = min(200, max(1, int(query.get("limit", [100])[0])))
            return self.send_json(
                200,
                {"events": ivsec_events(limit), "health": ivsec_event_health()},
            )
        if path.path == "/ivsec-playback":
            query = urllib.parse.parse_qs(path.query)
            return stream_ivsec_playback(
                self,
                query.get("camera", [""])[0],
                query.get("at", [""])[0],
            )
        if path.path == "/events":
            query = urllib.parse.parse_qs(path.query)
            limit = min(100, max(1, int(query.get("limit", [30])[0])))
            clauses, args = [], []
            if query.get("camera"):
                clauses.append("camera=?")
                camera_id = query["camera"][0]
                args.append(next((slug for slug, data in CAMERAS.items() if data["id"] == camera_id), camera_id))
            if query.get("before"):
                clauses.append("started_at<?")
                args.append(float(query["before"][0]))
            clauses.insert(0, "has_snapshot=1")
            where = f"WHERE {' AND '.join(clauses)}"
            with DB_LOCK, connect() as db:
                rows = db.execute(f"SELECT * FROM events {where} ORDER BY started_at DESC LIMIT ?", (*args, limit + 1)).fetchall()
            return self.send_json(200, {"events": [event_payload(row) for row in rows[:limit]], "nextBefore": rows[limit]["started_at"] if len(rows) > limit else None})
        if path.path.startswith("/events/"):
            event_id = urllib.parse.unquote(path.path[len("/events/"):])
            with DB_LOCK, connect() as db:
                row = db.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
            return self.send_json(200, event_payload(row)) if row else self.send_json(404, {"error": "Unknown event"})
        self.send_json(404, {"error": "Not found"})

    def do_PATCH(self):
        if self.path == "/ivsec-remote":
            try:
                return self.send_json(200, RECORDER_EVENTS.write(self.read_json()))
            except StateChanged as error:
                return self.send_json(409, {"error": str(error)})
            except (ValueError, TypeError, KeyError):
                return self.send_json(400, {"error": "Invalid or unsupported recorder settings. Reload and check the values."})
            except RecorderSecurityError as error:
                return self.send_json(503, {"error": str(error)})
            except Exception:
                return self.send_json(503, {"error": "IVSEC did not confirm this save. Reload this section before retrying."})
        if self.path == "/ivsec-security":
            try:
                body = self.read_json()
                if not isinstance(body, dict) or set(body) != {"disarming", "expectedDisarming"} or any(type(body[key]) is not bool for key in body):
                    raise ValueError("disarming and expectedDisarming must be booleans.")
            except (ValueError, TypeError):
                return self.send_json(400, {"error": "disarming and expectedDisarming must be booleans."})
            try:
                return self.send_json(200, RECORDER_SECURITY.write(body["disarming"], body["expectedDisarming"]))
            except StateChanged as error:
                return self.send_json(409, {"error": str(error)})
            except RecorderSecurityError as error:
                return self.send_json(503, {"error": str(error)})
            except (requests.RequestException, ValueError, RuntimeError):
                return self.send_json(503, {"error": "IVSEC did not confirm the change. Refresh its status before retrying."})
        if self.path != "/settings":
            return self.send_json(404, {"error": "Not found"})
        try:
            return self.send_json(200, update_settings(self.read_json()))
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            return self.send_json(400, {"error": str(error)})

    def do_POST(self):
        if self.path == "/ivsec-notification-rules":
            try:
                return self.send_json(200, IVSEC_NOTIFICATIONS.save(self.read_json()))
            except (ValueError, TypeError) as error:
                return self.send_json(400, {"error": str(error)})
        if self.path == "/ivsec-notification-test":
            try:
                body = self.read_json()
                if not IVSEC_WEBHOOK_URL:
                    raise ValueError("HA_IVSEC_WEBHOOK_URL is not configured.")
                return self.send_json(202, {"queued": IVSEC_NOTIFICATIONS.enqueue(int(body["eventId"]), str(body["ruleId"]))})
            except (ValueError, TypeError, KeyError) as error:
                return self.send_json(400, {"error": str(error)})
        if self.path.startswith("/quality/"):
            try:
                body = self.read_json()
                if not isinstance(body, dict):
                    raise ValueError("Invalid detection quality settings")
                return self.send_json(200, save_detection_quality(self.path.split("/")[-1], body))
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                return self.send_json(400, {"error": str(error)})
        if self.path.startswith("/masks/"):
            try:
                return self.send_json(200, save_object_masks(self.path.split("/")[-1], self.read_json().get("masks")))
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                return self.send_json(400, {"error": str(error)})
        if self.path == "/hourly-counts/reset":
            return self.send_json(200, reset_hourly_counts())
        if self.path.startswith("/events/") and self.path.endswith("/acknowledge"):
            event_id = urllib.parse.unquote(self.path[len("/events/"):-len("/acknowledge")].rstrip("/"))
            with DB_LOCK, connect() as db:
                result = db.execute("UPDATE events SET acknowledged_at=? WHERE id=?", (time.time(), event_id))
            return self.send_json(200, {"acknowledged": True}) if result.rowcount else self.send_json(404, {"error": "Unknown event"})
        if self.path == "/test-alert":
            row = {"id": "test", "camera": "ch01", "started_at": time.time(), "confidence": 0.99, "box": json.dumps([0.25, 0.25, 0.5, 0.5])}
            ok, error = post_webhook(alert_body(row, test=True))
            return self.send_json(200 if ok else 503, {"sent": ok, "error": error})
        self.send_json(404, {"error": "Not found"})

    def do_DELETE(self):
        if self.path.startswith("/ivsec-notification-rules/"):
            IVSEC_NOTIFICATIONS.delete(urllib.parse.unquote(self.path.split("/")[-1]))
            return self.send_json(200, {"deleted": True})
        if self.path == "/events":
            return self.send_json(200, clear_events())
        if self.path == "/ivsec-events":
            return self.send_json(200, clear_ivsec_events())
        self.send_json(404, {"error": "Not found"})


def on_connect(client, userdata, flags, reason_code, properties):
    global MQTT_ONLINE
    MQTT_ONLINE = reason_code == 0
    if MQTT_ONLINE:
        client.subscribe("frigate/events", qos=1)
        client.subscribe("frigate/available", qos=1)
        sync_detection()


def on_disconnect(client, userdata, disconnect_flags, reason_code, properties):
    global MQTT_ONLINE
    MQTT_ONLINE = False


def on_message(client, userdata, message):
    global FRIGATE_ONLINE, FRAME_SIZE_CHECKED
    if message.topic == "frigate/available":
        FRIGATE_ONLINE = message.payload.decode(errors="replace") == "online"
        if FRIGATE_ONLINE:
            with FRAME_SIZE_LOCK:
                FRAME_SIZE_CACHE.clear()
                FRAME_SIZE_CHECKED = 0.0
    elif message.topic == "frigate/events":
        handle_event(message.payload)


def start_mqtt():
    global MQTT_CLIENT
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="sentinel-animal-worker")
    MQTT_CLIENT = client
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    client.connect_async(MQTT_HOST, 1883, keepalive=30)
    client.loop_start()


if __name__ == "__main__":
    CPU_MONITOR.start()
    initialize()
    start_mqtt()
    threading.Thread(target=reconcile_existing_events, daemon=True).start()
    threading.Thread(target=cleanup, daemon=True).start()
    threading.Thread(target=ivsec_event_collector, daemon=True).start()
    threading.Thread(target=ivsec_history_collector, daemon=True).start()
    threading.Thread(target=IVSEC_NOTIFICATIONS.run, daemon=True).start()
    print("Sentinel animal worker listening on port 3101", flush=True)
    ThreadingHTTPServer(("0.0.0.0", 3101), Handler).serve_forever()
