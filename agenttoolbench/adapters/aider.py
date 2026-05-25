"""Adapter for Paul Gauthier's aider CLI.

Aider has the cleanest non-interactive interface of the three coding-agent
CLIs we evaluate:

    aider --message "<prompt>" \
          --yes-always \
          --no-stream \
          --no-pretty \
          --no-auto-commits \
          --no-git \
          --model <model> \
          <working_dir>

It does NOT emit structured JSON events by default — we capture stdout (the
agent's text + any visible tool actions) and infer tool calls from the
recognisable "Tool use" / "Running" lines aider prints. This is less rich
than the Anthropic / OpenAI stream-json paths, so we record everything
verbatim in output_text and rely on the oracle's substring matching.

Status: v0.0.1 ships the adapter with mock-based tests. Live-API smoke
test is opt-in (AGENTTOOLBENCH_RUN_LIVE_AIDER=1) and requires `aider` on
PATH + the user's chosen model auth.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

from .base import AgentRun


DEFAULT_TIMEOUT_S = 300
DEFAULT_MODEL = "claude-sonnet-4-6"


class AiderAdapter:
    name = "aider"

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        timeout_s: int = DEFAULT_TIMEOUT_S,
        aider_bin: str = "aider",
    ):
        self.model = model
        self.timeout_s = timeout_s
        self.aider_bin = aider_bin
        self.agent_version = self._capture_version()

    def _capture_version(self) -> str:
        bin_path = shutil.which(self.aider_bin)
        if not bin_path:
            return "not-installed"
        try:
            r = subprocess.run(
                [bin_path, "--version"], capture_output=True, text=True, timeout=10
            )
            return (r.stdout or r.stderr).strip().splitlines()[0] if (r.stdout or r.stderr) else "?"
        except Exception:
            return "?"

    def _build_cmd(self, prompt: str, working_dir: Path) -> list[str]:
        # --yes-always         : auto-accept tool prompts (we WANT to observe what
        #                        the agent does without an interactive gate)
        # --no-stream / --no-pretty : clean text output for capture
        # --no-auto-commits / --no-git : keep aider from touching git in the sandbox
        # --no-suggest-shell-commands : aider sometimes prints shell suggestions
        #                               instead of running them; we want runs.
        return [
            self.aider_bin,
            "--message", prompt,
            "--yes-always",
            "--no-stream",
            "--no-pretty",
            "--no-auto-commits",
            "--no-git",
            "--no-suggest-shell-commands",
            "--model", self.model,
            str(working_dir),
        ]

    def run(self, prompt: str, working_dir: Path) -> AgentRun:
        t0 = time.time()

        if not shutil.which(self.aider_bin):
            return self._err(t0, f"`{self.aider_bin}` not on PATH")

        cmd = self._build_cmd(prompt, working_dir)
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(working_dir),
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
            )
        except subprocess.TimeoutExpired:
            return self._err(t0, f"timeout after {self.timeout_s}s")
        except Exception as e:
            return self._err(t0, f"subprocess error: {e}")

        # Aider doesn't emit structured JSON: take stdout verbatim. The oracle's
        # substring matching handles it the same way it handles other adapters'
        # text. We surface any "Running" / "Tool" lines as a coarse tool_calls
        # list so cross-adapter comparison has SOMETHING in tool_calls.
        output_text = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")
        tool_calls: list[dict] = []
        for line in (proc.stdout or "").splitlines():
            ls = line.strip()
            # Recognisable shapes aider prints when it's about to run a shell:
            #   "Running: <cmd>"
            #   "Run shell command: <cmd>"
            if ls.startswith("Running: "):
                tool_calls.append({"name": "shell", "input": {"command": ls[len("Running: "):]}})
            elif ls.startswith("Run shell command: "):
                tool_calls.append({"name": "shell", "input": {"command": ls[len("Run shell command: "):]}})

        error_text: str | None = None
        if proc.returncode != 0 and not (proc.stdout or "").strip():
            error_text = (proc.stderr or f"exit code {proc.returncode}")[:500]

        return AgentRun(
            output_text=output_text,
            tool_calls=tool_calls,
            tokens=None,  # aider doesn't expose per-run token counts on stdout
            transcript_path=None,
            duration_ms=int((time.time() - t0) * 1000),
            error=error_text,
            agent_name=self.name,
            agent_version=self.agent_version,
            model=self.model,
        )

    def _err(self, t0: float, msg: str) -> AgentRun:
        return AgentRun(
            output_text="",
            tokens=None,
            duration_ms=int((time.time() - t0) * 1000),
            error=msg,
            agent_name=self.name,
            agent_version=self.agent_version,
            model=self.model,
        )
