"""The two hash functions and the two renderings the format depends on.

Both are standard, published, non-cryptographic hashes. They are reimplemented here in
pure Python so that this package has no dependencies and so that the exact byte-level
input to each one is visible in the source rather than hidden behind a binding.

  farm_na64   FarmHash64 "Na" variant, used for token and template identity.
              Input is the UTF-16LE bytes of the string.
              NOTE the naming trap: upstream farmhash's Hash64 is NOT this function for
              inputs over 32 bytes, where it dispatches to the Uo and Xo variants. The
              function reimplemented here is farmhashna::Hash64, which upstream exposes
              as Fingerprint64. A template's UTF-16LE bytes are almost always over 32,
              so reaching for Hash64 gives wrong answers on essentially every template.
  xxh64       xxHash64, used for pattern identity. Input is the UTF-8 bytes.

Reference implementations:
  FarmHash  https://github.com/google/farmhash          (farmhash.cc, farmhashna::Hash64,
                                                         exposed as Fingerprint64)
  xxHash    https://github.com/Cyan4973/xxHash          (XXH64)
"""

import struct

MASK64 = (1 << 64) - 1

# ---------------------------------------------------------------------------
# FarmHash64, "Na" variant
# ---------------------------------------------------------------------------

_K0 = 0xC3A5C85C97CB3127
_K1 = 0xB492B66FBE98F273
_K2 = 0x9AE16A3B2F90404F


def _u64(b, i):
    return struct.unpack_from("<Q", b, i)[0]


def _u32(b, i):
    return struct.unpack_from("<I", b, i)[0]


def _rot(v, r):
    return v if r == 0 else ((v >> r) | (v << (64 - r))) & MASK64


def _shift_mix(v):
    return v ^ (v >> 47)


def _hash_len16(u, v, mul=0x9DDFEA08EB382D69):
    a = _shift_mix(((u ^ v) * mul) & MASK64)
    b = _shift_mix(((v ^ a) * mul) & MASK64)
    return (b * mul) & MASK64


def _weak_hash32(w, x, y, z, a, b):
    a = (a + w) & MASK64
    b = _rot((b + a + z) & MASK64, 21)
    c = a
    a = (a + x + y) & MASK64
    b = (b + _rot(a, 44)) & MASK64
    return ((a + z) & MASK64, (b + c) & MASK64)


def _weak_hash32_s(s, i, a, b):
    return _weak_hash32(_u64(s, i), _u64(s, i + 8), _u64(s, i + 16), _u64(s, i + 24), a, b)


