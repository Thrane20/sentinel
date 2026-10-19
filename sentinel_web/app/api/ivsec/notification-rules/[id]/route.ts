import { animalWorker, proxyJson } from "@/lib/animals";
import { ivsecWriteOriginError } from "@/lib/ivsec-write";
export const dynamic = "force-dynamic";
export async function DELETE(
  request: Request,
  context: { params: Promise<{ id: string }> },
) {
  const denied = ivsecWriteOriginError(request);
  if (denied) return denied;
  const { id } = await context.params;
  if (!/^[a-z][a-z0-9_]{0,63}$/.test(id))
    return Response.json({ error: "Invalid rule ID" }, { status: 400 });
  return proxyJson(
    await animalWorker(`/ivsec-notification-rules/${id}`, { method: "DELETE" }),
  );
}
