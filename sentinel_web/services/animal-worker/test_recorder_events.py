import copy
import unittest
from unittest.mock import Mock
import requests
from recorder_events import RecorderEvents, revision, DAYS, validate_value
from recorder_security import StateChanged, RecorderSecurityError


def week(value=1):
    return [{"day": day, "time": [value] * 48} for day in DAYS]


class FakeRecorder(RecorderEvents):
    def __init__(self):
        super().__init__(lambda: ("http://recorder", None), lambda: True)
        self.data = {"channel_info": {"CH4": {"switch": True, "sensitivity": 2,
            "rule_info": {"polygon": [1, 2, 3]}, "unknown": "keep"}}}
        self.schema = {"switch": {"type": "bool"}, "sensitivity": {"type": "int32", "items": [1, 2, 3, 4]}}
        self.calls = []
        self.reject_readback = False

    def _open(self):
        return "http://recorder", None

    def _call(self, base, session, path, action, data):
        self.calls.append((path, action, copy.deepcopy(data)))
        if action == "Range":
            return {"channel_info": {"items": {"CH4": {"items": self.schema}}}}
        if action == "Get":
            return copy.deepcopy(self.data)
        if not self.reject_readback:
            self.data = copy.deepcopy(data)
            self.data.pop("page_type", None)
        return {}

    def body(self, section="detection", values=None, event="PID"):
        return {"camera": "04", "event": event, "section": section,
                "revision": self.read("04", event, section)["revision"], "values": values or {"switch": False}}


