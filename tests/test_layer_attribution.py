"""Tests for the tokenstack-style per-layer attribution helper."""
from __future__ import annotations

from agenttoolbench.layer_attribution import (
    categorize_tool,
    attribute_stream_events,
    chars_of,
    empty_layer_tokens,
    ALL_LAYERS,
)


# ---- categorize_tool ----

def test_mcp_tool_names_split_into_server_label():
    assert categorize_tool("mcp__sentry__list_issues") == ("mcp_servers", "sentry")
    assert categorize_tool("mcp__github__create_pr")    == ("mcp_servers", "github")


def test_agent_task_tools_use_subagent_type_from_input():
    assert categorize_tool("Agent", {"subagent_type": "Trend Researcher"}) == ("subagents", "Trend Researcher")
    assert categorize_tool("Task",  {"subagentType":  "general-purpose"})  == ("subagents", "general-purpose")
    assert categorize_tool("Agent")[0] == "subagents"  # missing input → unknown sub


def test_skill_tool_uses_skill_name():
    assert categorize_tool("Skill", {"skill": "brainstorming"}) == ("skills", "brainstorming")
    assert categorize_tool("Skill", {"name":  "writing-plans"}) == ("skills", "writing-plans")


def test_file_io_tools():
    for n in ("Bash", "Read", "Edit", "Write", "Glob", "Grep", "NotebookEdit"):
        assert categorize_tool(n) == ("file_io", n)


def test_web_tools():
    assert categorize_tool("WebFetch")  == ("web", "WebFetch")
    assert categorize_tool("WebSearch") == ("web", "WebSearch")


def test_unknown_tool_lands_in_other():
    assert categorize_tool("AskUserQuestion") == ("other", "AskUserQuestion")
    assert categorize_tool("SomeNovelTool")   == ("other", "SomeNovelTool")
    assert categorize_tool(None)              == ("other", "?")


# ---- chars_of ----

def test_chars_of_handles_str_dict_list():
    assert chars_of(None) == 0
    assert chars_of("hi") == 2
    assert chars_of({"type": "text", "text": "hello"}) == 5
    assert chars_of([{"type": "text", "text": "ab"}, {"type": "text", "text": "cde"}]) == 5
    # tool_result wraps content
    assert chars_of({"type": "tool_result", "content": "hello"}) == 5
    # image gets nonzero placeholder
    assert chars_of({"type": "image", "source": {}}) >= 100


# ---- attribute_stream_events ----

def _assistant_with(tool_uses):
    return {
        "type": "assistant",
        "message": {"role": "assistant", "content": tool_uses},
    }


def _user_with(tool_results):
    return {
        "type": "user",
        "message": {"role": "user", "content": tool_results},
    }


def test_attribute_counts_calls_and_result_tokens():
    events = [
        _assistant_with([
            {"type": "tool_use", "id": "tu1", "name": "Bash", "input": {"command": "ls"}},
            {"type": "tool_use", "id": "tu2", "name": "mcp__sentry__list_issues", "input": {}},
        ]),
        _user_with([
            {"type": "tool_result", "tool_use_id": "tu1", "content": "a" * 400},  # 100 tokens
            {"type": "tool_result", "tool_use_id": "tu2", "content": "b" * 800},  # 200 tokens
        ]),
    ]
    out = attribute_stream_events(events)
    assert out["file_io"]["Bash"]["calls"] == 1
    assert out["file_io"]["Bash"]["result_tokens"] == 100
    assert out["mcp_servers"]["sentry"]["calls"] == 1
    assert out["mcp_servers"]["sentry"]["result_tokens"] == 200


def test_attribute_handles_subagent_dispatches():
    events = [
        _assistant_with([
            {"type": "tool_use", "id": "tu1", "name": "Agent",
             "input": {"subagent_type": "Trend Researcher"}}
        ]),
        _user_with([
            {"type": "tool_result", "tool_use_id": "tu1", "content": [
                {"type": "text", "text": "x" * 2000}
            ]},
        ]),
    ]
    out = attribute_stream_events(events)
    assert out["subagents"]["Trend Researcher"]["calls"] == 1
    assert out["subagents"]["Trend Researcher"]["result_tokens"] == 500  # 2000/4


def test_attribute_orphan_tool_results_skipped_without_crash():
    events = [
        _user_with([
            {"type": "tool_result", "tool_use_id": "never_existed", "content": "hi"},
        ]),
    ]
    out = attribute_stream_events(events)
    # No layer should have populated entries
    assert all(len(v) == 0 for v in out.values())


def test_empty_layer_tokens_shape():
    out = empty_layer_tokens()
    assert set(out.keys()) == set(ALL_LAYERS)
    for v in out.values():
        assert v == {}


# ---- claude_code adapter populates layer_tokens ----

def test_claude_code_adapter_surfaces_layer_tokens(tmp_path):
    """End-to-end: stream-json events through ClaudeCodeAdapter → AgentRun.layer_tokens."""
    import json
    import subprocess
    from unittest.mock import patch
    from agenttoolbench.adapters.claude_code import ClaudeCodeAdapter

    events = [
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "tu1", "name": "Bash", "input": {"command": "ls"}},
        ], "usage": {"input_tokens": 100, "output_tokens": 10}}},
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "tu1", "content": "x" * 200},
        ]}},
        {"type": "result", "is_error": False, "result": "done"},
    ]
    stdout = "\n".join(json.dumps(e) for e in events)
    cp_ver = subprocess.CompletedProcess(args=[], returncode=0, stdout="Claude Code v2.1.150\n", stderr="")
    cp_run = subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")
    with patch("shutil.which", return_value="/fake/claude"), \
         patch("subprocess.run", side_effect=[cp_ver, cp_run]):
        out = ClaudeCodeAdapter().run("x", tmp_path)
    assert out.layer_tokens is not None
    assert out.layer_tokens["file_io"]["Bash"]["calls"] == 1
    assert out.layer_tokens["file_io"]["Bash"]["result_tokens"] == 50  # 200/4
