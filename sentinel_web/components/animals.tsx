"use client";

import Image from "next/image";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  Bell,
  Check,
  Cpu,
  ExternalLink,
  PawPrint,
  Radio,
  RefreshCw,
  ShieldCheck,
  Trash2,
  X,
} from "lucide-react";
import { cameras, type Camera } from "@/lib/cameras";

export type AnimalHealth = {
  online: boolean;
  mqttOnline: boolean;
  frigateOnline: boolean;
  model: string;
  provider: string;
  inferenceSpeedMs: number | null;
  alertsConfigured: boolean;
  alertsEnabled: boolean;
  enabledCameras: number;
};

type Event = {
  id: string;
  cameraId: string;
  cameraName: string;
  startedAt: number;
  endedAt: number | null;
  confidence: number;
  boundingBox: [number, number, number, number];
  travelPercent: number;
  pathPoints: number;
  hasSnapshot: boolean;
  snapshotUrl: string;
  alertStatus: string;
  alertAttempts: number;
  suppressed: boolean;
  acknowledgedAt: number | null;
};

type CameraSettings = {
  enabled: boolean;
  threshold: number;
  minArea: number;
  maxArea: number;
  minTravel: number;
};

type Settings = {
  globalEnabled: boolean;
  alertsEnabled: boolean;
  cooldownSeconds: number;
  retentionDays: number;
  maxEvents: number;
  cameras: Record<string, CameraSettings>;
};

