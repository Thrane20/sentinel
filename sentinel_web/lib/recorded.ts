import "server-only";

import { spawn } from "node:child_process";
import { cameras } from "./cameras";

const workerUrl = () =>
  (process.env.ANIMAL_WORKER_URL || "http://127.0.0.1:3101").replace(/\/$/, "");

export function recordedClip(
  channel: string,
  detectedAt: number,
  signal: AbortSignal,
) {
  if (!cameras.some((camera) => camera.id === channel))
    return Response.json(
      { error: "Unknown camera" },
      { status: 404, headers: { "Cache-Control": "no-store" } },
    );
  if (
    !Number.isInteger(detectedAt) ||
    detectedAt <= 0 ||
    detectedAt > Math.floor(Date.now() / 1000) + 60
  )
    return Response.json(
      { error: "Invalid playback time" },
      { status: 400, headers: { "Cache-Control": "no-store" } },
    );

  const source = new URL(`${workerUrl()}/ivsec-playback`);
  source.searchParams.set("camera", channel);
  source.searchParams.set("at", String(detectedAt));
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
      "-movflags",
      "frag_keyframe+empty_moov+default_base_moof",
      "-f",
      "mp4",
      "pipe:1",
    ],
    { stdio: ["ignore", "pipe", "ignore"] },
  );

  let finished = false;
  let delivered = false;
  const stop = () => {
    if (!finished) child.kill("SIGKILL");
  };
  signal.addEventListener("abort", stop, { once: true });

  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      child.stdout.on("data", (chunk: Buffer) => {
        delivered = true;
        controller.enqueue(new Uint8Array(chunk));
      });
      child.stdout.on("error", (error) => {
        if (!finished) {
          finished = true;
          controller.error(error);
        }
      });
      child.on("error", (error) => {
        if (!finished) {
          finished = true;
          controller.error(error);
        }
      });
      child.on("close", () => {
        if (finished) return;
        finished = true;
        signal.removeEventListener("abort", stop);
        if (delivered) controller.close();
        else controller.error(new Error("Recorder playback is unavailable"));
      });
    },
    cancel() {
      stop();
    },
  });

  return new Response(body, {
    headers: {
      "Content-Type": "video/mp4",
      "Cache-Control": "private, no-store, max-age=0",
      "Content-Disposition": `inline; filename="camera-${channel}-${detectedAt}.mp4"`,
    },
  });
}
