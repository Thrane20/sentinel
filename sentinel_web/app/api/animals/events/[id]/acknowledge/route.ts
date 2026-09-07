import { animalWorker, proxyJson } from "@/lib/animals";

export async function POST(
  _request: Request,
  context: { params: Promise<{ id: string }> },
) {
  const { id } = await context.params;
  return proxyJson(
    await animalWorker(`/events/${encodeURIComponent(id)}/acknowledge`, {
      method: "POST",
    }),
  );
}
