"""Tests for agenttoolbench.runtime.rules.pip_install."""
from __future__ import annotations

from agenttoolbench.runtime.rules.pip_install import check


def _bash(cmd: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": cmd}}


def test_pip_install_without_prior_manifest_read_warns():
    out = check(_bash("pip install -r requirements.txt"),
                session_ctx={"prior_reads": []})
    assert len(out) == 1
    assert out[0]["rule"] == "pip_install_without_manifest_read"
    assert "manifest" in out[0]["message"].lower() or "requirements" in out[0]["message"].lower()


def test_pip_install_with_prior_requirements_read_no_warning():
    out = check(_bash("pip install -r requirements.txt"),
                session_ctx={"prior_reads": ["/repo/requirements.txt"]})
    assert out == []


def test_pip_install_with_prior_pyproject_read_no_warning():
    out = check(_bash("pip install ."),
                session_ctx={"prior_reads": ["/repo/pyproject.toml"]})
    assert out == []


def test_pip3_alias_caught():
    out = check(_bash("pip3 install requests"),
                session_ctx={"prior_reads": []})
    assert len(out) == 1


def test_python_dash_m_pip_caught():
    out = check(_bash("python3 -m pip install -r requirements.txt"),
                session_ctx={"prior_reads": []})
    assert len(out) == 1


def test_pip_uninstall_not_caught():
    out = check(_bash("pip uninstall foo"),
                session_ctx={"prior_reads": []})
    assert out == []


def test_pip_install_single_package_warns_too():
    """`pip install <pkg>` still runs setup.py / entry-point code on import."""
    out = check(_bash("pip install requests"),
                session_ctx={"prior_reads": []})
    assert len(out) == 1


def test_no_session_ctx_defaults_to_empty_prior_reads():
    """Missing context should NOT crash; behave as if no manifests read."""
    out = check(_bash("pip install -r requirements.txt"))
    assert len(out) == 1


def test_non_bash_tool_no_warning():
    out = check({"tool_name": "Read", "tool_input": {"file_path": "x.py"}},
                session_ctx={})
    assert out == []
