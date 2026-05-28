#!/usr/bin/env bash
# agenttoolbench-guard PreToolUse hook.
#
# Forwards the Claude Code hook payload (on stdin) to the python
# guard module, which runs every enabled rule against the payload +
# session context. Warnings (if any) are written to stderr by the
# python module; the hook itself ALWAYS exits 0 — agenttoolbench-guard
# is warn-only per Allen's 2026-05-28 UX ratify ("工作流是最重要的").
#
# Failure mode: defensive. If the python module is missing or fails,
# the hook still exits 0 with no user-visible noise.

set +e  # never fail-stop

# Find the python interpreter.
PY="${ATB_PYTHON:-}"
if [ -z "$PY" ] && [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -x "$CLAUDE_PLUGIN_ROOT/.venv/bin/python3" ]; then
  PY="$CLAUDE_PLUGIN_ROOT/.venv/bin/python3"
fi
if [ -z "$PY" ]; then
  PY="$(command -v python3 2>/dev/null || true)"
fi
if [ -z "$PY" ]; then
  exit 0
fi

# Capture the guard's stderr into a temp file. If the guard ran
# successfully, surface that file as our own stderr (warnings reach
# the user). If it failed (e.g. module not importable), suppress it.
ERR_FILE="$(mktemp -t atb-guard.XXXXXX)"

# Pipe stdin through.
if "$PY" -m agenttoolbench.runtime.guard >/dev/null 2>"$ERR_FILE"; then
  cat "$ERR_FILE" >&2
elif [ -n "${CLAUDE_PLUGIN_ROOT:-}" ]; then
  # First try failed — module not on the python import path. Try the
  # plugin dir directly.
  PYTHONPATH="$CLAUDE_PLUGIN_ROOT:${PYTHONPATH:-}" \
    "$PY" -m agenttoolbench.runtime.guard >/dev/null 2>"$ERR_FILE" \
    && cat "$ERR_FILE" >&2
fi

rm -f "$ERR_FILE"
exit 0
