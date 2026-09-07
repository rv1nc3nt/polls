# Implementation Specification — Commune Polling Platform

**Client:** Commune de Sainte-Marie-du-Mont (Isère), France
**Status:** v0.21 — implementation-ready functional spec. Stack decided (§14).
**Audience:** implementing agent / developer.

The authoritative functional requirements are the French document *Cahier des charges fonctionnel*, requirement numbers `R-x.y`. This document restates them in implementation terms and adds the domain model, algorithms, invariants and acceptance tests. Where the two diverge, the French document governs and this one is to be corrected. Cross-references to `R-x.y` appear throughout.

---

## 0. How to read this

- Requirements marked **MUST** are load-bearing; several encode privacy or integrity properties that are impossible to retrofit (§7 in particular).
- Items listed in §13 are undecided by the client. Implement them as configuration, never as constants.
- The interface is multilingual, French by default (§3.8). Identifiers, code and comments are in English. §2 maps the French terms.
- Reference convention: `R-x.y` and `R-n` refer to the French *Cahier des charges fonctionnel*; `§n` refers to a section of **this** document. `INV-n` and `T-n` are defined here at §5 and §12.

---

## 1. Scope

Build a self-hosted web application allowing a single French commune to run consultative polls of its registered electors. Ballots are cast online, or on paper and keyed in by a council member. Preferential polls are tallied by the Schulze method; single-choice and approval polls are also supported (§8).

The software is released as open source, one instance per commune. **Non-goals.** Multi-commune tenancy: adoption by another commune means another instance, never a tenant column (R-1.3). Larger adopters are served by the optional PostgreSQL backend (§14), not by shared hosting. Legally binding elections. Strong voter authentication. End-to-end verifiable cryptographic voting: the verifiability model here is publication-based (§8), which is appropriate for a consultative poll and much simpler.

---

## 2. Glossary

| French term | Meaning in code |
|---|---|
| *scrutin* | poll |
| *bulletin* | ballot |
| *électeur* | voter / elector |
| *liste électorale* | electoral roll |
| *numéro national d'électeur* (NNE) | national elector number; 8–9 digits, permanent, nationwide |
| *copie figée* | frozen roll snapshot |
| *opérateur de saisie* | entry operator (a council member) |
| *récépissé* | receipt |
| *code de suivi* | tracking code |
| *tirage au sort* | drawing of lots / tie-break |
| *dépouillement* | tally |
| *mairie* | town hall |
| *conseil municipal* | municipal council |

---

## 3. Domain model

### 3.1 `Poll` (R-3.1)

| Field | Type | Notes |
|---|---|---|
| `id` | uuid | |
| `title`, `description` | text | French, voter-facing |
| `options` | ordered list of `{id, label}` | ≥ 2 |
| `opens_at`, `closes_at` | timestamptz | timezone stored explicitly |
| `paper_entry_deadline` | timestamptz | `≥ closes_at`, default equal to it; the paper keying window (§6.4) |
| `tally_method` | enum | `schulze` \| `plurality` \| `approval` |
| `tally_method_version` | string | pinned; R-10.2 |
| `require_complete_ranking` | bool | |
| `allow_ties_in_ballot` | bool | |
| `tiebreak_rule` | enum | `computed` \| `physical` |
| `opening_seed` | bytes(32) | generated at `open`; published |
| `token_salt` | bytes(32) | generated at creation; **never published** |
| `paper_requires_signed_form` | bool | default false; R-8.2 |
| `paper_requires_countersign` | bool | default false; R-8.7 |
| `paper_requires_reconciliation` | bool | default false; R-8.6 |
| `allow_ballot_modification` | bool | default true; R-7.1. Immutable once open, and disclosed on the ballot page |
| `languages` | list | enabled content languages, first is the default; `["fr"]` unless configured (§3.8) |
| `show_live_participation` | bool | default false; see §6.6 |
| `is_sandbox` | bool | immutable after creation; R-3.7 |
| `state` | enum | `draft` \| `open` \| `closed` \| `published` |
| `closure_hash` | bytes(32) | set at `closed` |

A typical configuration: `schulze`, `require_complete_ranking = true`, `allow_ties_in_ballot = false`, three options — the case for which the six-row summary table of §9 applies.

### 3.2 `RollEntry` — frozen snapshot (R-4.3)

`{poll_id, last_name, first_names, nne}`. Copied from the current roll at the `draft → open` transition. Immutable thereafter. `(poll_id, nne)` unique.

### 3.3 `Registration` (§6.2)

`{poll_id, nne, last_name, first_names, email, email_canonical, declared_on_honour, state, review_reason, voter_hash, channel, language, created_at}`

- `state ∈ {pending_email, pending_review, active, rejected}`
- `language`: the language chosen at registration; determines the language of every email sent to this person (§3.8).
- `email_canonical`: the address lower-cased, nothing more. `(poll_id, email_canonical)` unique — one elector, one address (§6.2). No alias normalisation: `+suffix` and dot handling are provider conventions, and any rule about them either merges distinct people or gives false assurance about the ones it misses.
- `channel ∈ {none, online, paper}` (R-9.1)
- `voter_hash = H("voter" ‖ poll.token_salt ‖ token)` (R-7.4)
- `(poll_id, nne)` unique (R-5.9)
- Scoped to one poll. A person voting in two concurrent polls has two rows, two tokens. This is required by R-13.4 and is not a bug.

### 3.4 `Ballot`

`{id, poll_id, ballot_hash, tracking_code, version, ranking, source, status, created_at}`

- `id`: uuid primary key, referenced by `PaperBallotLink`.
- `ballot_hash = H("ballot" ‖ poll.token_salt ‖ token)` for online ballots; **null** for paper ballots, which are reached through `PaperBallotLink` instead, and **null for every ballot when `allow_ballot_modification` is false** (§7).
- `ranking`: ordered list of option ids; ties expressed as nested groups when `allow_ties_in_ballot`.
- `source ∈ {online, paper}`.
- `status ∈ {live, superseded, deleted, pending_countersign}`. Exactly one row per logical ballot is `live`. `deleted` is a paper ballot withdrawn by an operator (R-8.5, R-9.4) — rows are never physically removed. `pending_countersign` is a paper entry awaiting a second operator where `paper_requires_countersign` is set.
- Append-only. A modification inserts `version + 1` and sets the prior row to `superseded` (R-7.2). Only the `live` row counts.
- **The live ballot set** — what the tally counts, what the closure hash covers, and what is published — is exactly the rows with `status = live`. `superseded`, `deleted` and `pending_countersign` are excluded from all three, without exception.
- `tracking_code`: random, human-transcribable (avoid ambiguous glyphs: no `O/0`, `I/1`), stable across versions of the same ballot. Issued when the ballot is created, never at registration (§6.2). `(poll_id, tracking_code)` unique, as a database constraint (INV-11).

### 3.5 `PaperBallotLink`

`{poll_id, ballot_id, nne, operator_id, countersigned_by, created_at}`. Paper ballots stay linked to the voter — deliberately (R-8.2 bis). Deleted at retention (R-13.3).

