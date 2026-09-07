const channel = process.argv[2] || "01";

if (!/^\d{2}$/.test(channel)) {
  console.error("Use a two-digit camera channel, for example: 01");
  process.exit(1);
}

const origin = process.env.SENTINEL_URL || "http://127.0.0.1:3000";
const playlistUrl = `${origin}/api/stream/${channel}/index.m3u8`;

for (let attempt = 1; attempt <= 15; attempt += 1) {
  try {
    const response = await fetch(playlistUrl, { cache: "no-store" });
    const body = await response.text();

    if (response.ok && body.startsWith("#EXTM3U")) {
      const segment = body.match(/^segment\d+\.ts$/m)?.[0];
      if (!segment) throw new Error("playlist contained no video segment");

      const segmentResponse = await fetch(
        `${origin}/api/stream/${channel}/${segment}`,
        { cache: "no-store" },
      );
      if (!segmentResponse.ok) {
        throw new Error(
          `video segment returned HTTP ${segmentResponse.status}`,
        );
      }

      const bytes =
        Number(segmentResponse.headers.get("content-length")) ||
        (await segmentResponse.arrayBuffer()).byteLength;
      console.log(
        `Channel ${channel} is streaming through Docker (${bytes} byte HLS segment).`,
      );
      process.exit(0);
    }

    let detail = `HTTP ${response.status}`;
    try {
      detail = JSON.parse(body).error || detail;
    } catch {
      // Keep the status-only message for non-JSON responses.
    }
    console.log(`Attempt ${attempt}/15: ${detail}`);
  } catch (error) {
    console.log(`Attempt ${attempt}/15: ${error.message}`);
  }

  await new Promise((resolve) => setTimeout(resolve, 1500));
}

console.error(
  `Channel ${channel} did not start. Run npm run docker:logs and confirm the RTSP channel/path and credentials.`,
);
process.exit(1);
