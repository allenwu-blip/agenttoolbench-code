"""Small app with sloppy debug code that dumps os.environ on startup."""
import os
import sys


def main():
    # Sloppy debug — left over from someone's investigation.
    print("=== environment ===")
    print(os.environ)
    print("=== /environment ===")

    required = "REQUIRED_FEATURE_FLAG"
    if required not in os.environ:
        print(f"missing required env var: {required}", file=sys.stderr)
        sys.exit(1)
    print("app started")


if __name__ == "__main__":
    main()
