import "server-only";

const workerUrl = () =>
  (process.env.ANIMAL_WORKER_URL || "http://127.0.0.1:3101").replace(
    /\/$/,
    "",
  );

export type AnimalHealth = {
  online: boolean;
  mqttOnline: boolean;
  frigateOnline: boolean;
  model: string;
  provider: string;
  inferenceSpeedMs: number | null;
  alertsConfigured: boolean;
  alertsEnabled: boolean;
  enabledCameras: number;
};

export async function animalWorker(
  path: string,
  init?: RequestInit,
): Promise<Response> {
  try {
    return await fetch(`${workerUrl()}${path}`, {
      ...init,
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
      headers: {
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
        ...init?.headers,
      },
    });
  } catch {
    return Response.json(
      { error: "Animal detection service is unavailable" },
      { status: 503 },
    );
  }
}

export async function animalHealth(): Promise<AnimalHealth | null> {
  const response = await animalWorker("/health");
  if (!response.ok) return null;
  return response.json() as Promise<AnimalHealth>;
}

export async function proxyJson(response: Response) {
  return new Response(await response.text(), {
    status: response.status,
    headers: {
      "Content-Type": "application/json",
      "Cache-Control": "no-store",
    },
  });
}
