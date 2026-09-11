# Statement of Functional Requirements — Commune Polling Platform

**A French commune**
v0.5 — functional scope only; no technical choices. Rules are numbered `R-x.y` and are the reference used by the implementation specification.

> English version of the *Cahier des charges fonctionnel*. **The French text governs**: where this translation and the French diverge, the French prevails, and this document is to be corrected rather than relied upon. Both are at v0.5 and rule-for-rule aligned.

---

## 1. Purpose and scope

**R-1.1** The platform allows the commune to organise consultative polls of its registered electors, conducted online, with provision for ballots collected on paper and entered by a member of the municipal council.

**R-1.2** Nothing about a particular poll is hardcoded: neither its title, nor its options, nor its dates, nor its tally method. All of it is configuration.

**R-1.3** The platform is intended for a single commune. Multi-authority management is out of scope, without the design having to preclude it in future.

**R-1.4** Polls are consultative. The public page of each poll states expressly that the result informs the deliberation of the municipal council without binding it, and that the poll does not constitute a *consultation des électeurs* within the meaning of articles L1112-15 et seq. of the CGCT.

**R-1.5** The software is published as open source, one instance per commune.

---

## 2. Roles

**R-2.1** Roles are assigned poll by poll, with the exception of that of commune administrator.

| Role | Permissions |
|---|---|
| Commune administrator | Creates polls, assigns the roles specific to each poll, imports the electoral roll. This role does not of itself carry any access to ballots. |
| Poll administrator | Modifies the configuration while the poll is in draft; opens, closes and publishes the poll; rules on registrations flagged for manual review. |
| Entry operator (council member) | Enters, corrects and deletes the poll's paper ballots; issues receipts. |
| Auditor | Read-only access to the poll configuration, to the anonymised list of ballots and to the entirety of the audit log. |
| Elector | Registers, casts and, where the poll permits, modifies their vote; verifies the recording of their own ballot. |

**R-2.2** Each operator holds a personal named account. Shared accounts are prohibited by design: the system requires one account per natural person.

**R-2.3** No role permits an elector who voted online to be associated with the ballot they cast (see R-7.4).

**R-2.4** The administrative interface is purpose-built. It is used by council members and mairie staff, is subject to R-14.1 like the rest of the site, and must not present destructive actions alongside routine ones.

---

## 3. The poll object and its lifecycle

**R-3.1** A poll comprises: a title; a description; an ordered list of at least two options; an opening date and time; a closing date and time; a timezone; a tally method and its version; the ballot constraints (complete ranking required or not, ties permitted or not); a tie-break rule; whether an elector may modify a cast ballot (R-7.1); whether participation figures are displayed while the poll is open (R-11.5); the list types conferring eligibility (R-4.7); the enabled languages (R-14.3); the formal requirements applicable to paper ballots (R-8.2); a frozen copy of the electoral roll; a test-poll indicator; a state.

**R-3.2** State changes are strictly ordered: `draft → open → closed → published`. No transition is reversible.

**R-3.3** The configuration is freely modifiable in the `draft` state and becomes immutable upon transition to the `open` state.

**R-3.4** Sole exception to R-3.3: the closing date may be extended while the poll is open. The extension is recorded in the audit log with the identity of the operator, the timestamp and a mandatory reason, and is displayed on the public page of the poll.

**R-3.5** Closure at the fixed date and time is enforced server-side. Ballots and modifications arriving after that instant are refused.

**R-3.6** A poll may be created by duplicating the full configuration of an existing poll (R-3.1), excluding the electorate and the ballots; or from a named template (R-3.9), which carries over only the tally method and its version, the ballot constraints, the tie-break rule, the formal requirements applicable to paper ballots, whether the ballot may be modified, the list types conferring eligibility, and the enabled languages — the new poll's title, description and options remain to be entered.

**R-3.7** A poll marked as a test poll is excluded from public listings, from published results and from all statistics. This quality is fixed at creation and is not modifiable.

**R-3.8** Several polls may run simultaneously among the same electorate. Each is independent in every respect: separate registration, separate frozen copy of the electoral roll, separate tokens, separate ballots.

**R-3.9** A poll, in whatever state, may be saved as a named template, carrying over the same elements a template supplies at creation (R-3.6). A template is not a poll: it has no title, description, options, dates, electorate or ballots, and is subject to no lifecycle; only its name, chosen by the operator, identifies it.

