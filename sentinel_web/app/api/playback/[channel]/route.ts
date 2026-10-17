import { recordedClip } from "@/lib/recorded";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(
  request: Request,
  context: { params: Promise<{ channel: string }> },
) {
  const { channel } = await context.params;
  const at = Number(new URL(request.url).searchParams.get("at"));
  return recordedClip(channel, at, request.signal);
}
