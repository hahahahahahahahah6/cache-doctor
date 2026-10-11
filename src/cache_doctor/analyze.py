"""Parse semantic-cache event logs and compute health metrics.

Log format: JSONL, one event per line. Fields (all except ``prompt``
optional)::

    {
      "ts": "2026-10-11T01:00:00Z",   # ISO-8601 timestamp
      "prompt": "What is the capital of France?",
      "cache_key": "9f3a...",
      "hit": true,                    # served from cache?
      "similarity": 0.93,             # similarity score of the hit, if any
      "threshold": 0.90,              # configured similarity threshold
      "ttl_seconds": 3600,
      "cache_age_seconds": 1200,      # age of the entry served (hits only)
      "miss_reason": "no_key",        # "no_key" | "expired" | "low_similarity"
      "flag_wrong": false             # ground truth: the hit was a false positive
    }

Everything is stdlib-only.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

MISS_REASONS = ("no_key", "expired", "low_similarity")
BORDERLINE_MARGIN = 0.05  # hits within +margin of threshold are "borderline"
STALE_FRACTION = 0.9      # hits served past 90% of TTL are "stale"

_WS_RE = re.compile(r"\s+")


def norm_prompt(prompt: str) -> str:
    """Canonical prompt form used for key-fragmentation detection."""
    return _WS_RE.sub(" ", (prompt or "").strip()).casefold()


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_log(path: str) -> list[dict]:
    """Read a JSONL cache log. Raises ValueError on malformed lines."""
    events: list[dict] = []
    with open(path, "r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"line {lineno}: invalid JSON ({exc.msg})") from exc
            if not isinstance(obj, dict):
                raise ValueError(f"line {lineno}: expected a JSON object")
            events.append(obj)
    return events


def _bucket_hour(ts: datetime | None) -> str:
    return ts.strftime("%Y-%m-%dT%H:00") if ts else "unknown"


def compute_metrics(events: list[dict]) -> dict:
    """Compute the full health-metrics dict for a list of cache events."""
    total = len(events)
    hits = [e for e in events if e.get("hit")]
    misses = [e for e in events if not e.get("hit")]
    hit_count = len(hits)
    miss_count = len(misses)

    miss_reasons: Counter = Counter()
    for e in misses:
        reason = e.get("miss_reason") or "no_key"
        miss_reasons[reason if reason in MISS_REASONS else "no_key"] += 1

    thresholds = [e["threshold"] for e in events
                  if isinstance(e.get("threshold"), (int, float))]
    threshold = (sorted(thresholds)[len(thresholds) // 2]
                 if thresholds else 0.9)

    hit_sims = [e["similarity"] for e in hits
                if isinstance(e.get("similarity"), (int, float))]
    miss_sims = [e["similarity"] for e in misses
                 if isinstance(e.get("similarity"), (int, float))]

    # Borderline hits: barely above the threshold -> false-positive risk.
    borderline_hits = [e for e in hits
                       if isinstance(e.get("similarity"), (int, float))
                       and e["similarity"] < threshold + BORDERLINE_MARGIN]

    # Ground-truth confirmed pollution: paraphrase served the wrong response.
    wrong_hits = [e for e in hits if e.get("flag_wrong")]

    # Key fragmentation: the same normalized prompt stored under many keys.
    by_prompt: dict[str, set] = defaultdict(set)
    for e in events:
        p = e.get("prompt")
        k = e.get("cache_key")
        if p and k:
            by_prompt[norm_prompt(p)].add(str(k))
    frag_groups = {p: sorted(keys) for p, keys in by_prompt.items()
                   if len(keys) > 1}
    frag_requests = sum(1 for e in events
                        if e.get("prompt") and e.get("cache_key")
                        and norm_prompt(e["prompt"]) in frag_groups)

    # Stale serving: hits from entries that were nearly expired.
    stale_hits = [e for e in hits
                  if isinstance(e.get("cache_age_seconds"), (int, float))
                  and isinstance(e.get("ttl_seconds"), (int, float))
                  and e["ttl_seconds"] > 0
                  and e["cache_age_seconds"] >= STALE_FRACTION * e["ttl_seconds"]]

    # Rolling hit rate per hour (chronological).
    buckets: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for e in events:
        b = _bucket_hour(_parse_ts(e.get("ts")))
        buckets[b][0] += 1
        buckets[b][1] += 1 if e.get("hit") else 0
    rolling = {b: round(h / t, 4) for b, (t, h) in sorted(buckets.items())}

    # Near misses: misses whose best similarity almost reached the threshold.
    near_misses = [e for e in misses
                   if isinstance(e.get("similarity"), (int, float))
                   and threshold - 0.05 <= e["similarity"] < threshold]

    expired_misses = miss_reasons.get("expired", 0)

    def _pctl(values: list[float], q: float) -> float | None:
        if not values:
            return None
        s = sorted(values)
        return round(s[min(len(s) - 1, int(q * len(s)))], 4)

    return {
        "total": total,
        "hits": hit_count,
        "misses": miss_count,
        "hit_rate": round(hit_count / total, 4) if total else 0.0,
        "miss_reasons": dict(miss_reasons),
        "expired_misses": expired_misses,
        "expired_miss_share": round(expired_misses / miss_count, 4) if miss_count else 0.0,
        "threshold": round(threshold, 4),
        "borderline_hits": len(borderline_hits),
        "borderline_share": round(len(borderline_hits) / hit_count, 4) if hit_count else 0.0,
        "wrong_hits": len(wrong_hits),
        "near_misses": len(near_misses),
        "near_miss_share": round(len(near_misses) / miss_count, 4) if miss_count else 0.0,
        "frag_groups": len(frag_groups),
        "frag_requests": frag_requests,
        "frag_share": round(frag_requests / total, 4) if total else 0.0,
        "stale_hits": len(stale_hits),
        "stale_share": round(len(stale_hits) / hit_count, 4) if hit_count else 0.0,
        "avg_sim_hit": round(sum(hit_sims) / len(hit_sims), 4) if hit_sims else None,
        "p10_sim_hit": _pctl(hit_sims, 0.10),
        "avg_sim_miss": round(sum(miss_sims) / len(miss_sims), 4) if miss_sims else None,
        "rolling_hourly": rolling,
        "events_analyzed": total,
    }
