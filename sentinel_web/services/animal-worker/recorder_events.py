"""Capability-driven IVSEC configuration. Only allowlisted fields on one channel
are editable; every save rereads, merges, and verifies the recorder response.
"""
import copy
import hashlib
import json
import re

import requests

from recorder_security import RecorderSecurity, RecorderSecurityError, StateChanged

# Names and API identifiers from the recorder's own remote-settings client.
EVENTS = [
    ("Motion", "Motion", "AlarmConfig/Motion"),
    ("PID", "Perimeter intrusion", "AI/Setup/PID"),
    ("LCD", "Line crossing", "AI/Setup/LCD"),
    ("PVD", "Human / vehicle detection", "AI/Setup/PVD"),
    ("Intrusion", "Intrusion", "AI/Setup/Intrusion"),
    ("RegionEntrance", "Region entrance", "AI/Setup/RegionEntrance"),
    ("RegionExiting", "Region exit", "AI/Setup/RegionExiting"),
    ("FD", "Face detection", "AI/Setup/FD"),
    ("SOD", "Stationary object", "AI/Setup/SOD"),
    ("CC", "Cross counting", "AI/Setup/CrossCount"),
    ("CD", "Crowd density", "AI/Setup/CD"),
    ("QD", "Queue detection", "AI/Setup/QD"),
    ("RSD", "Rare sound detection", "AI/Setup/RSD"),
    ("VT", "Video tampering / occlusion", "AlarmConfig/Intelligent/OcclusionDetection"),
    ("Sound", "Sound detection", "AlarmConfig/Intelligent/SoundDetection"),
    ("PIR", "PIR detection", "AlarmConfig/PIR"),
    ("IO", "Alarm input", "AlarmConfig/IO"),
    ("Sabotage", "Sabotage detection", "AlarmConfig/Sabotage"),
    ("LPD", "Licence plate detection", "AI/Setup/LPD"),
    ("VQA", "Video quality analysis", "AI/Setup/VQA"),
    ("LD", "Littering detection", "AI/Setup/LD"),
]
FIELDS = {
    "detection": {
        "switch": "Detection enabled", "schedule_enable": "Detection schedule enabled",
        "sensitivity": "Sensitivity", "camera_smd": "Motion target",
        "detection_type": "Detection targets", "time_threshold": "Dwell time (seconds)",
        "iva_lines": "Show detection lines",
    },
    "actions": {
        "http_listening": "HTTP event notification", "record_enable": "Record on event",
        "record_channel": "Recording channels", "post_recording": "Post recording (seconds)",
        "show_message": "Recorder popup", "send_email": "Email notification",
        "full_screen": "Full screen", "buzzer": "Recorder buzzer (seconds; 0 = off)",
        "alarm_out": "Alarm relay outputs", "latch_time": "Relay duration (seconds)",
        "ftp_picture_upload": "FTP snapshot", "ftp_video_upload": "FTP video",
        "picture_to_cloud": "Cloud snapshot", "video_to_cloud": "Cloud video",
    },
    "light": {
        "flood_light_switch": "Light / strobe enabled", "bright_time": "Light duration (seconds)",
        "flood_light_mode": "Light mode", "strobe_frequency": "Strobe frequency",
        "enforcer_light_switch": "Warning light enabled",
        "enforcer_bright_time": "Warning light duration (seconds)",
    },
    "siren": {
        "siren_switch": "Siren enabled", "siren_time": "Siren duration (seconds)",
        "siren_value": "Siren volume", "siren_type": "Siren sound",
    },
}
OUTPUTS = {"lightSchedule": "FloodLight", "warningSchedule": "EnforcerLight", "sirenSchedule": "Siren"}
DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]


