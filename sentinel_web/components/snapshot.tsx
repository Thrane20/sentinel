"use client";

import Image from "next/image";
import { useEffect, useRef, useState } from "react";

export function Snapshot({
  channel,
  name,
  tick,
  enabled,
}: {
  channel: string;
  name: string;
  tick: number;
  enabled: boolean;
}) {
  const [current, setCurrent] = useState("");
  const currentUrl = useRef("");

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    let objectUrl = "";

    async function load() {
      try {
        const response = await fetch(`/api/snapshot/${channel}?v=${tick}`, {
          cache: "no-store",
        });
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
        if (previous)
          window.setTimeout(() => URL.revokeObjectURL(previous), 1000);
      } catch {
        if (objectUrl) URL.revokeObjectURL(objectUrl);
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [channel, enabled, tick]);

  useEffect(
    () => () => {
      if (currentUrl.current) URL.revokeObjectURL(currentUrl.current);
    },
    [],
  );

  if (!current) return null;

  return (
    <Image
      className="camera-snapshot"
      src={current}
      alt={`Latest snapshot from ${name}`}
      fill
      sizes="(max-width: 700px) 50vw, (max-width: 1200px) 33vw, 25vw"
      unoptimized
    />
  );
}
