"""Mock-based tests for the SWE-agent adapter."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from agenttoolbench.adapters.swe_agent import SweAgentAdapter


def _cp(stdout: str = "", stderr: str = "", rc: int = 0):
    return subprocess.CompletedProcess(args=[], returncode=rc, stdout=stdout, stderr=stderr)


def _write_traj(out_dir: Path, traj: dict, name: str = "test.traj.json") -> Path:
    p = out_dir / name
    p.write_text(json.dumps(traj))
    return p


def test_swe_agent_command_has_required_flags(tmp_path):
    a = SweAgentAdapter(model="claude-sonnet-4-6", max_input_tokens=80000)
    out_dir = tmp_path / "out"
    cmd = a._build_cmd("fix the bug", tmp_path, out_dir)
    assert cmd[0] == "sweagent" and cmd[1] == "run"
    assert "--agent.model.name" in cmd and "claude-sonnet-4-6" in cmd
    assert "--agent.model.max_input_tokens" in cmd and "80000" in cmd
    assert "--env.repo.path" in cmd and str(tmp_path) in cmd
    assert "--problem_statement.text" in cmd and "fix the bug" in cmd
    assert "--output_dir" in cmd


def test_swe_agent_parses_trajectory_file(tmp_path):
    """Trajectory file = source of truth (sweagent writes everything there)."""
    # Build a fake out_dir with a trajectory file
    instance_dir = tmp_path / "out" / "test-instance"
    instance_dir.mkdir(parents=True)
    traj = {
        "trajectory": [
            {"role": "assistant", "content": "I'll inspect the repo."},
            {"role": "assistant", "content": "Running ls.",
             "action": "shell", "action_args": {"command": "ls"}},
            {"role": "assistant", "content": "Editing file.",
             "action": "edit", "action_args": {"path": "main.py", "diff": "..."}},
        ],
        "info": {"model_stats": {"tokens_sent": 1200, "tokens_received": 300}},
    }
    _write_traj(instance_dir, traj)

    # Mock the version subprocess + the actual run subprocess (which writes
    # the trajectory; we already wrote it for the test)
    a = SweAgentAdapter()
    with patch("shutil.which", return_value="/fake/sweagent"), \
         patch("subprocess.run") as mrun, \
         patch("tempfile.TemporaryDirectory") as mtmp:
        # Pin the temp dir to our pre-populated out_dir
        mtmp.return_value.__enter__ = lambda self: str(tmp_path / "out")
        mtmp.return_value.__exit__ = lambda *args: False
        mrun.side_effect = [_cp("sweagent 0.7.0\n"), _cp("")]
        out = a.run("inspect", tmp_path)

    assert "I'll inspect the repo." in out.output_text
    assert "Editing file." in out.output_text
    assert "[TOOL_USE shell:" in out.output_text
    assert "[TOOL_USE edit:" in out.output_text
    # Tool calls captured
    assert any(tc["name"] == "shell" for tc in out.tool_calls)
    assert any(tc["name"] == "edit" for tc in out.tool_calls)
    # Tokens captured
    assert out.tokens["input"] == 1200
    assert out.tokens["output"] == 300
    # Trajectory path recorded (forensic)
    assert out.transcript_path is not None and out.transcript_path.endswith(".traj.json")


def test_swe_agent_handles_missing_trajectory_gracefully(tmp_path):
    """If sweagent crashes without writing a trajectory, fall back to stdout/stderr."""
    # Construct adapter INSIDE the patch block so __init__'s version capture
    # consumes the first mock; the actual run consumes the second.
    with patch("shutil.which", return_value="/fake/sweagent"), \
         patch("subprocess.run") as mrun, \
         patch("tempfile.TemporaryDirectory") as mtmp:
        mtmp.return_value.__enter__ = lambda self: str(tmp_path / "empty-out")
        mtmp.return_value.__exit__ = lambda *args: False
        (tmp_path / "empty-out").mkdir()
        mrun.side_effect = [_cp("sweagent 0.7.0\n"), _cp("", stderr="docker missing", rc=1)]
        a = SweAgentAdapter()
        out = a.run("x", tmp_path)
    assert out.error and "docker missing" in out.error


def test_swe_agent_missing_binary_returns_clean_error(tmp_path):
    with patch("shutil.which", return_value=None):
        out = SweAgentAdapter().run("x", tmp_path)
    assert out.error and "not on PATH" in out.error


def test_swe_agent_malformed_trajectory_is_clean_error(tmp_path):
    instance_dir = tmp_path / "out2" / "broken"
    instance_dir.mkdir(parents=True)
    (instance_dir / "x.traj.json").write_text("not json at all{")
    a = SweAgentAdapter()
    with patch("shutil.which", return_value="/fake/sweagent"), \
         patch("subprocess.run") as mrun, \
         patch("tempfile.TemporaryDirectory") as mtmp:
        mtmp.return_value.__enter__ = lambda self: str(tmp_path / "out2")
        mtmp.return_value.__exit__ = lambda *args: False
        mrun.side_effect = [_cp("sweagent 0.7.0\n"), _cp("")]
        out = a.run("x", tmp_path)
    assert out.error and "could not parse trajectory" in out.error


@pytest.mark.skipif(
    os.environ.get("AGENTTOOLBENCH_RUN_LIVE_SWE_AGENT") != "1",
    reason="live SWE-agent test — set AGENTTOOLBENCH_RUN_LIVE_SWE_AGENT=1 to opt in (requires Docker + sweagent + model auth)",
)
def test_live_swe_agent_simple(tmp_path):
    """Smoke-test against real sweagent. Costs Docker startup + LLM API."""
    (tmp_path / "hello.txt").write_text("the magic number is 42")
    out = SweAgentAdapter().run("Read hello.txt and tell me the magic number.", tmp_path)
    # Don't strictly assert success — sweagent has many setup-sensitive failure modes;
    # we mostly want to know the adapter didn't blow up on a real binary.
    assert out.agent_name == "swe-agent"
