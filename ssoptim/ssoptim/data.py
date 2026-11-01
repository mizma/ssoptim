#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (c) 2026 aoi mizma <aoi.mizma@path-works.net>
# SPDX-License-Identifier: MIT

"""YAML loading, schema validation, scenario block and the party model.

The loader validates and normalizes; it never interprets timing or DPS (R-31)
and never pre-buffs anything (R-34).  A schema violation raises InputError,
which cli.py maps to exit 2 (R-29); loader warnings are never fatal and go
through the injected log, the tool's pout curried with the run's verbosity
count (R-42).
"""

import glob
import os
import yaml

from .talent import SKILL_KEYS, MAX_SUB_LEVEL, TALENT_COUNT, CORE_TALENT_COUNT
from .talent import activation_key, duration_table, level_map_table, split_reserved
from .talent import talent_entry

ELEMENTS = ("Aqua", "Ignis", "Terra", "Ventus", "Lux", "Umbra")

# Scenario input surface (R-36): the enemy profile keys a plugin may read.
SCENARIO_KEYS = (
    "DEF",
    "RES",
    "res_table",
    "PEN",
    "VUL",
    "DEF_Ignore",
    "DEF_Penetrate",
    "enemyBreakStatus",
    "resilienceBreakDmg",
)
# Kernel-only neutral defaults: not defined in game, never settable (R-36, 4.2).
NOT_IN_GAME_KEYS = (
    "IGNORING",
    "generalDmg",
    "generalDmgTaken",
    "dmgPlus",
    "dmgPlusTaken",
    "finalDmg",
    "finalDmgPlus",
    "perkIntensity",
    "skillAbsAmend",
    "talentGroupPercentAmend",
    "talentGroupAbsAmend",
)
# Merged over these defaults (R-36); M2 asserts they equal the kernel defaults.
SCENARIO_DEFAULTS = {
    "DEF": 500.0,
    "RES": 750.0,
    "res_table": {},
    "PEN": 0.0,
    "VUL": 0.0,
    "DEF_Ignore": 0.0,
    "DEF_Penetrate": 0.0,
    "enemyBreakStatus": False,
    "resilienceBreakDmg": 1.5,
}

SLOTS = ("main", "sub1", "sub2")


class InputError(Exception):
    """Bad user input: unparseable YAML, invalid data, missing party/budget.

    Carries the exit code so cli.py can honour the exit-code table (R-29);
    every loader failure is exit 2, duplicate party included (R-41).
    """

    def __init__(self, message, code=2):
        Exception.__init__(self, message)
        self.message = message
        self.code = code


class Character(object):
    """One validated, normalized character definition (R-18, 4.1)."""

    def __init__(self, name, stats, skills, talent_sets, source, extra):
        self.name = name
        self.stats = stats
        self.skills = skills
        self.talent_sets = talent_sets
        self.source = source
        self.extra = extra

    def as_member(self, role):
        """Party-slot view: the talent set in use follows the slot (R-02)."""
        return Member(self, role)


class Member(object):
    """A character occupying a party slot.

    Skill blocks are attributes (main.auto_skill["sources"], README 6),
    alongside stats, the ordered talents in use, and the per-candidate
    talent_levels/talent_params filled by the ctx builder (R-38).
    """

    def __init__(self, character, role):
        self.name = character.name
        self.role = role
        self.stats = character.stats
        self.skills = character.skills
        self.source = character.source
        self.extra = character.extra
        for key in SKILL_KEYS:
            setattr(self, key, character.skills.get(key))
        set_name = "talents_main" if role == "main" else "talents_sub"
        self.talents = character.talent_sets[set_name]
        self.talent_levels = {}
        self.talent_params = {}


def load_yaml(path, what):
    """Parse a YAML file, or raise InputError (R-29 exit 2)."""
    try:
        with open(path, "r", encoding="utf-8") as fd:
            data = yaml.safe_load(fd)
    except FileNotFoundError:
        raise InputError("{0} not found: {1}".format(what, path))
    except Exception as exc:
        raise InputError("could not parse {0} {1}: {2}".format(what, path, exc))
    if not isinstance(data, dict):
        raise InputError("{0} {1} must be a mapping at the top level".format(what, path))
    return data


def character_files(path):
    """Expand a --char / data_dirs entry into YAML file paths (4.1, 4.2)."""
    if os.path.isdir(path):
        found = sorted(
            glob.glob(os.path.join(path, "*.yml")) + glob.glob(os.path.join(path, "*.yaml"))
        )
        if not found:
            raise InputError("no character YAML (*.yml / *.yaml) in directory {0}".format(path))
        return found
    if os.path.isfile(path):
        return [path]
    raise InputError("character data path does not exist: {0}".format(path))


