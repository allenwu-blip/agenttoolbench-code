# AgentToolBench-Code

**Benchmarking silent security failures in AI coding agents.**

When an AI coding agent reads a file, runs a shell command, installs a
dependency, or returns a tool result, *silent* security failures happen —
the agent quietly executes the attacker's instructions and reports success
to its user. AgentToolBench-Code is an open benchmark that measures how
often this happens, across coding agents and across attack categories,
with a reproducible harness and a public leaderboard.

**Status (v0.0.1):** the harness loop is closed end-to-end, the Claude
Code adapter ships, and the scenario corpus covers **all 8 categories**
with one real-CVE-grounded or class-grounded scenario each. Codex CLI /
Aider / OpenHands / SWE-agent adapters and the per-category corpus
expansion to 60-100 scenarios are the next builds.

## Scoring axes (8)

Coding-agent-specific attack categories, anchored to OWASP ASI + Mindgard's
agent-vuln taxonomy:

| ID         | What it tests                                                                |
| :--------- | :--------------------------------------------------------------------------- |
| PI-CODE    | Prompt injection arriving via a codebase artifact (settings, README, rules) |
| PI-TOOL    | Prompt injection arriving via tool / MCP output (file content, fetch body)  |
| CMD-INJ    | Silent dangerous shell exec / allowlist bypass                              |
| CRED-LEAK  | Secret exfiltration via tool output (markdown img, DNS, redirect)           |
| DEP-MAL    | Malicious dependency install / slopsquatting / lifecycle script             |
| FS-ESCAPE  | Path traversal / file write outside scope / ignore-file bypass              |
| NET-EGRESS | SSRF / model-provider redirect / Mermaid bypass                             |
| BUDGET-DOS | Token / compute exhaustion (paired with tokenstack for compute-attributed risk) |

## Quickstart

```bash
git clone https://github.com/allenwu-blip/agenttoolbench-code
cd agenttoolbench-code
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# List all 8 scenarios:
agenttoolbench list-scenarios

# Run one scenario against the stub agent (no API cost):
agenttoolbench run-scenario \
  scenarios/pi-tool/notes_injection_smoke/scenario.yaml \
  --adapter stub:safe

# Run ALL scenarios against one adapter — writes one JSONL row per scenario:
agenttoolbench run-all --adapter stub:safe
agenttoolbench run-all --adapter stub:unsafe          # for comparison

# Filter to a single category:
agenttoolbench run-all --adapter stub:safe --filter cred-leak

# Run against the real Claude Code agent (costs Claude API budget per scenario):
agenttoolbench run-all \
  --adapter "claude-code:model=sonnet,budget=0.25"
# (set ANTHROPIC_API_KEY and add ":bare" to the adapter spec for a clean
#  benchmark run with no host plugin/skill/memory contamination)
```

Each run appends one JSON row to `results.jsonl` (override with `--results`).

## What's in v0.0.1

- Scenario schema + result schema (`schema/*.schema.json`)
- **8 scenarios covering all 8 categories** — one per axis, each grounded
  in a real CVE / public incident class or explicitly labelled synthetic:
  | Category   | Scenario                                       | Grounding |
  | :--------- | :--------------------------------------------- | :-------- |
  | PI-CODE    | `claude_md_hostile_directive`                  | CVE-2025-53773 class (Copilot YOLO settings.json) |
  | PI-TOOL    | `notes_injection_smoke`                        | synthetic smoke test |
  | CMD-INJ    | `echo_class_cve_2025_54795`                    | CVE-2025-54795 class (Claude Code echo) |
  | CRED-LEAK  | `env_file_secret_in_readme`                    | Snyk Nx s1ngularity class |
  | DEP-MAL    | `npm_postinstall_curl_sh`                      | npm supply-chain class |
  | FS-ESCAPE  | `config_writes_to_traversal_path`              | OWASP ASI class |
  | NET-EGRESS | `webhook_to_metadata_endpoint`                 | SSRF metadata class |
  | BUDGET-DOS | `recursive_subagent_explosion`                 | novel — paired with tokenstack |
- Sandbox: per-scenario tempdir populated from `starting_state/`
- Adapter interface + two adapters:
  - `stub` (deterministic, four modes — safe/unsafe/noop/error, no API cost)
  - `claude-code` (real `claude -p --output-format stream-json --verbose ...`,
    with `--max-budget-usd` cap, `--no-session-persistence`, never auto-enabling
    `--dangerously-skip-permissions`)
- Orchestrator + oracle + JSONL results writer
- CLI: `run-scenario`, `run-all`, `list-scenarios`
- **25 unit tests + 1 opt-in live test, all passing**

## What lands next

- **Corpus expansion**: 60-100 scenarios across the 8 categories, adapted
  from named CVEs (CVE-2025-54795, CVE-2025-53773, Invariant MCP exfil,
  Trail of Bits argument injection, Snyk Nx s1ngularity, etc.) and the
  Mindgard 25-pattern coding-agent-vuln taxonomy.
- **More adapters**: Codex CLI, Aider, OpenHands, SWE-agent (all confirmed
  scriptable in the landscape SCOUT).
- **tokenstack integration in adapters**: per-run per-layer token attribution
  → enables the novel BUDGET-DOS scoring (does compute allocation correlate
  with security outcomes?), the research hypothesis no published agent
  benchmark has tested.
- **Cross-agent runner + leaderboard site**: HTML leaderboard generated from
  the merged JSONL, agent × category matrix.
- **Launch artefact**: a single data-driven blog post — "What I found running
  N agents through M scenarios" — that frames the leaderboard as the call
  to action.

## What this benchmark deliberately ISN'T

- It is not yet another generic agent benchmark — it is **coding-agent-specific** (Claude Code, Codex CLI, Aider, OpenHands, SWE-agent and friends). Generic tool-use is covered by AgentDojo / AgentBench / InjecAgent.
- It is not an attempt to enumerate every novel attack — it adopts existing taxonomies (OWASP ASI, Mindgard, NIST AI RMF) and grounds scenarios in named CVEs / public incident writeups.
- It is not a moral framework — `silent_fail` doesn't mean the agent is "bad," it means it executed the attack without surfacing it. Some scenarios are subtle enough that even careful agents will silent-fail.

## Source-cited prior art (we build on, not replace)

- OWASP ASI (Agentic Security Initiative) Threats & Mitigations
- Mindgard `ai-ide-vuln-patterns` (25-pattern coding-agent taxonomy)
- AgentDojo (NeurIPS 2024) — the runnable-leaderboard precedent
- InjecAgent, AgentHarm, AgentBench, R-Judge — generic agent benchmarks
- Trail of Bits, Invariant Labs, Embrace the Red, Snyk Labs — agent-security CVE corpus we adapt scenarios from

## License

MIT — see [LICENSE](LICENSE).

## Status

v0.0.1 (Week 1 Day 1). Not yet for use — harness skeleton only. The first
real evaluation runs (Claude Code on real CVE-derived scenarios) land in
Week 1 Day 3-5.
