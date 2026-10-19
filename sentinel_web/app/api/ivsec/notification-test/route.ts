import { animalWorker, proxyJson } from "@/lib/animals";
import { ivsecWriteOriginError } from "@/lib/ivsec-write";
export const dynamic = "force-dynamic";
export async function POST(request: Request) {
  const denied = ivsecWriteOriginError(request);
  if (denied) return denied;
  try {
    const body = await request.json();
    if (
      !Number.isSafeInteger(body.eventId) ||
      body.eventId <= 0 ||
      typeof body.ruleId !== "string" ||
      !/^[a-z][a-z0-9_]{0,63}$/.test(body.ruleId)
    )
      return Response.json(
        { error: "Provide a valid eventId and ruleId" },
        { status: 400 },
      );
    return proxyJson(
      await animalWorker("/ivsec-notification-test", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    );
  } catch {
    return Response.json({ error: "Invalid JSON body" }, { status: 400 });
  }
}