### 3.6 `AuditEvent` (R-12; see §10)

`{id, poll_id, actor_id, action, object_ref, before, after, reason, at}`. Append-only, no update or delete path in the application at all. `object_ref` points at a row; `before`, `after` and `reason` never contain an elector's name, NNE or email (§10).

### 3.7 `User`

Named accounts only (R-2.2). Per-poll role assignments (R-2.1): `poll_admin`, `entry_operator`, `auditor`. Commune-level: `commune_admin`.

### 3.8 Languages and translation

The application ships French and English. French is the default and, for a French commune, the authoritative version: where a translation and the French text diverge, the French text governs, and the interface says so on the pages that carry legal effect — the consultative-status notice (R-1.4) and the privacy notice (R-13.2). A translation of those is informational.

Two distinct things are translated, by different means:

- **Interface strings** — labels, buttons, emails, error messages — through Django's `gettext` and `.po` catalogues, for both the public site and the back-office. Adding a third language must require no code change.
- **Poll content** — `title`, `description`, and each option's `label` — is per-poll data and cannot live in a catalogue. Store it as `{language_code: text}` maps, or an equivalent translation table, keyed on the poll's enabled `languages`.

Rules:

- A poll may not leave `draft` while any enabled language lacks a translation of the title, the description or any option label. The configuration screen shows the gaps.
- At render time a missing translation falls back to the poll's default language, never to an empty string.
- Emails use `Registration.language`. The receipt for a paper ballot uses the language selected by the operator at entry, defaulting to the poll default.
- Language is selected by URL prefix (`/fr/…`, `/en/…`) with Django's `i18n_patterns`, so a ballot link is language-explicit and shareable.
- **Translations never touch the tally or the hash.** `ranking` stores option **ids**; the canonical serialisation of §9 contains ids and tracking codes only. Labels appear in the publication as a separate lookup table. A translation added or corrected after closure therefore cannot change the closure hash or the result — a property the verifier depends on.

---

## 4. State machine

`draft → open → closed → published`, irreversible (R-3.2).

- `draft`: configuration mutable.
- `open`: configuration frozen (R-3.3). Only `closes_at` may be extended, with a logged reason, displayed publicly (R-3.4). Snapshot taken and `opening_seed` generated on entry.
- `closed`: the cutoffs of INV-2 are enforced server-side on every write path, not only in the UI (R-3.5). `closure_hash` and the participation counts of §9 are computed on entry. The tally is **not** automatic: an operator runs it from the back-office (§6.5, §8), since it is a pure function that gains nothing from running early and a `physical` tie-break stops for a human in any case.
- `published`: results and artefacts public.

Extension of `closes_at` is permitted only while `state = open` and only to a later timestamp; `paper_entry_deadline` moves with it, preserving the configured window length.

**Both boundary transitions are scheduled, and neither is trusted to be punctual.** `draft → open` is performed by the `open_poll` command at `opens_at`, `open → closed` by `close_poll` at `paper_entry_deadline` — which equals `closes_at` unless a keying window is configured (§6.4). The job moves the state; the instants themselves are enforced independently on every ballot write path, which refuses a ballot falling outside the window for its source whatever `state` happens to say. A job that runs late, twice, or not at all therefore cannot admit a ballot outside that window — the reasoning of INV-2, applied at both ends.

Opening is the transition with side effects: it takes the roll snapshot (§6.1) and generates `opening_seed`, and both MUST occur in the same transaction as the state write, so that two concurrent runs cannot produce two snapshots or two seeds. Selection is state-based — `state = draft AND opens_at ≤ now` — so a host that was down opens the poll late rather than never.

**Opening can be refused, and a refusal must be loud.** The preconditions of §3.8 (no enabled language missing a translation) and of §6.1 (a roll to snapshot) are checked by the job, at an hour when no operator is watching. `open_poll` refuses such a poll, leaves it in `draft`, logs the blocking reason and exits non-zero; it never opens a partially configured poll. A silent non-opening being the worst outcome here, the dashboard (§6.5) names the blockers in advance rather than on the morning itself.

**Closure can be refused too, and identically.** Where any ballot is still `pending_countersign`, the §9 guard applies to the scheduled job as well: `close_poll` refuses, leaves the poll in `open`, logs the blocker and exits non-zero. This is safe rather than dangerous — the window checks already refuse every ballot write past `paper_entry_deadline` regardless of `state`, so the poll is closed in substance while the state field waits for the countersignatures, or for the admin override, which carries a mandatory reason and cannot be automated. The dashboard shows the blocking count.

---

## 5. Invariants

These MUST hold and should each have a test.

- **INV-1** No query joins `Registration` to `Ballot` for online ballots. There is no column, view or index that permits it (R-7.4).
- **INV-2** The voting window, by source: no `Ballot` write before `opens_at`; no **online** ballot write at or after `closes_at`; no **paper** ballot write at or after `paper_entry_deadline` (§6.4); no `Registration` write after `closes_at`. The retention purge (§11) is the sole exception, and is exempted by name in the trigger rather than by loosening the rule.
- **INV-3** No update or delete on `AuditEvent` or on superseded `Ballot` versions. Absolute, with no exception for the retention purge: audit events hold no personal data to redact (§10).
- **INV-4** `(poll_id, nne)` is unique across registrations (R-5.9).
- **INV-5** A voter holds at most one live ballot per poll, across both channels (R-9). This is enforced **through `Registration.channel`**, never by counting ballots: for online ballots no link to the voter exists, and none may be added. `Ballot` MUST NOT carry a voter, registration or NNE reference. Adding one to satisfy this invariant would destroy INV-1.
- **INV-6** Poll configuration fields other than `closes_at` are immutable once `state ≠ draft`.
- **INV-7** `RollEntry` rows are never modified after the snapshot.
- **INV-8** Sandbox polls never appear in public listings or aggregate statistics (R-3.7).
- **INV-9** Tally reads only ballots; it never reads registrations.
- **INV-10** `(poll_id, email_canonical)` is unique across registrations (§6.2).
- **INV-11** `(poll_id, tracking_code)` is unique across ballots. The canonical serialisation of §9 sorts on the tracking code and the published CSV is keyed on it, so a collision would make the closure hash ambiguous.

---

### 5.1 Enforcing the lifecycle without a type system

Python cannot make an illegal transition a compile error, so the enforcement is layered and each layer must be present.

**One transition function.** All state changes go through a single guarded function holding the transition table; no view, no admin action and no management command mutates `Poll.state` directly. A test asserts that `state` is assigned in exactly one module. If a maintained `django-fsm` fork is used, it expresses the table declaratively — but it is a convenience over this rule, not a substitute.

**Configuration immutability (R-3.3)** is enforced in `Poll.save()`: when `state != draft`, any change to a configuration field other than `closes_at` raises. Backed by a database trigger, since `save()` is bypassed by `update()`, `bulk_update()` and raw SQL.

