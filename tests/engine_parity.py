#!/usr/bin/env python3
"""Compare this reference against the Log10x encoder, on identical input.

    python3 tests/engine_parity.py

Requires docker. Runs the pinned image log10x/pipeline-10x:1.1.5 over a slice of the
published sample, then checks three separate things against its output:

  1. TEMPLATE ID  hash_template reproduces the encoder's template hashes
  2. PATTERN ID   hash_pattern reproduces the encoder's pattern hashes, given the
                  encoder's own pattern strings. The two output files it reads carry the
                  same distinct patterns, so this is one measurement, not two.
  3. SELECTION    how often this reference picks the same symbols as the encoder,
                  which is where the two deliberately differ

Checks 1 and 2 are the identity functions and are expected to agree exactly. Check 3 is
expected to disagree, and it prints the size of the gap and what causes it. See
FORMAT_SPEC.md S3.4 and the "What this does not do" section of README.md.

This regenerates the engine-parity figures quoted in README.md.
"""

import argparse
import csv
import json
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from refimpl import SymbolLibrary, decode, encode, hash_pattern, hash_template  # noqa: E402
from refimpl.library import load as load_library  # noqa: E402

IMAGE = "log10x/pipeline-10x:1.1.5"
SAMPLE = ROOT / "fixtures" / "otel-sample" / "otel-sample-200mb.log"
SAMPLE_TZ_OFFSET_MINUTES = -240


def run_encoder(lines, workdir: Path):
    """Run the pinned image over `lines` and return (templates, rows)."""
    out = workdir / "out"
    out.mkdir(parents=True, exist_ok=True)
    source = workdir / "in.log"
    source.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with source.open("rb") as stdin:
        proc = subprocess.run(
            ["docker", "run", "--rm", "-i",
             "-e", "LOG10X_MCP_RUNTIME_NAME=x", "-e", "TENX_RUNTIME_NAME=x",
             "-v", f"{out}:/tmp/log10x-mcp-pull", IMAGE, "@apps/mcp-file"],
            stdin=stdin, capture_output=True,
        )
    produced = out / "x"
    if not (produced / "templates.json").exists():
        print(proc.stderr.decode()[-2000:], file=sys.stderr)
        raise SystemExit("the encoder produced no templates; is docker running?")

    templates = {}
    for raw in (produced / "templates.json").read_text(encoding="utf-8").splitlines():
        if raw.strip():
            record = json.loads(raw)
            templates[record["templateHash"]] = record["template"]

    rows = []
    for raw in (produced / "encoded.log").read_text(encoding="utf-8").splitlines():
        if ",pattern=," not in raw:
            continue
        head, rest = raw.split(",pattern=,", 1)
        parts = rest.split(",patternHash=,")
        if len(parts) != 2:
            continue
        rows.append({"encoded": head, "pattern": parts[0], "pattern_hash": parts[1]})

    aggregated = produced / "aggregated.csv"
    csv_rows = []
    if aggregated.exists():
        with aggregated.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if row.get("message_pattern") is not None and row.get("tenx_hash") is not None:
                    csv_rows.append((row["message_pattern"], row["tenx_hash"]))
    return templates, rows, csv_rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lines", type=int, default=2000)
    parser.add_argument("--library", type=Path, help="symbol library for the SELECTION check")
    args = parser.parse_args()

    if not SAMPLE.exists():
        raise SystemExit(f"{SAMPLE} is missing. Run tests/conformance.py first to fetch it.")

    with SAMPLE.open(encoding="utf-8") as handle:
        lines = [next(handle).rstrip("\n") for _ in range(args.lines)]

    with tempfile.TemporaryDirectory() as tmp:
        print(f"Running {IMAGE} over {len(lines):,} lines ...", flush=True)
        templates, rows, csv_rows = run_encoder(lines, Path(tmp))
    print(f"  {len(templates):,} templates, {len(rows):,} encoded events\n")

    # 1. TEMPLATE ID
    ok = sum(1 for h, t in templates.items() if hash_template(t) == h)
    print(f"  {'pass' if ok == len(templates) else 'FAIL'}  TEMPLATE ID  {ok:,}/{len(templates):,}")

    # 2. PATTERN ID, given the encoder's own pattern strings
    ok = sum(1 for r in rows if hash_pattern(r["pattern"]) == r["pattern_hash"])
    empty = sum(1 for r in rows if r["pattern"] == "")
    print(f"  {'pass' if ok == len(rows) else 'FAIL'}  PATTERN ID   {ok:,}/{len(rows):,}"
          f"   ({empty} of them the empty pattern)")
    if csv_rows:
        ok2 = sum(1 for p, h in csv_rows if hash_pattern(p) == h)
        print(f"  {'pass' if ok2 == len(csv_rows) else 'FAIL'}  PATTERN ID   {ok2:,}/{len(csv_rows):,}"
              f"   (aggregated.csv, same run: the same {len(set(p for p, _ in csv_rows)):,} distinct patterns)")

    # 3. SELECTION
    if args.library is None:
        print("\n  SELECTION check skipped. Pass --library to run it, for example:")
        print("     python3 tools/extract_library.py --out /tmp/symbols.10x.tar")
        print("     python3 tests/engine_parity.py --library /tmp/symbols.10x.tar")
        return 0

    print(f"\n  loading {args.library} ...", flush=True)
    library = load_library(args.library)
    print(f"  {len(library):,} token identities\n")

    comparable = agree = 0
    causes = Counter()
    for row in rows:
        original = decode(row["encoded"], templates, timezone_offset_minutes=SAMPLE_TZ_OFFSET_MINUTES)
        if original is None or "\n" in original:
            continue
        try:
            message = json.loads(original).get("log", "")
        except (json.JSONDecodeError, AttributeError):
            continue
        if not message:
            continue
        comparable += 1
        mine = encode(message, library).pattern
        if mine == row["pattern"]:
            agree += 1
        else:
            engine_tokens = set(row["pattern"].split("_")) - {""}
            mine_tokens = set(mine.split("_")) - {""}
            causes["engine saw a symbol this reference did not"] += len(engine_tokens - mine_tokens) > 0
            causes["this reference saw a symbol the engine did not"] += len(mine_tokens - engine_tokens) > 0

    share = (100 * agree / comparable) if comparable else 0
    print(f"  SELECTION    {agree:,}/{comparable:,} patterns identical  ({share:.1f}%)")
    print("               expected to disagree. The reference uses plain membership;")
    print("               the encoder also matches compound symbols and arbitrates origins.")
    for cause, count in causes.most_common():
        print(f"                 {count:,} lines where {cause}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