function formatTime(timestamp: number) {
  return new Date(timestamp * 1000).toLocaleString("en-AU", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function statusLabel(event: Event) {
  if (event.alertStatus === "sent") return "Alert sent";
  if (event.alertStatus === "failed") return "Alert failed";
  if (event.alertStatus === "cooldown") return "Cooldown";
  if (event.alertStatus === "filtered") return "Below camera filter";
  if (event.alertStatus === "pending" || event.alertStatus === "retrying")
    return "Sending alert";
  return "Shadow mode";
}

export function Animals({
  health,
  onOpenCamera,
}: {
  health: AnimalHealth | null;
  onOpenCamera: (camera: Camera) => void;
}) {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [events, setEvents] = useState<Event[]>([]);
  const [selected, setSelected] = useState<Event | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [testMessage, setTestMessage] = useState("");
  const dialog = useRef<HTMLDialogElement>(null);

  const load = useCallback(async () => {
    try {
      const [settingsResponse, eventsResponse] = await Promise.all([
        fetch("/api/animals/settings", { cache: "no-store" }),
        fetch("/api/animals/events?limit=40", { cache: "no-store" }),
      ]);
      if (!settingsResponse.ok || !eventsResponse.ok) throw new Error();
      setSettings(await settingsResponse.json());
      const eventData = (await eventsResponse.json()) as { events: Event[] };
      setEvents(eventData.events);
      setError("");
      const requested = new URLSearchParams(window.location.search).get("event");
      if (requested)
        setSelected(eventData.events.find((event) => event.id === requested) || null);
    } catch {
      setError("Animal detection services are not available yet.");
    }
  }, []);

  useEffect(() => {
    // The initial request resolves asynchronously before updating component state.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
    const timer = window.setInterval(() => {
      if (!document.hidden) void load();
    }, 10000);
    return () => window.clearInterval(timer);
  }, [load]);

  useEffect(() => {
    if (selected) dialog.current?.showModal();
    else dialog.current?.close();
  }, [selected]);

  async function patch(body: object) {
    setSaving(true);
    try {
      const response = await fetch("/api/animals/settings", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!response.ok) throw new Error();
      setSettings(await response.json());
      setError("");
    } catch {
      setError("The setting could not be saved.");
    } finally {
      setSaving(false);
    }
  }

  async function acknowledge(event: Event) {
    const response = await fetch(
      `/api/animals/events/${encodeURIComponent(event.id)}/acknowledge`,
      { method: "POST" },
    );
    if (response.ok) {
      const acknowledgedAt = Date.now() / 1000;
      setEvents((current) =>
        current.map((item) =>
          item.id === event.id ? { ...item, acknowledgedAt } : item,
        ),
      );
      setSelected({ ...event, acknowledgedAt });
    }
  }

  async function testAlert() {
    setTesting(true);
    setTestMessage("");
    try {
      const response = await fetch("/api/animals/test-alert", {
        method: "POST",
      });
      const body = (await response.json()) as { error?: string };
      setTestMessage(
        response.ok ? "Test alert sent." : body.error || "Test alert failed.",
      );
    } catch {
      setTestMessage("Test alert failed.");
    } finally {
      setTesting(false);
    }
  }

  async function clearEvents() {
    if (
      !window.confirm(
        "Clear every animal event, acknowledgement, alert record, and stored event snapshot? Camera settings will be kept.",
      )
    )
      return;

    setClearing(true);
    setTestMessage("");
    try {
      const response = await fetch("/api/animals/events", {
        method: "DELETE",
      });
      const body = (await response.json()) as {
        cleared?: number;
        frigateDeleteFailures?: number;
        error?: string;
      };
      if (!response.ok) throw new Error(body.error || "Clear failed");
      setEvents([]);
      setSelected(null);
      setTestMessage(
        body.frigateDeleteFailures
          ? `Cleared ${body.cleared || 0} events. ${body.frigateDeleteFailures} Frigate snapshots could not be removed.`
          : `Cleared ${body.cleared || 0} animal events and their metadata.`,
      );
      setError("");
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Animal events could not be cleared.",
      );
    } finally {
      setClearing(false);
    }
  }

  return (
    <>
      <div className="animal-heading">
        <div>
          <div className="eyebrow">
            <span /> LOCAL VISION / ANIMAL WATCH
          </div>
          <h1>
            Perimeter <em>life signs.</em>
          </h1>
          <p>Local animal detection across your enabled camera sectors.</p>
        </div>
        <button className="refresh-button" onClick={() => void load()}>
          <RefreshCw size={15} /> Refresh
        </button>
      </div>

      <section className="animal-status-grid" aria-label="Detector status">
        <div>
          <Cpu />
          <span>DETECTOR</span>
          <strong className={health?.frigateOnline ? "cyan-text" : "yellow-text"}>
            {health?.frigateOnline ? "Online" : "Offline"}
          </strong>
          <small>{health?.provider || "AUTO"} / {health?.model || "MegaDetector V6"}</small>
        </div>
        <div>
          <Radio />
          <span>INFERENCE</span>
          <strong>{health?.inferenceSpeedMs ? `${health.inferenceSpeedMs.toFixed(1)} ms` : "Waiting"}</strong>
          <small>{health?.mqttOnline ? "Event bus connected" : "Event bus offline"}</small>
        </div>
        <div>
          <Bell />
          <span>HOME ASSISTANT</span>
          <strong className={health?.alertsConfigured ? "cyan-text" : "yellow-text"}>
            {health?.alertsConfigured ? (settings?.alertsEnabled ? "Live" : "Shadow") : "Not set"}
          </strong>
          <small>2-minute camera cooldown</small>
        </div>
      </section>

      {error && (
        <p className="notice animal-notice" role="alert">
          <AlertTriangle size={16} /> {error}
        </p>
      )}

      <div className="animal-layout">
        <section className="panel animal-events">
          <div className="panel-heading">
            <h2><span className="slash">{"//"}</span> Recent detections</h2>
            <div className="animal-event-actions">
              <span className="tag">{events.length.toString().padStart(2, "0")} EVENTS</span>
              <button className="animal-clear" disabled={clearing || !events.length} onClick={() => void clearEvents()}>
                <Trash2 size={13} /> {clearing ? "Clearing…" : "Clear all"}
              </button>
            </div>
          </div>
          {events.length ? (
            <div className="animal-event-grid">
              {events.map((event) => (
                <button className="animal-event" key={event.id} onClick={() => setSelected(event)}>
                  <div className="animal-event-image">
                    <Image src={event.snapshotUrl} alt={`Animal at ${event.cameraName}`} fill sizes="(max-width: 700px) 100vw, 40vw" unoptimized />
                    <span>{Math.round(event.confidence * 100)}% MATCH</span>
                  </div>
                  <div className="animal-event-copy">
                    <span>CH {event.cameraId}</span>
                    <strong>{event.cameraName}</strong>
                    <small>{formatTime(event.startedAt)} · {Math.round(event.travelPercent * 100)}% movement · {statusLabel(event)}</small>
                  </div>
                  {event.acknowledgedAt ? <Check size={17} className="cyan-text" /> : <ExternalLink size={17} />}
                </button>
              ))}
            </div>
          ) : (
            <div className="empty animal-empty">
              <PawPrint size={40} />
              <h3>No animals logged</h3>
              <p>Confirmed detections will appear here with a snapshot.</p>
            </div>
          )}
        </section>

        <section className="panel animal-controls">
          <div className="panel-heading">
            <h2><span className="slash">{"//"}</span> Watch controls</h2>
            <span className="tag">ALWAYS ON</span>
          </div>
          <label className="switch-row">
            <span><strong>Animal detection</strong><small>All enabled cameras</small></span>
            <input type="checkbox" checked={settings?.globalEnabled || false} disabled={!settings || saving} onChange={(event) => void patch({ globalEnabled: event.target.checked })} />
            <i />
          </label>
          <label className="switch-row">
            <span><strong>Send alerts</strong><small>{health?.alertsConfigured ? "Home Assistant webhook" : "Configure webhook first"}</small></span>
            <input type="checkbox" checked={settings?.alertsEnabled || false} disabled={!settings || saving || !health?.alertsConfigured} onChange={(event) => void patch({ alertsEnabled: event.target.checked })} />
            <i />
          </label>
          <div className="camera-detection-list">
            {cameras.map((camera) => {
              const cameraSettings = settings?.cameras[camera.id];
              return (
                <div className="camera-detection" key={camera.id}>
                  <label className="switch-row compact">
                    <span><strong>CH {camera.id} / {camera.name}</strong><small>{camera.seen ? "Camera available" : "Previously offline"}</small></span>
                    <input type="checkbox" checked={cameraSettings?.enabled || false} disabled={!settings || saving || !camera.seen} onChange={(event) => void patch({ cameras: { [camera.id]: { enabled: event.target.checked } } })} />
                    <i />
                  </label>
                  {cameraSettings && (
                    <div className="camera-tuning">
                      <label>CONFIDENCE<input aria-label={`${camera.name} confidence`} type="number" min="80" max="99" value={Math.round(cameraSettings.threshold * 100)} onChange={(event) => setSettings((current) => current ? { ...current, cameras: { ...current.cameras, [camera.id]: { ...cameraSettings, threshold: Number(event.target.value) / 100 } } } : current)} onBlur={(event) => void patch({ cameras: { [camera.id]: { threshold: Number(event.target.value) / 100 } } })} /><span>%</span></label>
                      <label>MIN AREA<input aria-label={`${camera.name} minimum area`} type="number" min="0.01" max="25" step="0.01" value={Number((cameraSettings.minArea * 100).toFixed(2))} onChange={(event) => setSettings((current) => current ? { ...current, cameras: { ...current.cameras, [camera.id]: { ...cameraSettings, minArea: Number(event.target.value) / 100 } } } : current)} onBlur={(event) => void patch({ cameras: { [camera.id]: { minArea: Number(event.target.value) / 100 } } })} /><span>%</span></label>
                      <label>MAX AREA<input aria-label={`${camera.name} maximum area`} type="number" min="0.1" max="99" step="0.1" value={Number((cameraSettings.maxArea * 100).toFixed(1))} onChange={(event) => setSettings((current) => current ? { ...current, cameras: { ...current.cameras, [camera.id]: { ...cameraSettings, maxArea: Number(event.target.value) / 100 } } } : current)} onBlur={(event) => void patch({ cameras: { [camera.id]: { maxArea: Number(event.target.value) / 100 } } })} /><span>%</span></label>
                      <label>MIN MOVE<input aria-label={`${camera.name} minimum movement`} type="number" min="0" max="25" step="0.5" value={Number((cameraSettings.minTravel * 100).toFixed(1))} onChange={(event) => setSettings((current) => current ? { ...current, cameras: { ...current.cameras, [camera.id]: { ...cameraSettings, minTravel: Number(event.target.value) / 100 } } } : current)} onBlur={(event) => void patch({ cameras: { [camera.id]: { minTravel: Number(event.target.value) / 100 } } })} /><span>%</span></label>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
          <button className="secondary animal-test" disabled={testing || !health?.alertsConfigured} onClick={() => void testAlert()}>
            <Bell size={15} /> {testing ? "Sending…" : "Send test alert"}
          </button>
          {testMessage && <p className="muted">{testMessage}</p>}
        </section>
      </div>

      <dialog className="animal-dialog" ref={dialog} onCancel={() => setSelected(null)} onClick={(event) => { if (event.target === dialog.current) setSelected(null); }}>
        {selected && (
          <div>
            <div className="dialog-header">
              <div><span className="eyebrow">ANIMAL / CH {selected.cameraId}</span><h2>{selected.cameraName}</h2></div>
              <button autoFocus aria-label="Close animal event" onClick={() => setSelected(null)}><X /></button>
            </div>
            <div className="animal-detail-image"><Image src={selected.snapshotUrl} alt={`Animal detected at ${selected.cameraName}`} width={960} height={540} unoptimized /></div>
            <dl className="animal-detail-stats">
              <div><dt>Observed</dt><dd>{formatTime(selected.startedAt)}</dd></div>
              <div><dt>Confidence</dt><dd>{Math.round(selected.confidence * 100)}%</dd></div>
              <div><dt>Movement</dt><dd>{Math.round(selected.travelPercent * 100)}%</dd></div>
              <div><dt>Alert</dt><dd>{statusLabel(selected)}</dd></div>
            </dl>
            <div className="animal-detail-actions">
              <button className="secondary" disabled={Boolean(selected.acknowledgedAt)} onClick={() => void acknowledge(selected)}><ShieldCheck size={16} /> {selected.acknowledgedAt ? "Acknowledged" : "Acknowledge"}</button>
              <button className="primary" onClick={() => { const camera = cameras.find((item) => item.id === selected.cameraId); if (camera) { setSelected(null); onOpenCamera(camera); } }}><Radio size={16} /> Open live camera</button>
            </div>
          </div>
        )}
      </dialog>
    </>
  );
}
