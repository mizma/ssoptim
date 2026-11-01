#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (c) 2026 aoi mizma <aoi.mizma@path-works.net>
# SPDX-License-Identifier: MIT

"""The optimizer: differential evolution + verify/repair fallback (R-08..R-12).

The objective is opaque and non-linear, so the driver is
``scipy.optimize.differential_evolution`` with ``integrality=True``, integer
bounds and integer-coefficient linear constraints (R-10, 11 item 1). Plugins
return bigger-is-better numbers (R-21, Q-1); SciPy minimizes, so the driver
negates *internally only* and reports the plugin's own value back unchanged.

SciPy's constrained-integrality mode is finicky (10), so every candidate the
solver proposes is rounded and re-checked with ``constraints.verify`` (R-11);
when nothing survived, a greedy fill (start at the user's minimums, satisfy the
core rule, then repeatedly add the single level that improves the objective
most until the budget is spent) takes over - the same routine doubles as the
deterministic reference the tests enumerate against (5, M5 acceptance).
Nothing feasible after ``runs`` restarts is an error (exit 5, 7), never a
silently relaxed run (R-11).
"""

import numpy as np
import scipy.optimize as optimize

from .constraints import CORE_TALENT_COUNT, CORE_REQUIRED, verify
from .plugins import resolve_candidate, objective_call
from .ssoptim import pout, Level

TOLERANCE = 1e-6


class NoFeasible(Exception):
    """The solver found no feasible point after all restarts: exit 5 (7)."""

    def __init__(self, message, code=5):
        Exception.__init__(self, message)
        self.message = message
        self.code = code


def limit_rows(problem):
    """Split the generated rows into SciPy eq/ineq limit matrices (5).

    Returns ``(A_eq, b_eq, A_inq, b_inq)``; rows whose bound is one-sided are
    turned into SciPy's ``A @ x >= b`` orientation by negating the row. The
    budget row (the last one) is reported separately and left out of the
    ``ineq`` set for ``at_most`` runs, where unused levels are allowed (R-13).
    """
    block = problem["constraints"][0]
    rows, lower, upper = block["A"], block["lb"], block["ub"]
    eq_rows, eq_b, inq_rows, inq_b = [], [], [], []
    for index, row in enumerate(rows):
        lb, ub = float(lower[index]), float(upper[index])
        if lb == ub:
            eq_rows.append([int(v) for v in row])
            eq_b.append(float(lb))
        elif lb == float("-inf"):
            inq_rows.append([-int(v) for v in row])
            inq_b.append(-float(ub))
        else:
            inq_rows.append([int(v) for v in row])
            inq_b.append(float(lb))
    return (
        np.asarray(eq_rows, dtype=int),
        np.asarray(eq_b, dtype=float),
        np.asarray(inq_rows, dtype=int),
        np.asarray(inq_b, dtype=float),
    )


def partial_ok(x, problem):
    """Bounds and every row except the budget one - the fill-time check."""
    for index, (lo, hi) in enumerate(problem["bounds"]):
        if x[index] < lo or x[index] > hi:
            return False
    block = problem["constraints"][0]
    counts = np.asarray(block["A"], dtype=int) @ np.asarray([int(v) for v in x], dtype=int)
    for row in range(len(block["lb"]) - 1):  # the budget row is last
        lb, ub = float(block["lb"][row]), float(block["ub"][row])
        if lb != float("-inf") and counts[row] < lb:
            return False
        if counts[row] > ub:
            return False
    return True


def evaluate(objective, ctx, verbose=0):
    """Bigger-is-better objective wrapped for a minimizing driver.

    Fills the per-candidate level views (R-37/R-38), then at ``-vv`` prints the
    aggregated parameter dictionary and the objective value of every evaluated
    candidate (R-28) through the tool's own ``pout`` definition (R-42).
    """

    def one(x):
        resolve_candidate(x, ctx)
        value = objective_call(objective, x, ctx)
        if verbose >= 2:
            pout("evaluated x = {0}".format([int(v) for v in x]), verbose, Level.DEBUG)
            pout("aggregated: {0}".format(ctx["aggregated"]), verbose, Level.DEBUG)
            pout("objective = {0}".format(value), verbose, Level.DEBUG)
        return -value

    return one


