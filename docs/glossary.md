<!-- SPDX-License-Identifier: 0BSD -->

# Glossary

Domain terms as they appear in the code, with the French used in the
interface where the two differ. Code identifiers are English; interface text
and the functional requirements are French.

## Polls and their lifecycle

| Term (code) | French | Meaning |
|---|---|---|
| poll (`Poll`) | scrutin, consultation | One consultative question with its options, dates and rules. Consultative: the result is advisory (R-1.4). |
| option (`PollOption`) | proposition | One choice on the ballot. `option_id` is a slug; rankings, hashes and the CSV carry ids, never labels. |
| `draft` | brouillon | Editable configuration; not public. |
| `announced` | annoncé | Public preview with frozen configuration. The mandatory step before `open` (R-3.10). |
| `open` | ouvert | Registration and voting accepted, **subject to the clock** (see *window*). |
| `closed` | clos | Closure hash and counts frozen; awaiting publication. |
| `published` | publié | Results and artefacts public. |
| `withdrawn` | retiré | Terminal. The poll is hidden from the public and every write is refused (R-3.11). |
| sandbox poll (`is_sandbox`) | scrutin d'essai | A rehearsal poll that runs the full lifecycle, is never listed or counted, and is the only kind that can be deleted (R-3.7). |
| share link (`preview_token`) | lien d'aperçu | Unguessable URL for previewing a draft or reaching a sandbox poll (`elections/sharelink.py`). |
| window | fenêtre de vote | The interval in which a write is accepted: `opens_at` to `closes_at` online, to `paper_entry_deadline` for paper. Checked on the clock, not on `state` (INV-2, `elections/windows.py`). |
| paper entry deadline | fin de saisie des bulletins papier | Instant after `closes_at` until which paper ballots may still be keyed in (§6.4). `close_poll` runs at this instant. |
| extension | report de la clôture | Moving `closes_at` later while open, with a reason; `paper_entry_deadline` moves with it (R-3.4). |
| template (`PollTemplate`) | modèle de scrutin | A saved set of tally and ballot rules used to create new polls (screen 13). |
| frozen configuration | configuration figée | The fields in `FROZEN_CONFIG_FIELDS`; immutable once the poll leaves `draft` (INV-6). |

## The electoral roll

| Term (code) | French | Meaning |
|---|---|---|
| working roll (`WorkingRollEntry`) | liste de travail | The commune-wide roll as last imported; replaced wholesale by each import (screen 3). |
| snapshot (`RollEntry`) | liste électorale figée | Per-poll copy of the working roll taken at `open`; never modified afterwards (INV-7). |
| REU | répertoire électoral unique | The national electoral register the commune's roll export comes from. |
| list type (`ListType`) | type de liste | `principale`, `complementaire_municipale` or `complementaire_europeenne`. A poll accepts some of them (`eligible_list_types`, R-4.7). |
| birth name / name in use | nom de naissance / nom d'usage | Both are accepted when matching a registration (R-5.3). |
| `date_uncertain` | date incertaine | The date of birth did not parse. The row is kept verbatim and never matched automatically (R-4.9). |

## Electors and registrations

| Term (code) | French | Meaning |
|---|---|---|
| registration (`Registration`) | inscription | One person's request to vote online in one poll. Holds identity, `voter_hash` and `channel`. |
| `pending_email` | en attente de confirmation | Matched to the roll; the confirmation link has not been followed yet. |
| `pending_review` | en attente d'examen | No automatic match; a poll admin decides (screen 4). |
| `active` | active | Mailbox confirmed; may vote. |
| `rejected` | rejetée | Refused (ineligible list type, or by review). |
| channel (`Channel`) | canal de vote | `none` / `online` / `paper`. **The** answer to "has this person voted" (INV-5). |
| participating (`PARTICIPATING`) | participants | The registrations the turnout figures count. |
| duplicate attempt (`DuplicateAttempt`) | tentative de doublon | A refused registration against an already-registered roll entry, flagged to the poll admin (R-5.9). |
| paper shell | inscription papier | The `active`, address-less registration created when a paper ballot is keyed for someone who never registered online (`ensure_paper_registration`). |

