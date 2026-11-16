#!/usr/bin/env python3
"""Epoch timestamps with a fraction (spec S4.4), checked against the encoder's own output.

    python3 tests/test_epoch_fixtures.py

fixtures/epoch.jsonl holds 5 records {note, text, encoded, template_hash, template, pattern,
value, time_ns}, the encoder's output: three lines with a time in seconds with a fraction
($(+%s.%f)) and their compact lines (an audit record, a logfmt line, and a Kubernetes
container log line whose escaped JSON holds the slot), and the unchanged neighbours
$(+%s.%N) and $(+%s) (template and hash only). Checks: the template hash, byte-identical
decode, and the event time read from the value. Offline, under a second.
"""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from refimpl import decode, epoch_time_ns, hash_template  # noqa: E402

RECORDS = [json.loads(l) for l in (ROOT / "fixtures" / "epoch.jsonl").read_text(encoding="utf-8").splitlines() if l]


class EpochFixtures(unittest.TestCase):
    def test_template_hashes(self):
        for r in RECORDS:
            self.assertEqual(hash_template(r["template"]), r["template_hash"], r["note"])

    def test_decode_is_byte_identical(self):
        lines = [r for r in RECORDS if r["encoded"]]
        self.assertEqual(len(lines), 3)
        for r in lines:
            self.assertEqual(decode(r["encoded"], {r["template_hash"]: r["template"]}), r["text"], r["note"])

    def test_event_time(self):
        for r in RECORDS:
            self.assertEqual(epoch_time_ns(r["value"], r["pattern"]), r["time_ns"], r["note"])

    def test_fraction_digits_are_tenths_to_nanoseconds(self):
        self.assertEqual(epoch_time_ns("1723042099.6", "+%s.%f"), 1723042099600000000)
        self.assertEqual(epoch_time_ns("1705313472.022663733", "+%s.%f"), 1705313472022663733)
        self.assertEqual(epoch_time_ns("1705313472123.456789123", "+%s.%N"), 1705313472123456789)

    def test_a_value_of_another_shape_gives_no_time_and_keeps_its_text(self):
        for value in ("17230420.99", "1723042099", "1723042099.", "1723042099.1234567890"):
            self.assertIsNone(epoch_time_ns(value, "+%s.%f"), value)
        self.assertEqual(decode("~h,17230420.99", {"h": "ts=$(+%s.%f) msg=hello"}), "ts=17230420.99 msg=hello")

    def test_text_is_written_back_as_read(self):
        templates = {"h": "ts=$(+%s.%f) msg=hello"}
        for value in ("1723042099.600", "1723042099.6", "1705313472.000123"):
            self.assertEqual(decode("~h," + value, templates), f"ts={value} msg=hello")


if __name__ == "__main__":
    unittest.main()
