import "server-only";
import { spawn } from "node:child_process";

import { recorderSource, restreamUrl } from "./stream";

const pending = new Map<string, Promise<ArrayBuffer>>();
const frames = new Map<string, { data: ArrayBuffer; expires: number }>();
const failures = new Map<string, number>();

// Tile fallback when Frigate has no frame. Through Frigate's go2rtc restream a
// capture reuses the connection detection already holds, so it can refresh
// every 10s. Directly against the recorder (no Frigate), each capture is a new
// recorder session: allow one at a time, at most once a minute per camera.
// When Frigate is down entirely the restream fails too and tiles keep their
// last image instead of opening recorder connections.
function limits() {
  return restreamUrl("01", "2")
    ? { cacheMs: 10_000, retryMs: 10_000, concurrent: 2 }
    : { cacheMs: 60_000, retryMs: 60_000, concurrent: 1 };
}

// One short-lived capture per camera; concurrent refreshes share the same work.
export function recorderSnapshot(channel: string): Promise<ArrayBuffer> {
  const cached = frames.get(channel);
  if (cached && cached.expires > Date.now())
    return Promise.resolve(cached.data);
  if ((failures.get(channel) || 0) > Date.now())
    return Promise.reject(
      new Error("Recorder snapshot is recovering. Retry shortly."),
    );
  const existing = pending.get(channel);
  if (existing) return existing;
  const { cacheMs, retryMs, concurrent } = limits();
  if (pending.size >= concurrent)
    return Promise.reject(new Error("Snapshot capture busy. Retry shortly."));
  const capture = captureFrame(channel)
    .then(
      (data) => {
        frames.set(channel, { data, expires: Date.now() + cacheMs });
        failures.delete(channel);
        return data;
      },
      (error) => {
        failures.set(channel, Date.now() + retryMs);
        throw error;
      },
    )
    .finally(() => pending.delete(channel));
  pending.set(channel, capture);
  return capture;
}

function captureFrame(channel: string): Promise<ArrayBuffer> {
  return new Promise((resolve, reject) => {
    // Tiles are 640x360; use the recorder's low-bandwidth stream, not main.
    const index = /^[012]$/.test(process.env.IVSEC_SNAPSHOT_STREAM_INDEX || "")
      ? process.env.IVSEC_SNAPSHOT_STREAM_INDEX!
      : "2";
    let source: string;
    try {
      source = recorderSource(channel, index);
    } catch {
      reject(new Error("Invalid camera configuration"));
      return;
    }
    const child = spawn(
      process.env.FFMPEG_PATH || "ffmpeg",
      [
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-rtsp_transport",
        "tcp",
        "-timeout",
        "10000000",
        "-i",
        source,
        "-map",
        "0:v:0",
        "-an",
        "-frames:v",
        "1",
        "-vf",
        "scale=640:360",
        "-threads",
        "1",
        "-f",
        "image2pipe",
        "-c:v",
        "mjpeg",
        "pipe:1",
      ],
      { stdio: ["ignore", "pipe", "ignore"] },
    );
    const chunks: Buffer[] = [];
    let size = 0;
    let settled = false;
    function finish(error?: string) {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (error) {
        child.kill("SIGKILL");
        reject(new Error(error));
        return;
      }
      const data = Buffer.concat(chunks);
      if (data.length < 4 || data[0] !== 0xff || data[1] !== 0xd8) {
        reject(
          new Error(
            "Recorder returned no camera image. Check camera stream and recorder connectivity.",
          ),
        );
      } else resolve(Uint8Array.from(data).buffer);
    }
    const timer = setTimeout(
      () =>
        finish(
          "Recorder snapshot timed out. Check recorder connectivity and retry.",
        ),
      15000,
    );
    child.on("error", () =>
      finish("Unable to start snapshot capture. Check FFmpeg is installed."),
    );
    child.stdout.on("data", (data: Buffer) => {
      size += data.length;
      if (size > 2 * 1024 * 1024)
        finish("Recorder snapshot exceeded the size limit.");
      else chunks.push(data);
    });
    child.on("close", (code) =>
      finish(
        code === 0
          ? undefined
          : "Recorder snapshot failed. Check camera stream, credentials and connectivity.",
      ),
    );
  });
}
