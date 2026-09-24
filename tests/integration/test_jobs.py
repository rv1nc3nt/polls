# SPDX-License-Identifier: 0BSD
"""Self-locking (§14, T-49, T-51).

T-37/T-49 (``test_registration_http.py``) and T-66 (``test_retention_purge.py``)
run a command twice *in sequence* and check the second run has nothing left to
do — real coverage, but of state-based idempotency, not of the lock itself.
T-49 and T-51's actual text is stronger: a second instance started *while the
first is still running* exits 0 without acting. That needs something genuinely
holding the lock when the second call is made, which sequential re-runs never
exercise. ``job_lock`` is the one place this can go wrong (a bug there affects
every scheduled command identically), so it is tested directly once, then
through one real ``JobCommand`` end to end.
"""

from __future__ import annotations

import fcntl
import logging
from pathlib import Path
from typing import Any

import pytest
from django.core.management import call_command
from django.test import override_settings

from apps.core.jobs import EXIT_ERROR, AlreadyRunning, JobCommand, job_lock
from apps.core.models import JobRun
from apps.elections.models import Poll, PollState
from tests.conftest import force_announce


def test_job_lock_refuses_a_concurrent_holder(tmp_path: Path, db: None) -> None:
    with override_settings(JOB_LOCK_DIR=tmp_path):
        with job_lock("probe"):
            with pytest.raises(AlreadyRunning):
                with job_lock("probe"):
                    pytest.fail("must not be reached while the outer lock is held")


def test_job_lock_is_released_on_exit_for_the_next_run(tmp_path: Path, db: None) -> None:
    """Not a given from the refusal alone: a lock that never releases would
    refuse every run forever rather than only a genuinely concurrent one."""
    with override_settings(JOB_LOCK_DIR=tmp_path):
        with job_lock("probe"):
            pass
        with job_lock("probe"):
            pass


def test_t51_a_concurrent_open_poll_run_exits_0_and_touches_nothing(
    tmp_path: Path, open_window_poll: Poll
) -> None:
    """``open_window_poll`` is moved straight to ``announced`` with
    ``opens_at`` already past (bypassing ``announce_poll``'s guard, which
    would otherwise refuse a past ``opens_at`` — not what this test is
    about), so the command's own selection would open it — the lock, not the
    query, is what must stop the second instance here."""
    force_announce(open_window_poll)
    handle = (tmp_path / "open_poll.lock").open("w")
    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        with override_settings(JOB_LOCK_DIR=tmp_path):
            with pytest.raises(SystemExit) as exc_info:
                call_command("open_poll")
        assert exc_info.value.code == 0
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()

    open_window_poll.refresh_from_db()
    assert open_window_poll.state == PollState.ANNOUNCED
    assert open_window_poll.opening_seed is None


def test_a_refused_open_poll_still_finalises_its_jobrun_row(
    tmp_path: Path, open_window_poll: Poll
) -> None:
    """A refusal signals through ``raise SystemExit(EXIT_REFUSED)`` after
    setting ``run.succeeded``/``run.detail`` (T-53) — and ``SystemExit`` is a
    ``BaseException``, not an ``Exception``, so a narrower except clause in
    ``job_lock`` would let it fall straight to ``finally`` without ever
    calling ``save()``. The row this table exists to make a job observable by
    must not be left ``succeeded=NULL`` forever, indistinguishable from one
    still running."""
    open_window_poll.languages = ["fr", "en"]
    open_window_poll.save(update_fields=["languages"])
    force_announce(open_window_poll)

    with override_settings(JOB_LOCK_DIR=tmp_path):
        with pytest.raises(SystemExit) as exc_info:
            call_command("open_poll")
    assert exc_info.value.code == 1

    run = JobRun.objects.filter(command="open_poll").latest("started_at")
    assert run.succeeded is False
    assert run.finished_at is not None
    assert run.detail["refused"]


class _Crashing(JobCommand):
    """No ``job_name``: the lock and the logs fall back to the module name."""

    def handle_job(self, run: JobRun, **options: Any) -> None:
        raise RuntimeError("boom")


def test_an_unhandled_error_exits_2_logged_and_recorded(
    tmp_path: Path, db: None, caplog: pytest.LogCaptureFixture
) -> None:
    """Review note L9: an unexpected failure exits EXIT_ERROR, distinct from
    a refusal (1), names the job even without ``job_name``, and still leaves
    its ``JobRun`` row marked failed."""
    with override_settings(JOB_LOCK_DIR=tmp_path), caplog.at_level(logging.ERROR, "polls.jobs"):
        with pytest.raises(SystemExit) as exc_info:
            call_command(_Crashing())
    assert exc_info.value.code == EXIT_ERROR
    assert "test_jobs: failed" in caplog.text
    assert "boom" in caplog.text
    run = JobRun.objects.get(command="test_jobs")
    assert run.succeeded is False
