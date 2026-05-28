"""TDD: agenttoolbench/runtime/rules/npm_install.py

Rule: if the pending tool_use is `Bash` running `npm install` (without
the `--ignore-scripts` safety flag), AND no prior Read of package.json
has occurred in this session, emit a warning.

Lifecycle scripts in package.json can execute arbitrary shell on
install (postinstall: curl ... | sh). The defence the benchmark
shows works (aider, codex 0.134) is "read the manifest first, then
decide." This rule replicates that defence as a Claude Code hook.

UX mode: warn-only per Allen's 2026-05-28 ratify
("工作流是最重要的"). Rules NEVER block — they return Warning objects
that the hook prints to stderr and then exits 0.
"""
from __future__ import annotations

from agenttoolbench.runtime.rules.npm_install import check


def _tool_use(cmd: str, name: str = "Bash") -> dict:
    """Synthesise a PreToolUse payload that Claude Code would send."""
    return {
        "tool_name": name,
        "tool_input": {"command": cmd},
    }


def test_npm_install_without_prior_manifest_read_warns():
    payload = _tool_use("npm install")
    prior_reads: list[str] = []  # nothing read yet
    warnings = check(payload, session_ctx={"prior_reads": prior_reads})
    assert len(warnings) == 1
    w = warnings[0]
    assert w["level"] == "warn"
    assert w["rule"] == "npm_install_without_manifest_read"
    assert "package.json" in w["message"].lower()


def test_npm_install_with_prior_manifest_read_no_warning():
    """User-facing happy path: agent already inspected package.json,
    npm install can proceed without nagging."""
    payload = _tool_use("npm install")
    prior_reads = ["/some/repo/package.json"]
    assert check(payload, session_ctx={"prior_reads": prior_reads}) == []


def test_npm_install_with_ignore_scripts_flag_no_warning():
    """The safety flag --ignore-scripts disables lifecycle scripts,
    which is the actual attack vector. If user explicitly used that
    flag, no warning needed."""
    payload = _tool_use("npm install --ignore-scripts")
    assert check(payload, session_ctx={"prior_reads": []}) == []


def test_non_npm_install_bash_no_warning():
    """Don't fire on unrelated Bash commands."""
    payload = _tool_use("ls -la")
    assert check(payload, session_ctx={"prior_reads": []}) == []
    payload2 = _tool_use("git status")
    assert check(payload2, session_ctx={"prior_reads": []}) == []


def test_non_bash_tool_no_warning():
    """Rule only applies to Bash tool_use."""
    payload = {"tool_name": "Read", "tool_input": {"file_path": "x.txt"}}
    assert check(payload, session_ctx={"prior_reads": []}) == []


def test_npm_i_short_form_also_caught():
    """`npm i` is the shorthand alias for `npm install` — same risk."""
    payload = _tool_use("npm i")
    assert len(check(payload, session_ctx={"prior_reads": []})) == 1


def test_npm_init_not_npm_install_no_warning():
    """Make sure the alias regex doesn't accidentally catch `npm init`
    or `npm info` or `npm install-test` etc. — only `install` and `i`."""
    for cmd in ("npm init", "npm info react", "npm init -y"):
        payload = _tool_use(cmd)
        assert check(payload, session_ctx={"prior_reads": []}) == [], f"false positive on {cmd!r}"


def test_npm_install_with_package_no_warning_when_manifest_read():
    """`npm install <pkg>` doesn't modify package.json by default but
    still runs install scripts. Treat it like plain install if no
    manifest was read."""
    payload = _tool_use("npm install some-package")
    assert len(check(payload, session_ctx={"prior_reads": []})) == 1


def test_warning_carries_remediation_hint():
    """The user should see WHAT to do, not just the warning."""
    payload = _tool_use("npm install")
    [w] = check(payload, session_ctx={"prior_reads": []})
    assert "--ignore-scripts" in w["message"] or "ignore-scripts" in w["message"]


def test_check_handles_missing_command_field_gracefully():
    """Defensive: malformed payload doesn't crash the rule."""
    payload = {"tool_name": "Bash", "tool_input": {}}
    assert check(payload, session_ctx={"prior_reads": []}) == []


def test_check_handles_none_payload_gracefully():
    """Defensive: None / empty payload returns no warnings."""
    assert check({}, session_ctx={"prior_reads": []}) == []
    assert check({"tool_name": "Bash"}, session_ctx={"prior_reads": []}) == []
