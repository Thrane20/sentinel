import { getSnapshot } from "@/lib/snapshot";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(
  _request: Request,
  context: { params: Promise<{ channel: string }> },
) {
  const { channel } = await context.params;
  try {
    const result = await getSnapshot(channel);
    const headers = { "Cache-Control": "no-store, max-age=0" };
    if (!result.data)
      return Response.json(
        { error: result.error },
        { status: result.status, headers },
      );
    return new Response(new Uint8Array(result.data), {
      headers: { ...headers, "Content-Type": "image/jpeg" },
    });
  } catch {
    return Response.json(
      { error: "Unable to start the camera snapshot" },
      { status: 503, headers: { "Cache-Control": "no-store" } },
    );
  }
}
