import { existsSync } from "node:fs";
import { spawn } from "node:child_process";

const args = ["compose", "-f", "compose.yaml"];
const forcedCpu = process.env.FRIGATE_OPENVINO_DEVICE?.toUpperCase() === "CPU";
const intelDeviceAvailable = existsSync("/dev/dri/renderD128");

if (forcedCpu || !intelDeviceAvailable) {
  args.push("-f", "compose.cpu.yaml");
  console.log(
    forcedCpu
      ? "Starting animal detection in requested CPU mode."
      : "Intel render device not found; starting animal detection in CPU mode.",
  );
} else {
  console.log("Intel render device found; OpenVINO will prefer the GPU.");
}

args.push("up", "--build", "--remove-orphans");
if (!process.argv.includes("--foreground")) args.push("--detach");

const child = spawn("docker", args, { stdio: "inherit" });
child.on("exit", (code, signal) => {
  if (signal) process.kill(process.pid, signal);
  else process.exitCode = code ?? 1;
});
