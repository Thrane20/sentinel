import { animalWorker, proxyJson } from "@/lib/animals";

export const dynamic = "force-dynamic";

export async function GET() {
  return proxyJson(await animalWorker("/settings"));
}

export async function PATCH(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return Response.json({ error: "Invalid JSON body" }, { status: 400 });
  }
  return proxyJson(
    await animalWorker("/settings", {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  );
}
