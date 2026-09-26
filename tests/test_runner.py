"""Tests for the config parser and the refuses-to-lie guard.

★ THE BUG THESE TEST FOR ACTUALLY HAPPENED. The first dogfood run against a real config
returned RESULT: OK having opened zero files — the parser ignored `[[layers]]`
array-of-tables, so every declared layer silently vanished and the tool reported green
about nothing. That is precisely the failure class this kit exists to catch, committed by
the kit. The guard and these tests are the fix.
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from continuity.runner import _read_toml, run
from continuity.findings import FAIL, OK


class TestParser(unittest.TestCase):
    def parse(self, text):
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as f:
            f.write(text)
            p = f.name
        try:
            return _read_toml(p)
        finally:
            os.unlink(p)

    def test_array_of_tables_is_captured(self):
        cfg = self.parse("""
[[layers]]
path = "/a.md"
limit_bytes = 100

[[layers]]
path = "/b.md"
""")
        self.assertEqual(len(cfg["layers"]), 2)
        self.assertEqual(cfg["layers"][0]["path"], "/a.md")
        self.assertEqual(cfg["layers"][0]["limit_bytes"], 100)
        self.assertEqual(cfg["layers"][1]["path"], "/b.md")

    def test_nested_fields_land_in_the_right_element(self):
        cfg = self.parse("""
[[layers]]
path = "/one.md"
stale_hours = 5

[[layers]]
path = "/two.md"
stale_hours = 99
""")
        self.assertEqual(cfg["layers"][0]["stale_hours"], 5)
        self.assertEqual(cfg["layers"][1]["stale_hours"], 99)

    def test_plain_sections_still_work(self):
        cfg = self.parse("""
[sessions]
type = "sqlite"
limit = 200
""")
        self.assertEqual(cfg["sessions"]["type"], "sqlite")
        self.assertEqual(cfg["sessions"]["limit"], 200)


class TestRefusesToReportBlind(unittest.TestCase):
    def test_config_declaring_layers_that_parse_to_none_fails(self):
        """The guard: never OK on a run that looked at nothing."""
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as f:
            # deliberately malformed in the way that once caused a silent vanish
            f.write("[[layers]\npath = \"/a.md\"\n")
            p = f.name
        try:
            rep = run(cfg_path=p)
        finally:
            os.unlink(p)
        self.assertEqual(rep.level, FAIL)
        self.assertTrue(any(x.check == "config" for x in rep.findings))


if __name__ == "__main__":
    unittest.main(verbosity=2)
