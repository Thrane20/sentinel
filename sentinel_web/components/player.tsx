"use client";
import { useEffect, useRef, useState } from "react";
import Hls from "hls.js";
import { LoaderCircle, Play, Radio, RotateCcw } from "lucide-react";
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
  // Live video has no scrubber or pause: the only states are loading,
  // playing, blocked (autoplay refused) and failed.
  const [loading, setLoading] = useState<"connecting" | "buffering" | null>("connecting");
  const [blocked, setBlocked] = useState(false);
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
                setLoading(null);
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
        setLoading(null);
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
        autoPlay
        muted
        playsInline
        disableRemotePlayback
        disablePictureInPicture
        aria-label="Live camera video"
        onCanPlay={(event) => {
          // iOS Low Power Mode refuses autoplay; without controls the viewer
          // would otherwise be left on a spinner.
          event.currentTarget.play().catch(() => {
            setLoading(null);
            setBlocked(true);
          });
        }}
        onPlaying={() => {
          setLoading(null);
          setBlocked(false);
          onState("Live");
        }}
        onWaiting={() => {
          setLoading("buffering");
          onState("Buffering");
        }}
        onError={() => {
          setLoading(null);
          setError("Playback interrupted. Reconnect to try again.");
          onState("Unavailable");
        }}
      />
      {loading && !error && (
        <div className="player-loading" role="status">
          <LoaderCircle className="spin" size={34} aria-hidden="true" />
          <span>{loading === "connecting" ? "Connecting to camera…" : "Buffering…"}</span>
        </div>
      )}
      {blocked && !error && (
        <button
          className="player-start"
          onClick={() => {
            setBlocked(false);
            void video.current?.play().catch(() => setBlocked(true));
          }}
        >
          <Play size={30} aria-hidden="true" />
          <span>Tap to start live view</span>
        </button>
      )}
      {error && (
        <div className="player-error">
          <Radio size={28} />
          <p>{error}</p>
          <button
            className="primary"
            onClick={() => {
              setError("");
              setLoading("connecting");
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
