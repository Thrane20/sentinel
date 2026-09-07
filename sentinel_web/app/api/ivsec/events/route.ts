import { animalWorker, proxyJson } from "@/lib/animals";

export const dynamic = "force-dynamic";

export async function GET() {
  return proxyJson(await animalWorker("/ivsec-events?limit=100"));
}

export async function DELETE() {
  return proxyJson(
    await animalWorker("/ivsec-events", {
      method: "DELETE",
    }),
  );
}
