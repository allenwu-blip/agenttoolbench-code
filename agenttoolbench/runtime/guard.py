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

from .rules import npm_install


# Registry of enabled rules. Each rule exposes a `check(payload, *,
# prior_reads) -> list[dict]` function. v0.0.1 ships with the
# npm_install rule only; others are stubbed for incremental rollout.
_RULES = [
    npm_install,
]


def collect_prior_reads(transcript_path: str | None) -> list[str]:
    """Scan the session transcript JSONL for tool_use blocks of type
    "Read" and return the file_paths that were read.

    Returns [] if transcript missing, unreadable, or malformed.
    Defensive: never raises.
    """
    if not transcript_path:
        return []
    p = Path(transcript_path)
    if not p.is_file():
        return []
    reads: list[str] = []
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
                # Anthropic transcript shape: assistant messages contain
                # `message.content` blocks; tool_use blocks have name +
                # input. We scan for Read tool_use specifically.
                msg = rec.get("message") or {}
                content = msg.get("content") or []
                if not isinstance(content, list):
                    continue
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") != "tool_use":
                        continue
                    if block.get("name") != "Read":
                        continue
                    inp = block.get("input") or {}
                    fp = inp.get("file_path")
                    if isinstance(fp, str):
                        reads.append(fp)
    except Exception:
        # Defensive: any transcript parse failure → no prior reads.
        # Better to miss context than to crash the hook.
        return reads
    return reads


def run_rules(payload: dict, prior_reads: list[str]) -> list[dict]:
    """Run every enabled rule against the payload + context. Return
    flat list of warnings. Each rule failure is swallowed."""
    warnings: list[dict] = []
    for rule_mod in _RULES:
        try:
            result = rule_mod.check(payload, prior_reads=prior_reads)
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
        prior_reads = collect_prior_reads(payload.get("transcript_path"))
        warnings = run_rules(payload, prior_reads)
        if warnings:
            sys.stderr.write(format_warnings(warnings) + "\n")
    except Exception:
        # Hook NEVER blocks user workflow. Any failure → silent exit 0.
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
