#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (c) 2026 aoi mizma <aoi.mizma@path-works.net>
# SPDX-License-Identifier: MIT

"""Sparse talent level maps -> precomputed level tables (R-19, R-38, R-43).

A talent entry maps a free-form parameter key to a sparse ``{level: value}``
map (R-19, R-20).  Only the anchors the author bothered to write are present;
the loader expands them once into a table indexed by level so no objective
module re-reads YAML per evaluation (§5 invariant, R-38).

Interpolation is pinned in DESIGN.md 4.1 (R-19):

* level 0 contributes nothing, and the origin ``(0, 0)`` acts as an anchor,
* values between two declared anchors change in an even step,
* levels past the last declared anchor keep that anchor's value (no
  extrapolation beyond authored evidence).

The reserved keys ``duration``/``activation`` (R-43) share the level map but are
convention metadata: they are kept aside and never aggregated (R-20, R-35).
"""

MAX_SUB_LEVEL = 6
CORE_MAX_LEVEL = 1
CORE_TALENT_COUNT = 4
SUB_TALENT_COUNT = 12
TALENT_COUNT = CORE_TALENT_COUNT + SUB_TALENT_COUNT

RESERVED_KEYS = frozenset({"duration", "activation"})
SKILL_KEYS = (
    "auto_skill",
    "main_skill",
    "sub_skill",
    "ult_skill",
)
SLOTS = ("main", "sub1", "sub2")


def split_reserved(value_map):
    """Split a talent value map into (level anchors, reserved pair) (R-43).

    Args:
        value_map (dict): raw YAML map, e.g. ``{1: 0.045, 6: 0.18, duration:
        {1: 10, 4: 12}, activation: main_skill}``

    Returns:
        tuple: ``(level_anchors, reserved)`` where ``reserved`` only ever holds
        the ``duration``/``activation`` keys.
    """
    anchors = {}
    reserved = {}
    for key, val in value_map.items():
        if isinstance(key, str) and key in RESERVED_KEYS:
            reserved[key] = val
        else:
            anchors[key] = val
    return anchors, reserved


def level_map_table(anchors, max_level=MAX_SUB_LEVEL):
    """Expand sparse ``{level: value}`` anchors into a level-indexed table (R-19).

    Args:
        anchors (dict): declared ``{level: value}`` pairs; keys must be integers
        in 0..max_level and values numeric.
        max_level (int): highest level the table covers (1 for core talents, 6
        for sub talents, R-04/R-05).

    Returns:
        tuple: ``table[level]`` for level 0..max_level; ``table[0]`` is always
        0.0 because level 0 means "not owned" (R-05).

    Raises:
        ValueError: non-numeric key/value or an out-of-range level key.  The
        loader (data.py) converts this into an input error (R-29 exit 2).
    """
    numeric = {}
    for key, val in anchors.items():
        if isinstance(key, bool):
            raise ValueError("level key must be an integer, got {0!r}".format(key))
        if isinstance(key, int) or (isinstance(key, str) and key.lstrip("-").isdigit()):
            level = int(key)
        else:
            raise ValueError(
                "unknown key {0!r} in a level map; level keys are integers 0..{1}".format(
                    key, max_level
                )
            )
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            raise ValueError(
                "level value must be numeric, got {0!r} at level {1}".format(val, level)
            )
        if level < 0 or level > max_level:
            raise ValueError("level key {0} out of range 0..{1}".format(level, max_level))
        numeric[level] = float(val)

    table = [0.0] * (max_level + 1)
    declared = sorted(level for level in numeric if level > 0)
    if not declared:
        return tuple(table)

    # The origin (0, 0) is an anchor (R-19); a declared level-0 value never
    # contributes anything (level 0 = not owned).
    anchor_map = {level: numeric[level] for level in declared}
    anchor_map[0] = 0.0 if 0 not in numeric else numeric[0]
    anchor_levels = sorted(anchor_map)

    for level in range(1, max_level + 1):
        if level in numeric and level > 0:
            table[level] = numeric[level]
            continue
        below = max(pt for pt in anchor_levels if pt <= level)
        above_choices = [pt for pt in anchor_levels if pt >= level]
        if not above_choices:
            # Flat beyond the last declared anchor: no extrapolation (11, 22).
            table[level] = anchor_map[below]
            continue
        x0, x1 = below, min(above_choices)
        y0, y1 = anchor_map[x0], anchor_map[x1]
        # Even step between the two anchors (R-19).
        table[level] = y0 + (y1 - y0) * (level - x0) / (x1 - x0)
    table[0] = 0.0
    return tuple(table)


