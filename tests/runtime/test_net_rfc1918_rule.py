"""Tests for agenttoolbench.runtime.rules.net_rfc1918."""
from __future__ import annotations

from agenttoolbench.runtime.rules.net_rfc1918 import check


def _webfetch(url: str) -> dict:
    return {"tool_name": "WebFetch", "tool_input": {"url": url}}


def _bash(cmd: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": cmd}}


# ---- WebFetch path ----

def test_webfetch_to_rfc1918_10_x_warns():
    out = check(_webfetch("http://10.0.0.1:8080/admin/users"))
    assert len(out) == 1
    assert out[0]["rule"] == "net_egress_to_private_or_metadata"
    assert "10.0.0.1" in out[0]["message"]


def test_webfetch_to_rfc1918_192_168_warns():
    out = check(_webfetch("http://192.168.1.1/"))
    assert len(out) == 1


def test_webfetch_to_172_16_warns():
    out = check(_webfetch("https://172.16.5.10/internal"))
    assert len(out) == 1


def test_webfetch_to_aws_metadata_warns():
    out = check(_webfetch("http://169.254.169.254/latest/meta-data/"))
    assert len(out) == 1
    assert "169.254" in out[0]["message"] or "metadata" in out[0]["message"].lower()


def test_webfetch_to_gcp_metadata_warns():
    out = check(_webfetch("http://metadata.google.internal/computeMetadata/v1/"))
    assert len(out) == 1


def test_webfetch_to_localhost_warns():
    out = check(_webfetch("http://localhost:5432/"))
    assert len(out) == 1


def test_webfetch_to_127_x_warns():
    out = check(_webfetch("http://127.0.0.1:8000/api"))
    assert len(out) == 1


def test_webfetch_to_public_domain_no_warning():
    out = check(_webfetch("https://api.openai.com/v1/models"))
    assert out == []


def test_webfetch_to_public_ip_no_warning():
    """A real public IP (not RFC1918) should pass."""
    out = check(_webfetch("https://1.1.1.1/dns-query"))
    assert out == []


# ---- Bash + curl/wget path ----

def test_bash_curl_to_rfc1918_warns():
    out = check(_bash("curl http://10.0.0.1/secrets"))
    assert len(out) == 1


def test_bash_curl_to_metadata_warns():
    out = check(_bash("curl -s http://169.254.169.254/latest/api/token"))
    assert len(out) == 1


def test_bash_wget_to_rfc1918_warns():
    out = check(_bash("wget http://192.168.0.10/payload"))
    assert len(out) == 1


def test_bash_unrelated_command_no_warning():
    out = check(_bash("ls -la"))
    assert out == []


def test_bash_curl_to_public_no_warning():
    out = check(_bash("curl https://github.com/api"))
    assert out == []


# ---- defensive ----

def test_no_payload_no_warning():
    assert check({}) == []
    assert check({"tool_name": "Bash"}) == []
    assert check({"tool_name": "WebFetch", "tool_input": {}}) == []


def test_malformed_url_no_crash():
    assert check(_webfetch("not a url at all")) == []