def revision(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate_value(value, schema):
    kind = schema.get("type")
    if kind == "bool":
        valid = type(value) is bool
    elif kind in ("int16", "int32", "uint32"):
        valid = type(value) is int and schema.get("min", -2**31) <= value <= schema.get("max", 2**31)
    elif kind == "string":
        valid = isinstance(value, str) and len(value) <= 200
    elif kind == "array":
        options = schema.get("items", {}).get("items", []) if isinstance(schema.get("items"), dict) else []
        valid = (isinstance(value, list) and len(value) == len(set(str(v) for v in value))
                 and schema.get("min_size", 0) <= len(value) <= schema.get("max_size", 32)
                 and all(v in options and type(v) is str for v in value))
    else:
        valid = False
    if not valid or (kind != "array" and isinstance(schema.get("items"), list) and value not in schema["items"]):
        raise ValueError("A setting is outside the recorder's supported values.")


def valid_week(week):
    return (isinstance(week, list) and len(week) == 7
            and all(isinstance(d, dict) and set(d) == {"day", "time"} for d in week)
            and {d["day"] for d in week} == set(DAYS)
            and all(isinstance(d["time"], list) and len(d["time"]) == 48
                    and all(type(v) is int and v in (0, 1) for v in d["time"]) for d in week))


class RecorderEvents(RecorderSecurity):
    def _identity(self, camera, event, section):
        if not isinstance(camera, str) or not re.fullmatch(r"(?:0?[1-9]|1[0-6])", camera):
            raise ValueError("Choose a recorder camera from 01 to 16.")
        match = next((e for e in EVENTS if e[0] == event), None)
        if match is None or section not in {*FIELDS, *OUTPUTS}:
            raise ValueError("Unknown recorder event or settings section.")
        query = {"channel": [f"CH{int(camera)}"]}
        if section in ("detection", "actions"):
            path = match[2]
            query["page_type"] = "ChannelConfig" if section == "detection" else "AlarmConfig"
        elif section in OUTPUTS:
            path = "AlarmConfig/Schedule"
            query["page_type"] = OUTPUTS[section]
        else:
            path = "AlarmConfig/Deterrence" if section == "light" else "AlarmConfig/VoiceAlarm"
        return path, query, query["channel"][0]

    def _call(self, base, session, path, action, data):
        # IVSEC reports expired/replaced web sessions as HTTP 400 as well as
        # 401/403. Renew only after an explicit authentication rejection. Never
        # replay a Set after a timeout or an ambiguous transport failure.
        auth_codes = {"no_login", "expired", "one_IE", "logout", "login_at_other"}
        for attempt in range(2):
            active = self.session if self.session is not None else session
            response = active.post(base + "/API/" + path + "/" + action,
                                   json={"version": "1.0", "data": data}, timeout=12, allow_redirects=False)
            try:
                result = response.json()
            except ValueError:
                result = {}
            code = result.get("error_code") if isinstance(result, dict) else None
            auth_rejected = response.status_code in (401, 403) or code in auth_codes
            if auth_rejected and attempt == 0:
                response.close()
                self._invalidate_session()
                base, session = self._open()
                continue
            if auth_rejected:
                raise RecorderSecurityError("IVSEC rejected the recorder login. Check credentials and reload this section.")
            if not response.ok:
                print(f"IVSEC settings {action} {path}: HTTP {response.status_code}", flush=True)
                raise RecorderSecurityError(f"IVSEC rejected the settings request (HTTP {response.status_code}). Reload this section before retrying.")
            if not isinstance(result, dict) or result.get("result") != "success" or not isinstance(result.get("data", {}), dict):
                raise RecorderSecurityError("IVSEC rejected this settings request. Refresh before retrying.")
            return result.get("data", {})

    def _fetch(self, base, session, path, query, channel):
        ranges = self._call(base, session, path, "Range", query)
        data = self._call(base, session, path, "Get", query)
        config = data.get("channel_info", {}).get(channel, {})
        schema = ranges.get("channel_info", {}).get("items", {}).get(channel, {}).get("items", {})
        if not isinstance(config, dict) or not isinstance(schema, dict):
            raise RecorderSecurityError("IVSEC returned an unexpected configuration format.")
        return data, config, schema

    def _payload(self, data, config, schema, event, section):
        reason = config.get("reason")
        if config.get("status") in ("Offline", "Nonsupport"):
            reason = "Camera is offline or does not support these settings."
        fields = []
        for key, label in FIELDS.get(section, {}).items():
            spec = schema.get(key)
            if key in config and isinstance(spec, dict) and spec.get("mode") != "r":
                if spec.get("type") == "array" and not isinstance(spec.get("items"), dict):
                    continue
                disabled = ((section == "light" and config.get("flood_light_disable") and key.startswith(("flood_", "bright_", "strobe_")))
                            or (section == "light" and config.get("warning_light_disable") and key.startswith("enforcer_")))
                fields.append({"key": key, "label": label, "value": config[key], "schema": spec, "disabled": bool(disabled)})
        schedule = None
        if section in OUTPUTS:
            entries = config.get("time_schedule", [])
            entry = next((e for e in entries if e.get("schedule_type") == event), None)
            spec = schema.get("time_schedule", {}).get("items", [{}])[0]
            if (entry and type(entry.get("switch")) is bool and valid_week(entry.get("week"))
                    and event in spec.get("schedule_type", {}).get("items", [])
                    and spec.get("switch", {}).get("type") == "bool"):
                schedule = {"enabled": entry["switch"], "week": entry["week"]}
        supported = not reason and bool(fields or schedule)
        return {"supported": bool(supported), "reason": reason or (None if supported else "Not supported by this camera / event."),
                "revision": revision(data), "fields": fields if supported else [], "schedule": schedule if supported else None}

    def read(self, camera, event, section):
        path, query, channel = self._identity(camera, event, section)
        with self.lock:
            base, session = self._open()
            try:
                data, config, schema = self._fetch(base, session, path, query, channel)
                return self._payload(data, config, schema, event, section)
            except Exception:
                self._invalidate_session()
                raise

    def write(self, body):
        if not isinstance(body, dict) or set(body) != {"camera", "event", "section", "revision", "values"}:
            raise ValueError("Invalid recorder settings request.")
        camera, event, section = (body[k] for k in ("camera", "event", "section"))
        path, query, channel = self._identity(camera, event, section)
        if not isinstance(body["revision"], str) or not isinstance(body["values"], dict) or not body["values"]:
            raise ValueError("Load the settings and choose a change before saving.")
        with self.lock:
            # The editor may have been open longer than the recorder login.
            # Authenticate before the reread/compare/write transaction.
            self._invalidate_session()
            base, session = self._open()
            try:
                data, config, schema = self._fetch(base, session, path, query, channel)
                current = self._payload(data, config, schema, event, section)
                if not current["supported"]:
                    raise ValueError(current["reason"])
                if body["revision"] != current["revision"]:
                    raise StateChanged("These IVSEC settings changed elsewhere. Reload this section before saving.")
                updated = copy.deepcopy(data)
                # Never send another channel, even if firmware ignored the Get filter.
                updated["channel_info"] = {channel: copy.deepcopy(config)}
                target = updated["channel_info"][channel]
                if section in OUTPUTS:
                    values = body["values"]
                    if (set(values) != {"enabled", "week"} or type(values["enabled"]) is not bool
                            or not valid_week(values["week"])):
                        raise ValueError("Schedules require seven days of 48 half-hour on/off slots.")
                    entry = next(e for e in target["time_schedule"] if e["schedule_type"] == event)
                    entry["switch"] = values["enabled"]
                    entry["week"] = copy.deepcopy(values["week"])
                else:
                    editable = {f["key"]: f for f in current["fields"] if not f["disabled"]}
                    for key, value in body["values"].items():
                        if key not in editable:
                            raise ValueError("This setting cannot be edited for this camera.")
                        validate_value(value, editable[key]["schema"])
                        target[key] = value
                if "page_type" in query:
                    updated["page_type"] = query["page_type"]
                self._call(base, session, path, "Set", updated)
                actual, confirmed, actual_schema = self._fetch(base, session, path, query, channel)
                result = self._payload(actual, confirmed, actual_schema, event, section)
                if section in OUTPUTS:
                    matches = result["schedule"] == body["values"]
                else:
                    matches = all(type(confirmed.get(k)) is type(v) and confirmed.get(k) == v for k, v in body["values"].items())
                if not matches:
                    raise RecorderSecurityError("IVSEC did not confirm every requested value. Reload this section to see the recorder's current settings.")
                return result
            except Exception:
                self._invalidate_session()
                raise
