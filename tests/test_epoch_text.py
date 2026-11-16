#!/usr/bin/env python3
"""An epoch timestamp passes its text through (spec S4.4): $(+%s.%N) keeps the dot, the
fraction's leading zeros and every fraction digit.

    python3 tests/test_epoch_text.py

Templates and lines have the shape the encoder writes for epoch milliseconds with a
fraction. Offline, under a second.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from refimpl import decode  # noqa: E402

TEMPLATES = {
    "ms": "$(+%s.%N) INFO epoch ms fraction $ digits",
    "json": '{"ts":$(+%s.%N),"msg":"$"}',
    "ns": "$(+%s) INFO epoch ns",
}


class EpochText(unittest.TestCase):
    def test_fraction_keeps_its_dot(self):
        self.assertEqual(decode("~ms,1705313472123.456,3", TEMPLATES),
                         "1705313472123.456 INFO epoch ms fraction 3 digits")

    def test_leading_zeros_of_the_fraction_stay(self):
        self.assertEqual(decode("~ms,1705313472123.000456,6", TEMPLATES),
                         "1705313472123.000456 INFO epoch ms fraction 6 digits")

    def test_nine_fraction_digits(self):
        self.assertEqual(decode("~ms,1705313472123.456789123,9", TEMPLATES),
                         "1705313472123.456789123 INFO epoch ms fraction 9 digits")

    def test_in_a_json_line(self):
        self.assertEqual(decode("~json,1705313472123.456789,started", TEMPLATES),
                         '{"ts":1705313472123.456789,"msg":"started"}')

    def test_nanosecond_epoch(self):
        self.assertEqual(decode("~ns,1705313472123456789", TEMPLATES),
                         "1705313472123456789 INFO epoch ns")


if __name__ == "__main__":
    unittest.main()
