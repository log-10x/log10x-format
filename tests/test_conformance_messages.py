#!/usr/bin/env python3
"""The DECODE check of tests/conformance.py names why a line did not decode.

    python3 tests/test_conformance_messages.py

refimpl.decode returns None in three cases: the template is not in the map, a
back-reference in the template reaches before the first value, or the line carries
fewer values than the template's slots need. conformance.py used to print "template not
found" for all three, so a short value list sent the reader looking for a template that
was present. Offline, under a second.
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
from refimpl import decode  # noqa: E402

TEMPLATES = {
    "addr": "$.$.$.$ ok",            # four value slots
    "stamped": "$(epoch) $ and $",    # one timestamp slot, two value slots
    "backref": "$1 x",                # back-reference before any value
}


class WhyNotDecoded(unittest.TestCase):
    def assertReason(self, line, expected):
        # Only lines decode() refuses are ever explained.
        self.assertIsNone(decode(line, TEMPLATES))
        self.assertEqual(conformance.why_not_decoded(line, TEMPLATES), expected)

    def test_missing_template(self):
        self.assertReason("~nosuch,1,2", "template not found")

    def test_short_value_list(self):
        # An address written as one value where the template has four slots.
        self.assertReason("~addr,10.0.1.14",
                          "short value list: the line carries 1 value, its template needs 4")

    def test_short_value_list_counts_timestamps(self):
        self.assertReason("~stamped,1604207116696,a",
                          "short value list: the line carries 2 values, its template needs 3")

    def test_unresolvable_back_reference(self):
        self.assertReason("~backref,a", "template back-reference reaches before its first value")

    def test_full_lines_still_decode(self):
        self.assertEqual(decode("~addr,10,0,1,14", TEMPLATES), "10.0.1.14 ok")
        self.assertEqual(decode("~stamped,1604207116696,a,b", TEMPLATES), "1604207116696 a and b")


class DecodeCheckOutput(unittest.TestCase):
    """main() prints the reason and still fails the DECODE check."""

    def run_main(self, encoded_lines):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            (cache / "otel-sample-200mb.log").write_text("10.0.1.14 ok\n")
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

    def test_short_line_reported_as_short(self):
        code, out = self.run_main(["~addr,10.0.1.14"])
        self.assertEqual(code, 1)
        self.assertIn("FAIL  DECODE", out)
        self.assertIn("! short value list: the line carries 1 value, its template needs 4: ~addr,10.0.1.14", out)
        self.assertNotIn("template not found", out)

    def test_missing_template_reported_as_missing(self):
        code, out = self.run_main(["~other,10,0,1,14"])
        self.assertEqual(code, 1)
        self.assertIn("FAIL  DECODE", out)
        self.assertIn("! template not found: ~other,10,0,1,14", out)

    def test_good_line_passes_decode(self):
        code, out = self.run_main(["~addr,10,0,1,14"])
        self.assertIn("pass  DECODE", out)
        self.assertNotIn("! ", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
