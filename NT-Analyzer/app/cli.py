"""
NT-Analyzer CLI (no extra dependencies).

Subcommands:
    nta create-job  --class SampleMACrossOver --fast 10 --slow 25 ...
    nta status      [--job <id>]
    nta open-result [--job <id>]   # default = latest

Run via:
    py -3 -m app.cli <subcommand> ...
or via the wrapper at NT-Analyzer/tools/nta.cmd.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict

from . import jobqueue


# ---------------------------------------------------------------------------

def cmd_create_job(args: argparse.Namespace) -> int:
    parameters: Dict[str, Any] = {}
    if args.fast is not None:
        parameters["Fast"] = int(args.fast)
    if args.slow is not None:
        parameters["Slow"] = int(args.slow)
    if args.params:
        for p in args.params:
            if "=" not in p:
                print(f"--param {p!r} must be Name=Value", file=sys.stderr)
                return 2
            k, v = p.split("=", 1)
            try:
                parameters[k] = int(v)
            except ValueError:
                try:
                    parameters[k] = float(v)
                except ValueError:
                    parameters[k] = v

    req = jobqueue.CreateJobRequest(
        class_name=args.class_name,
        instrument=args.instrument,
        bars_period_type=args.tf_type,
        bars_period_value=args.tf_value,
        from_utc=args.from_utc,
        to_utc=args.to_utc,
        parameters=parameters,
        calculate=args.calculate,
        is_tick_replay=args.tick_replay,
        order_fill_resolution=args.order_fill_resolution,
        slippage_ticks=args.slippage_ticks,
        commission=args.commission,
        session_template=args.session_template,
        timezone=args.timezone,
        job_id=args.job_id,
    )
    try:
        job_id, path = jobqueue.create_job(req)
    except jobqueue.JobValidationError as e:
        print(f"job validation failed: {e}", file=sys.stderr)
        return 2

    print(f"job_id: {job_id}")
    print(f"path  : {path}")
    print("If NinjaTrader+bridge is running, the AddOn should claim it within ~poll_interval_ms.")
    return 0


def _print_summary(job_id: str) -> int:
    full = jobqueue.read_job_full(job_id)
    if not full:
        print(f"job not found: {job_id}", file=sys.stderr)
        return 1
    print(f"job_id : {full['job_id']}")
    print(f"status : {full['status']}")
    print(f"path   : {full['path']}")

    if full["status"] == "done":
        res = full.get("result") or {}
        m = res.get("metrics") or {}
        print(f"finished_at_utc: {res.get('finished_at_utc')}")
        print(f"duration_ms    : {res.get('duration_ms')}")
        print("metrics:")
        for k, v in m.items():
            print(f"  {k:14s} = {v}")
        print(f"trades in result.json: {len(res.get('trades') or [])}")
        print("validated_against_strategy_analyzer: True")
    elif full["status"] == "failed":
        err = full.get("error") or {}
        print(f"error_type: {err.get('error_type')}")
        msg = err.get("message") or ""
        print("error message (first lines):")
        for line in msg.splitlines()[:15]:
            print(f"  {line}")
        rp = full.get("result_partial") or {}
        warns = (rp.get("verification_warnings") or [])[-12:]
        if warns:
            print("verification_warnings (tail):")
            for w in warns:
                print(f"  {w}")
    elif full["status"] == "running":
        hb = full.get("heartbeat") or {}
        print(f"heartbeat_at_utc: {hb.get('updated_at_utc')}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    counts = jobqueue.queue_counts()
    print("queue counts:")
    for k, v in counts.items():
        print(f"  {k:9s} = {v}")
    print()

    nt_running = jobqueue.ninjatrader_running()
    print(f"NinjaTrader running: {nt_running}")
    print()

    job_id = args.job
    if not job_id:
        latest = jobqueue.latest_job()
        if not latest:
            print("no jobs yet")
            return 0
        job_id = latest["job_id"]
        print(f"latest job overall: {job_id}")
    return _print_summary(job_id)


def cmd_open_result(args: argparse.Namespace) -> int:
    job_id = args.job
    if not job_id:
        latest = jobqueue.latest_job()
        if not latest:
            print("no jobs yet", file=sys.stderr)
            return 1
        job_id = latest["job_id"]

    full = jobqueue.read_job_full(job_id)
    if not full:
        print(f"job not found: {job_id}", file=sys.stderr)
        return 1
    if full["status"] != "done":
        print(f"job is not done (status={full['status']})", file=sys.stderr)
        return 1

    res = full.get("result") or {}
    m = res.get("metrics") or {}
    ctx = res.get("context") or {}
    print(f"=== {full['job_id']} ===")
    print(f"strategy : {(ctx.get('strategy') or {}).get('class_name')}")
    print(f"instrument: {ctx.get('instrument')}")
    print(f"timeframe : {ctx.get('timeframe')}")
    print(f"period    : {ctx.get('period')}")
    print(f"final_parameters: {(ctx.get('strategy') or {}).get('final_parameters')}")
    print(f"duration_ms     : {res.get('duration_ms')}")
    print()
    print("metrics:")
    for k in ("trade_count", "winning_pct", "gross_profit", "gross_loss",
              "net_profit", "profit_factor", "max_drawdown"):
        if k in m:
            print(f"  {k:14s} = {m[k]}")
    trades = jobqueue.read_trades(full["job_id"], offset=0, limit=3)
    print()
    print(f"trades.json total: {trades.get('total')}")
    print("first 3 trades:")
    print(json.dumps(trades.get("trades") or [], ensure_ascii=False, indent=2))
    print()
    print("NOTE: bridge baseline is manually validated against NinjaTrader Strategy Analyzer UI.")
    return 0


# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="nta", description="NT-Analyzer CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    cj = sub.add_parser("create-job", help="enqueue a backtest job into pending/")
    cj.add_argument("--class", dest="class_name", default="SampleMACrossOver")
    cj.add_argument("--instrument", default="MES 06-26")
    cj.add_argument("--tf-type", default="Minute", choices=["Minute","Day","Tick","Second","Volume"])
    cj.add_argument("--tf-value", type=int, default=1)
    cj.add_argument("--from-utc", required=True, help="YYYY-MM-DDTHH:MM:SSZ")
    cj.add_argument("--to-utc", required=True, help="YYYY-MM-DDTHH:MM:SSZ")
    cj.add_argument("--fast", type=int, default=None)
    cj.add_argument("--slow", type=int, default=None)
    cj.add_argument("--param", dest="params", action="append",
                    help="extra parameter Name=Value, repeatable")
    cj.add_argument("--calculate", default="OnBarClose")
    cj.add_argument("--tick-replay", action="store_true")
    cj.add_argument("--order-fill-resolution", default="Standard")
    cj.add_argument("--slippage-ticks", type=int, default=0)
    cj.add_argument("--commission", type=float, default=0.0)
    cj.add_argument("--session-template", default="CME US Index Futures RTH")
    cj.add_argument("--timezone", default="UTC")
    cj.add_argument("--job-id", default=None)
    cj.set_defaults(func=cmd_create_job)

    s = sub.add_parser("status", help="show queue + latest job")
    s.add_argument("--job", default=None, help="specific job_id (default: latest overall)")
    s.set_defaults(func=cmd_status)

    o = sub.add_parser("open-result", help="pretty-print the latest done result")
    o.add_argument("--job", default=None)
    o.set_defaults(func=cmd_open_result)

    return p


def main(argv: list = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