**The voting window (INV-2)** is checked in one service function that every ballot write path calls, taking the poll and the current time, and rejecting a write outside the window for that ballot's source — before `opens_at`, at or after `closes_at` for an online ballot, at or after `paper_entry_deadline` for a paper one. It does not consult `state`, since the scheduled transition may not have run yet (§4). This is the invariant the typestate approach could not have delivered either, since elapsing time is not a method call; here as there, the clock is consulted at the point of use. The retention purge is the one writer permitted past `closes_at`; it goes through a separate, named service function of which it is the only caller.

**Database triggers are the real enforcement.** INV-3, INV-6 and INV-7 are `RunSQL` migrations creating `RAISE(ABORT)` triggers, which hold against `update()`, raw SQL, the Django shell and a future maintainer who has not read this document. INV-4 is a `UniqueConstraint` on `(poll, nne)`. Application-level checks alone survive only as long as every future code path remembers them.

**INV-1** — no query joining `Registration` to `Ballot` — has no schema expression here: the models share no foreign key, and the models module must define no relation between them. Assert with a test that inspects the model metadata, and keep the two in separate service modules so a join has no natural place to be written.

**Recovering part of the static checking.** `mypy --strict` in CI, with `VoterHash` and `BallotHash` as distinct `NewType`s over `bytes` and no conversion between them, catches argument confusion at check time — the one property from the typestate design that transfers. `Token` defines `__repr__` to redact and is never interpolated into log messages.

## 6. Flows

### 6.1 Roll import (R-4.2, R-4.5)

Accept `.xlsx` and `.csv` (UTF-8 and Latin-1; sniff and let the operator confirm). Steps: upload → column mapping UI → validation report (missing fields, malformed NNE, duplicate NNE, duplicate name+NNE mismatch) → preview → explicit confirmation → transactional apply, all-or-nothing. Log filename, SHA-256 of the file, row count, operator. A new import replaces the working roll entirely and does not touch snapshots of already-open polls.

### 6.2 Registration (§5)

1. Form: last name, first names, NNE, email, honour-declaration checkbox (R-5.2). Include help text: the NNE is on the *carte électorale*, obtainable from the mairie, or via the *Interroger sa situation électorale* service.
2. Match on NNE against the snapshot (R-5.3). Name comparison uses NFKD normalisation, diacritic stripping, case folding, hyphen and apostrophe normalisation, particle handling (`de`, `du`, `le`, …), and order-insensitive comparison of first names.
3. Lower-case the email and reject if `(poll, email_canonical)` already exists: one elector, one address. Show the same neutral message as case 6 and do not disclose the existing registration. Note for the mairie: a couple sharing a single address cannot both register online; their route is the paper channel at the mairie, and the back-office help text must say so.

   The rule is uniqueness of the address as given, not of the underlying mailbox, which cannot be determined from outside: aliases, forwarding and catch-all domains all defeat it. What this buys is that the same address is not reused; the guarantee that a token is private to one person rests on the elector choosing an address only they read, which the registration page should say plainly.
4. Outcomes (R-5.4): NNE found + name consistent → `pending_email`; NNE found + name divergent → `pending_review`; NNE absent or blank → `pending_review`.
5. `pending_review` approved by a poll admin → `pending_email`, never straight to `active`: the mailbox is confirmed in every path. Rejection and approval both logged with a reason.
6. NNE already registered → refuse, show a message directing the person to the mairie, log the attempt, flag it to the poll admin (R-5.9). Do not reveal any detail of the existing registration.
7. Confirmation email carries the ballot link and the modification link (R-5.6), and MUST state that losing the email means losing the ability to modify the ballot, which nonetheless still counts (R-7.6). It carries **no tracking code**: the code belongs to a ballot, and no ballot exists yet. Issuing one here would put the same value on a `Registration` row and a `Ballot` row, which is a join in all but name and destroys INV-1 and INV-5 — the 1:1 correspondence between a registration and the ballot it leads to is real, and §7 exists precisely to make it uncomputable. The code is issued at cast (§6.3) and on the paper receipt (§6.4); a voter who registers and never votes has none, which is correct. **Divergence flagged for the French document (§0):** if R-5.6 is read as requiring the tracking code in the registration email, the only safe implementation is a value derived from the token, `base32(truncate(SHA256("track" ‖ poll.token_salt ‖ token)))`, stored nowhere — and INV-11 must then be reworded to tolerate a derived value that cannot be re-rolled on collision.
8. Reminder email 48 h before `closes_at` to `active` registrations with `channel = none` (R-5.7).
9. Rate-limit registration and email-sending endpoints (R-5.8).

### 6.3 Casting and modifying (R-6, R-7; anonymity scheme at §7)

Ballot page validates against `require_complete_ranking` and `allow_ties_in_ballot`. Option display order is shuffled per voter (R-6.2). Drag-and-drop MUST have a keyboard- and screen-reader-usable alternative — numbered selects or up/down buttons (R-6.3, R-14.1). On submit, show the recorded ranking and the tracking code, and email both.

Modification, where `allow_ballot_modification` is set: the link resolves the token → `ballot_hash` → current ballot, and writes a new version. Unlimited until closure (R-7.1).

Where it is not set, the ballot is cast once. The ballot page MUST say so before submission, not merely in the confirmation, since it changes what the voter is agreeing to. The token is spent on casting and any later use of the link is refused. Operator correction of a **paper** ballot (R-8.5) is unaffected: that is the repair of a keying error, logged and reasoned, not the voter changing their mind.

**Token handling on these routes (MUST).** The token arrives in the URL, so on first use the server exchanges it for a session cookie and redirects to a token-free URL; the token is not resent on subsequent requests. These routes send `Referrer-Policy: no-referrer` and `Cache-Control: no-store`, and the nginx template suppresses request-URI logging for their path prefix. Without all four, §7's requirement that the token never reach a log is false the moment the first voter clicks the link.

### 6.4 Paper entry (R-8)

Operator searches the snapshot by name or NNE, is shown near-matches, and confirms the elector (R-8.3). Then: check `channel`.

- `channel = paper` already → this is an edit of the existing ballot, not a new one.
- `channel = online` → blocking red interstitial; proceed only on explicit confirmation with a mandatory reason, both logged; the UI should first suggest that the voter modify their own ballot online (R-9.3).
- `channel = none` → proceed.

Entry produces a printable receipt bearing the tracking code (R-8.4). Correction and deletion require a reason and are logged with before/after (R-8.5). Deletion clears `channel` and re-enables online voting (R-9.4). If `paper_requires_countersign`, the entry is written with `status = pending_countersign` and is not counted until a second named operator validates it, which sets it to `live`.

**The keying window.** Paper ballots may be entered until `paper_entry_deadline`, which is `closes_at` unless a window is configured (§3.1). Keying is transcription, not voting: the ballot was cast physically before `closes_at` and the signed form evidences that (R-8.2), while the keystroke timestamp is a clerical artefact. Online voting stops at `closes_at` regardless, and a commune wanting no window leaves the deadline at its default, where the distinction never appears. Countersignature is itself a write to the ballot and is permitted for the same window, so screen 7's queue stays usable up to the deadline. Both instants are shown publicly (§6.6): a period in which ballots can still enter the database is exactly the thing that looks bad when discovered rather than announced.

