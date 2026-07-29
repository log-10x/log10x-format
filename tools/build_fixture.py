#!/usr/bin/env python3
"""Filter an existing symbol library down to the fixture that ships with this repository.

This is a FILTER, not a compiler. It reads a library that already exists, keeps the token
identities the sample lines in fixtures/sample.jsonl need, and writes them out in the same
on-disk format. It reads no source code, no binaries and no container images, and it
computes no token identity that was not already in the input library.

The reason it exists: the full default library is about 100 MB, too large to commit, and
the demo has to run offline.

Run it only when the sample lines change:

    python3 tools/build_fixture.py --library /path/to/tenx-symbols-<version>.10x.tar

Every origin name it writes comes from the public open-source container images the input
library was compiled from; no private code is involved.
"""

import argparse
import json
import re
import sys
import tarfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from refimpl.codec import tokenize, token_hash  # noqa: E402
from refimpl.hashes import base84_decode, base84_encode  # noqa: E402

GROUP = re.compile(r"([a-z])\(([^)]*)\)")


def wanted_hashes(sample_path: Path) -> set:
    """Token hashes needed by the sample's COMPILED lines only.

    Lines marked as invented are deliberately excluded. The fixture stands in for a
    library compiled from the OpenTelemetry demo images and nothing else, so a line
    from code that was never compiled into it has to come back with an empty pattern.
    Including the invented lines here would quietly compile them in and destroy the
    one property the fixture exists to show.
    """
    wanted = set()
    for raw in sample_path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        record = json.loads(raw)
        if record.get("engine_pattern") is None:
            continue
        for text in (record["line"], record.get("message", "")):
            for token in tokenize(text):
                if not token.is_delimiter and token.text and not token.text[0].isdigit():
                    wanted.add(token_hash(token.text))
    return wanted


def scan(library_path: Path, wanted: set):
    """Yield (origin_name, context_tag, hash) for every wanted hash found."""
    found = []
    if library_path.suffix == ".tar":
        archive = tarfile.open(library_path, "r")
        member = next(
            m for m in archive.getmembers()
            if m.name.endswith(".json") and "manifest" not in m.name
        )
        stream = archive.extractfile(member)
        lines = (b.decode("utf-8", "replace") for b in stream)
    else:
        lines = open(library_path, "r", encoding="utf-8")

    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            record = json.loads(raw)
        except json.JSONDecodeError:
            continue
        origin = record.get("n") or "unknown"
        for match in GROUP.finditer(record.get("k", "")):
            tag, body = match.group(1), match.group(2)
            for item in body.split(","):
                if item.startswith("%="):
                    item = item[2:]
                if not item:
                    continue
                try:
                    value = base84_decode(item)
                except ValueError:
                    continue
                if value in wanted:
                    found.append((origin, tag, value))
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", required=True, type=Path)
    parser.add_argument("--sample", type=Path, default=Path("fixtures/sample.jsonl"))
    parser.add_argument("--out", type=Path, default=Path("fixtures/library.jsonl"))
    args = parser.parse_args()

    wanted = wanted_hashes(args.sample)
    print(f"sample needs {len(wanted):,} distinct token hashes")

    found = scan(args.library, wanted)
    print(f"found {len(found):,} matches in the library")

    # A token hash usually appears in many origins. The reference decides symbol-vs-value
    # by membership alone, so the fixture keeps one origin per hash to stay small. A real
    # library lists every origin; see FORMAT_SPEC.md S3.4.
    first_origin = {}
    for origin, tag, value in found:
        first_origin.setdefault(value, (origin, tag))

    by_origin = {}
    for value, (origin, tag) in first_origin.items():
        by_origin.setdefault((origin, tag), [])
        by_origin[(origin, tag)].append(value)

    with args.out.open("w", encoding="utf-8") as handle:
        for (origin, tag), values in sorted(by_origin.items(), key=lambda kv: (kv[0][0], kv[0][1])):
            keys = "".join(f"{tag}({base84_encode(v)})" for v in sorted(values))
            handle.write(
                json.dumps(
                    {"h": base84_encode(token_hash(origin)), "n": origin,
                     "v": 1.0, "i": -1, "c": 1, "k": keys},
                    ensure_ascii=False,
                )
                + "\n"
            )
    covered = len({v for _, _, v in found})
    print(f"wrote {args.out} : {len(by_origin):,} origin lines, {covered:,} distinct hashes")
    print(f"coverage of sample vocabulary: {covered}/{len(wanted)} ({100*covered/len(wanted):.1f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
