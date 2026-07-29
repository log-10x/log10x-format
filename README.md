# Reference implementation of the pattern-ID format

A log line is split on a delimiter set, each token is looked up in a compiled symbol
library, and the tokens the library holds are kept as structure while the rest are pulled
out as runtime values. Hashing what remains gives the line a name that does not depend on
what any process happened to see beforehand.

This repository is the runnable definition of that scheme: a versioned format
specification, a small encoder and decoder, and a suite that checks both against data
Log10x published, rather than against themselves.

Two identities come out of one line. The template hash names the exact shape and is the
join key; the pattern hash names the logging statement, so several templates collapse
onto one pattern. [Why log clustering keeps
drifting](https://www.log10x.com/blog/why-log-clustering-keeps-drifting/) explains why
the split exists; `FORMAT_SPEC.md` S5 defines both.

Everything here is Python 3, standard library only. There is nothing to install.

```bash
python3 tests/demo.py           # the four properties, offline, about a second
python3 tests/conformance.py    # checked against 197,430 published log lines
python3 tests/engine_parity.py  # compared against the pinned encoder, needs docker
python3 tests/fuzz.py           # the same properties on generated and hostile input
```

## What you can check

`tests/demo.py` runs four things and prints the evidence for each.

| | property | how it is shown |
| --- | --- | --- |
| 1 | the same line gets the same pattern ID on every run | 1,000 encodes, one distinct ID |
| 2 | two processes with the same library agree | two subprocesses, no shared state |
| 3 | an encoded line decodes to the original, byte for byte | encode then decode, compare bytes |
| 4 | vocabulary the library does not hold yields an EMPTY pattern | lines from code that was never compiled |

Property 4 is the coverage boundary and the reason the scheme is worth the compile step.
A line from code that is absent from the library comes back with an empty pattern and an
empty pattern hash. A wrong name would be worse than no name, so no name is what comes
back, and emptiness is testable on the identifier itself.

Only the pattern goes empty. Delimiters and value slots stay in the template whatever the
library holds, so the line still has a template, still has a template hash, and still
decodes byte for byte. An empty pattern costs the line its name, never its storage.

Read the property precisely in the other direction too. Emptiness proves the vocabulary is
absent. The reverse does not hold: a large general library contains common English words and generic identifiers,
so an unrelated line can still pick up a short, low-value pattern from them. The boundary
is a property of what was compiled, not a detector. `tests/demo.py` prints both sides.

## What has been measured

`tests/conformance.py` downloads the public
[otel-sample-v1](https://github.com/log-10x/config/releases/tag/otel-sample-v1) release,
197,430 Fluentd/Kubernetes lines from the OpenTelemetry demo, and checks this code
against the encoded form and templates Log10x published alongside it.

| check | result |
| --- | --- |
| encoded lines rebuilt byte for byte | 159,454 / 159,454 |
| original lines recovered | 197,430 / 197,430 |
| published template hashes reproduced | 2,896 / 2,896 |
| published values that are tokens of their line | 927,267 / 927,267 |
| back-references resolving inside the spec bound | 6,421, widest distance 9 |

`tests/engine_parity.py` runs the pinned encoder image `log10x/pipeline-10x:1.1.5` over
2,000 lines of that sample and compares against its output directly. Requires docker.

| check | result |
| --- | --- |
| template hashes reproduced | 1,198 / 1,198 |
| pattern hashes reproduced from the encoder's own pattern strings | 1,484 / 1,484 rows |
| the same, from its aggregate output | 1,135 / 1,135 rows |

Those two rows cover the **same 1,135 distinct patterns**, written to two different output
files by one encoder run. They are not independent measurements, and 1,135 is the number
of distinct patterns ever checked. Likewise the 1,198 templates above and the 2,896
published ones overlap by 71, so 4,023 distinct templates have been checked, not 4,094.

`tests/fuzz.py` checks the same properties on input the published sample never contains:
lone escape characters, a value shaped like a back-reference, the encoded-line prefix
inside a line, non-ASCII digits, and malformed templates from a hostile source. 20,000
tokenizer cases, 5,008 base-84 values including both ends of the signed 64-bit range,
6,666 round trips and 22 malformed inputs, with no failures.

Every number on this page is printed by a script in this repository. Nothing is quoted
that a reader cannot regenerate.

## What this does not do

**No compiler.** This code reads a symbol library. Building one is an ahead-of-time pass
over source trees, binaries and container images, and none of that is here. There is no
scanner of any kind, no binary or executable symbol extraction, and no dependency-closure
expansion. `FORMAT_SPEC.md` treats the library as an input and describes only how to read
it.

**No symbol arbitration.** Deciding symbol from value is plain membership (spec S3.2).
The Log10x encoder narrows it further: it matches compound symbols, where a run of
symbol and delimiter tokens is looked up as one entry, and where several origins could
claim the same tokens it ranks them with a coverage-ranked comparator (spec S3.4).

That difference is measurable and it is large. `tests/engine_parity.py` measures it: on
1,304 single-line events, with the message field scoped the same way and the same default
library, this reference agrees with the Log10x encoder's pattern on **11.2%** of lines,
and on 1,112 of the rest the encoder saw a symbol this reference did not.

Almost all of the gap is compound symbols. The reference sees
`DOTNET_RUNNING_IN_CONTAINER` as the tokens `DOTNET`, `RUNNING`, `IN` and `CONTAINER` and
keeps only the ones the library holds individually, where the encoder matches the whole
compound as one entry.

So the honest statement of what agrees, and what does not:

- **The format agrees exactly.** Decoding is byte-identical on every published line.
- **The identity functions agree exactly.** Given the same template string this code
  produces Log10x's template hash; given the same pattern string it produces Log10x's
  pattern hash. Verified on 4,023 distinct templates and 1,135 distinct patterns.
- **The choice of symbols does not agree**, and a pattern ID from this code is therefore
  generally not the pattern ID the Log10x encoder would assign to the same line.

`FORMAT_SPEC.md` S9 states conformance in those terms, which is why encode conformance is
defined on the format rather than on one encoder's choice of vocabulary.

## The symbol library

`fixtures/library.jsonl` is a small library that ships with this repository so the demo
runs offline. It stands in for a library compiled from the public OpenTelemetry demo
container images, filtered to the vocabulary the sample lines need. It holds 64-bit token
identities and origin names, never the token text.

The full default library holds about 946,000 token identities compiled from public
open-source container images. [Where log structure actually
lives](https://www.log10x.com/blog/where-log-structure-actually-lives/) describes how such
a library is built; this repository only reads one. Running the demo against it is the clearest way to see the
point above about the boundary moving with the library. Two ways to get it:

```bash
# download the published library, 96 MB
curl -O https://dl.log10x.com/symbols/v1.1.5/tenx-symbols-1.1.5.10x.tar
curl -O https://dl.log10x.com/symbols/v1.1.5/SHA256SUMS.txt
shasum -a 256 -c SHA256SUMS.txt
python3 tests/demo.py --library tenx-symbols-1.1.5.10x.tar

# or take it out of the encoder image, if you already have docker
python3 tools/extract_library.py --image log10x/pipeline-10x:1.1.5 --out symbols.10x.tar
python3 tests/demo.py --library symbols.10x.tar
```

Both give the same file, sha256 `fc3d0599a8787af180a36853e5ad740a796cbb62705857e3f13707059c86457c`. The library holds 64-bit token identities and origin names; it
never holds the token text, so no logged message or source string is recoverable from it.

## Layout

```
FORMAT_SPEC.md          the normative specification, version 1.0
refimpl/hashes.py       FarmHash64-Na, xxHash64, base-84
refimpl/codec.py        tokenizer, encoder, decoder, both identities
refimpl/library.py      reading a published symbol library
tests/demo.py           the four properties
tests/conformance.py    checked against published data
tests/engine_parity.py  compared against the pinned encoder image, needs docker
tests/fuzz.py           randomised and hostile input
tools/extract_library.py    pull the default library out of the encoder image
tools/build_fixture.py      filter a library down to fixtures/library.jsonl
```

## License

MIT. See [LICENSE](LICENSE).

Log10x retains its intellectual property in the method this code demonstrates.
