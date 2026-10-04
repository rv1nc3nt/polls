<!-- SPDX-License-Identifier: 0BSD -->

# Shared test vectors

One set of cases, read by both implementations (review D-2):

- `tests/integration/test_vectors.py` runs them against the application;
- `verifier/core/tests/vectors.rs` runs them against the verifier's core.

Neither side keeps its own copy of an expected value, so a change to either
implementation that alters a result fails here, on the side that changed.
`tests/integration/test_differential.py` adds a thousand seeded random cases,
written in this same format with the application's results as expectations,
and hands them to the verifier's runner.

## Format

Each file is `{"format": 1, "cases": [...]}`. A case:

| Member | Meaning |
|---|---|
| `name` | Shown when the case fails. |
| `source` | Where the expected values come from (below). |
| `method` | `schulze`, `plurality` or `approval`. |
| `options` | The poll's option ids, in its order. |
| `ballots` | The live set: `{"tracking_code": …, "ranking": [[id, …], …]}`. |
| `opening_seed` | Optional, hex. Given a tie, the hash-chain draw is checked too. |
| `expect` | The results, or absent for a case that must be refused. |
| `refuse` | Instead of `expect`: the refusal the input must meet. |

`expect` holds `closure_hash` (hex), `matrix` (`d[i][j]` for every ordered
pair), `winners` (sorted; more than one is a tie), `counts` (plurality and
approval; `null` under Schulze) and `tiebreak_order` (the draw's order, or
`null` with no seed or no tie).

`refuse` is one of:

| Kind | The application refuses it in | The verifier answers |
|---|---|---|
| `tracking_code` | `core.canonical.check_alphabets` | `MalformedTrackingCode` |
| `duplicate_tracking_code` | the database's unique constraint (INV-11) | `DuplicateTrackingCode` |
| `ranking` | `ballots.ranking.validate_ranking` | `MalformedRanking` |
| `option_id` (in a ranking) | `core.canonical.check_alphabets` | `MalformedRanking` |
| `listed_option_id` | `PollOption`'s trigger and form | `MalformedOptionId` |

## Where the expectations come from

A vector whose expected values were simply copied from one implementation
proves only that the other agrees with it (review D-1). Each case's `source`
says which kind it is:

- **outside the project**: the SHA-256 of the empty string (FIPS 180-4), and
  the 45-voter example of M. Schulze, *Social Choice and Welfare* 36 (2011),
  §3.1, whose pairwise matrix and winner are those printed there;
- **hand-worked**: small enough to check on paper, and checked;
- **derived by hand from the contract**: `derive-by-hand.sh` recomputes the
  T-9 case's closure hash and tie-break order, and the T-44 order, from
  `canonical-serialisation.md` and spec §8.3 with printf, xxd and OpenSSL
  alone; `test_vectors.py` checks that it agrees;
- **a documented value**: the worked vector of `canonical-serialisation.md`
  (T-42) and the acceptance tests named;
- **application**: the random cases only, which test agreement, not truth.

Beyond the corpus, `tests/integration/test_independent_schulze.py` compares the
application's pairwise counts, strongest paths and winners with `votelib`, an
implementation neither side wrote, on the same random polls; and the
verifier's SHA-256 is held to the FIPS 180-2 examples and to padding-boundary
digests computed with OpenSSL and coreutils (`verifier/core/src/sha256.rs`).

## Whole publication documents

`documents/publications.json` holds the same kind of cases one level up: whole
publication documents (`docs/publication-format.md`), in a subdirectory so the
ballot-level runners above do not read it. It is `{"format": 1, "bases": {…},
"cases": [...]}`.

A **base** is a complete, honest document with its `source`. Its ballots,
closure hash, matrix and winners are those of a case above; its strongest
paths and orderings are hand-worked; its draws and `serialisation_bytes` are
derived by `derive-by-hand.sh`; its counts, labels and ids are chosen to add
up. `test_vectors.py` checks that the application's writer
(`elections.closure.compose`) produces each base exactly.

A **case** names a `base`, applies its `edits` in order, and states what the
verifier must make of the result:

| Member | Meaning |
|---|---|
| `edits` | Each `{"set": path, "value": v}`, `{"remove": path}` (an object member), or `{"append_member": key, "value": v}` (to the document itself, even if the key is there: a duplicate key). A path is a list of member names and list indices. |
| `anchors` | `closure_hash` and `opening_seed`, as a reader noted them; either may be absent. |
| `verdict` | `verified` (exit 0), `differs` (1), `refused` (2, the document cannot be read) or `not_anchored` (4). |
| `differs` | With `differs` only: exactly the checks that disagree, sorted: `ballot_count`, `closure_hash`, `counts`, `derivation`, `hash_at_closure`, `matrix`, `orderings`, `participation`, `seed_at_opening`, `tiebreak`, `winner`. |

`verifier/core/tests/documents.rs` holds the verifier's core to each verdict
and list; `test_verifier_agreement.py` runs the command line on each and
checks its exit code and the lines it prints as `DIFFERS`. A case's expected
verdict is worked out from the edit and the contract, like any other vector.

## Adding a case

Write the input, work out the expected values by hand or from a published
source, and add both. Run `uv run pytest tests/integration/test_vectors.py`
and `cargo test --manifest-path verifier/Cargo.toml --test vectors`: a case
both sides pass goes in. If one side disagrees, that is the finding, and the
specification decides which is wrong, never a change to the vector to match.
