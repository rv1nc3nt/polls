<!-- SPDX-License-Identifier: 0BSD -->

# Threat model

Who could learn or change what, on one instance of this platform, and what
stops them. It gathers what spec §5 and §7, the review guide ("Security- and
privacy-sensitive areas") and the decision log already state, and adds the
boundaries none of them drew in one place. Where a guarantee has a limit, the
limit is stated here rather than left to be discovered.

The platform runs **consultative** polls for one commune. It is not built for,
and must not be used for, a vote where coercion or vote-buying is a realistic
risk (spec §7, "Receipt-freeness is not provided").

## What is protected

| Asset | Property | Held by |
|---|---|---|
| How an elector voted online | Secrecy: nobody can link an online ballot to the elector who cast it | INV-1, INV-5, §7 |
| The result | Integrity: the published ballots give the published result, checkably by anyone | §9, the independent verifier |
| A published ballot | Integrity: an elector can find their own ballot, unchanged, by its tracking code | §9 |
| Identity data (roll, registrations) | Confidentiality, and deletion on schedule | back-office roles, the retention purge (§11) |
| The audit log | Completeness: it cannot be edited or pruned | INV-3, by trigger |
| The poll's rules | Immutability once announced | INV-6, by trigger |

## What is not protected

Deliberately, and said so to the people concerned:

- **Receipt-freeness.** An elector who keeps their tracking code can show a
  third party their row in the published list. Publication-based
  verifiability cannot avoid this (spec §7).
- **Paper ballots** are linked to the elector on purpose (`PaperBallotLink`),
  for countersignature, correction and deletion (R-8).
- **Who voted** is visible to the poll administrator, never how or when
  (R-7.5). The paper channel needs it.
- **Participation across two polls** can be correlated by someone reading both
  polls' identity data directly, since name and date of birth are stable
  (R-13.4 bis). The commune accepts that risk; access to the data and the
  retention period contain it.

## Adversaries

### The public

Anyone on the internet, electors included. They see what the site publishes:
the poll pages, then the anonymised ballot list (tracking code and ranking),
the publication document and, from opening and closure, the opening seed and
the closure hash.

- **Cannot** link a published ballot to an elector: the list holds no voter
  data and, since decision log #42, no time or order either.
- **Cannot** read a sandbox poll or a draft without its share link (INV-8,
  R-3.10 bis).
- **Can** check the result with the verifier, and find their own ballot by its
  code. The verifier's own limits are listed in the citizen manual
  (`manuel/verifier.md`, "Ce que le vérificateur ne prouve pas").
- **Abuse** is limited by rate limits on registration and sign-in (keyed on a
  salted digest of the address, never the address itself), by the setup code
  that guards a fresh instance (#43), and by a strict Content-Security-Policy
  and server-side Markdown sanitising on everything an operator writes (#44).
- **Ballot tokens** never reach a log, a `Referer` header or a cache: they
  travel in the path of the ballot routes, which nginx does not log (#43),
  which Django's log filter redacts, and which answer with
  `Referrer-Policy: no-referrer` and `Cache-Control: no-store`. The token is
  exchanged for a session at once (§6.3), and the session holds only the
  `ballot_hash`. Until decision log #51, nginx added its own `same-origin` policy,
  which browsers applied instead, so on deployed instances the token did
  travel in the `Referer` of same-origin requests and could reach the access
  log.

### The mail relay

The SMTP relay the commune configures (screen 12), its logs, and the elector's
own mail provider.

- **Sees the token.** The confirmation mail carries the elector's ballot link,
  token included: it is the only place the token exists (§7). Whoever reads
  that message can vote, or modify a ballot, in the elector's place.
- **Sees the ballot.** The receipt mailed at casting (R-6.4, decision log #6)
  holds the ranking and the tracking code, and the tracking code is published.
  Whoever can read the relay's queue or logs can therefore match an address to
  a published ballot, outside the application and beyond its retention purge.
- INV-1 holds inside the database, not here. The commune chooses a relay it
  trusts, and its data-protection notice should say that mail passes through
  it.

### Someone holding a copy of the database

A stolen backup, a read-only account, a disk image: everything in
`db.sqlite3` at one moment, `token_salt` included.

- **Sees** the roll and the registrations (names, dates of birth, addresses,
  each one's voting channel), the ballots (ranking, tracking code, and
  `ballot_hash` where modification is allowed), the audit log and the session
  table.
- **Cannot** link an online ballot to its elector. No column or relation joins
  them (INV-1); the registration stores `voter_hash` and the ballot
  `ballot_hash`, two digests of a token that is never stored (§7); a ballot
  carries no time and the table no insertion order (`WITHOUT ROWID`, #42);
  nor does the session table, whose voter rows hold a receipt or a ballot
  hash (`WITHOUT ROWID`, #53), and whose expiries are rounded to the day and
  deleted once past.
- **Residual** (#42, #53): a trend point's day remains, and a registration's
  creation instant, which is exact. A day with one ballot and one
  registration pairs them. SQLite's write-ahead log keeps recent pages in write order until its
  next checkpoint; the nightly backup (`VACUUM INTO`) does not carry it, but a
  copy of the live files might. The optional PostgreSQL backend stores rows in
  insertion order and would need its own answer before being offered.
- **Combined with the mail relay**, the copy is enough: the token from a
  confirmation mail gives `voter_hash` and `ballot_hash`, and so both rows.
  Backups are therefore part of ballot secrecy: the deploy keeps them private
  to the service account (a `0700` directory, written under `umask 077`), and
  an off-host copy needs the same care.
- Identity data is purged two months after closure (§11); a copy taken before
  that keeps it, which the purge cannot reach.

### Back-office operators

Named accounts in the espace mairie, each with a role on given polls
(`poll_admin`, `entry_operator`, `auditor`) or the commune-level
`commune_admin`.

- Every poll screen checks the operator's role on that poll
  (`require_poll_role`); `commune_admin` grants nothing on a poll, and
  `is_superuser` is never consulted. A grant is itself audited.
- **Can**, as poll administrator, see who has voted and by which channel, but
  never how (R-7.5): the screens show two lists that cannot be joined.
- **Vote as electors**, like anyone else, and their own ballot is no more
  linked to them than another's: their session, which names them, is signed
  out before any ballot route runs, and signing in drops any ballot data the
  browser held (decision log #49).
- **Can**, as entry operator, key a paper ballot, which is linked to the
  elector by design.
- **Cannot** change a rule once the poll is announced (INV-6), rewrite or
  delete an audit event (INV-3), alter a superseded ballot (INV-3), or move a
  deadline without a reason that is logged and shown publicly (R-3.4).
- **Cannot** change the result unseen: closing and publishing are logged, the
  closure hash is shown at closure and the seed at opening (#40), and the
  published artefacts are stored once, by trigger (#41).
- Definitive actions pass a confirmation page first (R-2.4), against mistakes
  rather than malice.
- A sign-in lasts eight hours from the moment it was made, enforced on the
  server rather than by the cookie alone, so a browser left signed in on a
  shared mairie PC does not keep these screens open for days (review A-16).

### The instance operator

Whoever has root on the server, or deploys its code: the commune's IT contact
or its provider.

- **Can do anything the database reader can**, at any moment.
- **Can change the software.** A modified application could record tokens as
  requests arrive, or the time of each ballot, and nothing inside the
  application can prevent that. The secrecy guarantee against the operator is
  therefore a guarantee about the past: a copy of the data taken afterwards
  cannot link ballots to electors, but an operator who alters the code during
  the vote can.
- **Cannot change the result undetected**, as long as electors and observers
  check:
  - an elector who finds their own tracking code, with their ranking, in the
    published list sees that their ballot was counted unchanged;
  - an observer who notes the opening seed and the closure hash when they
    appear, and compares them after publication, sees that neither was
    changed afterwards;
  - anyone can recompute the result from the published ballots with the
    verifier, which shares no code with the application.
- **Can add ballots** in the names of electors who did not vote, adjusting the
  participation counts to match. The published list cannot show this: it does
  not say who voted (`manuel/verifier.md`, "Ce que le vérificateur ne prouve
  pas"). Only the commune's own records could, and they are kept by the same
  operator. This is the main limit of the model.
- What the operator runs can be compared with the source: releases carry
  checksums and build-provenance attestations for the verifier (#46), and the
  application's source is public under 0BSD. Whether a given server runs that
  source cannot be proven from outside.

## Assumptions

- TLS between browsers and nginx. The deploy enables it by default
  (`polls_enable_tls`); an instance that turns it off loses every guarantee
  about tokens in transit.
- The server's clock is right: the voting window is enforced on it (decision
  log #33).
- The verifier a citizen runs is the published one, checked against its
  checksums or built from source (`manuel/verifier.md`).
- Electors keep their confirmation mail private, and some of them check their
  tracking code after publication.

## Where each point is enforced

The review guide's table ("Invariants and where they are enforced") gives the
module, trigger and test for each invariant. The decision log records each
choice cited here by number.
