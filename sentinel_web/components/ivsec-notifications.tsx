"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { cameras, type Camera } from "@/lib/cameras";
import { X } from "lucide-react";

type Rule = {
  id: string;
  cameraId: string;
  eventKey: string;
  message: string;
  enabled: boolean;
  cooldownSeconds: number;
  createdAt?: number;
};
type Detail = {
  id: number;
  cameraId: string;
  cameraName: string;
  eventType: string;
  eventKey: string;
  sourceTime: string;
  observedAt: number | null;
  source: string;
  raw: unknown;
  deliveries: {
    rule_id: string;
    status: string;
    attempts: number;
    error: string | null;
  }[];
};
const blank = (): Rule => ({
  id: "",
  cameraId: "04",
  eventKey: "perimeter_intrusion",
  message: "Something is moving in the garage",
  enabled: false,
  cooldownSeconds: 60,
});
function editable(rule: Rule) {
  const { id, cameraId, eventKey, message, enabled, cooldownSeconds } = rule;
  return { id, cameraId, eventKey, message, enabled, cooldownSeconds };
}

export function IvsecNotifications({
  inspectId,
  onClose,
  onOpenPlayback,
}: {
  inspectId: number | null;
  onClose: () => void;
  onOpenPlayback: (camera: Camera, at: number) => void;
}) {
  const [rules, setRules] = useState<Rule[]>([]);
  const [catalog, setCatalog] = useState<
    { cameraId: string; eventKey: string; eventType: string }[]
  >([]);
  const [configured, setConfigured] = useState(false);
  const [draft, setDraft] = useState<Rule>(blank);
  const [editing, setEditing] = useState(false);
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const ruleIdInput = useRef<HTMLInputElement>(null);
  const load = useCallback(async () => {
    const response = await fetch("/api/ivsec/notification-rules", {
      cache: "no-store",
    });
    const body = await response.json();
    if (!response.ok)
      throw new Error(body.error || "Notification rules unavailable.");
    setRules(body.rules);
    setCatalog(body.catalog);
    setConfigured(body.webhookConfigured);
  }, []);
  useEffect(() => {
    // State is populated only after the asynchronous rules request resolves.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load().catch(() => {});
  }, [load]);
  useEffect(() => {
    if (inspectId === null) {
      dialog.current?.close();
      return;
    }
    let cancelled = false;
    dialog.current?.showModal();
    void fetch(`/api/ivsec/events/${inspectId}`, { cache: "no-store" })
      .then(async (response) => {
        const body = await response.json();
        if (!response.ok)
          throw new Error(body.error || "Event details unavailable.");
        if (!cancelled) {
          setDetail(body);
          setError("");
        }
      })
      .catch((cause) => {
        if (!cancelled) {
          setDetail(null);
          setError(String(cause.message));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [inspectId]);

  async function save(rule: Rule = draft) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const response = await fetch("/api/ivsec/notification-rules", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(editable(rule)),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error || "Save failed.");
      await load();
      setMessage(`Saved ${rule.id}.`);
      setEditing(false);
      setDraft(blank());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Save failed.");
    } finally {
      setBusy(false);
    }
  }
  async function remove(id: string) {
    setBusy(true);
    setError("");
    try {
      const response = await fetch(
        `/api/ivsec/notification-rules/${encodeURIComponent(id)}`,
        { method: "DELETE" },
      );
      if (!response.ok) throw new Error("Rule could not be deleted.");
      await load();
      setMessage(`Deleted ${id}.`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Delete failed.");
    } finally {
      setBusy(false);
    }
  }
  function fromEvent(event: Detail) {
    const name = event.cameraName
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_|_$/g, "");
    setDraft({
      id: `${name}_${event.eventKey}`.slice(0, 64),
      cameraId: event.cameraId,
      eventKey: event.eventKey,
      message: `${event.eventType} at ${event.cameraName}`,
      enabled: false,
      cooldownSeconds: 60,
    });
    setEditing(false);
    setOpen(true);
    onClose();
    requestAnimationFrame(() => ruleIdInput.current?.focus());
  }
  async function testRule(id: string) {
    if (!detail) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const response = await fetch("/api/ivsec/notification-test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ eventId: detail.id, ruleId: id }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error || "Test failed.");
      setMessage(
        "Test queued. Refresh the event inspector to check delivery. HA tests use a separate event type.",
      );
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Test failed.");
    } finally {
      setBusy(false);
    }
  }
  const current = detail?.id === inspectId ? detail : null;
  return (
    <>
      <details
        className="ivsec-routing"
        open={open}
        onToggle={(event) => setOpen(event.currentTarget.open)}
      >
        <summary>
          Home Assistant notification rules <span>{rules.length}</span>
        </summary>
        <button
          className="secondary"
          onClick={() =>
            void load().catch(() => setError("Notification rules unavailable."))
          }
        >
          Refresh notification rules
        </button>
        <p>
          Match a camera and IVSEC event key to a stable notification ID. Home
          Assistant controls notification sounds and time windows.
        </p>
        {!configured && (
          <p className="notice">
            Set HA_IVSEC_WEBHOOK_URL on the server to enable delivery. Rules can
            be prepared now.
          </p>
        )}
        {rules.map((rule) => (
          <div className="ivsec-rule-row" key={rule.id}>
            <div>
              <strong>{rule.id}</strong>
              <small>
                CH {rule.cameraId} · {rule.eventKey} ·{" "}
                {rule.enabled ? "Enabled" : "Disabled"}
              </small>
              <p>{rule.message}</p>
            </div>
            <button
              className="secondary"
              disabled={busy}
              onClick={() => {
                setDraft(editable(rule));
                setEditing(true);
              }}
            >
              Edit {rule.id}
            </button>
            <button
              className="secondary"
              disabled={busy}
              onClick={() => void remove(rule.id)}
            >
              Delete {rule.id}
            </button>
          </div>
        ))}
        <form
          className="ivsec-rule-form"
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          <label>
            Notification ID
            <input
              ref={ruleIdInput}
              required
              pattern="[a-z][a-z0-9_]{0,63}"
              maxLength={64}
              disabled={editing || busy}
              value={draft.id}
              placeholder="garage_intrusion"
              onChange={(event) =>
                setDraft({ ...draft, id: event.target.value })
              }
            />
          </label>
          <label>
            Camera
            <select
              value={draft.cameraId}
              disabled={busy}
              onChange={(event) =>
                setDraft({ ...draft, cameraId: event.target.value })
              }
            >
              {cameras.map((camera) => (
                <option key={camera.id} value={camera.id}>
                  {camera.name} · CH {camera.id}
                </option>
              ))}
            </select>
          </label>
          <label>
            IVSEC event key
            <input
              required
              list="ivsec-event-keys"
              pattern="[a-z][a-z0-9_]{0,63}"
              maxLength={64}
              value={draft.eventKey}
              disabled={busy}
              onChange={(event) =>
                setDraft({ ...draft, eventKey: event.target.value })
              }
            />
          </label>
          <datalist id="ivsec-event-keys">
            {Array.from(
              new Set(
                catalog
                  .filter((item) => item.cameraId === draft.cameraId)
                  .map((item) => item.eventKey),
              ),
            ).map((key) => (
              <option key={key} value={key} />
            ))}
          </datalist>
          <label>
            Notification message
            <input
              required
              maxLength={240}
              disabled={busy}
              value={draft.message}
              onChange={(event) =>
                setDraft({ ...draft, message: event.target.value })
              }
            />
          </label>
          <label>
            Rule cooldown (seconds)
            <input
              required
              type="number"
              min="0"
              max="86400"
              step="1"
              disabled={busy}
              value={draft.cooldownSeconds}
              onChange={(event) =>
                setDraft({
                  ...draft,
                  cooldownSeconds: Number(event.target.value),
                })
              }
            />
          </label>
          <label className="ivsec-rule-enabled">
            <input
              type="checkbox"
              checked={draft.enabled}
              disabled={busy}
              onChange={(event) =>
                setDraft({ ...draft, enabled: event.target.checked })
              }
            />{" "}
            Enable automatic delivery for this rule
          </label>
          <button className="secondary" disabled={busy} type="submit">
            {busy ? "Saving…" : "Save notification rule"}
          </button>
          {editing && (
            <button
              type="button"
              className="secondary"
              onClick={() => {
                setEditing(false);
                setDraft(blank());
              }}
            >
              New rule
            </button>
          )}
        </form>
        <p className="muted">
          Only fresh live IVSEC events are routed. Historical imports are
          available for inspection, playback and explicit tests.
        </p>
      </details>
      {error && (
        <p className="notice" role="alert">
          {error}
        </p>
      )}
      {message && (
        <p role="status" className="ivsec-alert-message">
          {message}
        </p>
      )}
      <dialog
        className="ivsec-inspector"
        ref={dialog}
        onCancel={onClose}
        onClick={(event) => {
          if (event.target === dialog.current) onClose();
        }}
      >
        <div className="dialog-header">
          <h2>IVSEC event inspector</h2>
          <button
            autoFocus
            aria-label="Close IVSEC event inspector"
            onClick={onClose}
          >
            <X />
          </button>
        </div>
        {inspectId !== null && !current && !error && (
          <p>Loading event details…</p>
        )}
        {error && <p role="alert">{error}</p>}
        {current && (
          <div className="ivsec-inspector-body">
            <h3>
              {current.eventType} · {current.cameraName}
            </h3>
            {current.source === "archive" && (
              <p>
                Historical recording entry: available for inspection and tests.
                For automatic notifications, inspect a live event with the
                subtype you want to match.
              </p>
            )}
            <dl>
              <dt>Camera ID</dt>
              <dd>{current.cameraId}</dd>
              <dt>Event key</dt>
              <dd>
                <code>{current.eventKey}</code>
              </dd>
              <dt>Recorder time</dt>
              <dd>{current.sourceTime}</dd>
              <dt>Source</dt>
              <dd>{current.source}</dd>
            </dl>
            <div className="ivsec-inspector-actions">
              <button className="secondary" onClick={() => fromEvent(current)}>
                Create notification rule
              </button>
              <button
                className="secondary"
                disabled={!current.observedAt}
                onClick={() => {
                  const camera = cameras.find(
                    (item) => item.id === current.cameraId,
                  );
                  if (camera && current.observedAt) {
                    onClose();
                    onOpenPlayback(camera, current.observedAt);
                  }
                }}
              >
                Play event recording
              </button>
            </div>
            <h3>Matching saved rules</h3>
            {rules
              .filter(
                (rule) =>
                  rule.cameraId === current.cameraId &&
                  rule.eventKey === current.eventKey,
              )
              .map((rule) => (
                <div className="ivsec-rule-row" key={rule.id}>
                  <span>
                    {rule.id} · {rule.enabled ? "Enabled" : "Disabled"}
                  </span>
                  <button
                    className="secondary"
                    disabled={busy || !configured || !current.observedAt}
                    onClick={() => void testRule(rule.id)}
                  >
                    Send HA test / {rule.id}
                  </button>
                </div>
              ))}
            <h3>Delivery history</h3>
            {current.deliveries.length ? (
              current.deliveries.map((delivery, index) => (
                <p key={index}>
                  {delivery.rule_id}: {delivery.status} · {delivery.attempts}{" "}
                  attempts {delivery.error}
                </p>
              ))
            ) : (
              <p>No routed deliveries for this event.</p>
            )}
            <h3>Raw IVSEC event data</h3>
            <pre>{JSON.stringify(current.raw, null, 2)}</pre>
            {message && <p role="status">{message}</p>}
          </div>
        )}
      </dialog>
    </>
  );
}
