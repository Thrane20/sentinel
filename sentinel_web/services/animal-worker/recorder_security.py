"""Read and update the recorder's global disarming flag without changing its policy."""

import copy
import threading
import time


class RecorderSecurityError(RuntimeError):
    pass


class StateChanged(RecorderSecurityError):
    pass


class RecorderSecurity:
    def __init__(self, session_factory, configured):
        self.session_factory = session_factory
        self.configured = configured
        self.lock = threading.Lock()
        self.cached = None
        self.session = None
        self.base = None

    def _open(self):
        if not self.configured():
            raise RecorderSecurityError("Recorder credentials are not configured.")
        if self.session is not None:
            return self.base, self.session
        base, session = self.session_factory()
        # This recorder marks its session cookie Secure even on its HTTP LAN
        # listener. Keep the adjustment local to this authenticated session.
        if base.startswith("http://"):
            for cookie in session.cookies:
                cookie.secure = False
        self.base, self.session = base, session
        return base, session

    def _invalidate_session(self):
        if self.session is not None:
            self.session.close()
        self.session = None
        self.base = None
        self.cached = None

    def _request(self, base, session, action, body):
        response = session.post(base + "/API/AlarmConfig/Disarming/" + action,
                                json=body, timeout=8, allow_redirects=False)
        response.raise_for_status()
        result = response.json()
        if result.get("result") != "success":
            raise RecorderSecurityError("Recorder rejected the disarming request.")
        return result.get("data")

    def _get(self, base, session):
        data = self._request(base, session, "Get", {})
        if not isinstance(data, dict) or type(data.get("disarming")) is not bool:
            raise RecorderSecurityError("Recorder did not report a valid disarming flag.")
        return data

    def _state(self, data):
        self.cached = {"online": True, "disarming": data["disarming"],
                       "armed": not data["disarming"], "checkedAt": time.time(),
                       "channelCount": len(data.get("disarming_channel", []))}
        return dict(self.cached)

    def read(self):
        with self.lock:
            if self.cached and time.time() - self.cached["checkedAt"] < 5:
                return dict(self.cached)
            self.cached = None
            base, session = self._open()
            try:
                return self._state(self._get(base, session))
            except Exception:
                self._invalidate_session()
                raise

    def write(self, disarming, expected):
        if type(disarming) is not bool or type(expected) is not bool:
            raise ValueError("disarming and expectedDisarming must be booleans.")
        with self.lock:
            self.cached = None
            base, session = self._open()
            try:
                data = self._get(base, session)
                if data["disarming"] == disarming:
                    return self._state(data)
                if data["disarming"] != expected:
                    raise StateChanged("IVSEC state changed. Refresh its status and retry.")
                updated = copy.deepcopy(data)
                updated["disarming"] = disarming
                self._request(base, session, "Set", {"version": "1.0", "data": updated})
                confirmed = self._get(base, session)
                if confirmed["disarming"] != disarming:
                    raise RecorderSecurityError("Recorder did not confirm the requested state. Refresh its status before retrying.")
                return self._state(confirmed)
            except Exception:
                self._invalidate_session()
                raise