---

## 4. Electorate

**R-4.1** Eligibility is reserved to persons entered on the electoral roll of the commune.

**R-4.2** The roll is imported by the commune administrator from an `.xlsx` or `.csv` export. Only what is necessary is imported: birth surname, name in use, forenames, date of birth, and list type. Sex, nationality, birth commune, birth department, birth country, address, polling station, constituency, canton and order number are not imported, save that the address is imported where postal enrolment is in use. Nationality in particular reveals national origin and is in any event implied by the list type.

**R-4.3** Upon transition to the `open` state, the poll constitutes a frozen and immutable copy of the electoral roll, archived with it. Subsequent modifications to the roll have no effect on an open or closed poll.

**R-4.4** The frozen copy remains accessible to auditors after closure, so that the question of who was eligible to vote remains verifiable at a later date. The identity data are held in clear rather than hashed, this being required by the review queue, by the operator search at R-8.3 and by this rule; the retention period at R-13.3 is what bounds the exposure.

**R-4.5** The import procedure comprises: selection of the file and mapping of the columns; a preliminary validation report; a preview submitted for express confirmation; and transactional execution, the import being applied in full or abandoned in full. The import is recorded in the audit log with the file name, its hash, the number of rows and the identity of the operator. A new import replaces the current roll in its entirety and has no effect on polls already open.

Only a structurally unusable file aborts the import: a missing mandatory column, or rows carrying no name. Duplicate entries, uncertain dates and incomplete rows are reported and imported, being facts about the roll rather than defects in the file.

**R-4.6** The export is not one row per elector. An elector entitled to vote in more than one kind of election appears once per list type, with identical identity data. The import collapses such rows into a single roll entry carrying a set of list types; failing which one person holds two entries and may register twice.

**R-4.7** Eligibility is filtered by list type, configured for each poll. A consultation on a municipal question concerns the *liste principale* and the *liste complémentaire municipale*; enrolment on the *liste complémentaire européenne* alone does not confer standing on such a question.

**R-4.8** The order number appearing on the roll is neither unique nor stable: it is renumbered whenever the roll changes, and may not serve as a key.

**R-4.9** Dates of birth are not uniformly well-formed, particularly for electors born abroad. A date that does not parse is retained verbatim and the entry flagged as uncertain; such an entry is imported normally, since refusing it would exclude a real elector, but never matches automatically and is always referred to the review queue.

---

## 5. Registration

**R-5.1** Registration is specific to a given poll. An elector taking part in two simultaneous polls registers twice and receives two independent tokens. This is an accepted consequence of R-13.4.

**R-5.2** The registration form collects: the surname, the forenames, the date of birth, the email address, and a declaration on honour, in the form of a tick-box, of enrolment on the electoral roll of the commune. The form accepts either the birth surname or the name in use, and says so.

**R-5.3** The registration is matched against the frozen copy of the electoral roll on normalised name and date of birth. Normalisation covers case, diacritics, hyphens, apostrophes, particles, the order of forenames, and comparison against both the birth surname and the name in use. The date of birth carries the greater part of the discrimination, so the comparison of names may be lenient.

**R-5.4** Outcomes:
- exactly one matching entry — registration proceeds;
- no matching entry, several matching entries, or an entry flagged uncertain under R-4.9 — the registration is placed in the manual review queue;
- a matching entry whose list types do not confer eligibility under R-4.7 — registration is refused, with the reason recorded.

In review cases, the administrator accepts or rejects the registration with reasons. An accepted registration passes to the pending-confirmation state under R-5.5, never directly to an active state. The elector is informed that their registration is under review.

**R-5.5** Registration is confirmed by a link sent to the declared email address. An unconfirmed registration carries no ballot, permits no vote, and is not counted in participation figures.

**R-5.6** The confirmation email contains, where the poll permits modification, the modification link, which ceases to operate at closure. It contains no tracking code: the tracking code attaches to a ballot, which does not yet exist at registration, and is issued only when the vote is cast (R-6.4) or on the paper receipt (R-8.4).

**R-5.7** A reminder is sent 48 hours before closure to registered electors who have not cast a vote.

**R-5.8** Registration endpoints are subject to rate limiting.

**R-5.9** A given roll entry may give rise to only one registration per poll. Any attempt to register against an entry already registered is refused, invites the person to contact the mairie, and is recorded in the audit log and flagged to the poll administrator. No detail of the existing registration is disclosed.

