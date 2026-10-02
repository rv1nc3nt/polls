<!-- SPDX-License-Identifier: 0BSD -->

# Canonical serialisation and the closure hash

This document is the contract between the application, the published CSV and the
independent verifier. A third party must be able to recompute `closure_hash`
from the published CSV alone (§9). `json.dumps` defaults are not a
canonicalisation guarantee, so the bytes are defined here rather than left to a
library.

Reference implementations: `src/apps/core/canonical.py` (Python) and
`verifier/core/src/canonical.rs` (Rust, written from this document and sharing
no code with it).

The publication document (`?format=json`) carries the same records in its
`ballots` member, and the verifier hashes them the same way. Its layout is
[`publication-format.md`](publication-format.md).

## The set

Exactly the ballots with `status = live`. `superseded`, `deleted` and
`pending_countersign` rows are excluded from the tally, from the hash and from
the publication, without exception (§3.4). The published CSV therefore contains
that set and nothing else, which is what makes the recomputation possible.

## A ranking

A ranking is a **list of groups**, each group a list of option **ids**:

    [["a"], ["b"], ["c"]]        strict: a > b > c
    [["a", "b"], ["c"]]          a and b tied, both above c
    [["a"]]                      only a ranked; b and c are equal-last (R-10.4)

Option ids, never labels: the hash and the result are built from ids alone and
are independent of the labels and their translations (§3.8). Ids **within a
group** are sorted by code point, because a tie is unordered and two orderings
of the same tie must not produce two hashes. Groups keep the voter's order.

A ranking places **at least one** option, has **no empty group**, and ranks
**no option twice**: the application refuses any other ballot before it is
stored, and the verifier refuses a ballot list holding one, as a list no poll
could have published.

## A record

    {"tracking_code":"AAAAAAAAAA","ranking":[["a"],["b"],["c"]]}

* keys in exactly that order: `tracking_code`, then `ranking`;
* no insignificant whitespace — JSON separators are `,` and `:`;
* every string written as-is between its quotes, with no escape sequence, which
  the alphabets below guarantee is the JSON for it.

## Alphabets

Every string in a record comes from a fixed alphabet:

| String | Alphabet | Length |
|---|---|---|
| tracking code | `23456789ABCDEFGHJKLMNPQRSTUVWXYZ` | exactly 10 |
| option id | `A-Z`, `a-z`, `0-9`, `_`, `-` | 1 to 50 |

JSON escapes none of these characters, so the format needs **no escaping
rule**: each string's JSON is the string between two quotes. The option-id
alphabet is the slug the application's forms and model already accept, and a
database trigger holds stored ids to it.

A string outside its alphabet is **refused, never escaped**: by the
application's serialiser, which will not hash it, and by the verifier, which
treats a ballot list or option list holding one as an input error. Escaping
would need a rule both sides follow to the byte — the application's
`json.dumps` writes a quote as `\"` and U+0001 as `\u0001`, where a serialiser
that writes strings raw, as the verifier's does, would not, and the two hashes
part (review B-7) — and an id that needs one has no use here. Widening an alphabet is therefore a change to this
contract: it needs that rule first, in Python, in Rust and here together.

## The document

Records are sorted by tracking code ascending, comparing **UTF-8 bytes**. The
tracking-code alphabet is ASCII (`23456789ABCDEFGHJKLMNPQRSTUVWXYZ` — no `O`,
`0`, `I` or `1`), so this is the obvious ordering; it is stated because it is
what the verifier must match. `(poll_id, tracking_code)` is unique in the
database (INV-11), so the sort is total. The verifier refuses a ballot list
holding a code outside that alphabet, of another length than 10, or repeated:
the database could not have produced it (see "Alphabets" above).

Each record is followed by a single `\n`, **including the last**. The document
is the concatenation of those lines, encoded UTF-8.

## The hash

    closure_hash = SHA256(document)

An empty live set serialises to zero bytes and hashes to
`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` — a poll with
no ballots still has a closure hash.

## Worked vector

Two ballots:

    {"tracking_code":"AAAAAAAAAA","ranking":[["a"],["b"],["c"]]}
    {"tracking_code":"BBBBBBBBBB","ranking":[["c"],["b"],["a"]]}

with a trailing newline on each line, gives

    closure_hash = 87694cf068ba44eca50e15bd4b7c1195fc4a1fae9ad3b0ba640deec22f7948e6

This vector is asserted by `tests/unit/test_canonical_and_crypto.py` (T-42) and
by the verifier's own tests.

## The tie-break, for completeness

    tiebreak_seed = SHA256(opening_seed || closure_hash)
    order tied options by ascending SHA256(tiebreak_seed || utf8(option_id))
    first wins

`opening_seed` and `closure_hash` are published as lower-case hex; the hash
inputs are the raw 32-byte values, not their hex text.
