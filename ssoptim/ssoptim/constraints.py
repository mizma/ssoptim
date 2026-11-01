#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (c) 2026 aoi mizma <aoi.mizma@path-works.net>
# SPDX-License-Identifier: MIT

"""Variable bounds and generated constraints (R-04, R-13..R-16).

Everything the optimizer needs is *generated* from the loaded data plus the
run config, never hand-written: integer bounds per talent (core 0/1, sub 0/6,
tightened by the user's per-talent bounds of R-15/R-16) and integer-coefficient
linear constraints (core sum == 2 per member from data, R-04/R-17; per-character
totals, R-14; the budget row, R-13). Per-talent bounds stay variable bounds
rather than constraint rows (11, item 2) because differential evolution needs a
tight box for integrality to behave.

A constraint set no candidate can satisfy is reported as Infeasible (exit 3,
7) rather than silently relaxed (R-11); the feasibility arithmetic needs no
SciPy, so the matrices stay testable as pure functions.
"""

import numpy as np

from .data import InputError, SLOTS
from .talent import CORE_TALENT_COUNT, CORE_MAX_LEVEL, MAX_SUB_LEVEL

CORE_REQUIRED = 2


class Infeasible(Exception):
    """No candidate satisfies the constraint set: exit 3 (7, R-11)."""

    def __init__(self, message, code=3):
        Exception.__init__(self, message)
        self.message = message
        self.code = code


def restriction_block(restrictions, slot):
    """The 4.2 `restrictions.<slot>` map, validated (exit 2 on a bad shape)."""
    if not restrictions:
        return {}
    block = restrictions.get(slot)
    if block is None:
        return {}
    if not isinstance(block, dict):
        raise InputError("restrictions.{0} must be a map (4.2)".format(slot))
    for key in block:
        if key not in ("min", "max", "talent_levels"):
            raise InputError(
                "unknown restrictions key {0!r} for {1}; allowed: min, max, talent_levels (4.2)".format(key, slot)
            )
    entries = block.get("talent_levels") or []
    if not isinstance(entries, list):
        raise InputError("restrictions.{0}.talent_levels must be a list (4.2)".format(slot))
    for position, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise InputError(
                "restrictions.{0}.talent_levels entry #{1} must be a map (4.2)".format(slot, position)
            )
    return block


def validate_restriction_names(members, restrictions):
    """Every named restriction entry must address a talent of that slot (4.2)."""
    if not restrictions:
        return
    for slot in SLOTS:
        if slot not in members:
            continue
        if slot not in restrictions:
            continue
        block = restriction_block(restrictions, slot)
        names = {talent["name"] for talent in members[slot].talents}
        for entry in block.get("talent_levels") or []:
            entry_name = entry.get("name")
            if entry_name is None:
                continue
            if entry_name not in names:
                raise InputError(
                    "restrictions.{0} names talent {1!r}, which {2} does not have (4.2)".format(
                        slot, entry_name, members[slot].name
                    )
                )


def talent_bounds_for(members, slot, name, block):
    """Bounds of one talent variable, tightened by keyed/positional entries.

    R-15 keyed form: `- { name: "Talent A", min: 1 }`; the positional form
    (no `name:`) aligns to the character's declaration order (4 and 4.2), so a
    player can transcribe talent order straight from the game.
    """
    entries = block.get("talent_levels") or []
    named = [entry for entry in entries if entry.get("name") is not None]
    positional = [entry for entry in entries if entry.get("name") is None]
    talent = None
    for candidate in members[slot].talents:
        if candidate["name"] == name:
            talent = candidate
            break
    if talent is None:
        raise InputError("talent {0!r} of member {1} is unknown (4.2)".format(name, members[slot].name))
    position = [t["name"] for t in members[slot].talents].index(name)

    entry = None
    for candidate in named:
        if candidate.get("name") == name:
            entry = candidate
            break
    if entry is None and position < len(positional):
        entry = positional[position]

    lo, hi = 0, CORE_MAX_LEVEL if talent["core"] else MAX_SUB_LEVEL
    cap = hi
    if entry is not None:
        for key, is_min in (("min", True), ("max", False)):
            if key in entry:
                value = entry[key]
                if isinstance(value, bool) or not isinstance(value, int):
                    raise InputError(
                        "restrictions.{0} bound {1!r} must be an integer level (R-05, 4.2)".format(slot, key)
                    )
                if value < 0 or value > cap:
                    raise InputError(
                        "restrictions bound for {0!r} of {1} is outside the level range 0..{2} "
                        "(core 0/1, sub 0/6: R-04, R-05)".format(name, members[slot].name, cap)
                    )
                if is_min:
                    lo = max(lo, value)
                else:
                    hi = min(hi, value)
    if lo > hi:
        raise InputError(
            "restrictions for talent {0!r} of {1}: min above max (4.2)".format(name, members[slot].name)
        )
    return (lo, hi)


def per_talent_bounds(members, vars_layout, restrictions=None):
    """Integer bounds aligned with the flat vector (R-15/R-16 as bounds)."""
    bounds = []
    for slot, name in vars_layout:
        bounds.append(talent_bounds_for(members, slot, name, restriction_block(restrictions, slot)))
    return bounds


def slot_ranges(vars_layout):
    """{slot: (start, stop)} slice of the flat vector per member (R-08)."""
    ranges = {}
    for index, (slot, _name) in enumerate(vars_layout):
        start, stop = ranges.get(slot, (index, index + 1))
        ranges[slot] = (start, max(stop, index + 1))
    return {slot: ranges[slot] for slot in SLOTS if slot in ranges}


