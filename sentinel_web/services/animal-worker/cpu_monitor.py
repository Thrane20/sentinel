"""Read-only Linux CPU sampling independent of browser requests."""
from collections import deque
from pathlib import Path
import threading
import time


def parse_cpu_stat(text):
    lines = text.splitlines()
    fields = next(line.split() for line in lines if line.startswith("cpu "))
    values = [int(value) for value in fields[1:]]
    if len(values) < 4 or any(value < 0 for value in values):
        raise ValueError("Invalid CPU counters")
    # guest/guest_nice are already included in user/nice: do not count twice.
    total = sum(values[:8])
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    count = sum(1 for line in lines if line.startswith("cpu") and line[3:4].isdigit())
    return total, idle, count


def read_cpu_stat():
    return parse_cpu_stat(Path("/proc/stat").read_text())


class CpuMonitor:
    interval = 5
    window_samples = 12

    def __init__(self, reader=read_cpu_stat, clock=time.monotonic, wall_clock=time.time):
        self.reader = reader
        self.clock = clock
        self.wall_clock = wall_clock
        self.lock = threading.Lock()
        self.samples = deque(maxlen=self.window_samples)
        self.previous = None
        self.cpu_count = None
        self.available = False
        self.sampled_at = None
        self.stop_event = threading.Event()

    def sample(self):
        try:
            total, idle, count = self.reader()
            now = self.clock()
        except (OSError, ValueError, StopIteration):
            with self.lock:
                self.available = False
                self.previous = None
                self.samples.clear()
            return
        with self.lock:
            self.available = True
            self.cpu_count = count
            previous = self.previous
            self.previous = (total, idle, now)
            if previous is None:
                return
            elapsed = now - previous[2]
            delta, idle_delta = total - previous[0], idle - previous[1]
            if elapsed <= 0 or elapsed > self.interval * 3 or delta <= 0 or not 0 <= idle_delta <= delta:
                self.samples.clear()
                self.sampled_at = None
                return
            busy = delta - idle_delta
            self.samples.append((busy, delta, elapsed))
            self.sampled_at = self.wall_clock()

    def payload(self):
        with self.lock:
            samples = list(self.samples)
            return {
                "available": self.available,
                "currentPercent": round(100 * samples[-1][0] / samples[-1][1], 1) if samples else None,
                "averagePercent": round(100 * sum(s[0] for s in samples) / sum(s[1] for s in samples), 1) if samples else None,
                "samples": len(samples),
                "coverageSeconds": round(sum(s[2] for s in samples), 1),
                "sampleIntervalSeconds": self.interval,
                "windowSeconds": self.interval * self.window_samples,
                "cpuCount": self.cpu_count,
                "sampledAt": self.sampled_at,
                "scope": "Linux host / Docker VM",
            }

    def start(self):
        def run():
            self.sample()
            while not self.stop_event.wait(self.interval):
                self.sample()
        threading.Thread(target=run, name="cpu-sampler", daemon=True).start()
