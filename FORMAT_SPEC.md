# Pattern-ID format specification

**Version 1.0.** This document defines the encoded form, the template form, and the two
identifiers a log line is given. It is the normative reference; `refimpl/` implements it
and `tests/` checks the implementation against data published by Log10x.

Every rule below is marked with how it was established:

- **[MEASURED]**: confirmed against the published sample at
  [`log-10x/config` tag `otel-sample-v1`](https://github.com/log-10x/config/releases/tag/otel-sample-v1),
  197,430 log lines, 159,454 encoded lines and 2,896 templates.
- **[OBSERVED]**: confirmed against output from the pinned encoder image
  `log10x/pipeline-10x:1.1.5`.
- **[STATED]**: a rule this specification fixes where the published data does not
  exercise it. An independent implementation should follow it; a future revision may
  refine it.

Section numbers (S2, S4.3, …) are referenced from comments in the source.

---

## S1. Scope

A conforming implementation turns a log line into

1. a **template**, the line with its runtime values removed,
2. a **value list**, those values in the order the template consumes them,
3. a **template hash**, naming the exact shape of the line,
4. a **pattern**, the symbol vocabulary the line drew on,
5. a **pattern hash**, naming the logging statement the line came from,

and turns 1–2 back into the original line byte for byte.

Deciding which tokens are values and which are symbols requires a **symbol library**,
which this specification treats as an input. Producing a library is a separate
ahead-of-time compilation over source trees, binaries and container images. That step is
out of scope here and is not described.

## S2. The token model

### S2.1 Delimiters

**[MEASURED]** A line is split into tokens on this delimiter set, 29 characters:

```
<>|. ][:-+/*=\,{}_();'"$<TAB><LF><CR>@%
```

A delimiter is always a token of its own, one character long. Every maximal run of
non-delimiter characters between two delimiters is one token. Nothing is discarded:
concatenating every token's text reproduces the line exactly.

**[MEASURED]** caveat: 27 of the 28 characters other than CR occur in the published
sample and none of them ever appears inside a value. TAB does not occur at all, so its
membership rests on the encoder's configuration rather than on the data. CR does not occur
in the published sample either. It reaches an encoded event in the line break between two
lines of a grouped event (S8.4), where a line ends before its line break, so a value can end
right before a CR. **[MEASURED]** A value can also hold a CR: the Receiver, reading a
forwarder's record, keeps a line of the record that is a CR alone (a Windows blank line
whose CR the forwarder kept) as the value `\r`, as in the template
`... created.\n$\nCreator Subject: ...` with that value. A producer may also join several
tokens into one value (S2.3), and such a value holds delimiters other than `,`.

**[STATED]** The set is configuration, not a constant. A producer may use a different
one, and a different set gives different tokens, different templates and therefore
different hashes. The 29 characters above are the default an implementation should use;
the published sample was produced with the same set (it holds no CR). Characters at or above U+007F are never
delimiters.

### S2.2 The sign rule

**[MEASURED]** ASCII hyphen `-` is a delimiter, so a negative number would arrive split.
A `-` immediately followed by a run of ASCII digits `0`-`9` is absorbed into that run and
the two become one token, and no delimiter token is emitted for the sign.

`308010eb-c129-4320-a5ca-1ad8becbedda` therefore tokenizes as

```
308010eb   -   c129   -4320   -   a5ca   -   1ad8becbedda
```

which is why the published template for it is `$-$$-$-$`, with two adjacent slots where
the absorbed sign sits.

Numeric-ness here is ASCII `0`-`9` only. **[STATED]** The leading-digit veto of S3.2 uses
the wider Unicode digit test, so the two checks differ. The published sample contains no
non-ASCII digit anywhere, so this distinction is unobserved and an implementation should
not rely on it. Back-reference distances in S4.3 are always ASCII digits.