def duration_table(duration, max_level=MAX_SUB_LEVEL):
    """Reserved ``duration`` (seconds) -> level-indexed table (R-43).

    Durations read as *bands*, matching DESIGN 4.1's worked example:
    ``{1: 10, 4: 12}`` is 10 s for levels 1-3 and 12 s for 4-6, i.e. the last
    declared anchor at or below the level applies.  Levels below the first
    anchor take that first anchor: a gated buff exists at every owned level,
    and 0 s would mean "no buff".  A bare number is the same at every level.
    (DESIGN.md 3's R-43 note states this: the R-19 even-step rule does
    not reproduce the documented 10/12 band; §10 K-10 keeps the gap.)
    """
    if duration is None:
        return None
    if isinstance(duration, (int, float)) and not isinstance(duration, bool):
        if duration <= 0:
            raise ValueError("duration must be > 0 seconds, got {0!r}".format(duration))
        return tuple([0.0] + [float(duration)] * max_level)
    if isinstance(duration, dict):
        anchors, _ = split_reserved(duration)
        numeric = {}
        for key, val in anchors.items():
            if isinstance(key, bool) or not isinstance(key, int):
                raise ValueError("duration band key must be an integer level, got {0!r}".format(key))
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                raise ValueError("duration must be numeric seconds, got {0!r}".format(val))
            if key < 0 or key > max_level:
                raise ValueError("duration band level {0} out of range 0..{1}".format(key, max_level))
            if val < 0:
                raise ValueError("duration must be > 0 seconds, got {0!r}".format(val))
            numeric[int(key)] = float(val)
        declared = sorted(level for level in numeric if level > 0)
        if not declared:
            raise ValueError("duration must be > 0 seconds, got no level band (R-43)")
        table = [0.0] * (max_level + 1)
        for level in range(1, max_level + 1):
            below = [pt for pt in declared if pt <= level]
            table[level] = numeric[below[-1]] if below else numeric[declared[0]]
        if max(table) <= 0:
            raise ValueError("duration must be > 0 seconds, got {0!r}".format(duration))
        table[0] = 0.0
        return tuple(table)
    raise ValueError("duration must be a number of seconds or a level map, got {0!r}".format(duration))


def activation_key(activation):
    """Validate reserved ``activation`` against the four skill keys (R-43, R-40).

    Args:
        activation: the declared tag, or None when the value is not gated.

    Returns:
        str or None
    """
    if activation is None:
        return None
    if not isinstance(activation, str) or activation not in SKILL_KEYS:
        raise ValueError(
            "activation must be one of {0}, got {1!r}".format(SKILL_KEYS, activation)
        )
    return str(activation)


