import { getStream } from "@/lib/stream";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export async function GET(
  _request: Request,
  context: { params: Promise<{ channel: string; file: string }> },
) {
  const { channel, file } = await context.params;
  try {
    const result = await getStream(channel, file);
    const headers = { "Cache-Control": "no-store" };
    if (!result.data)
      return Response.json(
        { error: result.error },
        { status: result.status, headers },
      );
    return new Response(new Uint8Array(result.data), {
      headers: {
        ...headers,
        "Content-Type": file.endsWith(".m3u8")
          ? "application/vnd.apple.mpegurl"
          : "video/mp2t",
      },
    });
  } catch {
    return Response.json(
      {
        error:
          "Unable to start the stream bridge. Check the host configuration.",
      },
      { status: 503 },
    );
  }
}
