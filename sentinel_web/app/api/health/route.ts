import { configured } from "@/lib/stream";
import { animalHealth } from "@/lib/animals";
export const dynamic = "force-dynamic";
export async function GET() {
  const animals = await animalHealth();
  return Response.json(
    {
      configured: configured(),
      host: process.env.IVSEC_HOST || "192.168.68.203",
      playback: false,
      metadataSource: "IVSEC_FINDINGS.md · 30 Mar 2026",
      animals,
    },
    { headers: { "Cache-Control": "no-store" } },
  );
}
