# SPDX-License-Identifier: 0BSD
"""T-50: the service definitions under ``contrib/init/`` (§15).

Three checks:

* ``systemd-analyze verify`` on ``polls.service``;
* ``shellcheck`` on the OpenRC, FreeBSD and OpenBSD scripts;
* no hardcoded path in those three shell scripts — every polls-specific
  absolute path is the fallback of a ``${VAR:-…}`` / ``: ${VAR:=…}`` parameter
  expansion, so a non-Debian install redirects it without editing the script.

The first two need binaries the CI ``services`` job has; here they run when the
binary is present and skip otherwise. The path check is pure and always runs.
The systemd unit is excluded from the path check: systemd does no ``${VAR:-…}``
substitution in ``ExecStart`` / ``WorkingDirectory`` / ``EnvironmentFile``, so
its prefixes are necessarily fixed and ``systemd-analyze`` covers it instead.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

_INIT = Path(__file__).resolve().parents[2] / "contrib" / "init"
_UNIT = _INIT / "polls.service"
_SHELL_SCRIPTS = [_INIT / name for name in ("polls.openrc", "polls.rc.freebsd", "polls.rc.openbsd")]

#: An absolute path that mentions the project — the kind that must stay
#: overridable. ``${name}`` interpolations carry no literal "polls" and are not
#: matched.
_POLLS_PATH = re.compile(r"/[A-Za-z0-9_./-]*polls[A-Za-z0-9_./-]*")
_DEFAULT_EXPANSION = (":-", ":=", ':-"', ':="')


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck not installed")
@pytest.mark.parametrize("script", _SHELL_SCRIPTS, ids=lambda p: p.name)
def test_t50_shell_scripts_pass_shellcheck(script: Path) -> None:
    result = subprocess.run(  # noqa: S603
        ["shellcheck", str(script)],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(shutil.which("systemd-analyze") is None, reason="systemd-analyze not installed")
def test_t50_the_unit_passes_systemd_analyze_verify() -> None:
    result = subprocess.run(  # noqa: S603
        ["systemd-analyze", "verify", str(_UNIT)],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    # The only tolerated complaint is that the deploy tree is absent on this
    # host — ``ExecStart`` points into ``/opt/polls`` which exists only after
    # the playbook has run. Any other diagnostic is a real defect in the unit.
    noise = re.compile(r"is not executable: No such file or directory")
    real = [line for line in result.stderr.splitlines() if line.strip() and not noise.search(line)]
    assert not real, result.stdout + result.stderr


@pytest.mark.parametrize("script", _SHELL_SCRIPTS, ids=lambda p: p.name)
def test_t50_no_hardcoded_path_in_a_shell_script(script: Path) -> None:
    offenders: list[tuple[int, str, str]] = []
    for lineno, raw in enumerate(script.read_text().splitlines(), start=1):
        line = raw.split("#", 1)[0]
        if "polls" not in line:
            continue
        for match in _POLLS_PATH.finditer(line):
            before = line[: match.start()].rstrip()
            if not before.endswith(_DEFAULT_EXPANSION):
                offenders.append((lineno, match.group(0), raw.strip()))
    assert not offenders, f"{script.name}: hardcoded path(s) {offenders}"


def test_t50_the_init_directory_holds_the_four_documented_files() -> None:
    present = {p.name for p in _INIT.iterdir() if p.is_file()}
    assert {
        "polls.service",
        "polls.openrc",
        "polls.rc.freebsd",
        "polls.rc.openbsd",
    } <= present
