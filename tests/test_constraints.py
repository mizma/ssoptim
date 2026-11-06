#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (c) 2026 aoi mizma <aoi.mizma@path-works.net>
# SPDX-License-Identifier: MIT

"""M4 constraints.py: generated bounds and constraint matrices.

Acceptance criteria (DESIGN.md 5): the generated matrices verified by a
direct check of R-04 (core == 2), R-13 (budget), R-14 (per-character totals)
and R-15 (per-talent bounds) on the fixtures; an infeasible input flagged
(exit-3 class); and a duplicate party still flagged with exit 2 (R-41).
"""

import itertools
import os

import pytest

from ssoptim.ssoptim.constraints import Infeasible, build_problem, verify, slot_ranges
from ssoptim.ssoptim.data import InputError, build_party, load_characters

CHARS = os.path.join(os.path.dirname(__file__), "data", "characters.yml")


def party():
    chars = load_characters([CHARS])
    return build_party({"main": "Char A", "sub1": "Char B", "sub2": "Char C"}, chars)


def cores_of(problem, slot):
    start, _stop = problem["ranges"][slot]
    return start, start + 4


def brute_cores(bounds, slot, problem):
    """Every core assignment the bounds allow, filtered by the core row."""
    start, stop = cores_of(problem, slot)
    ranges = [range(int(lo), int(hi) + 1) for lo, hi in bounds[start:stop]]
    ok = []
    for combo in itertools.product(*ranges):
        if sum(combo) != 2:
            continue
        ok.append(combo)
    return ok


class TestR15Bounds:
    """Bounds carry the per-talent limits, not constraint rows."""

    def test_default_bounds_follow_levels(self):
        members_party = party()
        problem = build_problem(members_party["members"], members_party["vars"], 40)
        assert len(problem["bounds"]) == 48
        assert problem["bounds"][0] == (0, 1)  # core: 0/1 (R-04)
        assert problem["bounds"][4] == (0, 6)  # sub: 0..6 (R-05)

    def test_keyed_talent_bounds(self):
        members_party = party()
        restrictions = {"main": {"talent_levels": [{"name": "Sub Signature", "max": 0}]}}
        problem = build_problem(members_party["members"], members_party["vars"], 40, restrictions=restrictions)
        assert problem["bounds"][15] == (0, 0)  # "Sub Signature" is main's 16th talent
        assert problem["bounds"][14] == (0, 6)

    def test_positional_talent_bounds(self):
        """Positional entries align to declaration order (4.2; DESIGN.md 3 R-15 note)."""
        members_party = party()
        restrictions = {"main": {"talent_levels": [{"min": 1, "max": 1}]}}
        problem = build_problem(members_party["members"], members_party["vars"], 40, restrictions=restrictions)
        assert problem["bounds"][0] == (1, 1)
        assert problem["bounds"][16] == (0, 1)  # sub1 keeps its own defaults

    def test_out_of_range_bound_is_exit_2(self):
        members_party = party()
        restrictions = {"main": {"talent_levels": [{"name": "Sub Signature", "max": 9}]}}
        with pytest.raises(InputError):
            build_problem(members_party["members"], members_party["vars"], 40, restrictions=restrictions)

    def test_min_above_max_is_exit_2(self):
        members_party = party()
        restrictions = {"sub1": {"talent_levels": [{"name": "B Sub Core Atk", "min": 1, "max": 0}]}}
        with pytest.raises(InputError):
            build_problem(members_party["members"], members_party["vars"], 40, restrictions=restrictions)

    def test_unknown_talent_name_is_exit_2(self):
        members_party = party()
        restrictions = {"main": {"talent_levels": [{"name": "No Such Talent", "min": 1}]}}
        with pytest.raises(InputError):
            build_problem(members_party["members"], members_party["vars"], 40, restrictions=restrictions)


