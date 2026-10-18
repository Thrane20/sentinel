import { animalWorker, proxyJson } from "@/lib/animals";

export const dynamic = "force-dynamic";
export async function GET(
  _request: Request,
  context: { params: Promise<{ id: string }> },
) {
  const { id } = await context.params;
  return proxyJson(await animalWorker(`/events/${encodeURIComponent(id)}`));
}
