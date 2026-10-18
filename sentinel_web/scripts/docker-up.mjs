import { existsSync } from "node:fs";
import { spawn, spawnSync } from "node:child_process";

const composeCheck = spawnSync("docker", ["compose", "version"], {
  encoding: "utf8",
});

if (composeCheck.error?.code === "ENOENT") {
  console.error(
    "Docker was not found. Install Docker Engine and the Docker Compose v2 plugin, then retry.",
  );
  process.exit(1);
}

if (composeCheck.status !== 0) {
  console.error(
    [
      "Docker Compose v2 is required but 'docker compose version' failed.",
      "On Ubuntu or Debian with Docker's official package repository:",
      "  sudo apt-get update",
      "  sudo apt-get install docker-compose-plugin",
      "Then verify with: docker compose version",
    ].join("\n"),
  );
  process.exit(1);
}

const args = ["compose", "-f", "compose.yaml"];
const forcedCpu = process.env.FRIGATE_OPENVINO_DEVICE?.toUpperCase() === "CPU";
const intelDeviceAvailable = existsSync("/dev/dri/renderD128");
const requestedGpu = process.argv.includes("--gpu");
const requestedCpu = process.argv.includes("--cpu");

if (requestedGpu && requestedCpu) {
  console.error("Choose either --gpu or --cpu, not both.");
  process.exit(1);
}

if (requestedCpu) process.env.FRIGATE_OPENVINO_DEVICE = "CPU";

if (requestedGpu && !intelDeviceAvailable) {
  console.error(
    "GPU mode requires a supported Intel GPU exposed at /dev/dri/renderD128 on the Linux Docker host. No render device was found. Use 'pnpm docker' for automatic CPU fallback.",
  );
  process.exit(1);
}

if (requestedGpu) {
  // Override Compose interpolation as well as the worker/model installer setting.
  process.env.FRIGATE_OPENVINO_DEVICE = "GPU";
  console.log("Starting Frigate animal detection on the Intel GPU (OpenVINO GPU mode).");
} else if (requestedCpu || forcedCpu || !intelDeviceAvailable) {
  args.push("-f", "compose.cpu.yaml");
  console.log(
    requestedCpu || forcedCpu
      ? "Starting animal detection in requested CPU mode."
      : "Intel render device not found; starting animal detection in CPU mode.",
  );
} else {
  console.log("Intel render device found; OpenVINO will prefer the GPU.");
}

args.push("up", "--build", "--remove-orphans");
// Frigate reads a generated config volume. Recreate it after model-init writes
// the requested device, even when the service definition itself hasn't changed.
if (requestedGpu || requestedCpu) args.push("--force-recreate");
if (!process.argv.includes("--foreground")) args.push("--detach");

const child = spawn("docker", args, { stdio: "inherit" });
child.on("error", (error) => {
  console.error(`Unable to start Docker Compose: ${error.message}`);
  process.exitCode = 1;
});
child.on("exit", (code, signal) => {
  if (signal) process.kill(process.pid, signal);
  else process.exitCode = code ?? 1;
});