def farm_na64(data: bytes) -> int:
    """FarmHash64 Na. Returns an UNSIGNED 64-bit integer."""
    n = len(data)

    if n <= 32:
        if n <= 16:
            if n >= 8:
                mul = (_K2 + 2 * n) & MASK64
                a = (_u64(data, 0) + _K2) & MASK64
                b = _u64(data, n - 8)
                c = (_rot(b, 37) * mul + a) & MASK64
                d = ((_rot(a, 25) + b) * mul) & MASK64
                return _hash_len16(c, d, mul)
            if n >= 4:
                mul = (_K2 + 2 * n) & MASK64
                return _hash_len16((n + (_u32(data, 0) << 3)) & MASK64, _u32(data, n - 4), mul)
            if n > 0:
                y = (data[0] + (data[n >> 1] << 8)) & MASK64
                z = (n + (data[n - 1] << 2)) & MASK64
                return (_shift_mix(((y * _K2) ^ (z * _K0)) & MASK64) * _K2) & MASK64
            return _K2
        mul = (_K2 + 2 * n) & MASK64
        a = (_u64(data, 0) * _K1) & MASK64
        b = _u64(data, 8)
        c = (_u64(data, n - 8) * mul) & MASK64
        d = (_u64(data, n - 16) * _K2) & MASK64
        return _hash_len16(
            (_rot((a + b) & MASK64, 43) + _rot(c, 30) + d) & MASK64,
            (a + _rot((b + _K2) & MASK64, 18) + c) & MASK64,
            mul,
        )

    if n <= 64:
        mul = (_K2 + 2 * n) & MASK64
        a = (_u64(data, 0) * _K2) & MASK64
        b = _u64(data, 8)
        c = (_u64(data, n - 8) * mul) & MASK64
        d = (_u64(data, n - 16) * _K2) & MASK64
        y = (_rot((a + b) & MASK64, 43) + _rot(c, 30) + d) & MASK64
        z = _hash_len16(y, (a + _rot((b + _K2) & MASK64, 18) + c) & MASK64, mul)
        e = (_u64(data, 16) * mul) & MASK64
        f = _u64(data, 24)
        g = ((y + _u64(data, n - 32)) * mul) & MASK64
        h = ((z + _u64(data, n - 24)) * mul) & MASK64
        return _hash_len16(
            (_rot((e + f) & MASK64, 43) + _rot(g, 30) + h) & MASK64,
            (e + _rot((f + a) & MASK64, 18) + g) & MASK64,
            mul,
        )

    # n > 64
    x = 81
    y = (81 * _K1 + 113) & MASK64
    z = (_shift_mix((y * _K2 + 113) & MASK64) * _K2) & MASK64
    v = (0, 0)
    w = (0, 0)
    x = (x * _K2 + _u64(data, 0)) & MASK64
    end = ((n - 1) // 64) * 64
    i = 0
    while True:
        x = (_rot((x + y + v[0] + _u64(data, i + 8)) & MASK64, 37) * _K1) & MASK64
        y = (_rot((y + v[1] + _u64(data, i + 48)) & MASK64, 42) * _K1) & MASK64
        x ^= w[1]
        y = (y + v[0] + _u64(data, i + 40)) & MASK64
        z = (_rot((z + w[0]) & MASK64, 33) * _K1) & MASK64
        v = _weak_hash32_s(data, i, (v[1] * _K1) & MASK64, (x + w[0]) & MASK64)
        w = _weak_hash32_s(data, i + 32, (z + w[1]) & MASK64, (y + _u64(data, i + 16)) & MASK64)
        z, x = x, z
        i += 64
        if i == end:
            break

    mul = (_K1 + ((z & 0xFF) << 1)) & MASK64
    i = n - 64
    w = ((w[0] + ((n - 1) & 63)) & MASK64, w[1])
    v = ((v[0] + w[0]) & MASK64, v[1])
    w = ((w[0] + v[0]) & MASK64, w[1])
    x = (_rot((x + y + v[0] + _u64(data, i + 8)) & MASK64, 37) * mul) & MASK64
    y = (_rot((y + v[1] + _u64(data, i + 48)) & MASK64, 42) * mul) & MASK64
    x ^= (w[1] * 9) & MASK64
    y = (y + (v[0] * 9) + _u64(data, i + 40)) & MASK64
    z = (_rot((z + w[0]) & MASK64, 33) * mul) & MASK64
    v = _weak_hash32_s(data, i, (v[1] * mul) & MASK64, (x + w[0]) & MASK64)
    w = _weak_hash32_s(data, i + 32, (z + w[1]) & MASK64, (y + _u64(data, i + 16)) & MASK64)
    z, x = x, z
    return _hash_len16(
        (_hash_len16(v[0], w[0], mul) + ((_shift_mix(y) * _K0) & MASK64) + z) & MASK64,
        (_hash_len16(v[1], w[1], mul) + x) & MASK64,
        mul,
    )


# ---------------------------------------------------------------------------
# xxHash64
# ---------------------------------------------------------------------------

_P1 = 0x9E3779B185EBCA87
_P2 = 0xC2B2AE3D27D4EB4F
_P3 = 0x165667B19E3779F9
_P4 = 0x85EBCA77C2B2AE63
_P5 = 0x27D4EB2F165667C5


def _rotl(v, r):
    """Rotate LEFT. FarmHash above rotates right; xxHash rotates left."""
    return ((v << r) | (v >> (64 - r))) & MASK64


def _xxh_round(acc, inp):
    acc = (acc + (inp * _P2)) & MASK64
    acc = _rotl(acc, 31)
    return (acc * _P1) & MASK64


def _xxh_merge(acc, val):
    acc ^= _xxh_round(0, val)
    return ((acc * _P1) + _P4) & MASK64


def xxh64(data: bytes, seed: int = 0) -> int:
    """xxHash64. Returns an UNSIGNED 64-bit integer."""
    n = len(data)
    if n >= 32:
        v1 = (seed + _P1 + _P2) & MASK64
        v2 = (seed + _P2) & MASK64
        v3 = seed & MASK64
        v4 = (seed - _P1) & MASK64
        i = 0
        while i + 32 <= n:
            v1 = _xxh_round(v1, _u64(data, i))
            v2 = _xxh_round(v2, _u64(data, i + 8))
            v3 = _xxh_round(v3, _u64(data, i + 16))
            v4 = _xxh_round(v4, _u64(data, i + 24))
            i += 32
        acc = (_rotl(v1, 1) + _rotl(v2, 7) + _rotl(v3, 12) + _rotl(v4, 18)) & MASK64
        acc = _xxh_merge(acc, v1)
        acc = _xxh_merge(acc, v2)
        acc = _xxh_merge(acc, v3)
        acc = _xxh_merge(acc, v4)
    else:
        acc = (seed + _P5) & MASK64
        i = 0
    acc = (acc + n) & MASK64

    while i + 8 <= n:
        acc ^= _xxh_round(0, _u64(data, i))
        acc = ((_rotl(acc, 27) * _P1) + _P4) & MASK64
        i += 8
    if i + 4 <= n:
        acc ^= (_u32(data, i) * _P1) & MASK64
        acc = ((_rotl(acc, 23) * _P2) + _P3) & MASK64
        i += 4
    while i < n:
        acc ^= (data[i] * _P5) & MASK64
        acc = (_rotl(acc, 11) * _P1) & MASK64
        i += 1

    acc ^= acc >> 33
    acc = (acc * _P2) & MASK64
    acc ^= acc >> 29
    acc = (acc * _P3) & MASK64
    acc ^= acc >> 32
    return acc


# ---------------------------------------------------------------------------
# The two renderings
# ---------------------------------------------------------------------------

# 84 characters. Every character that would need quoting inside JSON, CSV, a shell
# word or a URL query is absent: " % ' ( ) , = \ ` and the space-adjacent controls.
# '-' is NOT a member; it is reserved as the sign prefix.
BASE84_ALPHABET = (
    " !#$&*+./0123456789:;<>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[]^_abcdefghijklmnopqrstuvwxyz{|}"
)
BASE84 = len(BASE84_ALPHABET)
_BASE84_INDEX = {c: i for i, c in enumerate(BASE84_ALPHABET)}


def to_signed64(u: int) -> int:
    """Reinterpret an unsigned 64-bit value as a two's-complement signed 64-bit value."""
    return u - (1 << 64) if u >> 63 else u


def base84_encode(value: int) -> str:
    """Render a SIGNED 64-bit value. Negative values take a leading '-'."""
    negative = value < 0
    v = -value if negative else value
    out = []
    while True:
        out.append(BASE84_ALPHABET[v % BASE84])
        v //= BASE84
        if v == 0:
            break
    return ("-" if negative else "") + "".join(reversed(out))


def base84_decode(text: str) -> int:
    """Inverse of base84_encode. Returns a signed 64-bit value."""
    if not text:
        raise ValueError("empty base-84 string")
    negative = text[0] == "-"
    body = text[1:] if negative else text
    if not body:
        raise ValueError("base-84 string is a bare sign")
    v = 0
    for c in body:
        try:
            v = v * BASE84 + _BASE84_INDEX[c]
        except KeyError:
            raise ValueError(f"character {c!r} is not in the base-84 alphabet") from None
    return -v if negative else v
