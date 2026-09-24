<!-- SPDX-License-Identifier: 0BSD -->

# Documentation

Two sections for two kinds of reader. The authority above both is at the root of
the repository: the functional requirements (`cahier-des-charges.md`, French,
authoritative; `requirements-en.md`, its translation) and the implementation
specification (`spec-plateforme-vote.md`).

## `manuel/` — for the people who use the platform

French is the reference language; each served document has an English twin
suffixed `-en`. The application reads these files from disk and serves them
itself, so their paths and names are fixed: renaming one breaks the site.

| Reader | Document |
|---|---|
| everyone, to find the right guide | [`manuel/README.md`](manuel/README.md) |
| elector | [Guide de l'électeur](manuel/guide-electeur.md) · [en](manuel/guide-electeur-en.md) |
| elected official or agent in the espace mairie | [Guide de l'espace mairie](manuel/guide-espace-mairie.md) · [en](manuel/guide-espace-mairie-en.md) |
| IT contact installing and running an instance | [Guide de l'administrateur d'instance](manuel/guide-administrateur.md) (French only) |
| anyone checking a published result | [Vérifier un résultat par vous-même](manuel/verifier.md) · [en](manuel/verifier-en.md) |
| anyone wanting to know how a result is reached | [Les méthodes de dépouillement, expliquées](manuel/methodes-de-depouillement.md) · [en](manuel/methodes-de-depouillement-en.md) |
| any of the above, with a precise question | [Foire aux questions](manuel/faq.md) · [en](manuel/faq-en.md) |
| a maintainer regenerating the screenshots | [`manuel/captures/README.md`](manuel/captures/README.md) |

## This directory — for developers and reviewers

| Document | Read it to… |
|---|---|
| [`architecture.md`](architecture.md) | find your way round the code: components, app dependencies, key flows, external interfaces, the back-office screen map. Start here. |
| [`review-guide.md`](review-guide.md) | review the code: reading order, critical paths, privacy-sensitive areas, where each invariant is enforced and tested. |
| [`glossary.md`](glossary.md) | match a code identifier to its French interface term and its meaning. |
| [`canonical-serialisation.md`](canonical-serialisation.md) | know the exact bytes the closure hash covers. The contract between the Python code, the published CSV and the Rust verifier: change one, change all three. |
| [`publication-format.md`](publication-format.md) | know the layout of the published JSON document, which the verifier reads and checks claim by claim. Versioned; a change to a member the verifier reads is a new version. |
| [`specification-decision-log.md`](specification-decision-log.md) | find where and why the code departs from the specification, and which departures are still open (status table at the top). Cited as `#n` in code and commits. |
| [`review-notes.md`](review-notes.md) | see the suspected defects found in the September 2026 documentation pass, with their severity. |
| [`roadmap.md`](roadmap.md) | see the changes agreed in principle but deferred, and what each would touch. |

Rules for the whole tree (self-sufficiency of `manuel/`, French authoritative, where
a departure from the specification is recorded) are in the root `CLAUDE.md`,
"Conventions".
