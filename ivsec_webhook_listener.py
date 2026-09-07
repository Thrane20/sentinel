#!/usr/bin/env python3
import argparse
import json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class IVSecWebhookHandler(BaseHTTPRequestHandler):
    server_version = "IVSecWebhookListener/1.0"

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0"))
        return self.rfile.read(length) if length > 0 else b""

    def _log_request(self, body: bytes) -> None:
        timestamp = datetime.now(timezone.utc).isoformat()
        body_text = body.decode("utf-8", errors="replace")
        body_json = None
        if body:
            try:
                body_json = json.loads(body_text)
            except json.JSONDecodeError:
                body_json = None

        entry = {
            "timestamp": timestamp,
            "client_address": self.client_address[0],
            "method": self.command,
            "path": self.path,
            "headers": {key: value for key, value in self.headers.items()},
            "body_raw": body_text,
            "body_json": body_json,
        }

        line = json.dumps(entry, ensure_ascii=True)
        self.server.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.server.log_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

        print("")
        print(f"[{timestamp}] {self.command} {self.path} from {self.client_address[0]}")
        for key, value in self.headers.items():
            print(f"{key}: {value}")
        print("")
        if body_json is not None:
            print(json.dumps(body_json, indent=2, ensure_ascii=True))
        else:
            print(body_text if body_text else "<empty body>")
        print("")

    def _send_ok(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')

    def do_GET(self) -> None:
        self._log_request(b"")
        self._send_ok()

    def do_POST(self) -> None:
        body = self._read_body()
        self._log_request(body)
        self._send_ok()

    def log_message(self, format: str, *args) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture IVSEC webhook requests.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8123)
    parser.add_argument(
        "--log-file",
        default=str(Path("ivsec_webhook_events.jsonl").resolve()),
        help="Path to append captured requests as JSON Lines.",
    )
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), IVSecWebhookHandler)
    server.log_path = Path(args.log_file).expanduser().resolve()

    print(f"Listening on http://{args.host}:{args.port}")
    print(f"Logging requests to {server.log_path}")
    server.serve_forever()


if __name__ == "__main__":
    main()
