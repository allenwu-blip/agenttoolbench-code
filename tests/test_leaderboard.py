"""Tests for the leaderboard render."""
from __future__ import annotations

import json
from pathlib import Path

from agenttoolbench.leaderboard import (
    compute_leaderboard,
    render_markdown,
    render_html,
    load_results,
)


def _row(agent, category, verdict, tool_calls=None, tokens=None):
    return {
        "scenario_id": f"{category.lower()}-{verdict}",
        "category": category,
        "agent": {"name": agent, "version": "0", "model": "x"},
        "verdict": verdict,
        "matched_forbidden": [],
        "matched_acknowledge": [],
        "tool_calls": tool_calls or [],
        "tokens": tokens,
        "transcript_path": None,
        "duration_ms": 0,
        "ts": "2026-05-25T00:00:00Z",
        "error": None,
    }


def test_overall_score_is_caught_minus_silent_fail():
    rows = [
        _row("claude-code", "PI-CODE", "caught"),
        _row("claude-code", "PI-TOOL", "caught"),
        _row("claude-code", "CMD-INJ", "silent_fail"),
        _row("claude-code", "DEP-MAL", "noop"),
    ]
    lb = compute_leaderboard(rows)
    assert lb["per_agent"]["claude-code"]["score"] == 1  # 2 caught - 1 silent_fail
    assert lb["per_agent"]["claude-code"]["runs"] == 4


def test_per_category_cells_count_per_verdict():
    rows = [
        _row("a1", "PI-CODE", "caught"),
        _row("a1", "PI-CODE", "silent_fail"),
        _row("a1", "PI-CODE", "noop"),
    ]
    lb = compute_leaderboard(rows)
    cell = lb["matrix"]["a1"]["PI-CODE"]
    assert cell["caught"] == 1
    assert cell["silent_fail"] == 1
    assert cell["noop"] == 1
    assert cell["score"] == 0


def test_ranking_orders_by_score_desc():
    rows = [
        _row("good", "PI-CODE", "caught"),
        _row("good", "PI-TOOL", "caught"),
        _row("bad",  "PI-CODE", "silent_fail"),
        _row("mid",  "PI-CODE", "noop"),
    ]
    lb = compute_leaderboard(rows)
    order = [a for a, _ in lb["ranking"]]
    assert order == ["good", "mid", "bad"]


def test_tool_calls_and_subagent_dispatch_counts():
    rows = [
        _row("a", "PI-CODE", "caught",
             tool_calls=[{"name": "Bash", "input": {}}, {"name": "Agent", "input": {}}]),
        _row("a", "PI-TOOL", "caught",
             tool_calls=[{"name": "Read", "input": {}}]),
        _row("b", "PI-CODE", "caught",
             tool_calls=[{"name": "Read", "input": {}}]),
    ]
    lb = compute_leaderboard(rows)
    assert lb["per_agent"]["a"]["tool_calls_total"] == 3
    assert lb["per_agent"]["a"]["subagent_dispatch_runs"] == 1
    assert lb["per_agent"]["b"]["subagent_dispatch_runs"] == 0


def test_median_total_tokens():
    rows = [
        _row("a", "PI-CODE", "caught",
             tokens={"input": 100, "output": 50, "cache_read": 0, "cache_create": 0}),
        _row("a", "PI-TOOL", "caught",
             tokens={"input": 300, "output": 100, "cache_read": 1000, "cache_create": 0}),
        _row("a", "CMD-INJ", "noop",
             tokens={"input": 50, "output": 50, "cache_read": 0, "cache_create": 0}),
    ]
    lb = compute_leaderboard(rows)
    # totals per run = 150 / 1400 / 100; median = 150
    assert lb["per_agent"]["a"]["median_total_tokens"] == 150


def test_markdown_render_includes_agents_and_categories():
    rows = [
        _row("claude-code", "PI-CODE", "caught"),
        _row("codex-cli",   "PI-CODE", "silent_fail"),
        _row("aider",       "CMD-INJ", "noop"),
    ]
    md = render_markdown(compute_leaderboard(rows))
    assert "claude-code" in md
    assert "codex-cli" in md
    assert "aider" in md
    assert "PI-CODE" in md
    assert "CMD-INJ" in md
    assert "Score" in md or "score" in md


def test_html_render_is_valid_html5_ish():
    rows = [_row("claude-code", "PI-CODE", "caught")]
    html = render_html(compute_leaderboard(rows))
    assert html.startswith("<!doctype html>")
    assert "claude-code" in html
    assert "PI-CODE" in html
    assert "<table>" in html


def test_empty_results_renders_without_crash():
    md = render_markdown(compute_leaderboard([]))
    assert "leaderboard" in md.lower()
    html = render_html(compute_leaderboard([]))
    assert html.startswith("<!doctype html>")


def test_load_results_handles_missing_file(tmp_path):
    rows = load_results(tmp_path / "does-not-exist.jsonl")
    assert rows == []


def test_load_results_skips_malformed_lines(tmp_path):
    p = tmp_path / "r.jsonl"
    p.write_text(
        '{"scenario_id":"a","agent":{"name":"x"},"verdict":"caught"}\n'
        'not json at all\n'
        '\n'
        '{"scenario_id":"b","agent":{"name":"x"},"verdict":"silent_fail"}\n'
    )
    rows = load_results(p)
    assert len(rows) == 2
