import "server-only";
import { spawn } from "node:child_process";

const pending = new Map<string, Promise<ArrayBuffer>>();

// One short-lived capture per camera; concurrent refreshes share the same work.
export function recorderSnapshot(channel: string): Promise<ArrayBuffer> {
  const existing = pending.get(channel);
  if (existing) return existing;
  if (pending.size >= 2)
    return Promise.reject(new Error("Snapshot capture busy. Retry shortly."));
  const capture = captureFrame(channel).finally(() => pending.delete(channel));
  pending.set(channel, capture);
  return capture;
}

function captureFrame(channel: string): Promise<ArrayBuffer> {
  return new Promise((resolve, reject) => {
    const host = process.env.IVSEC_HOST || "192.168.68.203";
    if (!/^[a-zA-Z0-9.-]+$/.test(host) || !/^0[1-8]$/.test(channel)) {
      reject(new Error("Invalid camera configuration"));
      return;
    }
    const index = /^[012]$/.test(process.env.IVSEC_STREAM_INDEX || "")
      ? process.env.IVSEC_STREAM_INDEX
      : "0";
    const source = `rtsp://${encodeURIComponent(process.env.IVSEC_USERNAME!)}:${encodeURIComponent(process.env.IVSEC_PASSWORD!)}@${host}:554/ch${channel}/${index}`;
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