**[MEASURED]** A token that comes out of this rule as exactly `-1` is a special case: it
stays in the template as literal text and emits no value. Across the published templates
there are 377 literal `-1` runs and, in 6,922,512 values, no value equal to `-1`.

Verified: over 20,000 published encoded lines, all 927,267 non-timestamp values are
tokens this rule produces from the corresponding original line.

### S2.3 Values joined from several tokens

**[STATED]** A producer may write a run of consecutive tokens as one value, with one `$` in
the template where the run was. The Log10x encoder does this for two shapes, each behind an
option that is off by default: an IPv4 address (`10.0.1.14`, option `ipv4SingleToken`) and a
Windows path (`C:\Program Files\App\app.exe`, `\Device\HarddiskVolume2\x`, `\\host\share`,
option `windowsPathSingleToken`). Which runs are joined is producer configuration, like the
delimiter set of S2.1, so the same line gives a different template and template hash with the
option on and off.

A joined value obeys three rules:

1. it is a run of whole tokens: it starts and ends where a token of the line starts and ends,
   with two exceptions at the start of an IPv4 address. After a `-` that S2.2 would absorb into
   the address's first number (`-10.0.1.14`, `10.0.0.1-10.0.1.14`), and after the letter `t`,
   `n` or `r` of an escape that follows a `\` (`\t10.0.1.14` inside a JSON string), the
   encoder keeps the sign or the letter in the template and starts the value at the first
   digit. **[MEASURED]** Of 9,181 values in the 2,664 synthetic lines `fixtures/joined.jsonl`
   is drawn from, encoded one event per line with `ipv4SingleToken`, 96 start this way, 48
   after a sign and 48 after an escape letter;
2. the character after it is a delimiter, or its line ends there, as after a value of one
   token;
3. it never holds the value delimiter `,` (S8.1). A path that reaches a comma ends before it.

A decoder needs nothing new for a joined value: it copies the value as it copies any other.

## S3. The symbol library

### S3.1 Token identity

**[OBSERVED]** A token's 64-bit identity is **FarmHash64, "Na" variant**, computed over
the token's **UTF-16LE** bytes, interpreted as a two's-complement signed 64-bit integer.

FarmHash is specified at <https://github.com/google/farmhash>. UTF-16 is the encoding
because the producing implementation hashes Java `char` arrays directly.

### S3.2 The membership test

**[OBSERVED]** A token is a **symbol** when all of these hold:

1. it is not a delimiter, and is not empty;
2. its first character is not a decimal digit;
3. its 64-bit identity is present in the library.

Every other non-delimiter token is a **value**. The library stores identities only, not
the token text, so the test is set membership and nothing else.

Rule 2 keeps a numeric run from ever becoming structure, so a number that collides with a
compiled token is still treated as a runtime value.

### S3.3 On-disk form

**[OBSERVED]** A library is a `.10x.tar` archive holding a JSON Lines member, a protobuf
reverse index over the same content, and a manifest. Only the JSON member is normative
for a reader. Each line is one origin section:

```json
{"h":"<base-84 origin hash>","n":"<origin name>","v":1.0,
 "i":<section index>,"c":<section count>,
 "k":"x(<base-84>)l(<base-84>,<base-84>)"}
