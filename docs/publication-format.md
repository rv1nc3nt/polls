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

Those checks show the document agrees with itself, which a document rebuilt
from end to end would too. What ties it to the poll are the values its public
page showed before the result was published: the closure hash from the
closure, the opening seed from the opening. The reader passes them in
(`--closure-hash`, `--opening-seed`, or the GUI's fields), and the verifier
compares the recomputed hash and the document's seed with them. Only a
document whose ballots hash to the closure hash given is reported verified
(exit 0); one that agrees with itself but was given none is reported "not
anchored" (exit 4), never verified.

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
  new `opening_seed` or ballot list is as consistent as the original. The
  verifier catches it only against the closure hash and opening seed the
  reader noted from the public page at closure and opening, and cannot know
  whether they were noted then or read later beside the result.
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
| `tally_method` | `"schulze"` \| `"plurality"` \| `"approval"` | read, **restated** | The method the winner is recomputed under. Exactly one of the three identifiers; any other spelling is refused. |
| `tally_method_version` | string | **checked** | The method version the tally ran. The verifier refuses a version it does not implement (`SUPPORTED_METHOD_VERSIONS`, kept equal to the application's `IMPLEMENTED_VERSIONS`) rather than recount under other rules. |
| `closure_hash` | lower-case hex | **checked** | SHA-256 of the canonical serialisation of `ballots`, compared exactly: upper-case hex is not what the application writes. |
| `opening_seed` | lower-case hex | read | Input to the computed tie-break. |
| `counts` | object | **checked** | Participation frozen at closure: `registered`, `ballots_online`, `ballots_paper`, `paper_uncountersigned`, `non_voters`, each an integer and each required. The ballot list does not determine them, but they must add up with it: `ballots_online + ballots_paper = ballot_count`, and `registered = ballots_online + ballots_paper + paper_uncountersigned + non_voters`. |
| `closure_override_reason` | string | ignored | Reason given for closing despite uncountersigned entries, or `""`. |
| `options` | object: option id → labels by language | read (keys) | The poll's options, including any that no ballot ranks. Each key is an id from the alphabet of `canonical-serialisation.md`, "Alphabets"; the verifier refuses any other, as it does in a ranking. |
| `ballots` | list of `{"tracking_code": string, "ranking": [[option id, …], …]}` | read | The live set, sorted by tracking code, ids sorted within a group; the same records as the CSV. |
| `ballot_count` | integer | **checked** | Number of entries in `ballots`. |
| `winner` | option id or `null` | **checked** | The result after any tie-break. `null` only when there are no ballots. |
| `matrix` | object: id → (object: other id → integer) | **checked** | `d[i][j]`, the number of ballots ranking `i` strictly above `j`, for every ordered pair of distinct options. |
| `derivation` | object | **checked** | Schulze: `pairwise` (the matrix again), `paths` (strongest paths; each option's row empty when there are no ballots) and `winners`. Plurality and approval: `counts` (id → integer) and `winners`. `winners` are the tally's, before any tie-break, compared as a set. Each member present is recomputed and compared. |
| `serialisation_bytes` | integer | ignored | Length of the canonical serialisation. |
| `tiebreak` | object, present only if the tally tied | **checked** | See below. |
| `orderings` | object: ordering → integer | **checked** when present | Summary table, published for a Schulze poll with at most four options and shown on the results page. Each key is a ballot's groups in ranking order joined by `>`, the ids of a group sorted and joined by `=`; options a ballot does not rank are left out. Recomputed from `ballots`: the same keys, each with the same count. |

## Vectors

The rules of this page concern a whole document. Both sides run the
document corpus `tests/vectors/documents/publications.json`: whole documents
worked out by hand, and cases that change one thing in them and state the
verdict and the checks that must disagree. The application must write each
base document exactly (`test_vectors.py`); the verifier's core must reach each
verdict (`verifier/core/tests/documents.rs`), and so must its command line,
through its exit code (`test_verifier_agreement.py`). Each rule is also pinned
by a test of the verifier's core (`verifier/core/src/`) and, against documents
the application really publishes, by `tests/integration/test_verifier_agreement.py`.

| Rule | Verifier test | Agreement test |
|---|---|---|
| Encoding: unique keys | `json.rs`: `refuses_a_duplicate_key` | |
| Versioning: no or unknown `format_version` refused | `report.rs`: `a_document_without_a_format_version_is_refused` | |
| Anchoring: verified only against the closure hash noted at closure | `report.rs`: `a_consistent_document_alone_is_not_anchored`, `another_closure_hash_noted_at_closure_disagrees` | `test_a_document_alone_is_consistent_but_not_verified`, `test_a_rebuilt_document_is_caught_by_the_hash_noted_at_closure` |
| `tally_method`: the three identifiers only | `report.rs`: `the_tally_method_must_be_one_of_the_three_identifiers` | |
| `tally_method_version`: only those the verifier implements | `report.rs`: `a_method_version_this_verifier_does_not_implement_is_refused` | `test_a_method_version_the_verifier_does_not_implement_is_refused` |
| `closure_hash`: lower-case hex | `report.rs`: `the_documents_own_closure_hash_must_be_lower_case` | |
| `derivation` and `orderings` recomputed | `report.rs`: `the_published_derivation_and_orderings_are_recomputed`, `a_tampered_orderings_table_disagrees`, `a_tampered_derivation_disagrees` | `test_the_verifier_agrees_with_the_published_document`, `test_a_tampered_derivation_or_orderings_table_is_caught` |
| `closure_hash`, `ballot_count`, `matrix`, `counts` checked | `report.rs`: `a_consistent_publication_agrees_on_every_count` | `test_the_verifier_agrees_with_the_published_document` |
| `winner` checked | `report.rs`: `a_publication_claiming_another_winner_disagrees` | `test_a_tampered_winner_is_caught` |
| participation `counts` add up | `report.rs`: `participation_counts_must_add_up_to_the_ballot_list`, `a_publication_without_its_counts_is_refused` | `test_published_counts_that_do_not_add_up_are_caught` |
| `ballots` hold only rankings the application records | `report.rs`: `a_ranking_no_ballot_could_carry_is_refused_in_a_publication_too` | `test_a_ranking_the_platform_never_writes_is_refused` |
| `ballots`: tracking codes well formed and unique | `report.rs`: `a_repeated_or_malformed_tracking_code_is_refused` | `test_a_repeated_tracking_code_is_refused` |
| `options`: ids from the alphabet | `report.rs`: `an_option_id_outside_the_alphabet_is_refused` | |
| No ballots: `winner` null, no tie | `report.rs`: `a_schulze_poll_with_no_ballots_has_no_winner_and_no_tie` | |
| `tiebreak` only where the tally ties | `report.rs`: `a_publication_claiming_a_tie_that_is_not_there_disagrees` | |
| computed `tiebreak`: replayed, order compared | `report.rs`: `a_computed_tie_break_is_replayed_and_must_match` | |
| physical `tiebreak`: a draw among exactly the tied options | `report.rs`: `a_physical_draw_must_be_among_exactly_the_tied_options` | |
| `tiebreak.winner` is the first of `order` | `report.rs`: `the_tie_break_winner_must_be_the_first_of_its_order` | |

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
