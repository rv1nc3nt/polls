<!-- SPDX-License-Identifier: 0BSD -->

# The publication document

This document is the contract between the application, the JSON a published
poll serves at `/<lang>/scrutin/<id>/resultats/?format=json`, and the
independent verifier, which reads it in place of the CSV. It sits beside
[`canonical-serialisation.md`](canonical-serialisation.md), which fixes the
bytes the closure hash covers; this one fixes the document that carries those
ballots together with everything else the site claims about the result.

Reference implementations: `src/apps/elections/closure.py`, `publication`
(Python, the writer) and `verifier/core/src/publication.rs` (Rust, the reader,
sharing no code with it).

## Why the verifier reads it

The CSV carries tracking codes and rankings only. To check a winner from it, the
verifier has to be told the tally method, the option list, the closure hash, the
opening seed and the announced winner, which a person copies off the results
page. The document carries all of these. The verifier recomputes the closure
hash, the ballot count, the matrix, the counts, the winner and the tie-break
from its ballots, and checks each against the value the document states.

It cannot check the tally method this way, because the method decides what the
winner should be. It restates the method so the reader can compare it with the
one the poll announced. The method is fixed before the poll opens and shown on
its public page from that point on.

## Encoding

- UTF-8 JSON (RFC 8259), one object.
- Object keys are unique. The verifier refuses a duplicate key rather than
  keeping one of the values, so that two readers cannot find two different
  winners in the same file.
- Byte-exact formatting is **not** part of the contract, unlike the canonical
  serialisation: whitespace and key order may vary. The one exception is
  `options`, whose key order is the poll's option order and is kept by the
  verifier for display.

## Versioning

`format_version` is a string, `"1"` for the layout below
(`closure.PUBLICATION_FORMAT_VERSION`). Adding a member does not change the
version. Removing, renaming or re-typing a member the verifier reads does: the
writer, this page and the verifier's `SUPPORTED_FORMAT_VERSIONS` change
together. The verifier refuses a document with no version or a version it does
not know, rather than guessing.

## Members

The verifier reads the members marked **checked** and **read**, and ignores the
rest.

| Member | Type | Verifier | Meaning |
|---|---|---|---|
| `format_version` | string | read | This layout's version. |
| `poll_id` | string (UUID) | read | Shown in the report. |
| `tally_method` | `"schulze"` \| `"plurality"` \| `"approval"` | read, **restated** | The method the winner is recomputed under. |
| `tally_method_version` | string | read | Restated with the method. |
| `closure_hash` | lower-case hex | **checked** | SHA-256 of the canonical serialisation of `ballots`. |
| `opening_seed` | lower-case hex | read | Input to the computed tie-break. |
| `counts` | object | ignored | Participation frozen at closure: `registered`, `ballots_online`, `ballots_paper`, `paper_uncountersigned`, `non_voters`. It is published, but the ballot list does not determine it. |
| `closure_override_reason` | string | ignored | Reason given for closing despite uncountersigned entries, or `""`. |
| `options` | object: option id → labels by language | read (keys) | The poll's options, including any that no ballot ranks. |
| `ballots` | list of `{"tracking_code": string, "ranking": [[option id, …], …]}` | read | The live set, sorted by tracking code, ids sorted within a group; the same records as the CSV. |
| `ballot_count` | integer | **checked** | Number of entries in `ballots`. |
| `winner` | option id or `null` | **checked** | The result after any tie-break. `null` only when there are no ballots. |
| `matrix` | object: id → (object: other id → integer) | **checked** | `d[i][j]`, the number of ballots ranking `i` strictly above `j`, for every ordered pair of distinct options. |
| `derivation` | object | `counts` **checked** | Schulze: `pairwise`, `paths`, `winners`. Plurality and approval: `counts` (id → integer) and `winners`. |
| `serialisation_bytes` | integer | ignored | Length of the canonical serialisation. |
| `tiebreak` | object, present only if the tally tied | **checked** | See below. |
| `orderings` | object: ordering → integer | ignored | Summary table, published for a Schulze poll with at most four options. |

### `tiebreak`

Computed (the hash chain of `canonical-serialisation.md`, "The tie-break"):

    {"rule": "computed", "tied": [id, …],
     "order": [{"option_id": id, "draw": hex}, …], "winner": id}

The verifier replays the draw from `opening_seed` and the recomputed hash, and
requires `tied` to equal its own set of tied winners and `order` to equal its
own order.

Physical (a public draw at the mairie, entered on screen 9):

    {"rule": "physical", "tied": [id, …], "order": [id, …], "winner": id}

A program cannot replay a physical draw. The verifier checks that `tied`
equals its own set of tied winners and that `order` is a permutation of them.
It then takes the first entry of `order` as the winner.

With no `tiebreak` member, the recomputation must not tie.
