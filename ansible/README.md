<!-- SPDX-License-Identifier: 0BSD -->
# Ansible — deployment (§15)

The supported installation path: a bare Debian VM to a running instance by
editing one inventory file and running one command.

**Full instructions are the [guide de l'administrateur d'instance](../docs/manuel/guide-administrateur.md)**
(French) — control-machine prerequisites, the inventory variables, the
tag-by-tag breakdown (`provision`, `deploy`, `backup`, `restore`, `smoke`),
the scheduled-task options, and supervision. The nightly snapshot and the
restore playbook both cover `DJANGO_MEDIA_ROOT` (option images and the
commune logo/favicon) alongside the database — see
[`docs/specification-decision-log.md`](../docs/specification-decision-log.md)
#18 for how the two are kept in correspondence. What follows here is the
layout of this directory, not a replacement for that guide.

## Quick start

```sh
cp inventory.example.ini inventory.ini
# edit inventory.ini: domain, admin email, smoke-test email
ansible-playbook -i inventory.ini site.yml --ask-vault-pass
```

Idempotent: running it again against an already-provisioned host changes
nothing that has not actually drifted.

## Layout

    site.yml                the full run (provision, deploy, backup are
                             tagged so each can also run on its own)
    restore.yml              disaster recovery: provision → deploy → restore
                             the most recent (or a named) snapshot → smoke
                             (§15, T-16)
    inventory.example.ini   copy to inventory.ini and edit; secrets come from
                             ansible-vault, never from this file
    requirements.yml        Ansible collections the docker Molecule driver
                             needs (CI and local `molecule` runs only — not
                             part of a real deploy)
    roles/polls/             the one role, tasks split by tag: provision.yml,
                             deploy.yml, backup.yml, restore.yml, smoke.yml
    molecule/                the slow acceptance tests (T-16, T-38) that need
                             a throwaway host — see molecule/README.md

## Molecule — testing the deploy itself

[Molecule](https://ansible.readthedocs.io/projects/molecule/) is the standard
Ansible role-testing framework: it spins up a throwaway target, applies a role
against it, runs assertions against the result, and tears the target down
again. It exists here because none of this project's other test gates can
reach `site.yml` or `restore.yml` — `uv run pytest` runs against Django's test
database with no network and no root, and can no more provision a Debian host,
install a systemd unit or bind port 8000 than it can send real mail. Molecule
is the only place these playbooks run against a live target instead of just
being read; without it, a change to `roles/polls/tasks/deploy.yml` is checked
by `ansible-lint`'s opinion of the YAML and nothing else.

Concretely, for each scenario Molecule:

1. **`create`** — starts a container from `geerlingguy/docker-debian12-ansible`
   with `systemd` as PID 1 (`command: /usr/lib/systemd/systemd`), so
   `systemctl start polls` inside it behaves as it would on a real VM, not a
   stub.
2. **`converge`** — runs `converge.yml`, which applies the `polls` role exactly
   as `site.yml` does. This is the actual deploy under test, not a mock of it.
3. **`idempotence`** *(default scenario only)* — runs `converge.yml` a second
   time and fails if any task reports `changed`.
4. **`verify`** — runs the scenario's own assertions (below) against the
   converged container.
5. **`destroy`** — removes the container, whether or not the run passed.

Two scenarios each prove one acceptance test from §12 that nothing else
reaches:

- **`default` (T-38 — idempotence).** After `converge` and `idempotence`,
  `verify.yml` re-runs the deploy a third time in `--check` mode and asserts a
  clean diff (`changed=0`), then asserts that `SECRET_KEY`
  (`/etc/polls/polls.env`, mode `0600`, owned by the `polls` user), the SQLite
  database and the `audit_auditevent` row count are exactly what the first
  `converge` produced. That last check is the point of the scenario: a
  playbook that regenerates the secret key or re-applies a migration
  destructively on every run would still pass a bare `changed=0` count if the
  regenerated values happened to overwrite themselves cleanly, so T-38 checks
  the actual bytes and row counts, not just Ansible's own change-tracking. It
  finishes by asserting `/sante` answers `200` once `polls.service` is active.
- **`restore` (T-16 — disaster recovery).** `converge.yml` performs a full
  install, which (via the role's `backup` tag) leaves an initial snapshot
  under `/var/backups/polls`. `verify.yml` then drops a marker file under
  `media/`, takes a fresh backup so that file is actually inside a snapshot
  (R-3.12), records the audit-log row count and the published poll's closure
  hash, and **deletes `/var/lib/polls` outright** — simulating total loss of
  the host's state, the scenario `restore.yml` exists to recover from. It runs
  `restore.yml` against the same container (provision → restore the newest
  snapshot → smoke) and then asserts: the database file is back; the media
  marker survived byte-for-byte; the audit log recovered every row; the
  published `closure_hash` column still matches; and — the strongest check —
  that hash still *recomputes* from the restored ballots via
  `apps.core.canonical.closure_hash(live_ballots(poll))`, the same code path
  the Rust verifier and the public results page use. A restore that silently
  dropped a ballot or wrote the media archive back empty fails on that last
  assertion, not in production.

Both scenarios set `polls_smoke_require_mail: false` (the containers have no
MTA), run in their own CI job rather than under `pytest` — they take minutes,
not milliseconds, and need a container backend rather than a database — and
are otherwise ordinary consumers of the `polls` role: nothing in
`roles/polls/` is aware it is being tested. Full instructions for running them
locally — container backend setup (Docker or rootless Podman), the one-time
driver config, and how to target a different Debian release — are in
[`molecule/README.md`](molecule/README.md).

## Scope

**Debian stable, one distribution, playbook-installed and tested in CI.**
Anything else — systemd on a non-Debian host, OpenRC, FreeBSD, OpenBSD — gets
service files under [`../contrib/init/`](../contrib/init/) instead: installed
by hand, best effort, not covered by this playbook or by CI beyond
`systemd-analyze verify` and `shellcheck` on the files themselves.
