import "server-only";

import { spawn } from "node:child_process";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { cameras } from "./cameras";

const workerUrl = () =>
  (process.env.ANIMAL_WORKER_URL || "http://127.0.0.1:3101").replace(/\/$/, "");

// Safari (iPhone and Mac) will only play an MP4 <video> from a server that
// answers byte-range requests with the clip's real length. It first asks for
// bytes 0-1, aborts, then fetches ranges, so each clip is transcoded once into
// a complete MP4, kept briefly, and every range request is served from it.
// Without the cache each of Safari's requests would start another recorder
// download, which the recorder refuses while one is running (playback_mutex).
const CLIP_TTL_MS = 5 * 60_000;
const MAX_CLIPS = 4;
const TRANSCODE_TIMEOUT_MS = 90_000;

type Clip = { promise: Promise<Buffer>; expires: number };
const globalState = globalThis as typeof globalThis & {
  sentinelRecordedClips?: Map<string, Clip>;
};
const clips = (globalState.sentinelRecordedClips ??= new Map());

const noStore = { "Cache-Control": "no-store" };

function transcode(channel: string, detectedAt: number): Promise<Buffer> {
  const source = new URL(`${workerUrl()}/ivsec-playback`);
  source.searchParams.set("camera", channel);
  source.searchParams.set("at", String(detectedAt));
  return mkdtemp(join(tmpdir(), "sentinel-clip-")).then((dir) => {
    const output = join(dir, "clip.mp4");
    const child = spawn(
      /* turbopackIgnore: true */
      process.env.FFMPEG_PATH || "ffmpeg",
      [
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-fflags",
        "+genpts+discardcorrupt",
        "-rw_timeout",
        "15000000",
        "-i",
        source.toString(),
        "-map",
        "0:v:0",
        "-an",
        "-vf",
        "scale=1280:-2,fps=15,setpts=N/(15*TB)",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        "-r",
        "15",
        "-g",
        "30",
        "-sc_threshold",
        "0",
        "-crf",
        "25",
        "-threads",
        "2",
        "-t",
        "30",
        // A regular MP4 with its index first: the most widely playable form
        // once the length is known.
        "-movflags",
        "+faststart",
        "-f",
        "mp4",
        output,
      ],
      { stdio: "ignore" },
    );
    const timer = setTimeout(() => child.kill("SIGKILL"), TRANSCODE_TIMEOUT_MS);
    return new Promise<Buffer>((resolve, reject) => {
      child.on("error", reject);
      child.on("close", (code) => {
        if (code !== 0) return reject(new Error("Recorder playback is unavailable"));
        readFile(output).then(
          (data) => (data.length ? resolve(data) : reject(new Error("Empty recording"))),
          reject,
        );
      });
    }).finally(() => {
      clearTimeout(timer);
      void rm(dir, { recursive: true, force: true });
    });
  });
}

function clipFor(channel: string, detectedAt: number) {
  const now = Date.now();
  for (const [key, clip] of clips) if (clip.expires <= now) clips.delete(key);
  const key = `${channel}:${detectedAt}`;
  const existing = clips.get(key);
  if (existing) return existing.promise;
  while (clips.size >= MAX_CLIPS) clips.delete(clips.keys().next().value!);
  const promise = transcode(channel, detectedAt);
  clips.set(key, { promise, expires: now + CLIP_TTL_MS });
  // Never cache a failure: Retry must reach the recorder again.
  promise.catch(() => {
    if (clips.get(key)?.promise === promise) clips.delete(key);
  });
  return promise;
}

/** Parse a single `bytes=` range. Returns null for a full response, or
 *  "invalid" when the range cannot be satisfied. */
export function parseRange(header: string | null, size: number) {
  if (!header) return null;
  const match = /^bytes=(\d*)-(\d*)$/.exec(header.trim());
  if (!match || (!match[1] && !match[2])) return "invalid" as const;
  let start: number;
  let end: number;
  if (!match[1]) {
    const suffix = Number(match[2]);
    if (!suffix) return "invalid" as const;
    start = Math.max(size - suffix, 0);
    end = size - 1;
  } else {
    start = Number(match[1]);
    end = match[2] ? Math.min(Number(match[2]), size - 1) : size - 1;
  }
  if (start >= size || start > end) return "invalid" as const;
  return { start, end };
}

export async function recordedClip(
  channel: string,
  detectedAt: number,
  request: Request,
) {
  if (!cameras.some((camera) => camera.id === channel))
    return Response.json({ error: "Unknown camera" }, { status: 404, headers: noStore });
  if (
    !Number.isInteger(detectedAt) ||
    detectedAt <= 0 ||
    detectedAt > Math.floor(Date.now() / 1000) + 60
  )
    return Response.json({ error: "Invalid playback time" }, { status: 400, headers: noStore });

  let clip: Buffer;
  try {
    clip = await clipFor(channel, detectedAt);
  } catch {
    return Response.json(
      { error: "Recorder playback is unavailable" },
      { status: 502, headers: noStore },
    );
  }

  const headers: Record<string, string> = {
    "Content-Type": "video/mp4",
    "Accept-Ranges": "bytes",
    "Cache-Control": "private, no-store, max-age=0",
    "Content-Disposition": `inline; filename="camera-${channel}-${detectedAt}.mp4"`,
  };
  const range = parseRange(request.headers.get("range"), clip.length);
  if (range === "invalid")
    return new Response(null, {
      status: 416,
      headers: { ...headers, "Content-Range": `bytes */${clip.length}` },
    });
  if (!range)
    return new Response(new Uint8Array(clip), {
      headers: { ...headers, "Content-Length": String(clip.length) },
    });
  return new Response(new Uint8Array(clip.subarray(range.start, range.end + 1)), {
    status: 206,
    headers: {
      ...headers,
      "Content-Length": String(range.end - range.start + 1),
      "Content-Range": `bytes ${range.start}-${range.end}/${clip.length}`,
    },
  });
}
