#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (c) 2026 aoi mizma <aoi.mizma@path-works.net>
# SPDX-License-Identifier: MIT

"""M8 PLUGINS.md: every code snippet runs verbatim, and so does the CLI.

Acceptance (DESIGN.md 9, M8): each python block of PLUGINS.md executes against
the fixture party of `tests/data/characters.yml`, and the documented
`ssoptim optimize -f ./plugins/simple_dps.py:objective` invocation reports the
documented objective value - the guide's numbers are the tool's, not estimates.
"""

import os
import re
import yaml

import pytest
from click.testing import CliRunner

from ssoptim.cli import cli

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(ROOT, "PLUGINS.md")

# the shipped sample's value for the guide's fixture candidate, and its value
# once the search has been run over the bundled party (section 11)
DPS_ON_FIXTURE_CANDIDATE = 17221.271390400085
DOCUMENTED_BUNDLED_OBJECTIVE = 43534.76885493751


def blocks(text):
    """The python fences of the guide, in document order."""
    return [m.group(1) for m in re.finditer(r"```python\n(.*?)\n```", text, re.S)]


@pytest.fixture(scope="module")
def snippet_namespace():
    text = open(DOC, encoding="utf-8").read()
    namespace = {"__name__": "__main__"}
    for index, code in enumerate(blocks(text)):
        exec(compile(code, "%s[%d]" % (DOC, index), "exec"), namespace)
    return namespace


class TestSnippetsRun:
    """The guide's blocks execute in order in one namespace."""

    def test_all_blocks_are_executed(self, snippet_namespace):
        text = open(DOC, encoding="utf-8").read()
        assert len(blocks(text)) >= 8
        # the setup block defined the fixture run, the last block the failure path
        assert "x" in snippet_namespace and "ctx" in snippet_namespace
        assert "broken" in snippet_namespace

    def test_dps_walkthrough_value(self, snippet_namespace):
        assert abs(snippet_namespace["fn"](snippet_namespace["x"], snippet_namespace["ctx"]) - DPS_ON_FIXTURE_CANDIDATE) < 1e-9

    def test_kernel_and_builtin_agree(self, snippet_namespace):
        """R-33/R-34: the plugin-side Atk fold reproduces the built-in value."""
        assert abs(snippet_namespace["value"] - 53073.79031778418) < 1e-9

    def test_gating_uptime_is_derived_not_assumed(self, snippet_namespace):
        assert abs(snippet_namespace["gated_uptime"](  # the guide's own helper
            [t for t in snippet_namespace["ctx"]["members"]["main"].talents if t["name"] == "Sub Atk Up"][0],
            12.0,
        ) - 1.0
    ) < 1e-12


class TestDocumentedInvocation:
    """Section 11's console session is reproducible from the repo root."""

    def test_objective_value_matches_the_guide(self):
        os.chdir(ROOT)
        result = CliRunner().invoke(
            cli,
            [
                "optimize",
                "-m",
                "チトセ",
                "-s",
                "アヤメ",
                "-s",
                "テレサ",
                "-t",
                "40",
                "-f",
                "./plugins/simple_dps.py:objective",
                "--seed",
                "7",
                "--maxiter",
                "60",
                "--popsize",
                "16",
                "--runs",
                "2",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "objective_plugin: ./plugins/simple_dps.py:objective" in result.output
        doc = yaml.safe_load(result.output)
        assert doc["feasible"] is True
        assert doc["total_level"] == 40
        assert abs(doc["objective"] - DOCUMENTED_BUNDLED_OBJECTIVE) < 1e-9
