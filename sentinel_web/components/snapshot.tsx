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
  const [stale, setStale] = useState(false);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();

    let lastFrame = Date.now();

    async function load() {
      let objectUrl = "";
      let attempted = false;
      try {
        if (document.hidden) {
          lastFrame = Date.now(); // a hidden tab is not a stale feed
          return;
        }
        attempted = true;
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
        lastFrame = Date.now();
        setStale(false);
        if (previous)
          window.setTimeout(() => URL.revokeObjectURL(previous), 1000);
      } catch {
        if (objectUrl) URL.revokeObjectURL(objectUrl);
      } finally {
        // Keep the last frame on failure, but mark it so it is not mistaken for live.
        if (attempted && !cancelled && Date.now() - lastFrame > 20000)
          setStale(true);
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
      {stale && (
        <span
          className="snapshot-fallback"
          title="No new frame for over 20 seconds. Frigate may be offline; showing the last image received."
        >
          PAUSED
        </span>
      )}
    </>
  );
}
