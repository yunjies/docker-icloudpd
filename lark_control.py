#!/usr/bin/env python3

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


CONFIG_FILE = "/config/icloudpd.conf"
DEFAULT_COMMAND_FILE = "/tmp/icloudpd/remote_command.txt"


def read_config(path):
    config = {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                config[key] = value.strip().strip('"')
    except FileNotFoundError:
        pass
    return config


def extract_text(payload):
    event = payload.get("event") or {}
    message = event.get("message") or {}
    if message.get("message_type") != "text":
        old_text = event.get("text_without_at_bot") or event.get("text")
        return str(old_text or "").strip()
    content = message.get("content") or "{}"
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except json.JSONDecodeError:
            return ""
    return str(content.get("text") or "").strip()


def extract_sender_open_id(payload):
    event = payload.get("event") or {}
    sender = event.get("sender") or {}
    sender_id = sender.get("sender_id") or {}
    return sender_id.get("open_id") or event.get("open_id") or ""


def is_message_event(payload):
    header_event_type = (payload.get("header") or {}).get("event_type")
    if header_event_type == "im.message.receive_v1":
        return True

    event = payload.get("event") or {}
    return payload.get("type") == "event_callback" and event.get("type") == "message"


def command_prefix(config):
    return (config.get("user") or "user").strip().lower()


def is_control_command(config, text):
    text_lc = text.strip().lower()
    prefix = command_prefix(config)
    return (
        text_lc == prefix
        or text_lc == f"{prefix} auth"
        or (text_lc.startswith(f"{prefix} ") and len(text_lc.split()) == 2)
    )


def interrupt_current_check():
    os.system("ps | awk '/\\/opt\\/icloudpd\\/bin\\/icloudpd/ && !/awk/ {print $1}' | while read pid; do kill \"$pid\" 2>/dev/null; done")


def icloudpd_download_running():
    return os.system("ps | grep '/opt/icloudpd/bin/icloudpd' | grep -qv -- '--only-print-filenames'") == 0


class Handler(BaseHTTPRequestHandler):
    server_version = "lark-control/1.0"

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args), flush=True)

    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self.send_json(200, {"ok": True})
            return
        self.send_json(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        config = self.server.config
        expected_path = config.get("lark_control_path") or "/lark/events"
        if self.path.split("?", 1)[0] != expected_path:
            self.send_json(404, {"ok": False, "error": "not found"})
            return

        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length).decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw_body or "{}")
        except json.JSONDecodeError:
            self.send_json(400, {"ok": False, "error": "invalid json"})
            return

        verification_token = config.get("lark_verification_token")
        payload_token = payload.get("token") or (payload.get("header") or {}).get("token")
        if verification_token and payload_token != verification_token:
            self.send_json(403, {"ok": False, "error": "invalid token"})
            return

        challenge = payload.get("challenge") or (payload.get("event") or {}).get("challenge")
        if challenge:
            self.send_json(200, {"challenge": challenge})
            return

        if not is_message_event(payload):
            self.send_json(200, {"ok": True, "ignored": True})
            return

        sender_open_id = extract_sender_open_id(payload)
        allowed_open_ids = [
            item.strip()
            for item in (config.get("lark_allowed_open_ids") or "").split(",")
            if item.strip()
        ]
        if allowed_open_ids and sender_open_id not in allowed_open_ids:
            self.send_json(200, {"ok": True, "ignored": True, "reason": "sender not allowed"})
            return

        text = extract_text(payload)
        if not text:
            self.send_json(200, {"ok": True, "ignored": True, "reason": "empty or non-text message"})
            return

        if not is_control_command(config, text):
            self.send_json(200, {"ok": True, "ignored": True, "reason": "not a control command"})
            return

        if text.strip().lower() == command_prefix(config) and icloudpd_download_running():
            self.send_json(200, {"ok": True, "ignored": True, "reason": "download already running"})
            return

        command_file = config.get("lark_control_command_file") or DEFAULT_COMMAND_FILE
        os.makedirs(os.path.dirname(command_file), exist_ok=True)
        with open(command_file, "a", encoding="utf-8") as handle:
            handle.write(text.replace("\r", " ").replace("\n", " ").strip() + "\n")
        interrupt_current_check()

        self.send_json(200, {"ok": True})


def main():
    config = read_config(os.environ.get("config_file", CONFIG_FILE))
    host = config.get("lark_control_host") or "0.0.0.0"
    port = int(config.get("lark_control_port") or "8088")
    server = ThreadingHTTPServer((host, port), Handler)
    server.config = config
    print(f"lark-control listening on {host}:{port}{config.get('lark_control_path') or '/lark/events'}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
