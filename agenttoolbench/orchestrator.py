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
    run_index: int = 0,
    total_runs: int = 1,
) -> dict:
    """Run one adapter against one scenario; append to JSONL; return the row.

    v0.0.2: each invocation produces ONE row with run_index/total_runs
    annotations so multiple runs of the same (agent, scenario) are
    aggregateable downstream by leaderboard.compute_leaderboard().
    Each call gets a FRESH per_scenario_workdir for true isolation.
    """
    if not isinstance(scenario, Scenario):
        scenario = load_scenario(scenario)

    with per_scenario_workdir(scenario.starting_state_path) as workdir:
        run = adapter.run(scenario.prompt, workdir)

    verdict = score(scenario, run)
    row = make_row(scenario, run, verdict, run_index=run_index, total_runs=total_runs)
    append_jsonl(results_path, row)
    return row
