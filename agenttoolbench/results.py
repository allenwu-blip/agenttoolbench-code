"""Write run results as JSONL (one row per agent × scenario)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .schema import Scenario
from .adapters.base import AgentRun
from .oracle import Verdict


def make_row(scenario: Scenario, run: AgentRun, verdict: Verdict) -> dict:
    return {
        "scenario_id": scenario.id,
        "category": scenario.category,
        "agent": {
            "name": run.agent_name,
            "version": run.agent_version,
            "model": run.model,
        },
        "verdict": verdict.verdict,
        "matched_forbidden": verdict.matched_forbidden,
        "matched_acknowledge": verdict.matched_acknowledge,
        "tokens": run.tokens,
        "layer_tokens": run.layer_tokens,
        "transcript_path": run.transcript_path,
        "duration_ms": run.duration_ms,
        "ts": datetime.now(timezone.utc).isoformat(),
        "error": run.error,
    }


def append_jsonl(path: str | Path, row: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a") as f:
        f.write(json.dumps(row) + "\n")
