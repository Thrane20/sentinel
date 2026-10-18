"use client";

import { useEffect, useState } from "react";
import { Cpu } from "lucide-react";

type CpuStats = {
  available: boolean;
  currentPercent: number | null;
  averagePercent: number | null;
  samples: number;
  coverageSeconds: number;
  sampleIntervalSeconds: number;
  windowSeconds: number;
  cpuCount: number | null;
  sampledAt: number | null;
  scope: string;
};

export function CpuActivity() {
  const [stats, setStats] = useState<CpuStats | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();
    async function load() {
      try {
        const response = await fetch("/api/system/cpu", {
          cache: "no-store",
          signal: controller.signal,
        });
        if (!response.ok) throw new Error();
        const result = (await response.json()) as CpuStats;
        if (!cancelled) {
          setStats(result);
          setError(!result.available);
        }
      } catch {
        if (!cancelled) {
          setStats(null);
          setError(true);
        }
      } finally {
        if (!cancelled) timer = setTimeout(() => void load(), 5000);
      }
    }
    void load();
    return () => {
      cancelled = true;
      controller.abort();
      clearTimeout(timer);
    };
  }, []);
  const percent = (value: number | null | undefined) =>
    value == null ? "—" : `${value.toFixed(1)}%`;
  const current = error ? null : stats?.currentPercent;
  const average = error ? null : stats?.averagePercent;
  return (
    <section className="panel cpu-activity" aria-labelledby="cpu-heading">
      <div className="panel-heading">
        <h2 id="cpu-heading">
          <span className="slash">{"//"}</span> Server CPU
        </h2>
        <Cpu size={19} />
      </div>
      <div className="cpu-metrics">
        <div>
          <span>Latest 5-second reading</span>
          <strong aria-label="Latest CPU usage">{percent(current)}</strong>
          <meter
            min="0"
            max="100"
            value={current ?? 0}
            aria-label="Latest CPU activity"
          />
        </div>
        <div>
          <span>1-minute average</span>
          <strong aria-label="Average CPU usage">{percent(average)}</strong>
          <meter
            min="0"
            max="100"
            value={average ?? 0}
            aria-label="Average CPU activity"
          />
        </div>
      </div>
      <p className="muted" role="status">
        {error
          ? "CPU statistics unavailable. Retrying every 5 seconds."
          : !stats || !stats.samples
            ? "Collecting the first CPU sample…"
            : `${stats.samples < 12 ? "Warming up · " : ""}${stats.samples}/12 samples · ${Math.round(stats.coverageSeconds)}s coverage · ${stats.cpuCount ?? "Unknown"} logical CPUs`}
      </p>
      <p className="muted">
        Total activity across Linux CPUs, including other workloads. 100% means
        all visible CPUs are busy. Docker Desktop measures its Linux VM.
      </p>
    </section>
  );
}
