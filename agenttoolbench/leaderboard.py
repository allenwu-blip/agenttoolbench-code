"""Leaderboard rendering: results.jsonl → agent × category matrix + per-agent summary.

Pure stdlib. Produces both Markdown (paste into README) and HTML (host on
GitHub Pages or anywhere static). The leaderboard is grouped per category
so a viewer can see which agents handled which attack class.

The "score" we surface for each (agent, category) cell is:
  caught - silent_fail  (per scenario in that category)
i.e. how many attack scenarios this agent caught minus how many it
silently failed on. A perfect agent: +N caught, 0 silent_fail. A
worst-case agent: 0 caught, +N silent_fail.

We also surface compute signals (median tokens per run, total tool_calls,
fraction of runs that dispatched subagents) — these are the levers the
novel BUDGET-DOS / compute-attributed-risk hypothesis tests.
"""
from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path


VERDICTS = ["caught", "silent_fail", "noop", "error"]


def load_results(path: str | Path) -> list[dict]:
    """Read a JSONL results file → list of rows."""
    rows: list[dict] = []
    p = Path(path)
    if not p.exists():
        return rows
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def compute_leaderboard(rows: list[dict]) -> dict:
    """Produce the leaderboard data structure from a flat list of result rows.

    Returns:
      {
        "agents": [...sorted agent names...],
        "categories": [...sorted categories...],
        "matrix": {agent: {category: {"caught":N, "silent_fail":N, "noop":N, "error":N, "score":int}}},
        "per_agent": {agent: {"runs":N, "caught":N, "silent_fail":N, "noop":N, "error":N,
                              "score":int, "median_total_tokens":N|None,
                              "tool_calls_total":N, "subagent_dispatch_runs":N}},
        "ranking": [(agent, score), ...] sorted desc
      }
    """
    agents: set[str] = set()
    categories: set[str] = set()
    matrix: dict[str, dict[str, dict[str, int]]] = defaultdict(lambda: defaultdict(_blank_cell))
    per_agent_runs: dict[str, list[dict]] = defaultdict(list)

    for r in rows:
        agent = (r.get("agent") or {}).get("name") or "?"
        category = r.get("category") or "?"
        verdict = r.get("verdict") or "noop"
        if verdict not in VERDICTS:
            verdict = "noop"

        agents.add(agent)
        categories.add(category)

        matrix[agent][category][verdict] += 1
        # Update cell score on the fly
        cell = matrix[agent][category]
        cell["score"] = cell["caught"] - cell["silent_fail"]

        per_agent_runs[agent].append(r)

    per_agent: dict[str, dict] = {}
    for agent, runs in per_agent_runs.items():
        verdict_counts = {v: 0 for v in VERDICTS}
        tool_calls_total = 0
        subagent_dispatch_runs = 0
        total_tokens_per_run: list[int] = []
        for r in runs:
            v = r.get("verdict") or "noop"
            if v in verdict_counts:
                verdict_counts[v] += 1
            tcs = r.get("tool_calls") or []
            # tool_calls is a list in row schema OR we may have only the
            # count by category — be defensive
            tcs_count = len(tcs) if isinstance(tcs, list) else int(tcs or 0)
            tool_calls_total += tcs_count
            if isinstance(tcs, list) and any(
                isinstance(tc, dict) and tc.get("name") in ("Agent", "Task")
                for tc in tcs
            ):
                subagent_dispatch_runs += 1
            tokens = r.get("tokens") or {}
            if isinstance(tokens, dict):
                tt = (
                    int(tokens.get("input", 0) or 0)
                    + int(tokens.get("output", 0) or 0)
                    + int(tokens.get("cache_create", 0) or 0)
                    + int(tokens.get("cache_read", 0) or 0)
                )
                if tt > 0:
                    total_tokens_per_run.append(tt)

        per_agent[agent] = {
            "runs": len(runs),
            **verdict_counts,
            "score": verdict_counts["caught"] - verdict_counts["silent_fail"],
            "median_total_tokens": (
                int(statistics.median(total_tokens_per_run))
                if total_tokens_per_run else None
            ),
            "tool_calls_total": tool_calls_total,
            "subagent_dispatch_runs": subagent_dispatch_runs,
        }

    ranking = sorted(per_agent.items(), key=lambda kv: kv[1]["score"], reverse=True)

    return {
        "agents": sorted(agents),
        "categories": sorted(categories),
        "matrix": {a: dict(matrix[a]) for a in sorted(matrix.keys())},
        "per_agent": per_agent,
        "ranking": [(a, s["score"]) for a, s in ranking],
    }


def _blank_cell() -> dict[str, int]:
    return {"caught": 0, "silent_fail": 0, "noop": 0, "error": 0, "score": 0}


# ---- rendering ----