class TestGeneratedConstraints:
    """Rows are generated from data, with integer coefficients (5)."""

    def test_core_rows(self):
        members_party = party()
        problem = build_problem(members_party["members"], members_party["vars"], 40)
        block = problem["constraints"][0]
        rows, cols = block["A"].shape
        assert cols == 48 and rows == 4  # 3 core rows + the budget row
        ranges = slot_ranges(members_party["vars"])
        for slot in ("main", "sub1", "sub2"):
            start, _stop = ranges[slot]
            row = int(start / 4) if slot == "main" else None
            coefficients = list(block["A"][["main", "sub1", "sub2"].index(slot)])
            assert coefficients[start : start + 4] == [1, 1, 1, 1]
            outside = coefficients[:start] + coefficients[start + 4 :]
            assert all(int(v) == 0 for v in outside)

    def test_core_row_sums_are_two(self):
        members_party = party()
        problem = build_problem(members_party["members"], members_party["vars"], 40)
        block = problem["constraints"][0]
        assert list(block["lb"][:3]) == [2, 2, 2]
        assert list(block["ub"][:3]) == [2, 2, 2]
        for index in range(3):
            assert int(block["A"][index].sum()) == 4

    def test_budget_row(self):
        members_party = party()
        exact = build_problem(members_party["members"], members_party["vars"], 65)
        at_most = build_problem(members_party["members"], members_party["vars"], 65, total_level_mode="at_most")
        assert int(exact["constraints"][0]["A"][-1].sum()) == 48
        assert exact["constraints"][0]["lb"][-1] == 65 == exact["constraints"][0]["ub"][-1]
        assert at_most["constraints"][0]["lb"][-1] == float("-inf")
        assert at_most["constraints"][0]["ub"][-1] == 65

    def test_char_rows(self):
        members_party = party()
        restrictions = {"main": {"min": 20}, "sub1": {"min": 5, "max": 12}}
        problem = build_problem(members_party["members"], members_party["vars"], 40, restrictions=restrictions)
        block = problem["constraints"][0]
        rows = block["A"]
        # rows 3 and 4 are the two restricted characters: coefficients 1 on
        # that member's slice only
        assert int(rows[3].sum()) == 16 and int(rows[3][:16].sum()) == 16
        assert int(rows[4].sum()) == 16 and int(rows[4][16:32].sum()) == 16
        assert block["lb"][3] == 20 and block["lb"][4] == 5
        assert block["ub"][4] == 12

    def test_core_two_is_enforced_by_the_row(self):
        """Brute force over one member's core box: only the 2-of-4 survive."""
        members_party = party()
        restrictions = {"main": {"talent_levels": [{"name": "Core Echo", "min": 1}, {"name": "Core Mark", "min": 1}]}}
        problem = build_problem(members_party["members"], members_party["vars"], 40, restrictions=restrictions)
        start, stop = slot_ranges(members_party["vars"])["main"][:2]
        allowed = brute_cores(problem["bounds"], "main", problem)
        assert len(allowed) == 1  # pinning two cores forces the other two off (R-16)
        assert allowed[0] == (1, 1, 0, 0)


class TestVerify:
    """verify() re-checks bounds and every generated row (R-11, 5)."""

    def x_ok(self):
        x = [0] * 48
        x[0] = x[1] = 1
        x[16] = x[17] = 1
        x[32] = x[33] = 1
        return x

    def test_valid_candidate_passes(self):
        members_party = party()
        problem = build_problem(members_party["members"], members_party["vars"], 6)
        x = self.x_ok()
        assert verify(x, problem, 6)

    def test_budget_mismatch_fails(self):
        members_party = party()
        problem = build_problem(members_party["members"], members_party["vars"], 7)
        assert not verify(self.x_ok(), problem, 7)

    def test_core_row_violation_fails(self):
        members_party = party()
        problem = build_problem(members_party["members"], members_party["vars"], 6)
        x = self.x_ok()
        x[2] = 1  # three core talents for main (R-04)
        assert not verify(x, problem, 6)

    def test_bound_violation_fails(self):
        members_party = party()
        restrictions = {"main": {"talent_levels": [{"name": "Sub Signature", "max": 0}]}}
        problem = build_problem(members_party["members"], members_party["vars"], 7, restrictions=restrictions)
        x = self.x_ok()
        x[15] = 1
        assert not verify(x, problem, 7)

    def test_at_most_allides_unused_levels(self):
        members_party = party()
        problem = build_problem(members_party["members"], members_party["vars"], 12, total_level_mode="at_most")
        assert verify(self.x_ok(), problem, 12, "at_most")


class TestInfeasibility:
    """Exit 3: a constraint set nothing can satisfy, never relaxed (R-11)."""

    def test_budget_below_minimum(self):
        members_party = party()
        restrictions = {"main": {"min": 30}, "sub1": {"min": 20}, "sub2": {"min": 20}}
        with pytest.raises(Infeasible) as exc:
            build_problem(members_party["members"], members_party["vars"], 10, restrictions=restrictions)
        assert exc.value.code == 3

    def test_exact_budget_above_maximum(self):
        members_party = party()
        restrictions = {
            slot: {"talent_levels": [{"min": 0, "max": 0} for _ in range(16)]}
            for slot in ("main", "sub1", "sub2")
        }
        with pytest.raises(Infeasible):
            build_problem(members_party["members"], members_party["vars"], 65, restrictions=restrictions)

    def test_three_pinned_core_talents(self):
        members_party = party()
        restrictions = {
            "main": {
                "talent_levels": [
                    {"name": "Core Echo", "min": 1},
                    {"name": "Core Mark", "min": 1},
                    {"name": "Core Ward", "min": 1},
                ]
            }
        }
        with pytest.raises(Infeasible) as exc:
            build_problem(members_party["members"], members_party["vars"], 40, restrictions=restrictions)
        assert "core talents" in exc.value.message

    def test_character_floor_above_ceiling(self):
        members_party = party()
        restrictions = {"main": {"min": 60, "max": 10}}
        with pytest.raises(Infeasible):
            build_problem(members_party["members"], members_party["vars"], 40, restrictions=restrictions)

    def test_duplicate_party_is_still_exit_2(self):
        """R-41 stays a loader error (exit 2), before any constraint work."""
        chars = load_characters([CHARS])
        with pytest.raises(InputError) as exc:
            build_party({"main": "Char A", "sub1": "Char A", "sub2": "Char C"}, chars)
        assert exc.value.code == 2
