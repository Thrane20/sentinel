"use client";
import { useEffect, useRef, useState } from "react";
import Hls from "hls.js";
import { Radio, RotateCcw } from "lucide-react";
export function Player({
  channel,
  onState,
}: {
  channel: string;
  onState: (state: string) => void;
}) {
  const video = useRef<HTMLVideoElement>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const element = video.current!;
    const controller = new AbortController();
    let hls: Hls | undefined;
    onState("Connecting");
    async function connect() {
      const url = `/api/stream/${channel}/index.m3u8`;
      for (let i = 0; i < 15; i++) {
        const response = await fetch(url, { signal: controller.signal });
        if (response.ok) {
          if (Hls.isSupported()) {
            hls = new Hls();
            hls.loadSource(url);
            hls.attachMedia(element);
            hls.on(Hls.Events.ERROR, (_event, data) => {
              if (data.fatal) {
                setError("Video connection lost. Retry the stream.");
                onState("Unavailable");
                hls?.destroy();
              }
            });
          } else if (element.canPlayType("application/vnd.apple.mpegurl")) {
            element.src = url;
          } else throw new Error("This browser does not support HLS playback.");
          return;
        }
        const body = await response.json();
        if (!body.error?.includes("warming"))
          throw new Error(body.error || "Stream unavailable");
        await new Promise((resolve) => setTimeout(resolve, 1500));
        if (controller.signal.aborted) return;
      }
      throw new Error(
        "Recorder did not deliver video. Check credentials, RTSP path, and FFmpeg.",
      );
    }
    connect().catch((e) => {
      if (!controller.signal.aborted) {
        setError(e.message);
        onState("Unavailable");
      }
    });
    return () => {
      controller.abort();
      hls?.destroy();
      element.removeAttribute("src");
      element.load();
    };
  }, [channel, attempt, onState]);
  return (
    <div className="player">
      <video
        ref={video}
        controls
        autoPlay
        muted
        playsInline
        disableRemotePlayback
        onPlaying={() => onState("Live")}
        onWaiting={() => onState("Buffering")}
        onError={() => {
          setError("Playback interrupted. Reconnect to try again.");
          onState("Unavailable");
        }}
      />
      {error && (
        <div className="player-error">
          <Radio size={28} />
          <p>{error}</p>
          <button
            className="primary"
            onClick={() => {
              setError("");
              setAttempt((a) => a + 1);
            }}
          >
            <RotateCcw size={15} /> Retry connection
          </button>
        </div>
      )}
    </div>
  );
}