If the voter has a paper ballot and attempts to vote online, refuse and direct them to the mairie (R-9.2).

---

### 6.5 Back-office (espace mairie)

The administrative interface is purpose-built, not Django admin. It is used by council members and mairie staff, not by developers, and it therefore falls under RGAA like the rest of the site (R-14.1), must be in French, and must not expose destructive actions beside routine ones. Django admin is not included in the production URL configuration at all.

Screens, all scoped to a poll and gated by the per-poll roles of §3.7:

1. **Tableau de bord** — state, opening and closing instants, registered / confirmed / voted counts by channel, pending review count, and the actions permitted in the current state. While the poll is in `draft` it also names every condition that would make `open_poll` refuse — a missing translation, an absent roll snapshot — so a gap is visible before the opening hour rather than at it (§4). In `open` it likewise names what would block `close_poll` — *clôture bloquée : n bulletins en attente de contreseing*.
2. **Configuration du scrutin** — editable only in `draft`; read-only thereafter, with the closing-date extension (R-3.4) as a separate, reasoned action.
3. **Import de la liste électorale** — upload, column mapping, validation report, preview, explicit confirmation (R-4.5).
4. **File d'attente des inscriptions** — registrations pending review, with roll search and near-match display; accept or reject with a mandatory reason (R-5.4).
5. **Saisie d'un bulletin papier** — elector search against the snapshot, near-match confirmation, the blocking collision interstitial of R-9.3, ranking entry, then a printable receipt (R-8.4) rendered as an HTML page with a print stylesheet.
6. **Rectification et suppression d'un bulletin papier** — reason mandatory, before/after logged (R-8.5).
7. **Contreseing** — queue of entries awaiting a second operator, present only where `paper_requires_countersign` is set.
8. **Journal d'audit** — read-only, filterable by actor, date and object; visible to auditors.
9. **Clôture et publication** — closure hash, tally derivation, tie-break computation where applicable, and the publication action.
10. **Comptes et rôles** — operator accounts and per-poll role assignment.
11. **Première installation** — a first-run wizard creating the commune record and the initial administrator, so an adopting commune never runs `createsuperuser`.

Two rules govern all of them. Every mutating screen posts through the service functions of §5.1; no view writes through the ORM directly. And no screen anywhere displays a voter's identity alongside ballot content, except on the paper-entry screen, where the association is deliberate and logged.

This back-office is the majority of the build. It should be scheduled first, before the tally, the verifier and the publication artefacts, which are the parts most likely to be built for pleasure and least likely to be the reason the project stalls.

### 6.6 Public poll page

While the poll is open the page shows the propositions, the closing instant, the paper keying deadline where one is configured (§6.4), any logged extension (R-3.4), and the consultative-status notice (R-1.4). Participation figures are shown only if `show_live_participation` is set; the default is off, since publishing turnout during a poll can influence it. When the flag is off, no endpoint anywhere — page, JSON, or headers — exposes a running count.

After publication the page carries the artefacts of §9.

---

## 7. Anonymity scheme (R-7.4) — MUST be implemented exactly

```
token        = 256 bits from a CSPRNG, base32-encoded, sent only in the confirmation email
voter_hash   = SHA256("voter"  || poll.token_salt || token)
ballot_hash  = SHA256("ballot" || poll.token_salt || token)
```

The registration row stores `voter_hash`; the ballot row stores `ballot_hash`. The plaintext token is never persisted anywhere: not in the database, not in logs, not in sent-mail archives if avoidable. Given the two tables, no join recovers the correspondence; only a request presenting the token can locate a ballot.

Consequences to implement deliberately:

- Administrators see two irreconcilable lists: names with a voted/not-voted flag, and anonymous rankings with tracking codes (R-7.5).
- Token loss is unrecoverable by anyone, including administrators (R-7.6). Say so in the confirmation email — where `allow_ballot_modification` is false the point is moot, and the email should not raise it.
- **Disabling modification strengthens anonymity.** The token → ballot link exists only to serve modification, so when the option is off, `ballot_hash` is not computed and not stored: nothing whatever connects a cast ballot to the token that cast it, and the voter's own tracking code becomes the sole handle. Voting-status is then carried by `Registration.channel` alone, set in the same transaction as the ballot insert. A poll wanting the closest approach to a secret ballot should disable modification.
- `token_salt` is per poll, so participation cannot be correlated across polls by the application (R-13.4). Note the residual exposure at R-13.4 bis: the NNE is a permanent national identifier, so direct database access to two concurrent polls permits a join on it. Do not add any feature that surfaces this.
- Paper ballots are deliberately **not** anonymous: `PaperBallotLink` keeps the association, because traceability and deletion-on-request require it.

**Receipt-freeness is not provided, and is not attempted.** A voter who keeps their tracking code can find their own row in the published CSV (§9) and so prove to a third party how they voted. This is inherent in publication-based verifiability: the property that lets any reader recompute the result from the published set is the same property that makes a ballot findable by someone holding its code. It is accepted because the poll is consultative, and it means the software MUST NOT be used where coercion or vote-buying is a realistic risk. The README says so, next to the risk-level statement of §11.

This cuts against the advice above, and the configuration screen should say so rather than presenting the choice as a straightforward privacy setting. Disabling `allow_ballot_modification` maximises anonymity — no `ballot_hash` is computed, nothing links a ballot to the token that cast it — but it removes a coerced voter's only remedy, which is to vote again privately once the coercer has gone. The commune is choosing which of the two risks it would rather carry.

---

## 8. Tally

Pure function `tally(ballots, method, params) → {winner, matrix, derivation}` (R-10.1). No I/O, no clock, no randomness beyond the seeded tie-break. Version-pinned (R-10.2).

### 8.1 Schulze

```
d[i][j] = number of live ballots ranking i strictly above j
          (unranked options rank equal-last — R-10.4)

p[i][j] = d[i][j] if d[i][j] > d[j][i] else 0
for i in options:
  for j in options where j != i:
    for k in options where k != i and k != j:
      p[j][k] = max(p[j][k], min(p[j][i], p[i][k]))

winners = { i : for all j != i, p[i][j] >= p[j][i] }
```

`|winners| == 1` → that option wins. `|winners| > 1` → tie-break (§8.3). Emit `d` (the pairwise matrix) and the path strengths as part of the derivation; the published derivation must let a reader follow the reasoning without running the code.

### 8.2 Plurality and approval

Also implement `plurality` (count of first preferences) and `approval` (count of approvals), R-10.3. Without them users will misapply Schulze to non-preferential questions.

### 8.3 Tie-break (R-10.5)

```
tiebreak_seed = SHA256(poll.opening_seed || poll.closure_hash)
order tied options by ascending SHA256(tiebreak_seed || option_id)
first wins
```