**R-5.10** A given email address may likewise give rise to only one registration per poll, the address being compared in lower case and otherwise as given. No normalisation of aliases is performed: the handling of suffixes and dots is a matter of provider convention, and any rule concerning them would either merge distinct persons or give false assurance as to those it failed to catch. Two persons sharing a single mailbox therefore cannot both register online; their route is the paper channel at the mairie.

**R-5.11** At no point before the mailbox is confirmed is the matched identity displayed back to the person registering, failing which the form would become a means of confirming, from a name and a date of birth, that a person is enrolled.

**R-5.12** The identity data appearing on the roll are obtainable by any elector under article L.37 of the electoral code. Matching against the roll therefore establishes eligibility, not identity, and the assurance afforded by self-registration alone is limited accordingly.

---

## 6. Ballot

**R-6.1** The ballot presents the poll options and collects a ranking conforming to the constraints defined for that poll. These constraints are enforced on the server, and not merely in the browser.

**R-6.2** The display order of the options is randomised for each elector, independently of the order recorded in the configuration.

**R-6.3** The ranking interface provides an alternative to drag-and-drop (numbered drop-down lists or equivalent), usable with a keyboard and with a screen reader.

**R-6.4** On the first cast, the elector is shown a summary of their ranking and their tracking code, and receives both by email. On a later modification, the summary is shown on screen; no email is sent, the tracking code being unchanged (R-7.2) and already held by the elector.

**R-6.5** Where the poll does not permit modification, the ballot page states this before submission, and not merely in the confirmation.

---

## 7. Modification and anonymity

**R-7.1** Whether an elector may modify a cast ballot is settled for each poll. Where modification is permitted, the elector may modify as often as they wish until closure, by means of the modification link. Where it is not, the ballot is cast once and any later use of the link is refused.

**R-7.2** Every modification creates a new version of the ballot. Versions are never overwritten, and no ballot is ever physically deleted. Each ballot carries a status distinguishing the version in force, superseded versions, ballots withdrawn by an operator under R-8.5, and entries awaiting countersignature under R-8.7. Only ballots in force are counted, covered by the hash at R-11.1, and published under R-11.2.

**R-7.3** The version history is retained for audit purposes.

**R-7.4** The link between an elector voting online and their ballot is not reconstructible from the database. Each elector receives a random token, communicated exclusively in the confirmation email. The elector's record carries `H("voter" ‖ salt ‖ token)`; the ballot record carries `H("ballot" ‖ salt ‖ token)`. No join between the two tables is possible. Only the holder of the token can access their own ballot.

**R-7.4 bis** Where the poll does not permit modification, no link between token and ballot is computed or stored at all: nothing then connects a ballot to the token that cast it, and the elector's tracking code is the sole handle. A poll seeking the closest approach to a secret ballot disables modification.

**R-7.4 ter** The token travels in a hyperlink. The system therefore exchanges it, on first use, for a session, redirects to an address not containing it, suppresses the logging of these addresses, and instructs browsers to transmit no referrer. Absent these measures the undertaking at R-7.4 is not honoured.

**R-7.5** Administrators consequently hold only two irreconcilable lists: the names accompanied by a "has voted / has not voted" indicator, and the anonymous rankings identified by their tracking code.

**R-7.6** Where modification is permitted, an elector who loses their token can neither recover it nor modify their ballot. The confirmation email states this expressly. The ballot remains counted.

---

## 8. Paper ballots

**R-8.1** An entry operator may record a ballot on behalf of an elector without internet access.

**R-8.2** The formal requirements applicable to this voting channel are settled poll by poll, from among the following options: collection of a signed paper form; countersignature by a second operator; formal reconciliation at closure. None is enabled by default. R-8.3 to R-8.5 remain applicable in every case and constitute the minimum traceability core.

**R-8.2 bis** Where the signed paper form is required, it comprises the ranking, the declaration on honour, the elector's identity, together with a statement that a ballot entered by this channel remains associated with the elector's identity in the system — unlike a ballot cast online — for the purposes of traceability and of any subsequent deletion at their request. In the absence of a form, this information is carried on the receipt provided for at R-8.4.

