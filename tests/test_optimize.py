#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (c) 2026 aoi mizma <aoi.mizma@path-works.net>
# SPDX-License-Identifier: MIT

"""M5 optimize.py: differential evolution vs. exhaustive reference.

Acceptance (DESIGN.md 5): on a reduced fixture the optimum the driver
reports matches a brute-force enumeration of the whole space, and every
generated constraint holds for the returned candidate (R-11). The reduction
keeps the model honest - the real 3-member party, real 48-variable layout,
generated bounds and rows - but pins two core talents per member (R-16),
zeroes the other two, and leaves exactly one sub-talent per member free up to
level 4, so exhaustive search is cheap and the budget reaches past the pins.
"""

import itertools
import math
import os

import pytest

from ssoptim.ssoptim.constraints import Infeasible, build_problem, verify
from ssoptim.ssoptim.data import load_characters, build_party, normalize_scenario
from ssoptim.ssoptim.optimize import NoFeasible, evaluate, greedy_fill, solve
from ssoptim.ssoptim.plugins import build_run_context, resolve_candidate
from ssoptim.ssoptim.objectives import REGISTRY

CHARS = os.path.join(os.path.dirname(__file__), "data", "characters.yml")
FREE = {"main": "Sub Atk Up", "sub1": "B Team Atk 1", "sub2": "C Team Abs 1"}
FREE_CAP = 4


def reduced_restriction(slot, talents):
    """Keyed restrictions: pin two cores, zero the rest, free one sub talent."""
    entries = []
    for position, talent in enumerate(talents):
        if talent["core"]:
            if position < 2:
                entries.append({"name": talent["name"], "min": 1})
            else:
                entries.append({"name": talent["name"], "max": 0})
        elif talent["name"] == FREE[slot]:
            entries.append({"name": talent["name"], "max": FREE_CAP})
        else:
            entries.append({"name": talent["name"], "max": 0})
    return {"talent_levels": entries}


def reduced(total_level=10):
    """(members, vars_layout, problem) for the reduced fixture run."""
    chars = load_characters([CHARS])
    party = build_party({"main": "Char A", "sub1": "Char B", "sub2": "Char C"}, chars)
    members, vars_layout = party["members"], party["vars"]
    restrictions = {
        slot: reduced_restriction(slot, members[slot].talents) for slot in ("main", "sub1", "sub2")
    }
    problem = build_problem(members, vars_layout, total_level, restrictions=restrictions)
    return members, vars_layout, problem


def run_context(members, vars_layout):
    return build_run_context(members, vars_layout, normalize_scenario({"DEF": 350, "RES": 570}), {}, 0)


def brute_force(problem, ctx, objective, total_level, total_level_mode="exact"):
    """Evaluate every feasible integer point of the reduced box (5, reference)."""
    free_dims = [i for i, (lo, hi) in enumerate(problem["bounds"]) if hi > lo]
    base = [lo for lo, _hi in problem["bounds"]]
    best_value, best_x, feasible = None, None, 0
    for combo in itertools.product(*[range(problem["bounds"][i][0], problem["bounds"][i][1] + 1) for i in free_dims]):
        x = list(base)
        for dim, value in zip(free_dims, combo):
            x[dim] = value
        if not verify(x, problem, total_level, total_level_mode):
            continue
        feasible += 1
        resolve_candidate(x, ctx)
        value = objective(x, ctx)
        if best_value is None or value > best_value:
            best_value, best_x = value, x
    return best_value, best_x, feasible


