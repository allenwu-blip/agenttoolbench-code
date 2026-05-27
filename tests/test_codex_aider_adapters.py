"""Mock-based tests for Codex CLI and Aider adapters.

Verifies command construction, output parsing, and clean error paths
WITHOUT spending API credits. Live-API smoke tests are opt-in via env
vars (AGENTTOOLBENCH_RUN_LIVE_CODEX / AGENTTOOLBENCH_RUN_LIVE_AIDER).
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from agenttoolbench.adapters.codex_cli import CodexCliAdapter
from agenttoolbench.adapters.aider import AiderAdapter


def _cp(stdout: str, stderr: str = "", rc: int = 0):
    return subprocess.CompletedProcess(args=[], returncode=rc, stdout=stdout, stderr=stderr)


# =========== Codex CLI =================================================

def test_codex_command_has_required_safety_flags(tmp_path):
    a = CodexCliAdapter(model="gpt-5-codex", approval_mode="auto")
    cmd = a._build_cmd("do the thing", tmp_path)
    assert cmd[0] == "codex" and cmd[1] == "exec"
    assert "--cd" in cmd and str(tmp_path) in cmd
    assert "--json" in cmd
    assert "--approval-mode" in cmd and "auto" in cmd
    assert "--model" in cmd and "gpt-5-codex" in cmd
    assert "do the thing" in cmd
    # Never auto-enable dangerous modes
    assert "--dangerously-skip-permissions" not in cmd
    assert "--full-auto" not in cmd  # codex's "yolo" equivalent


def test_codex_parses_text_tool_call_completed(tmp_path):
    events = [
        {"type": "message", "role": "assistant",
         "content": [{"type": "text", "text": "I'll list the files."}]},
        {"type": "tool_call", "name": "shell",
         "arguments": {"command": ["bash", "-lc", "ls"]}},
        {"type": "message", "role": "assistant",
         "content": [{"type": "text", "text": "Found 3 files."}]},
        {"type": "completed", "usage": {"input_tokens": 200, "output_tokens": 30}},
    ]
    stdout = "\n".join(json.dumps(e) for e in events) + "\n"
    with patch("shutil.which", return_value="/fake/codex"), \
         patch("subprocess.run") as mrun:
        mrun.side_effect = [_cp("codex 0.5.0\n"), _cp(stdout)]
        out = CodexCliAdapter().run("hi", tmp_path)
    assert "I'll list the files." in out.output_text
    assert "Found 3 files." in out.output_text
    assert "[TOOL_USE shell:" in out.output_text
    assert any("ls" in str(v) for v in out.output_text.split("\n"))
    assert out.tool_calls == [{"name": "shell", "input": {"command": ["bash", "-lc", "ls"]}}]
    assert out.tokens["input"] == 200
    assert out.tokens["output"] == 30
    assert out.error is None


def test_codex_error_event_becomes_run_error(tmp_path):
    events = [{"type": "error", "message": "rate limited"}]
    stdout = "\n".join(json.dumps(e) for e in events)
    with patch("shutil.which", return_value="/fake/codex"), \
         patch("subprocess.run") as mrun:
        mrun.side_effect = [_cp("codex 0.5.0\n"), _cp(stdout, rc=1)]
        out = CodexCliAdapter().run("x", tmp_path)
    assert out.error and "rate limited" in out.error


def test_codex_missing_binary_returns_clean_error(tmp_path):
    with patch("shutil.which", return_value=None):
        out = CodexCliAdapter().run("x", tmp_path)
    assert out.error and "not on PATH" in out.error


# =========== Aider =====================================================

def test_aider_command_has_required_safety_flags(tmp_path):
    # Seed two files so the adapter has positional file args to enumerate.
    # Aider in --no-git mode rejects directory positionals, so the adapter
    # passes individual files instead (one of which exercises a dotfile to
    # confirm aider sees attack-vector files like .env / .cursorrules).
    (tmp_path / "main.py").write_text("print('hi')\n")
    (tmp_path / ".env").write_text("KEY=x\n")

    a = AiderAdapter(model="claude-sonnet-4-6")
    cmd = a._build_cmd("refactor calc.py", tmp_path)
    assert cmd[0] == "aider"
    assert "--message" in cmd and "refactor calc.py" in cmd
    assert "--yes-always" in cmd
    assert "--no-stream" in cmd
    assert "--no-pretty" in cmd
    assert "--no-auto-commits" in cmd
    assert "--no-git" in cmd
    assert "--no-suggest-shell-commands" in cmd
    assert "--model" in cmd and "claude-sonnet-4-6" in cmd
    # Positionals are files relative to working_dir, NOT the dir itself
    # (aider --no-git rejects directory positionals).
    assert str(tmp_path) not in cmd
    assert "main.py" in cmd
    assert ".env" in cmd


def test_aider_captures_stdout_and_recognises_running_lines(tmp_path):
    stdout = (
        "I'll inspect the file.\n"
        "Running: cat calc.py\n"
        "def c(l): ...\n"
        "Refactored. Done.\n"
    )
    with patch("shutil.which", return_value="/fake/aider"), \
         patch("subprocess.run") as mrun:
        mrun.side_effect = [_cp("aider 0.85.0\n"), _cp(stdout)]
        out = AiderAdapter().run("refactor", tmp_path)
    assert "I'll inspect the file." in out.output_text
    assert "Refactored. Done." in out.output_text
    assert out.tool_calls == [{"name": "shell", "input": {"command": "cat calc.py"}}]
    assert out.error is None


def test_aider_run_shell_command_prefix_also_recognised(tmp_path):
    stdout = "Run shell command: npm install\nok\n"
    with patch("shutil.which", return_value="/fake/aider"), \
         patch("subprocess.run") as mrun:
        mrun.side_effect = [_cp("aider 0.85.0\n"), _cp(stdout)]
        out = AiderAdapter().run("x", tmp_path)
    assert out.tool_calls == [{"name": "shell", "input": {"command": "npm install"}}]


def test_aider_missing_binary_returns_clean_error(tmp_path):
    with patch("shutil.which", return_value=None):
        out = AiderAdapter().run("x", tmp_path)
    assert out.error and "not on PATH" in out.error


def test_aider_nonzero_rc_with_empty_stdout_is_error(tmp_path):
    with patch("shutil.which", return_value="/fake/aider"), \
         patch("subprocess.run") as mrun:
        mrun.side_effect = [_cp("aider 0.85.0\n"), _cp("", stderr="api key missing", rc=2)]
        out = AiderAdapter().run("x", tmp_path)
    assert out.error and "api key missing" in out.error


# =========== Opt-in live ===============================================

@pytest.mark.skipif(
    os.environ.get("AGENTTOOLBENCH_RUN_LIVE_CODEX") != "1",
    reason="live Codex test — set AGENTTOOLBENCH_RUN_LIVE_CODEX=1 to opt in",
)
def test_live_codex_simple_prompt(tmp_path):
    (tmp_path / "hello.txt").write_text("the magic number is 42")
    out = CodexCliAdapter().run("Read hello.txt and tell me the magic number.", tmp_path)
    assert out.error is None, f"unexpected error: {out.error}"
    assert "42" in out.output_text


@pytest.mark.skipif(
    os.environ.get("AGENTTOOLBENCH_RUN_LIVE_AIDER") != "1",
    reason="live Aider test — set AGENTTOOLBENCH_RUN_LIVE_AIDER=1 to opt in",
)
def test_live_aider_simple_prompt(tmp_path):
    (tmp_path / "hello.txt").write_text("the magic number is 42")
    out = AiderAdapter().run("Read hello.txt and tell me the magic number.", tmp_path)
    assert out.error is None, f"unexpected error: {out.error}"
    assert "42" in out.output_text
