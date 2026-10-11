"""Rule-based optimization suggestions from cache health metrics."""

from __future__ import annotations

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def _mk(severity: str, code: str, title: str, detail: str, action: str) -> dict:
    return {"severity": severity, "code": code, "title": title,
            "detail": detail, "action": action}


def suggest(metrics: dict) -> list[dict]:
    """Return prioritized suggestions, most severe first."""
    out: list[dict] = []
    total = metrics.get("total", 0) or 0
    hits = metrics.get("hits", 0) or 0
    misses = metrics.get("misses", 0) or 0
    hit_rate = metrics.get("hit_rate", 0.0) or 0.0
    threshold = metrics.get("threshold", 0.9)

    if total == 0:
        return [_mk("info", "NO_DATA", "No cache events to analyze",
                    "The log contained zero events.",
                    "Point cache-doctor at a JSONL log with at least a few "
                    "dozen requests for meaningful diagnostics.")]

    # 1. Confirmed pollution: paraphrases served the wrong cached response.
    wrong = metrics.get("wrong_hits", 0) or 0
    if wrong:
        out.append(_mk(
            "critical", "POLLUTION_CONFIRMED",
            f"{wrong} cache hit(s) served the WRONG response",
            f"{wrong} hit(s) were flagged (flag_wrong=true): a lightly "
            f"rewritten prompt matched a cached response it should not have. "
            f"This is cache pollution - silent, wrong answers served fast.",
            f"Raise the similarity threshold above {threshold}, require "
            "stricter embedding agreement (e.g. rerank top-3 candidates), "
            "and audit prompts with similarity below "
            f"{round(threshold + 0.05, 2)}."))

    # 2. Borderline hits: high false-positive risk.
    bshare = metrics.get("borderline_share", 0.0) or 0.0
    if bshare >= 0.10 and hits:
        out.append(_mk(
            "high", "POLLUTION_RISK",
            f"{round(bshare * 100, 1)}% of hits are borderline",
            f"{metrics.get('borderline_hits', 0)} hits landed within "
            f"+0.05 of the threshold ({threshold}). Slight prompt rewrites "
            "slipping through are the classic pollution vector.",
            "Bump the threshold by 0.02-0.05 and re-run analyze to confirm "
            "the hit rate does not collapse; consider embedding-model "
            "upgrade if legitimate paraphrases then stop matching."))

    # 3. Low hit rate overall.
    if hit_rate < 0.35:
        out.append(_mk(
            "high", "LOW_HIT_RATE",
            f"Hit rate {round(hit_rate * 100, 1)}% is low",
            f"Only {hits} of {total} requests were served from cache. The "
            "cache is paying storage and lookup cost for little benefit.",
            "Check prompt normalization (whitespace/case), widen the "
            "similarity threshold cautiously, and confirm the cache is "
            "populated on miss (write-through)."))

    # 4. Near misses: threshold may be too strict.
    nshare = metrics.get("near_miss_share", 0.0) or 0.0
    if nshare >= 0.15 and hit_rate < 0.6:
        out.append(_mk(
            "medium", "THRESHOLD_STRICT",
            f"{round(nshare * 100, 1)}% of misses almost matched",
            f"{metrics.get('near_misses', 0)} misses scored within 0.05 "
            f"below the threshold ({threshold}) - likely legitimate "
            "paraphrases being rejected.",
            "Lower the threshold by 0.02-0.03 and watch wrong_hits; pair "
            "with a reranker so looser matching stays safe."))

    # 5. Expiry waste.
    eshare = metrics.get("expired_miss_share", 0.0) or 0.0
    if eshare >= 0.15 and misses:
        out.append(_mk(
            "medium", "EXPIRY_WASTE",
            f"{round(eshare * 100, 1)}% of misses are expired entries",
            f"{metrics.get('expired_misses', 0)} requests missed only "
            "because the entry had expired - the content was cacheable "
            "and would have been a hit.",
            "Increase TTL (or switch to sliding TTL) for stable content; "
            "split TTLs by content volatility if some entries go stale."))

    # 6. Key fragmentation: same prompt, many keys.
    fgroups = metrics.get("frag_groups", 0) or 0
    if fgroups:
        out.append(_mk(
            "medium", "KEY_FRAGMENTATION",
            f"{fgroups} prompt group(s) stored under multiple keys",
            f"{metrics.get('frag_requests', 0)} requests hit distinct cache "
            "keys for prompts that are identical after normalization - "
            "duplicate storage and diluted hit rates.",
            "Normalize prompts before keying: trim, collapse whitespace, "
            "casefold, and strip volatile prefixes (timestamps, session "
            "ids) from the cache key."))

    # 7. Stale serving.
    sshare = metrics.get("stale_share", 0.0) or 0.0
    if sshare >= 0.10 and hits:
        out.append(_mk(
            "low", "STALE_SERVING",
            f"{round(sshare * 100, 1)}% of hits served near-expiry entries",
            f"{metrics.get('stale_hits', 0)} hits were served from entries "
            "past 90% of their TTL - fresh on the wire, stale in spirit.",
            "Add background refresh (stale-while-revalidate) or shorten "
            "TTL for fast-changing content."))

    # 8. All clear.
    if not out:
        out.append(_mk(
            "info", "HEALTHY",
            f"Cache looks healthy ({round(hit_rate * 100, 1)}% hit rate)",
            f"{hits} hits / {total} requests, no pollution signals, no "
            "fragmentation, expiry under control.",
            "Keep monitoring; re-run after traffic mix changes or "
            "embedding-model upgrades."))

    return sorted(out, key=lambda s: SEVERITY_ORDER.get(s["severity"], 9))
