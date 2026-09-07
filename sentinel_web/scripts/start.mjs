import { cp } from "node:fs/promises";
import { createRequire } from "node:module";
await cp("public", ".next/standalone/public", { recursive: true });
await cp(".next/static", ".next/standalone/.next/static", { recursive: true });
process.env.HOSTNAME = process.env.SENTINEL_BIND_HOST || "0.0.0.0";
process.env.NODE_ENV = "production";
createRequire(import.meta.url)("../.next/standalone/server.js");
