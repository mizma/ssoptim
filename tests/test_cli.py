#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (c) 2026 aoi mizma <aoi.mizma@path-works.net>
# SPDX-License-Identifier: MIT

"""M6 cli.py + report.py: options, precedence, 4.3 YAML, exit codes.

Acceptance (DESIGN.md 7, 4.3): the documented invocation runs end-to-end and
writes the 4.3 result YAML; CLI options beat the config file and
``--scenario DEF=...`` beats the config's ``scenario:`` block; ``--show-params``
dumps the aggregated parameter map and the effective scenario (R-36); and the
DESIGN.md 7 exit-code table holds for each failure kind.

The runs use the reduced fixture box (two pinned cores per member, one free
sub talent) so the solver finishes in well under a second; the option surface,
the precedence chain and the YAML are exercised exactly as the README shows
them.
"""

import os
import yaml

import pytest
from click.testing import CliRunner

from ssoptim.cli import CONFIG_DEFAULT, CONFIG_TEMPLATE, settings_of
from ssoptim.cli import cli
from ssoptim.ssoptim.data import InputError
from ssoptim.ssoptim.constraints import Infeasible
from ssoptim.ssoptim.plugins import PluginError
from ssoptim.ssoptim.optimize import NoFeasible

CHARS = os.path.join(os.path.dirname(os.path.dirname(__file__)), "tests", "data", "characters.yml")

# The reduced run configuration: real 3-member party, one free sub talent per
# member, small solver knobs.
PARTY_YML = """\
party:
  main: "Char A"
  sub1: "Char B"
  sub2: "Char C"
data_dirs:
  - ./chars
total_level: 20
scenario:
  DEF: 350
  RES: 570
solver:
  maxiter: 40
  popsize: 12
  runs: 2
  seed: 1
"""

RESTRICTIONS_YML = """\
main:
  talent_levels:
    - { name: "Core Echo", min: 1 }
    - { name: "Core Mark", min: 1 }
    - { name: "Core Silence", max: 0 }
    - { name: "Core Ward", max: 0 }
    - { name: "Sub Atk Up", max: 6 }
sub1:
  talent_levels:
    - { name: "B Sub Core Atk", min: 1 }
    - { name: "B Sub Core Abs", min: 1 }
    - { name: "B Sub Core None", max: 0 }
    - { name: "B Sub Core Crit", max: 0 }
    - { name: "B Team Atk 1", max: 6 }
sub2:
  talent_levels:
    - { name: "C Sub Core Atk", min: 1 }
    - { name: "C Sub Core Abs", min: 1 }
    - { name: "C Sub Core None", max: 0 }
    - { name: "C Sub Core Crit", max: 0 }
    - { name: "C Team Abs 1", max: 6 }
"""


