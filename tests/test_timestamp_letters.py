#!/usr/bin/env python3
"""Hour, minute and second pattern letters render as DateTimeFormatter does (spec S7.1).

    python3 tests/test_timestamp_letters.py

One letter writes the number without padding, two or more pad it to that width:
`h:mm a` gives `5:05 AM`, `hh:mm a` gives `05:05 AM`. Offline, under a second.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from refimpl.codec import render_timestamp  # noqa: E402

MORNING = "1705295109000"  # 2024-01-15 05:05:09 UTC, milliseconds
EVENING = "1705352823000"  # 2024-01-15 21:07:03 UTC, milliseconds


class TimestampLetters(unittest.TestCase):

    def test_h_one_letter(self):
        self.assertEqual(render_timestamp(MORNING, "h:mm:ss a", 0), "5:05:09 AM")
        self.assertEqual(render_timestamp(EVENING, "h:mm a", 0), "9:07 PM")

    def test_h_two_letters(self):
        self.assertEqual(render_timestamp(MORNING, "hh:mm:ss a", 0), "05:05:09 AM")

    def test_H_m_s_one_letter(self):
        self.assertEqual(render_timestamp(MORNING, "H:mm", 0), "5:05")
        self.assertEqual(render_timestamp(MORNING, "HH:m:s", 0), "05:5:9")

    def test_two_letter_fields_unchanged(self):
        self.assertEqual(render_timestamp(MORNING, "yyyy-MM-dd HH:mm:ss", 0), "2024-01-15 05:05:09")


if __name__ == "__main__":
    unittest.main()
