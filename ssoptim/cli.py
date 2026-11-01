#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (c) 2026 aoi mizma <aoi.mizma@path-works.net>
# SPDX-License-Identifier: MIT

"""Main CLI Setup and Entrypoint.

Every option of 7 lives here, and so does the precedence rule of 7 ("command
line options override the --restrictions file, which overrides the --config
file, which overrides built-in defaults"): cli.py turns the click kwargs plus
the YAML config into one flat settings dict, and hands that to the
orchestration layer (``ssoptim.ssoptim.cmd``), which stays free of option
names and of output formatting.  The exit codes of 7 are mapped here too, by
the exception class each owning module raises.

Note that option *dests* are spelled as the 4.2 config keys, so a config
value and its CLI equivalent land in the same slot of the settings dict.
"""

from __future__ import absolute_import, division, print_function

import click
import os
import sys

from .ssoptim.ssoptim import cmd, pout, Level
from .ssoptim.data import InputError, load_run_config, load_yaml, normalize_scenario, scenario_key_override, coerce_scalar
from .ssoptim.constraints import Infeasible
from .ssoptim.plugins import PluginError
from .ssoptim.optimize import NoFeasible
from ssoptim import __version__

CONFIG_DEFAULT = "ssoptim.yml"

CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"])

# Exit codes of 7 are raised as the owning module's exception class, so the
# mapping is one line per class here.
ERROR_CLASSES = (InputError, Infeasible, PluginError, NoFeasible)

# 4.2 run-configuration schema: written out when no config file exists yet.
CONFIG_TEMPLATE = """\
party:
  main: null
  sub1: null
  sub2: null
data_dirs: []
objective: auto_attack
total_level: null
total_level_mode: exact
scenario:
  DEF: 500
  RES: 750
objective_opts: {}
restrictions: {}
solver:
  maxiter: 300
  popsize: 24
  runs: 3
  seed: 1
  polish: true
"""


@click.group(context_settings=CONTEXT_SETTINGS)
@click.version_option(version=__version__, prog_name="ssoptim")
def cli():
    """ssoptim: Stella Sora party build optimization tool."""
    pass


@cli.command()
@click.option(
    "--verbose",
    "-v",
    "verbose",
    count=True,
    help="output in verbose mode",
)
@click.option(
    "--config",
    "-c",
    "config",
    default=None,
    help="Path to Configuration File (default: ssoptim.yml)",
)
@click.option("--main", "-m", "main", default=None, help="main character name (overrides party.main)")
@click.option("--sub", "-s", "sub", multiple=True, help="support character name; repeat exactly twice")
@click.option("--total-levels", "-t", "total_level", type=int, default=None, help="total talent levels to distribute")
@click.option("--objective", "-f", "objective", default=None, help="objective spec: auto_attack, pkg.mod:func, ./p.py:func")
@click.option("--char", "char", multiple=True, help="character data file or directory; repeatable")
@click.option("--restrictions", "restrictions_file", default=None, help="YAML file of restrictions (merged over the config)")
@click.option("--total-level-mode", "total_level_mode", type=click.Choice(["exact", "at_most"]), default=None, help="exact: budget must be spent; at_most: levels may go unused")
@click.option("--out", "-o", "out", default=None, help="write the result YAML here (default: stdout)")
@click.option("--scenario", "scenario", multiple=True, help="KEY=VAL enemy-profile override; repeatable")
@click.option("--objective-opts", "objective_opts", multiple=True, help="KEY=VAL plugin knob; repeatable")
@click.option("--show-params", "show_params", is_flag=True, default=False, help="dump the aggregated parameters and the effective scenario")
@click.option("--maxiter", "maxiter", type=int, default=None, help="solver: differential evolution maxiter")
@click.option("--popsize", "popsize", type=int, default=None, help="solver: differential evolution popsize")
@click.option("--runs", "runs", type=int, default=None, help="solver: seeded restarts, best feasible kept")
@click.option("--seed", "seed", type=int, default=None, help="solver: base seed for the restarts")
@click.option("--no-polish", "no_polish", is_flag=True, default=False, help="solver: skip the polish stage")
def optimize(**kwargs):
    """Optimize talent-level distribution for a fixed party."""
    # the 7 exit-code table: each owning module raises its own class, mapped
    # here so a click run sees the SystemExit code (and CliRunner with it).
    try:
        cmd(settings_of(kwargs))
    except ERROR_CLASSES as exc:
        pout(str(exc), kwargs.get("verbose", 0), Level.ERROR)
        raise SystemExit(getattr(exc, "code", 1))
    pass


def write_default_config(path=CONFIG_DEFAULT):
    """4.2 first-run helper: create the schema file when none exists."""
    if os.path.isfile(path):
        return False
    try:
        with open(path, "w", encoding="utf-8") as fd:
            fd.write(CONFIG_TEMPLATE)
    except OSError:
        return False
    return True


