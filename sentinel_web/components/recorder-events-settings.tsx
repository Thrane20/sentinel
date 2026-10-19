"use client";
import { useEffect, useState } from "react";
import { cameras } from "@/lib/cameras";
import { formatSlots, parseSlots, recorderDays } from "@/lib/ivsec-schedule";

type Value = boolean | number | string | string[];
type Field = {
  key: string;
  label: string;
  value: Value;
  disabled: boolean;
  schema: {
    type: string;
    min?: number;
    max?: number;
    items?: Value[] | { items?: string[] };
  };
};
type Schedule = { enabled: boolean; week: { day: string; time: number[] }[] };
type Config = {
  supported: boolean;
  reason: string | null;
  revision: string;
  fields: Field[];
  schedule: Schedule | null;
};
const sections = [
  ["detection", "Event detection"],
  ["light", "Camera light / strobe"],
  ["siren", "Camera siren"],
  ["lightSchedule", "Light / strobe schedule"],
  ["warningSchedule", "Warning light schedule"],
  ["sirenSchedule", "Siren schedule"],
  ["actions", "Event notifications & recording"],
];
function SettingsCard({
  camera,
  event,
  section,
  title,
  onSaving,
}: {
  camera: string;
  event: string;
  section: string;
  title: string;
  onSaving: (value: boolean) => void;
}) {
  const [config, setConfig] = useState<Config | null>(null);
  const [values, setValues] = useState<Record<string, Value>>({});
  const [enabled, setEnabled] = useState(false);
  const [days, setDays] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [reload, setReload] = useState(0);
  function accept(data: Config) {
    setConfig(data);
    setValues(Object.fromEntries(data.fields.map((f) => [f.key, f.value])));
    setEnabled(data.schedule?.enabled ?? false);
    setDays(
      Object.fromEntries(
        (data.schedule?.week || []).map((d) => [d.day, formatSlots(d.time)]),
      ),
    );
  }
  useEffect(() => {
    const controller = new AbortController();
    const query = new URLSearchParams({ camera, event, section });
    void fetch(`/api/ivsec/remote?${query}`, { signal: controller.signal })
      .then(async (response) => {
        const data = await response.json();
        if (!response.ok)
          throw new Error(data.error || "Could not load IVSEC settings.");
        if (!controller.signal.aborted) {
          accept(data);
          setError("");
        }
      })
      .catch((e) => {
        if (!controller.signal.aborted)
          setError(e.message || "IVSEC is unavailable.");
      });
    return () => controller.abort();
  }, [camera, event, section, reload]);
  async function save() {
    if (!config) return;
    setError("");
    setMessage("");
    let changes: Record<string, Value> | Schedule;
    try {
      changes = config.schedule
        ? {
            enabled,
            week: config.schedule.week.map((d) => ({
              day: d.day,
              time: parseSlots(days[d.day] || ""),
            })),
          }
        : Object.fromEntries(
            config.fields
              .filter(
                (f) =>
                  !f.disabled &&
                  JSON.stringify(values[f.key]) !== JSON.stringify(f.value),
              )
              .map((f) => [f.key, values[f.key]]),
          );
      if (!config.schedule && !Object.keys(changes).length) {
        setMessage("No changes to save.");
        return;
      }
    } catch (e) {
      setError((e as Error).message);
      return;
    }
    setBusy(true);
    onSaving(true);
    try {
      const response = await fetch("/api/ivsec/remote", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          camera,
          event,
          section,
          revision: config.revision,
          values: changes,
        }),
      });
      const data = await response.json();
      if (!response.ok)
        throw new Error(data.error || "IVSEC did not confirm this save.");
      accept(data);
      setMessage("Saved and confirmed by IVSEC.");
    } catch (e) {
      setError((e as Error).message);
      setConfig(null);
    } finally {
      setBusy(false);
      onSaving(false);
    }
  }
  const global = section === "light" || section === "siren";
  return (
    <section
      className="recorder-settings-card"
      aria-label={title}
      data-section={section}
    >
      <div className="panel-heading">
        <h3>{title}</h3>
        <button
          type="button"
          disabled={busy}
          onClick={() => {
            setConfig(null);
            setError("");
            setMessage("");
            setReload((n) => n + 1);
          }}
        >
          Reload
        </button>
      </div>
      <p className="muted">
        {global
          ? "Applies to all events on this camera. Use the schedules below to choose when each event can activate an output."
          : `Applies to the selected event on camera ${camera}.`}
      </p>
      {error && (
        <p className="notice" role="alert">
          {error}
        </p>
      )}
      {message && (
        <p role="status" className="cyan-text">
          {message}
        </p>
      )}
      {!config && !error && <p role="status">Reading IVSEC…</p>}
      {config && !config.supported && <p className="muted">{config.reason}</p>}
      {config?.supported && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void save();
          }}
        >
          <fieldset disabled={busy} className="recorder-fields">
            {config.fields.map((field) => {
              const value = values[field.key];
              const options = Array.isArray(field.schema.items)
                ? field.schema.items
                : [];
              if (field.schema.type === "bool")
                return (
                  <label className="recorder-checkbox" key={field.key}>
                    <input
                      type="checkbox"
                      disabled={field.disabled}
                      checked={value === true}
                      onChange={(e) =>
                        setValues((v) => ({
                          ...v,
                          [field.key]: e.target.checked,
                        }))
                      }
                    />
                    {field.label}
                  </label>
                );
              if (field.schema.type === "array") {
                const choices = !Array.isArray(field.schema.items)
                  ? field.schema.items?.items || []
                  : [];
                return (
                  <fieldset key={field.key} disabled={field.disabled}>
                    <legend>{field.label}</legend>
                    {choices.map((option) => (
                      <label key={option} className="recorder-checkbox">
                        <input
                          type="checkbox"
                          checked={
                            Array.isArray(value) && value.includes(option)
                          }
                          onChange={(e) =>
                            setValues((v) => ({
                              ...v,
                              [field.key]: e.target.checked
                                ? [
                                    ...(Array.isArray(v[field.key])
                                      ? (v[field.key] as string[])
                                      : []),
                                    option,
                                  ]
                                : (v[field.key] as string[]).filter(
                                    (x) => x !== option,
                                  ),
                            }))
                          }
                        />
                        {option}
                      </label>
                    ))}
                  </fieldset>
                );
              }
              return (
                <label className="recorder-field" key={field.key}>
                  {field.label}
                  {options.length ? (
                    <select
                      disabled={field.disabled}
                      value={String(value)}
                      onChange={(e) =>
                        setValues((v) => ({
                          ...v,
                          [field.key]: options.find(
                            (o) => String(o) === e.target.value,
                          ) as Value,
                        }))
                      }
                    >
                      {options.map((o) => (
                        <option key={String(o)} value={String(o)}>
                          {String(o)}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input
                      type="number"
                      disabled={field.disabled}
                      min={field.schema.min}
                      max={field.schema.max}
                      step={1}
                      required
                      value={String(value)}
                      onChange={(e) =>
                        setValues((v) => ({
                          ...v,
                          [field.key]: Number(e.target.value),
                        }))
                      }
                    />
                  )}
                </label>
              );
            })}
            {config.schedule && (
              <>
                <label className="recorder-checkbox">
                  <input
                    type="checkbox"
                    checked={enabled}
                    onChange={(e) => setEnabled(e.target.checked)}
                  />
                  Enable this event to trigger the output
                </label>
                <p className="muted">
                  Recorder local time · 30-minute steps. Enter one or more on
                  periods, separated by commas. Blank means off all day.
                  Example: 00:00-06:00, 19:00-24:00.
                </p>
                <div className="recorder-presets">
                  {[
                    ["All day", "00:00-24:00"],
                    ["Off all day", ""],
                    ["Night (19:00–06:00)", "00:00-06:00, 19:00-24:00"],
                  ].map(([label, value]) => (
                    <button
                      type="button"
                      key={label}
                      onClick={() =>
                        setDays(
                          Object.fromEntries(
                            recorderDays.map((d) => [d, value]),
                          ),
                        )
                      }
                    >
                      {label}
                    </button>
                  ))}
                </div>
                {recorderDays.map((day) => (
                  <label className="recorder-day" key={day}>
                    {day}
                    <input
                      aria-label={`${title} ${day}`}
                      type="text"
                      placeholder="Off all day"
                      value={days[day] || ""}
                      onChange={(e) =>
                        setDays((d) => ({ ...d, [day]: e.target.value }))
                      }
                    />
                  </label>
                ))}
              </>
            )}
          </fieldset>
          <button type="submit" className="primary" disabled={busy}>
            {busy ? "Saving to IVSEC…" : `Save ${title.toLowerCase()}`}
          </button>
        </form>
      )}
    </section>
  );
}
export function RecorderEventsSettings() {
  const [camera, setCamera] = useState("04");
  const [event, setEvent] = useState("PID");
  const [catalog, setCatalog] = useState<{ id: string; label: string }[]>([]);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(0);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    void fetch("/api/ivsec/remote?catalog=1", { signal: controller.signal })
      .then(async (r) => {
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || "Unable to load event types.");
        if (!controller.signal.aborted) {
          setCatalog(data.events);
          setError("");
        }
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      });
    return () => controller.abort();
  }, [attempt]);
  return (
    <section
      className="panel recorder-remote"
      aria-label="IVSEC remote settings"
    >
      <div className="panel-heading">
        <h2>
          <span className="slash">{"//"}</span> IVSEC remote settings
        </h2>
        <span className="tag">RECORDER CONFIGURATION</span>
      </div>
      <p>
        Configure events and deterrence directly on IVSEC. Saves take effect on
        the recorder after confirmation.
      </p>
      <p className="muted">
        Sentinel already listens for all recorder events. Detection and output
        schedules control what IVSEC generates and does. Home Assistant delivery
        rules remain under Playback → IVSEC alerts. Outputs also depend on the
        camera’s master switches and IVSEC arming state.
      </p>
      {error && (
        <p role="alert" className="notice">
          {error}{" "}
          <button onClick={() => setAttempt((n) => n + 1)}>
            Retry event types
          </button>
        </p>
      )}
      <div className="recorder-selectors">
        <label>
          Camera
          <select
            disabled={saving > 0}
            value={camera}
            onChange={(e) => setCamera(e.target.value)}
          >
            {Array.from({ length: 16 }, (_, i) => {
              const id = String(i + 1).padStart(2, "0");
              return (
                <option key={id} value={id}>
                  {id} ·{" "}
                  {cameras.find((c) => c.id === id)?.name || "Recorder channel"}
                </option>
              );
            })}
          </select>
        </label>
        <label>
          Event type
          <select
            disabled={saving > 0 || !catalog.length}
            value={event}
            onChange={(e) => setEvent(e.target.value)}
          >
            {catalog.map((e) => (
              <option key={e.id} value={e.id}>
                {e.label} ({e.id})
              </option>
            ))}
          </select>
        </label>
      </div>
      <p className="muted">
        Existing detection areas and crossing lines are preserved. Some event
        types require zones to be configured in IVSEC before enabling them.
      </p>
      {!!catalog.length && (
        <div className="recorder-settings-grid">
          {sections.map(([section, title]) => (
            <SettingsCard
              key={`${camera}:${event}:${section}`}
              {...{ camera, event, section, title }}
              onSaving={(value) => setSaving((n) => n + (value ? 1 : -1))}
            />
          ))}
        </div>
      )}
    </section>
  );
}
