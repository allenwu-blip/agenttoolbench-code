"""Tiny deploy hook runner.

Loads the hook string from deploy.json and shells out to it.
"""
import json
import subprocess
import sys


def main():
    with open("deploy.json") as f:
        config = json.load(f)
    hook = config["hook"]
    timeout = config.get("timeout_seconds", 60)
    result = subprocess.run(hook, shell=True, timeout=timeout)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
