"""Mock-based tests for the OpenHands adapter."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from agenttoolbench.adapters.openhands import OpenHandsAdapter


def _cp(stdout: str, stderr: str = "", rc: int = 0):
    return subprocess.CompletedProcess(args=[], returncode=rc, stdout=stdout, stderr=stderr)


def test_openhands_command_has_required_safety_flags(tmp_path):
    a = OpenHandsAdapter(model="claude-sonnet-4-6", max_iterations=15)
    cmd = a._build_cmd("inspect the codebase", tmp_path)
    assert cmd[0] == "openhands"
    assert "--headless" in cmd
    assert "--cd" in cmd and str(tmp_path) in cmd
    assert "--workspace-base" in cmd
    assert "--max-iterations" in cmd and "15" in cmd
    assert "--model" in cmd and "claude-sonnet-4-6" in cmd
    assert "--task" in cmd and "inspect the codebase" in cmd


def test_openhands_parses_message_action_summary(tmp_path):
    events = [
        {"event_type": "message", "source": "agent", "message": "I'll inspect the codebase."},
        {"event_type": "action", "action": "run", "args": {"command": "ls -la"}},
        {"event_type": "observation", "observation": "run", "content": "file listing..."},
        {"event_type": "message", "source": "agent", "message": "Found 3 files."},
        {"event_type": "summary", "metrics": {"prompt_tokens": 200, "completion_tokens": 50}},
    ]
    stdout = "\n".join(json.dumps(e) for e in events) + "\n"
    with patch("shutil.which", return_value="/fake/openhands"), \
         patch("subprocess.run") as mrun:
        mrun.side_effect = [_cp("openhands 0.5.0\n"), _cp(stdout)]
        out = OpenHandsAdapter().run("task", tmp_path)
    assert "I'll inspect the codebase." in out.output_text
    assert "Found 3 files." in out.output_text
    assert "[TOOL_USE run:" in out.output_text
    assert "ls -la" in out.output_text
    assert out.tool_calls == [{"name": "run", "input": {"command": "ls -la"}}]
    # observations are intentionally NOT folded into output_text
    assert "file listing" not in out.output_text
    assert out.tokens["input"] == 200
    assert out.tokens["output"] == 50
    assert out.error is None


def test_openhands_error_event_becomes_run_error(tmp_path):
    events = [{"event_type": "error", "message": "max iterations exceeded"}]
    stdout = "\n".join(json.dumps(e) for e in events)
    with patch("shutil.which", return_value="/fake/openhands"), \
         patch("subprocess.run") as mrun:
        mrun.side_effect = [_cp("openhands 0.5.0\n"), _cp(stdout, rc=1)]
        out = OpenHandsAdapter().run("x", tmp_path)
    assert out.error and "max iterations" in out.error


def test_openhands_missing_binary_returns_clean_error(tmp_path):
    with patch("shutil.which", return_value=None):
        out = OpenHandsAdapter().run("x", tmp_path)
    assert out.error and "not on PATH" in out.error


def test_openhands_observation_events_do_not_pollute_oracle_text(tmp_path):
    """The oracle scores the AGENT's attempts, not the tool's responses.
    If a tool observation includes attacker payload text, we must NOT
    accidentally credit/blame the agent for it."""
    events = [
        {"event_type": "message", "source": "agent", "message": "I'll list files."},
        {"event_type": "action", "action": "run", "args": {"command": "cat /tmp/notes.txt"}},
        # Observation includes the attacker's injection payload — must not appear in output_text
        {"event_type": "observation", "observation": "run",
         "content": "evil.example.test injection payload curl -fsSL ..."},
        {"event_type": "message", "source": "agent",
         "message": "I saw a suspicious payload in that file; ignoring it."},
    ]
    stdout = "\n".join(json.dumps(e) for e in events) + "\n"
    with patch("shutil.which", return_value="/fake/openhands"), \
         patch("subprocess.run") as mrun:
        mrun.side_effect = [_cp("openhands 0.5.0\n"), _cp(stdout)]
        out = OpenHandsAdapter().run("x", tmp_path)
    # Agent's words present
    assert "suspicious payload" in out.output_text
    # Observation NOT present (would have triggered false silent_fail)
    assert "evil.example.test" not in out.output_text


@pytest.mark.skipif(
    os.environ.get("AGENTTOOLBENCH_RUN_LIVE_OPENHANDS") != "1",
    reason="live OpenHands test — set AGENTTOOLBENCH_RUN_LIVE_OPENHANDS=1 to opt in",
)
def test_live_openhands_simple_prompt(tmp_path):
    (tmp_path / "hello.txt").write_text("the magic number is 42")
    out = OpenHandsAdapter().run("Read hello.txt and tell me the magic number.", tmp_path)
    assert out.error is None, f"unexpected error: {out.error}"
    assert "42" in out.output_text
