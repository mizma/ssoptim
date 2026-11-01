#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (c) 2026 aoi mizma <aoi.mizma@path-works.net>
# SPDX-License-Identifier: MIT

"""Result rendering: the 4.3 result YAML (R-26, R-36).

The only output format the tool promises is the YAML of 4.3: the winning
distribution per party slot (core talents named separately), the objective
value the plugin returned for it, and the plugin spec that was run. ``--show-params``
(and ``-vv``) appends the aggregated parameter map and the effective scenario,
which is what lets a plugin author diff their own buffer and enemy-profile
assumptions against what the run actually used (R-36).

Console chatter is the orchestration layer's job (it owns the verbosity
definition, R-42); this module only turns the winning candidate into the
document, and hands it to ``--out`` or stdout.
"""

import os

import click
import yaml

from .ssoptim import pout, Level
from .data import InputError, SLOTS

KEY_ORDER = ("objective_plugin", "total_level", "objective", "feasible", "party",
             "aggregated_params", "scenario")


def document(best, value, members, problem, spec, total_level, feasible=True):
    """The 4.3 result document for the winning candidate (R-26).

    Args:
        best: the winning level vector.
        value: the value the objective module returned for it, verbatim.
        members: {slot: Member} holding the resolved talent levels.
        problem: the generated problem (for the variable ranges).
        spec: the objective spec that was run (4.3 ``objective_plugin``).
        total_level: the budget the run was given (4.3 ``total_level``).
        feasible: always True on a written result; kept explicit in the
        document because 4.3 spells the key out.

    Returns:
        dict: the result document, in 4.3 key order.
    """
    party = {}
    for slot in SLOTS:
        if slot not in members:
            continue
        member = members[slot]
        start, stop = problem["ranges"][slot]
        levels = {}
        for talent in member.talents:
            levels[talent["name"]] = int(best[talent["var"]])
        cores = [talent["name"] for talent in member.talents if talent["core"] and levels[talent["name"]] >= 1]
        party[slot] = {"core_talents": cores, "talent_levels": levels}

    doc = {
        "objective_plugin": spec,
        "total_level": int(total_level),
        "objective": value,
        "feasible": bool(feasible),
        "party": party,
    }
    return {key: doc[key] for key in KEY_ORDER if key in doc}


def with_params(doc, aggregated, scenario):
    """Append ``aggregated_params:`` and ``scenario:`` (4.3, --show-params)."""
    out = dict(doc)
    out["aggregated_params"] = {key: aggregated[key] for key in sorted(aggregated)}
    out["scenario"] = {key: scenario[key] for key in sorted(scenario)}
    return out


def as_yaml(doc):
    """YAML text of the document, key order preserved (4.3)."""
    return yaml.safe_dump(doc, default_flow_style=False, sort_keys=False, allow_unicode=True, width=100)


def write(doc, out=None, verbose=0):
    """Write the result: ``--out`` path, else stdout (7 ``-o`` default)."""
    text = as_yaml(doc)
    if out:
        try:
            with open(out, "w", encoding="utf-8") as fd:
                fd.write(text)
        except OSError as exc:
            raise InputError("cannot write result file {0}: {1}".format(out, exc))
        pout("result written to {0}".format(out), verbose, Level.INFO)
    else:
        click.echo(text, nl=False)
    return text
