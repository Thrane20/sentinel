"""Durable camera/event routing for live IVSEC events; no historical replay."""
import hashlib
import json
import re
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

RECORDER_TZ = timezone(timedelta(hours=10))


def event_key(label):
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")


def observed_at(row):
    try:
        return datetime.strptime(row["source_time"], "%m/%d/%Y %H:%M:%S").replace(tzinfo=RECORDER_TZ).timestamp()
    except (ValueError, TypeError):
        return None


def redact(value):
    if isinstance(value, dict):
        return {key: "[redacted]" if any(word in key.lower() for word in ("password", "token", "secret", "cookie", "authorization", "session")) else redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return re.sub(r"(\w+://)[^/@\s]+:[^/@\s]+@", r"\1[redacted]@", value)
    return value


class IvsecNotifications:
    def __init__(self, connect, lock, cameras, public_url, webhook_configured, send):
        self.connect, self.lock, self.cameras = connect, lock, cameras
        self.public_url = public_url.rstrip("/")
        self.webhook_configured, self.send = webhook_configured, send

    def initialize(self, db):
        db.executescript('''
          CREATE TABLE IF NOT EXISTS ivsec_notification_rules(id TEXT PRIMARY KEY, config TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS ivsec_notification_outbox(
            id TEXT PRIMARY KEY, rule_id TEXT NOT NULL, event_id INTEGER NOT NULL,
            payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0, error TEXT, created_at REAL NOT NULL,
            next_attempt REAL NOT NULL, expires_at REAL NOT NULL);
          CREATE INDEX IF NOT EXISTS ivsec_outbox_due ON ivsec_notification_outbox(status,next_attempt);
        ''')

    def rules(self):
        with self.lock, self.connect() as db:
            rules = [json.loads(row[0]) for row in db.execute("SELECT config FROM ivsec_notification_rules ORDER BY id")]
            catalog = [dict(row) for row in db.execute("SELECT DISTINCT camera,event_type FROM ivsec_events ORDER BY camera,event_type")]
        return {"rules": rules, "webhookConfigured": self.webhook_configured(),
                "catalog": [{"cameraId": self.cameras(row["camera"])["id"], "eventKey": event_key(row["event_type"]), "eventType": row["event_type"]} for row in catalog]}

    def save(self, body):
        if not isinstance(body, dict) or set(body) != {"id", "cameraId", "eventKey", "message", "enabled", "cooldownSeconds"}:
            raise ValueError("Provide a notification ID, camera, event key, message, enabled flag and cooldown.")
        for key in ("id", "eventKey"):
            if not isinstance(body[key], str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", body[key]):
                raise ValueError("Notification IDs and event keys must start with a lowercase letter and contain only lowercase letters, numbers or underscores (up to 64 characters).")
        if not isinstance(body["cameraId"], str) or body["cameraId"] not in {self.cameras(f"ch{number:02d}")["id"] for number in range(1, 9)}:
            raise ValueError("Unknown camera.")
        if not isinstance(body["message"], str) or not body["message"].strip() or len(body["message"]) > 240:
            raise ValueError("Enter a message of 1–240 characters.")
        if type(body["enabled"]) is not bool or type(body["cooldownSeconds"]) is not int or not 0 <= body["cooldownSeconds"] <= 86400:
            raise ValueError("Enabled must be a boolean and cooldown a whole number from 0 to 86400 seconds.")
        with self.lock, self.connect() as db:
            old = db.execute("SELECT config FROM ivsec_notification_rules WHERE id=?", (body["id"],)).fetchone()
            if not old and db.execute("SELECT COUNT(*) FROM ivsec_notification_rules").fetchone()[0] >= 100:
                raise ValueError("At most 100 notification rules can be saved.")
            rule = {**body, "message": body["message"].strip(), "createdAt": json.loads(old[0])["createdAt"] if old else time.time()}
            db.execute("INSERT OR REPLACE INTO ivsec_notification_rules VALUES(?,?)", (rule["id"], json.dumps(rule)))
            # Pending deliveries retain their original message/match. Changing a
            # rule cancels them so outdated policy cannot fire after editing it.
            db.execute("UPDATE ivsec_notification_outbox SET status='cancelled' WHERE rule_id=? AND status='pending'", (rule["id"],))
        return rule

    def delete(self, rule_id):
        with self.lock, self.connect() as db:
            db.execute("DELETE FROM ivsec_notification_rules WHERE id=?", (rule_id,))
            db.execute("UPDATE ivsec_notification_outbox SET status='cancelled' WHERE rule_id=? AND status='pending'", (rule_id,))

    def inspect(self, event_id):
        with self.lock, self.connect() as db:
            row = db.execute("SELECT * FROM ivsec_events WHERE id=?", (event_id,)).fetchone()
            deliveries = [dict(item) for item in db.execute("SELECT rule_id,status,attempts,error FROM ivsec_notification_outbox WHERE event_id=? ORDER BY created_at DESC", (event_id,))]
        if row is None:
            raise KeyError("Event was cleared or is no longer available.")
        timestamp = observed_at(row)
        camera = self.cameras(row["camera"])
        raw = json.loads(row["details"])
        return {"id": row["id"], "cameraId": camera["id"], "cameraName": row["camera_name"],
                "eventType": row["event_type"], "eventKey": event_key(row["event_type"]),
                "sourceTime": row["source_time"], "observedAt": timestamp,
                "collectedAt": row["captured_at"], "source": "archive" if "record_type" in raw else "live",
                "raw": redact(raw), "deliveries": deliveries}

    def enqueue(self, event_id, test_rule=None):
        try:
            event = self.inspect(event_id)
        except KeyError:
            if test_rule:
                raise
            return 0  # The user may clear history while a live event is stored.
        now = time.time()
        if event["observedAt"] is None:
            if test_rule:
                raise ValueError("This event has no reliable recorder time; choose another event.")
            return 0
        if not test_rule and (not self.webhook_configured() or event["source"] != "live" or not -60 <= now - event["observedAt"] <= 120):
            return 0
        count = 0
        with self.lock, self.connect() as db:
            rows = db.execute("SELECT config FROM ivsec_notification_rules").fetchall()
            for saved in rows:
                rule = json.loads(saved[0])
                if test_rule and rule["id"] != test_rule:
                    continue
                if rule["cameraId"] != event["cameraId"] or rule["eventKey"] != event["eventKey"]:
                    continue
                if not test_rule and (not rule["enabled"] or event["observedAt"] < rule["createdAt"]):
                    continue
                if not test_rule:
                    last = db.execute("SELECT MAX(created_at) FROM ivsec_notification_outbox WHERE rule_id=? AND json_extract(payload,'$.isTest')=0", (rule["id"],)).fetchone()[0]
                    if last is not None and now - last < rule["cooldownSeconds"]:
                        continue
                key = f"{rule['id']}|{event['cameraId']}|{event['sourceTime']}|{event['eventKey']}"
                if test_rule:
                    key += f"|test|{time.time_ns()}"
                delivery_id = "ivsec_" + hashlib.sha256(key.encode()).hexdigest()[:32]
                playback = self.public_url + "/?" + urllib.parse.urlencode({"tab": "playback", "ivsecEvent": event_id, "playback": "1", "camera": event["cameraId"], "at": int(event["observedAt"])})
                payload = {"schemaVersion": 1, "type": "sentinel.ivsec.test" if test_rule else "sentinel.ivsec.matched",
                           "isTest": bool(test_rule), "notificationId": rule["id"], "eventId": delivery_id,
                           "recorderEventId": event_id, "eventKey": event["eventKey"], "eventType": event["eventType"],
                           "camera": {"id": event["cameraId"], "name": event["cameraName"]}, "message": rule["message"],
                           "observedAt": datetime.fromtimestamp(event["observedAt"], timezone.utc).isoformat(),
                           "sentinelUrl": self.public_url + "/?" + urllib.parse.urlencode({"tab": "playback", "ivsecEvent": event_id}),
                           "playbackUrl": playback}
                count += db.execute("INSERT OR IGNORE INTO ivsec_notification_outbox(id,rule_id,event_id,payload,created_at,next_attempt,expires_at) VALUES(?,?,?,?,?,?,?)", (delivery_id, rule["id"], event_id, json.dumps(payload), now, now, now + 300)).rowcount
        if test_rule and not count:
            raise ValueError("Save a rule matching this camera and event key before sending its test.")
        return count

    def drain(self):
        now = time.time()
        with self.lock, self.connect() as db:
            db.execute("UPDATE ivsec_notification_outbox SET status='expired' WHERE status='pending' AND expires_at<?", (now,))
            rows = db.execute("SELECT * FROM ivsec_notification_outbox WHERE status='pending' AND next_attempt<=? LIMIT 10", (now,)).fetchall()
        for row in rows:
            with self.lock, self.connect() as db:
                if row["expires_at"] < time.time():
                    db.execute("UPDATE ivsec_notification_outbox SET status='expired' WHERE id=? AND status='pending'", (row["id"],))
                    continue
                rule = db.execute("SELECT config FROM ivsec_notification_rules WHERE id=?", (row["rule_id"],)).fetchone()
                current = db.execute("SELECT status FROM ivsec_notification_outbox WHERE id=?", (row["id"],)).fetchone()
                payload = json.loads(row["payload"])
                if not current or current[0] != "pending" or not rule or (not payload["isTest"] and not json.loads(rule[0])["enabled"]):
                    continue
            ok, error = self.send(payload)
            attempts = row["attempts"] + 1
            status = "sent" if ok else "failed" if attempts >= 4 else "pending"
            with self.lock, self.connect() as db:
                db.execute("UPDATE ivsec_notification_outbox SET status=?,attempts=?,error=?,next_attempt=? WHERE id=? AND status='pending'", (status, attempts, None if ok else "Home Assistant delivery failed. Check the webhook and connectivity.", time.time() + (1, 5, 30, 30)[min(attempts - 1, 3)], row["id"]))
        with self.lock, self.connect() as db:
            db.execute("DELETE FROM ivsec_notification_outbox WHERE created_at<? AND status!='pending'", (now - 30 * 86400,))

    def run(self):
        while True:
            try:
                self.drain()
            except Exception:
                print("IVSEC notification delivery paused after an error; retrying.", flush=True)
            time.sleep(2)