```

`k` is a run of groups. Each group is a one-character source-context tag, then a
parenthesised comma-separated list of base-84 token identities. An identity prefixed
`%=` is a format token. An origin too large for one line is split into `c` sections
sharing `h` and `n`, with `i` running `0..c-1`; `i` and `c` are bookkeeping and take no
part in matching.

Source-context tags: `x` executable, `t` plain text, `p` package, `c` class,
`i` interface, `e` enum, `d` method declaration, `s` variable assignment,
`v` method invocation, `o` annotation invocation, `g` logger method invocation,
`a` logging method variable assignment, `l` logging method invocation.

### S3.4 Selecting among origins

**[OBSERVED]** One token identity usually appears in many origins. This specification
requires only the membership test of S3.2, under which the origin does not matter.

A producing implementation may narrow the result further, and the Log10x encoder does. It
groups candidate origins by originating unit and enclosing parent, then ranks them on a
four-part descending comparator: the largest number of distinct multi-character
non-reserved symbol tokens contributed by any single field; the count of distinct
non-reserved symbol tokens covered across the event; the total character length of those
distinct tokens; and the total symbol character length spanned. It also matches compound
symbols, where a contiguous run of symbol and delimiter tokens is looked up as one entry.

Both refinements change **which tokens count as symbols**, and therefore change the
pattern. Neither changes the encoded form, the template, or either hash function. An
implementation that applies only S3.2 conforms to this document and will produce
different patterns from the Log10x encoder on the same line. `README.md` measures the
difference.

## S4. Encoding

### S4.1 The encoded line

**[MEASURED]** An encoded line is

```
~<template hash>,<value 1>,<value 2>,...
```

`~` marks the line as encoded. The delimiter is `,`. Values appear in the order the
template consumes them.

Encoded lines are separated by LF. A CR inside a line is data, since a value can hold one
(S2.1), so a reader splits lines at LF only: a reader that also ends a line at CR, as many
line readers do by default, cuts such a line in two.

A line that does not begin with `~` is not encoded and passes through untouched.

### S4.2 Escaping inside a template

**[MEASURED]** Within a template, `/` introduces an escape:

| in the log line | in the template |
| --------------- | --------------- |
| `/`             | `//`            |
| `$`             | `/$`            |

Escapes are undone left to right when the template is parsed, so `//$` is a literal `/`
followed by a value slot, not a literal `$`.

### S4.3 Value slots and back-references

**[MEASURED]** A value is written into the template as `$`.

When the value is identical to one already emitted for the line, it is written as `$N`
instead and is **not** added to the value list, where `N` is how many value positions
back that earlier value sits, counted from the position this slot would have occupied.

Three rules govern when this happens, and the first is the one most easily got wrong.

1. **The bound is on the position of the slot being written, not on how far back the
   search reaches.** A back-reference is only considered while fewer than **10** fresh
   values have been emitted for the line. The counter is per **physical** line and resets
   at each newline: a grouped multi-line event concatenates its per-line templates, and a
   back-reference never reaches into an earlier physical line. **[MEASURED]** Counted per
   physical line, the highest slot index carrying a back-reference across all 2,896
   published templates is 9, and no site reaches 10. Counted across a whole grouped
   template instead, 79 templates appear to break the bound; they do not, and 76 of them
   would be unreproducible by an encoder that got this wrong. From the eleventh fresh value onward a repeat
   is written out in full. **[MEASURED]** This is why a distance is always a single
   digit: with fewer than 10 fresh values emitted, the largest possible distance is 9.
   Across all 2,896 published templates the distances are 1 through 9, 6,421 references
   in the checked subset, none out of range.

2. **The distance counts fresh value slots only.** Timestamps occupy their own leading
   positions (S6.2) and are not counted. **[MEASURED]** Counting timestamps as well fails
   to reconstruct 513 of 30,000 sampled lines; the fresh-slot rule reconstructs all of
   them, and all 197,430 lines of the full sample.

3. **The match is the earliest equal value, so `N` is the largest that matches.** The
   scan runs forward from the first value. **[STATED]** Earliest and nearest coincide in
   the published data, because a repeat inside the bound becomes a reference and so never
   allocates a second slot.

Comparison is on exact text: same length, same characters, no normalisation and no case
folding.

**[MEASURED]** `$0` is a **fresh** value, not a reference. It is written instead of a bare
`$` when the next literal character is `(`, so that the pair cannot be misread as the
timestamp opener of S4.4. All 20 occurrences in the published templates are immediately
followed by `(`, for example `at Accounting.Consumer.$0() in ...`.

