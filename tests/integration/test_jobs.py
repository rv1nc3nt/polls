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
from pathlib import Path

import pytest
from django.core.management import call_command
from django.test import override_settings

from apps.core.jobs import AlreadyRunning, job_lock
from apps.elections.models import Poll, PollState


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
    """``open_window_poll`` is ``draft`` with ``opens_at`` already past, so the
    command's own selection would open it — the lock, not the query, is what
    must stop the second instance here."""
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
    assert open_window_poll.state == PollState.DRAFT
    assert open_window_poll.opening_seed is None
