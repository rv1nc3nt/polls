<!-- SPDX-License-Identifier: 0BSD -->

# Frequently asked questions

Three sub-parts: [instance administrator](#a-instance-administrator),
[mairie area](#b-mairie-area), [voter](#c-voter).

---

## A. Instance administrator

### Can I run several communes on the same installation?
No. One instance = one commune. There is no "tenant" column.
Another commune installs its own instance, with its own database and its own
keys.

### The playbook refuses to run on my distribution.
That is intentional. The supported target is **current Debian stable**, and
only that. For another system, `contrib/init/` provides service files
to install by hand, with no support guarantee.

### I ran a deployment and every ballot-change link is now broken.
`SECRET_KEY` was regenerated. It must be generated **once only** and never
rewritten; the Ansible role persists it under `/etc/polls/secret_key` and
reads it back. Restore that file from a backup. Links signed **before** the
key change stay lost.

### Can I apply a schema migration while a poll is open?
No, barring a carefully weighed reason. The role refuses (`assert`) while
`polls_open_poll_count > 0`, unless
`polls_allow_migrate_during_open_poll=true`. Plan schema changes **between
two polls**.

### Will a redeployment overwrite the frozen electoral roll or the audit log?
No. They live under `/var/lib/polls/`, which the `deploy` tag never touches.
Only `migrate` writes there.

### Where is the key that protects the anonymity of the vote?
`poll.token_salt` is **in the database**, and therefore in **every backup**.
The backup directory (`/var/backups/polls/`, including the off-site copy) is
part of the secret's perimeter: it stays `0700`, owned by the service
account. Never widen it.

### How do I test that my backups can be restored?
`ansible-playbook -i inventory.ini restore.yml`: it provisions a host,
restores the most recent snapshot and replays the smoke play. A backup never
restored is not a backup. `restore.yml` checks the snapshot's
integrity **before** trusting it and sets the old database aside as
`db.sqlite3.pre-restore-*`.

### The deployment stops on sending a test email.
The smoke play requires that **an email actually be sent** to
`polls_smoke_test_email`: every online vote depends on this. Fix the SMTP
relay (credentials in `ansible-vault`), rerun `--tags deploy` then the
smoke. A host can be brought up without a relay with
`polls_smoke_require_mail=false`, to be fixed before opening a poll.

### A scheduled task "works by hand" but fails under cron.
The cron environment is nearly empty. Use the wrapper
`/opt/polls/bin/polls-manage <task>`, which explicitly sources
`/etc/polls/polls.env`.

### `open_poll` did not open a poll at the scheduled time.
Check that the scheduler is running (`systemctl list-timers` or
`/etc/cron.d/polls`) and the interval (`polls_job_interval_minutes`, 5 min by
default). Tasks are state-driven: a host that was off catches up on the next
pass. If the poll still does not open, its dashboard lists what is blocking
it (missing translation, roll not frozen).

### How is the instance supervised?
`GET /sante` returns `{"version", "migrations_pending"}` with no
authentication and no personal data. Alert on: `/sante` silent,
`migrations_pending: true` after a deployment, a cron task failing
(`MAILTO` = `polls_admin_email`), no snapshot for > 24 h, a TLS certificate
nearing expiry.

### Can I turn on full URL logging in nginx?
Not for the `/bulletin/` prefix: the voting token travels there in a link
and must never reach a log. The nginx template deliberately
suppresses URI logging for this prefix.

### Is this software suitable for a big city's participatory budget?
Probably not. It is designed for the CNIL's **risk level 1** (a low-stakes
consultation). It is not designed for levels 2 or 3. The commune's DPO must
decide before any poll that would not clearly be level 1 (see the root
`README-en.md`).

### Where is personal data kept, and when does it disappear?
Registrations, the frozen roll snapshot, the paper-ballot ↔ voter
association: in the database, **deleted two months after closing** by
`retention_purge`, which also erases the "personal data" fields of the audit
log **while keeping** the entry, its author, its date and its reason
. Rate-limiting IP addresses are not kept beyond what is
necessary.

---

## B. Mairie area

### I am the commune administrator: why don't I have access to a poll's screens?
Because `commune_admin` is a **commune-level** role, not a superuser. It
creates polls and assigns roles; it grants access to no ballot. Assign
yourself the role you need on the poll — this writes an audit event, which
is the point: every access to sensitive screens must follow from a traceable
grant.

### How do you start a brand-new instance, with no `createsuperuser`?
Through the **first-run** wizard (`/mairie/installation/`), which creates
the commune's record (including the data-protection referent) and the first
administrator account. It closes as soon as one account exists.

### I made a mistake in the configuration and the poll is already open.
Configuration freezes on opening, and a database trigger
enforces it. **Only** the **closing date** can be extended (a separate
action, mandatory reason, shown publicly). For anything else, a new poll is
needed. No transition is reversible.

### Can a poll go back from "closed" to "open"?
No. `draft → announced → open → closed → published`, with no way back
. "Announced" is a **mandatory** step: *open now* only ever
accepts an already-announced poll as its starting point, there is no longer a
direct path from draft to open.

### Can I withdraw a poll that is already announced, open, closed or published?
Yes, from the configuration screen: an irreversible action, mandatory
reason. The poll disappears from every public page — including an already-
published result — but its detail URL does not just 404: it shows "this poll
has been withdrawn" and nothing else. A poll still in draft is **deleted**
instead of withdrawn.

### Can a poll be opened or closed without waiting for the scheduled task?
Yes, from the configuration screen (screen 2): *Announce now*, *Open now*
and *Close now*. *Open now* is allowed at any time, including ahead
of schedule — it does not let anyone vote before the configured time. *Close
now* only appears once the paper-ballot keying deadline has been reached.

### What is the "announced" state for?
To make a poll visible on the public site — propositions and schedule —
before it opens, with no registration or vote possible yet. It is
now a mandatory step for every poll, not just a useful option on ones that
will not allow changing an already-cast ballot — though the benefit stays the
same for those: voters can think over the propositions before voting.
Configuration freezes at the moment of announcing, exactly as it would have
at opening.

### Announcing makes the poll public. How do I get it reviewed privately first?
From the configuration screen, while the poll is still a draft: *share this
preview* generates an unguessable link, referenced nowhere, that
shows the public page as it will look. Unlike announcing, this link **freezes
nothing**: the page keeps changing along with the draft. Regenerating it
invalidates the old one immediately; revoking it disables it without creating
a new one. It has no effect once the poll leaves draft.

### The electoral-roll import reports duplicates and doubtful dates. Do I need to fix the file?
No. The report **informs, it does not block**. Only an unmapped required
column or a row with no name at all stop the import. Dates that cannot be
parsed (flagged "uncertain"), incomplete rows and duplicates are
**imported**: these are facts about the roll, not defects in the file.
Doubtful cases then land in the registration queue.

### Will a new import change a poll that is already open?
No. The import replaces the **working roll**; an open poll works from its
own **frozen snapshot** taken at opening.

### Can the electoral roll's detail be viewed, not just its status?
Yes, on two screens: the general "Electoral roll" menu (commune level) shows
the working roll currently in force, paginated and searchable; the
"Electoral roll" menu of a poll that is already open shows its **own frozen
snapshot**, accessible to the poll administrator and the auditor.

### Is an imported working roll kept forever if nothing uses it any more?
No. A roll that was imported but that no poll still in draft (or announced)
consumes any longer is deleted two months after its import —
distinct from the retention of a poll's frozen snapshot, which starts from
its closing.

### A voter says they are registered but the matching fails.
Their request goes to the **registration queue**. Compare the declaration
against the nearby entries; **accept** it (choosing the roll entry) or
**refuse** it, with a reason. An accepted registration moves to awaiting
address confirmation, never directly to the active state.

### A couple shares a single email address.
An address can only be used once per poll. One of the two votes
**on paper at the mairie**. No alias normalisation is done: any rule on dots
or suffixes would either merge distinct people or give a false assurance.

### A voter voted online and now wants a paper ballot.
Refused. The online ballot is anonymous and cannot be traced back
from the registration: it can be neither replaced nor deleted. If the poll
allows changes, the voter changes their online ballot **themselves**;
otherwise, the online vote is final.

### A voter has a paper ballot and wants to vote online.
They must come to the mairie to have the paper ballot **deleted** first.
The deletion (mandatory reason, before/after logged) clears the channel flag
and reopens online voting.

### What is the difference between "correcting" and "changing" a paper ballot?
A **correction** fixes an operator's keying mistake; it stays possible even
if the poll does not allow voters to change their vote. It is not the same
act as a voter changing their mind. Mandatory reason, before/after logged
.

### Closing is refused: "n ballots awaiting countersignature."
Either you obtain the countersignatures (screen 7), or the poll
administrator **overrides it with a mandatory reason**, which is recorded
and **appears in the publication**. Uncountersigned ballots are not counted;
ballots are never silently dropped.

### Closing is refused: "paper-ballot reconciliation not recorded."
The poll requires **formal reconciliation**: count the paper
forms kept by the commune and enter their number on the closing screen, once
`paper_entry_deadline` has been reached. Unlike the countersignature, **there
is no override** — closing waits for this to be recorded, with no exception.

### Can I show live turnout?
Only if the poll's configuration allows it (off by default): publishing
turnout while voting is under way could influence it. When this is off,
**no** page, API or header exposes a count.

### Who can see the audit log? Can an error be corrected in it?
**Auditors** have read-only access to it, as do the poll's administrators.
**No** event can be changed or deleted, not even by an
administrator. A clarification goes on the referenced row (registration,
paper-ballot link), not on the event, whose reason is a code.

### Will a "test" poll appear in the public results?
No. The flag is set at creation and cannot be changed; the poll is excluded
from public listings, results and any statistics.

### Why can't I change a proposition's identifier?
Because the ballots and the published result carry it; the tally and the
hash rest on the identifiers, not the labels. Labels, on the other
hand, can be freely corrected — but only while the poll is still a draft.

---

## C. Voter

### Is my vote really secret?
A ballot voted **online** is never linked back to your identity by any data
in the database: the platform knows that you voted, never how. A
**paper** ballot, by contrast, stays associated with your identity (for
traceability and deletion at your request), until it is erased two months
after closing.

### Is this an election? Does the result bind the council?
No. It is a **consultation**: the result informs the municipal council's
decision without binding it. It is not a legally-binding election (no
strong voter authentication, no end-to-end cryptography).

### I did not receive the confirmation email.
Check your spam folder. The address must be **exactly** the one entered.
Without confirmation, no ballot exists and you cannot vote. If you are stuck,
contact the mairie; you can also vote **on paper**.

### I lost the link received by email.
If you **have not voted yet**, contact the mairie. If you **have already
voted**: your ballot **stays recorded and counted**, but you will no longer
be able to change it. No one — not even the mairie — can retrieve this link
or send you another one.

### Can I register with my birth surname or my name in use?
Both are accepted. The date of birth carries most of the weight of the
check.

### Why aren't the propositions in the same order as on the public page?
The ballot's order is **randomised for each voter**, so as not to
favour a proposition by its position.

### Can I change my vote after casting it?
Only if the poll allows it — the ballot page tells you **before**
submission. If it does, reopen your registration link as many times as you
like until closing; each version replaces the previous one, your tracking
code does not change, and no new email is sent.

### What is the tracking code for? When do I receive it?
It is given to you **at the time of voting** (on screen and by email), not
at registration. After closing, it lets you **find your ballot in the
published list** and check your ranking, **without revealing your
identity**.

### With my tracking code, can someone find out how I voted?
You yourself can find your row in the published file — and so, if you share
your code, you can prove to a third party how you voted. This is the flip
side of verifiability through publication. For this reason, this platform
must not be used where coercion or vote-buying are a real risk.

### I received a reminder even though I already voted.
The reminder is sent 48 hours before closing to registered people with **no
ballot recorded**. If you just voted, the two may have crossed; your vote is
indeed counted. You can check this after closing with your tracking code.

### I was told I am not eligible for this consultation.
Exactly one roll entry matches your declaration, but its **electoral-list
type** does not give a vote on **this** poll (for example, being registered
only on the supplementary European list for a municipal question).
If in doubt about your registration, contact the mairie.

### Can I vote both online and on paper?
No. Only one channel per voter. If a paper ballot has been keyed in for you,
online voting is refused (and the reverse), until the first one is deleted
at the mairie.

### Is the interface usable on a phone and with a screen reader?
Yes. The interface complies with RGAA and is usable on a phone. Ranking the
propositions always has an alternative to drag-and-drop (numbered drop-down
lists), usable with the keyboard and a screen reader.
