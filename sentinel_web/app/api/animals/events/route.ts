import { animalWorker, proxyJson } from "@/lib/animals";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const query = new URL(request.url).search;
  return proxyJson(await animalWorker(`/events${query}`));
}

export async function DELETE() {
  return proxyJson(
    await animalWorker("/events", {
      method: "DELETE",
    }),
  );
}
