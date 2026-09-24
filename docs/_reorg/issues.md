<!-- SPDX-License-Identifier: 0BSD -->

# Documentation issues found during the reorganisation

## Outcome (2026-09-24, branch `docs/reorg`)

Approved: keep every path, add an index, fix D1–D13, reorder the decision log (D8),
add its status table (G2).

| Item | Resolved in |
|---|---|
| D8 | `d28dc43` decision log in numeric order (block move, no line changed) |
| D1, D3, D4, D5, D6, D7 | `b14901b` developer documents |
| G2 | `9b5eed3` decision-log status table |
| D9, D10, D11, D12 | `5f8563c` manual, fr and en together (`a0040f7` re-wrap) |
| D13 | `4943815` CLAUDE.md, worded to what the code and the test hold |
| G1 | `0465337` `docs/README.md`, root READMEs' `docs/` line |
| D2 | nothing to change in the doc; the code comment is C1 |
| **still open** | C1, C2 (code comments), C3 (code defects), G3 (threat model), Q1 |

Verification: 154 relative links, 0 broken; no file removed or renamed (one added);
every `docs/…md` path cited anywhere in the repository resolves; every removed line is
one of the items above; `pytest` 840 passed, 3 skipped; ruff clean.

The original findings follow unchanged. Each gives the location, the evidence and
the resolution that was proposed. **D** = a document is wrong or inconsistent (in
scope to fix once approved); **C** = the fix would touch source code or a code comment
(out of scope for this task); **G** = a gap; **Q** = a question for the requirements
owner.

## Documents contradicted by the code or by a later decision

