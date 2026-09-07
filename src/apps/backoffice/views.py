# SPDX-License-Identifier: 0BSD
"""The espace mairie (§6.5).

Purpose-built, not Django admin, which is not routed in production at all
(§14). Eleven screens, all scoped to a poll and gated by the per-poll roles of
§3.7; this is the majority of the build and is scheduled first, before the
tally, the verifier and the publication artefacts.

Two rules govern every screen and are not negotiable per-view:

* every mutating screen posts through the service functions of §5.1 — no view
  writes through the ORM directly;
* no screen displays a voter's identity alongside ballot content, except the
  paper-entry screen, where the association is deliberate and logged.

TODO(scaffold): screens 1–11 of §6.5, in that order. The dashboard comes first
because it is what names ``open_poll``'s and ``close_poll``'s blockers before
the hour they would fire (§4) — ``opening_blockers`` and ``closing_blockers``
in ``apps.elections.transitions`` already return them.
"""
