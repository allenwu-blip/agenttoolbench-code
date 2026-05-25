"""Adapter for OpenAI's Codex CLI.

Drives `codex exec --json ...` as a subprocess. The Codex CLI's
non-interactive exec mode emits one JSON event per line (similar shape to
Anthropic's stream-json: an outer envelope around content blocks that
include text and tool_use entries).

Status: v0.0.1 ships the adapter with mock-based tests against the
documented Codex CLI JSON event shape. The live-API smoke test is opt-in
(set AGENTTOOLBENCH_RUN_LIVE_CODEX=1) and requires `codex` on PATH plus
the user's OpenAI auth configured.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from .base import AgentRun


DEFAULT_TIMEOUT_S = 300
DEFAULT_MODEL = "gpt-5-codex"


class CodexCliAdapter:
    name = "codex-cli"

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        timeout_s: int = DEFAULT_TIMEOUT_S,
        codex_bin: str = "codex",
        approval_mode: str = "auto",  # codex's equivalent of permission_mode
    ):
        self.model = model
        self.timeout_s = timeout_s
        self.codex_bin = codex_bin
        self.approval_mode = approval_mode
        self.agent_version = self._capture_version()

    def _capture_version(self) -> str:
        bin_path = shutil.which(self.codex_bin)
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
        # codex exec is the non-interactive "do this prompt and exit" mode
        # --json emits JSONL events to stdout
        # --cd scopes the working directory (codex equivalent of --add-dir)
        # --approval-mode controls whether tool calls auto-execute
        return [
            self.codex_bin, "exec",
            "--cd", str(working_dir),
            "--json",
            "--model", self.model,
            "--approval-mode", self.approval_mode,
            prompt,
        ]

    def run(self, prompt: str, working_dir: Path) -> AgentRun:
        t0 = time.time()

        if not shutil.which(self.codex_bin):
            return self._err(t0, f"`{self.codex_bin}` not on PATH")

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

        return self._parse_jsonl(proc.stdout, proc.stderr, proc.returncode, t0)

    def _parse_jsonl(self, stdout: str, stderr: str, rc: int, t0: float) -> AgentRun:
        # Codex emits events. We accept multiple plausible event shapes
        # documented by codex --help / openai's blog posts:
        #
        #   {"type":"message","role":"assistant","content":[{"type":"text","text":"..."}]}
        #   {"type":"tool_call","name":"shell","arguments":{"command":["bash","-lc","echo hi"]}}
        #   {"type":"tool_result","output":"..."}
        #   {"type":"completed","usage":{"input_tokens":N,"output_tokens":N,...}}
        #
        # We unify into output_text + tool_calls + tokens.
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

            ev_type = ev.get("type")

            if ev_type == "message" and ev.get("role") == "assistant":
                for block in ev.get("content") or []:
                    if isinstance(block, dict) and block.get("type") == "text":
                        output_parts.append(block.get("text", ""))

            elif ev_type == "tool_call":
                tc = {"name": ev.get("name"), "input": ev.get("arguments") or {}}
                tool_calls.append(tc)
                output_parts.append(
                    f"[TOOL_USE {tc['name']}: {json.dumps(tc['input'], ensure_ascii=False)}]"
                )

            elif ev_type == "completed":
                u = ev.get("usage") or {}
                tokens["input"] += int(u.get("input_tokens", 0) or 0)
                tokens["output"] += int(u.get("output_tokens", 0) or 0)
                # Codex's usage doesn't currently expose cache breakdown like
                # Anthropic's; leave cache_read/cache_create at 0.

            elif ev_type == "error":
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
