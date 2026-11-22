import unittest
from unittest.mock import MagicMock

from recorder_load import RecorderLoadMonitor, go2rtc_connections, parse_kbps, recorder_bandwidth

NETWORK = {"result": "success", "data": {"bandwidth": {"total_bandwidth": "114688Kbps", "used_bandwidth": "47616Kbps"}}}
# Shape returned by Frigate's /api/go2rtc/streams: idle streams list only their
# source URL; connected ones gain connection details.
STREAMS = {
    "ch01_2": {"producers": [{"url": "rtsp://user:secret@nvr/ch01/2", "remote_addr": "recorder.local:554", "bytes_recv": 10}],
               "consumers": [{"remote_addr": "frigate"}, {"remote_addr": "sentinel"}]},
    "ch03_2": {"producers": [{"url": "rtsp://user:secret@nvr/ch03/2", "medias": ["video"]}], "consumers": None},
    "ch01_0": {"producers": [{"url": "rtsp://user:secret@nvr/ch01/0"}], "consumers": None},
}


def monitor(bodies, streams=STREAMS, stats=None, clock=None):
    session = MagicMock()
    responses = []
    for body in bodies:
        response = MagicMock()
        response.json.return_value = body
        responses.append(response)
    session.post.side_effect = responses
    opened, closed = [], []
    def open_session():
        opened.append(1)
        return "http://nvr", session
    load = RecorderLoadMonitor(open_session, lambda base, s: closed.append(s), lambda: True, "http://frigate:5000",
                               lambda: dict(stats or {"workerSessions": 3, "eventChecksPerMinute": 6}),
                               fetch_json=lambda url: streams, clock=clock or (lambda: 1000.0))
    load._log = lambda point, warnings: None
    return load, session, opened, closed


class RecorderLoadTests(unittest.TestCase):
    def test_parses_recorder_bandwidth_budget(self):
        self.assertEqual(parse_kbps("47616Kbps"), 47616)
        self.assertIsNone(parse_kbps("lots"))
        self.assertEqual(recorder_bandwidth(NETWORK), (47616, 114688))
        with self.assertRaises(ValueError):
            recorder_bandwidth({"result": "success", "data": {}})
        with self.assertRaises(ValueError):
            recorder_bandwidth({"error_code": "no_login"})

    def test_counts_only_connected_go2rtc_streams_and_never_exposes_urls(self):
        names, viewers = go2rtc_connections(STREAMS)
        self.assertEqual(names, ["ch01_2", "ch03_2"])
        self.assertEqual(viewers, 2)
        load, *_ = monitor([NETWORK])
        load.sample()
        self.assertNotIn("secret", repr(load.payload()))

    def test_sample_reuses_one_login_and_renews_after_failure(self):
        load, session, opened, closed = monitor([NETWORK, NETWORK, {"error_code": "no_login"}, NETWORK])
        for _ in range(4):
            load.sample()
        self.assertEqual(len(opened), 2)
        self.assertEqual(len(closed), 1)
        payload = load.payload()
        self.assertIsNone(payload["recorderError"])
        self.assertEqual(payload["latest"]["usedKbps"], 47616)
        self.assertEqual(payload["latest"]["recorderStreams"], 2)
        self.assertEqual(payload["latest"]["workerSessions"], 3)
        self.assertEqual(payload["warnings"], [])

    def test_warns_on_high_budget_unexplained_climb_and_excess_logins(self):
        now = [0.0]
        low = {"result": "success", "data": {"bandwidth": {"total_bandwidth": "100000Kbps", "used_bandwidth": "40000Kbps"}}}
        high = {"result": "success", "data": {"bandwidth": {"total_bandwidth": "100000Kbps", "used_bandwidth": "90000Kbps"}}}
        load, *_ = monitor([low, high], stats={"workerSessions": 9}, clock=lambda: now[0])
        load.sample()
        now[0] = 3000.0
        load.sample()
        warnings = load.payload()["warnings"]
        self.assertEqual(len(warnings), 3)
        self.assertIn("90% used", warnings[0])
        self.assertIn("without new Sentinel streams", warnings[1])
        self.assertIn("9 recorder logins", warnings[2])
        self.assertEqual(load.payload()["hourChangeKbps"], 50000)

    def test_frigate_outage_still_records_recorder_budget(self):
        load, *_ = monitor([NETWORK])
        load.fetch_json = MagicMock(side_effect=OSError("connection refused"))
        point = load.sample()
        self.assertEqual(point["usedKbps"], 47616)
        self.assertIsNone(point["recorderStreams"])
        self.assertIn("connection refused", load.payload()["frigateError"])


if __name__ == "__main__":
    unittest.main()
