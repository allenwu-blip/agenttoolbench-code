"""Adapter for Princeton/Stanford NLP's SWE-agent (sweagent CLI).

SWE-agent is heavier than the other agents we wrap — it expects a Docker
sandbox per instance and writes a trajectory file to disk rather than
streaming events to stdout. Our adapter takes the same shape as the
others: subprocess + parse output → AgentRun.

The CLI we drive (current as of mid-2026):

    sweagent run \\
      --agent.model.name <model> \\
      --env.repo.path <working_dir> \\
      --problem_statement.text "<prompt>" \\
      --output_dir <out_dir> \\
      --agent.model.max_input_tokens 100000

After the run, sweagent writes:
  - <out_dir>/<instance_id>/<instance_id>.traj.json  (full trajectory)
  - <out_dir>/<instance_id>/<instance_id>.pred       (prediction artefact)

We read the trajectory to recover the agent's actions + tool calls.

Status: v0.0.1 ships the adapter with mock-based tests. Live-API smoke
test is opt-in (AGENTTOOLBENCH_RUN_LIVE_SWE_AGENT=1) and requires
`sweagent` on PATH, Docker running, and the user's chosen model auth.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from .base import AgentRun


DEFAULT_TIMEOUT_S = 900  # SWE-agent runs longer than the others
DEFAULT_MODEL = "claude-sonnet-4-6"


class SweAgentAdapter:
    name = "swe-agent"

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        timeout_s: int = DEFAULT_TIMEOUT_S,
        sweagent_bin: str = "sweagent",
        max_input_tokens: int = 100_000,
    ):
        self.model = model
        self.timeout_s = timeout_s
        self.sweagent_bin = sweagent_bin
        self.max_input_tokens = max_input_tokens
        self.agent_version = self._capture_version()

    def _capture_version(self) -> str:
        bin_path = shutil.which(self.sweagent_bin)
        if not bin_path:
            return "not-installed"
        try:
            r = subprocess.run(
                [bin_path, "--version"], capture_output=True, text=True, timeout=10
            )
            return (r.stdout or r.stderr).strip().splitlines()[0] if (r.stdout or r.stderr) else "?"
        except Exception:
            return "?"

    def _build_cmd(self, prompt: str, working_dir: Path, out_dir: Path) -> list[str]:
        return [
            self.sweagent_bin, "run",
            "--agent.model.name", self.model,
            "--agent.model.max_input_tokens", str(self.max_input_tokens),
            "--env.repo.path", str(working_dir),
            "--problem_statement.text", prompt,
            "--output_dir", str(out_dir),
        ]

    def run(self, prompt: str, working_dir: Path) -> AgentRun:
        t0 = time.time()

        if not shutil.which(self.sweagent_bin):
            return self._err(t0, f"`{self.sweagent_bin}` not on PATH")

        with tempfile.TemporaryDirectory(prefix="sweagent-out-") as out_dir_s:
            out_dir = Path(out_dir_s)
            cmd = self._build_cmd(prompt, working_dir, out_dir)
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

            return self._parse_trajectory(out_dir, proc.stdout, proc.stderr, proc.returncode, t0)

    def _parse_trajectory(
        self,
        out_dir: Path,
        stdout: str,
        stderr: str,
        rc: int,
        t0: float,
    ) -> AgentRun:
        """Find sweagent's trajectory file and extract actions + tokens."""
        traj_files = list(out_dir.rglob("*.traj.json"))
        output_parts: list[str] = []
        tool_calls: list[dict] = []
        tokens = {"input": 0, "output": 0, "cache_read": 0, "cache_create": 0}
        error_text: str | None = None

        if not traj_files:
            # No trajectory written: fall back to stdout (best-effort)
            output_parts.append(stdout or "")
            if rc != 0 and not (stdout or "").strip():
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

        # Use the first trajectory file (one per instance in v0.0.1)
        traj_path = traj_files[0]
        try:
            traj = json.loads(traj_path.read_text())
        except Exception as e:
            return self._err(t0, f"could not parse trajectory at {traj_path}: {e}")

        # SWE-agent trajectory schema (current):
        #   {"trajectory": [ {"role":"assistant","content":"...","action":"...","tool":"..."}, ... ],
        #    "info": {"model_stats": {"tokens_sent": N, "tokens_received": N, ...}}}
        for step in traj.get("trajectory") or []:
            if not isinstance(step, dict):
                continue
            role = step.get("role")
            content = step.get("content") or ""
            action = step.get("action") or step.get("tool")
            args = step.get("action_args") or step.get("tool_args") or {}

            if role in ("assistant", "agent") and content:
                output_parts.append(str(content))

            if action:
                tc = {"name": str(action), "input": args if isinstance(args, dict) else {"raw": args}}
                tool_calls.append(tc)
                output_parts.append(
                    f"[TOOL_USE {tc['name']}: {json.dumps(tc['input'], ensure_ascii=False)}]"
                )

        info = traj.get("info") or {}
        stats = info.get("model_stats") or {}
        tokens["input"] = int(stats.get("tokens_sent", 0) or 0)
        tokens["output"] = int(stats.get("tokens_received", 0) or 0)
        # SWE-agent's per-step stats don't expose cache breakdown — leave 0.

        return AgentRun(
            output_text="\n".join(output_parts),
            tool_calls=tool_calls,
            tokens=tokens,
            transcript_path=str(traj_path),
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
