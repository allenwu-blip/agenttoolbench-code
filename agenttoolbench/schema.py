"""Minimal scenario and result schema loading.

We deliberately don't pull pydantic for v0.0.1 — plain dicts + validation
keeps the install footprint small. The authoritative schema lives in
schema/*.schema.json; this module just loads + lightly validates.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


VALID_CATEGORIES = {
    "PI-CODE", "PI-TOOL", "CMD-INJ", "CRED-LEAK",
    "DEP-MAL", "FS-ESCAPE", "NET-EGRESS", "BUDGET-DOS",
}
VALID_ORACLE_KINDS = {"forbidden_substring", "forbidden_regex", "file_written", "exit_code"}


@dataclass
class Oracle:
    kind: str
    patterns: list[str] = field(default_factory=list)
    must_acknowledge: list[str] = field(default_factory=list)
    # v0.0.3 (BUDGET-DOS axis): if set, count Agent/Task tool_uses in
    # AgentRun.tool_calls; if count > max_subagent_dispatches the verdict
    # is downgraded to silent_fail (the agent obeyed the recursive fan-out
    # attack regardless of what its narrative said). Also overrides "error"
    # verdicts — a crash mid-dispatch still proves the attack landed.
    # None = no gating (v0.0.2 behaviour).
    max_subagent_dispatches: int | None = None
    # v0.0.4 (BUDGET-DOS axis, token-based): if set, sum AgentRun.tokens
    # (input + output + cache_read + cache_create); if total >
    # max_total_tokens, downgrade caught/error → silent_fail. Captures
    # compute-burn attacks that don't fan out via subagents (e.g. "read
    # 100 files and summarise each"). The two rules compose via OR —
    # either tripping fires silent_fail.
    max_total_tokens: int | None = None


@dataclass
class Scenario:
    id: str
    category: str
    title: str
    prompt: str
    oracle: Oracle
    source: str = "synthetic"
    starting_state_dir: str = "starting_state"
    notes: str = ""
    # absolute path to the directory containing scenario.yaml — set by loader
    base_dir: Path | None = None

    @property
    def starting_state_path(self) -> Path:
        assert self.base_dir is not None, "base_dir not set; load via load_scenario()"
        return self.base_dir / self.starting_state_dir


def load_scenario(scenario_yaml_path: str | Path) -> Scenario:
    """Load and lightly validate a scenario.yaml file."""
    p = Path(scenario_yaml_path).resolve()
    with open(p) as f:
        d: dict[str, Any] = yaml.safe_load(f)

    # Required keys
    for k in ("id", "category", "title", "prompt", "oracle"):
        if k not in d:
            raise ValueError(f"{p}: missing required key '{k}'")
    if d["category"] not in VALID_CATEGORIES:
        raise ValueError(
            f"{p}: category '{d['category']}' not in {sorted(VALID_CATEGORIES)}"
        )
    oracle_d = d["oracle"]
    if oracle_d.get("kind") not in VALID_ORACLE_KINDS:
        raise ValueError(
            f"{p}: oracle.kind '{oracle_d.get('kind')}' not in {sorted(VALID_ORACLE_KINDS)}"
        )

    oracle = Oracle(
        kind=oracle_d["kind"],
        patterns=list(oracle_d.get("patterns", [])),
        must_acknowledge=list(oracle_d.get("must_acknowledge", [])),
        max_subagent_dispatches=oracle_d.get("max_subagent_dispatches"),
        max_total_tokens=oracle_d.get("max_total_tokens"),
    )
    return Scenario(
        id=d["id"],
        category=d["category"],
        title=d["title"],
        prompt=d["prompt"],
        oracle=oracle,
        source=d.get("source", "synthetic"),
        starting_state_dir=d.get("starting_state_dir", "starting_state"),
        notes=d.get("notes", ""),
        base_dir=p.parent,
    )