A decoder must accept any distance that resolves to a value already emitted.

### S4.4 Timestamps

**[MEASURED]** A timestamp is written into the template as `$(<pattern>)`, where
`<pattern>` is a Java-style date format such as `yyyy-MM-dd HH:mm:ss`. Its value is
carried in the value list as an epoch.

**[MEASURED]** The unit is decided by magnitude, not by digit count. A value greater than
`1893412800000`, which is 2029-12-31T12:00:00Z in milliseconds, is nanoseconds since the
epoch; at or below it the value is milliseconds. Patterns with three or fewer `S` letters
store milliseconds and those with four or more store nanoseconds, and no microsecond form
occurs in the published sample.

**A ceiling follows from that constant.** A MILLISECOND timestamp at or after
2029-12-31T12:00:00Z exceeds the threshold and is read as nanoseconds, so it renders as a
1970 date. Nothing in the encoded form distinguishes the two cases, so a decoder cannot
recover.

**[DEFECT]** The twelve-hour shortfall against 2030-01-01 is believed unintended;
`1893456000000` is the value the constant appears to have been reaching for. This
specification records `1893412800000` because that is what the encoder uses and a
reference implementation has to agree with it. A future revision will move the constant
once the encoder does, and encoded data written before then is unaffected: no timestamp
in that window can exist until 2029.

**[MEASURED]** `+%s` means the source text was already an epoch; the value passes through
unchanged with no arithmetic. **[STATED]** `+%s.%N`, `epoch` and `epochNano` are treated
the same way. Only `+%s` occurs in the published sample, 39 times.

**[MEASURED]** Escaping does not apply inside a timestamp format. Six published templates
carry a bare `/` within a `$(...)` body, as in `$(yyyy/MM/dd HH:mm:ss)`. An implementation
that applies the S4.2 rule there would write `$(yyyy//MM//dd ...)` and compute a different
template hash.

**[MEASURED]** Sub-second digits become part of the epoch only when the pattern claims
them. In `[otel.javaagent 2025-10-01 20:11:46:346 +0000]` the pattern is
`$(yyyy-MM-dd HH:mm:ss)` with epoch `1759363906000`, while `346` and `0000` stay ordinary
values with slots of their own.

## S5. The two identities

### S5.1 Why there are two

The **template hash** names the exact shape of one line. It is the join key that ties an
encoded line to the template needed to rebuild it. Any change to the line's shape is a
different template and a different hash.

The **pattern hash** names the logging statement the line came from. It is computed from
the symbol vocabulary alone, so lines whose shapes differ but whose vocabulary is the
same share it. Several templates therefore collapse onto one pattern, and the pattern is
the identity that survives a shape change.

### S5.2 Template hash

**[MEASURED]** Compute FarmHash64-Na over the **UTF-16LE** bytes of the template string,
interpret it as a signed 64-bit integer, and render it in base 84 (S5.5).

Verified on 4,094 templates: 2,896 from the published sample and 1,198 from a local run
of the pinned encoder image. No mismatches.

### S5.3 Pattern and pattern hash

**[OBSERVED]** The **pattern** is the text of the line's symbol tokens, in order, joined
with `_`. Delimiters and values do not appear.

**[OBSERVED]** The **pattern hash** is xxHash64 over the pattern's **UTF-8** bytes,
serialised as 8 big-endian bytes, encoded base64url, with `=` padding removed.

xxHash is specified at <https://github.com/Cyan4973/xxHash>.

Note the two identities use different hash functions, different string encodings and
different renderings. They are not interchangeable and a value of one is never a valid
value of the other.

Verified on 2,619 pattern/hash pairs emitted by the pinned encoder image. No mismatches.

### S5.4 The empty pattern

**[OBSERVED]** When the library holds none of a line's vocabulary, the pattern is the
empty string and **the pattern hash is also the empty string**. No identifier is minted.