**R-8.3** Before creating the ballot, the operator carries out a search in the frozen copy of the electoral roll and is shown near matches for confirmation. Where two entries cannot be distinguished on the data held, the operator resolves the matter with the elector present, and not from the record.

**R-8.4** Entry gives rise to the printing of a receipt bearing the tracking code, handed to the elector.

**R-8.5** Correction and deletion of a paper ballot are available to the operator, each requiring a mandatory reason and giving rise to an entry in the audit log stating the operator, the timestamp and the state before and after. Correction remains available whether or not the poll permits electors to modify their votes: the repair of a keying error is not the same act as an elector changing their mind.

**R-8.6** Where formal reconciliation is required by the configuration, the paper forms are retained by the commune and reconciled against the recorded ballots at closure, the reconciliation record being signed and archived. Failing that, the audit log serves as the record.

**R-8.7** Countersignature by a second operator is a configuration option, disabled by default. Where enabled, the entry is not deemed final, and the ballot is not counted, until validation by a second named operator.

**R-8.7 bis** Closure is refused while any entry awaits countersignature. The poll administrator either procures the countersignatures, or overrides the refusal with a mandatory reason which is recorded and appears in the publication. Uncountersigned entries are not counted, and the silent discarding of ballots at closure is not permitted.

---

## 9. Concurrence of the two voting channels

**R-9.1** Each elector's record carries a voting-channel indicator: none, online, or paper.

**R-9.2** Paper ballot already recorded → online voting is refused, with a message inviting the person to attend the mairie to obtain the prior deletion of their paper ballot.

**R-9.3** Online ballot already recorded → paper entry is refused. A ballot cast online is anonymous and cannot be located from the elector's registration (R-7.4); it therefore cannot be displaced. Where the poll permits modification, the elector is invited to modify their own ballot online; failing that, the screen states that the online vote is final.

**R-9.4** Deletion of a paper ballot by an operator clears the indicator and re-opens online voting for the elector concerned.

---

## 10. Tally

**R-10.1** The tally constitutes a pure function: set of ballots in force + method + parameters → winner, intermediate results and a statement of the reasoning in plain terms.

**R-10.2** The method identifier and its version are recorded with the poll, so that a published result remains reproducible notwithstanding subsequent changes to the code.

**R-10.3** Methods available from the first release: the Schulze method, single-choice voting (plurality), approval voting.

**R-10.4** Where the poll configuration does not require a complete ranking, the Schulze method treats unranked options as tied in last place.

**R-10.5** Where the method leaves a genuine tie, the tie-break rule specific to the poll applies. Default rule: a computed drawing of lots, random but reproducible and verifiable by any third party, conducted as follows:

1. a random seed is drawn and published at the opening of the poll, where it becomes immutable under R-3.3;
2. the tie-break seed equals `H(opening seed ‖ closure hash)`, the closure hash being that defined at R-11.1;
3. the options to be separated are ordered by ascending value of `H(tie-break seed ‖ option identifier)`, the first prevailing.

No library pseudo-random generator is used, reproducibility having to depend neither on the language nor on the execution platform. The opening seed, the closure hash and the detail of the computation are published with the result.

**R-10.5 bis** The procedure described at R-10.5 ensures that the outcome of the tie-break is neither predictable before closure nor capable of being influenced by the organiser, the tie-break seed depending on the entire set of ballots cast. The poll configuration may nevertheless substitute a physical drawing of lots conducted publicly, the result of which is recorded in the publication.

**R-10.6** The tally is carried out only after closure. It reads ballots alone, and never the register of electors.

**R-10.7** The tally rests on the identifiers of the options, never on their labels; the result and the hash at R-11.1 are thereby independent of the labels and their translations. The labels are frozen with the rest of the configuration on transition to the `open` state (R-3.3), so that the published result shows exactly the labels the electors ranked.

---

## 11. Publication and verifiability

**R-11.1** At closure, the system computes and displays a cryptographic hash covering the set of ballots in force, prior to publication of the result. The serialisation adopted is documented, so that the hash may be recomputed from the published data alone.

**R-11.2** Publication comprises: the anonymised list of ballots (tracking code and ranking) in CSV and JSON formats; the pairwise matrix; the statement of the reasoning leading to the result; the number of registered electors, the number of ballots cast by each of the two channels and the number of electors who did not vote; the opening seed and the detail of any tie-break; and the closure hash. The published list contains the ballots in force and nothing else.

