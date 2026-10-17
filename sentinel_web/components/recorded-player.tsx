"use client";

import { Clock3, RotateCcw } from "lucide-react";
import { useEffect, useState } from "react";

export function RecordedPlayer({
  channel,
  detectedAt,
  onState,
}: {
  channel: string;
  detectedAt: number;
  onState: (state: string) => void;
}) {
  const [attempt, setAttempt] = useState(0);
  const [error, setError] = useState(false);
  const url = `/api/playback/${channel}?at=${detectedAt}&attempt=${attempt}`;

  useEffect(() => {
    onState("Loading recording");
  }, [channel, detectedAt, attempt, onState]);

  return (
    <div className="player">
      <video
        key={url}
        src={url}
        controls
        autoPlay
        muted
        playsInline
        disableRemotePlayback
        onCanPlay={() => onState("Recorded playback")}
        onPlaying={() => onState("Recorded playback")}
        onWaiting={() => onState("Buffering recording")}
        onError={() => {
          setError(true);
          onState("Recording unavailable");
        }}
      />
      {error && (
        <div className="player-error">
          <Clock3 size={28} />
          <p>
            Recorder footage is unavailable for this camera and time. It may
            have expired, or another IVSEC playback may already be open.
          </p>
          <button
            className="primary"
            onClick={() => {
              setError(false);
              setAttempt((current) => current + 1);
            }}
          >
            <RotateCcw size={15} /> Retry recording
          </button>
        </div>
      )}
    </div>
  );
}
