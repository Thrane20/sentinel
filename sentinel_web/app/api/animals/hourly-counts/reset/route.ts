import { animalWorker, proxyJson } from "@/lib/animals";

export async function POST() {
  return proxyJson(
    await animalWorker("/hourly-counts/reset", { method: "POST" }),
  );
}
