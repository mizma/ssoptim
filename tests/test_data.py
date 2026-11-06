#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (c) 2026 aoi mizma <aoi.mizma@path-works.net>
# SPDX-License-Identifier: MIT

"""M1 data.py: YAML load, schema validation, scenario block, party model.

Acceptance criteria (DESIGN.md 4.1, 4.2): the loader round-trips the 4.1-shaped
fixture, cd/loop_time and multi-sources skills validate, the scenario block
merges over the kernel defaults, and a duplicate party plus invalid character
data both fail with the R-29 exit-2 error class.
"""

import math
import os

import pytest

from ssoptim.ssoptim.data import InputError, SCENARIO_DEFAULTS, SCENARIO_KEYS
from ssoptim.ssoptim.data import load_characters, load_yaml, build_character, build_party
from ssoptim.ssoptim.data import normalize_scenario, scenario_key_override, validate_res_table

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
CHARS = os.path.join(DATA_DIR, "characters.yml")
PARTY = os.path.join(DATA_DIR, "party.yml")
CHAR_D = os.path.join(DATA_DIR, "char_d_no_sub_skill.yml")
INVALID = os.path.join(DATA_DIR, "invalid_characters.yml")


def close(expected):
    return lambda actual: math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-12)


class TestFixtureRoundTrip:
    """The 4.1-shaped fixture loads into validated, normalized objects."""

    def test_all_three_characters_load(self):
        chars = load_characters([CHARS])
        # the bundled set inside the package is searched last (DESIGN.md 8), so a fixture
        # load sees its own characters plus the bundled ones
        assert {"Char A", "Char B", "Char C"} <= set(chars)
        assert chars["Char A"].stats == {"Atk": 6966, "HP": 94662, "DEF": 0}

    def test_both_talent_sets_required(self):
        chars = load_characters([CHARS])
        assert set(chars["Char A"].talent_sets) == {"talents_main", "talents_sub"}

    def test_free_form_character_keys_survive(self):
        """Unknown keys are tolerated, never fatal (R-20)."""
        chars = load_characters([CHARS])
        names = {talent["name"] for talent in chars["Char A"].talent_sets["talents_main"]}
        assert "Sub Signature" in names
        assert "signature_mark_uptime" in chars["Char A"].talent_sets["talents_main"][15]["params"]


class TestR32SkillNormalization:
    """Every skill ends up as one sources list; timing is data (R-30, R-31)."""

    def test_shorthand_damage_becomes_one_source(self):
        char = load_characters([CHARS])["Char A"]
        auto = char.skills["auto_skill"]
        assert len(auto["sources"]) == 1
        assert auto["loop_time"] == 4.2  # seconds per auto-attack cycle (R-30)
        assert auto["sources"][0]["damage"]["elemLuxDmg"] == {"skillPercentAmend": 11.30}
        assert "name" not in auto["sources"][0]  # labels only where authored (R-32)

    def test_multi_source_skill_keeps_own_timing(self):
        char = load_characters([CHARS])["Char A"]
        main = char.skills["main_skill"]
        assert main["cd"] == 12.0
        assert [s["name"] for s in main["sources"]] == ["hit", "mark"]
        assert main["sources"][1]["cd"] == 6.0  # that portion re-applies on its own period
        assert main["sources"][1]["damage"]["slotMarkDmg"] == {"skillPercentAmend": 1.22}

    def test_source_buffers_carry_the_pair(self):
        """R-43: duration/activation stay convention metadata, not parameters."""
        char = load_characters([CHARS])["Char A"]
        debuf = char.skills["main_skill"]["sources"][1]["debuf"]["DEF_rate_mod"]
        assert debuf["params"][1] == 0.10
        assert debuf["duration"] is not None and debuf["duration"][1] == 6.0
        assert debuf["activation"] == "main_skill"

    def test_missing_sub_skill_only_warns(self):
        """R-40: loader warns, never fails, for a support slot with no sub_skill."""
        seen = []
        chars = load_characters([CHAR_D, CHARS], log=lambda msg: seen.append(msg))
        assert "Char D" in chars
        assert "sub_skill" not in chars["Char D"].skills
        party = build_party({"main": "Char A", "sub1": "Char D", "sub2": "Char C"}, chars, log=lambda msg: seen.append(msg))
        assert party["members"]["sub1"].sub_skill is None
        assert len(party["vars"]) == 48  # the party still resolves
        assert any("no sub_skill" in m for m in seen)


