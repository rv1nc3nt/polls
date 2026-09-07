# Canonical serialisation and the closure hash

This document is the contract between the application, the published CSV and the
independent verifier. A third party must be able to recompute `closure_hash`
from the published CSV alone (§9). `json.dumps` defaults are not a
canonicalisation guarantee, so the bytes are defined here rather than left to a
library.

Reference implementations: `src/apps/core/canonical.py` (Python) and
`verifier/src/main.rs` (Rust, written from this document and sharing no code
with it).

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

Option ids, never labels: a translation corrected after closure must move
neither the hash nor the result (§3.8). Ids **within a group** are sorted by
code point, because a tie is unordered and two orderings of the same tie must
not produce two hashes. Groups keep the voter's order.

## A record

    {"tracking_code":"AAAAAAAAAA","ranking":[["a"],["b"],["c"]]}

* keys in exactly that order: `tracking_code`, then `ranking`;
* no insignificant whitespace — JSON separators are `,` and `:`;
* non-ASCII characters are emitted as UTF-8, not `\u`-escaped. (Both fields are
  drawn from restricted alphabets today; the rule is stated so a future option
  id cannot make the encoding ambiguous.)

## The document

Records are sorted by tracking code ascending, comparing **UTF-8 bytes**. The
tracking-code alphabet is ASCII (`23456789ABCDEFGHJKLMNPQRSTUVWXYZ` — no `O`,
`0`, `I` or `1`), so this is the obvious ordering; it is stated because it is
what the verifier must match. `(poll_id, tracking_code)` is unique in the
database (INV-11), so the sort is total.

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
