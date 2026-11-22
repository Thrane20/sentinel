"use client";

import { useEffect, useState } from "react";
import { Gauge } from "lucide-react";

type Sample = {
  at: number;
  usedKbps: number | null;
  totalKbps: number | null;
  recorderStreams: number | null;
  viewers: number | null;
  workerSessions?: number;
  eventChecksPerMinute?: number;
};
type RecorderLoadStats = {
  configured: boolean;
  latest: Sample | null;
  peakUsedKbps: number | null;
  hourChangeKbps: number | null;
  history: { at: number; usedKbps: number | null }[];
  recorderError: string | null;
  frigateError: string | null;
  warnings: string[];
};

const mbps = (kbps: number | null | undefined) =>
  kbps == null ? "—" : `${(kbps / 1024).toFixed(1)} Mbps`;
const count = (value: number | null | undefined) =>
  value == null ? "—" : String(value);

function Trend({ history, total }: { history: RecorderLoadStats["history"]; total: number }) {
  const points = history.filter((p) => p.usedKbps != null);
  if (points.length < 2) return null;
  const first = points[0].at;
  const span = Math.max(points[points.length - 1].at - first, 1);
  const path = points
    .map((p, i) => `${i ? "L" : "M"}${((p.at - first) / span) * 100},${40 - (p.usedKbps! / total) * 40}`)
    .join(" ");
  const hours = Math.round(span / 3600);
  return (
    <figure className="recorder-load-trend">
      <svg viewBox="0 0 100 40" preserveAspectRatio="none" role="img"
        aria-label={`Recorder bandwidth over the last ${hours || "<1"} hours`}>
        <line x1="0" x2="100" y1="6" y2="6" className="limit" />
        <path d={path} />
      </svg>
      <figcaption className="muted">
        Bandwidth used, last {hours ? `${hours}h` : "hour"} · dashed line 85%
      </figcaption>
    </figure>
  );
}

export function RecorderLoad() {
  const [stats, setStats] = useState<RecorderLoadStats | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();
    async function load() {
      try {
        const response = await fetch("/api/system/recorder-load", {
          cache: "no-store",
          signal: controller.signal,
        });
        if (!response.ok) throw new Error();
        const result = (await response.json()) as RecorderLoadStats;
        if (!cancelled) {
          setStats(result);
          setError(false);
        }
      } catch {
        if (!cancelled) setError(true);
      } finally {
        if (!cancelled) timer = setTimeout(() => void load(), 30000);
      }
    }
    void load();
    return () => {
      cancelled = true;
      controller.abort();
      clearTimeout(timer);
    };
  }, []);
  const latest = error ? null : stats?.latest;
  const used = latest?.usedKbps ?? null;
  const total = latest?.totalKbps ?? null;
  const percent = used != null && total ? Math.round((100 * used) / total) : null;
  const change = stats?.hourChangeKbps;
  return (
    <section className="panel recorder-load" aria-labelledby="recorder-load-heading">
      <div className="panel-heading">
        <h2 id="recorder-load-heading">
          <span className="slash">{"//"}</span> Recorder load
        </h2>
        <Gauge size={19} />
      </div>
      <div className="cpu-metrics">
        <div>
          <span>Streaming bandwidth used</span>
          <strong aria-label="Recorder bandwidth used">
            {percent == null ? "—" : `${percent}%`}
          </strong>
          <meter min="0" max="100" low={70} high={85} optimum={0} value={percent ?? 0}
            aria-label="Recorder bandwidth budget" />
          <p className="muted">{mbps(used)} of {mbps(total)}</p>
        </div>
        <dl className="recorder-load-facts">
          <div><dt>Change, last hour</dt><dd>{change == null ? "—" : `${change >= 0 ? "+" : "−"}${mbps(Math.abs(change))}`}</dd></div>
          <div><dt>Peak since restart</dt><dd>{mbps(stats?.peakUsedKbps)}</dd></div>
          <div><dt>Recorder streams via go2rtc</dt><dd aria-label="Recorder streams">{count(latest?.recorderStreams)}</dd></div>
          <div><dt>Worker recorder logins</dt><dd aria-label="Worker recorder logins">{count(latest?.workerSessions)}</dd></div>
          <div><dt>Event checks per minute</dt><dd>{count(latest?.eventChecksPerMinute)}</dd></div>
        </dl>
      </div>
      {total && stats ? <Trend history={stats.history} total={total} /> : null}
      {!error && stats?.warnings.length ? (
        <ul className="recorder-load-warnings" role="alert">
          {stats.warnings.map((w) => <li key={w}>{w}</li>)}
        </ul>
      ) : null}
      <p className="muted" role="status">
        {error
          ? "Recorder load unavailable. Retrying every 30 seconds."
          : !stats
            ? "Loading recorder load…"
            : !stats.configured
              ? "Add recorder credentials to monitor recorder load."
              : !latest
                ? "Collecting the first sample (one per minute)…"
                : [stats.recorderError && `Recorder: ${stats.recorderError}`,
                   stats.frigateError && `go2rtc: ${stats.frigateError}`]
                    .filter(Boolean).join(" · ") || `Sampled ${new Date(latest.at * 1000).toLocaleTimeString()}`}
      </p>
      <p className="muted">
        The recorder&apos;s own budget for streams it serves to any client, including
        the IVSEC app. A climb with no extra Sentinel streams points at connections
        the recorder is not releasing.
      </p>
    </section>
  );
}