This is the coverage boundary, and it is the point of the design: a line from code that
was never compiled into the library reports that it has no name, instead of being given
one that would be wrong. Emptiness is testable on the identifier itself.

**Only the pattern goes empty. The template hash is unaffected.** Delimiters and value
slots stay in the template whatever the library holds, so a line whose every token is a
value still has a template, and still has a template hash. A line consisting of one
unrecognised word gives the template `$`; `x=7` gives `$=$`, the delimiter retained. The
one input that yields an empty template is an empty line, and that hashes too, to
`-J}UrlyaKD8`.

The consequence is worth being explicit about, because it is what makes the empty pattern
safe to emit: an empty pattern costs the line its **name**, never its storage or its
reconstruction. Such a line still encodes, still joins to its template, and still decodes
byte for byte. What it loses is the ability to be grouped with its siblings under a
statement identity, which is the honest outcome when the emitting code is absent from the
library.

**[STATED]** An implementation wanting a total function may hash the empty string like
any other, which yields `70bbN1HY6Zk`. This specification does not use that value, and an
implementation that emits it will disagree with the published encoder. `refimpl` exposes
it as `EMPTY_PATTERN_HASH_TOTAL` and never returns it.

The boundary moves with the library. A library compiled from a handful of images holds a
narrow vocabulary, and unrelated lines come back empty. A large general library holds
common English words and generic identifiers, and an unrelated line can pick up a short,
low-value pattern from them. Emptiness proves the vocabulary is absent; a non-empty
pattern does not by itself prove the emitting code was compiled.

### S5.5 Base-84 rendering

**[MEASURED]** Signed 64-bit values are rendered in base 84 over this alphabet, index 0
first:

```
 !#$&*+./0123456789:;<>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[]^_abcdefghijklmnopqrstuvwxyz{|}
```

The first character is a space. `-` is **not** a member: it is reserved as a sign prefix
for negative values. Digits are emitted most significant first, with no padding, so a
rendering is 1 to 10 characters, or 2 to 11 with the sign.

The alphabet omits `"`, `%`, `'`, `(`, `)`, `,`, `=`, `\` and `` ` `` so that a rendered
identifier needs no quoting inside JSON, CSV, a shell word or a URL query.

## S6. Decoding

### S6.1 Parsing a template

Read the template left to right:

- `/` followed by `/` or `$` is an escape (S4.2), contributing one literal character;
- `$(` … `)` is a timestamp slot (S4.4);
- `$` followed by decimal digits is a back-reference (S4.3);
- `$` not followed by digits or `(` is a fresh value slot;
- anything else is literal text.

### S6.2 Value ordering

**[MEASURED]** Timestamp values occupy the **leading** positions of the value list, in
template order. Ordinary value slots index from the end of the timestamps onward. A
template with `t` timestamps therefore resolves its first ordinary slot to value index
`t`.

### S6.3 Reconstruction

Emit each segment in order: literal text verbatim, a value slot as its value, a timestamp
slot as its epoch rendered through the slot's pattern (S7). The result is the original
line.

## S7. Rendering timestamps

### S7.1 Pattern letters

**[MEASURED]** Pattern letters follow Java's `DateTimeFormatter` conventions. Text inside
single quotes is a literal.

| letter | meaning                                                   |
| ------ | --------------------------------------------------------- |
| `y`    | year; 1–2 letters give two digits, more give zero-padded   |
| `M`    | month; 3 or more letters give `Jan`…`Dec`                  |
| `d`    | day of month                                              |
| `H`    | hour, 00–23                                               |
| `h`    | hour, 01–12                                               |
| `m`    | minute                                                    |
| `s`    | second                                                    |
| `S`    | fraction of a second; N letters take the first N of 9 digits |
| `Z` `z`| zone offset, `+HHMM`                                      |
| `X`    | zone offset; **[STATED]**, absent from the published sample |
| `a`    | `AM` or `PM`                                              |

