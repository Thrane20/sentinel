import { animalWorker } from "@/lib/animals";

export const dynamic = "force-dynamic";

export async function GET(
  _request: Request,
  context: { params: Promise<{ id: string }> },
) {
  const { id } = await context.params;
  const event = await animalWorker(`/events/${encodeURIComponent(id)}`);
  if (!event.ok)
    return Response.json(
      {
        error:
          event.status === 404
            ? "Unknown event"
            : "Animal service unavailable",
      },
      { status: event.status, headers: { "Cache-Control": "no-store" } },
    );
  try {
    const base = (process.env.FRIGATE_URL || "http://127.0.0.1:5000").replace(
      /\/$/,
      "",
    );
    const snapshot = await fetch(
      `${base}/api/events/${encodeURIComponent(id)}/snapshot.jpg`,
      { cache: "no-store", signal: AbortSignal.timeout(5000) },
    );
    if (!snapshot.ok)
      return Response.json(
        { error: "Event snapshot is not available yet" },
        { status: snapshot.status, headers: { "Cache-Control": "no-store" } },
      );
    return new Response(await snapshot.arrayBuffer(), {
      headers: {
        "Content-Type": snapshot.headers.get("Content-Type") || "image/jpeg",
        "Cache-Control": "private, no-store, max-age=0",
      },
    });
  } catch {
    return Response.json(
      { error: "Frigate is unavailable" },
      { status: 503, headers: { "Cache-Control": "no-store" } },
    );
  }
}
