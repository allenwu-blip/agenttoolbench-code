---
description: agenttoolbench-guard — runtime security defender for Claude Code. Use when the user asks "what's the guard catching", "show me the agenttoolbench warnings", "/guard", or wants to understand the warnings printed before tool_use calls. The defender is warn-only — it surfaces patterns the agenttoolbench benchmark identifies as silent-fail risks (npm install without manifest read; RFC1918 webhooks; recursive subagent fan-out; etc.), but never blocks the user's tool_use.
---

# /agenttoolbench:guard — runtime defender warnings

You are being invoked because the user wants to inspect or explain the
warnings agenttoolbench-guard has surfaced during this session.

## What the guard does

A PreToolUse hook (`hooks/pre-tool-use.sh`) runs before every Claude
Code tool_use. It invokes the Python module
`agenttoolbench.runtime.guard`, which runs every enabled rule against
the payload + session context. Each rule returns 0 or more warnings.
The hook prints the warnings to stderr (where the user sees them as a
banner above the tool_use) and exits 0.

**The guard never blocks.** Warn-only by design — Allen ratified
this on 2026-05-28 ("工作流是最重要的"). The user keeps full agency;
the guard only surfaces patterns it thinks are risky.

## Enabled rules (v0.0.1)

| Rule | Fires when | Benchmark scenario |
| :--- | :--- | :--- |
| `npm_install_without_manifest_read` | `Bash` running `npm install` or `npm i` with no prior `Read` of `package.json`; `--ignore-scripts` flag absent | `dep-mal-npm_postinstall_curl_sh` |
| `pip_install_without_manifest_read` | `Bash` running `pip install` (or `pip3` / `python -m pip`) with no prior `Read` of any Python manifest (`requirements.txt` / `pyproject.toml` / `setup.py` / etc.) | `dep-mal-pypi_typosquat_requirements` + `dep-mal-pypi_alternative_index_url` |
| `net_egress_to_private_or_metadata` | `WebFetch` or `Bash` `curl`/`wget` targeting RFC1918 / loopback / cloud-metadata host (10.x, 172.16-31.x, 192.168.x, 127.x, 169.254.x, `localhost`, `metadata.google.internal`, `metadata.azure.com`) | `net-egress-webhook_to_internal_admin` + `net-egress-webhook_to_metadata_endpoint` + `net-egress-dns_rebinding_subdomain` |
| `shell_with_file_content_interpolation` | `Bash` command contains `$(cat …)`, `\`cat …\``, `$(<file)`, `$(head/tail …)` — subshell-reads that re-interpret file content as shell | `cmd-inj-echo_class_cve_2025_54795` |
| `subagent_burst` | `Agent` or `Task` tool_use with 2+ prior subagent dispatches in the session (warns from the 3rd onward) | `budget-dos-recursive_subagent_explosion` |

Each rule traces to a v0.0.2 benchmark scenario where the attack
silent-failed against at least one agent configuration.

## How to invoke (when user asks)

The guard runs automatically via the PreToolUse hook. There's nothing
the user needs to do for the warnings to appear.

If the user is asking *why* a particular warning fired, point them at:
- The rule name (printed in the banner)
- The matching scenario in `~/portfolio-foundry/products/agenttoolbench-code/scenarios/`
- The README in `~/portfolio-foundry/products/agenttoolbench-code/` for the
  full taxonomy

If the user wants to silence the guard for the rest of the session,
they can either:
- Disable the plugin in `~/.claude/config`
- Or use `--ignore-scripts` (or equivalent safe flag) so the rule
  doesn't fire in the first place

Don't suggest disabling unless the user explicitly asks — the
warnings are there for a reason.

## What NOT to do

- Do NOT claim the guard "blocked" anything — it doesn't block.
- Do NOT claim 100% protection — the guard catches what its rules
  catch. The benchmark v0.0.2 documents at least 8 attack classes;
  v0.0.1 of the guard covers 1 (the npm_install case). The rest are
  stubbed and surface no warnings yet.
- Don't fabricate rules — only the rules above exist.
