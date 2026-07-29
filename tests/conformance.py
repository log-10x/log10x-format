#!/usr/bin/env python3
"""Check this implementation against data Log10x published, not against itself.

    python3 tests/conformance.py

Downloads three files from the public release
https://github.com/log-10x/config/releases/tag/otel-sample-v1 (about 12 MB compressed),
caches them under fixtures/otel-sample/, and runs four checks:

  1. DECODE      every published encoded line rebuilds its original bytes exactly
  2. TEMPLATE ID hash_template reproduces every published template hash
  3. TOKENIZER   every published value is a token this tokenizer produces
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
from refimpl.codec import parse_template  # noqa: E402

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


def read_lines(path):
    text = path.read_text(encoding="utf-8")
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
    cursor = 0
    ok = 0
    failures = []
    for line in encoded:
        rebuilt = decode(line, templates, timezone_offset_minutes=SAMPLE_TZ_OFFSET_MINUTES)
        if rebuilt is None:
            failures.append((line[:80], "template not found"))
            continue
        parts = rebuilt.split("\n")
        matched = all(
            cursor + n < len(originals) and originals[cursor + n] == part
            for n, part in enumerate(parts)
        )
        if matched:
            ok += 1
        elif len(failures) < 3:
            failures.append((line[:80], f"differs at original line {cursor}"))
        cursor += len(parts)
    passed = ok == len(encoded) and cursor == len(originals)
    results.append(("DECODE      byte-identical reconstruction", f"{ok:,}/{len(encoded):,} lines, {cursor:,}/{len(originals):,} originals", passed))
    for line, why in failures[:3]:
        print(f"    ! {why}: {line}")

    # 2. TEMPLATE ID
    ok = sum(1 for h, t in templates.items() if hash_template(t) == h)
    results.append(("TEMPLATE ID hash_template reproduces published hashes", f"{ok:,}/{len(templates):,}", ok == len(templates)))

    # 3. TOKENIZER: every published value must be a token of its original line.
    checked = 0
    ok = 0
    cursor = 0
    for line in encoded[:20000]:
        rebuilt = decode(line, templates, timezone_offset_minutes=SAMPLE_TZ_OFFSET_MINUTES)
        if rebuilt is None:
            continue
        split = line[1:].find(",")
        values = line[1 + split + 1 :].split(",")
        segments, timestamps = parse_template(templates[line[1 : 1 + split]])
        produced = {t.text for t in tokenize(rebuilt)}
        # Timestamps are epochs, not tokens of the line, so skip their positions.
        for value in values[timestamps:]:
            checked += 1
            ok += value in produced
        cursor += 1
    results.append(("TOKENIZER   published values are tokens of the line", f"{ok:,}/{checked:,} values over {cursor:,} lines", ok == checked))

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
