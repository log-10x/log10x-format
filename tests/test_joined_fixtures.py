#!/usr/bin/env python3
"""Encoder output with the options ipv4SingleToken and windowsPathSingleToken, checked the
way tests/conformance.py checks the published sample.

    python3 tests/test_joined_fixtures.py

fixtures/joined.jsonl holds 253 records {option, text, encoded, template_hash, template}:
synthetic lines with IPv4 addresses and Windows paths in many positions (brackets, quotes,
URLs, key=value, ports, CIDR, JSON with escapes and doubled backslashes, XML, UNC and device
paths, 8.3 names, spaces and parentheses, non-ASCII folder names, long paths), encoded one
event per line by the 10x Engine with one option, the other, or both. Only lines whose
encoded form carries a value holding a token delimiter are kept, up to two per line shape.
Offline, under a second.
"""

import json
import sys
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import conformance  # noqa: E402
from refimpl import decode, hash_template  # noqa: E402
from refimpl.codec import parse_template  # noqa: E402

RECORDS = [json.loads(l) for l in (ROOT / "fixtures" / "joined.jsonl").read_text(encoding="utf-8").splitlines() if l]


class JoinedFixtures(unittest.TestCase):
    def test_every_option_is_present(self):
        counts = Counter(r["option"] for r in RECORDS)
        self.assertEqual(
            counts,
            {"ipv4SingleToken": 72, "windowsPathSingleToken": 70, "ipv4SingleToken windowsPathSingleToken": 111},
        )

    def test_decode_rebuilds_every_line_byte_for_byte(self):
        for r in RECORDS:
            with self.subTest(encoded=r["encoded"][:60]):
                rebuilt = decode(r["encoded"], {r["template_hash"]: r["template"]}, timezone_offset_minutes=0)
                self.assertEqual(rebuilt, r["text"])

    def test_template_hash_is_reproduced(self):
        for r in RECORDS:
            with self.subTest(template=r["template"][:60]):
                self.assertEqual(hash_template(r["template"]), r["template_hash"])

    def test_every_value_is_a_token_or_a_joined_run(self):
        templates = {r["template_hash"]: r["template"] for r in RECORDS}
        stats = {}
        ok, checked, lines, refused = conformance.check_tokenizer(
            [r["encoded"] for r in RECORDS], templates, 0, stats
        )
        self.assertEqual((ok, lines, refused), (checked, len(RECORDS), 0))
        # every record carries at least one joined value
        self.assertGreaterEqual(stats["joined"], len(RECORDS))

    def test_lines_without_values_are_counted_not_checked(self):
        # a line passed through whole (no prefix) and a template hash alone (spec S8.2)
        result = conformance.check_tokenizer(["plain line, not encoded", "~h"], {"h": "no slot here"}, 0)
        self.assertEqual(result, (0, 0, 1, 0))

    def test_back_references_stay_inside_the_bound(self):
        for r in RECORDS:
            segments, _ = parse_template(r["template"])
            emitted = 0
            for segment in segments:
                if segment[0] != "value":
                    continue
                if segment[1] == emitted:
                    emitted += 1
                    continue
                self.assertIsNotNone(segment[1])
                self.assertLess(emitted - segment[1], 10)


if __name__ == "__main__":
    unittest.main()
