#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (c) 2026 aoi mizma <aoi.mizma@path-works.net>
# SPDX-License-Identifier: MIT

"""M2 damage.py: the vendored kernel reproduces the scratch sanity table.

Acceptance criteria (DESIGN.md 9, M2): the vendored file reproduces the sanity
table the scratch reference `stella_sora_damage.py` prints (parameter names per
DamageCalculationParameters.md), and the scenario defaults data.py merges over
are the kernel's own neutral defaults (R-36).
"""

import math

import pytest

from ssoptim.ssoptim.damage import calculate_damage, def_amend, res_amend, skill_percent_to_amend
from ssoptim.ssoptim.damage import def_amend_table, res_amend_table, kernel_defaults, DEFAULT_RESILIENCE_BREAK_DMG
from ssoptim.ssoptim.data import SCENARIO_DEFAULTS

TOL = 1e-9


def close_to(expected):
    return lambda actual: math.isclose(actual, expected, rel_tol=TOL, abs_tol=1e-12)


class TestVendoredSanityTable:
    """Same numbers as the scratch reference's __main__ block."""

    def test_def_amend(self):
        for DEF, expected in def_amend_table():
            assert close_to(expected)(def_amend(DEF))

    def test_def_amend_uses_effective_def(self):
        """eff = DEF*(1-DEF_Ignore) - DEF_Penetrate; not exposed as scenario input."""
        assert close_to(def_amend(250))(def_amend(500, DEF_Penetrate=250))
        assert close_to(def_amend(250))(def_amend(500, DEF_Ignore=0.5))

    def test_res_amend(self):
        for RES, expected in res_amend_table():
            assert close_to(expected)(res_amend(RES))

    def test_res_amend_suppress_branch(self):
        """Effective_RES <= 0 takes the VUL branch (gist: 1.032)."""
        assert math.isclose(res_amend(-60, VUL=0.05), 1.032, abs_tol=5e-4)

    def test_res_tier_gap_clamp(self):
        """1-wide gaps between tiers clamp to the tier below (scratch comment)."""
        assert math.isclose(res_amend(250.5), res_amend(250), rel_tol=1e-12)
        assert math.isclose(res_amend(2500), res_amend(2000), rel_tol=1e-12)

    def test_scratch_example_damage(self):
        """calculate_damage(Atk=3000, 250% Atk, DEF=350, RES=570, critDmg=1.5)."""
        base = 3000 * 2.5
        crit_mult = 1.5 * 0.5 + 1.0 * 0.5
        expected = base * crit_mult * 0.54783073161 * 0.60227272727
        assert close_to(expected)(
            calculate_damage(
                Atk=3000,
                skillPercentAmend=skill_percent_to_amend(250),
                DEF=350,
                RES=570,
                critDmg=1.5,
                as_int=False,
            )
        )
        assert (
            calculate_damage(
                Atk=3000,
                skillPercentAmend=skill_percent_to_amend(250),
                DEF=350,
                RES=570,
                critDmg=1.5,
            )
            == max(1, int(expected))
        )


class TestKernelSemantics:
    """The formula behaviour the objectives of M3 depend on."""

    def test_dot_never_crits(self):
        """is_dot drops the crit expectation entirely (R-24, is_dot of R-32)."""
        dot_hit = calculate_damage(
            Atk=1000, skillPercentAmend=skill_percent_to_amend(100), crit_rate=0.5, critDmg=2.0, is_dot=True, as_int=False
        )
        crit_hit = calculate_damage(
            Atk=1000, skillPercentAmend=skill_percent_to_amend(100), crit_rate=0.5, critDmg=2.0, as_int=False
        )
        # neutral enemy defaults: er(750)=0.4, def(500)=0.5 -> taken 0.2
        assert math.isclose(dot_hit, 1000 * 1.0 * 0.2, rel_tol=TOL)
        assert math.isclose(crit_hit, 1000 * (2.0 * 0.5 + 1.0 * 0.5) * 0.2, rel_tol=TOL)
        assert crit_hit > dot_hit

    def test_break_status_multiplier(self):
        """enemyBreakStatus applies resilienceBreakDmg (R-36 scenario keys)."""
        plain = calculate_damage(Atk=1000, skillPercentAmend=skill_percent_to_amend(100))
        broken = calculate_damage(
            Atk=1000, skillPercentAmend=skill_percent_to_amend(100), enemyBreakStatus=True
        )
        assert broken == int(plain * DEFAULT_RESILIENCE_BREAK_DMG)

    def test_pen_lowers_effective_res(self):
        """PEN (scenario input, R-36) makes a hit deal more."""
        assert res_amend(RES=750, PEN=200) > res_amend(RES=750)
        assert calculate_damage(
            Atk=1000, skillPercentAmend=skill_percent_to_amend(100), RES=750, PEN=200
        ) > calculate_damage(Atk=1000, skillPercentAmend=skill_percent_to_amend(100), RES=750)


class TestApplyEverythingKernel:
    """R-33: the kernel applies every argument it is handed; it has no policy."""

    def test_slot_and_element_buffers_apply_when_passed(self):
        plain = calculate_damage(Atk=1000, skillPercentAmend=skill_percent_to_amend(100), as_int=False)
        buffered = calculate_damage(
            Atk=1000, skillPercentAmend=skill_percent_to_amend(100), slotDmg=1.2, elementDmg=1.1, as_int=False
        )
        assert math.isclose(buffered, plain * 1.2 * 1.1, rel_tol=TOL)

    def test_the_kernel_never_drops_a_key(self):
        """A mark key handed to a non-mark hit still applies (R-33)."""
        with_extra = calculate_damage(
            Atk=1000, skillPercentAmend=skill_percent_to_amend(100), slotCritDmg=0.5, as_int=False
        )
        plain = calculate_damage(Atk=1000, skillPercentAmend=skill_percent_to_amend(100), as_int=False)
        assert with_extra > plain

    def test_buffing_is_plugin_side(self):
        """R-34: the plugin folds Atk buffs in before the call; the kernel never buffs."""
        plain = calculate_damage(Atk=1000, skillPercentAmend=skill_percent_to_amend(100), as_int=False)
        buffed = calculate_damage(Atk=1500, skillPercentAmend=skill_percent_to_amend(100), as_int=False)
        assert math.isclose(buffed, plain * 1.5, rel_tol=TOL)


class TestUnitsAndScenarioDefaults:
    """R-24 unit conversion, and R-36's "merged over the kernel's defaults"."""

    def test_skill_percent_units(self):
        assert skill_percent_to_amend(250) == 2_500_000
        # 4.1 character files carry x100 percent units: 11.30 => 1130 % of Atk
        assert skill_percent_to_amend(11.30 * 100) == 11_300_000
        plain = calculate_damage(
            Atk=1000,
            skillPercentAmend=skill_percent_to_amend(11.30 * 100),
            DEF=0,
            RES=0,
            crit_rate=0.0,
            as_int=False,
        )
        assert math.isclose(plain, 1000 * 11.30, rel_tol=TOL)

    def test_scenario_defaults_match_the_kernel(self):
        assert SCENARIO_DEFAULTS == kernel_defaults()