def render_markdown(lb: dict) -> str:
    lines: list[str] = []
    lines.append("## AgentToolBench-Code leaderboard\n")
    lines.append("Score = caught − silent_fail. Higher is better.\n")

    lines.append("### Overall ranking\n")
    lines.append("| Rank | Agent | Score | Runs | Caught | Silent fail | Noop | Error | Median tokens/run | Subagent-dispatch runs |")
    lines.append("|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for i, (agent, _) in enumerate(lb["ranking"], 1):
        s = lb["per_agent"][agent]
        med = s["median_total_tokens"]
        lines.append(
            f"| {i} | `{agent}` | **{s['score']:+d}** | {s['runs']} | "
            f"{s['caught']} | {s['silent_fail']} | {s['noop']} | {s['error']} | "
            f"{med if med is not None else '—'} | {s['subagent_dispatch_runs']} |"
        )

    lines.append("\n### Per-category matrix\n")
    if not lb["categories"]:
        lines.append("_no data_")
        return "\n".join(lines) + "\n"

    header = "| Category | " + " | ".join(f"`{a}`" for a in lb["agents"]) + " |"
    sep = "|---|" + "---|" * len(lb["agents"])
    lines.append(header)
    lines.append(sep)
    for cat in lb["categories"]:
        cells: list[str] = []
        for agent in lb["agents"]:
            c = lb["matrix"].get(agent, {}).get(cat, _blank_cell())
            cells.append(
                f"{c['score']:+d} ({c['caught']}c / {c['silent_fail']}f / {c['noop']}n / {c['error']}e)"
            )
        lines.append(f"| **{cat}** | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def render_html(lb: dict) -> str:
    """Standalone, no-dependency HTML page. Hostable on GitHub Pages as is."""
    def esc(s):
        return (str(s)
                .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    parts: list[str] = []
    parts.append("<!doctype html><meta charset=utf-8>")
    parts.append("<title>AgentToolBench-Code Leaderboard</title>")
    parts.append("""<style>
      body { font: 15px/1.5 system-ui, sans-serif; max-width: 1100px; margin: 2em auto; padding: 0 1em; color: #222; }
      h1, h2 { font-weight: 600; }
      table { border-collapse: collapse; margin: 1em 0; }
      th, td { padding: 0.4em 0.7em; border: 1px solid #ddd; text-align: right; }
      th { background: #fafafa; }
      th:first-child, td:first-child { text-align: left; }
      code { background: #f4f4f4; padding: 0.1em 0.3em; border-radius: 3px; font-size: 0.95em; }
      .pos { color: #16803d; font-weight: 600; }
      .neg { color: #c0392b; font-weight: 600; }
      .zero { color: #888; }
      .subtle { color: #666; font-size: 0.92em; }
    </style>""")
    parts.append("<h1>AgentToolBench-Code Leaderboard</h1>")
    parts.append("<p class=subtle>Score = caught − silent_fail. Higher is better.</p>")

    parts.append("<h2>Overall ranking</h2>")
    parts.append("<table><thead><tr>")
    for h in ("Rank","Agent","Score","Runs","Caught","Silent fail","Noop","Error","Median tokens/run","Subagent dispatches"):
        parts.append(f"<th>{esc(h)}</th>")
    parts.append("</tr></thead><tbody>")
    for i, (agent, _) in enumerate(lb["ranking"], 1):
        s = lb["per_agent"][agent]
        score = s["score"]
        cls = "pos" if score > 0 else ("neg" if score < 0 else "zero")
        med = s["median_total_tokens"]
        parts.append(
            f"<tr><td>{i}</td><td><code>{esc(agent)}</code></td>"
            f"<td class={cls}>{score:+d}</td>"
            f"<td>{s['runs']}</td>"
            f"<td>{s['caught']}</td><td>{s['silent_fail']}</td>"
            f"<td>{s['noop']}</td><td>{s['error']}</td>"
            f"<td>{med if med is not None else '—'}</td>"
            f"<td>{s['subagent_dispatch_runs']}</td></tr>"
        )
    parts.append("</tbody></table>")

    if lb["categories"]:
        parts.append("<h2>Per-category matrix</h2>")
        parts.append("<table><thead><tr><th>Category</th>")
        for a in lb["agents"]:
            parts.append(f"<th><code>{esc(a)}</code></th>")
        parts.append("</tr></thead><tbody>")
        for cat in lb["categories"]:
            parts.append(f"<tr><td><strong>{esc(cat)}</strong></td>")
            for agent in lb["agents"]:
                c = lb["matrix"].get(agent, {}).get(cat, _blank_cell())
                score = c["score"]
                cls = "pos" if score > 0 else ("neg" if score < 0 else "zero")
                parts.append(
                    f"<td class={cls}>{score:+d}"
                    f"<span class=subtle> ({c['caught']}c/{c['silent_fail']}f/{c['noop']}n/{c['error']}e)</span></td>"
                )
            parts.append("</tr>")
        parts.append("</tbody></table>")

    parts.append('<p class=subtle>Cells: <code>score (caught / silent_fail / noop / error)</code>.</p>')
    return "".join(parts)
