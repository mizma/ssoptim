#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (c) 2026 aoi mizma <aoi.mizma@path-works.net>
# SPDX-License-Identifier: MIT

"""Built-in default objective (R-23): auto-attack skill damage, per hit.

The reference implementation and the objective of the README examples. It is
one kernel call per damage source of the main character's **auto skill**, with
only the buffers that belong to that source (R-32, R-33): the plugin - not the
kernel - folds the Atk buffs into the attacker's effective status first
(R-34), picks the element/slot/crit keys of that source (R-35), and reads the
enemy profile from ``ctx["scenario"]`` including the per-element RES of
``res_table`` (R-36). No timing arithmetic: this objective is per-hit, so
``loop_time`` is not consulted (R-31 puts that choice in the plugin).
"""

from ..damage import calculate_damage, skill_percent_to_amend
from ..plugins import aggregate_params
from ..data import ELEMENTS
from ..ssoptim import Level

# Slot class of each skill key (R-40 role semantics over the four keys).
SKILL_SLOT = {
    "auto_skill": "AutoAttack",
    "main_skill": "Skill",
    "sub_skill": "Skill",
    "ult_skill": "Ultimate",
}

# Buffer-key vocabulary (R-35, single source of truth in PLUGINS.md).
CRIT_BASE = 1.5
CRIT_RATE_BASE = 0.5


def element_of(damage_key):
    """Element name of an ``elem{E}Dmg`` damage-class key, else None (R-35)."""
    if damage_key.startswith("elem") and damage_key.endswith("Dmg"):
        name = damage_key[len("elem") : -len("Dmg")]
        if name in ELEMENTS:
            return name
    return None


def slot_class(skill_key, damage_key):
    """Slot class a damage source belongs to (R-32, R-35).

    A ``slot{X}Dmg`` damage key names the portion's own class (a mark portion
    takes ``slotMarkDmg``, not ``slotSkillDmg``); otherwise the class follows
    the skill the source came from (R-40).
    """
    if damage_key.startswith("slot") and damage_key.endswith("Dmg"):
        return damage_key[len("slot") : -len("Dmg")]
    return SKILL_SLOT.get(skill_key, "Other")


def percent_of(damage_value):
    """Kernel skillPercentAmend from a 4.1 damage entry (R-24 units)."""
    if isinstance(damage_value, dict):
        return skill_percent_to_amend(damage_value["skillPercentAmend"] * 100)
    return skill_percent_to_amend(damage_value * 100)


def source_res(scenario, element):
    """Per-element RES for a source (R-36 res_table over the scenario RES)."""
    table = scenario.get("res_table") or {}
    if element and element in table:
        return table[element]
    if "default" in table:
        return table["default"]
    return scenario["RES"]


def effective_def(scenario, params):
    """Enemy DEF with party-side debuffs folded in (R-35: DEF_rate_mod -> DEF -)."""
    return scenario["DEF"] * (1.0 - params.get("DEF_rate_mod", 0.0))


def effective_res(scenario, params, element):
    """Enemy RES with party-side debuffs folded in (R-35: RES_rate_mod -> RES -)."""
    return source_res(scenario, element) * (1.0 - params.get("RES_rate_mod", 0.0))


def objective(x, ctx):
    """Per-hit auto-attack damage of the main character: bigger is better.

    Args:
        x (sequence): flat level vector (R-08); read through the helpers only,
            never by indexing positions of a character's talents.
        ctx (dict): tool-built context of R-37/R-38 (members with full stats and
            normalized ``sources``, scenario, objective_opts, verbosity).

    Returns:
        float: summed per-source auto-attack damage of the main member.
    """
    main = ctx["members"]["main"]
    params = aggregate_params(x)
    scenario = ctx["scenario"]

    atk = main.stats.get("Atk", 0.0) * (1.0 + params.get("Atk_multiplier", 0.0)) + params.get(
        "Atk_absMod", 0.0
    )
    crit_rate = CRIT_RATE_BASE + params.get("crit_rateMod", 0.0)
    crit_dmg = CRIT_BASE + params.get("critDmgMod", 0.0)

    auto = getattr(main, "auto_skill", None)
    if auto is None:
        # R-42: data-missing notices go through ctx["log"] at Level.WARNING.
        ctx["log"]("main character {0} has no auto_skill: per-hit objective returns 0".format(main.name), level=Level.WARNING)
        return 0.0

    total = 0.0
    for source in auto["sources"]:
        dot = bool(source.get("dot", False))
        for damage_key, damage_value in source["damage"].items():
            element = element_of(damage_key)
            slot = slot_class("auto_skill", damage_key)
            total += calculate_damage(
                Atk=atk,
                skillPercentAmend=percent_of(damage_value),
                skillIntensity=1.0 + params.get("skillIntensity", 0.0),
                slotDmg=1.0 + params.get("slot{0}Dmg".format(slot), 0.0),
                elementDmg=1.0 + (params.get(damage_key, 0.0) if element else 0.0),
                slotCritDmg=params.get("slot{0}CritDmg".format(slot), 0.0),
                critDmg=crit_dmg,
                crit_rate=crit_rate,
                is_dot=dot,
                DEF=effective_def(scenario, params),
                DEF_Ignore=scenario.get("DEF_Ignore", 0.0),
                DEF_Penetrate=scenario.get("DEF_Penetrate", 0.0),
                RES=effective_res(scenario, params, element),
                PEN=scenario.get("PEN", 0.0),
                VUL=scenario.get("VUL", 0.0),
                as_int=False,
            )
    return float(total)
