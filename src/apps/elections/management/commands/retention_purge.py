# SPDX-License-Identifier: 0BSD
"""Delete identity data two months after closure, and the working roll two
months after import where idle (§11, R-13.3, R-13.3 bis).

Scheduled, logged and idempotent — not a manual procedure. State-based
selection, so a host that was down purges late rather than never.
"""

from __future__ import annotations

from typing import Any

from apps.core.jobs import JobCommand
from apps.core.models import JobRun
from apps.elections.retention import due_polls, purge, purge_working_roll


class Command(JobCommand):
    help = (
        "Purge les données d'identité des scrutins clos depuis deux mois, "
        "et la liste de travail inutilisée depuis deux mois."
    )
    job_name = "retention_purge"

    def handle_job(self, run: JobRun, **options: Any) -> None:
        reports = []
        for poll in due_polls():
            if options.get("dry_run"):
                self.stdout.write(f"would purge {poll.id}")
                continue
            report = purge(poll)
            reports.append(report.__dict__)
            self.stdout.write(
                f"purged {poll.id}: {report.registrations} registrations, "
                f"{report.roll_entries} roll entries, {report.paper_links} paper links"
            )

        working_roll_entries = 0
        if options.get("dry_run"):
            self.stdout.write("would check working roll")
        else:
            working_roll_entries = purge_working_roll()
            if working_roll_entries:
                self.stdout.write(f"purged working roll: {working_roll_entries} entries")

        run.detail = {"purged": reports, "working_roll_entries": working_roll_entries}