def differential_evolution_run(problem, one, seed, maxiter=300, popsize=24, polish=True):
    """One seeded restart of SciPy DE; returns an integer candidate or None."""
    bounds = [(int(lo), int(hi)) for lo, hi in problem["bounds"]]
    a_eq, b_eq, a_inq, b_inq = limit_rows(problem)
    constraints = []
    if a_eq.size:
        constraints.append({"type": "eq", "fun": lambda x, A=a_eq, b=b_eq: A @ x - b, "jac": a_eq})
    if a_inq.size:
        constraints.append({"type": "ineq", "fun": lambda x, A=a_inq, b=b_inq: A @ x - b, "jac": a_inq})
    try:
        result = optimize.differential_evolution(
            one,
            bounds,
            constraints=constraints,
            integrality=True,
            polish=polish,
            maxiter=maxiter,
            popsize=popsize,
            seed=seed,
            init="sobol",
            tol=1e-6,
        )
    except Exception:
        return None
    if result.x is None:
        return None
    return [int(round(v)) for v in result.x]


def greedy_fill(problem, one, total_level, total_level_mode="exact"):
    """Deterministic fill from the minimum bounds (5; reference for the tests).

    Core rows are satisfied first (promote the cheapest core talents), then
    levels are added one at a time at the position that improves the objective
    most, never breaking a row or a bound, until the budget is spent (R-13
    exact) or no positive gain remains (R-13 ``at_most``).
    """
    x = [int(lo) for lo, _hi in problem["bounds"]]
    for _slot, (start, stop) in problem["ranges"].items():
        core = list(range(start, start + CORE_TALENT_COUNT))
        chosen = [index for index in core if x[index] >= 1]
        free = [index for index in core if x[index] < 1]
        needed = CORE_REQUIRED - len(chosen)
        if needed < 0:
            return None
        for index in free[:needed]:
            x[index] = 1
    if not partial_ok(x, problem):
        return None
    capacity = [int(hi) for _lo, hi in problem["bounds"]]
    current = one(list(x))
    while True:
        total = sum(x)
        if total >= total_level and total_level_mode == "exact":
            break
        if total >= total_level:  # at_most: the budget is an upper bound (R-13)
            break
        gains = []
        for index in range(len(x)):
            if x[index] >= capacity[index]:
                continue
            trial = list(x)
            trial[index] += 1
            if not partial_ok(trial, problem):
                continue
            gains.append((one(trial), index))
        if not gains:
            break
        # one() is negated: the smallest value is the best gain.
        gains.sort(key=lambda pair: (pair[0], pair[1]))
        gain_value, index = gains[0]
        if total_level_mode != "exact" and gain_value >= current:
            # R-13 at_most: a non-monotone objective may stop improving early.
            break
        x[index] += 1
        current = gain_value
    return x if verify(x, problem, total_level, total_level_mode) else None


def solve(objective, problem, ctx, total_level, total_level_mode="exact", runs=3, seed=1,
          maxiter=300, popsize=24, polish=True, log=None):
    """Best feasible candidate for the run: (candidate, plugin value).

    Args:
        objective: the resolved plugin callable ``f(x, ctx)`` (R-21 bigger is
        better).
        problem: the matrices from constraints.build_problem.
        ctx: the persistent run context from plugins.build_run_context.
        total_level / total_level_mode: the budget (R-13).
        runs / seed / maxiter / popsize / polish: the solver knobs (4.2 solver
        block, 7 ``--maxiter/--popsize/--runs/--seed/--no-polish``).
        log: the tool's warning logger (R-42) for solver notices.

    Raises:
        NoFeasible: nothing satisfied every constraint after all restarts (exit 5).
    """
    one = evaluate(objective, ctx, ctx.get("verbose", 0))
    candidates = []
    for restart in range(max(1, int(runs))):
        candidate = differential_evolution_run(problem, one, seed + restart, maxiter, popsize, polish)
        if candidate is None:
            continue
        if verify(candidate, problem, total_level, total_level_mode):
            candidates.append(candidate)
        elif log:
            log("differential evolution returned an infeasible point; repairing by greedy fill", level=Level.WARNING)
            repaired = greedy_fill(problem, one, total_level, total_level_mode)
            if repaired is not None:
                candidates.append(repaired)

    if not candidates:
        fallback = greedy_fill(problem, one, total_level, total_level_mode)
        if fallback is not None:
            candidates.append(fallback)

    if not candidates:
        raise NoFeasible("no feasible candidate after {0} restarts (R-11, 7 exit 5)".format(max(1, int(runs))))

    best = max(candidates, key=one)  # one() is negated, so its max is the best
    resolve_candidate(best, ctx)
    return best, ctx_value(objective, best, ctx)


def ctx_value(objective, best, ctx):
    """The plugin's own value for the winning candidate (4.3, R-27)."""
    return objective_call(objective, best, ctx)