def build_problem(members, vars_layout, total_level, total_level_mode="exact", restrictions=None):
    """Generate bounds and constraint matrices for one run (5).

    Returns:
        dict: ``{"bounds": [(lo, hi)], "constraints": [{"A": int array,
        "lb": [...], "ub": [...]}], "ranges": {slot: (start, stop)}, "n": int}``
        - the shape differential evolution and the verifier both consume.

    Raises:
        InputError: a bad restriction shape (exit 2); Infeasible: a constraint
        set nothing can satisfy (exit 3, never relaxed, R-11).
    """
    n = len(vars_layout)
    validate_restriction_names(members, restrictions)
    bounds = per_talent_bounds(members, vars_layout, restrictions)
    ranges = slot_ranges(vars_layout)
    rows, lower, upper = [], [], []

    # R-04 / R-17: exactly two core talents per member, from data.
    for slot, (start, _stop) in ranges.items():
        row = [0] * n
        for index in range(start, start + CORE_TALENT_COUNT):
            row[index] = 1
        rows.append(row)
        lower.append(CORE_REQUIRED)
        upper.append(CORE_REQUIRED)

    # R-14: per-character totals, only when the config asks for them.
    for slot, (start, stop) in ranges.items():
        block = restriction_block(restrictions, slot)
        if "min" in block or "max" in block:
            row = [0] * n
            for index in range(start, stop):
                row[index] = 1
            rows.append(row)
            lower.append(int(block.get("min", 0)))
            upper.append(int(block.get("max", MAX_SUB_LEVEL * 16)))

    # R-13: the budget row; exact sum by default, <= for at_most (11 item 3).
    if total_level is None:
        raise InputError("total_level (the budget) is mandatory (R-13, -t)")
    if total_level_mode not in ("exact", "at_most"):
        raise InputError("total_level_mode must be exact or at_most (4.2), got {0!r}".format(total_level_mode))
    rows.append([1] * n)
    lower.append(int(total_level) if total_level_mode == "exact" else float("-inf"))
    upper.append(int(total_level))

    problem = {
        "bounds": bounds,
        "constraints": [{"A": np.asarray(rows, dtype=int), "lb": lower, "ub": upper}],
        "ranges": ranges,
        "n": n,
    }
    check_feasible(problem, total_level, total_level_mode, restrictions)
    return problem


def check_feasible(problem, total_level, total_level_mode, restrictions=None):
    """Arithmetic feasibility pre-check; raises Infeasible (exit 3, R-11)."""
    bounds = problem["bounds"]
    for index, (lo, hi) in enumerate(bounds):
        if lo < 0 or hi < lo:
            raise Infeasible("variable {0} bounds {1}..{2} cannot be satisfied".format(index, lo, hi))

    total_min = 0
    total_max = 0
    for slot, (start, stop) in problem["ranges"].items():
        core = bounds[start : start + CORE_TALENT_COUNT]
        sub = bounds[start + CORE_TALENT_COUNT : stop]
        core_min = sum(lo for lo, _hi in core)
        core_max = sum(hi for _lo, hi in core)
        if core_min > CORE_REQUIRED:
            raise Infeasible(
                "{0}: pinned core talents already sum above the required {1} (R-04)".format(slot, CORE_REQUIRED)
            )
        if core_max < CORE_REQUIRED:
            raise Infeasible(
                "{0}: fewer than {1} core talents can reach 1 (R-04, 4.2 restrictions)".format(slot, CORE_REQUIRED)
            )
        block = restriction_block(restrictions, slot)
        char_min = CORE_REQUIRED + sum(lo for lo, _hi in sub)
        char_max = CORE_REQUIRED + sum(hi for _lo, hi in sub)
        if "min" in block:
            char_min = max(char_min, int(block["min"]))
        if "max" in block:
            char_max = min(char_max, int(block["max"]))
        if char_min > char_max:
            raise Infeasible(
                "{0}: character total floor {1} above ceiling {2} (R-14)".format(slot, char_min, char_max)
            )
        total_min += char_min
        total_max += char_max

    if total_level < total_min:
        raise Infeasible(
            "budget {0} below the minimum achievable {1} (R-13, 4.2 restrictions min)".format(total_level, total_min)
        )
    if total_level_mode == "exact" and total_level > total_max:
        raise Infeasible(
            "budget {0} above the maximum achievable {1} (R-13 exact)".format(total_level, total_max)
        )
    return True


def verify(x, problem, total_level=None, total_level_mode="exact"):
    """Direct constraint check of an integer candidate (R-11, 5 verify pass).

    Bounds, the core rows, the per-character rows and the budget row are all
    re-checked from the generated matrices, so a solver that ignores
    integrality cannot slip a bad candidate through.
    """
    for index, (lo, hi) in enumerate(problem["bounds"]):
        if int(x[index]) < lo or int(x[index]) > hi:
            return False
    for block in problem["constraints"]:
        values = np.asarray(block["A"], dtype=int) @ np.asarray([int(v) for v in x], dtype=int)
        for row, value in enumerate(values):
            lb, ub = block["lb"][row], block["ub"][row]
            if lb is not None and lb != float("-inf") and value < lb:
                return False
            if ub is not None and value > ub:
                return False
    return True
