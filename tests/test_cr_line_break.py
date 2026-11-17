#!/usr/bin/env python3
"""A grouped event whose lines end with CR LF or a CR alone (spec S2.1, S8.4): CR is a delimiter,
so a value or a timestamp that ends a line ends right before it.

    python3 tests/test_cr_line_break.py

The template is the shape the encoder writes for a Windows Security event read with CR LF
line breaks. Offline, under a second.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import conformance  # noqa: E402
from refimpl import decode, tokenize  # noqa: E402

TEMPLATES = {"w": "<Data Name='AccessList'>%%$\r\n\t\t\t\t</Data>\r\n<Data Name='AccessMask'>$</Data>"}
LINE = "~w,4432,0x1"
TEXT = "<Data Name='AccessList'>%%4432\r\n\t\t\t\t</Data>\r\n<Data Name='AccessMask'>0x1</Data>"


class CrLineBreak(unittest.TestCase):
    def test_the_event_decodes_with_its_cr_lf(self):
        self.assertEqual(decode(LINE, TEMPLATES), TEXT)

    def test_cr_is_a_token_of_its_own(self):
        texts = [t.text for t in tokenize(TEXT)]
        self.assertIn("4432", texts)
        self.assertIn("\r", texts)
        self.assertEqual("".join(texts), TEXT)

    def test_a_lone_cr_and_a_timestamp_before_cr(self):
        templates = {"p": "$ : $(yyyy-MM-dd'T'HH:mm:ss'Z')\rVersion : $\r\n\t%%$\rend"}
        self.assertEqual(decode("~p,1488916587000,LastOriginatingChange,4,4433", templates),
                         "LastOriginatingChange : 2017-03-07T19:56:27Z\rVersion : 4\r\n\t%%4433\rend")

    def test_a_value_that_is_a_cr(self):
        templates = {"s": "Message=$ new process has been created.\n$\nCreator Subject:\n\tSecurity ID:\t\t$\\Administrator"}
        compact = "~s,A,\r,ATTACKRANGE\n~s,A,\r,X\n"
        lines = compact.split("\n")[:-1]  # S4.1: lines end at LF only
        self.assertEqual(len(lines), 2)
        self.assertEqual(decode(lines[0], templates),
                         "Message=A new process has been created.\n\r\nCreator Subject:\n\tSecurity ID:\t\tATTACKRANGE\\Administrator")
        self.assertEqual(len(compact.splitlines()), 4)  # a reader that ends lines at CR cuts both

    def test_the_value_before_cr_is_a_token_of_the_line(self):
        ok, checked, lines, refused = conformance.check_tokenizer([LINE], TEMPLATES, 0)
        self.assertEqual((ok, checked, lines, refused), (2, 2, 1, 0))


if __name__ == "__main__":
    unittest.main()