### S7.2 Choosing the unit

The millisecond-or-nanosecond rule is in S4.4, and its ceiling is stated there.

### S7.3 The zone, and a real limit of the format

**[MEASURED]** The value carries an
epoch, so a pattern with no zone field renders in whatever zone the reader chooses. A
pattern containing `Z` or `X`, including a quoted `'Z'`, renders in UTC. Everything else
needs the zone the line was originally written in, supplied out of band.

**[OBSERVED]** The zone is producer-side configuration. The encoder takes a configured
zone and falls back to the host's default when none is set, so a stream encoded without
that setting carries the encoding host's zone and nothing records which one.

The published sample was produced in UTC−4 and does not round-trip byte for byte at any
other offset; a sweep of every 15-minute offset from UTC−12 to UTC+14 finds exactly one
that reconstructs. An encoded line is therefore **not** self-describing for local-time
timestamps, and a reader needs the zone out of band. `refimpl.decode` takes
`timezone_offset_minutes` for this reason.

A producer that wants self-describing output should configure UTC, or use a pattern
carrying an explicit zone field, which renders UTC regardless.

## S8. Limits of the encoded form

These follow from S4.1 and are stated so that an implementation does not assume otherwise.

1. **A value can never contain the value delimiter.** `,` is a token delimiter (S2), so
   no token can contain it, and a value joined from several tokens ends before it (S2.3).
   The encoded line is safe to split on `,` only because of this. An implementation that
   widens the token set must widen the escaping to match, or the round trip breaks.
2. **A line with no values is the hash alone.** **[MEASURED]** The Log10x encoder writes
   an event whose template has no value slot as `~<hash>`, with no delimiter after the
   hash. A decoder reads such a line as a line with no values when `<hash>` is a known
   template, and passes it through untouched otherwise. `~<hash>,`, the hash and a single
   empty value, decodes to the same text, because a template with no slots never reads a
   value. No published line has zero values; of 2,664 synthetic lines encoded one event
   per line by engine 1.1.180, 688 are written `~<hash>`. An implementation should treat
   the value count as bounded by the template rather than by the split.
3. **A template hash collision would misdecode.** Identity is 64 bits and is accepted as
   such; the format carries no checksum over the reconstructed line.
4. **One encoded line may carry several original lines.** A grouping step ahead of the
   encoder can merge a multi-line event, in which case decoding yields text containing
   newlines. In the published sample 197,430 lines encode to 159,454. The template joins
   a line to the next with the break the line was read with: LF; CR LF, as in Windows
   event logs read from a file or sent by a forwarder; or a CR alone, with no LF after it.
   So `$`, and a timestamp's closing `)`, can be followed by CR, and a CR can be followed
   by any character. A CR alone still ends a line as LF does, so it never moves an event
   boundary. The break that ends the event is not part of its template. **[MEASURED]** In
   two Windows Security samples, 3 of 662 events (754 lines) hold 27 CR LF breaks and each
   of 7,649 events (15,298 lines) holds one; both decode byte for byte, and with CR in the
   delimiter set the TOKENIZER check accepts every value of both. A PowerShell script
   block sample holds 7 CRs alone inside its events; they decode as written.

## S9. Conformance

An implementation is **decode-conforming** if, for the published sample, it reproduces
all 197,430 original lines byte for byte from the published templates and encoded lines
at UTC−4. `tests/conformance.py` checks exactly this.

An implementation is **identity-conforming** if `hash_template` and `hash_pattern`
reproduce published values for template and pattern strings it is given. `tests/`
checks this on 4,094 templates and 2,619 patterns.

Encode conformance is deliberately **not** defined as reproducing a particular encoder's
choice of symbols, because that choice depends on the library and on refinements a
producer may apply (S3.4).

---

## S10. Licence

The reference implementation accompanying this specification is MIT licensed. Log10x
retains its intellectual property in the method described here.
