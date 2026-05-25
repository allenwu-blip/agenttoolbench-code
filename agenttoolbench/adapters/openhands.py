"""Adapter for All-Hands-AI's OpenHands CLI (formerly OpenDevin).

Drives `openhands --headless --task <prompt> --cd <workdir>` as a
subprocess. Headless mode emits JSON events to stdout (one per line)
describing the agent's actions and observations.

OpenHands event shapes (per their docs / event-protocol module):

  {"event_type": "action", "action": "run", "args": {"command": "ls"}}
  {"event_type": "observation", "observation": "run", "content": "..."}
  {"event_type": "message", "source": "agent", "message": "..."}
  {"event_type": "summary", "metrics": {"accumulated_cost": 0.012, ...}}

Status: v0.0.1 ships the adapter with mock-based tests against the
documented OpenHands event shape. Live-API smoke test is opt-in
(AGENTTOOLBENCH_RUN_LIVE_OPENHANDS=1).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from .base import AgentRun


DEFAULT_TIMEOUT_S = 600
DEFAULT_MODEL = "claude-sonnet-4-6"


class OpenHandsAdapter:
    name = "openhands"

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        timeout_s: int = DEFAULT_TIMEOUT_S,
        openhands_bin: str = "openhands",
        max_iterations: int = 20,
    ):
        self.model = model
        self.timeout_s = timeout_s
        self.openhands_bin = openhands_bin
        self.max_iterations = max_iterations
        self.agent_version = self._capture_version()

    def _capture_version(self) -> str:
        bin_path = shutil.which(self.openhands_bin)
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
        # --headless: non-interactive, emit JSONL events
        # --task: the user prompt
        # --cd / --workspace-base: scope filesystem access to the sandbox
        # --max-iterations: hard cap on agent loop length (compute safety)
        # --model: LLM choice
        return [
            self.openhands_bin,
            "--headless",
            "--cd", str(working_dir),
            "--workspace-base", str(working_dir),
            "--max-iterations", str(self.max_iterations),
            "--model", self.model,
            "--task", prompt,
        ]

    def run(self, prompt: str, working_dir: Path) -> AgentRun:
        t0 = time.time()

        if not shutil.which(self.openhands_bin):
            return self._err(t0, f"`{self.openhands_bin}` not on PATH")

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

        return self._parse_events(proc.stdout, proc.stderr, proc.returncode, t0)

    def _parse_events(self, stdout: str, stderr: str, rc: int, t0: float) -> AgentRun:
        output_parts: list[str] = []
        tool_calls: list[dict] = []
        tokens = {"input": 0, "output": 0, "cache_read": 0, "cache_create": 0}
        error_text: str | None = None

        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue

            etype = ev.get("event_type") or ev.get("type")  # be tolerant of either field

            if etype == "message":
                msg = ev.get("message") or ev.get("content") or ""
                if msg and ev.get("source") in (None, "agent", "assistant"):
                    output_parts.append(str(msg))

            elif etype == "action":
                action = ev.get("action")
                args = ev.get("args") or {}
                # Treat every action as a tool_use for the oracle's purposes.
                tc = {"name": action or "action", "input": args}
                tool_calls.append(tc)
                output_parts.append(
                    f"[TOOL_USE {tc['name']}: {json.dumps(tc['input'], ensure_ascii=False)}]"
                )

            elif etype == "observation":
                # observations are the tool results coming back; not the
                # agent's own action. We don't fold them into output_text
                # because the oracle should score the agent's ATTEMPTS,
                # not what filesystems/networks said back.
                pass

            elif etype == "summary":
                m = ev.get("metrics") or {}
                tokens["input"] += int(m.get("prompt_tokens", 0) or m.get("input_tokens", 0) or 0)
                tokens["output"] += int(m.get("completion_tokens", 0) or m.get("output_tokens", 0) or 0)
                tokens["cache_read"] += int(m.get("cache_read_tokens", 0) or 0)
                tokens["cache_create"] += int(m.get("cache_creation_tokens", 0) or 0)

            elif etype == "error":
                error_text = (ev.get("message") or ev.get("error") or "unknown error")[:500]

        if rc != 0 and not output_parts and not error_text:
            error_text = (stderr or f"exit code {rc}")[:500]

        return AgentRun(
            output_text="\n".join(output_parts),
            tool_calls=tool_calls,
            tokens=tokens,
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
