import "server-only";

import { cameras } from "./cameras";

const frigateUrl = () =>
  (process.env.FRIGATE_URL || "http://127.0.0.1:5000").replace(/\/$/, "");

export async function getSnapshot(channel: string) {
  if (!cameras.some((camera) => camera.id === channel))
    return { status: 404, error: "Unknown camera" };
  if (!process.env.IVSEC_USERNAME || !process.env.IVSEC_PASSWORD)
    return { status: 503, error: "Recorder credentials are not configured" };

  try {
    const response = await fetch(`${frigateUrl()}/api/ch${channel}/latest.jpg`, {
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
    });
    if (!response.ok)
      return { status: 503, error: "Camera snapshot is unavailable" };
    return { status: 200, data: await response.arrayBuffer() };
  } catch {
    return { status: 503, error: "Animal detector snapshot service is offline" };
  }
}
