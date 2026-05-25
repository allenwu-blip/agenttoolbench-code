"""End-to-end runner: scenario × adapter → verdict → JSONL row."""
from __future__ import annotations

from pathlib import Path

from .schema import Scenario, load_scenario
from .adapters.base import Adapter
from .sandbox import per_scenario_workdir
from .oracle import score
from .results import make_row, append_jsonl


def run_scenario(
    scenario: Scenario | str | Path,
    adapter: Adapter,
    results_path: str | Path = "results.jsonl",
) -> dict:
    """Run one adapter against one scenario; append to JSONL; return the row."""
    if not isinstance(scenario, Scenario):
        scenario = load_scenario(scenario)

    with per_scenario_workdir(scenario.starting_state_path) as workdir:
        run = adapter.run(scenario.prompt, workdir)

    verdict = score(scenario, run)
    row = make_row(scenario, run, verdict)
    append_jsonl(results_path, row)
    return row
