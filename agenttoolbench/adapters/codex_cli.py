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
        sandbox_mode: str = "workspace-write",  # codex 0.134+ replacement
                                                # for the deprecated --full-auto.
                                                # Allows the agent to run shell
                                                # commands without per-call
                                                # approval, scoped to the
                                                # workspace dir.
                                                # Other valid values:
                                                # "read-only" / "danger-full-access".
    ):
        self.model = model
        self.timeout_s = timeout_s
        self.codex_bin = codex_bin
        self.sandbox_mode = sandbox_mode
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
        # codex exec is the non-interactive "do this prompt and exit" mode.
        # codex 0.134 (Oct 2026) flag set, verified via `codex exec --help`:
        #   --cd <DIR>                 working directory
        #   --json                     emit JSONL events to stdout
        #   -m, --model <MODEL>        model alias
        #   -s, --sandbox <MODE>       sandbox policy (replaces deprecated
        #                              --full-auto). workspace-write = the
        #                              agent can run shell commands and edit
        #                              files in the workspace without per-call
        #                              approval. This is what we want for the
        #                              benchmark — observe what the agent
        #                              ACTUALLY does, including dangerous calls.
        #   --skip-git-repo-check      allow running in non-git dirs (our
        #                              sandboxes under /tmp/atb-scenario-*
        #                              are not git repos). Without this codex
        #                              hard-fails: "Not inside a trusted
        #                              directory and --skip-git-repo-check
        #                              was not specified."
        # Earlier adapter used --full-auto + no skip-git-repo-check, which
        # produced 20/20 error verdicts on real codex 0.134 (deprecated
        # warning + trusted-dir fail).
        return [
            self.codex_bin, "exec",
            "--cd", str(working_dir),
            "--json",
            "--model", self.model,
            "--sandbox", self.sandbox_mode,
            "--skip-git-repo-check",
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
        # codex 0.134 (Oct 2026) JSONL event schema, verified by probing
        # `codex exec --json --model gpt-4o-mini`:
        #
        #   {"type":"thread.started","thread_id":"..."}
        #   {"type":"turn.started"}
        #   {"type":"item.started","item":{"id":"item_N","type":"command_execution",
        #                                  "command":"...","status":"in_progress"}}
        #   {"type":"item.completed","item":{"id":"item_N","type":"agent_message","text":"..."}}
        #   {"type":"item.completed","item":{"id":"item_N","type":"command_execution",
        #                                    "command":"...","aggregated_output":"...",
        #                                    "exit_code":0,"status":"completed"}}
        #   {"type":"turn.completed","usage":{"input_tokens":N,"output_tokens":N,
        #                                     "cached_input_tokens":N,
        #                                     "reasoning_output_tokens":N}}
        #
        # Item types observed: "agent_message" (text) and "command_execution"
        # (shell tool call). Other inner types (reasoning, etc.) ignored.
        #
        # The earlier adapter assumed message / tool_call / completed event
        # types — wrong for 0.134, resulting in 20/20 empty output rows.
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

            if ev_type == "item.completed":
                item = ev.get("item") or {}
                item_type = item.get("type")
                if item_type == "agent_message":
                    text = item.get("text") or ""
                    if text:
                        output_parts.append(text)
                elif item_type == "command_execution":
                    command = item.get("command") or ""
                    tc = {"name": "shell", "input": {"command": command}}
                    tool_calls.append(tc)
                    # Emit a [TOOL_USE ...] bracket so the oracle's
                    # _TOOL_USE_BLOCK_RE picks this up as execution
                    # evidence (matching the claude-code adapter's shape).
                    output_parts.append(
                        f"[TOOL_USE shell: {json.dumps(tc['input'], ensure_ascii=False)}]"
                    )
                    # Also include the command output for narrative context —
                    # truncated since shell output can be long.
                    agg = item.get("aggregated_output") or ""
                    if agg:
                        output_parts.append(
                            f"[TOOL_RESULT shell exit={item.get('exit_code')}: "
                            f"{agg[:500]}{'…' if len(agg) > 500 else ''}]"
                        )
                # Other item types (reasoning, etc.) intentionally ignored.

            elif ev_type == "turn.completed":
                u = ev.get("usage") or {}
                tokens["input"] += int(u.get("input_tokens", 0) or 0)
                tokens["output"] += int(u.get("output_tokens", 0) or 0)
                tokens["cache_read"] += int(u.get("cached_input_tokens", 0) or 0)
                # codex 0.134 doesn't expose cache_creation tokens separately
                # like Anthropic does; leave cache_create at 0.

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
