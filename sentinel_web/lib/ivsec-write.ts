export function ivsecWriteOriginError(request: Request) {
  const origin = request.headers.get("origin");
  try {
    if (!origin || new URL(origin).host === request.headers.get("host"))
      return null;
  } catch {
    /* Treat malformed origins as untrusted. */
  }
  return Response.json(
    { error: "Cross-origin IVSEC changes are not allowed." },
    { status: 403 },
  );
}