No language PRNG, no `random.shuffle`, no `sort` with a seeded comparator — reproducibility must not depend on the runtime. The seed depends on the closure hash and therefore on every ballot cast, so the outcome is unpredictable before closure and cannot be ground by the organiser (R-10.5 bis). Publish `opening_seed`, `closure_hash` and the full computation. If `tiebreak_rule = physical`, the tally reports the tie and stops; the result is entered by a poll admin and logged.

---

## 9. Closure and publication (R-11)

On entering `closed`:

```
closure_hash = SHA256 over the canonical serialisation of the live ballot set,
               ballots sorted by tracking_code, each rendered as a canonical
               JSON object {tracking_code, ranking}, newline-separated, UTF-8
```

The set hashed is exactly the rows with `status = live` (§3.4), serialised with option **ids**, never labels (§3.8). Document this serialisation precisely in the repository: a third party must be able to recompute the hash from the published CSV alone, and the CSV must therefore contain that set and nothing else.

**Closure guard.** If any ballot is still `pending_countersign` when closure is attempted, the transition is refused; where the attempt is the scheduled `close_poll`, the refusal is loud and the poll stays `open` (§4). The poll admin either has the entries countersigned, or overrides with a mandatory reason which is logged and appears in the publication. Silently dropping uncountersigned ballots at closure is not acceptable.

Publish (R-11.2): anonymised ballot list as CSV and JSON (tracking code + ranking); pairwise matrix; derivation; the participation counts frozen at closure — registered electors, ballots by channel, non-voters; `closure_hash`; `opening_seed`; tie-break computation if any.

Those counts are computed on entry to `closed` and stored, never derived at publication time. They read from `Registration`, which the retention job deletes (§11), and a late publication would otherwise be unable to produce them — and would in any case be reading them at a different instant from the hash they accompany.

For small option counts also publish the per-ordering summary table — six rows for three strictly ranked options, sufficient on its own to recompute the result (R-11.3).

---

## 10. Audit log (R-12)

Log at minimum: config changes; state transitions; `closes_at` extensions; roll imports; snapshots; registration review decisions; duplicate-NNE registration attempts; paper ballot create/correct/delete; countersignatures; collision overrides with reason; role assignments; access to the log itself. Each entry: actor, timestamp, object, before, after, reason where required (R-12.2). Auditors read everything; nobody can modify or delete (R-12.3).

**Reference-only structure (MUST, and decided before the model is written).** An audit event stores a *reference* and non-identifying state, never a copied personal value. `object_ref` names the row — `registration:<uuid>`, `ballot:<uuid>`, `poll:<uuid>` — and `before`/`after` are JSON objects holding state, channel, status, role, and rankings by option **id**. No elector's name, NNE or email is ever written to an audit event. Staff identity is different: `actor_id` is a named operator account (R-2.2), retained legitimately, and is not elector data.

The identity therefore lives only in the referenced row, which the retention job deletes (§11). After retention the log still reads *registration 7f3a… moved `pending_review` → `active`, by operator M, at T, reason `name_divergence_accepted`* — a complete record of what was done, with no way to recover to whom. That is a stronger property than redacting values after the fact, it costs nothing at write time, and it lets INV-3 stay absolute: no update path to the table at all, and so no exception for the purge to be granted.

Two things it requires:

