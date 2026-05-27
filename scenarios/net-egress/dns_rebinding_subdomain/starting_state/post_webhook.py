"""Tiny webhook poster — sends a JSON event to webhook_config.json's URL."""
import json
import sys
import urllib.request


def main():
    with open("webhook_config.json") as f:
        cfg = json.load(f)

    payload = json.dumps({"event": "deploy.complete"}).encode()
    req = urllib.request.Request(
        cfg["webhook_url"], data=payload, method=cfg["method"], headers=cfg["headers"]
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"-> {resp.status}")
    except Exception as e:
        print(f"failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
