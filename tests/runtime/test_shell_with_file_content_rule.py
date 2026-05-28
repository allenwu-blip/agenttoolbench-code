"""Tests for agenttoolbench.runtime.rules.shell_with_file_content."""
from __future__ import annotations

from agenttoolbench.runtime.rules.shell_with_file_content import check


def _bash(cmd: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": cmd}}


def test_dollar_paren_cat_warns():
    out = check(_bash("echo $(cat greeting.txt)"))
    assert len(out) == 1
    assert out[0]["rule"] == "shell_with_file_content_interpolation"
    assert "cat greeting.txt" in out[0]["message"] or "$(cat" in out[0]["message"]


def test_backtick_cat_warns():
    out = check(_bash("echo `cat notes.md`"))
    assert len(out) == 1


def test_dollar_paren_redirect_warns():
    """`$(<file)` is bash's terse subshell-read; same risk class."""
    out = check(_bash("data=$(<config.json)"))
    assert len(out) == 1


def test_head_in_subshell_warns():
    out = check(_bash("echo $(head -5 log.txt)"))
    assert len(out) == 1


def test_tail_in_subshell_warns():
    out = check(_bash("echo `tail -1 log.txt`"))
    assert len(out) == 1


def test_plain_cat_no_warning():
    """`cat foo` not in a subshell — that's safe display."""
    out = check(_bash("cat README.md"))
    assert out == []


def test_unrelated_bash_no_warning():
    out = check(_bash("ls -la /tmp"))
    assert out == []


def test_echo_string_no_warning():
    out = check(_bash('echo "hello world"'))
    assert out == []


def test_non_bash_tool_no_warning():
    out = check({"tool_name": "Read", "tool_input": {"file_path": "x.txt"}})
    assert out == []


def test_no_session_ctx_works():
    """Rule has no session_ctx dependency — should work without."""
    out = check(_bash("echo $(cat foo)"))
    assert len(out) == 1


def test_defensive_empty_payload():
    assert check({}) == []
    assert check({"tool_name": "Bash"}) == []
    assert check({"tool_name": "Bash", "tool_input": {}}) == []
