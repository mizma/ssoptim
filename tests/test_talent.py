#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (c) 2026 aoi mizma <aoi.mizma@path-works.net>
# SPDX-License-Identifier: MIT

"""M1 talent.py: sparse level maps -> pinned interpolation tables (R-19, R-43).

Acceptance criteria (DESIGN.md 4.1; R-19, R-43): interpolation of the 1<->6 anchor keys
matches the even-step rule, level 0 contributes nothing, the reserved
duration/activation pair is validated, and the per-talent breakdown stays
available for R-38.
"""

import math

import pytest

from ssoptim.ssoptim.talent import CORE_MAX_LEVEL, MAX_SUB_LEVEL, SKILL_KEYS
from ssoptim.ssoptim.talent import level_map_table, duration_table, activation_key, talent_entry
from ssoptim.ssoptim.talent import resolve_talent_value, split_reserved


def close_to(expected):
    def check(actual):
        return math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-12)

    return check


class TestR19Interpolation:
    """Sparse anchors expand to an even step, with the origin as an anchor."""

    def test_anchor_pair_1_to_6(self):
        table = level_map_table({1: 0.045, 6: 0.18})
        assert table[0] == 0.0, "level 0 contributes nothing (R-05, R-19)"
        step = (0.18 - 0.045) / 5
        for level in range(1, 7):
            assert close_to(0.045 + step * (level - 1))(table[level])
        assert table[1] == 0.045 and table[6] == 0.18

    def test_level_zero_never_owned(self):
        assert level_map_table({1: 0.045, 6: 0.18})[0] == 0.0
        assert level_map_table({0: 0.0, 6: 0.3})[0] == 0.0

    def test_single_anchor_ramps_from_origin(self):
        table = level_map_table({6: 0.12})
        assert table[6] == 0.12
        assert close_to(0.02)(table[1])
        assert close_to(0.06)(table[3])

    def test_flat_beyond_last_anchor(self):
        """No extrapolation past authored evidence (DESIGN 4.1; R-19)."""
        table = level_map_table({2: 0.5})
        assert table[1] == 0.25
        assert all(table[level] == 0.5 for level in range(2, 7))

    def test_core_bounds_are_0_1(self):
        table = level_map_table({1: 0.15}, CORE_MAX_LEVEL)
        assert len(table) == CORE_MAX_LEVEL + 1
        assert table == (0.0, 0.15)

    def test_out_of_range_level_key_is_rejected(self):
        with pytest.raises(ValueError, match="out of range"):
            level_map_table({1: 0.1, 7: 0.7})

    def test_non_numeric_level_value_is_rejected(self):
        with pytest.raises(ValueError, match="must be numeric"):
            level_map_table({1: "high"})

    def test_unknown_key_in_level_map_is_rejected(self):
        with pytest.raises(ValueError, match="unknown key"):
            level_map_table({1: 0.1, "sideways": 0.2})


class TestR43ReservedPair:
    """duration/activation are convention metadata, never parameters."""

    def test_reserved_split(self):
        anchors, reserved = split_reserved({1: 0.045, 6: 0.18, "duration": {1: 10, 4: 12}, "activation": "main_skill"})
        assert anchors == {1: 0.045, 6: 0.18}
        assert set(reserved) == {"duration", "activation"}

    def test_duration_sparse_map(self):
        """10 s for levels 1-3, 12 s for 4-6 (DESIGN 4.1 worked example)."""
        table = duration_table({1: 10, 4: 12})
        assert table[0] == 0.0
        assert table[1:4] == (10.0, 10.0, 10.0)
        assert table[4:7] == (12.0, 12.0, 12.0)

    def test_duration_bare_number(self):
        table = duration_table(6)
        assert table[1:] == (6.0,) * MAX_SUB_LEVEL

    def test_duration_must_be_positive(self):
        with pytest.raises(ValueError, match="duration must be > 0"):
            duration_table(0)
        with pytest.raises(ValueError, match="duration must be > 0"):
            duration_table({1: -3})

    def test_activation_is_a_skill_key(self):
        assert activation_key("sub_skill") == "sub_skill"
        with pytest.raises(ValueError, match="activation must be one of"):
            activation_key("burst_skill")

    def test_reserved_keys_stay_out_of_params(self):
        talent = talent_entry(
            {
                "talent_name": "Talent E",
                "core_talent": False,
                "Atk_multiplier": {1: 0.045, 6: 0.18, "duration": {1: 10, 4: 12}, "activation": "main_skill"},
                "slotSkillDmg": {6: 0.10},
            },
            index=4,
            core=False,
        )
        assert set(talent["params"]) == {"Atk_multiplier", "slotSkillDmg"}
        assert talent["duration"][4] == 12.0
        assert talent["activation"] == "main_skill"
        assert talent["core"] is False and talent["max_level"] == MAX_SUB_LEVEL

    def test_core_talent_kind_is_validated(self):
        """core talents are the first four entries (R-17)."""
        with pytest.raises(ValueError, match="core_talent mismatch"):
            talent_entry({"talent_name": "Sneaky", "core_talent": True}, index=6, core=False)
        assert activation_key(None) is None
        assert SKILL_KEYS == ("auto_skill", "main_skill", "sub_skill", "ult_skill")


class TestResolveHelpers:
    """resolve_talent_value reads a table or a raw map (R-19)."""

    def test_table_form(self):
        table = level_map_table({1: 0.045, 6: 0.18})
        assert resolve_talent_value(table, 3) == table[3]
        assert resolve_talent_value(table, 0) == 0.0

    def test_raw_map_form(self):
        assert close_to(0.072)(resolve_talent_value({1: 0.045, 6: 0.18}, 2))
