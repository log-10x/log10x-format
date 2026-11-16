#!/usr/bin/env python3
"""The day-of-week pattern letter E renders as the encoder's DateTimeFormatter writes it.

    python3 tests/test_day_of_week.py

The engine's shipped timestamp patterns include "EEE MMM dd HH:mm:ss yyyy" and
"EEE, dd MMM yyyy HH:mm:ss zzz". Offline, under a second.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from refimpl import decode  # noqa: E402
from refimpl.codec import render_timestamp  # noqa: E402


class DayOfWeek(unittest.TestCase):
    def test_short_name_in_a_ctime_slot(self):
        templates = {"ctime": "job ran at $(EEE MMM dd HH:mm:ss yyyy)"}
        self.assertEqual(decode("~ctime,1794733507000", templates), "job ran at Sun Nov 15 09:05:07 2026")

    def test_full_name_and_first_letter(self):
        self.assertEqual(render_timestamp("1794733507000", "EEEE dd MMM yyyy"), "Sunday 15 Nov 2026")
        self.assertEqual(render_timestamp("1794733507000", "EEEEE"), "S")

    def test_comma_after_the_name(self):
        self.assertEqual(render_timestamp("1794733507000", "EEE, dd MMM yyyy HH:mm:ss"), "Sun, 15 Nov 2026 09:05:07")

    def test_the_offset_moves_the_day(self):
        # 2026-11-15 00:30 UTC is still Saturday at UTC-1
        self.assertEqual(render_timestamp("1794702600000", "EEE HH:mm", timezone_offset_minutes=-60), "Sat 23:30")


if __name__ == "__main__":
    unittest.main()
