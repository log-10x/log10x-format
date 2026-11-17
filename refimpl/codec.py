"""Reference encoder and decoder for the published pattern-ID format.

Deliberately naive and readable. See FORMAT_SPEC.md for the normative rules; every
rule cited below as "spec S<n>" is a section of that document.

The chain is:

    log line ──tokenize──> tokens ──library membership──> symbol | value
                                          │
                     ┌────────────────────┴────────────────────┐
                     │                                         │
              template + values                        symbol skeleton
                     │                                         │
             template hash (base-84)                   pattern (joined)
                     │                                         │
             ~hash,v1,v2,...                       pattern hash (base64url)

Two identities come out of one line, and they answer different questions:

  TEMPLATE HASH names the exact shape of this line. It is the join key that ties an
  encoded line back to the template needed to rebuild it.

  PATTERN HASH names the logging statement the line came from. Several templates
  collapse onto one pattern, so this is the identity that survives a shape change and
  the one a budget or a routing rule keys on.
"""

import base64
import re
import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set

from .hashes import base84_encode, farm_na64, to_signed64, xxh64

# --- spec S2: the token model ------------------------------------------------

#: Characters that terminate a token and are themselves emitted as tokens.
TOKEN_DELIMITERS = frozenset('<>|. ][:-+/*=\\,{}_();\'"$\t\n\r@%')

VAR_PLACEHOLDER = "$"
VAR_ESCAPE = "/"
TIMESTAMP_OPEN = "("
TIMESTAMP_CLOSE = ")"
LINE_PREFIX = "~"
VALUE_DELIMITER = ","

#: spec S4.3. A back-reference is only considered while fewer than this many fresh
#: values have been emitted for the line. A repeat after that is written out in full.
#: This bound is what keeps a back-reference distance to a single digit.
MAX_BACKREFERENCE_SLOTS = 10

#: spec S5.3. The separator used to join symbol tokens into the pattern string.
PATTERN_JOIN = "_"


# --- tokenizing --------------------------------------------------------------


@dataclass
class Token:
    text: str
    is_delimiter: bool
    #: spec S2.2. True when the token is the literal "-1", which stays in the template
    #: as text and emits no value.
    is_minus_one: bool = False


def _is_ascii_digits(text: str) -> bool:
    """spec S2.2. Numeric-ness for the sign rule is ASCII 0-9 only.

    Deliberately not str.isdigit(), which is true for other Unicode digit characters.
    The symbol veto in S3.2 does use the wider test; the two are not the same check.
    """
    return bool(text) and all("0" <= c <= "9" for c in text)


def tokenize(line: str, delimiters=TOKEN_DELIMITERS) -> List[Token]:
    """spec S2. Split a line into delimiter tokens and the runs between them.

    A delimiter is always its own single-character token; everything between two
    delimiters is one token. Nothing is discarded, so the concatenation of every
    token's text is the original line.

    Two refinements follow S2.2. A '-' immediately before an all-digit run is absorbed
    into it, so a negative number is one token and no delimiter token is emitted for the
    sign. A token that is then exactly "-1" is marked, because it stays in the template
    literally instead of becoming a value.
    """
    raw: List[Token] = []
    buf: List[str] = []
    for ch in line:
        if ch in delimiters:
            if buf:
                raw.append(Token("".join(buf), False))
                buf = []
            raw.append(Token(ch, True))
        else:
            buf.append(ch)
    if buf:
        raw.append(Token("".join(buf), False))

    tokens: List[Token] = []
    i = 0
    while i < len(raw):
        token = raw[i]
        if (
            token.is_delimiter
            and token.text == "-"
            and i + 1 < len(raw)
            and not raw[i + 1].is_delimiter
            and _is_ascii_digits(raw[i + 1].text)
        ):
            text = "-" + raw[i + 1].text
            tokens.append(Token(text, False, is_minus_one=(text == "-1")))
            i += 2
            continue
        tokens.append(token)
        i += 1
    return tokens


def token_hash(text: str) -> int:
    """spec S3.1. The 64-bit identity of a token: FarmHash64-Na over its UTF-16LE bytes."""
    return to_signed64(farm_na64(text.encode("utf-16-le")))


