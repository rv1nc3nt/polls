# Plateforme de consultation citoyenne

Self-hosted web application for a French commune to run **consultative** polls
of its registered electors. Ballots are cast online, or on paper and keyed in by
a council member. Preferential polls are tallied by the Schulze method;
single-choice and approval polls are also supported.

One instance per commune. Adoption by another commune means another instance,
never a tenant column.

Written to [`spec-plateforme-vote.md`](spec-plateforme-vote.md), which restates
the functional requirements — the `R-x.y` numbers cited throughout — in
implementation terms. Departures of the code from the specification are recorded
in [`docs/spec-divergences.md`](docs/spec-divergences.md).

## What this software is not for

**Not legally binding elections.** No strong voter authentication, no
end-to-end verifiable cryptography. The verifiability model is
publication-based: the anonymised ballot set is published, and anyone can
recompute the result and the closure hash from it.

**Receipt-freeness is not provided, and is not attempted.** A voter who keeps
their tracking code can find their own row in the published CSV and so prove to
a third party how they voted. This is inherent in publication-based
verifiability — the property that lets any reader recompute the result is the
same property that makes a ballot findable by someone holding its code. It is
accepted because the poll is consultative, and it means this software **must not
be used where coercion or vote-buying is a realistic risk**.

## Regulatory risk level, for a DPO

The CNIL's recommendation on the security of electronic voting is
**délibération n° 2026-045 of 19 March 2026** (published 24 April 2026), which
repealed the 2010 and 2019 texts, accompanied by ANSSI technical guide
**ANSSI-PA-118**; the two are designed to be read together.

**This software is designed to meet risk level 1** — a low-stakes consultative
poll, of the kind that is probably outside the scope of a text aimed at
secret-ballot elections. **It is not designed for level 2 or 3**, which is where
a participatory budget in a city of fifty thousand may well land. An adopting
commune's DPO should be able to answer the question from this section without
reading the source; if the poll in question is not clearly level 1, this is not
the right software for it.

Ballots already in preparation for 2026 may continue under the 2019 version;
any new ballot falls under the new text.

## Quick start (development)

    uv sync
    uv run python manage.py migrate
    uv run python manage.py runserver

Tests, lint and types:

    uv run pytest -q
    uv run ruff check .
    uv run mypy src tests
    cargo test --manifest-path verifier/Cargo.toml

## Installation

`ansible/` is the supported path: a bare Debian VM to a running instance by
editing one inventory file and running one command. A container image is the
alternative. `contrib/init/` carries service files for systemd, OpenRC, FreeBSD
and OpenBSD — **Debian is playbook-installed and tested in CI; the other
platforms are best effort, installation by hand.**

## Layout

    src/config/            Django project: settings, URLs, WSGI
    src/apps/core/         Types, crypto (§7), canonical serialisation (§9),
                           name matching (§6.2), tracking codes, job locking
    src/apps/elections/    Poll, options, roll snapshot, the one transition
                           function (§5.1), the voting window (INV-2), closure
                           and publication (§9), retention (§11)
    src/apps/registrations/ Registration and review — no relation to ballots
    src/apps/ballots/      Ballot and PaperBallotLink — no relation to voters
    src/apps/audit/        Append-only, reference-only audit log (§10)
    src/apps/tally/        Pure tally functions (§8); imports no model
    src/apps/backoffice/   Espace mairie (§6.5) — the majority of the build
    src/apps/publicsite/   Public pages (§6.6) and GET /sante
    verifier/              Independent Rust verifier; shares no code (§14)
    ansible/               Deployment (§15)
    docs/                  Canonical serialisation, spec divergences

## Properties that must not be broken

Read §5, §7 and §10 of the specification before touching the domain, and
[`CONTRIBUTING.md`](CONTRIBUTING.md) before opening a pull request. In short:
no query may join a registration to an online ballot; voting status lives on
`Registration.channel`; the audit log holds references and non-identifying
state only, and has no update or delete path; the closure hash depends on option
ids and tracking codes alone.

## Scaffolding status

Implemented and tested: the domain model and its migrations, the database
triggers enforcing INV-2, INV-3, INV-6 and INV-7, the transition function and
its guards, the closure hash and publication artefacts, the tally and the
tie-break, the anonymity scheme, name and address matching, the management
commands' locking and selection, and the Rust verifier with its cross-check
against the Python tally.

Not yet written: the back-office screens (§6.5), the registration and casting
flows (§6.2–§6.4) — their service functions are stubs with the specification
attached — the roll import (§6.1), the email templates, the RGAA markup, the
`.po` catalogues, and the bodies of the Ansible tasks.

## Licence

[0BSD](LICENSE), documentation and specifications included. See
[`PROVENANCE.md`](PROVENANCE.md) for how the code was produced.
