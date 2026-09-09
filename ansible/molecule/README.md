<!-- SPDX-License-Identifier: 0BSD -->
# Molecule scenarios — the slow acceptance tests

These need a throwaway host, not the ordinary test database (§12), so they run
in their own CI job and are not part of `pytest`.

| Scenario | Acceptance test | What it does |
|----------|-----------------|--------------|
| `default` | **T-38** | Provisions and deploys into a fresh systemd container, then runs `converge` a second time (`molecule idempotence`) and a third in `--check` mode, asserting no drift, and that `SECRET_KEY`, the database and the audit log are untouched by the repeat runs. |
| `restore` | **T-16** | Full install with a backup taken, records the audit-log row count and the published closure hash, wipes the state directory, runs `restore.yml`, and asserts the audit log came back whole and the closure hash still recomputes from the restored data. |

## Status

`roles/polls/tasks/*.yml` are still `debug` stubs. The scenarios therefore prove
the **harness** — the container comes up, the role applies, idempotence and
`--check` run — and every assertion that needs a real artefact (the env file,
the database, a backup snapshot, the running service) is guarded: it warns and
is skipped until that artefact exists, and bites automatically once
`provision.yml`, `deploy.yml`, `backup.yml` and `restore.yml` are written.

## Running locally

Prerequisite: a container backend. This repo's environment blocks unprivileged
user namespaces (`kernel.apparmor_restrict_unprivileged_userns=1`), so pick one:

**Docker** (daemon runs as root, simplest):

```sh
sudo apt-get install -y docker.io
sudo usermod -aG docker "$USER"      # log out and back in, or: newgrp docker
```

**Rootless Podman** (no daemon; flip the AppArmor gate first):

```sh
echo 'kernel.apparmor_restrict_unprivileged_userns=0' | sudo tee /etc/sysctl.d/60-userns.conf
sudo sysctl --system
sudo apt-get install -y podman
```

Molecule does not env-interpolate `driver.name`, so point it at podman with a
one-time user-level base config that both scenarios inherit:

```sh
mkdir -p ~/.config/molecule
printf 'driver:\n  name: podman\n' > ~/.config/molecule/config.yml
```

Then, from the repository root:

```sh
uv tool install --with 'molecule-plugins[docker]' --with 'molecule-plugins[podman]' \
                --with ansible-core molecule
cd ansible
molecule test                 # the default scenario (T-38)
molecule test -s restore      # the restore round trip (T-16)
molecule converge             # apply once and leave the container up for poking
molecule login                # shell into it
molecule destroy
```

## Changing the target release

`molecule.yml` pins `geerlingguy/docker-debian12-ansible`. For another Debian
release edit the two `image:` lines, or override them in
`~/.config/molecule/config.yml`. The role only supports current Debian stable
(`roles/polls/tasks/main.yml`), so the image must stay a Debian one.