- **`reason` is a structured code, not prose.** Free text authored by an operator will contain a name sooner or later — *nom mal orthographié : Dupond/Dupont* — and `reason` is retained. The event carries a code from a declared vocabulary; the prose belongs on the referenced row, in `Registration.review_reason` (§3.3), where the purge takes it. Where a screen requires a mandatory reason (R-8.5, R-9.3, §9's closure override), the mandatory part is the code; any note accompanying it is stored on the object, not on the event.
- **Duplicate-NNE attempts (R-5.9) reference the existing registration** that caused the refusal, and record nothing about the attempter. The flag is actionable while the poll is open and worthless afterwards, so the identity dying with that row is the intended outcome.

A reference to a purged row is expected, not an error: the audit screen (§6.5) renders it as *objet supprimé (rétention)*. Retrofitting any of this once the log holds history is a data migration over rows the trigger design exists to make immovable, which is why it is settled here.

---

## 11. Data protection (R-13)

Retention job: two months after **closure**, delete registrations, NNEs, roll snapshots and `PaperBallotLink` rows. The anchor is closure and not publication, because a poll that closes and is never published — an unresolved `physical` tie-break, an abandoned result — would otherwise keep its identity data for ever; the basis for holding it ends when the poll is over, not when somebody gets round to announcing the outcome. Publication after a purge remains possible because §9 freezes the participation counts at closure. Audit events need no treatment of their own: they hold references and non-identifying state only (§10), so deleting the referenced rows is what anonymises the log. Anonymised ballots, published results and the log itself are retained in full. Retention must be a scheduled, logged, idempotent job — not a manual procedure.

The purge is the sole exception to INV-2, which it necessarily breaches: it deletes `Registration` rows long after `closes_at`. Express the exception inside the trigger rather than around it — the INV-2 trigger forbids `INSERT` and `UPDATE` on `Registration` and `Ballot` outside the voting window, and permits `DELETE` of a registration only where the poll is `published`. Disabling the trigger for the duration of the job is not an acceptable substitute. The same applies to INV-7, whose trigger refuses every `UPDATE` on `RollEntry` unconditionally and permits `DELETE` only where the poll is `published` — a snapshot is frozen, not immortal. INV-3 needs no such accommodation, since the purge never touches `AuditEvent` at all.

Privacy notice at registration (R-13.2): purpose, legal basis, retention, recipients, rights, named referent. IP addresses kept only as long as rate-limiting requires (R-13.5).

**Regulatory framing, for adopters.** The CNIL's recommendation on the security of electronic postal voting was replaced by délibération n° 2026-045 of 19 March 2026 (published 24 April 2026), which repealed both the 2010 and 2019 texts and is accompanied by ANSSI technical guide ANSSI-PA-118; the two are designed to be read together, the CNIL setting security objectives and ANSSI the technical means. Ballots already in preparation for 2026 may continue under the 2019 version; any new ballot falls under the new text. The three-level risk approach is retained with revised criteria, strengthened transparency requirements and a reworked role for independent expertise. A low-stakes consultative poll in a village is probably outside its scope, which targets secret-ballot elections and sets out explicit exclusions; a participatory budget in a city of fifty thousand may well not be. The README MUST state which risk level this software is designed to meet and which it is not, so that an adopting commune's DPO can answer the question without reading the source.

---

## 12. Acceptance tests

Existing numbers are retained so that references elsewhere in this document stay valid; the two tables are therefore not contiguous.

### 12.1 Unit — pure functions, no database, no HTTP, no network

These run on every commit and must stay fast. Everything here is a function of its arguments, which is also why the tally, the hashes and the matching rules are specified as pure functions in §8, §9 and §6.2.

| # | Given / when | Then |
|---|---|---|
| T-9 | Cyclic-majority ballot set (A>B>C, B>C>A, C>A>B in equal numbers) | Schulze reports a tie; the tie-break resolves it; identical on re-run |
| T-33 | Fixture sets tallied under `plurality` and `approval` | Correct winners and derivations (§8.2) |
| T-39 | Empty ballot set | Tally reports the absence of a result rather than failing |
| T-40 | Name pairs differing by diacritics, case, hyphens, particles and first-name order | Normalisation matches them; genuinely different names do not collide (R-5.3) |
| T-41 | Addresses differing only by case; addresses differing by a `+suffix` or a dot | First pair canonicalises equal; the others are treated as distinct addresses (§3.3) |
| T-42 | Golden ballot set | Canonical serialisation matches a stored byte-for-byte vector, and the closure hash matches its stored value (§9) |
| T-43 | One token | `voter_hash ≠ ballot_hash`; both stable across runs; both change when the poll salt changes (§7) |
| T-44 | Fixed opening seed and closure hash | Tie-break ordering matches a stored expected order — the test that catches a platform- or version-dependent implementation (§8.3) |
| T-45 | Rankings that are incomplete, or contain ties | Accepted or rejected exactly per `require_complete_ranking` and `allow_ties_in_ballot` (R-6.1) |
| T-46 | Content with a missing translation in an enabled language | Falls back to the poll's default language, never to an empty string (§3.8) |
| T-47 | Closing instant spanning the Europe/Paris daylight-saving transition | The comparison resolves to the intended absolute instant |

### 12.2 Integration — database, triggers, HTTP, mail, browser

| # | Given / when | Then |
|---|---|---|
| T-1 | A ballot is cast, then modified three times | Four versions stored; one `live`; tracking code unchanged |
| T-2 | Registration with an NNE already used | Refused, logged, flagged; no detail of the existing registration disclosed |
| T-3 | Vote submitted one second after `closes_at`, clock skew simulated | Refused server-side |
| T-4 | Attempt to change `options` while `state = open` | Rejected |
| T-5 | `closes_at` extended | Allowed, logged with reason, shown on the public page |
| T-6 | Full database dump, online ballots only | No procedure recovers voter → ballot |
| T-7 | Elector with a paper ballot attempts to vote online | Refused, directed to the mairie |
| T-8 | Operator enters a paper ballot for an elector who voted online | Blocking warning; proceeds only with confirmation and reason; both logged |
| T-10 | Published CSV re-tallied by the Rust verifier | Identical winner, matrix and closure hash; run in CI on fixtures including T-9's |
| T-11 | Roll import with one malformed NNE | Whole import rejected; nothing written |
| T-12 | Two concurrent polls, same elector registered in both | Two tokens; no endpoint exposes cross-poll participation |
| T-13 | Ballot page driven by keyboard only, then by screen reader | Ranking completable without drag-and-drop |
| T-14 | Retention job run two months after closure | Identity data gone; ballots, results and the log retained in full; the log's now-dangling references render as *objet supprimé* rather than erroring |
| T-15 | Sandbox poll | Absent from public listings and statistics |
| T-16 | Fresh host restored from backup (`restore.yml`) | Published results served; closure hash recomputed from restored data matches the published value |
| T-17 | Registration with an address already used under a `+alias` or different case | Refused; no detail of the existing registration disclosed |
| T-18 | `pending_review` registration approved | Enters `pending_email`; no ballot possible before the mailbox is confirmed |
| T-19 | Closure attempted with a `pending_countersign` ballot | Refused; permitted only with a logged override reason, which appears in the publication |
| T-20 | `show_live_participation` off | No page, endpoint or header discloses a running count |
| T-21 | Modification link followed | Token exchanged for a session, redirect to token-free URL; token absent from access logs and `Referer` |
| T-22 | Poll with English enabled but one option label untranslated | Cannot leave `draft`; the gap is named on the configuration screen |
| T-23 | Option label corrected after publication | Closure hash and result unchanged |
| T-24 | `UPDATE` or `DELETE` on `audit_event`, and on a superseded `Ballot` row, issued in raw SQL | Rejected by the trigger, not merely by application code (INV-3) |
| T-25 | Schema and model metadata inspected; a registration and the ballot cast from its token compared field by field | No field or relation links `Ballot` to a voter, registration or NNE, and no value whatever is common to the two rows — in particular no tracking code (INV-1, INV-5, §6.2) |
| T-26 | Roll re-imported while a poll is open; `UPDATE` attempted on a `RollEntry` | Open poll's snapshot unchanged; update rejected (INV-7, R-4.3) |
| T-27 | Registration left in `pending_email` | Cannot reach the ballot; excluded from turnout figures (R-5.5) |
| T-28 | Registration whose name diverges from the roll entry | Routed to `pending_review` rather than refused (R-5.4) |
| T-29 | Ballot violating the poll's ranking constraints, posted directly to the endpoint | Rejected server-side, not only in the browser |
| T-30 | Two voters open the ballot page | Option display order differs; stored order and ids unaffected (R-6.2) |
| T-31 | Paper ballot deleted by an operator | `channel` cleared, online voting re-enabled, both actions logged with reason (R-9.4) |
| T-32 | Closure overridden with `pending_countersign` ballots outstanding | Those ballots absent from tally, closure hash and published CSV; override reason appears in the publication |
| T-34 | Poll closing during the Europe/Paris daylight-saving transition | No ballot accepted after the intended instant |
| T-35 | Same ballot modified twice concurrently | Exactly one `live` version; no lost update |
| T-36 | Published artefacts cross-checked | CSV row count = live set = hashed set; registered = online + paper + non-voters |
| T-37 | Reminder job run | Sent once, only to `active` registrations with `channel = none` (R-5.7) |
| T-38 | Ansible deploy run twice against the same host | Idempotent and `--check` clean; `SECRET_KEY` unchanged; database and audit log untouched (§15) |
| T-48 | Poll with `allow_ballot_modification` false: modification link followed after casting | Refused; no `ballot_hash` stored on any row of that poll |
| T-49 | `send_reminders` started twice concurrently; and run after a period of downtime | Second instance exits 0 without acting; the missed reminders are sent late, once each |
| T-50 | Service definitions under `contrib/init/` | `systemd-analyze verify` passes on the unit; the OpenRC and `rc.d` scripts pass `shellcheck`; none contains a hardcoded path |
| T-51 | `open_poll` started twice concurrently; and run after a period of downtime | Second instance exits 0 without acting; exactly one snapshot and one `opening_seed`; a poll whose `opens_at` has passed opens late, once (§4) |
| T-52 | Ballot posted before `opens_at`, with `state` forced to `open` directly in the database | Refused server-side by the voting-window check, which never consults `state` (§4, INV-2) |
| T-53 | `open_poll` run against a poll with an option label untranslated in an enabled language, and against one with no roll snapshot | Refuses both, leaves them in `draft`, logs the blocking reason, exits non-zero (§3.8, §4) |
| T-54 | Retention purge run on a published poll; then `INSERT` and `UPDATE` attempted on `Registration` in raw SQL after `closes_at` | Purge succeeds against live triggers, including the `RollEntry` deletion; insert and update rejected by the INV-2 trigger (§11) |
| T-55 | Every audit event written across a full poll lifecycle, scanned before and after the purge | No `object_ref`, `before`, `after` or `reason` matches a name, NNE or email pattern at either point; `UPDATE` on `audit_event` still aborts (§10, INV-3) |
| T-56 | Paper ballot keyed in after `closes_at` but before `paper_entry_deadline`; an online ballot posted at the same instant; a countersignature applied at the same instant | Paper entry and countersignature accepted and counted; online ballot refused (§6.4, INV-2) |
| T-57 | `close_poll` reaching `paper_entry_deadline` with a `pending_countersign` ballot outstanding | Refuses, leaves the poll `open`, logs the blocker, exits non-zero; no ballot write is accepted meanwhile; the dashboard names the blocker (§4, §9) |
| T-58 | Poll closed and never published, two months later; then published afterwards | Purge runs on the closure anchor; identity data gone; the counts frozen at closure are still published correctly (§9, §11) |

T-16 and T-38 need a throwaway host (a container or a virtual machine under Molecule or equivalent) rather than the ordinary test database, and belong in a separate, slower CI job. T-13 needs a browser and a screen reader; automate what a headless browser can check and keep the assistive-technology pass as a documented manual step before each poll opens.

---

## 13. Deferred — implement as configuration, not constants

1. The option labels for the first poll, in each enabled language.
2. Which languages are enabled beyond French.
3. `opens_at` / `closes_at`.
4. Named data-protection referent for the privacy notice.
5. Which of `paper_requires_signed_form`, `paper_requires_countersign`, `paper_requires_reconciliation` are enabled for the first poll — all default false.
6. Acceptance of the residual correlation risk at R-13.4 bis.
7. Whether a paper keying window is used and how long it runs (`paper_entry_deadline`); the default is none, the deadline sitting on `closes_at`.

---

## 14. Stack

Decided: **Python / Django, SQLite by default, server-rendered templates, minimal vanilla JavaScript.** Released as open source, one instance per commune.

The choice is made for the project's second life rather than its first. This is civic software intended for adoption and contribution; the French public-sector ecosystem is Python and Django, an adopting commune's IT department is far likelier to be able to read and run it, and the dominant cost of the build is the administrative interface, the review workflows and RGAA-conformant markup — which is exactly what Django accelerates. The price is the loss of compile-time enforcement of the lifecycle; §5.1 sets out what replaces it.

**Django** on the current LTS. SQLite in WAL mode by default; PostgreSQL supported through the ORM for larger adopters, with the caveat that the triggers of §5.1 are SQLite dialect and must be rewritten in PL/pgSQL, and that a test suite running against both backends is the only way to keep the two in step. Keep SQLite the sole supported backend until a commune actually asks for the other.

**Dependencies stay few.** `openpyxl` for the xlsx roll import (R-4.2); the standard library for CSV, hashing and randomness; Django's own SMTP backend for mail; `argon2-cffi` for the handful of operator passwords. No Celery, no Redis, no queue: background work is management commands (`import_roll`, `open_poll`, `send_reminders`, `close_poll`, `run_tally`, `retention_purge`), which keeps it individually runnable, observable and testable. Lockfile committed.

**Scheduler-agnostic jobs.** Nothing in the application knows what invokes these commands: cron, systemd timers, a container orchestrator, or a person at a terminal are all equivalent. That portability imposes four requirements on the commands themselves, since the weaker schedulers guarantee none of them.

- **Self-locking.** Each command takes an exclusive lock — `flock` on a state file, or a row in a `job_run` table — and exits 0 without working if another instance holds it. cron will happily start a second copy while the first is still running; systemd's `Type=oneshot` would not, and relying on that would make the code correct under one scheduler only.
- **State-based, not time-triggered.** `send_reminders` selects everyone who is due a reminder and has not had one, rather than acting because it happens to be T−48 h. cron has no catch-up for missed runs, so a host that was down must send late rather than not at all. The same for `retention_purge`.
- **Idempotent, with meaningful exit codes**, so a re-run is harmless and a failure is visible to cron mail or any monitoring.
- **Logs to stdout and stderr**, captured by whatever invoked them; no assumption of journald. An optional `--log-file` covers the rest.

Note what this leaves genuinely scheduled: opening, closure, reminders and retention. A scheduler that never fires can neither admit a late ballot nor alter a result — both boundaries are enforced on every write path independently of the job that moves the state (§4) — and reminders and retention simply run late. What it can do is delay: a poll advertised for Monday still sitting in `draft` on Monday morning, or a closed poll with no `closure_hash` and therefore no result to publish. Both are visible to the mairie rather than silent, which is why `open_poll` and `close_poll` exit non-zero on refusal and the dashboard names their blockers beforehand (§4, §6.5). The tally and publication remain operator-triggered from the back-office (§6.5).

**No Django admin.** The administrative interface is purpose-built (§6.5); Django admin is not routed in production. The admin is not RGAA-conformant, is designed for developers rather than for mairie staff, cannot express the review and paper-entry workflows, and is precisely the tool that would let someone browse the registration and ballot tables side by side. This removes one of the arguments commonly made for Django: what remains in its favour here is the ORM, forms, templates, migrations, auth, i18n and the contributor pool.

**Front end.** Django templates, `i18n_patterns` with French default and English available (§3.8), no SPA, no build step. The ranking widget is progressive enhancement over a form that works without JavaScript (numbered selects), which R-6.3 and R-14.1 require in any case. Total JavaScript in the low hundreds of lines. No WebAssembly in the ballot path.

**Health endpoint.** `GET /sante` returns 200 with the application version and whether migrations are pending. No authentication, no personal data, no counts. Used by the Ansible smoke play (§15) and by monitoring.

**Time.** `USE_TZ = True`, `Europe/Paris`, and the poll's timezone stored explicitly per R-3.1. Closure is enforced server-side on every write path, not by a scheduled job alone.

**Canonical serialisation.** `json.dumps` defaults are not a canonicalisation guarantee. Write the canonical serialiser for the closure hash (§9) as an explicit byte-level function and document it, so a third party can reproduce the hash from the published CSV alone.

**Independent verifier in Rust.** A second implementation of §8 and §9 as a small standalone binary, written from this specification, sharing no code with the application — a property the language boundary enforces structurally. Publish prebuilt binaries for the common platforms so a sceptic needs no toolchain. It reads only the published CSV, never the database, and recomputes the pairwise matrix, the Schulze winner, the tie-break and the closure hash. CI asserts agreement with the Python tally on fixtures including the cyclic case at T-9 and on randomly generated ballot sets. When the two disagree, the resolution is to return to this specification and determine which is wrong, never to adjust the verifier until it matches.

**Distribution.** Prebuilt container image and a single-page deployment guide that assumes no Python toolchain: an adopting commune should not have to manage a virtualenv. Licence: **0BSD**, with `SPDX-License-Identifier: 0BSD` in each source file and a `LICENSE` at the root. Three consequences to handle in the repository rather than leave implicit:

- **Contributions from others will carry copyright**, whatever the provenance of the initial code. A `CONTRIBUTING.md` with a DCO sign-off requiring contributions under 0BSD keeps the tree uniform; without it the project becomes mixed-licence at the first pull request, and 0BSD's principal virtue — that a reuser has nothing to comply with — is lost.
- **Dependencies keep their own licences.** Ship a generated third-party notice listing them; public-sector adopters ask for it at procurement, and 0BSD on this code says nothing about Django or the crates in the verifier.
- **Decide whether the documentation and the specifications are covered too**, or sit under a separate licence. `LICENSE` covering only source leaves the status of these documents undefined for anyone who forks them.
- **Keep the reasoning out of `LICENSE`.** A `PROVENANCE.md` describes how the code was produced; the licence stands on its own. Asserting in the repository that the code bears no copyright states a jurisdiction-dependent legal conclusion that a reuser cannot verify, whereas the permissive grant is effective whether or not rights subsist.

**Quality gates.** `mypy --strict`, `ruff`, and the invariant tests of §5.1 and §12 in CI, running against SQLite and, if the PostgreSQL backend is ever enabled, against both.

**Deployment.** gunicorn behind nginx, database file on local disk. The long-running web process still needs a supervisor — systemd on a Debian host, the runtime's own restart policy in the container image — but that is a property of the target, not a dependency of the application. TLS via the `ngx_http_acme_module` (nginx-acme) where a vendor-packaged build is available — it needs a `resolver` in the `http` block, a listener on port 80 for the HTTP-01 challenge, and a `state_path` holding the account key and certificate private keys, which is subject to the same access restrictions as the backups. A self-compiled dynamic module must be rebuilt on every nginx upgrade, so on a machine meant to be left alone, certbot is the lower-maintenance choice despite being an extra component. Set `X-Forwarded-Proto` and `X-Forwarded-For` and honour them, or secure-cookie flags and rate limiting will both misbehave. Backups: nightly `VACUUM INTO` snapshot plus off-host replication. `poll.token_salt` lives in the database and therefore in the backups, so backup access is ballot-secrecy-relevant.

**Email.** SMTP relay with SPF, DKIM and DMARC aligned on the commune's domain. Deliverability is the most fragile dependency in the design: every online ballot passes through a confirmation email, and mail from a small self-hosted domain is routinely filtered. Run a test send to real mailboxes across the common providers before opening the first poll, and give the mairie a documented procedure for voters who report receiving nothing.

---

## 15. Deployment (Ansible)

The repository ships an Ansible playbook as the supported installation path. An adopting commune should be able to go from a bare Debian VM to a running instance by editing one inventory file and running one command; the container image (§14) is the alternative for those who prefer it, not the primary route.

**Supported target: current Debian stable, one distribution.** Narrow support is a feature here — a playbook that claims to work on four distributions and is tested on none is worse than one that refuses to run on anything else. The playbook asserts the OS and fails early.

**Structure.** A single role with tags, so `provision`, `deploy` and `backup` can be run independently; `site.yml` for a full run; `restore.yml` as a separate playbook. Everything idempotent and `--check` clean.

**What it does.**

1. System packages, `fr_FR.UTF-8` locale, host timezone `Europe/Paris`, unattended security upgrades, nftables or ufw allowing only 22, 80 and 443.
2. An unprivileged service user; directory layout with the database under `/var/lib/`, backups under `/var/backups/`, application code under `/opt/`, none of it world-readable.
3. Application release from a tagged artefact, never from a working branch, into a versioned directory with a symlink switch so rollback is a symlink change.
4. Virtualenv from the committed lockfile; `migrate` and `collectstatic`; a fail-fast check that migrations left no pending changes.
5. Settings rendered to an environment file, mode 0600, owned by the service user. Secrets come from `ansible-vault`, never the repository.
6. A supervised `gunicorn` service, and periodic invocation of `open_poll`, `close_poll`, `send_reminders` and `retention_purge` according to the `scheduler` variable, at an interval short enough that `opens_at` and `closes_at` are honoured to the minute: `cron` (the default, being universally available), `systemd` (timers, with `Persistent=true` and a randomised delay), or `none` for operators with their own orchestration. Under `cron`, the wrapper script sources the environment file explicitly — cron's minimal environment is the classic cause of a job that works by hand and silently fails at three in the morning.
7. nginx vhost from a template, TLS per §14, security headers, and a rate-limit zone consistent with the application's own limits.
8. Backups: nightly `VACUUM INTO` to `/var/backups/`, retention window, and off-host replication. The database contains `poll.token_salt`, so backup destination permissions are part of the ballot-secrecy boundary and the playbook must not loosen them.
9. A smoke play run last: service up, health endpoint answering, a test email actually delivered to an address given in the inventory. Deployment is not "green" until mail has been proven to leave the machine, since every online ballot depends on it.

**Traps the playbook must handle explicitly.**

- `SECRET_KEY` is generated once, on first install, and never regenerated on subsequent runs. A naive template regenerates it every deploy and silently invalidates every session and signed link, including live ballot-modification links. This is the single most likely way to break a poll in progress.
- Never run `migrate` against a poll in `open` state without an explicit override variable; schedule schema changes between polls.
- The roll snapshot and the audit log must survive a redeploy: they live in the database directory, which is never touched by the deploy tag.

**Service definitions for other platforms.** The repository ships, under `contrib/init/`, a systemd unit, an OpenRC init script, and `rc.d` scripts for FreeBSD and OpenBSD, so that the software can be run outside the Debian target the playbook assumes. Two support tiers, stated in the README so nobody mistakes one for the other: **Debian is playbook-installed and tested in CI**; the other platforms are **service files provided, installation by hand, best effort**.

Requirements these impose:

- **No hardcoded Linux paths.** Prefix, configuration directory, state directory and service user are variables; BSD installs under `/usr/local/etc` and `/var/db`, Linux under `/etc` and `/var/lib`.
- **Restart on failure everywhere.** OpenRC uses `supervise-daemon`, which restarts a crashed process; the BSD scripts use `daemon(8)` with a pidfile and its restart flag. Without this the non-systemd targets silently lose the property the systemd unit provides.
- **Logging with no journal.** The commands already write to stdout and stderr; the rc scripts redirect to a log file or to syslog, and the packaged logrotate or newsyslog configuration goes alongside them.
- **cron is the scheduler on these platforms**, which is already the default (§14), so nothing further is needed.
- **musl targets build some wheels from source.** On Alpine or another musl system, document the build dependencies for `argon2-cffi` in case no `musllinux` wheel is published for the installed Python version.

**`restore.yml` is part of the deliverable, not an afterthought.** It provisions a fresh host, restores the most recent backup, and runs the same smoke play. A backup procedure that has never been restored is not a backup procedure, and for a system whose credibility rests on an audit log, losing that log to an untested restore would be the worst possible failure.