# --- spec S3: the symbol library ---------------------------------------------


class SymbolLibrary:
    """A set of token hashes, plus the origin each hash was seen in.

    This reads a library; it never builds one. Building a library is a compile step
    over source, binaries and container images and is out of scope here, by design.
    """

    def __init__(self) -> None:
        self._hashes: Set[int] = set()
        self._origins: Dict[int, List[str]] = {}

    def __len__(self) -> int:
        return len(self._hashes)

    def add(self, hash_value: int, origin: Optional[str] = None) -> None:
        self._hashes.add(hash_value)
        if origin is not None:
            self._origins.setdefault(hash_value, [])
            if origin not in self._origins[hash_value]:
                self._origins[hash_value].append(origin)

    def contains(self, hash_value: int) -> bool:
        return hash_value in self._hashes

    def origins_of(self, hash_value: int) -> Sequence[str]:
        return self._origins.get(hash_value, ())

    def is_symbol(self, token: Token) -> bool:
        """spec S3.2. A token is a symbol when the library holds its hash.

        The leading-digit veto keeps a numeric run from ever being a symbol, so a
        number that happens to collide with a compiled token is still treated as a
        runtime value.
        """
        if token.is_delimiter or not token.text:
            return False
        if token.text[0].isdigit():
            return False
        return self.contains(token_hash(token.text))


# --- spec S4: encoding -------------------------------------------------------


@dataclass
class Encoded:
    """Everything one line produces."""

    template: str
    template_hash: str
    values: List[str]
    pattern: str
    pattern_hash: str
    symbols: List[str] = field(default_factory=list)

    @property
    def line(self) -> str:
        """spec S4.1. The encoded line: prefix, template hash, then values in order."""
        return LINE_PREFIX + self.template_hash + VALUE_DELIMITER + VALUE_DELIMITER.join(self.values)

    @property
    def is_empty_pattern(self) -> bool:
        """True when the library covered nothing in this line. See spec S5.4."""
        return self.pattern == ""


def _escape_literal(text: str) -> str:
    """spec S4.2. Inside a template, '/' introduces an escape, so a literal '/' is
    written '//' and a literal '$' is written '/$'."""
    return text.replace(VAR_ESCAPE, VAR_ESCAPE * 2).replace(
        VAR_PLACEHOLDER, VAR_ESCAPE + VAR_PLACEHOLDER
    )


def encode(line: str, library: SymbolLibrary) -> Encoded:
    """spec S4. Turn one line into a template, its values, and the two identities."""
    tokens = tokenize(line)

    template_parts: List[str] = []
    values: List[str] = []
    symbols: List[str] = []

    for position, token in enumerate(tokens):
        if token.is_delimiter or token.is_minus_one or library.is_symbol(token):
            # Symbols, delimiters and a literal -1 are structure. They stay verbatim.
            template_parts.append(_escape_literal(token.text))
            if not token.is_delimiter and not token.is_minus_one:
                symbols.append(token.text)
            continue

        # Everything else is a runtime value: it leaves the template and joins the
        # value list, as a back-reference if an identical value came earlier.
        distance = _backreference_distance(values, token.text)
        if distance is not None:
            template_parts.append(VAR_PLACEHOLDER + str(distance))
            continue

        # spec S4.3: a fresh slot is written "$0" rather than "$" when the next literal
        # character is "(", so that the pair cannot be read as a timestamp opener.
        following = tokens[position + 1] if position + 1 < len(tokens) else None
        opens_timestamp = following is not None and following.text.startswith(TIMESTAMP_OPEN)
        template_parts.append(VAR_PLACEHOLDER + ("0" if opens_timestamp else ""))
        values.append(token.text)

    template = "".join(template_parts)
    pattern = PATTERN_JOIN.join(symbols)
    return Encoded(
        template=template,
        template_hash=hash_template(template),
        values=values,
        pattern=pattern,
        pattern_hash=hash_pattern(pattern),
        symbols=symbols,
    )


