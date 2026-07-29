"""Reference implementation of the published pattern-ID format. See FORMAT_SPEC.md."""
from .codec import (
    EMPTY_PATTERN_HASH_TOTAL,
    Encoded,
    SymbolLibrary,
    decode,
    encode,
    hash_pattern,
    hash_template,
    token_hash,
    tokenize,
)
from .library import load as load_library

__all__ = [
    "EMPTY_PATTERN_HASH_TOTAL", "Encoded", "SymbolLibrary", "decode", "encode",
    "hash_pattern", "hash_template", "token_hash", "tokenize", "load_library",
]
