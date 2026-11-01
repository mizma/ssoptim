#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (c) 2026 aoi mizma <aoi.mizma@path-works.net>
# SPDX-License-Identifier: MIT

"""M0 scaffold: the package installs, imports and exposes the CLI shape.

Acceptance criteria (DESIGN.md §9, M0): `ssoptim --version` prints a version
(the click-cutter fallback `0.0.0+dev` from a bare checkout, otherwise the
setuptools-scm version) and `ssoptim optimize` runs.
"""

import pytest

from click.testing import CliRunner

from ssoptim import __version__
from ssoptim.cli import cli


def test_version_fallback_from_bare_checkout():
    """`ssoptim --version` works and reports the built/dev version (M0)."""
    assert __version__
    result = CliRunner().invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_group_shape_one_optimize_verb():
    """0.1.0 registers exactly one command: `optimize` (§11 item 23)."""
    assert list(cli.commands.keys()) == ["optimize"]


def test_optimize_stub_runs():
    """The verb is live: `ssoptim optimize -v` exits 0 (M0)."""
    result = CliRunner().invoke(cli, ["optimize", "-v"])
    assert result.exit_code == 0
