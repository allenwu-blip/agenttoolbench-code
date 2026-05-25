"""Adapter for Anthropic's Claude Code CLI.

Drives `claude -p --output-format stream-json --verbose ...` as a subprocess,
parses the JSONL event stream, extracts every text block AND every tool_use
block into output_text (so the oracle can see what the agent ATTEMPTED, not
just what it finally said), and aggregates token usage.

Defaults are tuned for safe benchmark runs:
  - --add-dir <sandbox_workdir>        scope tool access to the sandbox
  - --max-budget-usd 0.50               hard per-scenario cost cap
  - --permission-mode auto              accept routine tool calls (a benchmark
                                        wants to OBSERVE what the agent does,
                                        not be blocked by approval prompts)
  - --no-session-persistence            don't litter ~/.claude/projects
  - --disable-slash-commands            no host-plugin contamination
  - --bare (optional)                   maximally clean env, requires
                                        ANTHROPIC_API_KEY (skips OAuth/keychain)

The adapter NEVER auto-enables --dangerously-skip-permissions. If you want
the agent to be allowed to do something dangerous (so you can measure whether
it WILL), set permission_mode='bypassPermissions' explicitly.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from .base import AgentRun
from ..layer_attribution import attribute_stream_events


DEFAULT_TIMEOUT_S = 300
DEFAULT_MAX_BUDGET_USD = 0.50
DEFAULT_MODEL = "claude-sonnet-4-6"


class ClaudeCodeAdapter:
    name = "claude-code"

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        bare: bool = False,
        max_budget_usd: float = DEFAULT_MAX_BUDGET_USD,
        permission_mode: str = "auto",
        timeout_s: int = DEFAULT_TIMEOUT_S,
        claude_bin: str = "claude",
    ):
        self.model = model
        self.bare = bare
        self.max_budget_usd = max_budget_usd
        self.permission_mode = permission_mode
        self.timeout_s = timeout_s
        self.claude_bin = claude_bin
        self.agent_version = self._capture_version()

    def _capture_version(self) -> str:
        bin_path = shutil.which(self.claude_bin)
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
        cmd = [self.claude_bin, "-p", prompt]
        if self.bare:
            cmd.insert(1, "--bare")
        cmd += [
            "--add-dir", str(working_dir),
            "--output-format", "stream-json",
            "--verbose",
            "--max-budget-usd", str(self.max_budget_usd),
            "--model", self.model,
            "--no-session-persistence",
            "--permission-mode", self.permission_mode,
            "--disable-slash-commands",
        ]
        return cmd

    def run(self, prompt: str, working_dir: Path) -> AgentRun:
        t0 = time.time()

        if not shutil.which(self.claude_bin):
            return self._err(t0, f"`{self.claude_bin}` not on PATH")

        if self.bare and not os.environ.get("ANTHROPIC_API_KEY"):
            return self._err(
                t0,
                "--bare requires ANTHROPIC_API_KEY in env (OAuth + keychain are skipped under --bare)",
            )

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

        return self._parse_stream_json(proc.stdout, proc.stderr, proc.returncode, t0)

    # ---- parsing ----

    def _parse_stream_json(self, stdout: str, stderr: str, rc: int, t0: float) -> AgentRun:
        output_parts: list[str] = []
        tool_calls: list[dict] = []
        tokens = {"input": 0, "output": 0, "cache_read": 0, "cache_create": 0}
        error_text: str | None = None

        # Materialise events once so we can both stream-iterate and pass to the
        # tokenstack-style per-layer attribution helper below.
        events: list[dict] = []
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue

        for ev in events:
            ev_type = ev.get("type")

            if ev_type == "assistant":
                msg = ev.get("message") or {}
                u = msg.get("usage") or {}
                tokens["input"] += int(u.get("input_tokens", 0) or 0)
                tokens["output"] += int(u.get("output_tokens", 0) or 0)
                tokens["cache_read"] += int(u.get("cache_read_input_tokens", 0) or 0)
                tokens["cache_create"] += int(u.get("cache_creation_input_tokens", 0) or 0)

                for block in msg.get("content") or []:
                    if not isinstance(block, dict):
                        continue
                    btype = block.get("type")
                    if btype == "text":
                        output_parts.append(block.get("text", ""))
                    elif btype == "tool_use":
                        tc = {
                            "name": block.get("name"),
                            "input": block.get("input") or {},
                        }
                        tool_calls.append(tc)
                        # Project the tool call into output_text so the oracle
                        # can scan it. The COMMAND a Bash tool_use carried is
                        # the actual attack surface; without surfacing it,
                        # silent_fail goes undetected when the agent does the
                        # bad action without mentioning it in text.
                        output_parts.append(
                            f"[TOOL_USE {tc['name']}: {json.dumps(tc['input'], ensure_ascii=False)}]"
                        )

            elif ev_type == "result":
                if ev.get("is_error"):
                    error_text = (ev.get("result") or "unknown error")[:500]

        # Subprocess error (nonzero rc, nothing useful parsed)
        if rc != 0 and not output_parts and not error_text:
            error_text = (stderr or f"exit code {rc}")[:500]

        # Per-layer attribution from the same event stream.
        # This is what makes BUDGET-DOS scoring possible: surface "75% of this
        # run's tool_result tokens came from subagent return blobs" etc.
        layer_tokens = attribute_stream_events(events)

        return AgentRun(
            output_text="\n".join(output_parts),
            tool_calls=tool_calls,
            tokens=tokens,
            layer_tokens=layer_tokens,
            transcript_path=None,  # --no-session-persistence: no transcript on disk
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
