"""Smoke tests for cache-doctor (stdlib unittest only)."""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cache_doctor.analyze import compute_metrics, norm_prompt, parse_log
from cache_doctor.cli import main
from cache_doctor.suggest import suggest


def ev(**kw):
    base = {"ts": "2026-10-11T01:00:00Z", "threshold": 0.9,
            "ttl_seconds": 3600}
    base.update(kw)
    return base


def write_jsonl(events):
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        for e in events:
            fh.write(json.dumps(e) + "\n")
    return path


class TestParse(unittest.TestCase):
    def test_parse_ok(self):
        path = write_jsonl([ev(prompt="a", hit=False), ev(prompt="b", hit=True)])
        try:
            self.assertEqual(len(parse_log(path)), 2)
        finally:
            os.unlink(path)

    def test_parse_bad_json_raises(self):
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(fd, "w") as fh:
            fh.write('{"ok": 1}\nnot json\n')
        try:
            with self.assertRaises(ValueError):
                parse_log(path)
        finally:
            os.unlink(path)

    def test_parse_empty_file(self):
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
        try:
            self.assertEqual(parse_log(path), [])
        finally:
            os.unlink(path)


class TestMetrics(unittest.TestCase):
    def test_hit_rate(self):
        events = [ev(hit=True, similarity=0.95) for _ in range(3)]
        events += [ev(hit=False, miss_reason="no_key") for _ in range(2)]
        m = compute_metrics(events)
        self.assertEqual(m["total"], 5)
        self.assertEqual(m["hit_rate"], 0.6)
        self.assertEqual(m["miss_reasons"]["no_key"], 2)

    def test_borderline_hits_detected(self):
        events = [ev(hit=True, similarity=0.92)]  # within +0.05 of 0.9
        m = compute_metrics(events)
        self.assertEqual(m["borderline_hits"], 1)
        self.assertEqual(m["borderline_share"], 1.0)

    def test_wrong_hits_detected(self):
        events = [ev(hit=True, similarity=0.95, flag_wrong=True)]
        m = compute_metrics(events)
        self.assertEqual(m["wrong_hits"], 1)

    def test_expiry_share(self):
        events = [ev(hit=False, miss_reason="expired") for _ in range(3)]
        events += [ev(hit=False, miss_reason="no_key")]
        m = compute_metrics(events)
        self.assertEqual(m["expired_miss_share"], 0.75)

    def test_key_fragmentation(self):
        events = [
            ev(prompt="What is AI?", cache_key="k1", hit=False),
            ev(prompt="what  is ai?", cache_key="k2", hit=False),
            ev(prompt="unrelated", cache_key="k9", hit=False),
        ]
        m = compute_metrics(events)
        self.assertEqual(m["frag_groups"], 1)
        self.assertEqual(m["frag_requests"], 2)

    def test_stale_hits(self):
        events = [ev(hit=True, similarity=0.95,
                     cache_age_seconds=3500, ttl_seconds=3600)]
        m = compute_metrics(events)
        self.assertEqual(m["stale_hits"], 1)

    def test_empty_events(self):
        m = compute_metrics([])
        self.assertEqual(m["total"], 0)
        self.assertEqual(m["hit_rate"], 0.0)

    def test_norm_prompt(self):
        self.assertEqual(norm_prompt("  What IS  AI? "), "what is ai?")


class TestSuggest(unittest.TestCase):
    def test_pollution_is_critical(self):
        m = compute_metrics([ev(hit=True, similarity=0.93, flag_wrong=True)])
        s = suggest(m)
        self.assertEqual(s[0]["code"], "POLLUTION_CONFIRMED")
        self.assertEqual(s[0]["severity"], "critical")

    def test_low_hit_rate_suggests(self):
        events = [ev(hit=False, miss_reason="no_key") for _ in range(9)]
        events += [ev(hit=True, similarity=0.95)]
        s = suggest(compute_metrics(events))
        self.assertTrue(any(x["code"] == "LOW_HIT_RATE" for x in s))

    def test_healthy_cache_reports_info(self):
        events = [ev(hit=True, similarity=0.99) for _ in range(9)]
        events += [ev(hit=False, miss_reason="no_key", similarity=0.5)]
        s = suggest(compute_metrics(events))
        self.assertEqual(s, [s[0]])
        self.assertEqual(s[0]["code"], "HEALTHY")

    def test_expiry_waste_suggests(self):
        events = [ev(hit=False, miss_reason="expired") for _ in range(4)]
        events += [ev(hit=False, miss_reason="no_key")]
        s = suggest(compute_metrics(events))
        self.assertTrue(any(x["code"] == "EXPIRY_WASTE" for x in s))

    def test_empty_metrics(self):
        s = suggest(compute_metrics([]))
        self.assertEqual(s[0]["code"], "NO_DATA")


class TestCLI(unittest.TestCase):
    def test_analyze_runs(self):
        path = write_jsonl([ev(prompt="a", hit=True, similarity=0.95),
                            ev(prompt="b", hit=False, miss_reason="no_key")])
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                rc = main(["analyze", path])
        finally:
            os.unlink(path)
        self.assertEqual(rc, 0)
        self.assertIn("hit rate", buf.getvalue())

    def test_analyze_json_output(self):
        path = write_jsonl([ev(prompt="a", hit=True, similarity=0.95)])
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                rc = main(["analyze", path, "--json"])
        finally:
            os.unlink(path)
        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        self.assertEqual(data["total"], 1)

    def test_suggest_from_log(self):
        path = write_jsonl([ev(prompt="a", hit=False, miss_reason="no_key")])
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                rc = main(["suggest", "--log", path, "--json"])
        finally:
            os.unlink(path)
        self.assertEqual(rc, 0)
        codes = [s["code"] for s in json.loads(buf.getvalue())]
        self.assertIn("LOW_HIT_RATE", codes)

    def test_analyze_missing_file_errors(self):
        err = io.StringIO()
        with redirect_stderr(err):
            rc = main(["analyze", "/nonexistent/file.jsonl"])
        self.assertEqual(rc, 2)

    def test_sample_log_end_to_end(self):
        sample = os.path.join(os.path.dirname(__file__), "..",
                              "examples", "sample-log.jsonl")
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["analyze", os.path.abspath(sample)])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("pollution signals", out)  # the flag_wrong event
        self.assertIn("frag. groups", out)       # capital-of-france k001..k003


if __name__ == "__main__":
    unittest.main(verbosity=2)