def _backreference_distance(values: Sequence[str], text: str) -> Optional[int]:
    """spec S4.3. Distance back to the EARLIEST identical value already emitted.

    The gate is on the position of the slot being written, not on how far back the
    search may reach: a back-reference is only considered while fewer than
    MAX_BACKREFERENCE_SLOTS fresh values have been emitted. Within that, the scan runs
    from the first value forward, so the distance is the largest one that matches. Those
    two facts together are why a distance never exceeds MAX_BACKREFERENCE_SLOTS - 1.

    The distance counts fresh value slots only. Timestamps occupy their own leading
    positions (spec S6.2) and are not counted.
    """
    if len(values) >= MAX_BACKREFERENCE_SLOTS:
        return None
    for index, earlier in enumerate(values):
        if earlier == text:
            return len(values) - index
    return None


# --- spec S5: the two identities ---------------------------------------------


def hash_template(template: str) -> str:
    """spec S5.2. FarmHash64-Na over the template's UTF-16LE bytes, rendered base-84."""
    return base84_encode(to_signed64(farm_na64(template.encode("utf-16-le"))))


def hash_pattern(pattern: str) -> str:
    """spec S5.3. xxHash64 over the pattern's UTF-8 bytes, big-endian, base64url.

    An empty pattern hashes to the empty string, not to a value. That is a deliberate
    part of the format and it is what the shipped encoder does: a line whose vocabulary
    the library does not hold gets no name at all, rather than a name that would be
    wrong. Callers can therefore test emptiness on the identifier itself.

    spec S5.4 records the alternative reading, under which the empty pattern would hash
    to EMPTY_PATTERN_HASH_TOTAL like any other string. This implementation does not use
    it, because it would disagree with the encoder that produced the published data.
    """
    if pattern == "":
        return ""
    return _hash_pattern_total(pattern)


def _hash_pattern_total(pattern: str) -> str:
    """hash_pattern without the empty-string special case. See spec S5.4."""
    digest = struct.pack(">Q", xxh64(pattern.encode("utf-8")))
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


#: What the empty pattern WOULD hash to if the empty-string case were not special.
#: Provided for anyone who wants a total function; not emitted by this implementation.
EMPTY_PATTERN_HASH_TOTAL = _hash_pattern_total("")


# --- spec S6: decoding -------------------------------------------------------


def parse_template(template: str):
    """spec S6.1. Split a template into literal runs, value slots and timestamp slots.

    Returns (segments, timestamp_count). A segment is one of
        ("literal", text)  ("value", index)  ("timestamp", index, format)
    """
    segments = []
    literal: List[str] = []
    value_count = 0
    timestamp_count = 0
    i = 0
    n = len(template)

    def flush() -> None:
        if literal:
            text = "".join(literal)
            # Undo the S4.2 escapes in a single left-to-right scan. A substitution pass
            # would need a sentinel, and any sentinel can occur in a log line: a literal
            # NUL in the template would come back out as '$'.
            out: List[str] = []
            k = 0
            while k < len(text):
                if (
                    text[k] == VAR_ESCAPE
                    and k + 1 < len(text)
                    and text[k + 1] in (VAR_ESCAPE, VAR_PLACEHOLDER)
                ):
                    out.append(text[k + 1])
                    k += 2
                else:
                    out.append(text[k])
                    k += 1
            segments.append(("literal", "".join(out)))
            literal.clear()

    while i < n:
        ch = template[i]

        if ch == VAR_ESCAPE and i + 1 < n and template[i + 1] in (VAR_PLACEHOLDER, VAR_ESCAPE):
            literal.append(template[i])
            literal.append(template[i + 1])
            i += 2
            continue

        if ch == VAR_PLACEHOLDER:
            if i + 1 < n and template[i + 1] == TIMESTAMP_OPEN:
                close = template.find(TIMESTAMP_CLOSE, i + 2)
                if close != -1:
                    flush()
                    segments.append(("timestamp", timestamp_count, template[i + 2 : close]))
                    timestamp_count += 1
                    i = close + 1
                    continue
            j = i + 1
            digits = ""
            while j < n and "0" <= template[j] <= "9":
                digits += template[j]
                j += 1
            flush()
            distance = int(digits) if digits else 0
            if distance:
                # A distance reaching past the first value is malformed. Record it as
                # unresolvable rather than letting a negative index wrap round the list.
                target = value_count - distance
                segments.append(("value", target if target >= 0 else None))
            else:
                segments.append(("value", value_count))
                value_count += 1
            i = j
            continue

        literal.append(ch)
        i += 1

    flush()
    return segments, timestamp_count


