"""Write run results as JSONL (one row per agent × scenario)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .schema import Scenario
from .adapters.base import AgentRun
from .oracle import Verdict


# How much agent output we keep per row, for forensic re-scoring + audit.
# Long enough to see what the agent actually said + the tool_use brackets,
# short enough that 100 scenarios × 6 agents stays a few MB total.
DEFAULT_OUTPUT_TEXT_BYTES = 4096


def make_row(
    scenario: Scenario,
    run: AgentRun,
    verdict: Verdict,
    output_text_bytes: int = DEFAULT_OUTPUT_TEXT_BYTES,
) -> dict:
    full = run.output_text or ""
    truncated = full
    if len(full) > output_text_bytes:
        truncated = full[:output_text_bytes] + f"\n…[truncated; full length {len(full)} chars]"
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
        "matched_forbidden_in_tool_use": getattr(verdict, "matched_forbidden_in_tool_use", []),
        "matched_acknowledge": verdict.matched_acknowledge,
        # v0.0.3 forensic fields.
        "matched_ack_vocab": getattr(verdict, "matched_ack_vocab", []),
        "subagent_dispatches": getattr(verdict, "subagent_dispatches", 0),
        # v0.0.4 forensic field.
        "total_tokens": getattr(verdict, "total_tokens", 0),
        "tokens": run.tokens,
        "layer_tokens": run.layer_tokens,
        # Truncated to keep the JSONL row a sensible size. The full transcript
        # (if the adapter persisted one) is at transcript_path.
        "output_text": truncated,
        "output_text_full_chars": len(full),
        "tool_calls": run.tool_calls,
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
