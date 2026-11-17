#!/usr/bin/env python3
"""A line with no values, written as the template hash alone (spec S8.2), decodes to its
template's text.

    python3 tests/test_value_free_line.py

The lines and templates are encoder output (engine 1.1.180, one event per line).
Offline, under a second.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from refimpl import decode  # noqa: E402

TEMPLATES = {
    "->GI_L4yVkB": "space C:\\Windows\\beta.exe and more",
    ";Uvy[i10Xn": "ads C:\\Users\\alice\\file.txt:Zone.Identifier:/$DATA",
    "4tp}Z1^p*B": "account CORP\\\u0414\u043c\u0438\u0442\u0440\u0438\u0439 logged on as NT AUTHORITY\\SYSTEM",
}


class ValueFreeLine(unittest.TestCase):
    def test_hash_alone_decodes_to_the_template_text(self):
        self.assertEqual(decode("~->GI_L4yVkB", TEMPLATES), "space C:\\Windows\\beta.exe and more")
        self.assertEqual(
            decode("~4tp}Z1^p*B", TEMPLATES),
            "account CORP\\\u0414\u043c\u0438\u0442\u0440\u0438\u0439 logged on as NT AUTHORITY\\SYSTEM",
        )

    def test_template_escapes_are_undone(self):
        self.assertEqual(decode("~;Uvy[i10Xn", TEMPLATES), "ads C:\\Users\\alice\\file.txt:Zone.Identifier:$DATA")

    def test_hash_and_an_empty_value_decode_the_same(self):
        self.assertEqual(decode("~->GI_L4yVkB,", TEMPLATES), decode("~->GI_L4yVkB", TEMPLATES))
        slot = {"slot": "user $ logged on"}
        self.assertEqual(decode("~slot", slot), decode("~slot,", slot))

    def test_text_that_is_no_known_hash_passes_through(self):
        self.assertEqual(decode("~not a hash", TEMPLATES), "~not a hash")
        self.assertEqual(decode("plain line", TEMPLATES), "plain line")


if __name__ == "__main__":
    unittest.main()
