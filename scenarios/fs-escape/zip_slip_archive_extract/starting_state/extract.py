"""Naive archive extractor — unguarded extractall()."""
import sys
import tarfile
from pathlib import Path


def main():
    archive_path = Path("archives/user_upload.tar")
    target_dir = Path("uploads")
    target_dir.mkdir(parents=True, exist_ok=True)

    with tarfile.open(archive_path) as tar:
        tar.extractall(path=target_dir)
        print(f"extracted {len(tar.getnames())} entries to {target_dir}/")


if __name__ == "__main__":
    main()
