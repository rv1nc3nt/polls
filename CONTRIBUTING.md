# Contributing

Contributions are welcome. Two rules keep the tree simple for the communes that
reuse it.

## Licence and sign-off

Everything in this repository is under [0BSD](LICENSE), documentation and
specifications included, so that a reusing commune has nothing to comply with.
Contributions from others carry copyright whatever the provenance of the initial
code, so every commit must carry a Developer Certificate of Origin sign-off
certifying that you may contribute the work **under 0BSD**:

    git commit -s

Without this the project becomes mixed-licence at the first pull request, and
0BSD's principal virtue is lost.

Add `SPDX-License-Identifier: 0BSD` to each new source file.

## What a change must not break

The specification (`spec-plateforme-vote.md`) is authoritative, and the
`R-x.y` numbers in it cite the functional requirements it restates. Some
properties there are impossible to retrofit; the ones to read before touching
the domain are §5 (invariants), §7 (the anonymity scheme) and §10 (the
reference-only audit log).

In particular, a change must never:

* add a column, view, index or query that joins a registration to an online
  ballot (INV-1, INV-5) — voting status lives on `Registration.channel`;
* write an elector's name, NNE or email into an audit event (§10);
* add an update or delete path to `AuditEvent` (INV-3);
* make the closure hash depend on anything but option ids and tracking codes
  (§3.8, §9);
* replace the tie-break with a language PRNG or a seeded sort (§8.3).

`mypy --strict`, `ruff` and the test suite run in CI and must be green. When the
Python tally and the Rust verifier disagree, the resolution is to return to the
specification and determine which is wrong, never to adjust the verifier until
it matches.
