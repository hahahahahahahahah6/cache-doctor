"""Human-readable report rendering for cache-doctor."""

from __future__ import annotations

_BAR_WIDTH = 30


def _bar(frac: float) -> str:
    filled = int(round(max(0.0, min(1.0, frac)) * _BAR_WIDTH))
    return "#" * filled + "-" * (_BAR_WIDTH - filled)


def _pct(frac: float | None) -> str:
    return f"{frac * 100:6.1f}%" if frac is not None else "     n/a"


def render_metrics(m: dict) -> str:
    lines = [
        "cache-doctor  health report",
        "=" * 44,
        f"events analyzed : {m['total']:>10}",
        f"cache hits      : {m['hits']:>10}   {_pct(m['hit_rate'])}  [{_bar(m['hit_rate'])}]",
        f"cache misses    : {m['misses']:>10}",
        f"similarity thr. : {m['threshold']:>10}",
        "",
        "miss reasons:",
    ]
    for reason, count in sorted(m.get("miss_reasons", {}).items()):
        share = count / m["misses"] if m["misses"] else 0.0
        lines.append(f"  {reason:<15} {count:>6}  {_pct(share)}")
    lines += [
        "",
        "pollution signals:",
        f"  borderline hits : {m['borderline_hits']:>6}  ({_pct(m['borderline_share'])} of hits)",
        f"  wrong hits      : {m['wrong_hits']:>6}   <- flag_wrong=true",
        f"  near misses     : {m['near_misses']:>6}  ({_pct(m['near_miss_share'])} of misses)",
        "",
        "policy signals:",
        f"  expired misses  : {m['expired_misses']:>6}  ({_pct(m['expired_miss_share'])} of misses)",
        f"  stale hits      : {m['stale_hits']:>6}  ({_pct(m['stale_share'])} of hits)",
        f"  frag. groups    : {m['frag_groups']:>6}  ({m['frag_requests']} requests)",
        "",
        "similarity stats:",
        f"  avg hit sim     : {m['avg_sim_hit'] if m['avg_sim_hit'] is not None else 'n/a':>10}",
        f"  p10 hit sim     : {m['p10_sim_hit'] if m['p10_sim_hit'] is not None else 'n/a':>10}",
        f"  avg miss sim    : {m['avg_sim_miss'] if m['avg_sim_miss'] is not None else 'n/a':>10}",
    ]
    rolling = m.get("rolling_hourly") or {}
    if rolling:
        lines += ["", "rolling hourly hit rate:"]
        for hour, rate in rolling.items():
            lines.append(f"  {hour}  {_pct(rate)}  [{_bar(rate)}]")
    return "\n".join(lines)


_SEV_MARK = {"critical": "!!", "high": "**", "medium": "*", "low": "-", "info": "ok"}


def render_suggestions(suggestions: list[dict]) -> str:
    lines = ["optimization suggestions", "=" * 44]
    for i, s in enumerate(suggestions, 1):
        mark = _SEV_MARK.get(s["severity"], "?")
        lines += [
            f"{i}. [{mark}] {s['severity'].upper():8} {s['title']}",
            f"   {s['detail']}",
            f"   -> {s['action']}",
            "",
        ]
    return "\n".join(lines).rstrip()
