import { animalWorker, proxyJson } from "@/lib/animals";

export const dynamic = "force-dynamic";

export async function GET() {
  return proxyJson(await animalWorker("/ivsec-security"));
}

export async function PATCH(request: Request) {
  const origin = request.headers.get("origin");
  let sameHost = !origin;
  try {
    if (origin) sameHost = new URL(origin).host === request.headers.get("host");
  } catch {
    /* A malformed Origin cannot authorize a recorder change. */
  }
  if (!sameHost)
    return Response.json(
      { error: "Cross-origin recorder changes are not allowed." },
      { status: 403 },
    );
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return Response.json({ error: "Invalid JSON body" }, { status: 400 });
  }
  if (
    !body ||
    typeof body !== "object" ||
    Array.isArray(body) ||
    Object.keys(body).length !== 2 ||
    !("disarming" in body) ||
    typeof body.disarming !== "boolean" ||
    !("expectedDisarming" in body) ||
    typeof body.expectedDisarming !== "boolean"
  )
    return Response.json(
      { error: "disarming and expectedDisarming must be booleans." },
      { status: 400 },
    );
  return proxyJson(
    await animalWorker("/ivsec-security", {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  );
}
