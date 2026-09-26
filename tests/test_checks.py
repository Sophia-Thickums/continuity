"""Tests. Deliberately unglamorous: each one asserts on a MEASURED value."""
import os
import sys
import json
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from continuity import checks, store
from continuity.findings import OK, WARN, FAIL

EX = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples")


class TestGap(unittest.TestCase):
    def sessions(self, a, b):
        return [{"id": "a", "ts": a, "title": "", "messages": 1},
                {"id": "b", "ts": b, "title": "", "messages": 1}]

    def test_same_sitting_is_ok_and_measured(self):
        f = checks.check_gap(self.sessions(1000.0, 995.0))
        self.assertEqual(f.level, OK)
        self.assertEqual(f.measured["gap_seconds"], 5.0)
        self.assertIn("SAME SITTING", f.detail)

    def test_long_gap_is_a_real_gap(self):
        f = checks.check_gap(self.sessions(100000.0, 1000.0))
        self.assertIn("REAL GAP", f.detail)

    def test_gap_never_hides_its_number(self):
        f = checks.check_gap(self.sessions(1000.0, 900.0))
        self.assertIn("gap_seconds", f.measured)

    def test_single_session_does_not_guess(self):
        f = checks.check_gap([{"id": "a", "ts": 1.0}])
        self.assertEqual(f.level, OK)
        self.assertIn("not enough sessions", f.message)


class TestDuplicateSections(unittest.TestCase):
    def test_clean_file_passes(self):
        f = checks.check_duplicate_sections(os.path.join(EX, "memory_clean.md"))
        self.assertEqual(f.level, OK)
        self.assertEqual(f.measured["duplicated_headings"], {})

    def test_doubled_block_fails(self):
        f = checks.check_duplicate_sections(os.path.join(EX, "memory_doubled.md"))
        self.assertEqual(f.level, FAIL)
        self.assertIn("NOW", f.measured["duplicated_headings"])

    def test_narrow_check_would_have_missed_it(self):
        """The whole reason this check exists: grep for the FIRST heading says 1."""
        p = os.path.join(EX, "memory_doubled.md")
        with open(p) as fh:
            body = fh.read()
        self.assertEqual(body.count("## NOW"), 2)          # reality
        self.assertEqual(body.split("##")[1].strip().splitlines()[0], "NOW")  # first look: fine


class TestDeadPaths(unittest.TestCase):
    def test_resolvable_paths_pass(self):
        f = checks.check_dead_paths(os.path.join(EX, "memory_clean.md"), root=EX)
        self.assertEqual(f.level, OK)

    def test_missing_path_fails_and_names_itself(self):
        f = checks.check_dead_paths(os.path.join(EX, "memory_deadpaths.md"), root=EX)
        self.assertEqual(f.level, FAIL)
        self.assertTrue(any("old_prune_check" in d for d in f.measured["unresolved"]))


class TestContradictions(unittest.TestCase):
    def test_retired_rows_are_tombstones_not_assertions(self):
        claims = [
            {"key": "gpu.display", "claim": "9070 XT", "tier": "verified"},
            {"key": "gpu.display", "claim": "Vega FE", "tier": "retired"},
        ]
        f = checks.check_contradictions(claims)
        self.assertEqual(f.level, OK)          # the tombstone must NOT raise an alarm

    def test_two_live_claims_disagreeing_is_a_failure(self):
        claims = [
            {"key": "storage.pool", "claim": "/dev/sda", "tier": "verified"},
            {"key": "storage.pool", "claim": "/dev/sdb", "tier": "authored"},
        ]
        f = checks.check_contradictions(claims)
        self.assertEqual(f.level, FAIL)
        self.assertEqual(f.measured["contradictions"], 1)

    def test_superseded_row_does_not_conflict(self):
        claims = [
            {"key": "k", "claim": "v1", "tier": "retired", "superseded_by": "k@t2"},
            {"key": "k", "claim": "v2", "tier": "verified"},
        ]
        self.assertEqual(checks.check_contradictions(claims).level, OK)


class TestStore(unittest.TestCase):
    def test_jsonl_reads_newest_first(self):
        s = store.JsonlSessions(os.path.join(EX, "sessions.jsonl")).sessions()
        self.assertEqual(s[0]["id"], "w_1042")
        self.assertTrue(s[0]["ts"] > s[1]["ts"])

    def test_millis_are_normalised(self):
        import datetime
        t = store.normalize_ts(1790373719509)
        self.assertAlmostEqual(t, 1790373719.509, places=2)

    def test_bad_timestamp_is_none_not_a_guess(self):
        self.assertIsNone(store.normalize_ts("not a date"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