class TestSettingsPrecedence:
    """The 7 line: CLI > --restrictions file > --config file > defaults."""

    @pytest.fixture
    def sandbox(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        os.mkdir(tmp_path / "chars")
        import shutil

        shutil.copy(CHARS, tmp_path / "chars" / "characters.yml")
        (tmp_path / "party.yml").write_text(PARTY_YML, encoding="utf-8")
        (tmp_path / "rest.yml").write_text(RESTRICTIONS_YML, encoding="utf-8")
        return tmp_path

    def test_config_then_cli(self, sandbox):
        base = settings_of({"verbose": 0, "config": str(sandbox / "party.yml")})
        assert base["total_level"] == 20  # 4.2 value
        assert base["scenario"]["DEF"] == 350
        won = settings_of({"verbose": 0, "config": str(sandbox / "party.yml"), "total_level": 12, "main": "Char Z"})
        assert won["total_level"] == 12  # CLI wins (7)
        assert won["main"] == "Char Z"
        assert won["total_level_mode"] == "exact"  # built-in default layer

    def test_restrictions_file_merges_over_config(self, sandbox):
        config = settings_of({
            "verbose": 0,
            "config": str(sandbox / "party.yml"),
            "restrictions_file": str(sandbox / "rest.yml"),
        })
        assert config["restrictions"]["main"]["talent_levels"][0]["min"] == 1
        # the restrictions file brings slots the config file never mentioned
        assert set(config["restrictions"]) == {"main", "sub1", "sub2"}
        assert config["restrictions"]["sub2"]["talent_levels"][-1] == {"name": "C Team Abs 1", "max": 6}

    def test_scenario_override_beats_config_block(self, sandbox):
        won = settings_of(
            {"verbose": 0, "config": str(sandbox / "party.yml"), "scenario": ["DEF=500", "res_table={ Lux: 250 }"]}
        )
        assert won["scenario"]["DEF"] == 500  # --scenario beats the block (R-36)
        assert won["scenario"]["RES"] == 570  # untouched keys keep the block value
        assert won["scenario"]["res_table"] == {"Lux": 250}

    def test_objective_opts_reach_the_context(self, sandbox):
        won = settings_of(
            {"verbose": 0, "config": str(sandbox / "party.yml"), "objective_opts": ["uptime_fraction=0.6"]}
        )
        assert won["objective_opts"] == {"uptime_fraction": 0.6}

    def test_solver_knobs_merge(self, sandbox):
        won = settings_of({"verbose": 0, "config": str(sandbox / "party.yml"), "runs": 5, "no_polish": True})
        assert won["solver"]["runs"] == 5  # CLI over the 4.2 solver block
        assert won["solver"]["polish"] is False  # --no-polish
        assert won["solver"]["maxiter"] == 40  # config keeps the rest

    def test_unknown_config_key_is_exit_2(self, sandbox):
        (sandbox / "bogus.yml").write_text(
            PARTY_YML + "\ntypo_key: 3\n", encoding="utf-8"
        )
        with pytest.raises(InputError):
            settings_of({"verbose": 0, "config": str(sandbox / "bogus.yml")})

    def test_default_config_written_when_absent(self, sandbox):
        assert not (sandbox / CONFIG_DEFAULT).exists()
        settings_of({"verbose": 0})
        assert (sandbox / CONFIG_DEFAULT).read_text(encoding="utf-8") == CONFIG_TEMPLATE


class TestEndToEnd:
    """The README invocation runs and writes the 4.3 YAML (R-26)."""

    @pytest.fixture
    def sandbox(self, tmp_path, monkeypatch):
        import shutil

        monkeypatch.chdir(tmp_path)
        os.mkdir(tmp_path / "chars")
        shutil.copy(CHARS, tmp_path / "chars" / "characters.yml")
        (tmp_path / "party.yml").write_text(PARTY_YML, encoding="utf-8")
        (tmp_path / "rest.yml").write_text(RESTRICTIONS_YML, encoding="utf-8")
        return tmp_path

    def invoke(self, sandbox, args):
        result = CliRunner().invoke(cli, ["optimize"] + args)
        return result

    def test_result_yaml_written(self, sandbox):
        result = self.invoke(
            sandbox,
            [
                "-c",
                "party.yml",
                "--restrictions",
                "rest.yml",
                "-t",
                "20",
                "-f",
                "auto_attack",
                "-o",
                "result.yml",
                "-v",
            ],
        )
        assert result.exit_code == 0
        doc = yaml.safe_load((sandbox / "result.yml").read_text(encoding="utf-8"))
        assert doc["objective_plugin"] == "auto_attack"
        assert doc["total_level"] == 20
        assert doc["feasible"] is True
        assert set(doc["party"]) == {"main", "sub1", "sub2"}
        for slot in ("main", "sub1", "sub2"):
            block = doc["party"][slot]
            assert set(block) == {"core_talents", "talent_levels"}
            assert len(block["core_talents"]) == 2  # R-04/R-17
            levels = block["talent_levels"]
            assert len(levels) == 16  # R-03: the whole set is reported
            assert sum(levels.values()) >= 2
        assert sum(sum(b["talent_levels"].values()) for b in doc["party"].values()) == 20  # R-13

    def test_stdout_yaml_by_default(self, sandbox):
        result = self.invoke(
            sandbox,
            [
                "-c",
                "party.yml",
                "--restrictions",
                "rest.yml",
                "-t",
                "20",
                "-f",
                "auto_attack",
            ],
        )
        assert result.exit_code == 0
        doc = yaml.safe_load(result.output)
        assert doc["feasible"] is True
        assert "party" in doc

    def test_show_params_adds_aggregated_and_scenario(self, sandbox):
        result = self.invoke(
            sandbox,
            [
                "-c",
                "party.yml",
                "--restrictions",
                "rest.yml",
                "--scenario",
                "DEF=500",
                "-t",
                "20",
                "-f",
                "auto_attack",
                "--show-params",
            ],
        )
        assert result.exit_code == 0
        doc = yaml.safe_load(result.output)
        assert doc["scenario"]["DEF"] == 500  # effective profile the plugin got (R-36)
        assert "aggregated_params" in doc
        assert doc["aggregated_params"]["Atk_multiplier"] > 0

    def test_verbose_implies_show_params(self, sandbox):
        result = self.invoke(
            sandbox,
            ["-c", "party.yml", "--restrictions", "rest.yml", "-t", "20", "-f", "auto_attack", "-vv"],
        )
        assert result.exit_code == 0
        assert "aggregated_params" in result.output


class TestExitCodes:
    """DESIGN.md 7 exit-code table: 2 usage/config, 3 infeasible, 4 plugin, 5 no point."""

    @pytest.fixture
    def sandbox(self, tmp_path, monkeypatch):
        import shutil

        monkeypatch.chdir(tmp_path)
        os.mkdir(tmp_path / "chars")
        shutil.copy(CHARS, tmp_path / "chars" / "characters.yml")
        (tmp_path / "party.yml").write_text(PARTY_YML, encoding="utf-8")
        (tmp_path / "rest.yml").write_text(RESTRICTIONS_YML, encoding="utf-8")
        return tmp_path

    def invoke(self, sandbox, args):
        return CliRunner().invoke(cli, ["optimize"] + args)

    def test_missing_budget_is_exit_2(self, sandbox):
        result = self.invoke(sandbox, ["-c", "party.yml", "--restrictions", "rest.yml", "-f", "auto_attack"])
        (sandbox / "no_budget.yml").write_text(
            (sandbox / "party.yml").read_text(encoding="utf-8").replace("total_level: 20", ""),
            encoding="utf-8",
        )
        result = self.invoke(sandbox, ["-c", "no_budget.yml", "--restrictions", "rest.yml", "-f", "auto_attack"])
        assert result.exit_code == 2

    def test_bad_yaml_is_exit_2(self, sandbox):
        (sandbox / "broken.yml").write_text("party: [unclosed\n", encoding="utf-8")
        result = self.invoke(sandbox, ["-c", "broken.yml", "-t", "20"])
        assert result.exit_code == 2

    def test_unknown_character_is_exit_2(self, sandbox):
        result = self.invoke(
            sandbox, ["-c", "party.yml", "--restrictions", "rest.yml", "-t", "20", "-m", "Char Nobody"]
        )
        assert result.exit_code == 2

    def test_out_of_range_restriction_is_exit_2(self, sandbox):
        (sandbox / "bad_rest.yml").write_text(
            RESTRICTIONS_YML.replace('{ name: "Sub Atk Up", max: 6 }', '{ name: "Sub Atk Up", max: 9 }'),
            encoding="utf-8",
        )
        result = self.invoke(sandbox, ["-c", "party.yml", "--restrictions", "bad_rest.yml", "-t", "20"])
        assert result.exit_code == 2

    def test_three_subs_is_exit_2(self, sandbox):
        result = self.invoke(
            sandbox,
            [
                "-c",
                "party.yml",
                "--restrictions",
                "rest.yml",
                "-t",
                "20",
                "-s",
                "Char B",
                "-s",
                "Char C",
                "-s",
                "Char D",
            ],
        )
        assert result.exit_code == 2

    def test_infeasible_budget_is_exit_3(self, sandbox):
        result = self.invoke(sandbox, ["-c", "party.yml", "--restrictions", "rest.yml", "-t", "3"])
        assert result.exit_code == 3

    def test_plugin_load_failure_is_exit_4(self, sandbox):
        result = self.invoke(sandbox, ["-c", "party.yml", "--restrictions", "rest.yml", "-t", "20", "-f", "./nope.py:objective"])
        assert result.exit_code == 4

    def test_plugin_raise_is_exit_4(self, sandbox):
        (sandbox / "boom.py").write_text("def objective(x, ctx):\n    raise RuntimeError('boom')\n", encoding="utf-8")
        result = self.invoke(
            sandbox, ["-c", "party.yml", "--restrictions", "rest.yml", "-t", "20", "-f", "./boom.py:objective"]
        )
        assert result.exit_code == 4

    def test_error_carries_its_own_code(self):
        for exc, code in ((InputError, 2), (Infeasible, 3), (PluginError, 4), (NoFeasible, 5)):
            assert exc("m").code == code
