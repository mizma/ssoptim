#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (c) 2026 aoi mizma <aoi.mizma@path-works.net>
# SPDX-License-Identifier: MIT

"""M0 scaffold: the package installs, imports and exposes the CLI shape.

Acceptance criteria (DESIGN.md 8, 7): `ssoptim --version` prints a version
(the click-cutter fallback `0.0.0+dev` from a bare checkout, otherwise the
setuptools-scm version) and `ssoptim optimize` runs.
"""

import pytest

from click.testing import CliRunner

from ssoptim import __version__
from ssoptim.cli import cli


def test_version_fallback_from_bare_checkout():
    """`ssoptim --version` works and reports the built/dev version (scaffold shape)."""
    assert __version__
    result = CliRunner().invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_group_shape_one_optimize_verb():
    """0.1.0 registers exactly one command: `optimize` (DESIGN.md 7)."""
    assert list(cli.commands.keys()) == ["optimize"]


def test_optimize_runs_the_whole_surface():
    """The verb is live and takes every option of DESIGN.md 7 (0.1.0 state).

    A bare invocation is now a usage error (no party, no budget), which the
    scaffold test above could not tell apart: the stub used to exit 0, while
    the implemented pipeline reports the missing configuration with exit 2.
    """
    result = CliRunner().invoke(cli, ["optimize", "-v"])
    assert result.exit_code == 2
    help_result = CliRunner().invoke(cli, ["optimize", "--help"])
    assert help_result.exit_code == 0
    for flag in ("--config", "--main", "--sub", "--total-levels", "--objective", "--char",
                 "--restrictions", "--total-level-mode", "--out", "--scenario",
                 "--objective-opts", "--show-params", "--maxiter", "--popsize", "--runs",
                 "--seed", "--no-polish"):
        assert flag in help_result.output

