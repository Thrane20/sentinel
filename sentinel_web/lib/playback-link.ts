import { cameras } from "./cameras";

export function parsePlaybackLink(
  search: string,
  now = Math.floor(Date.now() / 1000),
) {
  const params = new URLSearchParams(search);
  if (!params.has("playback")) return { kind: "none" } as const;
  const camera = cameras.find((item) => item.id === params.get("camera"));
  const rawTime = params.get("at") || "";
  const at = Number(rawTime);
  if (
    params.get("playback") !== "1" ||
    !camera ||
    !/^\d+$/.test(rawTime) ||
    !Number.isSafeInteger(at) ||
    at <= 0 ||
    at > now + 60
  )
    return { kind: "invalid" } as const;
  return { kind: "playback", camera, at } as const;
}
