#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (c) 2026 aoi mizma <aoi.mizma@path-works.net>
# SPDX-License-Identifier: MIT

"""M7 packaging: the bundled character set and the installed CLI.

Acceptance (DESIGN.md 9, M7): the bundled set loads and round-trips through the
4.1 validation rules, and an installed copy works with `optimize` and its
config defaults.  The wheel-level check builds the distribution inside the
test session, so a packaging regression - bundled data not shipped, or the
test fixtures shipped - fails here rather than in a release.
"""

import glob
import os
import shutil
import subprocess
import zipfile

import pytest
from click.testing import CliRunner

from ssoptim.cli import cli
from ssoptim.ssoptim.data import build_party, load_characters, normalize_scenario, bundled_character_paths
from ssoptim.ssoptim.data import SLOTS, SKILL_KEYS
from ssoptim.ssoptim.plugins import build_run_context, resolve_candidate
from ssoptim.ssoptim.talent import CORE_TALENT_COUNT, MAX_SUB_LEVEL

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLED = ("アヤメ", "チトセ", "テレサ")


def bundled_party():
    """The bundled three, slotted main/sub1/sub2 (R-01)."""
    characters = load_characters([])  # nothing but the bundled set
    return build_party({"main": "チトセ", "sub1": "アヤメ", "sub2": "テレサ"}, characters)


class TestBundledSet:
    """The wheel's own character data (R-22; authored from the R-44 extract)."""

    def test_bundled_files_are_found(self):
        paths = bundled_character_paths()
        assert len(paths) == 3
        assert all(os.path.isfile(p) for p in paths)
        assert sorted(os.path.basename(p) for p in paths) == ["アヤメ.yml", "チトセ.yml", "テレサ.yml"]

    def test_bundled_set_passes_the_4_1_rules(self):
        characters = load_characters(bundled_character_paths())
        assert set(BUNDLED) <= set(characters)
        for name in BUNDLED:
            character = characters[name]
            assert character.name == name
            assert set(character.stats) == {"Atk", "HP", "DEF"}
            assert all(isinstance(v, (int, float)) for v in character.stats.values())
            assert character.extra.get("element") == "Aqua"  # free-form key survives
            for set_name in ("talents_main", "talents_sub"):
                talents = character.talent_sets[set_name]
                assert len(talents) == 16  # R-03
                assert [t["core"] for t in talents[:CORE_TALENT_COUNT]] == [True] * 4
                assert not any(t["core"] for t in talents[CORE_TALENT_COUNT:])
                assert len({t["name"] for t in talents}) == 16  # R-18
            assert set(character.skills) == set(SKILL_KEYS)
            assert character.skills["auto_skill"]["loop_time"] == 20.0  # R-30 timing authored
            assert character.skills["ult_skill"]["cd"] == 30.0

    def test_gating_pair_stays_out_of_the_aggregate(self):
        """R-35/R-43: duration/activation are convention metadata, not buffers."""
        party = bundled_party()
        members, vars_layout = party["members"], party["vars"]
        ctx = build_run_context(members, vars_layout, normalize_scenario(None), {}, 0)
        levels = []
        for slot in SLOTS:
            levels += [1, 1, 0, 0] + [MAX_SUB_LEVEL] * 12  # R-04 core pair
        resolve_candidate(levels, ctx)
        assert "duration" not in ctx["aggregated"]
        assert "activation" not in ctx["aggregated"]
        assert "Atk_multiplier" in ctx["aggregated"]
        assert "slotUltimateDmg" in ctx["aggregated"]

    def test_load_is_idempotent(self):
        """A repeated search entry keeps the first definition (R-18)."""
        paths = bundled_character_paths()
        first = load_characters(paths)
        again = load_characters(list(paths) + list(paths))
        assert set(first) == set(again)
        for name in BUNDLED:
            assert first[name].stats == again[name].stats
            assert [t["name"] for t in first[name].talent_sets["talents_sub"]] == [
                t["name"] for t in again[name].talent_sets["talents_sub"]
            ]


class TestBundledCli:
    """`optimize` runs on the bundled set alone, as an installed copy would."""

    def test_bundled_only_invocation(self):
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
                "20",
                "-f",
                "auto_attack",
                "--maxiter",
                "10",
                "--popsize",
                "8",
                "--runs",
                "1",
            ],
        )
        assert result.exit_code == 0
        assert "party:" in result.output
        assert "objective_plugin: auto_attack" in result.output

    def test_user_character_dir_still_works(self):
        """README Layout: the repo-root characters/ dir is user data."""
        characters = load_characters([os.path.join(ROOT, "characters")])
        assert "Char A" in characters
        assert characters["Char A"].stats["Atk"] == 6966


@pytest.fixture(scope="module")
def wheel_names(tmp_path_factory):
    out = tmp_path_factory.mktemp("wheel")
    uv = shutil.which("uv")
    assert uv, "uv not found"
    completed = subprocess.run([uv, "build", "--out-dir", str(out)], cwd=ROOT, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr[-500:]
    wheel = sorted(glob.glob(str(out / "*.whl")))[-1]
    return zipfile.ZipFile(wheel).namelist()


class TestWheelContents:
    """`uv build` ships the bundled data and nothing else (R-22, R-44)."""

    def test_bundled_characters_are_shipped(self, wheel_names):
        shipped = [n for n in wheel_names if n.startswith("ssoptim/characters/")]
        assert len(shipped) == 3
        for name in BUNDLED:
            assert any(name in n for n in shipped)

    def test_repo_only_dirs_are_not_shipped(self, wheel_names):
        for prefix in ("tests/", "wiki_data/", "characters/", "plugins/"):
            assert not [n for n in wheel_names if n.startswith(prefix)]