def talent_entry(entry, index, core):
    """Build one validated talent record from a YAML list entry (R-03, R-17).

    Args:
        entry (dict): raw YAML entry with ``talent_name`` plus free-form
            parameter keys mapped to sparse level maps.
        index (int): declaration index inside the talent set; defines the
            variable order of that character (R-08, R-17).
        core (bool): expected core/sub kind, derived from ``index``.

    Returns:
        dict: ``{"name", "core", "index", "max_level", "params", "duration",
        "activation"}``; ``params`` maps each parameter key (character-specific
        keys included, R-20) to a level table precomputed once (R-19).

    Raises:
        ValueError: bad name, ``core_talent`` mismatch, non-map value, or an
        invalid level/reserved key.
    """
    if not isinstance(entry, dict):
        raise ValueError("talent entry must be a map, got {0!r}".format(entry))
    name = entry.get("talent_name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("talent entry needs a non-empty talent_name")

    max_level = CORE_MAX_LEVEL if core else MAX_SUB_LEVEL
    declared_core = entry.get("core_talent")
    if declared_core is not None and not isinstance(declared_core, bool):
        raise ValueError("core_talent must be a boolean, got {0!r}".format(declared_core))
    if declared_core is not None and declared_core != core:
        raise ValueError(
            "core_talent mismatch at index {0}: core talents are the first four "
            "entries (R-17), got {1!r}".format(index, declared_core)
        )

    params = {}
    duration = None
    activation = None
    for key, value_map in entry.items():
        if key in ("talent_name", "core_talent"):
            continue
        if not isinstance(value_map, dict):
            raise ValueError(
                "talent {0!r} key {1!r} must map levels to values, got {2!r}".format(
                    name, key, value_map
                )
            )
        anchors, reserved = split_reserved(value_map)
        if "duration" in value_map:
            duration = duration_table(value_map["duration"], max_level)
        if "activation" in value_map:
            activation = activation_key(value_map["activation"])
        params[key] = level_map_table(anchors, max_level)
    return {
        "name": name,
        "core": bool(core),
        "index": index,
        "max_level": max_level,
        "params": params,
        "duration": duration,
        "activation": activation,
    }


def resolve_talent_value(param, level):
    """Interpolated value of one talent parameter at ``level`` (R-19).

    Args:
        param: a level table (sequence) or a sparse ``{level: value}`` map.
        level (int): the level to resolve; 0 contributes nothing.

    Returns:
        float
    """
    level = int(level)
    if level <= 0:
        return 0.0
    if isinstance(param, (list, tuple)):
        return float(param[min(level, len(param) - 1)])
    return level_map_table(param)[level]


def member_field(member, key):
    """Read a member field whether the slot view is a Member or a plain dict.

    ``ctx["members"][slot]`` is the tool's Member object (R-37: attribute
    access, README/§6), but hand-written contexts may pass a dict; both work.
    """
    return member[key] if isinstance(member, dict) else getattr(member, key)


def resolve_talent_params(x, ctx=None):
    """Per-talent breakdown of the candidate vector ``x`` (R-38).

    Args:
        x (sequence): flat integer level vector, main first then sub1, sub2,
            each in YAML declaration order (R-08).  Each talent record carries
            its variable index in ``var``.
        ctx (dict): tool-built context; defaults to the active run context set
            by the optimizer (R-37), so plugin code may call
            ``resolve_talent_params(x)`` (§6, README).

    Returns:
        dict: ``{slot: {"levels": {talent_name: level}, "talent_params":
        {talent_name: {key: value}}}}`` — the mandatory per-talent breakdown.
    """
    ctx = ctx if ctx is not None else active_ctx()
    out = {}
    for slot in (slot for slot in SLOTS if slot in ctx["members"]):
        levels = {}
        params = {}
        for talent in member_field(ctx["members"][slot], "talents"):
            level = int(x[talent["var"]])
            levels[talent["name"]] = level
            params[talent["name"]] = {key: table[level] for key, table in talent["params"].items()}
        out[slot] = {"levels": levels, "talent_params": params}
    return out


def aggregate_params(x, ctx=None):
    """Sum every talent parameter at the chosen levels (R-20).

    Keys stay free-form, including character-specific keys unknown to the
    damage kernel (R-20); the result equals ``ctx["aggregated"]`` (R-38).

    Args:
        x (sequence): flat level vector (R-08).
        ctx (dict): tool-built context; defaults to the active run context.

    Returns:
        dict: ``{key: summed value}``
    """
    ctx = ctx if ctx is not None else active_ctx()
    total = {}
    for slot in (slot for slot in SLOTS if slot in ctx["members"]):
        for talent in member_field(ctx["members"][slot], "talents"):
            level = int(x[talent["var"]])
            for key, table in talent["params"].items():
                value = table[level]
                if value:
                    total[key] = total.get(key, 0.0) + value
    return total


def active_ctx():
    """The context of the candidate currently being evaluated, or None.

    Set by ``plugins.py``/``optimize.py`` per candidate so the documented
    one-argument helper forms (§6) work inside plugins; passing ``ctx``
    explicitly always wins.
    """
    from .plugins import ACTIVE

    return ACTIVE.get("ctx")
