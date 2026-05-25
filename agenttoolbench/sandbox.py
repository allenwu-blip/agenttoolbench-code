"""Sandbox: per-scenario isolated working directory.

v0.0.1 is plain tempdir-based — no Docker, no chroot. The agent runs against
a private copy of the scenario's starting_state. Future versions will add
container isolation; for now the contract is just "the agent cannot easily
escape to your real filesystem because it's pointed at a temp dir."
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from contextlib import contextmanager
from typing import Generator


@contextmanager
def per_scenario_workdir(starting_state: Path) -> Generator[Path, None, None]:
    """Yield a fresh temp directory pre-populated with the scenario's starting state."""
    if not starting_state.exists():
        # An empty starting state is allowed — yield an empty dir.
        with tempfile.TemporaryDirectory(prefix="atb-empty-") as d:
            yield Path(d)
        return

    with tempfile.TemporaryDirectory(prefix="atb-scenario-") as d:
        dst = Path(d)
        # copy contents (not the directory itself)
        for entry in starting_state.iterdir():
            if entry.is_dir():
                shutil.copytree(entry, dst / entry.name)
            else:
                shutil.copy2(entry, dst / entry.name)
        yield dst
