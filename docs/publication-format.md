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

## What a verdict does not establish

Every check above is internal: the document against its own ballots. Agreement
therefore shows that the published ballots give the published result, and no
more. Outside it, and stated in the citizen manual as well
(`docs/manuel/verifier.md`, "Ce que le vérificateur ne prouve pas"):

- **Eligibility and stuffing.** Nothing published links a ballot to a
  registration (INV-1), so the verifier cannot tell a ballot cast by an
  elector from one added. `counts` must add up with the list, but nothing
  checks them against the registrations themselves.
- **Removal or alteration of a ballot.** Shown only by an elector finding
  their tracking code, with their ranking, in `ballots`.
- **When the values were fixed.** A document rebuilt from end to end with a
  new `opening_seed` or ballot list is as consistent as the original. Only
  comparing `opening_seed` and `closure_hash` with the values shown on the
  public page at opening and closure shows that they were not
  changed afterwards.
- **CSV against document.** The verifier reads one or the other. They carry
  the same ballots exactly when their closure hashes are equal.
- **`tally_method`**, restated rather than checked (above).
- **The poll's ballot rules.** Every ranking must be one the application
  could record (`canonical-serialisation.md`, "A ranking"), but
  `require_complete_ranking` and `allow_ties_in_ballot` are not published, so
  a ballot that breaks them is not caught.
- **Labels.** `options` is read for its keys only.
- **A physical draw**, which cannot be replayed (`tiebreak`, below).
- **Ballot secrecy**, a property of the platform and its operation, not of
  anything published.

## Encoding

- UTF-8 JSON (RFC 8259), one object.
- Object keys are unique. The verifier refuses a duplicate key rather than
  keeping one of the values, so that two readers cannot find two different
  winners in the same file.
- Byte-exact formatting is **not** part of the contract, unlike the canonical
  serialisation: whitespace and key order may vary. The one exception is
  `options`, whose key order is the poll's option order and is kept by the
  verifier for display.

## Stored, not recomputed

The application stores this document, and the CSV beside it, when the poll is
published, and serves the stored text from then on. A later change to the code
cannot change a document already published.

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
| `tally_method_version` | string | read | The method version the tally ran. Restated with the method. |
| `closure_hash` | lower-case hex | **checked** | SHA-256 of the canonical serialisation of `ballots`. |
| `opening_seed` | lower-case hex | read | Input to the computed tie-break. |
| `counts` | object | **checked** | Participation frozen at closure: `registered`, `ballots_online`, `ballots_paper`, `paper_uncountersigned`, `non_voters`, each an integer and each required. The ballot list does not determine them, but they must add up with it: `ballots_online + ballots_paper = ballot_count`, and `registered = ballots_online + ballots_paper + paper_uncountersigned + non_voters`. |
| `closure_override_reason` | string | ignored | Reason given for closing despite uncountersigned entries, or `""`. |
| `options` | object: option id → labels by language | read (keys) | The poll's options, including any that no ballot ranks. Each key is an id from the alphabet of `canonical-serialisation.md`, "Alphabets"; the verifier refuses any other, as it does in a ranking. |
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
own order, compared by `option_id`. Each `draw` is shown for a reader replaying
the chain by hand and is not compared: the order it produces is.

Physical (a public draw at the mairie, entered on screen 9):

    {"rule": "physical", "tied": [id, …], "order": [id, …], "winner": id}

A program cannot replay a physical draw. The verifier checks that `tied`
equals its own set of tied winners and that `order` is a permutation of them.
It then takes the first entry of `order` as the winner.

Under either rule, `winner` is **checked**: it must be the first entry of
`order`, and the document's top-level `winner` is then compared with it like
any other winner. A `tiebreak` with no `winner`, or one that is not the first
of its order, disagrees.

With no `tiebreak` member, the recomputation must not tie. With no ballots
there is no result under any method: no winners, so no tie, and `winner` is
`null`.
