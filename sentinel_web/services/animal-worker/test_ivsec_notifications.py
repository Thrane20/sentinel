import json
import os
import tempfile
import time
import unittest
from datetime import datetime
from unittest.mock import Mock, patch

import worker
from ivsec_notifications import RECORDER_TZ, IvsecNotifications


class IvsecNotificationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.old_path = worker.DB_PATH
        worker.DB_PATH = os.path.join(self.directory.name, "events.db")
        worker.initialize()
        self.send = Mock(return_value=(True, None))
        self.router = IvsecNotifications(worker.connect, worker.DB_LOCK, worker.camera_data, "http://sentinel:3000", lambda: True, self.send)
        self.rule = {"id": "garage_intrusion", "cameraId": "04", "eventKey": "perimeter_intrusion", "message": "Something is moving in the garage", "enabled": True, "cooldownSeconds": 60}
        with patch("ivsec_notifications.time.time", return_value=time.time() - 60):
            self.router.save(self.rule)

    def tearDown(self):
        worker.DB_PATH = self.old_path
        self.directory.cleanup()

    def event(self, camera="ch04", label="Perimeter intrusion", seconds_ago=0, details=None, source_time=None):
        now = time.time()
        stamp = source_time or datetime.fromtimestamp(now-seconds_ago, RECORDER_TZ).strftime("%m/%d/%Y %H:%M:%S")
        with worker.connect() as db:
            result = db.execute("INSERT INTO ivsec_events(fingerprint,camera,camera_name,event_type,source_time,details,captured_at) VALUES(?,?,?,?,?,?,?)", (str(time.time_ns()),camera,worker.camera_data(camera)["name"],label,stamp,json.dumps(details or {"intelligent_alarm":{"alarm_val":True,"int_subtype":"pid"}}),now))
            return result.lastrowid

    def rows(self):
        with worker.connect() as db:
            return db.execute("SELECT * FROM ivsec_notification_outbox ORDER BY created_at").fetchall()

    def test_exact_camera_and_event_match_and_stable_payload(self):
        self.assertEqual(self.router.enqueue(self.event(camera="ch05")), 0)
        self.assertEqual(self.router.enqueue(self.event(label="Motion")), 0)
        self.assertEqual(self.router.enqueue(self.event()), 1)
        payload = json.loads(self.rows()[0]["payload"])
        self.assertEqual(payload["notificationId"], "garage_intrusion")
        self.assertEqual(payload["camera"]["id"], "04")
        self.assertEqual(payload["message"], self.rule["message"])
        self.assertIn("tab=playback",payload["playbackUrl"])
        self.assertFalse(payload["isTest"])
        self.router.drain()
        self.assertEqual(self.rows()[0]["status"], "sent")

    def test_replay_and_clear_do_not_duplicate_delivery(self):
        event_id = self.event()
        source_time = self.router.inspect(event_id)["sourceTime"]
        self.assertEqual(self.router.enqueue(event_id), 1)
        self.router.save({**self.rule,"cooldownSeconds":0})
        self.assertEqual(self.router.enqueue(event_id), 0)
        worker.clear_ivsec_events()
        replay = self.event(source_time=source_time)
        self.assertEqual(self.router.enqueue(replay), 0)

    def test_archive_old_invalid_and_future_events_do_not_alert(self):
        for event in [self.event(details={"record_type":16}), self.event(seconds_ago=180), self.event(source_time="00/00/0000 00:00:00"),self.event(seconds_ago=-180)]:
            self.assertEqual(self.router.enqueue(event),0)
        self.send.assert_not_called()

    def test_cooldown_is_per_rule_and_survives_restart(self):
        self.assertEqual(self.router.enqueue(self.event()),1)
        router = IvsecNotifications(worker.connect,worker.DB_LOCK,worker.camera_data,"http://sentinel",lambda: True,self.send)
        self.assertEqual(router.enqueue(self.event(seconds_ago=1)),0)
        with patch("ivsec_notifications.time.time", return_value=time.time()-10):
            router.save({**self.rule,"id":"garage_intrusion_second"})
        self.assertEqual(router.enqueue(self.event()),1)

    def test_pending_delivery_survives_restart_and_retries_with_same_id(self):
        self.router.enqueue(self.event())
        self.send.return_value = (False,"connection error with private URL")
        self.router.drain()
        self.assertEqual(self.rows()[0]["attempts"],1)
        self.assertNotIn("private URL",self.rows()[0]["error"])
        with worker.connect() as db: db.execute("UPDATE ivsec_notification_outbox SET next_attempt=0")
        self.send.return_value = (True,None)
        restarted = IvsecNotifications(worker.connect,worker.DB_LOCK,worker.camera_data,"http://sentinel",lambda: True,self.send)
        restarted.drain()
        self.assertEqual(self.rows()[0]["status"],"sent")
        self.assertEqual(self.send.call_args_list[0].args[0]["eventId"],self.send.call_args_list[1].args[0]["eventId"])

    def test_disabled_rule_and_edits_cancel_pending(self):
        self.router.enqueue(self.event())
        self.router.save({**self.rule,"enabled":False})
        self.router.drain()
        self.send.assert_not_called()
        self.assertEqual(self.rows()[0]["status"],"cancelled")
        self.assertEqual(self.router.enqueue(self.event()),0)

    def test_manual_test_is_explicit_and_not_live_event_type(self):
        self.router.save({**self.rule,"enabled":False})
        self.assertEqual(self.router.enqueue(self.event(seconds_ago=86400,details={"record_type":16}),"garage_intrusion"),1)
        payload=json.loads(self.rows()[0]["payload"])
        self.assertTrue(payload["isTest"])
        self.assertEqual(payload["type"],"sentinel.ivsec.test")

    def test_inspection_redacts_secrets_and_keeps_subtype(self):
        detail=self.router.inspect(self.event(details={"password":"secret", "nested":{"token":"private"},"url":"rtsp://user:pass@recorder/path","int_subtype":"pid"}))
        self.assertEqual(detail["raw"]["password"],"[redacted]")
        self.assertEqual(detail["raw"]["int_subtype"],"pid")
        self.assertNotIn("user:pass",json.dumps(detail))
        self.assertEqual(detail["eventKey"],"perimeter_intrusion")

    def test_validation_and_missing_event(self):
        for changed in [{"id":"bad id"},{"eventKey":"*"},{"cameraId":"99"},{"cooldownSeconds":True},{"message":""}]:
            with self.assertRaises(ValueError): self.router.save({**self.rule,**changed})
        with self.assertRaises(KeyError): self.router.inspect(99999)

    def test_event_cleared_during_ingestion_does_not_break_live_collector(self):
        self.assertEqual(self.router.enqueue(99999), 0)
        with self.assertRaises(KeyError): self.router.enqueue(99999, "garage_intrusion")

    def test_expired_delivery_is_not_sent(self):
        self.router.enqueue(self.event())
        with worker.connect() as db: db.execute("UPDATE ivsec_notification_outbox SET expires_at=0")
        self.router.drain()
        self.send.assert_not_called()
        self.assertEqual(self.rows()[0]["status"],"expired")

    def test_live_collector_keeps_subtypes_and_enqueues_only_matching_rule(self):
        stamp = datetime.fromtimestamp(time.time(), RECORDER_TZ).strftime("%m/%d/%Y %H:%M:%S")
        alarms=[{"time":stamp,"channel_alarm":[{"channel":"CH4","motion_alarm":True,"int_alarm":{"alarm_val":True,"int_subtype":"pid"}}]}]
        with patch.object(worker,"IVSEC_NOTIFICATIONS",self.router):
            self.assertEqual(worker.store_ivsec_alarms(alarms,1),2)
            self.assertEqual(worker.store_ivsec_alarms(alarms,2),0)
        self.assertEqual(len(self.rows()),1)
        self.assertEqual({event["eventType"] for event in worker.ivsec_events()},{"Motion","Perimeter intrusion"})


if __name__ == "__main__": unittest.main()
