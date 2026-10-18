import { animalWorker, proxyJson } from "@/lib/animals";

type Context = { params: Promise<{ channel: string }> };
export async function GET(_request: Request, context: Context) {
  const { channel } = await context.params;
  if (!/^0[1-8]$/.test(channel))
    return Response.json({ error: "Unknown camera" }, { status: 404 });
  return proxyJson(await animalWorker(`/masks/${channel}`));
}
export async function POST(request: Request, context: Context) {
  const { channel } = await context.params;
  if (!/^0[1-8]$/.test(channel))
    return Response.json({ error: "Unknown camera" }, { status: 404 });
  let body;
  try {
    body = await request.json();
  } catch {
    return Response.json({ error: "Invalid JSON" }, { status: 400 });
  }
  return proxyJson(
    await animalWorker(`/masks/${channel}`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  );
}