class TestBruteForceAgreement:
    """The driver's optimum equals exhaustive search (DESIGN.md 5)."""

    def test_optimum_matches_enumeration(self):
        members, vars_layout, problem = reduced(10)
        objective = REGISTRY["auto_attack"]
        ctx = run_context(members, vars_layout)
        expected, _expected_x, feasible = brute_force(problem, ctx, objective, 10)
        assert expected is not None and feasible > 1
        best_x, best_value = solve(objective, problem, ctx, 10, runs=2, seed=7, maxiter=3, popsize=4, polish=False)
        assert math.isclose(best_value, expected, rel_tol=1e-9)
        assert verify(best_x, problem, 10)

    def test_every_constraint_holds_for_the_answer(self):
        members, vars_layout, problem = reduced(10)
        objective = REGISTRY["auto_attack"]
        ctx = run_context(members, vars_layout)
        best_x, _value = solve(objective, problem, ctx, 10, runs=1, seed=3, maxiter=2, popsize=4, polish=False)
        for _slot, (start, _stop) in problem["ranges"].items():
            assert sum(best_x[start : start + 4]) == 2  # R-04 / R-17
        assert sum(best_x) == 10  # R-13 exact
        for index, (lo, hi) in enumerate(problem["bounds"]):
            assert lo <= best_x[index] <= hi  # R-15 / R-16
        assert sum(sum(best_x[start + 4 : stop]) for start, stop in problem["ranges"].values()) == 4

    def test_greedy_reference_reaches_the_optimum(self):
        members, vars_layout, problem = reduced(10)
        objective = REGISTRY["auto_attack"]
        ctx = run_context(members, vars_layout)
        expected, _x, _count = brute_force(problem, ctx, objective, 10)
        assert expected is not None
        one = evaluate(objective, ctx, 0)
        candidate = greedy_fill(problem, one, 10, "exact")
        assert candidate is not None and verify(candidate, problem, 10)
        resolve_candidate(candidate, ctx)
        assert math.isclose(objective(candidate, ctx), expected, rel_tol=1e-9)

    def test_at_most_leaves_levels_unused(self):
        members, vars_layout, problem = reduced(7)
        objective = REGISTRY["auto_attack"]
        ctx = run_context(members, vars_layout)
        best_x, value = solve(objective, problem, ctx, 7, total_level_mode="at_most", runs=1, seed=5, maxiter=2, popsize=4, polish=False)
        assert sum(best_x) <= 7  # R-13 at_most is an upper bound
        assert sum(best_x) >= 6  # the six pinned cores alone (R-04, R-16)
        expected, _x, _count = brute_force(problem, ctx, objective, 7, "at_most")
        assert expected is not None and math.isclose(value, expected, rel_tol=1e-9)


class TestInfeasibility:
    """A constraint set nothing can satisfy is exit 3 before solving (R-11)."""

    def test_budget_below_the_pins(self):
        with pytest.raises(Infeasible) as caught:
            reduced(3)  # six pinned cores alone need 6 levels
        assert caught.value.code == 3

    def test_budget_above_the_box(self):
        with pytest.raises(Infeasible) as caught:
            reduced(100)  # 6 pinned cores + 3 free x 4 = 18 at most
        assert caught.value.code == 3


class TestNoFeasible:
    """The solver landing nothing feasible is exit 5, never a relaxed run."""

    def test_solver_raises_after_every_restart(self, monkeypatch):
        members, vars_layout, problem = reduced(10)
        objective = REGISTRY["auto_attack"]
        ctx = run_context(members, vars_layout)
        monkeypatch.setattr("ssoptim.ssoptim.optimize.differential_evolution_run", lambda *a, **k: None)
        monkeypatch.setattr("ssoptim.ssoptim.optimize.greedy_fill", lambda *a, **k: None)
        with pytest.raises(NoFeasible) as caught:
            solve(objective, problem, ctx, 10, runs=3, seed=1)
        assert caught.value.code == 5

    def test_no_feasible_when_the_solver_ignores_integrality(self, monkeypatch):
        """A proposed point that fails verify() is rejected, not reported (R-11)."""
        members, vars_layout, problem = reduced(10)
        objective = REGISTRY["auto_attack"]
        ctx = run_context(members, vars_layout)

        monkeypatch.setattr(
            "ssoptim.ssoptim.optimize.differential_evolution_run", lambda *a, **k: [0] * problem["n"]
        )
        monkeypatch.setattr("ssoptim.ssoptim.optimize.greedy_fill", lambda *a, **k: None)
        with pytest.raises(NoFeasible) as caught:
            solve(objective, problem, ctx, 10, runs=2, seed=1)
        assert caught.value.code == 5