def decode(
    encoded_line: str,
    templates: Dict[str, str],
    timezone_offset_minutes: int = 0,
) -> Optional[str]:
    """spec S6. Rebuild the original line from an encoded line and the template map.

    Returns None when the template is not in the map, and returns the input unchanged
    when the line carries no encoding prefix. A line that is the prefix and a template
    hash alone, with no value delimiter, is a line with no values (spec S8.2); with no
    delimiter and no such template it is returned unchanged.

    timezone_offset_minutes is the zone the line was written in. It is needed because a
    timestamp is carried as an epoch, so a format with no zone field renders in local
    time. See spec S7.3.
    """
    if not encoded_line.startswith(LINE_PREFIX):
        return encoded_line
    body = encoded_line[len(LINE_PREFIX) :]
    split = body.find(VALUE_DELIMITER)
    if split == -1:
        # spec S8.2: an event whose template has no value slot is written as the hash
        # alone. Anything else without a delimiter is not an encoded line.
        if body not in templates:
            return encoded_line
        split = len(body)

    template = templates.get(body[:split])
    if template is None:
        return None

    values = body[split + 1 :].split(VALUE_DELIMITER)
    segments, timestamp_count = parse_template(template)

    out: List[str] = []
    for segment in segments:
        kind = segment[0]
        if kind == "literal":
            out.append(segment[1])
        elif kind == "value":
            # spec S6.2: timestamps occupy the leading value positions.
            if segment[1] is None:
                return None
            index = segment[1] + timestamp_count
            if not 0 <= index < len(values):
                # The template asks for a value the line does not carry. Returning
                # partial text here would look like a successful decode.
                return None
            out.append(values[index])
        else:
            _, index, fmt = segment
            out.append(
                render_timestamp(values[index], fmt, timezone_offset_minutes)
                if index < len(values)
                else ""
            )
    return "".join(out)


# --- spec S7: timestamps -----------------------------------------------------

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_EPOCH_PASSTHROUGH = {"epoch", "epochNano", "+%s", "+%s.%N", "+%s.%f"}

_SECONDS_FRACTION = re.compile(r"^([0-9]{10})\.([0-9]{1,9})$")
_MILLIS_FRACTION = re.compile(r"^([0-9]{1,18})(?:\.([0-9]{1,9}))?$")

#: spec S4.4. 2029-12-31T12:00:00Z expressed in milliseconds. A timestamp value above
#: this is read as nanoseconds since the epoch, at or below it as milliseconds. The
#: constant is the encoder's; note it is half a day short of 2030-01-01, so a
#: MILLISECOND timestamp at or after 2029-12-31T12:00:00Z is read as nanoseconds and
#: renders as 1970. The shortfall is believed to be a defect in the encoder rather than a
#: design choice, and 1893456000000 is the intended value. This reader keeps the
#: encoder's constant on purpose: a reference that silently corrects its subject stops
#: being a reference. See FORMAT_SPEC.md S4.4.
NANOSECOND_THRESHOLD = 1_893_412_800_000

#: Widest epoch this renderer will format, in either unit. Anything beyond is returned
#: unchanged instead of raising out of datetime.
MAX_RENDERABLE_EPOCH = 4 * 10**18


def epoch_time_ns(value: str, fmt: str) -> Optional[int]:
    """spec S4.4. The event time, in nanoseconds since the epoch, of the value of an epoch
    slot, or None when the value gives no time.

    `+%s.%f`: 10 digits of seconds, a dot, 1 to 9 fraction digits (`1723042099.6` is
    1723042099.600 s). `+%s.%N`: milliseconds, then an optional dot and fraction digits of
    a millisecond; digits past the nanosecond are dropped. Neither is read through the
    magnitude rule. `+%s`, `epoch`, `epochNano`: an integer epoch, milliseconds or
    nanoseconds by magnitude.
    """
    if fmt == "+%s.%f":
        m = _SECONDS_FRACTION.match(value)
        if not m:
            return None
        digits = m.group(2)
        return int(m.group(1)) * 1_000_000_000 + int(digits) * 10 ** (9 - len(digits))
    if fmt == "+%s.%N":
        m = _MILLIS_FRACTION.match(value)
        if not m:
            return None
        millis, digits = int(m.group(1)), m.group(2) or ""
        nanos = int(digits) * 10 ** (6 - len(digits)) if len(digits) <= 6 else int(digits[:6])
        return millis * 1_000_000 + (nanos if digits else 0)
    if fmt in ("+%s", "epoch", "epochNano"):
        if not value or not all("0" <= c <= "9" for c in value):
            return None
        epoch = int(value)
        return epoch if epoch > NANOSECOND_THRESHOLD else epoch * 1_000_000
    return None


