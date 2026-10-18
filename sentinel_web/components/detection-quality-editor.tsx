"use client";

import { useEffect, useRef, useState } from "react";
import type { Camera } from "@/lib/cameras";

type Quality = {
  profile: string | null;
  fps: number;
  width: number;
  height: number;
  stream: string;
};
export function DetectionQualityEditor({
  camera,
  onClose,
}: {
  camera: Camera;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [current, setCurrent] = useState<Quality | null>(null);
  const [profile, setProfile] = useState("720p");
  const [fps, setFps] = useState(2);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    dialog.current?.showModal();
    let cancelled = false;
    async function load() {
      try {
        const response = await fetch(`/api/animals/quality/${camera.id}`, {
          cache: "no-store",
        });
        const result = await response.json();
        if (!response.ok)
          throw new Error(result.error || "Could not read quality settings.");
        if (!cancelled) {
          setCurrent(result);
          setProfile(result.profile || "720p");
          setFps(result.fps === 5 ? 5 : 2);
          setLoaded(true);
        }
      } catch (caught) {
        if (!cancelled)
          setError(
            caught instanceof Error
              ? caught.message
              : "Could not read quality settings.",
          );
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [camera.id]);
  async function apply() {
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const response = await fetch(`/api/animals/quality/${camera.id}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ profile, fps }),
      });
      const result = await response.json();
      if (!response.ok)
        throw new Error(result.error || "Could not save detection quality.");
      setMessage(result.message);
      setSaved(true);
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "Could not save detection quality.",
      );
    } finally {
      setSaving(false);
    }
  }
  return (
    <dialog
      ref={dialog}
      className="mask-editor quality-editor"
      aria-labelledby="quality-title"
      onCancel={(event) => {
        event.preventDefault();
        if (!saving) onClose();
      }}
    >
      <div className="mask-heading">
        <h2 id="quality-title">Detection quality / {camera.name}</h2>
        <button className="animal-clear" disabled={saving} onClick={onClose}>
          Close
        </button>
      </div>
      {error && (
        <p role="alert" className="notice">
          {error}
        </p>
      )}
      {message && (
        <p role="status" className="notice">
          {message}
        </p>
      )}
      {current ? (
        <p>
          Current: {current.width} × {current.height} at {current.fps} FPS ·
          recorder stream {current.stream}
        </p>
      ) : (
        !error && <p>Reading Frigate settings…</p>
      )}
      <p>
        720p and 1080p use the recorder’s main stream. 360p uses the configured
        low-bandwidth stream.
      </p>
      <div className="quality-fields">
        <label>
          Detection resolution
          <select
            aria-label="Detection resolution"
            value={profile}
            disabled={!loaded || saving || saved}
            onChange={(event) => setProfile(event.target.value)}
          >
            <option value="360p">
              360p — 640 × 360 / low-bandwidth stream
            </option>
            <option value="720p">720p — 1280 × 720 / main stream</option>
            <option value="1080p">1080p — 1920 × 1080 / main stream</option>
          </select>
        </label>
        <label>
          Detection frame rate
          <select
            aria-label="Detection frame rate"
            value={fps}
            disabled={!loaded || saving || saved}
            onChange={(event) => setFps(Number(event.target.value))}
          >
            <option value="2">2 FPS</option>
            <option value="5">5 FPS</option>
          </select>
        </label>
      </div>
      <p>
        Start with 720p at 2 FPS on one camera. Higher resolution and frame rate
        increase CPU and network use; they cannot add detail beyond the source
        camera stream.
      </p>
      <p>
        Applying restarts Frigate for all cameras. Detection and thumbnails
        pause briefly; full live viewing remains available. Existing confidence,
        masks and event limits are kept. Check mask alignment after switching
        streams.
      </p>
      <button
        className="animal-clear"
        disabled={!loaded || saving || saved}
        onClick={() => void apply()}
      >
        {saving ? "Saving…" : "Save and restart Frigate"}
      </button>
    </dialog>
  );
}
