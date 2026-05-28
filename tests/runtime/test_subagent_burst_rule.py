"""Tests for agenttoolbench.runtime.rules.subagent_burst."""
from __future__ import annotations

from agenttoolbench.runtime.rules.subagent_burst import check


def _agent_dispatch(name: str = "Agent") -> dict:
    return {
        "tool_name": name,
        "tool_input": {"description": "summarise something",
                       "prompt": "..."},
    }


def test_first_subagent_no_warning():
    """1st dispatch (count = 1 after) is safe."""
    out = check(_agent_dispatch(),
                session_ctx={"prior_subagent_count": 0})
    assert out == []


def test_second_subagent_no_warning():
    """2nd dispatch is still under threshold (3)."""
    out = check(_agent_dispatch(),
                session_ctx={"prior_subagent_count": 1})
    assert out == []


def test_third_subagent_warns():
    """3rd dispatch hits the burst threshold."""
    out = check(_agent_dispatch(),
                session_ctx={"prior_subagent_count": 2})
    assert len(out) == 1
    assert out[0]["rule"] == "subagent_burst"
    assert "3th subagent" in out[0]["message"] or "third" in out[0]["message"].lower()


def test_many_subagents_warns():
    out = check(_agent_dispatch(),
                session_ctx={"prior_subagent_count": 8})
    assert len(out) == 1


def test_task_tool_alias_also_warns():
    """Some adapters surface subagents as 'Task' instead of 'Agent'."""
    out = check(_agent_dispatch(name="Task"),
                session_ctx={"prior_subagent_count": 5})
    assert len(out) == 1


def test_non_subagent_tool_no_warning():
    """Bash / Read / WebFetch shouldn't trigger even at high counts."""
    out = check({"tool_name": "Bash", "tool_input": {"command": "ls"}},
                session_ctx={"prior_subagent_count": 10})
    assert out == []


def test_no_session_ctx_no_warning():
    """Missing context → treat as 0 prior dispatches → first dispatch ok."""
    out = check(_agent_dispatch())
    assert out == []


def test_defensive_empty_payload():
    assert check({}, session_ctx={"prior_subagent_count": 5}) == []
