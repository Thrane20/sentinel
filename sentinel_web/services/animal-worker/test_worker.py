import json
import io
import os
import tempfile
import time
import unittest
from unittest.mock import patch

import worker


class AnimalWorkerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        worker.DB_PATH = os.path.join(self.directory.name, "animals.db")
        worker.MQTT_CLIENT = None
        worker.SUPPRESSED_EVENT_IDS.clear()
        worker.initialize()

    def tearDown(self):
        self.directory.cleanup()

    def test_defaults_and_camera_tuning_persist(self):
        current = worker.settings()
        self.assertTrue(current["globalEnabled"])
        self.assertFalse(current["alertsEnabled"])
        self.assertTrue(current["cameras"]["01"]["enabled"])
        self.assertFalse(current["cameras"]["02"]["enabled"])
        self.assertEqual(current["cameras"]["05"]["threshold"], 0.80)
        self.assertEqual(current["cameras"]["05"]["maxArea"], 0.10)
        self.assertEqual(current["cameras"]["05"]["minTravel"], 0.04)

        updated = worker.update_settings(
            {"cameras": {"05": {"enabled": False, "threshold": 0.82, "minArea": 0.01, "maxArea": 0.12, "minTravel": 0.05}}}
        )
        self.assertEqual(updated["cameras"]["05"], {"enabled": False, "threshold": 0.82, "minArea": 0.01, "maxArea": 0.12, "minTravel": 0.05})
        self.assertEqual(worker.settings()["cameras"]["05"], updated["cameras"]["05"])

    def test_frigate_event_is_retained_in_shadow_mode(self):
        payload = {
            "type": "new",
            "after": {
                "id": "event-1",
                "camera": "ch05",
                "label": "animal",
                "false_positive": False,
                "top_score": 0.83,
                "start_time": 1000,
                "box": [64, 36, 192, 144],
                "has_snapshot": True,
            },
        }
        with patch.object(worker, "event_track_metrics", return_value=(0.05, 3)):
            worker.handle_event(json.dumps(payload).encode())
        with worker.connect() as db:
            row = db.execute("SELECT * FROM events WHERE id='event-1'").fetchone()
        self.assertEqual(row["alert_status"], "shadow")
        self.assertEqual(json.loads(row["box"]), [0.1, 0.1, 0.2, 0.3])
        self.assertEqual(row["travel"], 0.05)

    def test_transient_frigate_track_without_snapshot_is_not_retained(self):
        payload = {
            "type": "new",
            "after": {
                "id": "transient-event",
                "camera": "ch05",
                "label": "animal",
                "false_positive": False,
                "top_score": 0.78,
                "start_time": 1000,
                "box": [64, 36, 320, 180],
                "has_snapshot": False,
            },
        }
        worker.handle_event(json.dumps(payload).encode())
        with worker.connect() as db:
            row = db.execute(
                "SELECT * FROM events WHERE id='transient-event'"
            ).fetchone()
        self.assertIsNone(row)

    def test_shadow_history_cooldown_keeps_one_event_per_camera(self):
        now = time.time()
        first = {
            "type": "new",
            "after": {
                "id": "event-first",
                "camera": "ch05",
                "label": "animal",
                "false_positive": False,
                "top_score": 0.91,
                "start_time": now,
                "box": [64, 36, 192, 144],
                "has_snapshot": True,
            },
        }
        second = json.loads(json.dumps(first))
        second["after"]["id"] = "event-second"
        with patch.object(worker, "event_track_metrics", return_value=(0.05, 3)):
            worker.handle_event(json.dumps(first).encode())
            worker.handle_event(json.dumps(second).encode())
        with worker.connect() as db:
            rows = db.execute("SELECT id FROM events ORDER BY id").fetchall()
        self.assertEqual([row["id"] for row in rows], ["event-first"])
        self.assertIn("event-second", worker.SUPPRESSED_EVENT_IDS)

    def test_cooldown_is_camera_specific(self):
        worker.update_settings({"alertsEnabled": True})
        now = time.time()
        with worker.connect() as db:
            db.execute(
                """INSERT INTO events(id,camera,started_at,confidence,box,alert_status,updated_at)
                   VALUES(?,?,?,?,?,'sent',?)""",
                ("prior", "ch05", now, 0.9, "[0,0,0.5,0.5]", now),
            )
        self.assertEqual(worker.should_alert("ch05", 0.9, [0, 0, 0.2, 0.2], 0.05), (False, "cooldown"))
        self.assertEqual(worker.should_alert("ch06", 0.9, [0, 0, 0.2, 0.2], 0.05), (True, "pending"))

    def test_threshold_and_area_filters(self):
        worker.update_settings({"alertsEnabled": True})
        self.assertEqual(worker.should_alert("ch05", 0.79, [0, 0, 0.2, 0.2], 0.05), (False, "filtered"))
        self.assertEqual(worker.should_alert("ch05", 0.9, [0, 0, 0.01, 0.01], 0.05), (False, "filtered"))
        self.assertEqual(worker.should_alert("ch05", 0.9, [0, 0, 0.4, 0.4], 0.05), (False, "filtered"))
        self.assertEqual(worker.should_alert("ch05", 0.9, [0, 0, 0.2, 0.2], 0.02), (False, "filtered"))

    def test_event_track_movement_uses_furthest_path_points(self):
        details = {
            "data": {
                "path_data": [
                    [[0.80, 0.90], 1],
                    [[0.80, 0.94], 2],
                    [[0.80, 0.98], 3],
                ]
            }
        }
        with patch.object(
            worker.urllib.request,
            "urlopen",
            return_value=io.BytesIO(json.dumps(details).encode()),
        ):
            travel, points = worker.event_track_metrics("event-path")
        self.assertAlmostEqual(travel, 0.08 / (2 ** 0.5))
        self.assertEqual(points, 3)

    def test_stationary_finished_candidate_is_not_retained(self):
        payload = {
            "type": "end",
            "after": {
                "id": "stationary-event",
                "camera": "ch05",
                "label": "animal",
                "false_positive": False,
                "top_score": 0.91,
                "start_time": 1000,
                "end_time": 1005,
                "box": [64, 36, 192, 144],
                "has_snapshot": True,
            },
        }
        with patch.object(worker, "event_track_metrics", return_value=(0.01, 2)):
            worker.handle_event(json.dumps(payload).encode())
        with worker.connect() as db:
            row = db.execute("SELECT * FROM events WHERE id='stationary-event'").fetchone()
        self.assertIsNone(row)

    def test_delivery_retries_and_persists_success(self):
        now = time.time()
        with worker.connect() as db:
            db.execute(
                """INSERT INTO events(id,camera,started_at,confidence,box,alert_status,updated_at)
                   VALUES(?,?,?,?,?,'pending',?)""",
                ("retry-event", "ch05", now, 0.9, "[0,0,0.5,0.5]", now),
            )
        with (
            patch.object(worker, "wait_for_snapshot"),
            patch.object(worker.time, "sleep"),
            patch.object(
                worker,
                "post_webhook",
                side_effect=[(False, "down"), (False, "down"), (True, None)],
            ) as webhook,
        ):
            worker.deliver("retry-event")
        with worker.connect() as db:
            row = db.execute("SELECT * FROM events WHERE id='retry-event'").fetchone()
        self.assertEqual(webhook.call_count, 3)
        self.assertEqual(row["alert_status"], "sent")
        self.assertEqual(row["alert_attempts"], 3)

    def test_clear_events_removes_metadata_and_frigate_events(self):
        now = time.time()
        with worker.connect() as db:
            db.executemany(
                """INSERT INTO events(id,camera,started_at,confidence,box,alert_status,updated_at)
                   VALUES(?,?,?,?,?,'shadow',?)""",
                [
                    ("clear-1", "ch05", now, 0.9, "[0,0,0.5,0.5]", now),
                    ("clear-2", "ch06", now, 0.8, "[0,0,0.5,0.5]", now),
                ],
            )
        response = unittest.mock.MagicMock()
        response.status = 200
        response.__enter__.return_value = response
        with patch.object(worker.urllib.request, "urlopen", return_value=response) as delete:
            result = worker.clear_events()
        with worker.connect() as db:
            remaining = db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        self.assertEqual(remaining, 0)
        self.assertEqual(result, {"cleared": 2, "frigateEventsDeleted": 2, "frigateDeleteFailures": 0})
        self.assertEqual(delete.call_count, 2)
        self.assertEqual(worker.settings()["globalEnabled"], True)

    def test_ivsec_alerts_are_stored_deduplicated_and_cleared(self):
        alarms = [
            {
                "time": "09/07/2026 17:05:30",
                "channel_alarm": [
                    {
                        "channel": "CH5",
                        "channel_name": "Front Drive",
                        "motion_alarm": True,
                        "videoloss": False,
                        "camera_connect_status": {"connect_status": "Offline"},
                    }
                ],
            }
        ]

        self.assertEqual(worker.store_ivsec_alarms(alarms, 418), 1)
        self.assertEqual(worker.store_ivsec_alarms(alarms, 418), 0)

        events = worker.ivsec_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["cameraId"], "05")
        self.assertEqual(events[0]["cameraName"], "Front Drive")
        self.assertEqual(events[0]["eventType"], "Motion")
        self.assertEqual(events[0]["sourceTime"], "09/07/2026 17:05:30")

        self.assertEqual(worker.clear_ivsec_events(), {"cleared": 1})
        self.assertEqual(worker.ivsec_events(), [])
        self.assertGreater(worker.settings()["ivsecClearedBefore"], 0)

    def test_ivsec_intelligent_alarm_uses_its_subtype(self):
        alarms = [
            {
                "time": "09/07/2026 17:07:20",
                "channel_alarm": [
                    {
                        "channel": "CH6",
                        "int_alarm": {
                            "alarm_val": True,
                            "int_subtype": "pid",
                            "take_alarm_snap": 5,
                        },
                    }
                ],
            }
        ]
        self.assertEqual(worker.store_ivsec_alarms(alarms, 419), 1)
        self.assertEqual(worker.ivsec_events()[0]["eventType"], "Perimeter intrusion")

    def test_ivsec_archive_records_are_mapped_and_deduplicated(self):
        worker.store_ivsec_alarms(
            [
                {
                    "time": "09/07/2026 09:32:31",
                    "channel_alarm": [
                        {
                            "channel": "CH6",
                            "int_alarm": {"alarm_val": True, "int_subtype": "pid"},
                        }
                    ],
                }
            ],
            400,
        )
        records = [
            [
                {
                    "channel": "CH6",
                    "record_type": 128,
                    "start_date": "09/07/2026",
                    "start_time": "09:32:31",
                    "end_date": "09/07/2026",
                    "end_time": "09:33:01",
                    "record_id": 1635,
                    "disk_event_id": 1,
                }
            ]
        ]
        self.assertEqual(worker.store_ivsec_records(records), 1)
        self.assertEqual(worker.store_ivsec_records(records), 0)
        event = worker.ivsec_events()[0]
        self.assertEqual(len(worker.ivsec_events()), 1)
        self.assertEqual(event["cameraId"], "06")
        self.assertEqual(event["cameraName"], "Backyard - Down")
        self.assertEqual(event["eventType"], "Smart detection")
        self.assertEqual(event["sourceTime"], "09/07/2026 09:32:31")

        worker.clear_ivsec_events()
        self.assertEqual(worker.store_ivsec_records(records), 0)
        self.assertEqual(worker.ivsec_events(), [])


if __name__ == "__main__":
    unittest.main()
