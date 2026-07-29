"""Reading a published symbol library.

This module reads a library and nothing else. It does not build one, and it contains no
scanner of any kind. Building a library is a separate ahead-of-time compile over source
trees, binaries and container images; that step is not part of this reference and is not
described here.

The on-disk form is JSON Lines, one line per origin section (spec S3.3):

    {"h":"<base-84 origin hash>",
     "n":"<origin name, e.g. Server.java>",
     "v":1.0,
     "i":<section index>,
     "c":<section count>,
     "k":"x(<base-84>)l(<base-84>,<base-84>)..."}

`k` is a run of groups. Each group is a single-character source-context tag, then a
parenthesised comma-separated list of base-84 token hashes. A hash prefixed with `%=`
is a format token. One origin too large for a single line is split into `c` sections
carrying the same `h` and `n`, with `i` running 0..c-1; `i` and `c` are identity
bookkeeping and take no part in matching.
"""

import json
import re
import tarfile
from pathlib import Path
from typing import Iterable, Optional

from .codec import SymbolLibrary
from .hashes import base84_decode

#: Source-context tags that may introduce a group in the `k` field.
SOURCE_CONTEXT_TAGS = {
    "x": "executable symbol",
    "t": "plain text",
    "p": "package",
    "c": "class",
    "i": "interface",
    "e": "enum",
    "d": "method declaration",
    "s": "variable assignment",
    "v": "method invocation",
    "o": "annotation invocation",
    "g": "logger method invocation",
    "a": "logging method variable assignment",
    "l": "logging method invocation",
}

_GROUP = re.compile(r"([a-z])\(([^)]*)\)")


def _iter_hashes(k: str) -> Iterable[int]:
    for match in _GROUP.finditer(k or ""):
        body = match.group(2)
        if not body:
            continue
        for item in body.split(","):
            if item.startswith("%="):
                item = item[2:]
            if not item:
                continue
            try:
                yield base84_decode(item)
            except ValueError:
                # A token hash this reader cannot parse is skipped rather than guessed at.
                continue


def load_jsonl(path, limit: Optional[int] = None) -> SymbolLibrary:
    """Load a library from an uncompressed `symbols.10x.json` (JSON Lines)."""
    library = SymbolLibrary()
    with open(path, "r", encoding="utf-8") as handle:
        for count, line in enumerate(handle):
            if limit is not None and count >= limit:
                break
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            origin = record.get("n")
            for value in _iter_hashes(record.get("k", "")):
                library.add(value, origin)
    return library


def load_tar(path, limit: Optional[int] = None) -> SymbolLibrary:
    """Load a library from a `.10x.tar` archive, reading only its JSON member.

    The archive also holds a protobuf reverse index and a manifest. Neither is read
    here: the JSON member alone carries everything a reader needs, and the reverse
    index is a lookup accelerator for the same content.
    """
    library = SymbolLibrary()
    with tarfile.open(path, "r") as archive:
        member = next(
            (m for m in archive.getmembers() if m.name.endswith(".json") and "manifest" not in m.name),
            None,
        )
        if member is None:
            raise ValueError(f"no symbol JSON member found in {path}")
        handle = archive.extractfile(member)
        if handle is None:
            raise ValueError(f"could not read {member.name} from {path}")
        for count, raw in enumerate(handle):
            if limit is not None and count >= limit:
                break
            raw = raw.strip()
            if not raw:
                continue
            try:
                record = json.loads(raw)
            except json.JSONDecodeError:
                continue
            origin = record.get("n")
            for value in _iter_hashes(record.get("k", "")):
                library.add(value, origin)
    return library


def load(path, limit: Optional[int] = None) -> SymbolLibrary:
    """Load a library from either form, chosen by extension."""
    path = Path(path)
    if path.suffix == ".tar":
        return load_tar(path, limit)
    return load_jsonl(path, limit)
