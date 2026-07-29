#!/usr/bin/env python3
"""The four properties this repository exists to let you check, run offline.

    python3 tests/demo.py

Nothing is downloaded and nothing is installed. The library used is the small fixture in
fixtures/, which stands in for a library compiled from the public OpenTelemetry demo
images. Pass --library to point at a real one.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from refimpl import decode, encode  # noqa: E402
from refimpl.library import load as load_library  # noqa: E402

PASS = "pass"
FAIL = "FAIL"


def banner(n, title):
    print(f"\n{'=' * 74}\n{n}. {title}\n{'=' * 74}")


def load_sample():
    return [json.loads(l) for l in (ROOT / "fixtures" / "sample.jsonl").read_text().splitlines() if l.strip()]


def demo_deterministic(library, sample):
    banner(1, "The same line gets the same pattern ID on every run")
    line = sample[0]["message"]
    ids = {encode(line, library).pattern_hash for _ in range(1000)}
    ok = len(ids) == 1
    print(f"   line     : {line}")
    print(f"   1000 encodes produced {len(ids)} distinct pattern hash(es): {sorted(ids)}")
    print(f"   -> {PASS if ok else FAIL}")
    return ok


def demo_two_processes(library_path, sample):
    banner(2, "Two separate processes, same library, produce the same ID")
    line = sample[0]["message"]
    script = (
        "import sys,json;sys.path.insert(0,%r);"
        "from refimpl import encode;from refimpl.library import load;"
        "lib=load(%r);r=encode(sys.stdin.read(),lib);"
        "print(json.dumps({'t':r.template_hash,'p':r.pattern_hash}))"
        % (str(ROOT), str(library_path))
    )
    out = []
    for n in (1, 2):
        proc = subprocess.run(
            [sys.executable, "-c", script], input=line, capture_output=True, text=True
        )
        if proc.returncode != 0:
            print(f"   process {n} failed:\n{proc.stderr}")
            return False
        out.append(json.loads(proc.stdout))
        print(f"   process {n} (pid differs, no shared state): {out[-1]}")
    ok = out[0] == out[1]
    print(f"   -> {PASS if ok else FAIL}")
    return ok


def demo_round_trip(library, sample):
    banner(3, "An encoded line decodes back to the original, byte for byte")
    ok = True
    for record in sample:
        line = record["line"]
        result = encode(line, library)
        back = decode(result.line, {result.template_hash: result.template})
        if back != line:
            ok = False
            print(f"   {FAIL} {line[:70]}\n        got {str(back)[:70]}")
    print(f"   {len(sample)} lines encoded and decoded")
    print(f"   every byte identical: {PASS if ok else FAIL}")
    print("\n   worked example:")
    example = encode(sample[0]["line"], library)
    print(f"     original : {sample[0]['line'][:100]}")
    print(f"     template : {example.template[:100]}")
    print(f"     encoded  : {example.line[:100]}")
    print(f"     values   : {example.values[:6]}{' ...' if len(example.values) > 6 else ''}")
    return ok


def demo_coverage_boundary(library, sample, default_library):
    banner(4, "Vocabulary the library does not hold yields an EMPTY pattern")
    print("   A wrong name would be worse than no name, so no name is what comes back.\n")
    compiled = [r for r in sample if r["engine_pattern"] is not None]
    invented = [r for r in sample if r["engine_pattern"] is None]

    print("   lines from code that IS in the library:")
    named = 0
    for record in compiled[:4]:
        result = encode(record["message"], library)
        named += bool(result.pattern)
        print(f"     pattern={result.pattern!r:44} hash={result.pattern_hash!r}")

    print("\n   lines from code that is NOT in the library:")
    all_empty = True
    for record in invented:
        result = encode(record["message"], library)
        all_empty &= result.pattern == "" and result.pattern_hash == ""
        print(f"     pattern={result.pattern!r:44} hash={result.pattern_hash!r}")
        print(f"       from: {record['message'][:66]}")

    print()
    if not default_library:
        # A library other than the shipped fixture covers a different vocabulary, so the
        # outcome here is a reading of THAT library, not a verdict on this code.
        if all_empty:
            print("   observed: every uncompiled line came back empty against this library.")
        else:
            print("   observed: some uncompiled lines picked up a pattern from this library.")
            print("   That is the expected reading, not a defect. A large general library holds")
            print("   common English words and generic identifiers, so an unrelated line can")
            print("   match a few of them. Emptiness proves the vocabulary is absent; a")
            print("   non-empty pattern does not prove the emitting code was compiled.")
        print("\n   Run without --library to see the property checked against a library")
        print("   scoped to the code it was compiled from. See FORMAT_SPEC.md S5.4.")
        return True

    ok = all_empty and named > 0
    print(f"   every uncompiled line came back empty, and compiled lines did not:"
          f" {PASS if ok else FAIL}")
    print("\n   The boundary is a property of what was compiled, not a detector. A larger")
    print("   library holds common words, so an unrelated line can pick up a short, low")
    print("   value pattern from them, which --library will show. See FORMAT_SPEC.md S5.4.")
    return ok


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    default_library = ROOT / "fixtures" / "library.jsonl"
    parser.add_argument("--library", type=Path, default=default_library)
    args = parser.parse_args()
    is_default = args.library == default_library

    sample = load_sample()
    library = load_library(args.library)
    print(f"library : {args.library}  ({len(library):,} token identities)")
    print(f"sample  : {len(sample)} lines")

    results = [
        demo_deterministic(library, sample),
        demo_two_processes(args.library, sample),
        demo_round_trip(library, sample),
        demo_coverage_boundary(library, sample, is_default),
    ]

    print(f"\n{'=' * 74}")
    if is_default:
        print(f"{sum(results)}/{len(results)} properties hold")
    else:
        # Property 4 reads the supplied library rather than checking this code, so it is
        # reported above and deliberately not counted as a pass here.
        print(f"{sum(results[:3])}/3 checked properties hold")
        print("property 4 was reported against the supplied library, not scored")
    print(f"{'=' * 74}")
    if is_default:
        print("\nThat ran against the small fixture library. To check the reference against")
        print("Log10x's own published data, 197,430 real log lines:")
    else:
        print(f"\nThat ran against {args.library}. To check the reference against")
        print("Log10x's own published data, 197,430 real log lines:")
    print("    python3 tests/conformance.py")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
