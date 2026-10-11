# cache-doctor

The checkup your semantic cache never had.

LLM gateways all ship semantic caches now — but every tool on the market only
*operates* the cache (store, lookup, evict). Nobody diagnoses it. **cache-doctor
is the first CLI that performs a health check on a semantic cache**: it reads
your cache event log and reports hit rate, expiry waste, key fragmentation, and
— the silent killer — **cache pollution**, where a lightly rewritten prompt
matches a cached response it should never have matched.

## Differentiation

| | Cache products (Redis, GPTCache, LangChain caches, …) | cache-doctor |
|---|---|---|
| Job | Store and serve cached LLM responses | **Diagnose** the cache |
| Hit rate | You compute it yourself | Measured, with rolling hourly trend |
| Expiry | Configured once, forgotten | Expired-miss share + stale-serving detection |
| Pollution | Invisible | Borderline-hit risk + ground-truth `flag_wrong` detection |
| Key design | Whatever you happened to key on | Fragmentation detection (same prompt, many keys) |
| Advice | None | Prioritized, severity-ranked suggestions |

Think of it as the relationship between a database and a database health
monitor: the cache is the patient, cache-doctor is the checkup instrument.

## Install

```bash
pip install cache-doctor
```

Zero dependencies, stdlib only. Python ≥ 3.9. Works fully offline — your
prompts never leave the machine.

## Usage

Point it at a JSONL cache log — one event per line:

```jsonc
{"ts": "2026-10-11T01:00:01Z", "prompt": "What is the capital of France?",
 "cache_key": "k001", "hit": false, "miss_reason": "no_key",
 "threshold": 0.9, "ttl_seconds": 3600}
{"ts": "2026-10-11T01:00:22Z", "prompt": "Capital of France?",
 "cache_key": "k001", "hit": true, "similarity": 0.91,
 "threshold": 0.9, "ttl_seconds": 3600, "cache_age_seconds": 60}
```

```bash
# Full health report + suggestions
cache-doctor analyze cache-log.jsonl

# Machine-readable metrics
cache-doctor analyze cache-log.jsonl --json

# Suggestions only (from a log, or from saved --state)
cache-doctor suggest --log cache-log.jsonl
cache-doctor analyze cache-log.jsonl --state state.json
cache-doctor suggest --state state.json
```

### What it reports

- **Hit rate** — overall plus a rolling hourly trend, so you can see *when* it degraded.
- **Miss reasons** — `no_key` / `expired` / `low_similarity`, with expired-miss share.
- **Pollution signals** — borderline hits (similarity within +0.05 of threshold),
  ground-truth wrong hits (`flag_wrong: true`), and near misses.
- **Key fragmentation** — the same normalized prompt stored under multiple keys
  (a prompt-normalization bug wasting storage and diluting hits).
- **Stale serving** — hits served from entries past 90% of their TTL.
- **Suggestions** — severity-ranked fixes (`POLLUTION_CONFIRMED`,
  `THRESHOLD_STRICT`, `EXPIRY_WASTE`, `KEY_FRAGMENTATION`, `STALE_SERVING`, …).

### Log schema

| Field | Required | Meaning |
|---|---|---|
| `prompt` | yes | Full prompt text |
| `cache_key` | no | The key used for lookup |
| `hit` | yes | Was it served from cache? |
| `similarity` | no | Similarity score of the hit / best candidate |
| `threshold` | no | Configured similarity threshold (default 0.9) |
| `ttl_seconds` | no | TTL of the entry |
| `cache_age_seconds` | no | Age of the served entry (hits) |
| `miss_reason` | no | `no_key`, `expired`, `low_similarity` |
| `flag_wrong` | no | Ground truth: the hit was a false positive |
| `ts` | no | ISO-8601 timestamp (enables hourly trend) |

## Example

```
$ cache-doctor analyze examples/sample-log.jsonl

cache-doctor  health report
============================================
events analyzed :         16
cache hits      :          6     37.5%  [###########-------------------]
cache misses    :         10
similarity thr. :        0.9

miss reasons:
  expired             2    20.0%
  low_similarity      3    30.0%
  no_key              5    50.0%

pollution signals:
  borderline hits :      3  (  50.0% of hits)
  wrong hits      :      1   <- flag_wrong=true
  near misses     :      3  ( 30.0% of misses)
...
```

## Development

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

## License

MIT — see [LICENSE](LICENSE).