class TestR17TalentOrder:
    """Core talents are the first four; the set shape is validated (R-03, R-17)."""

    def test_talent_count_and_core_positions(self):
        char = load_characters([CHARS])["Char A"]
        talents = char.talent_sets["talents_main"]
        assert len(talents) == 16
        assert [t["core"] for t in talents] == [True] * 4 + [False] * 12

    def test_interpolation_is_precomputed_once(self):
        char = load_characters([CHARS])["Char A"]
        talent = next(t for t in char.talent_sets["talents_main"] if t["name"] == "Sub Atk Up")
        table = talent["params"]["Atk_multiplier"]
        step = (0.18 - 0.045) / 5
        for level in range(1, 7):
            assert close(0.045 + step * (level - 1))(table[level])
        assert talent["duration"][:4] == (0.0, 10.0, 10.0, 10.0)
        assert talent["duration"][6] == 12.0
        assert talent["activation"] == "main_skill"

    def test_duplicate_talent_name_is_rejected(self):
        raw = self.raw_fixture()
        raw["talents_main"][1]["talent_name"] = raw["talents_main"][0]["talent_name"]
        with pytest.raises(InputError, match="duplicate talent_name"):
            build_character("Dup", raw, "inline")

    def raw_fixture(self):
        import yaml

        with open(CHARS, encoding="utf-8") as fd:
            return yaml.safe_load(fd)["Char A"]


class TestPartyModel:
    """R-01 exactly main+sub1+sub2, R-02 role sets, R-08 flat variable order."""

    def test_party_var_layout(self):
        chars = load_characters([CHARS])
        party = build_party({"main": "Char A", "sub1": "Char B", "sub2": "Char C"}, chars)
        assert len(party["vars"]) == 48  # 16 per character, main first (R-08)
        assert party["vars"][0] == ("main", "Core Echo")
        assert party["vars"][16] == ("sub1", "B Sub Core Atk")  # support slot uses talents_sub (R-02)
        assert party["vars"][47] == ("sub2", "C Team Signature")

    def test_slot_selects_the_talent_set(self):
        chars = load_characters([CHARS])
        party = build_party({"main": "Char A", "sub1": "Char B", "sub2": "Char C"}, chars)
        assert party["members"]["main"].talents[0]["name"] == "Core Echo"
        assert party["members"]["sub1"].talents[0]["name"] == "B Sub Core Atk"
        assert party["members"]["sub2"].talents[-1]["name"] == "C Team Signature"

    def test_duplicate_party_is_exit_2(self):
        chars = load_characters([CHARS])
        with pytest.raises(InputError) as exc:
            build_party({"main": "Char A", "sub1": "Char A", "sub2": "Char C"}, chars)
        assert exc.value.code == 2
        assert "distinct" in exc.value.message  # R-41

    def test_unknown_character_is_exit_2_and_named(self):
        chars = load_characters([CHARS])
        with pytest.raises(InputError) as exc:
            build_party({"main": "Char Z", "sub1": "Char B", "sub2": "Char C"}, chars)
        assert exc.value.code == 2
        assert "Char Z" in exc.value.message


