"use client";

import Image from "next/image";
import { useEffect, useRef, useState } from "react";
import type { Camera } from "@/lib/cameras";

type Point = [number, number];
type Polygon = Point[];
const encode = (polygon: Polygon) =>
  polygon
    .flat()
    .map((v) => v.toFixed(6))
    .join(",");
const decode = (mask: string): Polygon => {
  const values = mask.split(",").map(Number);
  return Array.from({ length: values.length / 2 }, (_, i) => [
    values[i * 2],
    values[i * 2 + 1],
  ]);
};

export function AnimalMaskEditor({
  camera,
  onClose,
}: {
  camera: Camera;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const drag = useRef<{ polygon: number; point: number } | null>(null);
  const [polygons, setPolygons] = useState<Polygon[]>([]);
  const [draft, setDraft] = useState<Polygon>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [image, setImage] = useState("");
  const [imageReady, setImageReady] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [snapshotLoading, setSnapshotLoading] = useState(true);
  const [snapshotError, setSnapshotError] = useState("");
  const [snapshotVersion, setSnapshotVersion] = useState(0);

  useEffect(() => {
    dialog.current?.showModal();
    let cancelled = false;
    async function load() {
      try {
        const response = await fetch(`/api/animals/masks/${camera.id}`, {
          cache: "no-store",
        });
        const result = await response.json();
        if (!response.ok)
          throw new Error(result.error || "Could not load masks.");
        if (!cancelled) {
          setPolygons(result.masks.map(decode));
          setLoaded(true);
        }
      } catch (caught) {
        if (!cancelled)
          setError(
            caught instanceof Error ? caught.message : "Could not load masks.",
          );
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [camera.id]);

  useEffect(() => {
    let cancelled = false;
    let url = "";
    async function loadSnapshot() {
      try {
        const response = await fetch(
          `/api/snapshot/${camera.id}?requireFrames=1&v=${Date.now()}`,
          { cache: "no-store" },
        );
        if (!response.ok) {
          const result = await response.json().catch(() => ({}));
          throw new Error(
            result.error ||
              "Camera snapshot unavailable. Refresh the image to retry.",
          );
        }
        url = URL.createObjectURL(await response.blob());
        if (!cancelled) setImage(url);
        else URL.revokeObjectURL(url);
      } catch (caught) {
        if (!cancelled)
          setSnapshotError(
            caught instanceof Error ? caught.message : "Snapshot unavailable.",
          );
      } finally {
        if (!cancelled) setSnapshotLoading(false);
      }
    }
    void loadSnapshot();
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [camera.id, snapshotVersion]);

  function close() {
    if (saving) return;
    if (dirty && !window.confirm("Discard unsaved mask changes?")) return;
    onClose();
  }
  function point(event: React.PointerEvent<SVGSVGElement>): Point {
    const bounds = event.currentTarget.getBoundingClientRect();
    return [
      Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width)),
      Math.max(0, Math.min(1, (event.clientY - bounds.top) / bounds.height)),
    ];
  }
  function changed() {
    setDirty(true);
    setMessage("");
    setError("");
  }
  function finish() {
    if (draft.length < 3 || polygons.length >= 20) return;
    setPolygons([...polygons, draft]);
    setSelected(polygons.length);
    setDraft([]);
    changed();
  }
  async function save() {
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const response = await fetch(`/api/animals/masks/${camera.id}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ masks: polygons.map(encode) }),
      });
      const result = await response.json();
      if (!response.ok)
        throw new Error(result.error || "Could not apply masks.");
      setPolygons(result.masks.map(decode));
      setDirty(false);
      setMessage(
        "Masks saved and applied to Frigate. Allow a few seconds for propagation.",
      );
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Could not save masks.",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <dialog
      ref={dialog}
      className="mask-editor"
      aria-labelledby="mask-title"
      onCancel={(event) => {
        event.preventDefault();
        close();
      }}
    >
      <div className="mask-heading">
        <h2 id="mask-title">Animal masks / {camera.name}</h2>
        <button className="animal-clear" onClick={close} disabled={saving}>
          Close
        </button>
      </div>
      <p>
        Tap or click points around an exclusion area, then finish the polygon.
        Add more polygons as needed. Select a mask to drag its corners or delete
        it.
      </p>
      <p className="mask-explanation">
        Animals are ignored when the bottom-centre of their detection box is
        inside a shaded area. Keep masks tight around the fence or other
        false-positive area.
      </p>
      {error && (
        <p role="alert" className="notice">
          {error}
        </p>
      )}
      {snapshotError && (
        <p role="alert" className="notice">
          {snapshotError}
        </p>
      )}
      {message && (
        <p role="status" className="notice">
          {message}
        </p>
      )}
      <div className="mask-canvas">
        {image && (
          <Image
            src={image}
            alt={`Mask reference for ${camera.name}`}
            width={640}
            height={360}
            unoptimized
            onLoad={() => setImageReady(true)}
            onError={() => {
              setImageReady(false);
              setSnapshotError("Could not display the camera snapshot.");
            }}
          />
        )}
        {!imageReady && (
          <span className="mask-loading">
            {snapshotLoading
              ? "Loading camera snapshot…"
              : "No camera image available"}
          </span>
        )}
        <svg
          viewBox="0 0 640 360"
          preserveAspectRatio="none"
          aria-label="Draw animal masks"
          role="img"
          onPointerDown={(event) => {
            if (
              !loaded ||
              !imageReady ||
              saving ||
              polygons.length >= 20 ||
              draft.length >= 64
            )
              return;
            setSelected(null);
            setDraft([...draft, point(event)]);
            changed();
          }}
          onPointerMove={(event) => {
            if (!drag.current || saving) return;
            const position = point(event);
            const active = drag.current;
            setPolygons((current) =>
              current.map((polygon, i) =>
                i !== active.polygon
                  ? polygon
                  : polygon.map((vertex, j) =>
                      j === active.point ? position : vertex,
                    ),
              ),
            );
            changed();
          }}
          onPointerUp={() => {
            drag.current = null;
          }}
          onPointerCancel={() => {
            drag.current = null;
          }}
        >
          {polygons.map((polygon, index) => (
            <g key={index}>
              <polygon
                points={polygon
                  .map(([x, y]) => `${x * 640},${y * 360}`)
                  .join(" ")}
                fill={selected === index ? "#e5fb3355" : "#ff705544"}
                stroke={selected === index ? "#e5fb33" : "#ff7055"}
                strokeWidth="2"
                onPointerDown={(event) => {
                  event.stopPropagation();
                  if (!saving && !draft.length) setSelected(index);
                }}
              />
              {selected === index &&
                !draft.length &&
                polygon.map(([x, y], vertex) => (
                  <circle
                    key={vertex}
                    cx={x * 640}
                    cy={y * 360}
                    r="6"
                    fill="#e5fb33"
                    stroke="#111"
                    onPointerDown={(event) => {
                      event.stopPropagation();
                      if (saving) return;
                      drag.current = { polygon: index, point: vertex };
                      event.currentTarget.setPointerCapture(event.pointerId);
                    }}
                  />
                ))}
            </g>
          ))}
          {draft.length > 0 && (
            <polyline
              points={draft.map(([x, y]) => `${x * 640},${y * 360}`).join(" ")}
              fill="#e5fb3322"
              stroke="#e5fb33"
              strokeWidth="2"
            />
          )}
          {draft.map(([x, y], i) => (
            <circle
              key={i}
              cx={x * 640}
              cy={y * 360}
              r="4"
              fill="#e5fb33"
              pointerEvents="none"
            />
          ))}
        </svg>
      </div>
      <div className="mask-actions">
        <button
          className="animal-clear"
          disabled={
            !loaded || saving || draft.length < 3 || polygons.length >= 20
          }
          onClick={finish}
        >
          Finish polygon
        </button>
        <button
          className="animal-clear"
          disabled={saving || !draft.length}
          onClick={() => {
            setDraft(draft.slice(0, -1));
            changed();
          }}
        >
          Undo point
        </button>
        <button
          className="animal-clear"
          disabled={saving || selected === null || draft.length > 0}
          onClick={() => {
            setPolygons(polygons.filter((_, i) => i !== selected));
            setSelected(null);
            changed();
          }}
        >
          Delete selected mask
        </button>
        <button
          className="animal-clear"
          disabled={saving || (!polygons.length && !draft.length)}
          onClick={() => {
            setPolygons([]);
            setDraft([]);
            setSelected(null);
            changed();
          }}
        >
          Clear masks
        </button>
        <button
          className="animal-clear"
          disabled={saving || snapshotLoading}
          onClick={() => {
            setSnapshotLoading(true);
            setSnapshotError("");
            setImageReady(false);
            setSnapshotVersion(snapshotVersion + 1);
          }}
        >
          {snapshotLoading ? "Refreshing image…" : "Refresh image"}
        </button>
      </div>
      <div className="mask-actions">
        {polygons.map((_, index) => (
          <button
            className="animal-clear"
            key={index}
            aria-pressed={selected === index}
            disabled={saving || draft.length > 0}
            onClick={() => setSelected(index)}
          >
            Mask {index + 1}
          </button>
        ))}
      </div>
      <div className="mask-heading">
        <span>
          {polygons.length}/20 masks{" "}
          {draft.length > 0
            ? ` · ${draft.length} draft points — finish before saving`
            : dirty
              ? " · Unsaved changes"
              : ""}
        </span>
        <button
          className="animal-clear"
          disabled={
            !loaded || !imageReady || saving || !dirty || draft.length > 0
          }
          onClick={() => void save()}
        >
          {saving ? "Applying…" : "Save masks"}
        </button>
      </div>
    </dialog>
  );
}
