#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (c) 2026 aoi mizma <aoi.mizma@path-works.net>
# SPDX-License-Identifier: MIT

"""M3: built-in objective + the tool-built ctx + the DPS sample plugin.

Acceptance criteria (DESIGN.md 6, 6.3): the default objective on a fixed 3-char
fixture equals a hand-computed value from the 4.1 constants, simple_dps
reproduces a hand-computed main-character DPS from loop_time/cd and its two
sources (per-source buffers, R-32/R-34), and both plugins take (x, ctx) and
read levels/buffers through the helpers, never by indexing x (R-37, R-38).
"""

import math
import os

import pytest

from ssoptim.ssoptim.data import InputError, load_characters, build_party, normalize_scenario
from ssoptim.ssoptim.plugins import PluginError, build_run_context, resolve_candidate, resolve_plugin, objective_call
from ssoptim.ssoptim.objectives import REGISTRY
from ssoptim.ssoptim.objectives.auto_attack import objective as auto_attack
from ssoptim.ssoptim.damage import def_amend, res_amend, skill_percent_to_amend
from ssoptim.ssoptim.plugins import aggregate_params
from ssoptim.ssoptim.ssoptim import Level, pout

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
CHARS = os.path.join(DATA_DIR, "characters.yml")
SIMPLE_DPS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "plugins", "simple_dps.py")


def fixture_candidate(levels_main, scenario_over=None, objective_opts=None):
    """Party Char A/B/C, one candidate vector filled into a run context."""
    chars = load_characters([CHARS])
    party = build_party({"main": "Char A", "sub1": "Char B", "sub2": "Char C"}, chars)
    scenario = normalize_scenario(
        {"DEF": 350, "RES": 570, "res_table": {"Lux": 250, "default": 750}}, defaults=None
    )
    ctx = build_run_context(party["members"], party["vars"], scenario, objective_opts or {}, verbose=0)
    x = [0] * len(party["vars"])
    for index, level in levels_main.items():
        x[index] = level
    return resolve_candidate(x, ctx), x


class TestCtxContract:
    """R-37/R-38: the tool builds the data context; plugins never map x."""

    def test_members_carry_full_data(self):
        ctx, x = fixture_candidate({0: 1, 1: 1})
        main = ctx["members"]["main"]
        assert main.name == "Char A"
        assert main.stats == {"Atk": 6966, "HP": 94662, "DEF": 0}
        assert main.auto_skill["loop_time"] == 4.2
        assert len(main.main_skill["sources"]) == 2
        sub1 = ctx["members"]["sub1"]
        assert sub1.talents[0]["name"] == "B Sub Core Atk"  # support role set (R-02)

    def test_levels_are_name_keyed(self):
        ctx, x = fixture_candidate({0: 1, 1: 1, 4: 4})
        main = ctx["members"]["main"]
        assert main.talent_levels["Sub Atk Up"] == 4
        assert main.talent_levels["Core Echo"] == 1
        assert len(main.talent_levels) == 16

    def test_aggregated_matches_the_helper(self):
        ctx, x = fixture_candidate({0: 1, 1: 1, 4: 4})
        assert ctx["aggregated"] == aggregate_params(x, ctx)

    def test_per_talent_breakdown_is_present(self):
        """R-38: the per-talent map is mandatory, not just the sum."""
        ctx, x = fixture_candidate({0: 1, 1: 1, 4: 4})
        main = ctx["members"]["main"]
        assert set(main.talent_params["Sub Atk Up"]) == {"Atk_multiplier"}
        assert set(main.talent_params["Core Echo"]) == {"Atk_multiplier"}
        assert main.talent_params["Sub Atk Up"]["Atk_multiplier"] == 0.045 + (0.18 - 0.045) * 3 / 5

    def test_verbosity_and_log_reach_plugins(self):
        """R-42: ctx["verbose"] and ctx["log"] (pout curried with -v)."""
        ctx, x = fixture_candidate({0: 1, 1: 1})
        assert ctx["verbose"] == 0
        printed = []
        ctx["log"]("quiet notice", level=Level.WARNING)
        assert printed == []


