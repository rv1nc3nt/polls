# SPDX-License-Identifier: 0BSD
"""Scaffolding shared by the management commands (§14).

Nothing in the application knows what invokes them: cron, a systemd timer, a
container orchestrator or a person at a terminal are all equivalent. The weaker
schedulers guarantee none of the four properties below, so the commands provide
them themselves.

* **Self-locking.** ``flock`` on a state file plus a ``JobRun`` row. cron will
  happily start a second copy while the first is still running; relying on
  systemd's ``Type=oneshot`` instead would make the code correct under one
  scheduler only. A second instance exits 0 without acting (T-49, T-51).
* **State-based, not time-triggered.** Selection is by what is due and not yet
  done, never by "it is now T−48 h", so a host that was down acts late rather
  than not at all.
* **Idempotent, with meaningful exit codes**, so a re-run is harmless and a
  failure is visible to cron mail.
* **Logs to stdout and stderr**, captured by whatever invoked them; no
  assumption of journald. ``--log-file`` covers the rest.
"""

from __future__ import annotations

import fcntl
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Any

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from .models import JobRun

logger = logging.getLogger("polls.jobs")

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_ERROR = 2


class AlreadyRunning(Exception):
    """Another instance holds the lock. Not an error: exit 0, do nothing."""


@contextmanager
def job_lock(name: str) -> Iterator[JobRun]:
    """Exclusive lock for one command, plus the ``JobRun`` row that records it."""
    lock_dir = Path(settings.JOB_LOCK_DIR)
    lock_dir.mkdir(parents=True, exist_ok=True)
    handle: IO[str] = (lock_dir / f"{name}.lock").open("w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        handle.close()
        raise AlreadyRunning(name) from exc

    run = JobRun.objects.create(command=name)
    try:
        yield run
    except Exception:
        run.succeeded = False
        run.finished_at = timezone.now()
        run.save(update_fields=["succeeded", "finished_at"])
        raise
    else:
        if run.succeeded is None:
            run.succeeded = True
        run.finished_at = timezone.now()
        run.save(update_fields=["succeeded", "finished_at", "detail"])
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()


class JobCommand(BaseCommand):
    """Base class carrying the four properties above.

    Subclasses implement ``handle_job(run, **options)`` and let exceptions
    propagate; the exit code is this class's business.
    """

    job_name = ""

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--log-file", default=None, help="Also append logs to this file.")
        parser.add_argument(
            "--dry-run", action="store_true", help="Report what would happen; write nothing."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if options.get("log_file"):
            handler = logging.FileHandler(options["log_file"])
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            logging.getLogger("polls").addHandler(handler)
        try:
            with job_lock(self.job_name or self.__module__.rsplit(".", 1)[-1]) as run:
                self.handle_job(run, **options)
        except AlreadyRunning:
            logger.info("%s: another instance is running; nothing to do", self.job_name)
            sys.exit(EXIT_OK)

    def handle_job(self, run: JobRun, **options: Any) -> None:
        raise NotImplementedError
