#!/usr/bin/env python3
"""After a line it cannot decode, the DECODE check of tests/conformance.py still compares
every later line with its own original, and the TOKENIZER check does not pass on lines
it could not check.

    python3 tests/test_conformance_cursor.py

A refused line stands for at least one original line. The DECODE check used to leave its
cursor where it was, so every later line was compared with the original before it and
reported as different; and the TOKENIZER check skipped refused lines, so it passed with
"0/0 values" when it had checked nothing. Offline, under a second.
"""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import conformance  # noqa: E402

TEMPLATES = {
    "addr": "$.$.$.$ ok",     # four value slots
    "pair": "$ head\n$ tail",  # an event of two lines
}


class DecodeCursor(unittest.TestCase):
    def check(self, encoded, originals):
        return conformance.check_decode(encoded, originals, TEMPLATES, 0)

    def test_lines_after_a_refusal_match_their_own_originals(self):
        originals = ["10.0.1.14 ok", "10.0.1.15 ok", "10.0.1.16 ok"]
        ok, cursor, failures = self.check(
            ["~addr,10.0.1.14", "~addr,10,0,1,15", "~addr,10,0,1,16"], originals)
        self.assertEqual((ok, cursor), (2, 3))
        self.assertEqual([why for _, why in failures],
                         ["short value list: the line carries 1 value, its template needs 4"])

    def test_a_refused_multi_line_event(self):
        originals = ["a head", "b tail", "10.0.1.15 ok"]
        ok, cursor, failures = self.check(["~pair,a", "~addr,10,0,1,15"], originals)
        self.assertEqual((ok, cursor), (1, 3))
        self.assertEqual(len(failures), 1)

    def test_refusals_in_a_row(self):
        originals = ["10.0.1.1 ok", "10.0.1.2 ok", "10.0.1.3 ok", "10.0.1.4 ok"]
        ok, cursor, failures = self.check(
            ["~addr,10,0,1,1", "~addr,x", "~nosuch,1", "~addr,10,0,1,4"], originals)
        self.assertEqual((ok, cursor), (2, 4))
        self.assertEqual([why for _, why in failures],
                         ["short value list: the line carries 1 value, its template needs 4",
                          "template not found"])

    def test_no_refusal_is_unchanged(self):
        originals = ["10.0.1.1 ok", "a head", "b tail"]
        ok, cursor, failures = self.check(["~addr,10,0,1,1", "~pair,a,b"], originals)
        self.assertEqual((ok, cursor, failures), (2, 3, []))

    def test_a_wrong_line_is_still_reported(self):
        originals = ["10.0.1.1 ok", "10.0.1.2 ok"]
        ok, cursor, failures = self.check(["~addr,10,0,1,1", "~addr,10,0,1,9"], originals)
        self.assertEqual((ok, cursor), (1, 2))
        self.assertEqual([why for _, why in failures], ["differs at original line 1"])


class TokenizerCheck(unittest.TestCase):
    def test_refused_lines_are_counted(self):
        ok, checked, lines, refused = conformance.check_tokenizer(
            ["~addr,10.0.1.14", "~addr,10,0,1,15"], TEMPLATES, 0)
        self.assertEqual((ok, checked, lines, refused), (4, 4, 1, 1))


class MainOutput(unittest.TestCase):
    """main() on a sample whose first line is refused."""

    def run_main(self, encoded_lines, original_lines):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            (cache / "otel-sample-200mb.log").write_text("\n".join(original_lines) + "\n")
            (cache / "otel-sample-encoded.log").write_text("\n".join(encoded_lines) + "\n")
            (cache / "otel-sample-templates.json").write_text(
                json.dumps({"templateHash": "addr", "template": TEMPLATES["addr"]}) + "\n")
            saved = conformance.CACHE
            conformance.CACHE = cache
            out = io.StringIO()
            try:
                with contextlib.redirect_stdout(out):
                    code = conformance.main()
            finally:
                conformance.CACHE = saved
        return code, out.getvalue()

    def test_only_the_refused_line_is_reported(self):
        code, out = self.run_main(["~addr,10.0.1.14", "~addr,10,0,1,15", "~addr,10,0,1,16"],
                                  ["10.0.1.14 ok", "10.0.1.15 ok", "10.0.1.16 ok"])
        self.assertEqual(code, 1)
        self.assertIn("FAIL  DECODE", out)
        self.assertIn("2/3 lines, 3/3 originals", out)
        self.assertNotIn("differs at original line", out)

    def test_tokenizer_fails_when_nothing_was_checked(self):
        code, out = self.run_main(["~addr,10.0.1.14"], ["10.0.1.14 ok"])
        self.assertIn("FAIL  TOKENIZER", out)
        self.assertIn("0/0 values over 0 lines, 1 lines not decoded and not checked", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
