#!/usr/bin/env python3

import json
import os
import sys
import time
import urllib.error
import urllib.request


CONFIG_FILE = "/config/icloudpd.conf"
TOKEN_CACHE_FILE = "/tmp/icloudpd/lark_tenant_access_token.json"


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


def post_json(url, payload, headers=None):
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8", **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body or "{}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body or "{}")
        except json.JSONDecodeError:
            parsed = {"msg": body}
        return exc.code, parsed


def get_tenant_access_token(config):
    now = int(time.time())
    try:
        with open(TOKEN_CACHE_FILE, "r", encoding="utf-8") as handle:
            cached = json.load(handle)
        if cached.get("tenant_access_token") and int(cached.get("expires_at", 0)) > now + 60:
            return cached["tenant_access_token"]
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        pass

    api_base = config.get("lark_api_base") or "https://open.feishu.cn"
    status, payload = post_json(
        f"{api_base}/open-apis/auth/v3/tenant_access_token/internal",
        {
            "app_id": config.get("lark_app_id"),
            "app_secret": config.get("lark_app_secret"),
        },
    )
    if status != 200 or payload.get("code") != 0:
        raise RuntimeError(f"failed to obtain tenant_access_token: http={status} payload={payload}")

    token = payload["tenant_access_token"]
    expires_at = now + int(payload.get("expire", 7200))
    with open(TOKEN_CACHE_FILE, "w", encoding="utf-8") as handle:
        json.dump({"tenant_access_token": token, "expires_at": expires_at}, handle)
    return token


def build_text(title, event, message, preview_count, preview_type, preview_text):
    message = (message or "").replace("%0A", "\n")
    preview_text = (preview_text or "").replace("%0A", "\n")
    parts = [title]
    if event and event != title:
        parts.append(event)
    if message:
        parts.append(message)
    if preview_count and preview_type and preview_text:
        parts.append(f"Most recent {preview_count} {preview_type} files:\n{preview_text}")
    return "\n".join(parts)


def main():
    config = read_config(os.environ.get("config_file", CONFIG_FILE))
    required = ["lark_app_id", "lark_app_secret", "lark_receive_id"]
    missing = [key for key in required if not config.get(key)]
    if missing:
        raise RuntimeError(f"missing required lark config: {', '.join(missing)}")

    title = os.environ.get("LARK_NOTIFICATION_TITLE", "iCloudPD")
    event = os.environ.get("LARK_NOTIFICATION_EVENT", "")
    message = os.environ.get("LARK_NOTIFICATION_MESSAGE", "")
    preview_count = os.environ.get("LARK_NOTIFICATION_PREVIEW_COUNT", "")
    preview_type = os.environ.get("LARK_NOTIFICATION_PREVIEW_TYPE", "")
    preview_text = os.environ.get("LARK_NOTIFICATION_PREVIEW_TEXT", "")
    text = build_text(title, event, message, preview_count, preview_type, preview_text)

    api_base = config.get("lark_api_base") or "https://open.feishu.cn"
    receive_id_type = config.get("lark_receive_id_type") or "open_id"
    token = get_tenant_access_token(config)
    status, payload = post_json(
        f"{api_base}/open-apis/im/v1/messages?receive_id_type={receive_id_type}",
        {
            "receive_id": config["lark_receive_id"],
            "msg_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False),
        },
        {"Authorization": f"Bearer {token}"},
    )
    if status == 200 and payload.get("code") == 0:
        print("200")
        return 0

    print(status if status else "500")
    print(f"Lark send failed: http={status} payload={payload}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("500")
        print(f"Lark send failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
