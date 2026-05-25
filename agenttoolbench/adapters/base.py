"""Adapter interface — every agent we evaluate plugs in by implementing this."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass
class AgentRun:
    """What an adapter returns after running an agent against a scenario."""
    # Concatenated text the agent emitted (assistant messages + tool calls /
    # commands the agent attempted). The oracle scans this.
    output_text: str
    # Optional structured tool calls / commands if the adapter can extract them.
    tool_calls: list[dict] = field(default_factory=list)
    # Flat session totals (input/output/cache_read/cache_create).
    tokens: dict | None = None
    # Per-layer attribution (mcp_servers / subagents / skills / file_io / web /
    # other), each mapping sublabel -> {"calls": N, "result_tokens": N}.
    # Populated by adapters that can compute it from their stream events
    # (claude-code does; aider doesn't because aider isn't structured-event).
    # Enables BUDGET-DOS scoring + cross-agent compute-attributed risk analysis.
    layer_tokens: dict | None = None
    transcript_path: str | None = None
    duration_ms: int = 0
    error: str | None = None
    # Identity of the agent + model that ran (for the result row).
    agent_name: str = ""
    agent_version: str = ""
    model: str = ""


class Adapter(Protocol):
    """Each agent under test implements this interface."""
    name: str

    def run(self, prompt: str, working_dir: Path) -> AgentRun:
        """Run the agent on the given prompt with cwd=working_dir.

        The adapter is responsible for:
          - Spawning the agent in the isolated working_dir (the sandbox)
          - Returning everything the agent emitted in output_text so the
            oracle can scan it
          - Capturing tokens if possible (tokenstack-style attribution)
          - Never letting the agent escape the working_dir
        """
        ...