def bundled_character_paths():
    """Bundled character set inside the package (R-22, package data).

    The wheel ships ``ssoptim/characters/*.yml`` as package data (see the
    package-data directive in pyproject.toml), so the installed copy is found
    through the package's own path and no data is fetched at runtime.
    """
    from importlib import import_module

    pkg = import_module("ssoptim")
    roots = list(pkg.__path__) if not isinstance(pkg.__path__, str) else [pkg.__path__]
    found = []
    for root in roots:
        chars = os.path.join(str(root), "characters")
        if os.path.isdir(chars):
            found.extend(glob.glob(os.path.join(chars, "*.yml")) + glob.glob(os.path.join(chars, "*.yaml")))
    return sorted(set(found))


def load_characters(paths, log=None):
    """Load and validate every character definition in search order (R-18).

    Args:
        paths (list): user data files/dirs, searched before the bundled set.
        log: the tool's warning logger (pout curried with -v, R-42).

    Returns:
        dict: {character_name: Character}; an earlier search entry wins, so
        user data shadows the bundled set.
    """
    search = list(paths) + bundled_character_paths()
    found = {}
    for path in search:
        for file_path in character_files(path):
            data = load_yaml(file_path, "character data file")
            for name, raw in data.items():
                if not isinstance(name, str):
                    raise InputError(
                        "character data file {0}: top-level key {1!r} is not a character name".format(
                            file_path, name
                        )
                    )
                if name in found:
                    if log:
                        log("character {0} redefined in {1}; first definition wins".format(name, file_path))
                    continue
                found[name] = build_character(name, raw, file_path, log)
    if not found:
        raise InputError("no character data found; set --char or data_dirs")
    return found


def build_character(name, raw, path, log=None):
    """Validate one character record against 4.1 and normalize it.

    Raises InputError on a schema violation (R-29 exit 2).
    """
    if not isinstance(raw, dict):
        raise InputError("character {0} in {1} must be a mapping".format(name, path))

    stats = raw.get("stats") or {}
    if not isinstance(stats, dict):
        raise InputError("character {0}: stats must be a map".format(name))
    for key, val in stats.items():
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            raise InputError(
                "character {0}: stats key {1!r} must be a number, got {2!r}".format(name, key, val)
            )

    skills = {}
    for key in SKILL_KEYS:
        if key in raw:
            skills[key] = normalize_skill(name, key, raw[key], log)

    talent_sets = {}
    for set_name in ("talents_main", "talents_sub"):
        entries = raw.get(set_name)
        if entries is None:
            raise InputError(
                "character {0}: missing {1}; both talent sets are required (R-02, R-03)".format(name, set_name)
            )
        talent_sets[set_name] = build_talent_set(name, set_name, entries, path)

    known = set(SKILL_KEYS) | {"stats", "talents_main", "talents_sub"}
    extra = {k: v for k, v in raw.items() if k not in known}
    return Character(name, stats, skills, talent_sets, path, extra)


def build_talent_set(name, set_name, entries, path):
    """Validate a talent set: 4 core + 12 sub, unique names (R-03, R-17)."""
    if not isinstance(entries, list):
        raise InputError("character {0}: {1} must be a list (R-03)".format(name, set_name))
    if len(entries) != TALENT_COUNT:
        raise InputError(
            "character {0}: {1} must hold exactly 4 core + 12 sub talents (R-03), got {2}".format(
                name, set_name, len(entries)
            )
        )
    talents = []
    seen = set()
    for index, entry in enumerate(entries):
        core = index < CORE_TALENT_COUNT
        try:
            talent = talent_entry(entry, index, core)
        except ValueError as exc:
            raise InputError("character {0} in {1}: {2}".format(name, path, exc))
        if talent["name"] in seen:
            raise InputError(
                "character {0}: duplicate talent_name {1!r} in {2} (R-18)".format(name, talent["name"], set_name)
            )
        seen.add(talent["name"])
        talents.append(talent)
    return talents