## Ballots

| Term (code) | French | Meaning |
|---|---|---|
| ballot (`Ballot`) | bulletin | One version of a ranked ballot. Carries no reference to a voter. |
| ranking | classement | A list of groups of option ids; a group of more than one option is a tie. |
| live set (`Ballot.live`) | bulletins en vigueur | Rows with `status = live`. The only rows that are tallied, hashed and published. |
| `superseded` | remplacé | An earlier version, replaced by a modification or correction. Immutable. |
| `pending_countersign` | en attente de contreseing | A paper entry awaiting a second operator; not counted until countersigned. |
| countersignature | contreseing | The second operator's check of a paper entry (R-8.7, screen 7). |
| paper ballot link (`PaperBallotLink`) | lien bulletin papier | The deliberate link from a paper ballot to the roll entry (R-8.2 bis). Purged at retention. |
| reconciliation (`ReconciliationRecord`) | rapprochement, procès-verbal | Count of retained paper forms against paper ballots recorded, signed before closure where required (R-8.6). |
| tracking code | code de suivi | A 10-character code shown on the receipt and published in the CSV, so voters can check their ballot was counted (§3.4). |

## Cryptography and publication

| Term (code) | French | Meaning |
|---|---|---|
| token | jeton | 256-bit secret in the confirmation link. Never stored (§7). |
| `token_salt` | sel | Per-poll secret mixed into both hashes. Never published. |
| `voter_hash` | empreinte électeur | `SHA256("voter"‖salt‖token)`, on the registration. |
| `ballot_hash` | empreinte bulletin | `SHA256("ballot"‖salt‖token)`, on the ballot. Only when modification is allowed. |
| closure hash | empreinte de clôture | SHA-256 of the canonical serialisation of the live set at closure (§9). |
| canonical serialisation | sérialisation canonique | The exact byte format the closure hash covers (`docs/canonical-serialisation.md`). |
| opening seed | graine d'ouverture | 32 random bytes drawn at `open`; combined with the closure hash for the computed tie-break (§8.3). |
| computed / physical tie-break | tirage au sort calculé / physique | A hash-chain draw anyone can reproduce, or a human draw entered on screen 9. |
| frozen counts | décompte figé | Participation figures stored at closure, since the registrations they come from are purged later (§9). |
| verifier | vérificateur indépendant | The Rust program in `verifier/` that recomputes the hash and Schulze result from the CSV. |
| Schulze / plurality / approval | Schulze / majoritaire / par assentiment | The three tally methods (R-10.3). |

## People and roles

| Term (code) | French | Meaning |
|---|---|---|
| espace mairie | espace mairie | The back office (`apps/backoffice`). |
| commune admin (`is_commune_admin`) | administrateur de la commune | Manages accounts, creates polls, imports the roll. **No** rights on an individual poll. |
| poll admin (`poll_admin`) | administrateur du scrutin | Configures, reviews registrations, closes and publishes one poll. |
| entry operator (`entry_operator`) | opérateur de saisie | Keys in, corrects and countersigns paper ballots. |
| auditor (`auditor`) | auditeur | Read-only access to one poll's log, roll and results. |
| data-protection referent | référent données personnelles | The contact named on the public notice (R-13.2), stored on `Commune`. |

## Project vocabulary

| Term | Meaning |
|---|---|
| `R-x.y` | A rule of the functional requirements (`cahier-des-charges.md`, authoritative; `requirements-en.md`, translation). |
| `§n` | A section of `spec-plateforme-vote.md`. |
| `INV-n` | An invariant, spec §5. |
| `T-n` | An acceptance test, spec §12. |
| decision log `#n` | An entry in `docs/specification-decision-log.md`: a recorded departure from the specification. |
