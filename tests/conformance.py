#!/usr/bin/env python3
"""Check this implementation against data Log10x published, not against itself.

    python3 tests/conformance.py

Downloads three files from the public release
https://github.com/log-10x/config/releases/tag/otel-sample-v1 (about 12 MB compressed),
caches them under fixtures/otel-sample/, and runs four checks:

  1. DECODE      every published encoded line rebuilds its original bytes exactly
  2. TEMPLATE ID hash_template reproduces every published template hash
  3. TOKENIZER   every published value is a token this tokenizer produces, or a run of
                 several tokens a producer joined into one value (spec S2.3)
  4. BACK-REFS   the published back-reference distances obey spec S4.3

Check 1 is the load-bearing one: 159,454 encoded lines, 197,430 original lines, and the
comparison is on bytes.
"""

import gzip
import json
import shutil
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from refimpl import decode, hash_template, tokenize  # noqa: E402
from refimpl.codec import LINE_PREFIX, TOKEN_DELIMITERS, VALUE_DELIMITER, parse_template  # noqa: E402

BASE = "https://github.com/log-10x/config/releases/download/otel-sample-v1/"
FILES = {
    "otel-sample-200mb.log.gz": "otel-sample-200mb.log",
    "otel-sample-encoded.log.gz": "otel-sample-encoded.log",
    "otel-sample-templates.json.gz": "otel-sample-templates.json",
}
CACHE = ROOT / "fixtures" / "otel-sample"

#: spec S7.3. The sample was produced on a us-east-1 host in EDT. A zone-less timestamp
#: pattern renders in local time, so decoding needs the zone the lines were written in.
SAMPLE_TZ_OFFSET_MINUTES = -240


def fetch():
    CACHE.mkdir(parents=True, exist_ok=True)
    for archive, plain in FILES.items():
        target = CACHE / plain
        if target.exists():
            continue
        gz = CACHE / archive
        if not gz.exists():
            print(f"  downloading {archive} ...", flush=True)
            urllib.request.urlretrieve(BASE + archive, gz)
        print(f"  expanding {archive} ...", flush=True)
        with gzip.open(gz, "rb") as src, target.open("wb") as dst:
            shutil.copyfileobj(src, dst)
        gz.unlink()


def why_not_decoded(line, templates):
    """Name why decode() returned None for an encoded line.

    decode() refuses a line in three cases: the template is not in the map, a
    back-reference in the template reaches before its first value, or the line carries
    fewer values than the template's slots need (timestamps lead the value list, spec
    S6.2). Only the first is a missing template.
    """
    body = line[len(LINE_PREFIX) :]
    split = body.find(VALUE_DELIMITER)
    template = templates.get(body[:split])
    if template is None:
        return "template not found"
    segments, timestamp_count = parse_template(template)
    indexes = [segment[1] for segment in segments if segment[0] == "value"]
    if any(index is None for index in indexes):
        return "template back-reference reaches before its first value"
    needed = timestamp_count + max(indexes, default=-1) + 1
    carried = len(body[split + 1 :].split(VALUE_DELIMITER))
    if carried < needed:
        noun = "value" if carried == 1 else "values"
        return f"short value list: the line carries {carried} {noun}, its template needs {needed}"
    return "not decoded"


#: how far past a refused line the DECODE check looks for the original line the next
#: decoded event starts at.
RESYNC_WINDOW = 10000


def check_decode(encoded, originals, templates, timezone_offset_minutes):
    """Decode every encoded line and compare it with the original lines it stands for.

    Returns (lines rebuilt exactly, original lines consumed, failures). A line decode()
    refuses stands for an unknown number of original lines, at least one: the cursor
    moves past one original line for it, and the next decoded event is compared from the
    first original line equal to its own first line, within RESYNC_WINDOW lines. Without
    that, every line after a refusal was compared with the wrong original.
    """
    cursor = 0
    ok = 0
    failures = []
    refused = False
    for line in encoded:
        rebuilt = decode(line, templates, timezone_offset_minutes=timezone_offset_minutes)
        if rebuilt is None:
            failures.append((line[:80], why_not_decoded(line, templates)))
            cursor += 1
            refused = True
            continue
        parts = rebuilt.split("\n")
        if refused:
            refused = False
            for at in range(cursor, min(len(originals), cursor + RESYNC_WINDOW)):
                if originals[at] == parts[0]:
                    cursor = at
                    break
        matched = all(
            cursor + n < len(originals) and originals[cursor + n] == part
            for n, part in enumerate(parts)
        )
        if matched:
            ok += 1
        elif len(failures) < 3:
            failures.append((line[:80], f"differs at original line {cursor}"))
        cursor += len(parts)
    return ok, cursor, failures


