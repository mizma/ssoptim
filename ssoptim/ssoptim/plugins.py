#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (c) 2026 aoi mizma <aoi.mizma@path-works.net>
# SPDX-License-Identifier: MIT

"""Objective-module resolution and the tool-built data context.

Resolution accepts the three spec forms of R-22: a built-in short name, a
dotted module path ``pkg.mod:func``, or a file path ``./plugins/x.py:func``
(loaded by path, so a pipx/uv-tool-installed copy takes new plugins without a
rebuild).

The context of R-37/R-38 is built **once per run** and then *filled* per
candidate: members keep their role-resolved skill/talent views, and each
evaluation only writes the level-resolved views (``talent_levels``,
``talent_params`` per member and ``ctx["aggregated"]``), so no YAML work and no
re-resolution happens on the hot path (5 invariant).

Verbosity reaches plugins through ``ctx["verbose"]`` and ``ctx["log"]``, the
template's ``pout`` already curried with the run's ``-v`` count (R-42); plugin
progress output must use it so ``-v``/``-vv`` mean one thing to tool and plugin.
"""

from functools import partial
import importlib
import importlib.util
import os

from .ssoptim import pout, Level
from .talent import aggregate_params, resolve_talent_params, resolve_talent_value

# The context of the candidate currently being evaluated, so the documented
# one-argument helper forms (6, README) work inside plugins. build_run_context
# / resolve_candidate keep this pointing at the active candidate context.
ACTIVE = {"ctx": None}

SLOTS = ("main", "sub1", "sub2")


class PluginError(Exception):
    """Objective module could not be loaded or raised while evaluating.

    Carries the exit code so cli.py can honour the 7 table (R-29 exit 4).
    """

    def __init__(self, message, code=4):
        Exception.__init__(self, message)
        self.message = message
        self.code = code


def module_function(spec):
    """Load ``target`` as a module:func pair, or raise PluginError (R-22).

    Args:
        spec (str): built-in short name, ``pkg.mod:func`` or ``./path/file.py:func``.

    Returns:
        tuple: (module, func_name) or (None, short_name) for a built-in name.
    """
    name, sep, func = str(spec).partition(":")
    if sep:
        if not func:
            raise PluginError("objective spec {0!r} needs a function after ':' (R-22)".format(spec))
        if name.startswith(".") or name.endswith(".py") or os.path.sep in name or (
            os.altsep and os.altsep in name
        ):
            return "file", name, func
        return "module", name, func
    return "builtin", name, None


def resolve_plugin(spec, registry, log=None):
    """Resolve a plugin spec into a callable ``f(x, ctx) -> float``.

    Args:
        spec (str): one of the three forms of R-22.
        registry (dict): built-in objectives (objectives.REGISTRY).
        log: the tool's warning logger (R-42), used for load notices.

    Returns:
        tuple: (callable, resolved_name) - resolved_name names the spec in the
        result YAML (4.3 objective_plugin).

    Raises:
        PluginError: unknown built-in, unimportable module, missing file or a
        missing attribute (exit 4).
    """
    kind, target, func = module_function(spec)
    if kind == "builtin":
        if target not in registry:
            raise PluginError(
                "unknown built-in objective {0!r}; known: {1}".format(
                    spec, ", ".join(sorted(registry))
                )
            )
        return registry[target], spec

    if kind == "file":
        path = os.path.abspath(target)
        if not os.path.isfile(path):
            raise PluginError("objective module file not found: {0}".format(path))
        stem = os.path.splitext(os.path.basename(path))[0]
        try:
            loader_spec = importlib.util.spec_from_file_location(stem, path)
            module = importlib.util.module_from_spec(loader_spec)
            loader_spec.loader.exec_module(module)
        except Exception as exc:
            raise PluginError("could not load objective module {0}: {1}".format(path, exc))
    else:
        try:
            module = importlib.import_module(target)
        except Exception as exc:
            raise PluginError("could not import objective module {0}: {1}".format(target, exc))
    try:
        return getattr(module, func), spec
    except AttributeError as exc:
        raise PluginError("objective module {0} has no {1} (R-22)".format(target, func))


def build_run_context(members, vars_layout, scenario, objective_opts=None, verbose=0, log=None):
    """Build the persistent part of the context once per run (R-37).

    Args:
        members (dict): {slot: Member} from data.build_party (full character
        data incl. HP/DEF for HP-scaled mechanics, skill blocks with
        cd/loop_time/sources, the talent set in use, R-37/R-40).
        vars_layout (list): [(slot, talent_name), ...] in R-08 order.
        scenario (dict): merged enemy profile (R-36).
        objective_opts (dict): plugin knobs from --objective-opts (R-36, R-37).
        verbose (int): the run's -v count (R-42).
        log: an already-curried warning logger; defaults to pout bound to the
        run verbosity.

    Returns:
        dict: the context; call resolve_candidate(x, ctx) per candidate.
    """
    if log is None:
        log = partial(pout, Verbose=verbose)
    ctx = {
        "members": members,
        "vars": vars_layout,
        "scenario": scenario,
        "objective_opts": dict(objective_opts) if objective_opts else {},
        "aggregated": {},
        "verbose": verbose,
        "log": log,
    }
    return ctx


def resolve_candidate(x, ctx):
    """Fill the level-resolved views of ``ctx`` for candidate ``x`` (R-38).

    Sets every member's ``talent_levels`` (name-keyed, R-08 order) and
    ``talent_params`` (the mandatory per-talent breakdown), plus the summed
    map ``ctx["aggregated"]`` identical to aggregate_params(x) (R-20, R-38),
    and makes ``ctx`` the active one so the one-argument helper forms work.

    Returns:
        dict: the same ctx, filled.
    """
    view = resolve_talent_params(x, ctx)
    for slot, member in ctx["members"].items():
        member.talent_levels = view[slot]["levels"]
        member.talent_params = view[slot]["talent_params"]
    ctx["aggregated"] = aggregate_params(x, ctx)
    ACTIVE["ctx"] = ctx
    return ctx


def objective_call(objective, x, ctx):
    """Call the objective module, mapping a plugin raise to PluginError.

    R-21: bigger is better; the tool maximizes and never negates or
    normalizes. A plugin raising is a user-code failure (exit 4, 7 table), and
    the -vv verbosity prints each evaluated value for diagnosis (R-28).
    """
    try:
        value = objective(x, ctx)
    except PluginError:
        raise
    except Exception as exc:
        raise PluginError("objective module raised while evaluating: {0}".format(exc))
    try:
        return float(value)
    except (TypeError, ValueError):
        raise PluginError(
            "objective module returned a non-number {0!r}; plugins return bigger-is-better numbers (R-21, Q-1)".format(
                value
            )
        )
