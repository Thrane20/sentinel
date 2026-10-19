import { animalWorker, proxyJson } from "@/lib/animals";
import { ivsecWriteOriginError } from "@/lib/ivsec-write";
export const dynamic = "force-dynamic";
export async function GET(request: Request) {
  const params = new URL(request.url).searchParams;
  if (params.get("catalog") === "1")
    return proxyJson(await animalWorker("/ivsec-remote/catalog"));
  const query = new URLSearchParams();
  for (const key of ["camera", "event", "section"])
    query.set(key, params.get(key) || "");
  return proxyJson(await animalWorker(`/ivsec-remote?${query}`));
}
export async function PATCH(request: Request) {
  const error = ivsecWriteOriginError(request);
  if (error) return error;
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return Response.json({ error: "Invalid JSON body" }, { status: 400 });
  }
  return proxyJson(
    await animalWorker("/ivsec-remote", {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  );
}
