"use client";

import Image from "next/image";
import { useEffect, useRef, useState } from "react";

export function Snapshot({
  channel,
  name,
  enabled,
}: {
  channel: string;
  name: string;
  tick: number;
  enabled: boolean;
}) {
  const [current, setCurrent] = useState("");
  const currentUrl = useRef("");
  const [fallback, setFallback] = useState(false);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();

    async function load() {
      let objectUrl = "";
      try {
        if (document.hidden) return;
        const response = await fetch(
          `/api/snapshot/${channel}?v=${Date.now()}`,
          {
            cache: "no-store",
            signal: controller.signal,
          },
        );
        if (!response.ok) return;
        objectUrl = URL.createObjectURL(await response.blob());

        // Decode the complete JPEG before changing the visible src. The previous
        // object URL stays painted while the next frame is fetched and decoded.
        const preload = new window.Image();
        preload.src = objectUrl;
        await preload.decode();
        if (cancelled) {
          URL.revokeObjectURL(objectUrl);
          return;
        }

        const previous = currentUrl.current;
        currentUrl.current = objectUrl;
        setCurrent(objectUrl);
        setFallback(response.headers.get("X-Snapshot-Source") === "recorder");
        if (previous)
          window.setTimeout(() => URL.revokeObjectURL(previous), 1000);
      } catch {
        if (objectUrl) URL.revokeObjectURL(objectUrl);
      } finally {
        if (!cancelled) timer = setTimeout(() => void load(), 1000);
      }
    }

    void load();
    return () => {
      cancelled = true;
      controller.abort();
      clearTimeout(timer);
    };
  }, [channel, enabled]);

  useEffect(
    () => () => {
      if (currentUrl.current) URL.revokeObjectURL(currentUrl.current);
    },
    [],
  );

  if (!current) return null;

  return (
    <>
      <Image
        className="camera-snapshot"
        src={current}
        alt={`Latest snapshot from ${name}`}
        fill
        sizes="(max-width: 700px) 50vw, (max-width: 1200px) 33vw, 25vw"
        unoptimized
      />
      {fallback && (
        <span
          className="snapshot-fallback"
          title="Frigate preview unavailable. This image comes directly from the recorder; check detector health."
        >
          RECORDER PREVIEW
        </span>
      )}
    </>
  );
}
