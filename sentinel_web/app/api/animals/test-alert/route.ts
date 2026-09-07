import { animalWorker, proxyJson } from "@/lib/animals";

export async function POST() {
  return proxyJson(
    await animalWorker("/test-alert", {
      method: "POST",
    }),
  );
}