def is_joined_value(value, line, tokens):
    """spec S2.3. True when value is a run of several whole tokens of line, followed by a
    delimiter or by the end of the line. tokens is tokenize(line).

    The run may also start one character into a token: after the '-' that the sign rule
    (S2.2) absorbed into a number, or after the escape letter t, n or r of a token that
    follows a backslash, where the encoder starts an IPv4 address at its first digit."""
    starts = set()
    inner = set()
    position = 0
    previous = None
    for token in tokens:
        starts.add(position)
        text = token.text
        if len(text) > 1 and text[1:2].isdigit():
            if text[0] == "-" or (text[0] in "tnr" and previous is not None and previous.text == "\\"):
                inner.add(position + 1)
        previous = token
        position += len(token.text)
    ends = {start for start in starts if start} | {position}
    starts |= inner
    at = line.find(value)
    while at != -1:
        end = at + len(value)
        if at in starts and end in ends and (end == len(line) or line[end] in TOKEN_DELIMITERS):
            return True
        at = line.find(value, at + 1)
    return False


def check_tokenizer(encoded, templates, timezone_offset_minutes, stats=None):
    """Every value of a decoded line must be a token of the line it rebuilds, or a run of
    several of its tokens joined as one value (spec S2.3).

    Returns (values that are tokens or joined runs, values checked, lines checked, lines
    not decoded). A line decode() refuses cannot be checked; it is counted, and the check
    does not pass while any line is uncounted that way. When stats is a dict, its "joined"
    entry receives the number of joined values.
    """
    checked = 0
    ok = 0
    joined = 0
    lines = 0
    refused = 0
    for line in encoded:
        if not line.startswith(LINE_PREFIX):
            # spec S4.1: not an encoded line; it carries no values.
            continue
        rebuilt = decode(line, templates, timezone_offset_minutes=timezone_offset_minutes)
        if rebuilt is None:
            refused += 1
            continue
        split = line[1:].find(",")
        if split == -1:
            # spec S8.2: the template hash alone, a line with no values.
            lines += 1
            continue
        values = line[1 + split + 1 :].split(",")
        segments, timestamps = parse_template(templates[line[1 : 1 + split]])
        tokens = tokenize(rebuilt)
        produced = {t.text for t in tokens}
        # Timestamps are epochs, not tokens of the line, so skip their positions.
        for value in values[timestamps:]:
            checked += 1
            if value in produced:
                ok += 1
            elif is_joined_value(value, rebuilt, tokens):
                ok += 1
                joined += 1
        lines += 1
    if stats is not None:
        stats["joined"] = joined
    return ok, checked, lines, refused


def read_lines(path):
    # bytes decoded as they are: a text-mode read would turn CR LF into LF and a lone CR
    # into a line break, and an encoder keeps the CR of a CR LF inside an event.
    text = path.read_bytes().decode("utf-8")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def main():
    print("Fetching the published sample")
    fetch()

    templates = {}
    for raw in read_lines(CACHE / "otel-sample-templates.json"):
        record = json.loads(raw)
        templates[record["templateHash"]] = record["template"]
    originals = read_lines(CACHE / "otel-sample-200mb.log")
    encoded = read_lines(CACHE / "otel-sample-encoded.log")

    print(f"\n  {len(originals):,} original lines")
    print(f"  {len(encoded):,} encoded lines")
    print(f"  {len(templates):,} templates\n")

    results = []

    # 1. DECODE
    ok, cursor, failures = check_decode(encoded, originals, templates, SAMPLE_TZ_OFFSET_MINUTES)
    passed = ok == len(encoded) and cursor == len(originals)
    results.append(("DECODE      byte-identical reconstruction", f"{ok:,}/{len(encoded):,} lines, {cursor:,}/{len(originals):,} originals", passed))
    for line, why in failures[:3]:
        print(f"    ! {why}: {line}")

    # 2. TEMPLATE ID
    ok = sum(1 for h, t in templates.items() if hash_template(t) == h)
    results.append(("TEMPLATE ID hash_template reproduces published hashes", f"{ok:,}/{len(templates):,}", ok == len(templates)))

    # 3. TOKENIZER: every published value must be a token of its original line.
    stats = {}
    ok, checked, lines, refused = check_tokenizer(encoded[:20000], templates, SAMPLE_TZ_OFFSET_MINUTES, stats)
    detail = f"{ok:,}/{checked:,} values over {lines:,} lines"
    if stats["joined"]:
        detail += f", {stats['joined']:,} of them joined from several tokens"
    if refused:
        detail += f", {refused:,} lines not decoded and not checked"
    results.append(("TOKENIZER   published values are tokens of the line", detail, ok == checked and refused == 0))

    # 4. BACK-REFS: distances stay inside the S4.3 bound and always resolve.
    worst = 0
    bad = 0
    total = 0
    for template in templates.values():
        segments, timestamps = parse_template(template)
        emitted = 0
        for segment in segments:
            if segment[0] != "value":
                continue
            index = segment[1]
            if index == emitted:
                emitted += 1
                continue
            total += 1
            distance = emitted - index
            worst = max(worst, distance)
            if index < 0 or distance >= 10:
                bad += 1
    results.append(("BACK-REFS   distances resolve and stay under 10", f"{total:,} references, widest {worst}, {bad} out of range", bad == 0 and worst < 10))

    print()
    for name, detail, passed in results:
        print(f"  {'pass' if passed else 'FAIL'}  {name}")
        print(f"        {detail}")
    print()
    everything = all(p for _, _, p in results)
    print("=" * 74)
    print("conformant" if everything else "NOT CONFORMANT")
    print("=" * 74)
    return 0 if everything else 1


if __name__ == "__main__":
    raise SystemExit(main())