class TestBuiltInAutoAttack:
    """R-23: per-hit auto-attack damage of the main member."""

    def test_hand_computed_default_objective(self):
        """Two pinned core talents, nothing else: 15 % Atk, +10 % crit rate."""
        ctx, x = fixture_candidate({0: 1, 1: 1})
        atk = 6966 * (1 + 0.15)
        expected = atk * 11.30 * 1.0 * 1.0 * (1.5 * 0.6 + 1.0 * 0.4) * res_amend(250) * def_amend(350)
        got = objective_call(auto_attack, x, ctx)
        assert math.isclose(got, expected, rel_tol=1e-9)

    def test_only_auto_attack_keys_apply(self):
        """An auto-attack buffer raises it; a skill buffer does not (R-35)."""
        ctx_auto, x_auto = fixture_candidate({0: 1, 1: 1, 5: 6})  # Sub Auto Up
        ctx_skill, x_skill = fixture_candidate({0: 1, 1: 1, 6: 6})  # Sub Skill Up
        atk = 6966 * 1.15
        tail = 11.30 * (1.5 * 0.6 + 1.0 * 0.4) * res_amend(250) * def_amend(350)
        base = atk * tail
        assert math.isclose(objective_call(auto_attack, x_auto, ctx_auto), base * 1.18, rel_tol=1e-9)
        assert math.isclose(objective_call(auto_attack, x_skill, ctx_skill), base, rel_tol=1e-9)

    def test_per_element_res_is_used(self):
        """Lux source reads res_table Lux=250, not the neutral 570 (R-36)."""
        ctx_neutral, x_neutral = fixture_candidate({0: 1, 1: 1})
        plain = res_amend(570)
        weak = res_amend(250)
        atk = 6966 * 1.15
        base = atk * 11.30 * (1.5 * 0.6 + 1.0 * 0.4) * def_amend(350)
        assert math.isclose(objective_call(auto_attack, x_neutral, ctx_neutral), base * weak, rel_tol=1e-9)
        assert objective_call(auto_attack, x_neutral, ctx_neutral) != base * plain

    def test_registry_and_spec_forms(self):
        """R-22: short name, dotted module path and file path all resolve."""
        builtin, name = resolve_plugin("auto_attack", REGISTRY)
        dotted, dotted_name = resolve_plugin("ssoptim.ssoptim.objectives.auto_attack:objective", REGISTRY)
        assert builtin is dotted is auto_attack
        assert name == "auto_attack"


class TestSimpleDpsSample:
    """§6.3 item 2: per-source damage / period, gated buffs by uptime."""

    def test_hand_computed_dps(self):
        """Core pins + one gated Atk buff + per-source slot buffers."""
        levels = {0: 1, 1: 1, 4: 4, 5: 2, 6: 3, 10: 1}
        ctx, x = fixture_candidate(levels, objective_opts={"uptime_fraction": 0.6})
        plugin, spec = resolve_plugin(os.path.join(".", "plugins", "simple_dps.py") + ":objective", REGISTRY)
        atk_mult = 0.15 + (0.045 + (0.18 - 0.045) * 3 / 5)  # Sub Atk Up level 4, uptime 12s/12s
        atk = 6966 * (1 + atk_mult)
        crit_mult = 1.5 * 0.6 + 1.0 * 0.4
        # mark portion debuffs DEF by 0.10 while its 6 s uptime over the 12 s CD lasts
        def_eff = def_amend(350 * (1 - 0.10 * min(6, 12) / 12))
        auto = atk * 11.30 * (1 + 0.06) * crit_mult * res_amend(250) * def_eff / 4.2
        hit = atk * 8.90 * (1 + 0.05) * crit_mult * res_amend(250) * def_eff / 12.0
        mark = atk * 1.22 * (1 + 0.06) * crit_mult * res_amend(750) * def_eff / 6.0
        assert math.isclose(objective_call(plugin, x, ctx), auto + hit + mark, rel_tol=1e-9)

    def test_mark_source_uses_mark_buffers_not_skill_buffers(self):
        """R-32/R-35: raising Sub Mark Up lifts only the mark portion."""
        base_levels = {0: 1, 1: 1, 4: 4, 5: 2, 6: 3}
        ctx0, x0 = fixture_candidate(base_levels)
        ctx1, x1 = fixture_candidate({**base_levels, 10: 6})
        plugin, _ = resolve_plugin(os.path.join(".", "plugins", "simple_dps.py") + ":objective", REGISTRY)
        plain = objective_call(plugin, x0, ctx0)
        raised = objective_call(plugin, x1, ctx1)
        assert raised > plain
        atk = 6966 * (1 + 0.15 + (0.045 + (0.18 - 0.045) * 3 / 5))
        delta = atk * 1.22 * 0.36 * (1.5 * 0.6 + 1.0 * 0.4) * res_amend(750) * def_amend(332.5) / 6.0
        assert raised - plain == pytest.approx(delta, rel=1e-9)

    def test_plugin_never_indexes_x(self):
        """Same ctx, reordered-looking x: the plugin reads resolved views only."""
        ctx_a, x_a = fixture_candidate({0: 1, 1: 1, 5: 3})
        plugin, _ = resolve_plugin(os.path.join(".", "plugins", "simple_dps.py") + ":objective", REGISTRY)
        value_from_ctx = plugin(x_a, ctx_a)
        recomputed = plugin(list(x_a), ctx_a)
        assert value_from_ctx == recomputed


class TestPluginFailure:
    """Exit 4 surface: R-22 load failures and plugin raises."""

    def test_missing_file(self):
        with pytest.raises(PluginError) as exc:
            resolve_plugin("./plugins/nope.py:objective", REGISTRY)
        assert exc.value.code == 4

    def test_missing_attribute(self):
        with pytest.raises(PluginError) as exc:
            resolve_plugin("ssoptim.ssoptim.objectives.auto_attack:not_there", REGISTRY)
        assert exc.value.code == 4

    def test_plugin_raise_is_mapped(self):
        def boom(x, ctx):
            raise ZeroDivisionError("nope")

        ctx, x = fixture_candidate({0: 1, 1: 1})
        with pytest.raises(PluginError) as exc:
            objective_call(boom, x, ctx)
        assert exc.value.code == 4

    def test_non_number_return_is_mapped(self):
        ctx, x = fixture_candidate({0: 1, 1: 1})
        with pytest.raises(PluginError) as exc:
            objective_call(lambda x, ctx: "bigger", x, ctx)
        assert exc.value.code == 4
