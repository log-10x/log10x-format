#!/usr/bin/env python3
"""The TOKENIZER check of tests/conformance.py accepts a value joined from several tokens
(spec S2.3) and still rejects a value that is not a run of whole tokens.

    python3 tests/test_conformance_joined.py

The joined lines are encoder output with the options ipv4SingleToken and
windowsPathSingleToken on (an IPv4 address and Windows paths as one value). Offline,
under a second.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import conformance  # noqa: E402
from refimpl import decode, tokenize  # noqa: E402

TEMPLATES = {
    "-MP_[zO@ps[": "<Data Name='ObjectName'>$<//Data>",
    "2e7Bfx^Cii": "<Data Name='ShareName'>$<//Data>",
    "-DVbX!U&>Y*": "src=$ file=$",
    "4d$Z}5oQ05": 'ProcessName="$" pid=$',
}

ENCODED = [
    "~-MP_[zO@ps[,C:\\Program Files (x86)\\Common Files\\Microsoft Shared\\app.dll",
    "~-MP_[zO@ps[,C:\\Users\\J\u00fcrgen\\\u0414\u043e\u043a\u0443\u043c\u0435\u043d\u0442\u044b\\\u043e\u0442\u0447\u0451\u0442_2024.docx",
    "~-MP_[zO@ps[,\\REGISTRY\\MACHINE\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Winlogon",
    "~2e7Bfx^Cii,\\\\fileserver01\\Finance$\\Q3 Reports\\report.xlsx",
    "~-DVbX!U&>Y*,10.0.1.14,C:\\inetpub\\logs\\LogFiles\\W3SVC1\\u_ex231114.log status=200",
    "~4d$Z}5oQ05,C:\\Windows\\System32\\svchost.exe,4",
]


class JoinedValues(unittest.TestCase):
    def test_joined_values_pass_and_are_counted(self):
        stats = {}
        ok, checked, lines, refused = conformance.check_tokenizer(ENCODED, TEMPLATES, 0, stats)
        self.assertEqual((ok, checked, lines, refused), (8, 8, 6, 0))
        # every value but the pid 4 is several tokens
        self.assertEqual(stats["joined"], 7)

    def test_a_value_of_one_token_is_not_counted_as_joined(self):
        stats = {}
        conformance.check_tokenizer(["~4d$Z}5oQ05,svchost,4"], TEMPLATES, 0, stats)
        self.assertEqual(stats["joined"], 0)

    def check_one(self, template, value):
        templates = {"h": template}
        return conformance.check_tokenizer(["~h," + value], templates, 0)

    def test_a_run_of_whole_tokens_before_a_delimiter(self):
        self.assertEqual(self.check_one("a $ b", "C:\\x\\y"), (1, 1, 1, 0))
        self.assertEqual(self.check_one("a $", "C:\\x\\y"), (1, 1, 1, 0))

    def test_a_value_that_ends_inside_a_token_fails(self):
        # the line reads "a C:\x\yb": the value ends inside the token "yb"
        self.assertEqual(self.check_one("a $b", "C:\\x\\y"), (0, 1, 1, 0))

    def test_a_value_followed_by_a_character_that_is_no_delimiter_fails(self):
        # "?" is no delimiter (S2.1): the line reads "GET C:\x\index.aspx?id", where
        # "aspx?id" is one token
        self.assertEqual(self.check_one("GET $?id", "C:\\x\\index.aspx"), (0, 1, 1, 0))

    def test_a_value_that_starts_inside_a_token_fails(self):
        # the line reads "a xy:\z": the value starts inside the token "xy"
        self.assertEqual(self.check_one("a x$", "y:\\z"), (0, 1, 1, 0))

    def test_the_lines_decode_to_their_text(self):
        line = decode(ENCODED[3], TEMPLATES)
        self.assertEqual(line, "<Data Name='ShareName'>\\\\fileserver01\\Finance$\\Q3 Reports\\report.xlsx</Data>")
        self.assertTrue(conformance.is_joined_value(
            "\\\\fileserver01\\Finance$\\Q3 Reports\\report.xlsx", line, tokenize(line)))


if __name__ == "__main__":
    unittest.main()
