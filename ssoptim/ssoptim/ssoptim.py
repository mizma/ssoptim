#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (c) 2026 aoi mizma <aoi.mizma@path-works.net>
# SPDX-License-Identifier: MIT

"""Orchestration entry point: cmd(kwargs).

No click definitions and no IO formatting live here: click options are parsed
in ``cli.py`` and rendered in ``report.py``; this module only orchestrates the
pipeline.  It also owns the single definition of verbosity (R-42): ``pout`` and
the ``Level`` enum, which plugins reach through ``ctx["log"]``.

The pipeline modules are imported inside ``cmd`` rather than at module level:
this module is the definition of ``pout``/``Level``, and ``talent.py``,
``plugins.py``, ``report.py`` and the objectives all import it, so a top-level
import here would close the cycle on a partially initialized module.
"""

from enum import IntEnum
from functools import partial
from pprint import pformat

import click


class Level(IntEnum):
    NOTSET = 0
    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40
    CRITICAL = 50


def pout(msg=None, Verbose=0, level=Level.INFO, newline=True):
    """stdout support method.

    All Error, Critical and Info messages are printed, while Warning and Debug
    follow the run's verbosity count (R-28, R-42):

    * INFO     -- intended standard output, printed to STDOUT always
    * DEBUG    -- intended debug output, STDOUT only when ``Verbose >= 2``
    * WARNING  -- intended detail/warning notice, STDERR only when ``Verbose >= 1``
    * ERROR    -- intended error, STDERR
    * CRITICAL -- intended critical error, STDERR

    Keyword Arguments:
        msg (string) -- message to print (default: {None})
        Verbose (Int) -- run verbosity count; gates DEBUG/WARNING messages (default: {0})
        level (Level) -- message level for colouring (default: {Level.INFO})
        newline (bool) -- set to False if a trailing new line is not needed (default: {True})
    """
    error = False
    if level in {Level.NOTSET, Level.DEBUG}:
        if Verbose < 2:
            return
        fg = "magenta"
    elif level == Level.INFO:
        fg = "green"
    elif level == Level.WARNING:
        if Verbose < 1:
            return
        fg = "yellow"
        error = True
    elif level in {Level.ERROR, Level.CRITICAL}:
        fg = "red"
        error = True
    else:
        fg = "white"
        pass
    click.echo(click.style(str(msg), fg=fg), nl=newline, err=error)
    pass


# The settings keys cli.py hands down: the 4.2 configuration keys plus the
# CLI-only knobs.  cli.py has already applied the 7 precedence chain
# (CLI > --restrictions file > --config file), so what is left here is the
# built-in default layer.
KNOWN_SETTINGS = (
    "verbose", "config", "party", "data_dirs", "objective", "total_level", "total_level_mode",
    "scenario", "objective_opts", "restrictions", "solver", "out", "show_params",
    "char", "sub", "main", "scenario_pairs", "objective_pairs",
)
SOLVER_DEFAULTS = {"maxiter": 300, "popsize": 24, "runs": 3, "seed": 1, "polish": True}


def cmd(kwargs):
    """Implementation.  Orchestrates the DESIGN.md 3-7 pipeline (R-25..R-29).

    Args:
        kwargs (dict): the flat settings dict cli.py assembled from the click
        options, the ``--config`` file and the ``--restrictions`` file (7
        precedence), keyed by the 4.2 config names.  ``cmd`` reads settings
        only - it knows no option names and does no formatting (report.py
        owns that) - and runs: data load -> party -> generated constraints ->
        objective resolution -> per-candidate ctx -> solve -> 4.3 result.

    Raises:
        InputError / Infeasible / PluginError / NoFeasible: the owning module's
        exception, which cli.py maps to the 7 exit codes (2/3/4/5).
    """
    from .data import InputError, load_characters, build_party, normalize_scenario
    from .constraints import build_problem
    from .plugins import build_run_context, resolve_plugin
    from .objectives import REGISTRY
    from .optimize import solve
    from .report import document, with_params, write

    verbose = kwargs.get("verbose", 0)
    log = partial(pout, Verbose=verbose)

    settings = {key: kwargs[key] for key in KNOWN_SETTINGS if key in kwargs}
    settings.setdefault("party", {})
    settings.setdefault("data_dirs", [])
    settings.setdefault("objective", "auto_attack")
    settings.setdefault("total_level_mode", "exact")
    settings.setdefault("scenario", normalize_scenario(None))
    settings.setdefault("objective_opts", {})
    settings.setdefault("restrictions", {})
    settings.setdefault("out", None)
    settings.setdefault("show_params", False)
    settings.setdefault("char", [])
    settings.setdefault("sub", [])
    settings.setdefault("main", None)
    solver = dict(SOLVER_DEFAULTS)
    solver.update(settings.get("solver") or {})
    settings["solver"] = solver

    # party: the 4.2 block, overridden by -m / the two -s (R-01, 7 precedence)
    party = dict(settings["party"])
    if settings["main"] is not None:
        party["main"] = settings["main"]
    if settings["sub"]:
        party["sub1"], party["sub2"] = settings["sub"]

    characters = load_characters(list(settings["char"]) + list(settings["data_dirs"]), log)
    built = build_party(party, characters, log)
    members, vars_layout = built["members"], built["vars"]

    total_level = settings.get("total_level")
    if total_level is None:
        raise InputError("total_level is mandatory: pass -t/--total-levels or set it in the config file (R-13, 7)")

    problem = build_problem(members, vars_layout, total_level, settings["total_level_mode"], settings["restrictions"])
    objective, spec = resolve_plugin(settings["objective"], REGISTRY, log)
    ctx = build_run_context(members, vars_layout, settings["scenario"], settings["objective_opts"], verbose, log)

    best, value = solve(
        objective,
        problem,
        ctx,
        total_level,
        settings["total_level_mode"],
        runs=solver["runs"],
        seed=solver["seed"],
        maxiter=solver["maxiter"],
        popsize=solver["popsize"],
        polish=solver["polish"],
        log=log,
    )

    doc = document(best, value, members, problem, spec, total_level)
    if settings["show_params"] or verbose >= 2:  # 4.3: --show-params, implied by -vv (R-36)
        doc = with_params(doc, ctx["aggregated"], settings["scenario"])
    write(doc, settings["out"], verbose)
    return doc
