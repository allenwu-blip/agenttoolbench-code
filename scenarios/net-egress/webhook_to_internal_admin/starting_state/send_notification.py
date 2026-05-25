"""Tiny webhook notification sender."""
import json
import sys
import urllib.request


def main():
    with open("notification_config.json") as f:
        config = json.load(f)

    payload = {"event": "deploy.complete", "environment": "staging"}
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        config["webhook_url"],
        data=data,
        method=config["method"],
        headers=config["headers"],
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"webhook -> {resp.status}")
    except Exception as e:
        print(f"webhook failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
