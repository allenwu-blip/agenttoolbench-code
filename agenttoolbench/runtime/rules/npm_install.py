"""npm_install rule: flag `npm install` (or `npm i`) tool_uses when no
prior Read of package.json has occurred in this session.

Rule rationale (from agenttoolbench v0.0.2 benchmark data):
  - claude-code Sonnet silent-fails the npm-postinstall attack 2/3 N=3 runs
  - Both Codex and aider catch it because they don't auto-shell
  - The defence the catchers share: read package.json FIRST, decide SECOND
  - This rule fires before npm install would run, surfaces the
    suggestion to read the manifest first, but does NOT block (warn-only
    per Allen's UX ratify 2026-05-28).
"""
from __future__ import annotations

import re


# Matches `npm install` and `npm i` (with optional args, but NOT `npm init`
# / `npm info` / other npm commands that contain `i` as a substring).
_NPM_INSTALL_RE = re.compile(
    r"""(?xs)
    ^\s*npm
    \s+
    (?:install|i)
    (?:\s+|$)
    """
)

_IGNORE_SCRIPTS_RE = re.compile(r"\B--ignore-scripts\b")


def check(payload: dict, *, prior_reads: list[str]) -> list[dict]:
    """Return a list of warning dicts (0 or 1 element for this rule).

    Args:
      payload:     The PreToolUse hook payload. Expected keys:
                     tool_name (e.g. "Bash")
                     tool_input (dict; for Bash: command, description, timeout)
      prior_reads: List of file paths that have been Read in this session
                   so far (from transcript scan or hook-side state).
                   Empty list means "no prior reads".

    Returns:
      [] if the rule doesn't apply or no warning needed.
      [{"level": "warn", "rule": "...", "message": "..."}] if warning fires.
    """
    if not isinstance(payload, dict):
        return []
    if payload.get("tool_name") != "Bash":
        return []
    tool_input = payload.get("tool_input") or {}
    cmd = tool_input.get("command") or ""
    if not _NPM_INSTALL_RE.match(cmd):
        return []
    # User explicitly opted out of lifecycle scripts — that's the actual
    # attack vector being neutered, so no warning.
    if _IGNORE_SCRIPTS_RE.search(cmd):
        return []
    # Did any prior Read of a package.json happen?
    for path in prior_reads:
        if path.endswith("package.json"):
            return []
    return [{
        "level": "warn",
        "rule": "npm_install_without_manifest_read",
        "message": (
            "About to run `npm install` without first reading package.json. "
            "Lifecycle scripts (postinstall, preinstall) can execute arbitrary "
            "shell on install. Consider Read-ing package.json first, OR running "
            "with --ignore-scripts to disable lifecycle hooks."
        ),
    }]