class RecorderEventsTests(unittest.TestCase):
    def auth_recorder(self):
        old, fresh = Mock(), Mock()
        old.cookies = fresh.cookies = []
        factory = Mock(return_value=("http://recorder", fresh))
        r = RecorderEvents(factory, lambda: True)
        r.base, r.session = "http://recorder", old
        return r, old, fresh, factory

    def response(self, status=200, data=None):
        response = Mock()
        response.status_code = status
        response.ok = 200 <= status < 300
        response.json.return_value = data if data is not None else {"result": "success", "data": {}}
        return response

    def test_expired_http400_session_renews_once_and_followup_uses_new_token(self):
        r, old, fresh, factory = self.auth_recorder()
        old.post.return_value = self.response(400, {"error_code": "one_IE"})
        fresh.post.return_value = self.response()
        r._call("http://recorder", old, "AlarmConfig/Schedule", "Get", {})
        # Caller still holds its original reference; subsequent requests must
        # use the renewed session, including Set and readback.
        r._call("http://recorder", old, "AlarmConfig/Schedule", "Get", {})
        self.assertEqual(old.post.call_count, 1)
        self.assertEqual(fresh.post.call_count, 2)
        factory.assert_called_once()
        old.close.assert_called_once()

    def test_definitively_rejected_set_can_reauthenticate_once(self):
        r, old, fresh, factory = self.auth_recorder()
        old.post.return_value = self.response(400, {"error_code": "expired"})
        fresh.post.return_value = self.response()
        r._call("http://recorder", old, "AlarmConfig/Schedule", "Set", {"example": True})
        self.assertEqual(old.post.call_args.kwargs["json"], fresh.post.call_args.kwargs["json"])
        factory.assert_called_once()

    def test_ambiguous_set_timeout_is_never_replayed(self):
        r, old, fresh, factory = self.auth_recorder()
        old.post.side_effect = requests.Timeout()
        with self.assertRaises(requests.Timeout):
            r._call("http://recorder", old, "AlarmConfig/Schedule", "Set", {})
        factory.assert_not_called()
        fresh.post.assert_not_called()

    def test_other_http400_is_reported_without_reauthentication(self):
        r, old, fresh, factory = self.auth_recorder()
        old.post.return_value = self.response(400, {"error_code": "invalid_parameter"})
        with self.assertRaisesRegex(RecorderSecurityError, "HTTP 400"):
            r._call("http://recorder", old, "AlarmConfig/Schedule", "Set", {})
        factory.assert_not_called()
        fresh.post.assert_not_called()

    def test_repeated_login_rejection_is_bounded(self):
        r, old, fresh, factory = self.auth_recorder()
        old.post.return_value = self.response(401)
        fresh.post.return_value = self.response(403)
        with self.assertRaisesRegex(RecorderSecurityError, "recorder login"):
            r._call("http://recorder", old, "AlarmConfig/Schedule", "Get", {})
        self.assertEqual(fresh.post.call_count, 1)
        factory.assert_called_once()

    def test_pid_mapping_preserves_zones_and_unknown_values(self):
        r = FakeRecorder()
        result = r.write(r.body(values={"sensitivity": 4}))
        self.assertTrue(result["supported"])
        written = next(c for c in r.calls if c[1] == "Set")
        self.assertEqual(written[0], "AI/Setup/PID")
        self.assertEqual(written[2]["page_type"], "ChannelConfig")
        self.assertEqual(r.data["channel_info"]["CH4"]["rule_info"], {"polygon": [1, 2, 3]})
        self.assertEqual(r.data["channel_info"]["CH4"]["unknown"], "keep")

    def test_stale_save_never_sets(self):
        r = FakeRecorder(); body = r.body()
        r.data["channel_info"]["CH4"]["unknown"] = "changed externally"
        with self.assertRaises(StateChanged): r.write(body)
        self.assertFalse(any(c[1] == "Set" for c in r.calls))

    def test_validation_blocks_raw_fields_and_invalid_numeric_boolean(self):
        for values in ({"rule_info": {}}, {"sensitivity": 5}, {"switch": 1}, {"sensitivity": True}, {"switch": False, "new_field": True}):
            r = FakeRecorder()
            with self.assertRaises(ValueError): r.write(r.body(values=values))
            self.assertFalse(any(c[1] == "Set" for c in r.calls))

    def test_readback_mismatch_is_failure(self):
        r = FakeRecorder(); r.reject_readback = True
        with self.assertRaises(RecorderSecurityError): r.write(r.body())

    def test_only_selected_channel_is_sent(self):
        r = FakeRecorder(); r.data["channel_info"]["CH5"] = {"switch": False}
        r.write(r.body())
        written = next(c for c in r.calls if c[1] == "Set")
        self.assertEqual(set(written[2]["channel_info"]), {"CH4"})

    def test_unsupported_or_offline_cannot_be_written(self):
        for config in ({"reason": "Not configured"}, {"status": "Offline", "switch": True}):
            r = FakeRecorder(); r.data["channel_info"]["CH4"] = config
            self.assertFalse(r.read("04", "PID", "detection")["supported"])
            with self.assertRaises(ValueError): r.write(r.body())

    def schedule_recorder(self):
        r = FakeRecorder()
        r.data = {"page_type": "Siren", "channel_info": {"CH4": {"time_schedule": [
            {"schedule_type": "PID", "switch": True, "week": week(), "vendor": "keep"},
            {"schedule_type": "Motion", "switch": False, "week": week(0)}]}}}
        r.schema = {"time_schedule": {"items": [{"schedule_type": {"items": ["PID", "Motion"]}, "switch": {"type": "bool"}}]}}
        return r

    def test_schedule_preserves_other_events_and_sends_correct_output(self):
        r = self.schedule_recorder(); original = copy.deepcopy(r.data)
        values = {"enabled": False, "week": week(0)}
        r.write(r.body("sirenSchedule", values))
        written = next(c for c in r.calls if c[1] == "Set")[2]
        self.assertEqual(written["page_type"], "Siren")
        entries = written["channel_info"]["CH4"]["time_schedule"]
        self.assertEqual(entries[1], original["channel_info"]["CH4"]["time_schedule"][1])
        self.assertEqual(entries[0]["vendor"], "keep")
        self.assertFalse(entries[0]["switch"])
        self.assertEqual(entries[0]["week"], week(0))

    def test_malformed_schedule_rejected_before_write(self):
        for change in (lambda w: w.pop(), lambda w: w[0]["time"].pop(), lambda w: w[0]["time"].__setitem__(0, True), lambda w: w[0].__setitem__("day", "Mon")):
            r = self.schedule_recorder(); w = week(); change(w)
            with self.assertRaises(ValueError): r.write(r.body("sirenSchedule", {"enabled": True, "week": w}))
            self.assertFalse(any(c[1] == "Set" for c in r.calls))

    def test_disabled_output_field_is_not_editable(self):
        r = FakeRecorder(); r.data["channel_info"]["CH4"] = {"flood_light_switch": False, "flood_light_disable": True}
        r.schema = {"flood_light_switch": {"type": "bool"}}
        with self.assertRaises(ValueError): r.write(r.body("light", {"flood_light_switch": True}))

    def test_identity_is_allowlisted(self):
        r = FakeRecorder()
        for camera, event, section in (("../4", "PID", "light"), ("00", "PID", "light"), ("17", "PID", "light"), ("04", "../Disarming", "light"), ("04", "PID", "reboot")):
            with self.assertRaises(ValueError): r.read(camera, event, section)
        self.assertFalse(r.calls)

    def test_array_options_are_validated(self):
        spec = {"type": "array", "min_size": 0, "max_size": 2, "items": {"items": ["CH4", "CH5"]}}
        validate_value(["CH4"], spec)
        for bad in (["CH7"], ["CH4", "CH4"], "CH4"):
            with self.assertRaises(ValueError): validate_value(bad, spec)

if __name__ == "__main__": unittest.main()
