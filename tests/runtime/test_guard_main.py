"""Tests for agenttoolbench.runtime.guard orchestration:

  - collect_prior_reads(transcript_path) scans for Read tool_uses
  - run_rules(payload, prior_reads) dispatches to every enabled rule
  - format_warnings produces a stderr banner
  - main() reads stdin → runs rules → prints to stderr → exits 0 (always)
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

from agenttoolbench.runtime.guard import (
    collect_prior_reads,
    run_rules,
    format_warnings,
    main,
)


# ---------- collect_prior_reads ----------

def test_collect_prior_reads_returns_empty_when_no_transcript():
    assert collect_prior_reads(None) == []
    assert collect_prior_reads("") == []
    assert collect_prior_reads("/nonexistent/path.jsonl") == []


def test_collect_prior_reads_extracts_read_tool_uses(tmp_path: Path):
    transcript = tmp_path / "session.jsonl"
    transcript.write_text("\n".join([
        # Assistant message with a Read tool_use
        json.dumps({"type": "assistant", "message": {"content": [
            {"type": "text", "text": "Let me look at package.json"},
            {"type": "tool_use", "name": "Read",
             "input": {"file_path": "/repo/package.json"}},
        ]}}),
        # Another with a Bash (not Read)
        json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Bash",
             "input": {"command": "ls"}},
        ]}}),
        # Another Read
        json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Read",
             "input": {"file_path": "/repo/src/app.js"}},
        ]}}),
    ]))
    reads = collect_prior_reads(str(transcript))
    assert reads == ["/repo/package.json", "/repo/src/app.js"]


def test_collect_prior_reads_handles_malformed_lines(tmp_path: Path):
    """Malformed JSON lines are skipped — don't crash."""
    transcript = tmp_path / "broken.jsonl"
    transcript.write_text("\n".join([
        "not json at all",
        json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Read",
             "input": {"file_path": "/a.txt"}},
        ]}}),
        "",  # blank line
        "{ also malformed",
    ]))
    assert collect_prior_reads(str(transcript)) == ["/a.txt"]


def test_collect_prior_reads_ignores_non_assistant_records(tmp_path: Path):
    """User messages, system records etc. don't contain tool_uses."""
    transcript = tmp_path / "mixed.jsonl"
    transcript.write_text("\n".join([
        json.dumps({"type": "user", "message": {"content": "hello"}}),
        json.dumps({"type": "system", "data": {}}),
        json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Read",
             "input": {"file_path": "/relevant.txt"}},
        ]}}),
    ]))
    assert collect_prior_reads(str(transcript)) == ["/relevant.txt"]


# ---------- run_rules ----------

def test_run_rules_dispatches_to_npm_install_rule():
    payload = {"tool_name": "Bash", "tool_input": {"command": "npm install"}}
    warnings = run_rules(payload, prior_reads=[])
    assert len(warnings) == 1
    assert warnings[0]["rule"] == "npm_install_without_manifest_read"


def test_run_rules_returns_empty_when_no_rule_fires():
    payload = {"tool_name": "Read", "tool_input": {"file_path": "x.txt"}}
    assert run_rules(payload, prior_reads=[]) == []


def test_run_rules_swallows_rule_exceptions():
    """A buggy rule must not break the whole guard."""
    from agenttoolbench.runtime import guard as guard_mod

    class _BrokenRule:
        @staticmethod
        def check(payload, *, prior_reads):
            raise RuntimeError("rule blew up")

    with patch.object(guard_mod, "_RULES", [_BrokenRule]):
        # Doesn't raise. Returns no warnings (because the rule blew up).
        assert run_rules({"tool_name": "Bash"}, prior_reads=[]) == []


# ---------- format_warnings ----------

def test_format_warnings_renders_banner():
    warnings = [{
        "level": "warn",
        "rule": "npm_install_without_manifest_read",
        "message": "About to run npm install without reading package.json.",
    }]
    out = format_warnings(warnings)
    assert "agenttoolbench-guard" in out
    assert "⚠" in out
    assert "WARN" in out
    assert "npm_install_without_manifest_read" in out
    assert "package.json" in out


def test_format_warnings_empty_returns_empty_string():
    assert format_warnings([]) == ""


# ---------- main (end-to-end via stdin) ----------

def test_main_with_npm_install_payload_prints_warning_to_stderr(capfd, tmp_path):
    """Full flow: stdin → parse → run rules → stderr."""
    transcript = tmp_path / "session.jsonl"
    transcript.write_text("")  # empty (no prior reads)

    payload_json = json.dumps({
        "tool_name": "Bash",
        "tool_input": {"command": "npm install"},
        "transcript_path": str(transcript),
    })

    with patch("sys.stdin", io.StringIO(payload_json)):
        rc = main()
    assert rc == 0, "guard must always exit 0 in warn-only mode"
    captured = capfd.readouterr()
    assert "agenttoolbench-guard" in captured.err
    assert "npm install" in captured.err.lower() or "package.json" in captured.err.lower()


def test_main_with_safe_payload_prints_nothing_exits_zero(capfd):
    """Read tool_use → no rule fires → no banner → exit 0."""
    payload_json = json.dumps({
        "tool_name": "Read",
        "tool_input": {"file_path": "x.txt"},
    })
    with patch("sys.stdin", io.StringIO(payload_json)):
        rc = main()
    assert rc == 0
    captured = capfd.readouterr()
    assert captured.err == ""


def test_main_with_malformed_payload_exits_zero_silent(capfd):
    """Bad input → exit 0 silently. Hook MUST NOT crash Claude Code's flow."""
    with patch("sys.stdin", io.StringIO("not json at all")):
        rc = main()
    assert rc == 0


def test_main_with_empty_stdin_exits_zero_silent(capfd):
    """Empty stdin → exit 0 silently."""
    with patch("sys.stdin", io.StringIO("")):
        rc = main()
    assert rc == 0
    assert capfd.readouterr().err == ""


def test_main_npm_install_with_prior_manifest_read_no_warning(capfd, tmp_path):
    """Happy path: agent already read package.json, npm install proceeds
    without nagging."""
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(json.dumps({
        "type": "assistant",
        "message": {"content": [
            {"type": "tool_use", "name": "Read",
             "input": {"file_path": "/repo/package.json"}},
        ]},
    }))
    payload_json = json.dumps({
        "tool_name": "Bash",
        "tool_input": {"command": "npm install"},
        "transcript_path": str(transcript),
    })
    with patch("sys.stdin", io.StringIO(payload_json)):
        rc = main()
    assert rc == 0
    captured = capfd.readouterr()
    # Banner does NOT appear because the rule didn't fire.
    assert captured.err == ""
