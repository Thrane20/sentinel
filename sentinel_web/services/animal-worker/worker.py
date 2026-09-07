import json
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

DB_PATH = os.getenv("ANIMAL_DB_PATH", "/data/animals.db")
FRIGATE_URL = os.getenv("FRIGATE_URL", "http://frigate:5000").rstrip("/")
MQTT_HOST = os.getenv("MQTT_HOST", "mqtt")
PUBLIC_URL = os.getenv("SENTINEL_PUBLIC_URL", "http://localhost:3000").rstrip("/")
WEBHOOK_URL = os.getenv("HA_ANIMAL_WEBHOOK_URL", "")
IVSEC_HOST = os.getenv("IVSEC_HOST", "192.168.68.203")
IVSEC_USERNAME = os.getenv("IVSEC_USERNAME", "")
IVSEC_PASSWORD = os.getenv("IVSEC_PASSWORD", "")
IVSEC_HISTORY_DAYS = min(30, max(1, int(os.getenv("IVSEC_HISTORY_DAYS", "7"))))
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
        defaults = {
            "globalEnabled": True,
            "alertsEnabled": False,
            "cooldownSeconds": 120,
            "retentionDays": 30,
            "maxEvents": 5000,
            "ivsecClearedBefore": 0,
            "cameras": {
                data["id"]: {
                    "enabled": data["enabled"],
                    "threshold": 0.80,
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
            if item.get("threshold") == 0.70:
                item["threshold"] = 0.80
                changed = True
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


def update_settings(body):
    current = settings()
    if "globalEnabled" in body:
        current["globalEnabled"] = bool(body["globalEnabled"])
    if "alertsEnabled" in body:
        current["alertsEnabled"] = bool(body["alertsEnabled"])
    if "cameras" in body and isinstance(body["cameras"], dict):
        for camera_id, patch in body["cameras"].items():
            if camera_id not in current["cameras"] or not isinstance(patch, dict):
                continue
            item = current["cameras"][camera_id]
            if "enabled" in patch:
                item["enabled"] = bool(patch["enabled"])
            if "threshold" in patch:
                item["threshold"] = min(0.99, max(0.50, float(patch["threshold"])))
            if "minArea" in patch:
                item["minArea"] = min(0.25, max(0.0001, float(patch["minArea"])))
            if "maxArea" in patch:
                item["maxArea"] = min(0.99, max(0.001, float(patch["maxArea"])))
            if "minTravel" in patch:
                item["minTravel"] = min(0.25, max(0, float(patch["minTravel"])))
            if item.get("maxArea", 0.99) < item.get("minArea", 0.0001):
                item["maxArea"] = item["minArea"]
    with DB_LOCK, connect() as db:
        for key in ("globalEnabled", "alertsEnabled", "cameras"):
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


def normalize_box(box):
    if not isinstance(box, list) or len(box) != 4:
        return [0, 0, 0, 0]
    x1, y1, x2, y2 = (float(value) for value in box)
    if max(box) <= 1:
        return [round(x1, 5), round(y1, 5), round(x2 - x1, 5), round(y2 - y1, 5)]
    return [round(x1 / 640, 5), round(y1 / 360, 5), round((x2 - x1) / 640, 5), round((y2 - y1) / 360, 5)]


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
    return {
        "schemaVersion": 1,
        "type": "sentinel.animal.test" if test else "sentinel.animal.detected",
        "eventId": event_id,
        "camera": {"id": camera["id"], "name": camera["name"]},
        "observedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(row["started_at"])),
        "confidence": row["confidence"],
        "boundingBox": json.loads(row["box"]),
        "movement": row["travel"],
        "snapshotUrl": f"{PUBLIC_URL}/api/animals/events/{urllib.parse.quote(event_id)}/snapshot",
        "sentinelUrl": f"{PUBLIC_URL}/?tab=animals&event={urllib.parse.quote(event_id)}",
    }


def post_webhook(payload):
    if not WEBHOOK_URL:
        return False, "HA_ANIMAL_WEBHOOK_URL is not configured"
    request = urllib.request.Request(
        WEBHOOK_URL,
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
        confidence >= specific.get("threshold", 0.80)
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
        box = normalize_box((after.get("snapshot") or {}).get("box") or after.get("box"))
        has_snapshot = bool(after.get("has_snapshot"))
        now = time.time()
        with DB_LOCK, connect() as db:
            existed = db.execute("SELECT 1 FROM events WHERE id=?", (event_id,)).fetchone()
        if not has_snapshot and not existed:
            return
        metrics = event_track_metrics(event_id) if has_snapshot else None
        # A live track can qualify as soon as it has travelled far enough. If it
        # has not, wait for later MQTT updates or the final event path.
        if not existed:
            if metrics is None or not passes_camera_filter(slug, confidence, box, metrics[0]):
                if after.get("end_time") is not None:
                    print(f"Rejected stationary/filtered animal candidate {event_id}", flush=True)
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
    for alarm in alarm_list or []:
        source_time = str(alarm.get("time") or "")
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
                        "SELECT 1 FROM ivsec_events WHERE camera=? AND source_time=?",
                        (slug, source_time),
                    ).fetchone():
                        continue
                    result = db.execute(
                        """INSERT OR IGNORE INTO ivsec_events
                           (fingerprint,camera,camera_name,event_type,source_time,details,captured_at)
                           VALUES(?,?,?,?,?,?,?)""",
                        (fingerprint, slug, camera_name, event_type, source_time, detail, now),
                    )
                stored += result.rowcount
    return stored


def recorder_timestamp(date_value, time_value):
    value = f"{date_value} {time_value}"
    try:
        parsed = datetime.strptime(value, "%m/%d/%Y %H:%M:%S")
        return value, parsed.replace(tzinfo=timezone(timedelta(hours=10))).timestamp()
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
                db.execute(
                    "DELETE FROM ivsec_events WHERE camera=? AND source_time=?",
                    (slug, source_time),
                )
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
            "capturedAt": row["captured_at"],
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


def sync_ivsec_history(session, base, days):
    recorder_today = datetime.now(timezone(timedelta(hours=10))).date()
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


def clear_events():
    """Remove Sentinel event metadata and its corresponding Frigate events."""
    with DB_LOCK, connect() as db:
        event_ids = [row["id"] for row in db.execute("SELECT id FROM events").fetchall()]
        db.execute("DELETE FROM events")

    snapshots_deleted = 0
    snapshot_failures = 0
    for event_id in event_ids:
        request = urllib.request.Request(
            f"{FRIGATE_URL}/api/events/{urllib.parse.quote(event_id, safe='')}",
            method="DELETE",
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                if 200 <= response.status < 300:
                    snapshots_deleted += 1
                else:
                    snapshot_failures += 1
        except urllib.error.HTTPError as error:
            # A missing Frigate event is already in the requested cleared state.
            if error.code == 404:
                snapshots_deleted += 1
            else:
                snapshot_failures += 1
        except Exception:
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
        if self.path != "/settings":
            return self.send_json(404, {"error": "Not found"})
        try:
            return self.send_json(200, update_settings(self.read_json()))
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            return self.send_json(400, {"error": str(error)})

    def do_POST(self):
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
    global FRIGATE_ONLINE
    if message.topic == "frigate/available":
        FRIGATE_ONLINE = message.payload.decode(errors="replace") == "online"
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
    initialize()
    start_mqtt()
    threading.Thread(target=reconcile_existing_events, daemon=True).start()
    threading.Thread(target=cleanup, daemon=True).start()
    threading.Thread(target=ivsec_event_collector, daemon=True).start()
    threading.Thread(target=ivsec_history_collector, daemon=True).start()
    print("Sentinel animal worker listening on port 3101", flush=True)
    ThreadingHTTPServer(("0.0.0.0", 3101), Handler).serve_forever()
