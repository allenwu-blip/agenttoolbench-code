"""CLI entry: agenttoolbench run-scenario <scenario.yaml> --adapter stub:safe"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path  # noqa: F401  (used by `leaderboard --out`)

from .orchestrator import run_scenario
from .adapters.stub import StubAdapter
from .adapters.claude_code import ClaudeCodeAdapter
from .adapters.codex_cli import CodexCliAdapter
from .adapters.aider import AiderAdapter
from .adapters.openhands import OpenHandsAdapter
from .adapters.swe_agent import SweAgentAdapter


def _parse_opts(opt_str: str) -> dict:
    """Parse a comma-separated 'k=v,flag' option string into a dict.

    Examples:
      ""                       -> {}
      "bare"                   -> {"bare": True}
      "model=opus"             -> {"model": "opus"}
      "bare,model=opus,budget=0.10" -> {"bare": True, "model": "opus", "budget": "0.10"}
    """
    if not opt_str:
        return {}
    out: dict = {}
    for chunk in opt_str.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "=" in chunk:
            k, v = chunk.split("=", 1)
            out[k.strip()] = v.strip()
        else:
            out[chunk] = True
    return out


def _make_adapter(spec: str):
    """Resolve a --adapter=NAME[:OPT] spec into an Adapter instance.

    Supported:
      stub[:safe|unsafe|noop|error]
      claude-code[:bare,model=NAME,budget=USD,permission=MODE]
    """
    if ":" in spec:
        name, opt_str = spec.split(":", 1)
    else:
        name, opt_str = spec, ""

    if name == "stub":
        # stub's "option" is just the mode string
        return StubAdapter(mode=opt_str or "safe")

    if name == "claude-code":
        opts = _parse_opts(opt_str)
        kwargs: dict = {}
        if opts.get("bare"):
            kwargs["bare"] = True
        if "model" in opts:
            model = opts["model"]
            kwargs["model"] = {
                "sonnet": "claude-sonnet-4-6",
                "opus": "claude-opus-4-7",
                "haiku": "claude-haiku-4-5-20251001",
            }.get(model, model)
        if "budget" in opts:
            kwargs["max_budget_usd"] = float(opts["budget"])
        if "permission" in opts:
            kwargs["permission_mode"] = opts["permission"]
        return ClaudeCodeAdapter(**kwargs)

    if name == "codex-cli":
        opts = _parse_opts(opt_str)
        kwargs = {}
        if "model" in opts:
            kwargs["model"] = opts["model"]
        if "approval" in opts:
            kwargs["approval_mode"] = opts["approval"]
        return CodexCliAdapter(**kwargs)

    if name == "aider":
        opts = _parse_opts(opt_str)
        kwargs = {}
        if "model" in opts:
            kwargs["model"] = opts["model"]
        return AiderAdapter(**kwargs)

    if name == "openhands":
        opts = _parse_opts(opt_str)
        kwargs = {}
        if "model" in opts:
            kwargs["model"] = opts["model"]
        if "iterations" in opts:
            kwargs["max_iterations"] = int(opts["iterations"])
        return OpenHandsAdapter(**kwargs)

    if name == "swe-agent":
        opts = _parse_opts(opt_str)
        kwargs = {}
        if "model" in opts:
            kwargs["model"] = opts["model"]
        if "max_input" in opts:
            kwargs["max_input_tokens"] = int(opts["max_input"])
        return SweAgentAdapter(**kwargs)

    raise SystemExit(
        f"adapter '{name}' not implemented yet. Supported: stub, claude-code, "
        f"codex-cli, aider, openhands, swe-agent."
    )


def _discover_scenarios(root: str | None) -> list[Path]:
    """Walk a scenarios root and return every scenario.yaml found."""
    base = Path(root) if root else Path(__file__).resolve().parents[1] / "scenarios"
    return sorted(base.rglob("scenario.yaml"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="agenttoolbench")
    sub = ap.add_subparsers(dest="cmd", required=True)

    rs = sub.add_parser("run-scenario", help="Run one adapter against one scenario.")
    rs.add_argument("scenario", help="Path to scenario.yaml")
    rs.add_argument("--adapter", required=True, help="e.g. stub:safe / stub:unsafe / stub:noop / stub:error")
    rs.add_argument("--results", default="results.jsonl", help="Output JSONL path")

    ra = sub.add_parser("run-all", help="Run one adapter against EVERY scenario under --scenarios-dir.")
    ra.add_argument("--adapter", required=True, help="Adapter spec (same as run-scenario --adapter).")
    ra.add_argument("--scenarios-dir", default=None,
                    help="Root scenarios/ dir to walk (default: ../scenarios relative to package).")
    ra.add_argument("--results", default="results.jsonl", help="Output JSONL path")
    ra.add_argument("--filter", default=None,
                    help="Only run scenarios whose id contains this substring (e.g. 'pi-tool', 'cve').")
    ra.add_argument("--runs", type=int, default=1,
                    help="How many INDEPENDENT runs per (agent, scenario). Default 1 = "
                         "current single-run behaviour. Use >=3 to surface verdict variance "
                         "(captured as stability metric in leaderboard).")

    ls = sub.add_parser("list-scenarios", help="List all discovered scenarios.")
    ls.add_argument("--scenarios-dir", default=None)

    lb = sub.add_parser("leaderboard", help="Render results.jsonl as a leaderboard (Markdown / HTML).")
    lb.add_argument("results", help="Path to a results.jsonl file.")
    lb.add_argument("--format", choices=["markdown", "md", "html"], default="markdown")
    lb.add_argument("--out", default=None, help="Write output to a file (default: stdout).")

    args = ap.parse_args(argv)

    if args.cmd == "run-scenario":
        adapter = _make_adapter(args.adapter)
        row = run_scenario(args.scenario, adapter, results_path=args.results)
        print(json.dumps(row, indent=2))
        return 0

    if args.cmd == "run-all":
        adapter = _make_adapter(args.adapter)
        scenarios = _discover_scenarios(args.scenarios_dir)
        summary = {"caught": 0, "silent_fail": 0, "noop": 0, "error": 0, "total": 0}
        from .schema import load_scenario as _load
        total_runs = max(1, int(args.runs or 1))
        for sc_path in scenarios:
            try:
                sc = _load(sc_path)
            except Exception as e:
                print(f"SKIP {sc_path}: {e}", file=sys.stderr)
                continue
            if args.filter and args.filter not in sc.id:
                continue
            # For N>1, emit a verdict line per run + a per-scenario aggregate.
            scenario_verdicts: list[str] = []
            for run_idx in range(total_runs):
                row = run_scenario(
                    sc, adapter,
                    results_path=args.results,
                    run_index=run_idx,
                    total_runs=total_runs,
                )
                summary[row["verdict"]] = summary.get(row["verdict"], 0) + 1
                summary["total"] += 1
                scenario_verdicts.append(row["verdict"])
                if total_runs > 1:
                    print(f"  {sc.id:50s} run {run_idx+1}/{total_runs} -> {row['verdict']}")
            if total_runs == 1:
                print(f"  {sc.id:50s} -> {scenario_verdicts[0]}")
        print()
        print(f"summary: total={summary['total']}  caught={summary['caught']}  "
              f"silent_fail={summary['silent_fail']}  noop={summary['noop']}  error={summary['error']}")
        if total_runs > 1:
            print(f"(--runs={total_runs}: total={summary['total']} = scenarios × {total_runs} runs;"
                  f" use `agenttoolbench leaderboard` for per-scenario aggregated view)")
        return 0

    if args.cmd == "list-scenarios":
        from .schema import load_scenario as _load
        for sc_path in _discover_scenarios(args.scenarios_dir):
            try:
                sc = _load(sc_path)
                print(f"  {sc.category:10s} {sc.id:50s} {sc_path}")
            except Exception as e:
                print(f"  ?          (load failed: {e})  {sc_path}")
        return 0

    if args.cmd == "leaderboard":
        from .leaderboard import load_results, compute_leaderboard, render_markdown, render_html
        rows = load_results(args.results)
        if not rows:
            print(f"warning: no rows loaded from {args.results}", file=sys.stderr)
        data = compute_leaderboard(rows)
        if args.format == "html":
            rendered = render_html(data)
        else:
            rendered = render_markdown(data)
        if args.out:
            Path(args.out).write_text(rendered)
            print(f"wrote {args.out} ({len(rendered)} chars)")
        else:
            print(rendered)
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
