# Camera 06 cat replay — 21 October 2026

Requested recorder time: **21 October 2026, 08:55:08 Australia/Brisbane** (Unix timestamp 1792536908). Retrieved a 30-second, 1280×720, 15 FPS H.264 clip through the Ubuntu Sentinel playback endpoint. Playback requests include five seconds of pre-roll. The cat is visually confirmed in the clip and annotated Frigate snapshot.

## Test method

Ran a separate local Docker instance of **sentinel-frigate:0.17.2-fp32**, with the installed **MDV6-mit-yolov9-c** model mounted read-only. OpenVINO startup confirmed **CPU / float32**. MQTT was disabled, the container had no external network, and config/media were temporary test directories. No live cameras, production filters, retained events, or Home Assistant notifications were changed. The test container was stopped and removed after collecting results.

The replay used the real Frigate motion, region, detection and object-tracking pipeline, not just one full-frame model inference. Two file-input cameras compared a 60% tracked threshold / 50% minimum raw score and a more permissive 50% / 35% profile. Both used 1280×720 at a configured 5 FPS, motion threshold 25, contour area 10, and animal minimum area 0.001. Both recognised the cat; recorded tracked scores reached approximately 83–89%.

This is a diagnostic approximation of production. It ran on the Mac's CPU, not the Ubuntu GPU. Processing achieved roughly one frame per second per camera while both replay cameras were active, despite the configured 5 FPS. The replay used the browser-transcoded recording rather than the exact historical live detection frames. Its motion settings came from Sentinel's checked-in generator; Ubuntu's raw Frigate configuration was not directly retrieved. File looping can affect track continuity, so aggregate displacement spanning replay boundaries should not be treated as the cat's original continuous path.

## Measured sample and Sentinel filter check

For a current-profile cat track with an available snapshot:

| Measurement | Observed |
| --- | ---: |
| Frigate tracked top score | 87.23% |
| Bounding-box area | 0.453% of frame |
| Recorded normalized movement at observation | 0% |

These measurements were passed through the existing worker's `matches_measurement_filter` function:

| Filter profile | Result |
| --- | --- |
| Earlier: 70% confidence, 0.70% minimum area, 4% minimum movement | Rejected |
| Current Ubuntu: 60% confidence, 0.10% minimum area, 1% minimum movement | Rejected |
| Current Ubuntu with minimum movement set to 0% | Passed measurement filters |

This is a point-in-time check of an ongoing track, not proof that the track could never move enough to qualify later. It also does not simulate cooldown, hourly admission quota, MQTT delivery or notification dispatch. It demonstrates that a correctly recognised cat can be suppressed by Sentinel's movement gate. Earlier minimum-area settings would also exclude this measured cat.

## Recommendation

For camera **06 · Backyard – Down**, keep **60% confidence**, **0.10% minimum area**, and the existing **720p / 5 FPS** profile; set **minimum movement to 0%** for the next live test. No evidence from this clip requires lowering confidence below 60%. No production settings were changed during this experiment.

## Files

- `clip.mp4`: downloaded recorder playback.
- `cat-detected.jpg`: Frigate's annotated snapshot showing the cat's detection box.
- `settings-at-test.json`: live Sentinel settings retrieved from Ubuntu before the test.
- `replay-events.json`: isolated Frigate event observations, including temporary replay cameras and track data.
- `filter-results.json`: measurement-filter comparison produced using the worker's actual filter function.