**R-11.3** Where the number of options is small, a summary table giving the number of ballots for each distinct ordering is published in addition. For three fully ranked options, this table comprises six rows and permits the result to be recomputed on its own.

**R-11.4** Any elector may find their tracking code in the published list and verify that their ballot was recorded as they cast it. Any third party may recompute the result from the published data. An independent implementation of the tally and of the hash is published for that purpose.

**R-11.5** Participation figures are displayed while a poll is open only where its configuration so provides; the default is that they are not, the publication of turnout during a poll being capable of influencing it. Where they are not displayed, no page or interface discloses a running count. Participation is in no case published broken down by polling station.

---

## 12. Audit log

**R-12.1** The log is append-only and records at minimum: modifications to poll configurations; state changes and extensions of the closing date; imports and frozen copies of the electoral roll; decisions rendered on registrations submitted for review; refused registration attempts; the creation, correction and deletion of paper ballots; countersignatures and closure overrides; overrides of the channel-concurrence warning; role assignments; and access to the log itself.

**R-12.2** Each entry states the operator, the timestamp, the object concerned, the state before and after, and the reason where one is required.

**R-12.3** Auditors have read access to the entirety of the log. No role permits an entry to be modified or deleted.

**R-12.4** Each category of entry declares which of its fields hold personal data, so that the retention procedure at R-13.3 may erase precisely those fields while preserving the entry, its author, its date and its reason.

---

## 13. Data protection

**R-13.1** The commune is the data controller. The processing is entered in the register of processing activities.

**R-13.2** An information notice is presented at registration, stating the purpose, the legal basis, the retention periods, the recipients and the rights of data subjects, together with the identity of the referent responsible for requests and complaints.

**R-13.3** Retention periods: identity data (registration records, frozen copy of the electoral roll, association of paper ballots with electors) are deleted on expiry of a period of two months running from closure of the poll, and the fields declared under R-12.4 are erased from the audit log at the same term. The starting point is closure and not publication: a poll that closes but is never published — an unresolved physical tie-break, an abandoned result — would otherwise keep this data indefinitely. Anonymised ballots, the published result and the log itself are retained beyond that term.

**R-13.4** The salts used to derive the tokens are specific to each poll, so that the platform permits no correlation of the participation of the same person in two distinct polls. No cross-poll participation report is provided.

**R-13.4 bis** Name and date of birth being stable identifiers, the guarantee stated at R-13.4 holds only for processing carried out by the platform: direct access to the data of two concurrent polls would allow participation to be correlated by their means. The risk, which bears on participation alone and not on the content of ballots, is contained by restricting access to identity data to the poll administrator alone and by the retention period fixed at R-13.3. Its acceptance is a matter for the commune.

**R-13.5** IP addresses, where recorded for the purposes of rate limiting, are not retained beyond what is necessary for that sole purpose.

**R-13.6** A real roll export constitutes the personal data of every elector in the commune. It is never placed in the source repository, the test suite or a fault report; test data are synthetic.

---

## 14. Accessibility, presentation and languages

**R-14.1** The public interface and the administrative interface conform to the RGAA, being a public online service.

**R-14.2** The interface is usable from a mobile telephone.

**R-14.3** The interface is available in French by default and, where the configuration so provides, in other languages. Interface text is translated by catalogue; the title, description and option labels of a poll are translated for each enabled language. A poll may not be opened while a translation is missing, and a missing translation falls back to the poll's default language rather than to nothing. French remains authoritative: where a translation and the French text diverge, the French text governs, and the pages carrying legal effect — the notices at R-1.4 and R-13.2 — say so.

---

## 15. Matters remaining to be settled

1. For each poll: its propositions, in each enabled language, and its opening and closing dates.
2. The identity of the referent referred to at R-13.2.
3. For each poll: the formal options retained for the paper channel under R-8.2.
4. Acceptance by the commune of the residual risk set out at R-13.4 bis.
5. **Whether every registration is submitted to review, or only those that R-5.4 refers there.** Given R-5.12, an exact match establishes less than it appears; universal review is the stronger position and, at the scale of a small commune, an affordable one.
6. **Whether registration opens before voting does.** As drafted, the frozen copy is taken at the opening of the poll, so registration, review and voting all begin at the same instant, and an elector registering shortly before closure may be unable to vote in time. A separate registration period, the copy being frozen at its start, would resolve this.