def render_timestamp(value: str, fmt: str, timezone_offset_minutes: int = 0) -> str:
    """spec S7. Render an epoch value back through a Java-style date pattern."""
    import datetime

    if fmt in _EPOCH_PASSTHROUGH:
        return value
    body = value[1:] if value[:1] == "-" else value
    if not body or not all("0" <= c <= "9" for c in body):
        return value

    # spec S4.4. The unit is decided by magnitude, not by digit count: a value above
    # 2030-01-01 expressed in milliseconds is too large to be milliseconds, so it is
    # nanoseconds.
    epoch = int(value)
    if not -MAX_RENDERABLE_EPOCH <= epoch <= MAX_RENDERABLE_EPOCH:
        # Beyond what a calendar date can express. Emit the value rather than raise:
        # a decoder handed hostile input should degrade, not stop.
        return value
    if epoch > NANOSECOND_THRESHOLD:
        seconds, fraction = divmod(epoch, 1_000_000_000)
        nanos = f"{fraction:09d}"
    else:
        seconds, fraction = divmod(epoch, 1000)
        nanos = f"{fraction:03d}" + "000000"

    # spec S7.3: a Z or X field means the pattern carries its own zone, so render UTC.
    offset = 0 if ("Z" in fmt or "X" in fmt) else timezone_offset_minutes
    try:
        when = datetime.datetime.fromtimestamp(seconds + offset * 60, datetime.timezone.utc)
    except (OverflowError, OSError, ValueError):
        return value
    sign = "+" if offset >= 0 else "-"
    zone = f"{sign}{abs(offset) // 60:02d}{abs(offset) % 60:02d}"

    out: List[str] = []
    i = 0
    n = len(fmt)
    while i < n:
        ch = fmt[i]
        if ch == "'":
            end = fmt.find("'", i + 1)
            if end == -1:
                out.append(fmt[i + 1 :])
                break
            out.append(fmt[i + 1 : end] or "'")
            i = end + 1
            continue
        run = 1
        while i + run < n and fmt[i + run] == ch:
            run += 1
        if ch == "y":
            out.append(f"{when.year % 100:02d}" if run <= 2 else str(when.year).zfill(run))
        elif ch == "M":
            out.append(
                _MONTHS[when.month - 1]
                if run >= 3
                else (f"{when.month:02d}" if run == 2 else str(when.month))
            )
        elif ch == "d":
            out.append(f"{when.day:02d}" if run >= 2 else str(when.day))
        elif ch == "E":
            # Day of the week, as DateTimeFormatter writes it in English: one to three
            # letters the short name (Tue), four the full name (Tuesday), five the first
            # letter (T).
            day = _DAYS[when.weekday()]
            out.append(day[:3] if run <= 3 else (day if run == 4 else day[:1]))
        elif ch in ("H", "h", "m", "s"):
            # DateTimeFormatter: one letter writes the number without padding (5),
            # more letters pad it to that width (05).
            number = {
                "H": when.hour,
                "h": when.hour % 12 or 12,
                "m": when.minute,
                "s": when.second,
            }[ch]
            out.append(str(number).zfill(run) if run > 1 else str(number))
        elif ch == "S":
            out.append(nanos[:run])
        elif ch in ("Z", "z"):
            out.append(zone)
        elif ch == "a":
            out.append("AM" if when.hour < 12 else "PM")
        else:
            out.append(fmt[i : i + run])
        i += run
    return "".join(out)
