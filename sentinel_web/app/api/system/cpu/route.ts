import { animalWorker, proxyJson } from "@/lib/animals";

export const dynamic = "force-dynamic";
export async function GET() {
  return proxyJson(await animalWorker("/system/cpu"));
}