def merge_restrictions(config, file_path):
    """--restrictions FILE merged over the config's restrictions (7)."""
    merged = dict(config.get("restrictions") or {})
    if not file_path:
        return merged
    extra = load_yaml(file_path, "restrictions file")
    if "restrictions" in extra and set(extra) <= {"restrictions"}:
        extra = extra["restrictions"]
    for slot, block in extra.items():
        if slot in ("restrictions",):
            continue
        if not isinstance(block, dict):
            raise InputError("restrictions file {0}: {1} must be a mapping (4.2)".format(file_path, slot))
        current = dict(merged.get(slot) or {})
        for key, value in block.items():
            if key in ("min", "max"):
                current[key] = value
            elif key == "talent_levels":
                current["talent_levels"] = merge_talent_levels(current.get("talent_levels") or [], value)
            else:
                raise InputError(
                    "restrictions file {0}: unknown key {1!r} for {2}; allowed: min, max, talent_levels (4.2)".format(
                        file_path, key, slot
                    )
                )
        merged[slot] = current
    return merged


def merge_talent_levels(base, override):
    """Restriction-file entries win by name; positional entries stay put."""
    out = list(base)
    for entry in override or []:
        if not isinstance(entry, dict):
            raise InputError("restrictions file talent_levels entry must be a mapping (4.2)")
        name = entry.get("name")
        replaced = False
        if name is not None:
            for index, existing in enumerate(out):
                if isinstance(existing, dict) and existing.get("name") == name:
                    out[index] = entry
                    replaced = True
                    break
        if not replaced:
            out.append(entry)
    return out


def settings_of(kwargs):
    """One flat settings dict: built-in defaults < config < restrictions < CLI.

    Config keys spelled like option dests (see the option declarations above)
    are overwritten by any value the user actually passed on the command line,
    so precedence is exactly the 7 line: CLI > --restrictions > --config >
    defaults.
    """
    verbose = kwargs.get("verbose", 0)
    config_path = kwargs.get("config") or CONFIG_DEFAULT
    if kwargs.get("config"):
        config = load_run_config(config_path)
    elif os.path.isfile(config_path):
        config = load_run_config(config_path)
    else:
        created = write_default_config(config_path)
        config = load_run_config(config_path) if created else {}
        if created:
            pout("wrote default configuration file {0} (4.2 schema); fill it in or pass -c".format(config_path), verbose, Level.WARNING)
    if not isinstance(config, dict):
        raise InputError("configuration file {0} must be a mapping (4.2)".format(config_path))

    known = {"party", "data_dirs", "objective", "total_level", "total_level_mode", "scenario",
             "objective_opts", "restrictions", "solver"}
    for key in config:
        if key not in known:
            raise InputError("unknown configuration key {0!r} in {1} (4.2)".format(key, config_path))

    settings = {
        "verbose": verbose,
        "config": config_path,
        "party": dict(config.get("party") or {}),
        "data_dirs": list(config.get("data_dirs") or []),
        "objective": (config.get("objective") or "auto_attack"),
        "total_level": config.get("total_level"),
        "total_level_mode": config.get("total_level_mode") or "exact",
        "scenario": normalize_scenario(config.get("scenario")),
        "objective_opts": dict(config.get("objective_opts") or {}),
        "solver": dict(config.get("solver") or {}),
        "out": None,
        "show_params": False,
        "char": [],
        "sub": [],
        "main": None,
        "restrictions_file": None,
        "scenario_pairs": [],
        "objective_pairs": [],
    }

    # CLI layer: only values the user actually gave participate.
    if kwargs.get("main") is not None:
        settings["main"] = kwargs["main"]
    if kwargs.get("sub"):
        subs = list(kwargs["sub"])
        if len(subs) != 2:
            raise InputError("--sub must be given exactly twice (sub1 then sub2), got {0} (7)".format(len(subs)))
        settings["sub"] = subs
    if kwargs.get("char"):
        settings["char"] = list(kwargs["char"])
    if kwargs.get("total_level") is not None:
        settings["total_level"] = kwargs["total_level"]
    if kwargs.get("total_level_mode") is not None:
        settings["total_level_mode"] = kwargs["total_level_mode"]
    if kwargs.get("objective") is not None:
        settings["objective"] = kwargs["objective"]
    if kwargs.get("out") is not None:
        settings["out"] = kwargs["out"]
    if kwargs.get("show_params"):
        settings["show_params"] = True
    settings["scenario_pairs"] = list(kwargs.get("scenario") or [])
    settings["objective_pairs"] = list(kwargs.get("objective_opts") or [])

    solver = dict(settings["solver"])
    for key in ("maxiter", "popsize", "runs", "seed"):
        if kwargs.get(key) is not None:
            solver[key] = kwargs[key]
    if kwargs.get("no_polish"):
        solver["polish"] = False
    if "polish" not in solver:
        solver["polish"] = True
    settings["solver"] = solver

    settings["restrictions"] = merge_restrictions(config, kwargs.get("restrictions_file"))

    for pair in settings["scenario_pairs"]:
        scenario_key_override(settings["scenario"], [pair])
    for pair in settings["objective_pairs"]:
        raw_key, sep, raw_value = str(pair).partition("=")
        if not sep:
            raise InputError("--objective-opts must be KEY=VALUE, got {0!r}".format(pair))
        settings["objective_opts"][raw_key.strip()] = coerce_scalar(raw_value)

    return settings


def main():
    """Main script."""
    cli()
    pass


if __name__ == "__main__":
    main()