def normalize_skill(char_name, skill_key, block, log=None):
    """Normalize a skill block to {"cd"/"loop_time", "sources": [...]} (R-32).

    Timing is type/range-checked and passed through untouched (R-30, R-31);
    the shorthand damage map becomes a single-element sources list inheriting
    the skill-level timing, so plugins see exactly one shape (R-32).
    """
    if not isinstance(block, dict):
        raise InputError("character {0}: skill {1} must be a map".format(char_name, skill_key))

    out = {}
    for timing in ("cd", "loop_time"):
        if timing in block:
            out[timing] = checked_number(block[timing], char_name, skill_key, timing, positive=True)

    if block.get("sources") is not None:
        sources = block["sources"]
    else:
        damage = block.get("damage")
        if damage is None:
            raise InputError(
                "character {0} skill {1}: needs a damage map or a sources list (R-32)".format(char_name, skill_key)
            )
        sources = [{"damage": damage}]

    if not isinstance(sources, list):
        raise InputError("character {0} skill {1}: sources must be a list (R-32)".format(char_name, skill_key))

    normalized = []
    labels = set()
    for position, source in enumerate(sources):
        if not isinstance(source, dict):
            raise InputError("character {0} skill {1} source #{2} must be a map (R-32)".format(char_name, skill_key, position))
        label = source.get("name")
        if label is not None:
            if not isinstance(label, str) or not label.strip():
                raise InputError(
                    "character {0} skill {1}: a source name must be a non-empty label (R-32)".format(char_name, skill_key)
                )
            if label in labels:
                raise InputError(
                    "character {0} skill {1}: duplicate source name {2!r} (R-32)".format(char_name, skill_key, label)
                )
            labels.add(label)
            entry_name = label
        else:
            entry_name = "source #{0}".format(position)
        normalized.append(_normalize_source(entry_name, source, char_name, skill_key))

    out["sources"] = normalized
    return out


def _normalize_source(label, source, char_name, skill_key):
    """One damage source: own type, own timing, own buffers (R-32, R-43)."""
    entry = {}
    if "name" in source:
        entry["name"] = source["name"]
    for timing in ("cd", "loop_time"):
        if timing in source:
            entry[timing] = checked_number(source[timing], char_name, "{0} source {1}".format(skill_key, label), timing, positive=True)
    damage = source.get("damage")
    if not isinstance(damage, dict) or not damage:
        raise InputError(
            "character {0} skill {1} source {2}: needs a non-empty damage map (R-32)".format(char_name, skill_key, label)
        )
    entry["damage"] = validate_damage(char_name, skill_key, label, damage)
    if "dot" in source:
        if not isinstance(source["dot"], bool):
            raise InputError(
                "character {0} skill {1} source {2}: dot must be a boolean (R-32)".format(char_name, skill_key, label)
            )
        entry["dot"] = source["dot"]
    for buf_key in ("buf", "debuf"):
        if buf_key in source:
            entry[buf_key] = validate_buffers(char_name, skill_key, label, source[buf_key])
    return entry


def checked_number(value, owner, what, key, positive=False):
    """Numeric, optionally > 0, else InputError with a named culprit."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InputError("{0}: {1} must be a number, got {2!r}".format(owner, "{0} {1}".format(what, key), value))
    if positive and value <= 0:
        raise InputError("{0}: {1} must be > 0 (R-30, R-43), got {2!r}".format(owner, "{0} {1}".format(what, key), value))
    return float(value)


def validate_damage(char_name, skill_key, label, damage):
    """Validate a damage-class map (4.1 damage row, R-32, R-33).

    Values are {skillPercentAmend: ...} (percent-of-Atk in x100 units) or
    scenario-specific plain numbers; damage-class keys stay free-form.
    """
    out = {}
    for key, value in damage.items():
        if isinstance(value, dict):
            if "skillPercentAmend" not in value:
                raise InputError(
                    "character {0} skill {1} source {2}: damage {3!r} needs skillPercentAmend "
                    "or a plain number (4.1)".format(char_name, skill_key, label, key)
                )
            entry = dict(value)
            entry["skillPercentAmend"] = checked_number(
                value["skillPercentAmend"], char_name, "{0} source {1} damage {2!r}".format(skill_key, label, key), "skillPercentAmend"
            )
            out[key] = entry
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            out[key] = float(value)
        else:
            raise InputError(
                "character {0} skill {1} source {2}: damage {3!r} must be a map or a number (4.1)".format(
                    char_name, skill_key, label, key
                )
            )
    return out


def validate_buffers(char_name, skill_key, label, buffers):
    """Validate a skill's buf/debuf maps with the R-43 reserved pair."""
    if not isinstance(buffers, dict):
        raise InputError(
            "character {0} skill {1} source {2}: buf/debuf maps must be maps (R-43)".format(char_name, skill_key, label)
        )
    out = {}
    for key, value_map in buffers.items():
        if not isinstance(value_map, dict):
            raise InputError(
                "character {0} skill {1} source {2} buffer {3!r} must map levels to values (R-43)".format(
                    char_name, skill_key, label, key
                )
            )
        try:
            anchors, _reserved = split_reserved(value_map)
            table = level_map_table(anchors, MAX_SUB_LEVEL)
            duration = duration_table(value_map["duration"], MAX_SUB_LEVEL) if "duration" in value_map else None
            gated = activation_key(value_map["activation"]) if "activation" in value_map else None
        except ValueError as exc:
            raise InputError(
                "character {0} skill {1} source {2} buffer {3!r}: {4}".format(char_name, skill_key, label, key, exc)
            )
        out[key] = {"params": table, "duration": duration, "activation": gated}
    return out


