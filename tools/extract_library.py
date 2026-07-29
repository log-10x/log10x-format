#!/usr/bin/env python3
"""Pull the default symbol library out of the public encoder image.

    python3 tools/extract_library.py --image log10x/pipeline-10x:1.1.5 --out /tmp/symbols.10x.tar

The image ships the library it was built with. This copies that file out; it does not
run the encoder and it does not build anything. Requires docker on PATH.
"""

import argparse
import subprocess
import sys
from pathlib import Path

IMAGE_PATH = "/etc/tenx/symbols"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="log10x/pipeline-10x:1.1.5")
    parser.add_argument("--out", type=Path, default=Path("symbols.10x.tar"))
    args = parser.parse_args()

    listing = subprocess.run(
        ["docker", "run", "--rm", "--entrypoint", "ls", args.image, IMAGE_PATH],
        capture_output=True, text=True,
    )
    if listing.returncode != 0:
        print(f"could not list {IMAGE_PATH} in {args.image}:\n{listing.stderr}", file=sys.stderr)
        return 1
    names = [n for n in listing.stdout.split() if n.endswith(".10x.tar")]
    if not names:
        print(f"no .10x.tar found in {IMAGE_PATH} of {args.image}", file=sys.stderr)
        return 1

    created = subprocess.run(["docker", "create", args.image], capture_output=True, text=True)
    if created.returncode != 0:
        print(created.stderr, file=sys.stderr)
        return 1
    container = created.stdout.strip()
    try:
        copied = subprocess.run(
            ["docker", "cp", f"{container}:{IMAGE_PATH}/{names[0]}", str(args.out)],
            capture_output=True, text=True,
        )
        if copied.returncode != 0:
            print(copied.stderr, file=sys.stderr)
            return 1
    finally:
        subprocess.run(["docker", "rm", container], capture_output=True)

    print(f"wrote {args.out} ({args.out.stat().st_size / 1e6:.0f} MB) from {args.image}")
    print(f"\n    python3 tests/demo.py --library {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
