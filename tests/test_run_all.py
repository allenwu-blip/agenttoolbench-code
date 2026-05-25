"""Tests for the run-all CLI: discovers all scenarios and runs one adapter against them."""
from __future__ import annotations

import json
from pathlib import Path

from agenttoolbench.cli import _discover_scenarios, main as cli_main


REPO = Path(__file__).resolve().parents[1]


def test_discover_finds_all_seeded_scenarios():
    """v0.0.1 ships ≥8 scenarios — one per category at minimum."""
    found = _discover_scenarios(str(REPO / "scenarios"))
    ids = [p.parent.name for p in found]
    # one per category
    expected = {
        "notes_injection_smoke",              # PI-TOOL
        "web_fetch_response_injection",       # PI-TOOL (variant)
        "echo_class_cve_2025_54795",          # CMD-INJ
        "claude_md_hostile_directive",        # PI-CODE
        "cursor_rules_hostile",               # PI-CODE (variant)
        "env_file_secret_in_readme",          # CRED-LEAK
        "npm_postinstall_curl_sh",            # DEP-MAL
        "config_writes_to_traversal_path",    # FS-ESCAPE
        "webhook_to_metadata_endpoint",       # NET-EGRESS
        "recursive_subagent_explosion",       # BUDGET-DOS
    }
    assert expected.issubset(set(ids)), \
        f"missing scenarios: {expected - set(ids)}"
    assert len(found) >= 10


def test_all_8_categories_have_at_least_one_scenario():
    """Verify the corpus covers all 8 scoring axes."""
    from agenttoolbench.schema import load_scenario, VALID_CATEGORIES
    found = _discover_scenarios(str(REPO / "scenarios"))
    seen_categories: set[str] = set()
    for p in found:
        try:
            sc = load_scenario(p)
            seen_categories.add(sc.category)
        except Exception:
            continue
    missing = VALID_CATEGORIES - seen_categories
    assert not missing, f"categories without any scenario: {sorted(missing)}"


def test_run_all_with_safe_stub_writes_jsonl(tmp_path, capsys):
    """run-all on the safe stub should write one JSONL row per scenario."""
    out = tmp_path / "results.jsonl"
    rc = cli_main([
        "run-all",
        "--adapter", "stub:safe",
        "--scenarios-dir", str(REPO / "scenarios"),
        "--results", str(out),
    ])
    assert rc == 0
    lines = out.read_text().strip().splitlines()
    assert len(lines) >= 4
    for line in lines:
        row = json.loads(line)
        assert "scenario_id" in row
        assert "verdict" in row


def test_run_all_filter_narrows_to_matching(tmp_path):
    """--filter restricts to scenarios whose id contains the substring."""
    out = tmp_path / "results.jsonl"
    rc = cli_main([
        "run-all",
        "--adapter", "stub:safe",
        "--scenarios-dir", str(REPO / "scenarios"),
        "--results", str(out),
        "--filter", "pi-tool",
    ])
    assert rc == 0
    lines = out.read_text().strip().splitlines()
    # all pi-tool scenarios (we have 2: smoke + web_fetch_response_injection)
    assert len(lines) >= 2
    for line in lines:
        assert "pi-tool" in json.loads(line)["scenario_id"]


def test_list_scenarios_prints_them(capsys):
    rc = cli_main(["list-scenarios", "--scenarios-dir", str(REPO / "scenarios")])
    assert rc == 0
    out = capsys.readouterr().out
    assert "PI-TOOL" in out
    assert "CMD-INJ" in out
    assert "PI-CODE" in out
    assert "CRED-LEAK" in out
