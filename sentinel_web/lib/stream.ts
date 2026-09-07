import "server-only";
import { spawn, type ChildProcess } from "node:child_process";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { cameras } from "./cameras";
type Worker = {
  process: ChildProcess;
  dir: string;
  touched: number;
  failed: boolean;
  failedAt?: number;
};
const globalState = globalThis as typeof globalThis & {
  sentinelWorkers?: Map<string, Promise<Worker>>;
};
const workers = (globalState.sentinelWorkers ??= new Map());
export const configured = () =>
  Boolean(process.env.IVSEC_USERNAME && process.env.IVSEC_PASSWORD);
export async function getStream(channel: string, file: string) {
  if (
    !cameras.some((c) => c.id === channel) ||
    !/^(index\.m3u8|segment\d+\.ts)$/.test(file)
  )
    return { status: 404, error: "Unknown stream" };
  if (!configured())
    return {
      status: 503,
      error: "Add recorder credentials to .env.local and restart Sentinel.",
    };
  let pending = workers.get(channel);
  if (!pending) {
    if (workers.size >= 4)
      return {
        status: 429,
        error:
          "Four streams are already active. Wait a minute before opening another.",
      };
    pending = start(channel);
    workers.set(channel, pending);
    pending.catch(() => workers.delete(channel));
  }
  const worker = await pending;
  worker.touched = Date.now();
  if (worker.failed)
    return {
      status: 502,
      error:
        "Stream unavailable. Check FFmpeg, recorder credentials, and network access.",
    };
  try {
    return { status: 200, data: await readFile(join(worker.dir, file)) };
  } catch {
    return { status: 503, error: "Stream is warming up. Try again shortly." };
  }
}
async function start(channel: string): Promise<Worker> {
  const host = process.env.IVSEC_HOST || "192.168.68.203";
  if (!/^[a-zA-Z0-9.-]+$/.test(host)) throw new Error("Invalid IVSEC_HOST");
  const dir = await mkdtemp(join(tmpdir(), "sentinel-"));
  const index = /^[012]$/.test(process.env.IVSEC_STREAM_INDEX || "")
    ? process.env.IVSEC_STREAM_INDEX
    : "0";
  const source = `rtsp://${encodeURIComponent(process.env.IVSEC_USERNAME!)}:${encodeURIComponent(process.env.IVSEC_PASSWORD!)}@${host}:554/ch${channel}/${index}`;
  const processHandle = spawn(
    /* turbopackIgnore: true */
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
      "-vf",
      "scale=1280:-2",
      "-c:v",
      "libx264",
      "-preset",
      "ultrafast",
      "-tune",
      "zerolatency",
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
      "-f",
      "hls",
      "-hls_time",
      "2",
      "-hls_list_size",
      "6",
      "-hls_flags",
      "delete_segments+independent_segments+temp_file",
      "-hls_segment_filename",
      join(dir, "segment%09d.ts"),
      join(dir, "index.m3u8"),
    ],
    { stdio: "ignore" },
  );
  const worker: Worker = {
    process: processHandle,
    dir,
    touched: Date.now(),
    failed: false,
  };
  processHandle.on("error", () => {
    worker.failed = true;
    worker.failedAt = Date.now();
  });
  processHandle.on("exit", () => {
    worker.failed = true;
    worker.failedAt = Date.now();
  });
  const timer = setInterval(() => {
    if (
      Date.now() - worker.touched > 45000 ||
      (worker.failedAt && Date.now() - worker.failedAt > 5000)
    ) {
      clearInterval(timer);
      workers.delete(channel);
      processHandle.kill("SIGKILL");
      void rm(dir, { recursive: true, force: true });
    }
  }, 10000);
  timer.unref();
  return worker;
}
