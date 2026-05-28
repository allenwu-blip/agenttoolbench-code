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


def check(payload: dict, *, session_ctx: dict | None = None) -> list[dict]:
    """Return a list of warning dicts (0 or 1 element for this rule).

    Args:
      payload:     PreToolUse hook payload (tool_name + tool_input).
      session_ctx: dict of session context. Keys this rule reads:
                     "prior_reads": list[str] — file paths Read this session.
                   Missing or empty keys are treated as "no prior context".

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
    prior_reads = (session_ctx or {}).get("prior_reads") or []
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
