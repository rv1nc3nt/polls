# Service definitions for other platforms

Two support tiers, so nobody mistakes one for the other (§15):

* **Debian** — playbook-installed (`ansible/`) and tested in CI.
* **Everything here** — service files provided, installation by hand, best
  effort.

| File | Platform |
|---|---|
| `polls.service` | systemd (Debian, and any systemd host) |
| `polls.openrc` | OpenRC (Alpine, Gentoo) — `supervise-daemon`, so a crashed process restarts |
| `polls.rc.freebsd` | FreeBSD — `daemon(8)` with a pidfile and `-r` |
| `polls.rc.openbsd` | OpenBSD |

Requirements these impose, all satisfied above:

* **No hardcoded Linux paths.** Prefix, configuration directory, state
  directory and service user are variables; BSD installs under
  `/usr/local/etc` and `/var/db`, Linux under `/etc` and `/var/lib`.
* **Restart on failure everywhere**, or the non-systemd targets silently lose
  the property the systemd unit provides.
* **Logging with no journal.** The management commands write to stdout and
  stderr; these scripts redirect to a log file, and the packaged logrotate or
  `newsyslog` configuration goes alongside them.
* **cron is the scheduler on these platforms**, which is already the default.
* **musl targets build some wheels from source.** On Alpine, install the build
  dependencies for `argon2-cffi` (`gcc`, `musl-dev`, `libffi-dev`,
  `python3-dev`) in case no `musllinux` wheel is published for the installed
  Python version.

T-50 checks these: `systemd-analyze verify` on the unit, `shellcheck` on the
OpenRC and `rc.d` scripts, and no hardcoded path in any of them.
