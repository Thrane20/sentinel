"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  Radio,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { cameras, type Camera } from "@/lib/cameras";

type RecorderEvent = {
  id: number;
  cameraId: string;
  cameraName: string;
  eventType: string;
  sourceTime: string;
  capturedAt: number;
};

type EventHealth = {
  online: boolean;
  configured: boolean;
  lastPoll: number | null;
  error: string | null;
};

function formatRecorderTime(value: string, fallback: number) {
  const match = value.match(
    /^(\d{2})\/(\d{2})\/(\d{4}) (\d{2}):(\d{2}):(\d{2})$/,
  );
  if (match && value !== "00/00/0000 00:00:00") {
    const [, month, day, year, hour, minute, second] = match;
    return new Date(
      Number(year),
      Number(month) - 1,
      Number(day),
      Number(hour),
      Number(minute),
      Number(second),
    ).toLocaleString("en-AU", {
      day: "2-digit",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  }
  return `${new Date(fallback * 1000).toLocaleString("en-AU")} · recorder time unavailable`;
}

export function IvsecEvents({
  onOpenCamera,
}: {
  onOpenCamera: (camera: Camera) => void;
}) {
  const [events, setEvents] = useState<RecorderEvent[]>([]);
  const [health, setHealth] = useState<EventHealth | null>(null);
  const [loading, setLoading] = useState(true);
  const [clearing, setClearing] = useState(false);
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    try {
      const response = await fetch("/api/ivsec/events", { cache: "no-store" });
      if (!response.ok) throw new Error();
      const body = (await response.json()) as {
        events: RecorderEvent[];
        health: EventHealth;
      };
      setEvents(body.events);
      setHealth(body.health);
    } catch {
      setHealth({
        online: false,
        configured: false,
        lastPoll: null,
        error: "Recorder event service is unavailable",
      });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // State changes only after the asynchronous request completes.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
    const timer = window.setInterval(() => {
      if (!document.hidden) void load();
    }, 10000);
    return () => window.clearInterval(timer);
  }, [load]);

  async function clearEvents() {
    if (
      !window.confirm(
        "Clear the collected IVSEC alert list? This keeps the recorder's own alerts and recordings.",
      )
    )
      return;
    setClearing(true);
    setMessage("");
    try {
      const response = await fetch("/api/ivsec/events", { method: "DELETE" });
      const body = (await response.json()) as { cleared?: number; error?: string };
      if (!response.ok) throw new Error(body.error || "Clear failed");
      setEvents([]);
      setMessage(`Cleared ${body.cleared || 0} collected alerts.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Alerts could not be cleared.");
    } finally {
      setClearing(false);
    }
  }

  return (
    <section className="panel ivsec-alerts">
      <div className="panel-heading">
        <div>
          <h2>
            <span className="slash">{"//"}</span> IVSEC alerts
          </h2>
          <span className={`collector-state ${health?.online ? "online" : ""}`}>
            {health?.online ? <CheckCircle2 size={12} /> : <AlertTriangle size={12} />}
            {health?.online ? "Recorder feed connected" : health?.error || "Connecting"}
          </span>
        </div>
        <div className="ivsec-alert-actions">
          <button aria-label="Refresh IVSEC alerts" onClick={() => void load()} disabled={loading}>
            <RefreshCw size={14} className={loading ? "spin" : ""} />
          </button>
          <button className="animal-clear" onClick={() => void clearEvents()} disabled={clearing || !events.length}>
            <Trash2 size={13} /> {clearing ? "Clearing…" : "Clear"}
          </button>
        </div>
      </div>

      {events.length ? (
        <div className="ivsec-alert-list">
          {events.map((event) => {
            const camera = cameras.find((item) => item.id === event.cameraId);
            return (
              <button
                key={event.id}
                className="ivsec-alert-row"
                disabled={!camera?.seen}
                onClick={() => camera && onOpenCamera(camera)}
              >
                <span className="ivsec-alert-icon"><Radio size={15} /></span>
                <span>
                  <strong>{event.eventType}</strong>
                  <small>{formatRecorderTime(event.sourceTime, event.capturedAt)}</small>
                </span>
                <span className="ivsec-alert-camera">
                  <b>CH {event.cameraId}</b>
                  <small>{event.cameraName}</small>
                </span>
                {camera?.seen && <ChevronRight size={15} />}
              </button>
            );
          })}
        </div>
      ) : (
        <div className="empty ivsec-alert-empty">
          <Radio size={32} />
          <h3>{loading ? "Connecting to IVSEC…" : "No collected alerts"}</h3>
          <p>Recorder alerts from the last seven days will appear here with their camera and timestamp.</p>
        </div>
      )}
      {message && <p className="muted ivsec-alert-message">{message}</p>}
      <p className="ivsec-alert-note">
        Sentinel reads IVSEC&apos;s alert recordings for the last seven days and follows its live event cursor. Clearing this list does not delete recorder footage.
      </p>
    </section>
  );
}
