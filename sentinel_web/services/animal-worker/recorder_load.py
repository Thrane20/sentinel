"""Read-only watch on how hard Sentinel leans on the IVSEC recorder.

The recorder has a fixed network streaming budget (SystemInfo/Network
"bandwidth": total vs used). When stale or duplicated connections pile up,
"used" climbs until the recorder refuses new streams. This samples that budget
alongside what Sentinel itself holds open (go2rtc recorder connections and
worker web logins) so a climb can be attributed, or ruled out as ours.

It never closes anything: the recorder exposes no session list to reap.
"""
from collections import deque
import json
import re
import threading
import time
import urllib.request

KBPS = re.compile(r"^\s*(\d+)\s*Kbps\s*$", re.IGNORECASE)
# go2rtc only adds these once a producer has actually connected to its source.
CONNECTED_PRODUCER_KEYS = ("remote_addr", "bytes_recv", "receivers", "medias")


def parse_kbps(value):
    match = KBPS.match(value) if isinstance(value, str) else None
    return int(match.group(1)) if match else None


def recorder_bandwidth(body):
    if not isinstance(body, dict) or body.get("result") != "success":
        raise ValueError("Recorder network status was not successful")
    bandwidth = (body.get("data") or {}).get("bandwidth") or {}
    used, total = parse_kbps(bandwidth.get("used_bandwidth")), parse_kbps(bandwidth.get("total_bandwidth"))
    if used is None or not total:
        raise ValueError("Recorder did not report bandwidth")
    return used, total


def go2rtc_connections(streams):
    """Count recorder connections go2rtc holds and the clients reading them.
    Source URLs carry recorder credentials, so only counts and names leave here."""
    if not isinstance(streams, dict):
        raise ValueError("Unexpected go2rtc stream list")
    active, consumers = [], 0
    for name, stream in streams.items():
        stream = stream if isinstance(stream, dict) else {}
        producers = [p for p in stream.get("producers") or [] if isinstance(p, dict)]
        if any(any(p.get(key) for key in CONNECTED_PRODUCER_KEYS) for p in producers):
            active.append(str(name))
        consumers += len([c for c in stream.get("consumers") or [] if isinstance(c, dict)])
    return sorted(active), consumers


class RecorderLoadMonitor:
    interval = 60
    history_samples = 24 * 60
    log_every = 10
    warn_percent = 85
    # Event collector, history collector, security, settings, this monitor.
    expected_sessions = 5

    def __init__(self, open_session, close_session, configured, frigate_url, worker_stats,
                 fetch_json=None, clock=time.time):
        self.open_session, self.close_session = open_session, close_session
        self.configured, self.frigate_url = configured, frigate_url.rstrip("/")
        self.worker_stats, self.clock = worker_stats, clock
        self.fetch_json = fetch_json or self._fetch_json
        self.lock = threading.Lock()
        self.samples = deque(maxlen=self.history_samples)
        self.base = self.session = None
        self.recorder_error = self.frigate_error = None
        self.sampled = 0
        self.last_warnings = ()

    @staticmethod
    def _fetch_json(url):
        with urllib.request.urlopen(url, timeout=5) as response:
            return json.load(response)

    def _recorder(self):
        if not self.configured():
            raise RuntimeError("Recorder credentials are not configured")
        # One long-lived login, renewed only after a failure, rather than a
        # fresh login every minute.
        if self.session is None:
            self.base, self.session = self.open_session()
        response = self.session.post(f"{self.base}/API/SystemInfo/Network/Get",
                                     json={"version": "1.0", "data": {}}, timeout=10)
        response.raise_for_status()
        return recorder_bandwidth(response.json())

    def sample(self):
        point = {"at": self.clock(), "usedKbps": None, "totalKbps": None,
                 "recorderStreams": None, "streamNames": [], "viewers": None}
        try:
            point["usedKbps"], point["totalKbps"] = self._recorder()
            self.recorder_error = None
        except Exception as error:
            self.recorder_error = str(error)[:180] or "Recorder unavailable"
            self.close_session(self.base, self.session)
            self.base = self.session = None
        try:
            names, viewers = go2rtc_connections(self.fetch_json(f"{self.frigate_url}/api/go2rtc/streams"))
            point.update(recorderStreams=len(names), streamNames=names, viewers=viewers)
            self.frigate_error = None
        except Exception as error:
            self.frigate_error = str(error)[:180] or "go2rtc unavailable"
        point.update(self.worker_stats())
        with self.lock:
            self.samples.append(point)
            self.sampled += 1
            payload = self._payload()
        self._log(point, payload["warnings"])
        return point

    def _log(self, point, warnings):
        changed = tuple(warnings) != self.last_warnings
        self.last_warnings = tuple(warnings)
        if self.sampled % self.log_every != 1 and not changed:
            return
        used, total = point["usedKbps"], point["totalKbps"]
        budget = f"{used}/{total} Kbps ({round(100 * used / total)}%)" if used is not None else "unavailable"
        print(f"recorder load: bandwidth {budget}; go2rtc recorder streams {point['recorderStreams']}; "
              f"viewers {point['viewers']}; worker logins open {point.get('workerSessions')}; "
              f"event checks/min {point.get('eventChecksPerMinute')}"
              + (f"; WARN {' | '.join(warnings)}" if warnings else ""), flush=True)

    def _payload(self):
        samples = list(self.samples)
        latest = samples[-1] if samples else None
        with_bw = [s for s in samples if s["usedKbps"] is not None]
        hour_ago = next((s for s in with_bw if latest and s["at"] >= latest["at"] - 3600), None)
        current = with_bw[-1] if with_bw else None
        warnings = []
        if current and 100 * current["usedKbps"] / current["totalKbps"] >= self.warn_percent:
            warnings.append(f"Recorder streaming budget is {round(100 * current['usedKbps'] / current['totalKbps'])}% used")
        if current and hour_ago and hour_ago is not current:
            grew = current["usedKbps"] - hour_ago["usedKbps"]
            same_streams = current["recorderStreams"] is not None and current["recorderStreams"] <= (hour_ago["recorderStreams"] or 0)
            if grew >= 8192 and same_streams:
                warnings.append(f"Recorder bandwidth rose {round(grew / 1024)} Mbps in the last hour without new Sentinel streams")
        if latest and (latest.get("workerSessions") or 0) > self.expected_sessions:
            warnings.append(f"Worker holds {latest['workerSessions']} recorder logins (expected at most {self.expected_sessions})")
        return {
            "configured": bool(self.configured()),
            "latest": latest,
            "peakUsedKbps": max((s["usedKbps"] for s in with_bw), default=None),
            "hourChangeKbps": current["usedKbps"] - hour_ago["usedKbps"] if current and hour_ago else None,
            "history": [{"at": s["at"], "usedKbps": s["usedKbps"], "recorderStreams": s["recorderStreams"]} for s in samples],
            "sampleIntervalSeconds": self.interval,
            "recorderError": self.recorder_error,
            "frigateError": self.frigate_error,
            "warnings": warnings,
        }

    def payload(self):
        with self.lock:
            return self._payload()

    def start(self):
        def run():
            while True:
                try:
                    self.sample()
                except Exception as error:  # never let the sampler thread die
                    print(f"recorder load sample failed: {str(error)[:180]}", flush=True)
                time.sleep(self.interval)
        threading.Thread(target=run, name="recorder-load", daemon=True).start()
