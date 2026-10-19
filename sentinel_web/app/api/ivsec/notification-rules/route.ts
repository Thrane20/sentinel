import { animalWorker, proxyJson } from "@/lib/animals";
import { ivsecWriteOriginError } from "@/lib/ivsec-write";
export const dynamic = "force-dynamic";
export async function GET() {
  return proxyJson(await animalWorker("/ivsec-notification-rules"));
}
export async function POST(request: Request) {
  const denied = ivsecWriteOriginError(request);
  if (denied) return denied;
  try {
    return proxyJson(
      await animalWorker("/ivsec-notification-rules", {
        method: "POST",
        body: JSON.stringify(await request.json()),
      }),
    );
  } catch {
    return Response.json({ error: "Invalid JSON body" }, { status: 400 });
  }
}
