#!/usr/bin/env python3
"""Randomised checks on the properties the format claims for arbitrary input.

    python3 tests/fuzz.py [--rounds N]

The conformance suite proves this code handles Log10x's published data. This proves it
handles input that data never contains: lone escape characters, a value that looks like a
back-reference, the encoded-line prefix appearing inside a line, non-ASCII digits, and
malformed templates from a hostile source.

Five properties, each checked over generated input:

  1. TOKENIZE   concatenating every token reproduces the line exactly
  2. BASE-84    encode then decode is the identity across the signed 64-bit range
  3. ROUND TRIP encode then decode returns the original bytes, with an empty library
                so that every token becomes a value and the value path is fully exercised
  4. TEMPLATES  a malformed template is parsed or rejected, never crashed on
  5. DECODE     a malformed encoded line is handled, never crashed on

Property 3 covers the case the format cannot represent, spec S8.1: a value containing the
value delimiter. Commas are generated deliberately, and the round trip holds because a
comma is a token delimiter and so can never end up inside a value.
"""

import argparse
import random
import string
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from refimpl import SymbolLibrary, decode, encode, tokenize  # noqa: E402
from refimpl.codec import parse_template  # noqa: E402
from refimpl.hashes import base84_decode, base84_encode  # noqa: E402

ALPHABET = string.printable + "é中٣\x00\r"

#: Fragments chosen because each one is a way the format could break.
ADVERSARIAL = [
    "$", "/", "//", "/$", "~", ",", "\n", "$1", "$(x)", "$0(", "$$$",
    "a$b", "a//b", "x,y", "-1", "--1", "1-1", "-", "a-", "٣", "-٣", "()",
]

MALFORMED_TEMPLATES = [
    "$(", "$", "/", "//", "/$", "$99", "$(unterminated", "a$(b", "$0", "",
    "$(())", "///", "$$", "$" * 50,
    "$\u0663",           # a Unicode digit after a slot marker is not a distance
    "a\x00b",            # a literal NUL must survive unescaping
    "$9", "$1",          # a distance reaching past the first value
]

MALFORMED_LINES = ["~", "~,", "~abc", "~abc,", "not encoded", "~a,b,c", "", "~,,,"]

#: Regression cases. Each one is a defect that was found and fixed; each pairs a
#: template with an encoded line and the result the reader must produce.
REGRESSIONS = [
    # A literal NUL in a template used to come back as "$", because unescaping ran as a
    # series of substitutions through a sentinel that can itself occur in a log line.
    ("a\x00b", "~t,", "a\x00b"),
    # "$" followed by a Unicode digit used to parse as a back-reference distance and
    # resolve to a negative index, silently reading a value from the end of the list.
    ("$\u0663", "~t,v", "v\u0663"),
    # A distance reaching past the first value must fail the line, not wrap around.
    ("$9", "~t,v", None),
    # A template asking for more values than the line carries must fail the line.
    ("$ $ $", "~t,v", None),
]

#: Timestamp values a hostile source could supply. None may raise out of the decoder.
HOSTILE_TIMESTAMPS = ["\u0663", "-", "--5", "99999999999999999999999999",
                      "-99999999999999999999", "", "0", "-1"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=20000)
    parser.add_argument("--seed", type=int, default=11)
    args = parser.parse_args()
    random.seed(args.seed)

    empty = SymbolLibrary()
    failures = []
    results = []

    # 1. TOKENIZE
    for _ in range(args.rounds):
        line = "".join(random.choice(ALPHABET) for _ in range(random.randrange(0, 40)))
        if "".join(t.text for t in tokenize(line)) != line:
            failures.append(("tokenize is lossy", repr(line)))
    results.append(("TOKENIZE   concatenated tokens reproduce the line", f"{args.rounds:,} lines"))

    # 2. BASE-84
    edges = [0, 1, -1, 84, -84, 2**63 - 1, -(2**63), -(2**63) + 1]
    values = edges + [random.randrange(-(2**63), 2**63) for _ in range(args.rounds // 4)]
    for value in values:
        try:
            if base84_decode(base84_encode(value)) != value:
                failures.append(("base-84 round trip", value))
        except Exception as error:  # noqa: BLE001
            failures.append(("base-84 raised", value, repr(error)))
    results.append(("BASE-84    encode then decode is the identity", f"{len(values):,} values, including both range ends"))

    # 3. ROUND TRIP
    trips = max(1, args.rounds // 3)
    for _ in range(trips):
        line = "".join(
            random.choice(ADVERSARIAL + list(ALPHABET))
            for _ in range(random.randrange(0, 10))
        )
        result = encode(line, empty)
        back = decode(result.line, {result.template_hash: result.template})
        if back != line:
            failures.append(("round trip", repr(line), repr(back)))
    results.append(("ROUND TRIP encode then decode returns the original bytes", f"{trips:,} lines built from adversarial fragments"))

    # 4. TEMPLATES
    for template in MALFORMED_TEMPLATES:
        try:
            parse_template(template)
        except Exception as error:  # noqa: BLE001
            failures.append(("parse_template crashed", repr(template), repr(error)))
    results.append(("TEMPLATES  a malformed template does not crash the parser", f"{len(MALFORMED_TEMPLATES)} templates"))

    # 5. DECODE
    for line in MALFORMED_LINES:
        try:
            decode(line, {})
        except Exception as error:  # noqa: BLE001
            failures.append(("decode crashed", repr(line), repr(error)))
    for value in HOSTILE_TIMESTAMPS:
        try:
            decode(f"~t,{value}", {"t": "$(yyyy-MM-dd HH:mm:ss)"})
        except Exception as error:  # noqa: BLE001
            failures.append(("hostile timestamp crashed", repr(value), repr(error)))
    results.append(("DECODE     a malformed encoded line does not crash", f"{len(MALFORMED_LINES)} lines, {len(HOSTILE_TIMESTAMPS)} hostile timestamps"))

    # 6. REGRESSIONS
    for template, line, expected in REGRESSIONS:
        try:
            got = decode(line, {"t": template})
        except Exception as error:  # noqa: BLE001
            failures.append(("regression raised", repr(template), repr(error)))
            continue
        if got != expected:
            failures.append(("regression", repr(template), f"got {got!r} want {expected!r}"))
    results.append(("REGRESSION previously fixed defects stay fixed", f"{len(REGRESSIONS)} cases"))

    for name, detail in results:
        print(f"  pass  {name}" if not failures else f"        {name}")
        print(f"        {detail}")
    print()
    if failures:
        print(f"{len(failures)} FAILURES")
        for failure in failures[:10]:
            print("   ", failure)
        return 1
    print("=" * 74)
    print("no failures")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
