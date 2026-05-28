"""agenttoolbench runtime guard — Claude Code PreToolUse hook orchestrator.

How it integrates with Claude Code:
  1. User installs the agenttoolbench-code Claude Code plugin
     (`.claude-plugin/plugin.json` declares hooks/ + skills/).
  2. Claude Code reads `hooks/hooks.json` and registers
     `hooks/pre-tool-use.sh` as a PreToolUse hook.
  3. Before any tool_use fires, Claude Code pipes a JSON payload to
     the hook on stdin. The payload contains:
       {
         "tool_name": "Bash" | "Read" | "Edit" | "Agent" | ...,
         "tool_input": { ... tool-specific args ... },
         "session_id": "...",
         "transcript_path": "/Users/.../session.jsonl"
       }
  4. The hook script invokes `python -m agenttoolbench.runtime.guard`,
     piping the payload to its stdin.
  5. This module reads the payload, scans the transcript for prior
     tool_uses (to give rules context), runs every enabled rule, and
     prints any warnings to stderr.
  6. Hook exits 0 — ALWAYS. Per Allen's 2026-05-28 UX ratify
     ("工作流是最重要的"), the guard is warn-only and never blocks.

Failure mode: defensive. Any exception → exit 0 with no output.
The guard must never interfere with user workflow.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .rules import (
    npm_install,
    pip_install,
    net_rfc1918,
    shell_with_file_content,
    subagent_burst,
)


# Registry of enabled rules. Each rule exposes a
# `check(payload, *, session_ctx) -> list[dict]` function where
# session_ctx is a dict of optional context keys:
#   - "prior_reads":            list[str] — files Read this session
#   - "prior_subagent_count":   int — number of Agent/Task dispatches so far
# New rules drop in alongside the others.
_RULES = [
    npm_install,
    pip_install,
    net_rfc1918,
    shell_with_file_content,
    subagent_burst,
]


def collect_session_context(transcript_path: str | None) -> dict:
    """Scan the session transcript JSONL once and collect every context
    field rules might want. Returns a dict with:
      - "prior_reads":          list[str] — files Read so far
      - "prior_subagent_count": int — Agent/Task tool_uses so far

    Returns sensible defaults if transcript missing / unreadable.
    Defensive: never raises.

    Single-pass over the transcript so we don't read it once per rule.
    """
    ctx: dict = {"prior_reads": [], "prior_subagent_count": 0}
    if not transcript_path:
        return ctx
    p = Path(transcript_path)
    if not p.is_file():
        return ctx
    try:
        with p.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                msg = rec.get("message") or {}
                content = msg.get("content") or []
                if not isinstance(content, list):
                    continue
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") != "tool_use":
                        continue
                    name = block.get("name")
                    if name == "Read":
                        inp = block.get("input") or {}
                        fp = inp.get("file_path")
                        if isinstance(fp, str):
                            ctx["prior_reads"].append(fp)
                    elif name in ("Agent", "Task"):
                        ctx["prior_subagent_count"] += 1
    except Exception:
        # Defensive: any transcript parse failure → return partial ctx.
        # Better to under-collect than to crash the hook.
        return ctx
    return ctx


# Backward-compat shim: old function name still works.
def collect_prior_reads(transcript_path: str | None) -> list[str]:
    """Deprecated; use collect_session_context. Kept for backward compat."""
    return collect_session_context(transcript_path)["prior_reads"]


def run_rules(payload: dict, prior_reads: list[str] | None = None,
              session_ctx: dict | None = None) -> list[dict]:
    """Run every enabled rule against the payload + context. Return
    flat list of warnings. Each rule failure is swallowed.

    Accepts either:
      - `prior_reads=[...]` (legacy positional kwarg, wraps into session_ctx)
      - `session_ctx={"prior_reads": [...], ...}` (preferred, extensible)
    """
    if session_ctx is None:
        session_ctx = {"prior_reads": prior_reads or []}
    elif prior_reads is not None and "prior_reads" not in session_ctx:
        session_ctx = {**session_ctx, "prior_reads": prior_reads}

    warnings: list[dict] = []
    for rule_mod in _RULES:
        try:
            result = rule_mod.check(payload, session_ctx=session_ctx)
        except Exception:
            continue
        if isinstance(result, list):
            warnings.extend(w for w in result if isinstance(w, dict))
    return warnings


def format_warnings(warnings: list[dict]) -> str:
    """Render warnings as a human-readable banner for stderr."""
    if not warnings:
        return ""
    lines = []
    lines.append("─── agenttoolbench-guard ──────────────────────────────")
    for w in warnings:
        level = (w.get("level") or "warn").upper()
        rule = w.get("rule") or "?"
        msg = w.get("message") or ""
        lines.append(f"⚠ [{level}] {rule}")
        # Wrap long messages naturally.
        for chunk in _wrap(msg, 70):
            lines.append(f"   {chunk}")
    lines.append("──────────────────────────────────────────────────────")
    return "\n".join(lines)


def _wrap(text: str, width: int) -> list[str]:
    """Tiny word-wrap. stdlib textwrap would do but we keep this
    stdlib-only with no extra import — the agenttoolbench guard runs
    in a hook subprocess and start-up time matters."""
    out: list[str] = []
    current = ""
    for word in (text or "").split():
        if not current:
            current = word
        elif len(current) + 1 + len(word) <= width:
            current += " " + word
        else:
            out.append(current)
            current = word
    if current:
        out.append(current)
    return out or [""]


def main() -> int:
    """Hook entry point. Always returns 0 (warn-only)."""
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return 0
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            return 0
        session_ctx = collect_session_context(payload.get("transcript_path"))
        warnings = run_rules(payload, session_ctx=session_ctx)
        if warnings:
            sys.stderr.write(format_warnings(warnings) + "\n")
    except Exception:
        # Hook NEVER blocks user workflow. Any failure → silent exit 0.
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
