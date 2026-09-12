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
    mkdir -p var/locks var/media var/static
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

## Build status

Implemented and tested — the four CI gates (`ruff`, `ruff format`,
`mypy --strict`, `pytest`) and the Rust `cargo test` are green:

- the domain model and its migrations, and the database triggers enforcing
  INV-2, INV-3, INV-6 and INV-7;
- the transition function and its guards, the voting window, closure, the
  closure hash and publication artefacts, the tally, the tie-break, retention;
- the anonymity scheme (§7), name and address matching;
- the roll import (§6.1), the registration and review flow (§6.2), online
  casting and modification (§6.3), paper entry, correction, deletion and
  countersignature (§6.4);
- all eleven back-office screens (§6.5), the public poll and results pages and
  `GET /sante` (§6.6);
- the management commands, with the locking and state-based selection §14
  requires, and the mail templates they send;
- the `en` message catalogue (French is the msgid language);
- the independent Rust verifier and its cross-check against the Python tally;
- the Ansible role — `provision`, `deploy`, `backup`, `restore`, `smoke` (§15).

Every acceptance test T-1…T-64 (§12) has a test or a Molecule scenario.

Outstanding:

- **T-16 and T-38** run only in the dedicated CI `molecule` job — they need a
  throwaway systemd host, not the pytest database — and **T-13**'s
  screen-reader pass stays a manual step before each poll opens (the
  keyboard-only half is automated).
- No prebuilt **container image** or no-toolchain deployment guide yet, and no
  generated **third-party licence notice** (§14).
- **RGAA conformance audit** of the markup (R-14.1) and an **email
  deliverability test** to real mailboxes (§14) are pre-launch tasks, not code.
- The §13 items — first-poll option labels, enabled languages, opening and
  closing instants, the data-protection referent, the paper-workflow toggles,
  the keying window, postal enrolment, `review_all_registrations` — are wired
  as configuration and await the commune's values.

## Licence

[0BSD](LICENSE), documentation and specifications included. See
[`PROVENANCE.md`](PROVENANCE.md) for how the code was produced.
