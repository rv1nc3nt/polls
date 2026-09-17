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

## Scope

**Debian stable, one distribution, playbook-installed and tested in CI.**
Anything else — systemd on a non-Debian host, OpenRC, FreeBSD, OpenBSD — gets
service files under [`../contrib/init/`](../contrib/init/) instead: installed
by hand, best effort, not covered by this playbook or by CI beyond
`systemd-analyze verify` and `shellcheck` on the files themselves.
