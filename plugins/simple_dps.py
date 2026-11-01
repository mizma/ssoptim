#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (c) 2026 aoi mizma <aoi.mizma@path-works.net>
# SPDX-License-Identifier: MIT

"""Shipped DPS sample plugin (DESIGN.md 6.3 item 2, M3/M8).

This is an **external** objective module: it lives in the repo's `plugins/`
dir and is loaded by path (`ssoptim optimize -f ./plugins/simple_dps.py:objective`),
which is the R-22 extensibility form for a pipx/uv-tool-installed copy.

It reports the main character's DPS under the "use a skill again as soon as
its CD is up" default (R-31, 6.2): every damage source of the auto and main
skills is calculated separately with only its own buffers (R-32/R-33), divided
by its own period (`loop_time` for the auto cycle, `cd` for the active skill,
R-30) and summed.  Buffs are applied **before** each kernel call by this
module, never by the kernel (R-34).  A value carrying the R-43
`duration`/`activation` pair is folded in with uptime
`min(duration, period(activation)) / period(activation)`; where the pair is
absent the module falls back to `objective_opts.uptime_fraction` and says so
with `-v` (R-39).  Talent contributions are read through the per-talent
breakdown of R-38 because that is what attributes a buff to the talent that
granted it.  No timeline, no energy model: ultimate portions are skipped, as
6.2 states.
"""

from ssoptim.ssoptim.damage import calculate_damage, skill_percent_to_amend
from ssoptim.ssoptim.data import ELEMENTS
from ssoptim.ssoptim.ssoptim import Level
from ssoptim.ssoptim.talent import MAX_SUB_LEVEL

# The main slot may use auto/main/ult (R-40); the DPS shape of 6.2 uses the
# timed ones, and ult stays out because the tool models no energy/charge.
DPS_SKILLS = ("auto_skill", "main_skill")
SKILL_SLOT = {"auto_skill": "AutoAttack", "main_skill": "Skill", "sub_skill": "Skill", "ult_skill": "Ultimate"}
CRIT_BASE = 1.5
CRIT_RATE_BASE = 0.5


def skill_period(skill):
    """Period a skill's own sources default to: loop_time or cd (R-30, 6.2)."""
    if skill is None:
        return None
    return skill.get("loop_time") or skill.get("cd")


def period_of(skill, source):
    """A source may carry its own period; else the skill-level one (R-32, 6.2)."""
    return source.get("loop_time") or source.get("cd") or skill_period(skill)


def element_of(key):
    """Element name of an `elem{E}Dmg` damage key (R-35)."""
    if key.startswith("elem") and key.endswith("Dmg"):
        name = key[len("elem") : -len("Dmg")]
        if name in ELEMENTS:
            return name
    return None


