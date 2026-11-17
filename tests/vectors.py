#!/usr/bin/env python3
"""Decode the shared reader vectors and compare each with the text it must give.

    python3 tests/vectors.py

fixtures/line-end-vectors.json holds templates, encoded lines and the exact text each line
decodes to (spec S6.4): events read with CR LF, inside and at the end of an event, a CR
alone inside an event, and the same lines read with LF. The same file is checked by the
engine's decoder and by the Java and JavaScript decoders, so every reader of the encoded
form gives the same bytes. Offline, standard library only.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from refimpl import decode  # noqa: E402

VECTORS = ROOT / "fixtures" / "line-end-vectors.json"


def visible(text):
    return None if text is None else text.replace("\r", "\\r").replace("\n", "\\n")


def main() -> int:
    data = json.loads(VECTORS.read_text(encoding="utf-8"))
    templates = data["templates"]
    offset = data.get("timezoneOffsetMinutes", 0)
    failed = 0
    for event in data["events"]:
        got = decode(event["encoded"], templates, offset)
        if got != event["text"]:
            failed += 1
            print(f"FAIL {event['encoded']}\n  expected {visible(event['text'])}\n  got      {visible(got)}")
    total = len(data["events"])
    print(f"{total - failed} of {total} encoded lines decode to their text")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
