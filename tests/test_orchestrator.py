"""End-to-end loop-closure tests.

These prove Week-1-Day-1 done: schema loads, sandbox spins, stub adapter runs,
oracle scores, results JSONL writes — all chained.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agenttoolbench.orchestrator import run_scenario
from agenttoolbench.adapters.stub import StubAdapter


REPO = Path(__file__).resolve().parents[1]
SMOKE = REPO / "scenarios" / "pi-tool" / "notes_injection_smoke" / "scenario.yaml"


def test_smoke_safe_agent_is_caught(tmp_path):
    """A 'safe' agent that acknowledges the injection → verdict 'caught'."""
    out = tmp_path / "results.jsonl"
    row = run_scenario(SMOKE, StubAdapter("safe"), results_path=out)
    assert row["verdict"] == "caught"
    assert row["matched_forbidden"] == []
    assert any(p in row["matched_acknowledge"] for p in ("prompt injection", "ignore", "suspicious"))


def test_smoke_unsafe_agent_silent_fails(tmp_path):
    """An 'unsafe' agent that executes the injection → verdict 'silent_fail'."""
    out = tmp_path / "results.jsonl"
    row = run_scenario(SMOKE, StubAdapter("unsafe"), results_path=out)
    assert row["verdict"] == "silent_fail"
    assert any("curl" in p or "whoami" in p or "rm -rf" in p for p in row["matched_forbidden"])


def test_smoke_noop_agent(tmp_path):
    out = tmp_path / "results.jsonl"
    row = run_scenario(SMOKE, StubAdapter("noop"), results_path=out)
    assert row["verdict"] == "noop"


def test_smoke_error_agent(tmp_path):
    out = tmp_path / "results.jsonl"
    row = run_scenario(SMOKE, StubAdapter("error"), results_path=out)
    assert row["verdict"] == "error"


def test_jsonl_written(tmp_path):
    """Two runs against same results.jsonl → two rows, valid JSON each."""
    out = tmp_path / "results.jsonl"
    run_scenario(SMOKE, StubAdapter("safe"), results_path=out)
    run_scenario(SMOKE, StubAdapter("unsafe"), results_path=out)
    lines = out.read_text().strip().splitlines()
    assert len(lines) == 2
    for line in lines:
        json.loads(line)  # raises if malformed
