import { animalWorker, proxyJson } from "@/lib/animals";
export const dynamic = "force-dynamic";
export async function GET(
  _request: Request,
  context: { params: Promise<{ id: string }> },
) {
  const { id } = await context.params;
  if (!/^\d+$/.test(id))
    return Response.json({ error: "Invalid event ID" }, { status: 400 });
  return proxyJson(await animalWorker(`/ivsec-events/${id}`));
}
