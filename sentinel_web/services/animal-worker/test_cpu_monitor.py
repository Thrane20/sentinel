import unittest
from cpu_monitor import CpuMonitor, parse_cpu_stat


class CpuMonitorTests(unittest.TestCase):
    def test_guest_time_not_double_counted_and_iowait_is_idle(self):
        self.assertEqual(parse_cpu_stat("cpu  100 10 30 800 20 2 3 5 40 5\ncpu0 1 2 3 4\ncpu1 1 2 3 4\n"), (970, 820, 2))

    def test_warmup_current_and_weighted_rolling_average(self):
        now = [0]
        counters = [1000, 500]
        monitor = CpuMonitor(reader=lambda: (*counters, 4), clock=lambda: now[0], wall_clock=lambda: 100 + now[0])
        monitor.sample()
        self.assertIsNone(monitor.payload()["averagePercent"])
        self.assertTrue(monitor.payload()["available"])
        now[0] += 5; counters[:] = [1100, 550]; monitor.sample()
        self.assertEqual(monitor.payload()["currentPercent"], 50)
        now[0] += 5; counters[:] = [1300, 700]; monitor.sample()
        self.assertEqual(monitor.payload()["currentPercent"], 25)
        self.assertEqual(monitor.payload()["averagePercent"], 33.3)
        for _ in range(12):
            now[0] += 5; counters[0] += 100; monitor.sample()
        result = monitor.payload()
        self.assertEqual(result["samples"], 12)
        self.assertEqual(result["coverageSeconds"], 60)
        self.assertEqual(result["averagePercent"], 100)

    def test_failure_counter_reset_and_suspend_do_not_show_stale_average(self):
        now = [0]; counters = [1000, 500]; failed = [False]
        def read():
            if failed[0]: raise OSError("unavailable")
            return *counters, 2
        monitor = CpuMonitor(reader=read, clock=lambda: now[0])
        monitor.sample(); now[0] += 5; counters[0] += 100; monitor.sample()
        failed[0] = True; monitor.sample()
        self.assertFalse(monitor.payload()["available"])
        self.assertIsNone(monitor.payload()["averagePercent"])
        failed[0] = False; monitor.sample()
        now[0] += 5; counters[:] = [10, 5]; monitor.sample()
        self.assertIsNone(monitor.payload()["currentPercent"])
        now[0] += 5; counters[:] = [110, 55]; monitor.sample()
        self.assertEqual(monitor.payload()["averagePercent"], 50)
        now[0] += 120; counters[0] += 100; monitor.sample()
        self.assertIsNone(monitor.payload()["averagePercent"])
