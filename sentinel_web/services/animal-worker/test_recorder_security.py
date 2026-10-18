import copy
import unittest
from unittest.mock import Mock

from recorder_security import RecorderSecurity, RecorderSecurityError


class RecorderSecurityTests(unittest.TestCase):
    def setUp(self):
        self.data = {"disarming": False, "action": {"buzzer": True, "mobile_push": True},
                     "disarming_channel": ["CH1", "CH2"], "channel_info": {"CH1": {"schedule": [1, 0]}}}
        self.session = Mock()
        self.session.cookies = []
        self.factory = Mock(return_value=("http://recorder", self.session))
        self.security = RecorderSecurity(self.factory, lambda: True)

    def response(self, data=None, result="success"):
        response = Mock()
        response.json.return_value = {"result": result, "data": data}
        return response

    def test_read_is_cached_and_never_writes(self):
        self.session.post.return_value = self.response(self.data)
        self.assertTrue(self.security.read()["armed"])
        self.assertFalse(self.security.read()["disarming"])
        self.assertEqual(self.factory.call_count, 1)
        self.assertTrue(self.session.post.call_args.args[0].endswith("/Get"))
        self.session.close.assert_not_called()

    def test_expired_status_cache_reuses_authenticated_session(self):
        self.session.post.return_value = self.response(self.data)
        self.security.read()
        self.security.cached["checkedAt"] = 0
        self.security.read()
        self.assertEqual(self.factory.call_count, 1)
        self.assertEqual(self.session.post.call_count, 2)

    def test_disarm_changes_only_flag_and_confirms_by_readback(self):
        confirmed = copy.deepcopy(self.data)
        confirmed["disarming"] = True
        self.session.post.side_effect = [self.response(self.data), self.response(), self.response(confirmed)]
        result = self.security.write(True, False)
        self.assertFalse(result["armed"])
        self.assertTrue(result["disarming"])
        calls = self.session.post.call_args_list
        self.assertTrue(calls[1].args[0].endswith("/Set"))
        self.assertEqual(calls[1].kwargs["json"], {"version": "1.0", "data": confirmed})
        self.assertFalse(self.data["disarming"])
        self.assertTrue(calls[2].args[0].endswith("/Get"))

    def test_arm_clears_flag_without_changing_policy(self):
        current = {**self.data, "disarming": True}
        self.session.post.side_effect = [self.response(current), self.response(), self.response(self.data)]
        self.assertTrue(self.security.write(False, True)["armed"])
        self.assertEqual(self.session.post.call_args_list[1].kwargs["json"]["data"], self.data)

    def test_unconfirmed_write_is_not_cached_as_success(self):
        self.session.post.side_effect = [self.response(self.data), self.response(), self.response(self.data)]
        with self.assertRaisesRegex(RecorderSecurityError, "did not confirm"):
            self.security.write(True, False)
        self.assertIsNone(self.security.cached)
        self.session.close.assert_called_once()

    def test_recorder_rejection_does_not_show_success(self):
        self.session.post.side_effect = [self.response(self.data), self.response(result="failure")]
        with self.assertRaises(RecorderSecurityError):
            self.security.write(True, False)
        self.assertIsNone(self.security.cached)

    def test_invalid_state_and_inputs_never_become_armed(self):
        self.session.post.return_value = self.response({"disarming": "false"})
        with self.assertRaises(RecorderSecurityError):
            self.security.read()
        with self.assertRaises(ValueError):
            self.security.write("true", False)

    def test_already_requested_state_does_not_write(self):
        self.session.post.return_value = self.response(self.data)
        self.assertTrue(self.security.write(False, True)["armed"])
        self.assertEqual(self.session.post.call_count, 1)

    def test_missing_credentials_does_not_contact_recorder(self):
        self.security.configured = lambda: False
        with self.assertRaises(RecorderSecurityError):
            self.security.read()
        self.factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
