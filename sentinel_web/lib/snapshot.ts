import "server-only";
import { createHash } from "node:crypto";

import { recorderSnapshot } from "./recorder-snapshot";

import { cameras } from "./cameras";

const frigateUrl = () =>
  (process.env.FRIGATE_URL || "http://127.0.0.1:5000").replace(/\/$/, "");

export async function getSnapshot(channel: string, requireFrames = false) {
  if (!cameras.some((camera) => camera.id === channel))
    return { status: 404, error: "Unknown camera" };
  if (!process.env.IVSEC_USERNAME || !process.env.IVSEC_PASSWORD)
    return { status: 503, error: "Recorder credentials are not configured" };

  try {
    const response = await fetch(
      `${frigateUrl()}/api/ch${channel}/latest.jpg${requireFrames ? "?height=360&quality=70" : ""}`,
      {
        cache: "no-store",
        signal: AbortSignal.timeout(5000),
      },
    );
    if (!response.ok) throw new Error("Camera snapshot is unavailable");
    const data = await response.arrayBuffer();
    // Frigate 0.17.2 returns its camera-error image with HTTP 200 even when FPS
    // counters are nonzero. Reject that fixed image at the explicit size/quality.
    if (
      requireFrames &&
      createHash("sha256").update(new Uint8Array(data)).digest("hex") ===
        "905fbe058b4649063ec90e507fc87da4108ecf08f5be6f37c98985c35d111376"
    )
      throw new Error("Frigate has no camera frame");
    return { status: 200, data };
  } catch {
    if (requireFrames) {
      try {
        return { status: 200, data: await recorderSnapshot(channel) };
      } catch (caught) {
        return {
          status: 503,
          error:
            caught instanceof Error
              ? caught.message
              : "Recorder snapshot is unavailable",
        };
      }
    }
    return {
      status: 503,
      error: "Animal detector snapshot service is offline",
    };
  }
}