**D1. `architecture.md:106` — sandbox deletion shown from `draft` only.** The state
diagram has `draft --> [*]: delete (sandbox only)`. `elections/sandbox.delete_poll`
deletes a sandbox poll "from any state (R-3.7)" (decision log #26).
*Fix:* redraw as a note ("a sandbox poll can be deleted from any state") instead of a
`draft` edge.

**D2. `architecture.md:224–239` vs `src/apps/backoffice/views.py:2107`.** The doc says
14 numbered screens (and its table lists 14); the code comment says "eleven numbered
screens". The doc is right; the comment is stale → see C1.

**D3. `glossary.md:108` — "window … Checked on the clock, not on `state`".** Reversed by
decision log #33: a write needs `state = open` *and* the clock inside the window
(`windows.check_ballot_window`, `check_registration_window`, migration 0014).
*Fix:* "Admitted only while the poll is `open`; bounded by the clock, never by
`state` alone (INV-2, decision log #33)."

**D4. `review-guide.md:31, 137` — stale figures.** "later migrations that redefine
triggers (0005–0013)": `0014_inv2_requires_open.py` redefines the INV-2 triggers.
"~800 tests": 843 are collected today.
*Fix:* "0005–0014"; drop the count or say "~850".

**D5. `specification-decision-log.md` #12 (l. 377–398) reads as current but three of
its statements were reversed.** "*Ouvrir maintenant* — offered throughout `draft`"
(reversed by #19), "gate on the clock … never on `state`" (reversed by #33),
"*Clôturer maintenant* — offered only once `paper_entry_deadline` has passed, never
before … deliberately not symmetric" (reversed by #34). #13 and #26 already carry
forward pointers ("Not reopened by…", "Since #36…"); #12 has none.
*Fix:* append one line, in the log's own style: "**Superseded in part** by #19 (no
opening from `draft`), #33 (the state admits) and #34 (early closure)." The log keeps
settled entries by design, so the body stays.

**D6. `specification-decision-log.md` #16 (l. 650–653).** "the same restriction screen
2 already puts on the manual `close_poll` trigger" — true when written, not since #34.
*Fix:* forward pointer to #34, as for D5.

**D7. `specification-decision-log.md` #24 (l. 854) — wrong cross-reference.**
"Specification, §4 and item 5 above": the *Ouvrir maintenant* reasoning it quotes is
item **12** (item 5 is paper entry). Same entry, l. 861: "`_status_key`, item 15" — the
function was introduced by item **14**.
*Fix:* "item 12", "item 14".

**D8. `specification-decision-log.md` — entries out of numeric order.** The file reads
1–10, **12, 13, 11, 18**, 14–17, 19–36. Items are cited by number everywhere (~25 code
comments), so the order only costs reading time.
*Fix (optional):* move 11 before 12 and 18 after 17. This is a pure block move: no
number changes and every `#n` reference stays valid.

**D9. `manuel/README.md:5–8, 41` breaks CLAUDE.md's "`docs/manuel/` is
self-sufficient" rule.** It links `cahier-des-charges.md` and `spec-plateforme-vote.md`
and cites `R-x.y` and `§n`. It is not served, but CLAUDE.md holds the whole tree to the
rule.
*Fix:* "Ce manuel accompagne la plateforme de consultation. Il est rédigé en français ;
c'est la seule langue de référence." For l. 41, replace "même convention que
`requirements-en.md` à côté de `cahier-des-charges.md`" with no comparison.

**D10. `manuel/faq.md:134–135`, `manuel/faq-en.md:135–136` — *Clôturer maintenant*.**
"n'apparaît qu'une fois l'échéance de saisie des bulletins papier atteinte" / "only
appears once the paper-ballot keying deadline has been reached". Contradicts
`guide-espace-mairie.md:214` ("proposé à tout moment une fois le scrutin ouvert … clôture
anticipée"), decision log #34 and `transitions.is_early_closure`.
*Fix:* restate the guide's rule in both FAQs: offered at any time once open; before
the deadline it is an early closure and needs a reason. Served text: both languages in
one commit.

**D11. `manuel/verifier.md:264–266`, `verifier-en.md:246–248` — the verifier
"recomputes Schulze, plurality or approval".** `verifier/core/src/report.rs:9`: "nothing
here implements plurality or approval". This is review note M2, still open. `glossary.md`
("recomputes the hash and Schulze result") is correct.
*Fix:* say that the verifier recomputes the closure hash for every poll and the winner
for Schulze polls only. Do this unless the verifier gains the two methods first.

**D12. `manuel/captures/README.md:57` — inventory row 13.** "Configuration modifiable
(brouillon), avec *Annoncer* et *Ouvrir maintenant*". Since #19 a draft offers
*Annoncer* only, and the capture itself contains no "Ouvrir".
*Fix:* "avec *Annoncer*".

## Contradictions between documents

**D13. CLAUDE.md "INV-1 / INV-5" vs `architecture.md:81–84` and review note L3.**
CLAUDE.md says "the two apps' modules do not import each other". The code, as
`architecture.md` describes it correctly: `registrations` never imports `ballots`, but
`ballots.services` and `ballots.views` import `registrations.services` by design.
*Fix:* "`registrations` never imports `ballots`; `ballots` reaches `registrations` only
through `registrations.services`, passing ids and strings, and neither `models.py`
imports the other." CLAUDE.md is instructions to agents as well as documentation, so
this is your call.

## Duplicates and overlaps (no merge recommended)

- **Check commands** appear in CLAUDE.md, `review-guide.md`, README.md and README-en.md.
  Each serves a different reader, and they agree except for D4's test count. Keep all
  four; CLAUDE.md stays the authoritative list.
- **"The clock refuses, the state admits"** is restated in CLAUDE.md,
  `architecture.md`, `review-guide.md`, `roadmap.md` and decision log #33. Each restatement
  summarises the rule and cites #33, so #33 is the single authority. These are summaries,
  not copies.
- **`glossary.md` vs spec §2.** The spec's list is a 16-row French→code word list;
  the glossary is a ~60-row domain glossary covering most of those pairs (not
  *récépissé*, *mairie*, *conseil municipal*). They do not disagree. Keep both;
  optionally, have the glossary's preamble say that it extends spec §2.
- **Capture pipeline** is described in `manuel/README.md` (summary) and
  `captures/README.md` (commands). The summary links to the commands. Fine.

## Source-side mismatches (out of scope, recorded only)

**C1. `src/apps/backoffice/views.py:2107`** — "the eleven numbered screens": there are
14 (screens 13 and 14 were added later; `architecture.md` is right).

**C2. `docs/manuel/captures/outils/render_captures.py:1`** — docstring says "under
`docs/captures/`"; the script writes `docs/manuel/captures/`.

**C3. Review notes M2, M3, M4 and L1–L11** remain open in the code (M2–M4 re-checked
2026-09-24). They are defects, not documentation problems.

## Gaps

**G1. No index of `docs/`.** Three documents have no inbound link at all:
`glossary.md`, `review-guide.md` and `roadmap.md`. README.md/README-en.md describe
`docs/` as "Canonical serialisation, spec divergences, manuel/", which omits five of the
seven developer documents. Addressed by step 4e, `docs/README.md`, plus a one-line
edit of the two README tree descriptions.

**G2. The decision log has no status overview.** Items still open are buried in
long entries: #10 (direct duplication of a poll), #17 (signed-form layout), #29 (R-5.5
wording), and #9 by design. A short table at the top (number, title, status) would let a
reviewer find them. This would be new content, so it needs your approval.

**G3. No threat-model document.** Review notes' first open question asks whether the
receipt-mail linkage "is stated in the threat model". There is none; the substance is
spread over spec §5/§7, `review-guide.md` "Security- and privacy-sensitive areas" and
`review-notes.md`. Writing one is new content, beyond a reorganisation. Noted, not
proposed here.

## For the requirements owner

**Q1. Early closure is impossible on a poll requiring reconciliation, and nothing says
so.** `ballots.services.record_reconciliation` refuses before `paper_entry_deadline`,
and `closing_blockers`' `reconciliation_pending` has no override. So a poll with
`paper_requires_reconciliation` can never close early, although #34 and
`guide-espace-mairie.md:214` say *Clôturer maintenant* is "proposé à tout moment".
Either the manual says so, or the reconciliation gate follows the early-closure instant.
