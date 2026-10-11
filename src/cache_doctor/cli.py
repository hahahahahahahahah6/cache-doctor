"""CLI entry point for cache-doctor."""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .analyze import compute_metrics, parse_log
from .report import render_metrics, render_suggestions
from .suggest import suggest


def _cmd_analyze(args: argparse.Namespace) -> int:
    try:
        events = parse_log(args.log)
    except (OSError, ValueError) as exc:
        print(f"cache-doctor: error: {exc}", file=sys.stderr)
        return 2
    metrics = compute_metrics(events)
    if args.json:
        print(json.dumps(metrics, indent=2))
    else:
        print(render_metrics(metrics))
        print()
        print(render_suggestions(suggest(metrics)))
    if args.state:
        try:
            with open(args.state, "w", encoding="utf-8") as fh:
                json.dump(metrics, fh, indent=2)
        except OSError as exc:
            print(f"cache-doctor: warning: cannot write state: {exc}",
                  file=sys.stderr)
    return 0


def _load_metrics_for_suggest(args: argparse.Namespace) -> dict | None:
    if args.log:
        try:
            return compute_metrics(parse_log(args.log))
        except (OSError, ValueError) as exc:
            print(f"cache-doctor: error: {exc}", file=sys.stderr)
            return None
    if args.state:
        try:
            with open(args.state, encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                raise ValueError("state file must contain a JSON object")
            return data
        except (OSError, ValueError) as exc:
            print(f"cache-doctor: error: {exc}", file=sys.stderr)
            return None
    print("cache-doctor: error: suggest needs --log or --state",
          file=sys.stderr)
    return None


def _cmd_suggest(args: argparse.Namespace) -> int:
    metrics = _load_metrics_for_suggest(args)
    if metrics is None:
        return 2
    out = suggest(metrics)
    if args.json:
        print(json.dumps(out, indent=2))
    else:
        print(render_suggestions(out))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cache-doctor",
        description="Semantic-cache health diagnostics: hit rate, expiry, "
                    "and cache-pollution analysis with optimization advice.")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    sub = p.add_subparsers(dest="command", required=True)

    a = sub.add_parser("analyze", help="Analyze a cache event log (JSONL).")
    a.add_argument("log", help="Path to the JSONL cache log.")
    a.add_argument("--json", action="store_true",
                   help="Emit metrics as JSON instead of a text report.")
    a.add_argument("--state", default=None, metavar="PATH",
                   help="Also save metrics JSON to PATH for later `suggest`.")
    a.set_defaults(func=_cmd_analyze)

    s = sub.add_parser("suggest", help="Show optimization suggestions.")
    s.add_argument("--log", default=None, help="Path to the JSONL cache log.")
    s.add_argument("--state", default=None,
                   help="Path to a metrics JSON saved by `analyze --state`.")
    s.add_argument("--json", action="store_true",
                   help="Emit suggestions as JSON.")
    s.set_defaults(func=_cmd_suggest)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