class TestScenarioBlock:
    """R-36: typed scenario merged over kernel defaults."""

    def test_defaults_when_absent(self):
        assert normalize_scenario(None) == SCENARIO_DEFAULTS

    def test_config_block_merges(self):
        cfg = load_yaml(PARTY, "run configuration file")["scenario"]
        merged = normalize_scenario(cfg)
        assert merged["DEF"] == 350 and merged["RES"] == 570
        assert merged["PEN"] == 0.0 and merged["resilienceBreakDmg"] == 1.5
        assert merged["res_table"] == {"Lux": 250.0, "default": 750.0}

    def test_game_undefined_keys_are_not_exposed(self):
        with pytest.raises(InputError) as exc:
            normalize_scenario({"generalDmg": 1.5})
        assert exc.value.code == 2

    def test_unknown_scenario_key_is_exit_2(self):
        with pytest.raises(InputError) as exc:
            normalize_scenario({"BOSS": True})
        assert exc.value.code == 2

    def test_cli_scenario_override(self):
        merged = normalize_scenario({"DEF": 500, "RES": 750})
        scenario_key_override(merged, ["DEF=350", "RES=570"])
        assert merged["DEF"] == 350 and merged["RES"] == 570

    def test_res_table_keys_are_elements(self):
        with pytest.raises(InputError):
            validate_res_table({"Light": 250})
        assert validate_res_table({"Aqua": 250, "default": 750}) == {"Aqua": 250.0, "default": 750.0}


class TestR38Breakdown:
    """The per-talent breakdown and the summed map come from one resolution."""

    def test_levels_and_breakdown(self):
        from ssoptim.ssoptim.talent import resolve_talent_params

        chars = load_characters([CHARS])
        party = build_party({"main": "Char A", "sub1": "Char B", "sub2": "Char C"}, chars)
        ctx = {"members": party["members"], "scenario": {}, "aggregated": {}}
        x = [0] * 48
        x[0] = 1  # "Core Echo" core talent
        x[4] = 2  # "Sub Atk Up": first sub talent above the core block
        x[16] = 1  # sub1's first core talent of talents_sub
        view = resolve_talent_params(x, ctx)
        assert view["main"]["levels"]["Core Echo"] == 1
        assert view["main"]["levels"]["Sub Atk Up"] == 2
        assert close(0.072)(view["main"]["talent_params"]["Sub Atk Up"]["Atk_multiplier"])
        assert view["sub1"]["levels"]["B Sub Core Atk"] == 1
        assert "Sub Team Atk" not in view["main"]["talent_params"]  # role sets stay apart (R-02)

    def test_aggregated_sums_across_members(self):
        from ssoptim.ssoptim.talent import aggregate_params

        chars = load_characters([CHARS])
        party = build_party({"main": "Char A", "sub1": "Char B", "sub2": "Char C"}, chars)
        ctx = {"members": party["members"], "scenario": {}, "aggregated": {}}
        x = [0] * 48
        x[0] = 1  # Char A Core Echo: Atk_multiplier 0.15
        x[16] = 1  # Char B talents_sub Core Atk: Atk_multiplier 0.08
        total = aggregate_params(x, ctx)
        assert set(total) == {"Atk_multiplier"}
        assert close(0.23)(total["Atk_multiplier"])


class TestLoaderErrors:
    """Every loader failure is an InputError carrying exit code 2 (R-29)."""

    def test_invalid_character_file(self):
        with pytest.raises(InputError) as exc:
            load_characters([INVALID])
        assert exc.value.code == 2
        assert "4 core + 12 sub" in exc.value.message

    def test_bad_level_key(self):
        raw = {
            "stats": {"Atk": 1},
            "auto_skill": {"damage": {"elemLuxDmg": {"skillPercentAmend": 1.0}}},
            "talents_main": [{"talent_name": "C1", "core_talent": True, "Atk_multiplier": {1: 0.1, 7: 0.7}}]
            + [{"talent_name": "C{0}".format(i), "core_talent": True} for i in range(2, 5)]
            + [{"talent_name": "S{0}".format(i), "core_talent": False} for i in range(1, 13)],
            "talents_sub": [{"talent_name": "T{0}".format(i), "core_talent": True} for i in range(1, 5)]
            + [{"talent_name": "U{0}".format(i), "core_talent": False} for i in range(1, 13)],
        }
        with pytest.raises(InputError, match="out of range"):
            build_character("Bad", raw, "inline")

    def test_missing_party_slot(self):
        chars = load_characters([CHARS])
        with pytest.raises(InputError) as exc:
            build_party({"main": "Char A", "sub1": "Char B"}, chars)
        assert exc.value.code == 2

    def test_broken_yaml_is_exit_2(self):
        with pytest.raises(InputError, match="could not parse"):
            load_yaml(os.path.join(DATA_DIR, "broken.yml"), "run configuration file")