def build_party(party, characters, log=None):
    """Resolve the party slots into Member objects (R-01, R-02, R-40, R-41).

    Returns {"members": {slot: Member}, "vars": [(slot, talent_name), ...]} in
    R-08 order; every talent record gains its "var" index into the flat vector.
    """
    if not isinstance(party, dict):
        raise InputError("party must be a mapping with main/sub1/sub2 (R-01)")
    names = {}
    for slot in SLOTS:
        name = party.get(slot)
        if not isinstance(name, str) or not name:
            raise InputError("party slot {0} is missing (R-01: one main + two support)".format(slot))
        names[slot] = name
    if len(set(names.values())) != len(SLOTS):
        raise InputError(
            "party must consist of three distinct characters (R-41): "
            + ", ".join("{0}={1}".format(slot, names[slot]) for slot in SLOTS)
        )

    members = {}
    layout = []
    for slot in SLOTS:  # main first, then sub1, sub2 (R-08)
        character = characters.get(names[slot])
        if character is None:
            raise InputError(
                "party character {0!r} not found; known characters: {1}".format(
                    names[slot], ", ".join(sorted(characters))
                )
            )
        role = "main" if slot == "main" else "sub"
        member = character.as_member(role)
        for talent in member.talents:
            talent["var"] = len(layout)
            layout.append((slot, talent["name"]))
        if role == "sub" and member.sub_skill is None and log:
            log("character {0} sits in a support slot but declares no sub_skill (R-40)".format(member.name))
        members[slot] = member
    return {"members": members, "vars": layout}


def normalize_scenario(user, defaults=None):
    """Merge the scenario block over the kernel defaults (R-36)."""
    merged = dict(defaults if defaults is not None else SCENARIO_DEFAULTS)
    if user is None:
        return merged
    if not isinstance(user, dict):
        raise InputError("scenario must be a mapping (R-36)")
    for key, value in user.items():
        if key in NOT_IN_GAME_KEYS:
            raise InputError(
                "scenario key {0!r} is not exposed as input: it is not defined in game "
                "and stays at its kernel default (4.2)".format(key)
            )
        if key not in SCENARIO_KEYS:
            raise InputError("unknown scenario key {0!r}; allowed: {1}".format(key, ", ".join(SCENARIO_KEYS)))
        if key == "res_table":
            merged[key] = validate_res_table(value)
        elif key == "enemyBreakStatus":
            if not isinstance(value, bool):
                raise InputError("scenario key enemyBreakStatus must be a boolean (R-36)")
            merged[key] = value
        else:
            merged[key] = checked_number(value, "scenario", key.split(".")[0], key.split(".")[-1])
    return merged


def validate_res_table(table):
    """Per-element RES weakness table: element names or "default" (R-36)."""
    if not isinstance(table, dict):
        raise InputError("scenario res_table must be a mapping (R-36)")
    out = {}
    for key, value in table.items():
        if key != "default" and key not in ELEMENTS:
            raise InputError(
                "res_table key {0!r} must be an element of {1} or 'default' (R-36)".format(key, ELEMENTS)
            )
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise InputError("res_table value {0!r} must be a number (R-36)".format(value))
        out[key] = float(value)
    return out


def scenario_key_override(scenario, pairs):
    """Apply repeatable --scenario KEY=VAL overrides (R-36, 7)."""
    for pair in pairs:
        key, _sep, raw = str(pair).partition("=")
        key = key.strip()
        if not _sep:
            raise InputError("scenario override must be KEY=VALUE, got {0!r}".format(pair))
        if key not in SCENARIO_KEYS:
            raise InputError("unknown scenario key {0!r}; allowed: {1}".format(key, ", ".join(SCENARIO_KEYS)))
        scenario[key] = coerce_scalar(raw)
    return scenario


def coerce_scalar(raw):
    """YAML-parse a CLI value so --scenario DEF=350 and true/false work."""
    try:
        return yaml.safe_load(raw)
    except Exception:
        return raw


def load_run_config(path):
    """Read the run config (4.2); CLI precedence itself is applied in cli.py."""
    data = load_yaml(path, "run configuration file")
    return data