def slot_class(skill_key, damage_key):
    """Slot class of one damage source (R-32, R-35).

    A `slot{X}Dmg` damage key names the portion's own class, so a mark portion
    takes `slotMarkDmg` and not `slotSkillDmg`; otherwise the class follows the
    skill the source came from (R-40).
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
    """Per-element RES for a source (R-36 `res_table` over the scenario RES)."""
    table = scenario.get("res_table") or {}
    if element and element in table:
        return table[element]
    if "default" in table:
        return table["default"]
    return scenario["RES"]


def gated(value, duration, period, ctx, log):
    """Uptime of a gated value: min(duration, period)/period (R-43, 6.2).

    Without a usable period the value keeps the R-39 documented-convention
    reading and the plugin-declared fallback factor, announced with `-v`.
    """
    if duration is None or not period:
        fraction = (ctx.get("objective_opts") or {}).get("uptime_fraction", 1.0)
        log(
            "gated value has no usable activation period; assuming uptime_fraction={0}".format(
                fraction
            ),
            level=Level.WARNING,
        )
        return value * fraction
    return value * min(duration, period) / period


def effective_params(ctx):
    """Effective buffer map, gated values uptime-scaled (R-38, R-39, R-43).

    Walks the **per-talent** breakdown so a gated buff is attributed to the
    talent that granted it (the summed map alone cannot say that, R-38); a
    value with no `duration`/`activation` pair keeps its full reading.
    """
    main = ctx["members"]["main"]
    log = ctx["log"]
    total = {}
    for slot, member in ctx["members"].items():
        for talent in member.talents:
            level = member.talent_levels.get(talent["name"], 0)
            if level <= 0:
                continue
            duration = talent["duration"][level] if talent["duration"] else None
            activation = talent["activation"]
            scale = 1.0
            if duration is not None and activation:
                period = skill_period(getattr(main, activation, None))
                for key, table in talent["params"].items():
                    value = table[level]
                    if not value:
                        continue
                    total[key] = total.get(key, 0.0) + gated(value, duration, period, ctx, log)
                continue
            for key, table in talent["params"].items():
                value = table[level]
                if value:
                    total[key] = total.get(key, 0.0) + value
    return total


def objective(x, ctx):
    """Main-character DPS: bigger is better (R-21, Q-1).

    Args:
        x (sequence): flat level vector (R-08) - read through the tool's level
            resolution in `ctx`, never by indexing talent positions.
        ctx (dict): the tool-built context (R-37/R-38): members with full
            stats/skills/talents and per-candidate `talent_levels`,
            `talent_params`, plus `scenario`, `objective_opts`, `verbose`,
            `log`.
    """
    main = ctx["members"]["main"]
    scenario = ctx["scenario"]
    log = ctx["log"]

    params = effective_params(ctx)
    atk = main.stats.get("Atk", 0.0) * (1.0 + params.get("Atk_multiplier", 0.0)) + params.get(
        "Atk_absMod", 0.0
    )
    crit_rate = CRIT_RATE_BASE + params.get("crit_rateMod", 0.0)
    crit_dmg = CRIT_BASE + params.get("critDmgMod", 0.0)

    # Party-side debuffs and skill-applied debuffs fold into the enemy profile
    # before the calls (R-34/R-35); skill-applied ones carry the R-43 pair.
    def_rate = params.get("DEF_rate_mod", 0.0)
    res_rate = params.get("RES_rate_mod", 0.0)
    for skill_key in DPS_SKILLS:
        skill = getattr(main, skill_key, None)
        if skill is None:
            continue
        period_skill = skill_period(skill)
        for source in skill["sources"]:
            for buf_key in ("buf", "debuf"):
                for key, buf in source.get(buf_key, {}).items():
                    value = buf["params"][1]  # skill maps are authored at level 1
                    duration = buf["duration"][1] if buf["duration"] else None
                    activation = buf["activation"]
                    period = skill_period(getattr(main, activation, None)) if activation else period_skill
                    scaled = gated(value, duration, period, ctx, log)
                    if key == "DEF_rate_mod":
                        def_rate += scaled
                    elif key == "RES_rate_mod":
                        res_rate += scaled

    def_eff = scenario["DEF"] * (1.0 - def_rate)

    dps = 0.0
    for skill_key in DPS_SKILLS:
        skill = getattr(main, skill_key, None)
        if skill is None:
            continue
        for source in skill["sources"]:
            period = period_of(skill, source)
            if not period:
                # 6.2: an untimed source is per-hit only; skip it and say so.
                log(
                    "source {0!r} of {1} carries no loop_time/cd: skipped from DPS".format(
                        source.get("name", "unnamed"), skill_key
                    ),
                    level=Level.WARNING,
                )
                continue
            for damage_key, damage_value in source["damage"].items():
                element = element_of(damage_key)
                slot = slot_class(skill_key, damage_key)
                hit = calculate_damage(
                    Atk=atk,
                    skillPercentAmend=percent_of(damage_value),
                    skillIntensity=1.0 + params.get("skillIntensity", 0.0),
                    slotDmg=1.0 + params.get("slot{0}Dmg".format(slot), 0.0),
                    elementDmg=1.0 + (params.get(damage_key, 0.0) if element else 0.0),
                    slotCritDmg=params.get("slot{0}CritDmg".format(slot), 0.0),
                    critDmg=crit_dmg,
                    crit_rate=crit_rate,
                    is_dot=bool(source.get("dot", False)),
                    DEF=def_eff,
                    DEF_Ignore=scenario.get("DEF_Ignore", 0.0),
                    DEF_Penetrate=scenario.get("DEF_Penetrate", 0.0),
                    RES=source_res(scenario, element) * (1.0 - res_rate),
                    PEN=scenario.get("PEN", 0.0),
                    VUL=scenario.get("VUL", 0.0),
                    as_int=False,
                )
                dps += hit / period
    return float(dps)
