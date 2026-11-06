# PLUGINS.md - writing an objective module

An objective module answers one question: **which number do we want bigger?**
The tool hands it a candidate talent distribution plus the data context it
built for that candidate, and the module returns a number. Everything about
*what the number means* - damage models, uptime assumptions, which buff keys a
skill may use - lives in the module.

The python blocks below are executed in order by `tests/test_plugins_doc.py`
against the fixture party of `tests/data/characters.yml`, so each one runs
verbatim in that namespace (the first block is the shared setup).

## 1. The contract

```python
def objective(x, ctx) -> float:
    ...
    return expected_dps
```

* `x` is the flat, integer **level vector** the optimizer is exploring.
* `ctx` is the **tool-built** context for that candidate (section 3): the
  module never reads YAML and never maps vector positions itself (R-37, R-38).
* **Bigger is better.** The tool maximizes and never negates or normalizes the
  value it reports (R-21); if your model is smaller-is-better, negate it
  on your own side before returning.
* Returning anything non-numeric, or raising, is a user-code failure: the tool
  wraps a raise into `PluginError` and exits **4** (7's exit-code table).

```python
import os

from ssoptim.ssoptim.data import load_characters, build_party, normalize_scenario
from ssoptim.ssoptim.plugins import build_run_context, resolve_candidate
from ssoptim.ssoptim.objectives import REGISTRY

chars = load_characters([os.path.join(".", "tests", "data", "characters.yml")])
party = build_party({"main": "Char A", "sub1": "Char B", "sub2": "Char C"}, chars)
members, vars_layout = party["members"], party["vars"]
scenario = normalize_scenario({"DEF": 350, "RES": 570})
ctx = build_run_context(members, vars_layout, scenario, {"uptime_fraction": 0.6}, 0)

x = []
for slot in ("main", "sub1", "sub2"):
    for index, talent in enumerate(members[slot].talents):
        if index < 2:
            x.append(1)                                     # exactly two cores (R-04)
        elif index < 4:
            x.append(0)
        elif talent["name"] == "Sub Atk Up":
            x.append(4)
        elif talent["name"] in ("B Team Atk 1", "C Team Abs 1"):
            x.append(3)
        else:
            x.append(0)
resolve_candidate(x, ctx)
```

## 2. The vector layout (R-08)

One variable per talent, per party member, main first then `sub1`, `sub2`, and
inside a member in the order its character file declares the talent set. The
first four entries of a set are its **core** talents (level `0/1`), the rest are
sub talents (level `0..6`). A talent record carries its vector index in
`talent["var"]`, so a plugin reads levels through the record, never through an
index it computed itself.

```python
assert len(x) == 3 * 16                                 # R-03: 16 talents per member
assert vars_layout[0] == ("main", "Core Echo")           # declaration order, main first
assert vars_layout[16] == ("sub1", "B Sub Core Atk")
assert vars_layout[32] == ("sub2", "C Sub Core Atk")
assert sum(x) == 16                                     # this example spends its budget
```

## 3. The context (`ctx`) that the tool builds

Built once per run (`build_run_context`) and **filled** per candidate
(`resolve_candidate(x, ctx)`), so the hot path never re-reads data (R-37, R-38).

| Key | What it holds |
| --- | --- |
| `ctx["members"][slot]` | the slot's character: `stats`, the role-resolved `skills` blocks (`cd`/`loop_time`/`sources`), the talent set in use, `extra` (free-form keys such as `element`), and the level-resolved `talent_levels` / `talent_params` for the current `x` |
| `ctx["aggregated"]` | the summed `{key: value}` map at the current levels (R-20) - identical to `aggregate_params(x)` |
| `ctx["scenario"]` | the effective enemy profile, kernel defaults merged with the config/CLI overrides (R-36) |
| `ctx["objective_opts"]` | the free-form knobs from `--objective-opts` (R-36, R-37) |
| `ctx["verbose"]` / `ctx["log"]` | the run's `-v` count, and `pout` already bound to it (R-42) |
| `ctx["vars"]` | the `(slot, talent_name)` layout, for messages only - a plugin addresses talents through the records |

Helpers the tool provides (import from `ssoptim.ssoptim.plugins`):
`aggregate_params(x)`, `resolve_talent_params(x)`, `resolve_talent_value(param, level)`,
`member_field(member, key)`, and the damage kernel
(`calculate_damage`, `skill_percent_to_amend`, `def_amend`, `res_amend`).
One-argument calls use the **active** candidate context, which the optimizer
sets on every `resolve_candidate`; pass `ctx` explicitly when you build your
own (DESIGN.md 6's helper note).

```python
from ssoptim.ssoptim.plugins import aggregate_params, resolve_talent_params

assert aggregate_params(x) == ctx["aggregated"]              # R-38 equality
assert abs(aggregate_params(x)["Atk_multiplier"] - 0.526) < 1e-9
breakdown = resolve_talent_params(x)
assert abs(breakdown["main"]["talent_params"]["Sub Atk Up"]["Atk_multiplier"] - 0.126) < 1e-9
assert abs(breakdown["sub1"]["talent_params"]["B Team Atk 1"]["Atk_multiplier"] - 0.11) < 1e-9
```

The per-talent breakdown is what a timeline-minded plugin needs: the summed map
cannot tell you *which* talent granted a buff (R-38).

## 4. Buffer-key vocabulary (R-35)

The buffer keys below a talent are free-form (R-20); the tool only defines the
convention below so a generic objective and hand-written ones agree. Unknown
keys - character-specific mechanics - are passed through untouched.

| Key | Meaning |
| --- | --- |
| `Atk_multiplier` | fractional increase of the attacker's Atk (0.15 = +15 %) |
| `Atk_absMod` | flat Atk added after the multipliers |
| `critDmgMod` | added to the kernel's base crit damage (1.5 default) |
| `crit_rateMod` | added to the crit rate (clamped in the kernel) |
| `slot{X}Dmg` | damage multiplier for a portion of class `X` (`AutoAttack`, `Skill`, `Mark`, `Ultimate`, ...) |
| `slot{X}CritDmg` | the same class under a crit |
| `elem{E}Dmg` | elemental damage bonus, `E` one of the six elements |
| `DEF_rate_mod` / `RES_rate_mod` | debuff of the target's DEF/RES |
| `duration` / `activation` | reserved gating pair, never aggregated (R-43) |

**Ownership** (R-33/R-34): the kernel applies every argument it is given and
knows nothing about talent keys or skills. The plugin (a) picks the argument
set per damage source and (b) folds `Atk_multiplier`/`Atk_absMod` and any other
status buff into the effective `Atk` **before** the call.

```python
from ssoptim.ssoptim.damage import calculate_damage, skill_percent_to_amend
from ssoptim.ssoptim.plugins import aggregate_params

main = ctx["members"]["main"]
p = aggregate_params(x)
source = main.auto_skill["sources"][0]              # shorthand damage -> one source (R-32)
hit = source["damage"]["elemLuxDmg"]
value = calculate_damage(
    Atk=main.stats["Atk"] * (1 + p.get("Atk_multiplier", 0.0)) + p.get("Atk_absMod", 0.0),
    skillPercentAmend=skill_percent_to_amend(hit["skillPercentAmend"] * 100),
    critDmg=1.5 + p.get("critDmgMod", 0.0),
    crit_rate=0.5 + p.get("crit_rateMod", 0.0),
    slotDmg=1.0 + p.get("slotAutoAttackDmg", 0.0),   # auto-attack class only
    elementDmg=1.0 + p.get("elemLuxDmg", 0.0),
    DEF=ctx["scenario"]["DEF"],
    RES=ctx["scenario"]["RES"],
    as_int=False,
)
assert abs(value - REGISTRY["auto_attack"](x, ctx)) < 1e-9     # 53073.79031778418
```

The kernel floors to an in-game integer damage by default; `as_int=False` keeps
the expectation, which is what an objective comparing several distributions wants.
The built-in `auto_attack` additionally reads the element weakness out of
`ctx["scenario"]["res_table"]` (R-36) and passes `slotCritDmg`/`skillIntensity`
through, so a hand-written module that omits them agrees with the built-in only
while those keys stay empty.

## 5. Gating: the `duration`/`activation` pair (R-43)

A value map may carry the reserved pair `duration` (seconds, read as **level
bands**: the last declared band at or below the level) and `activation`
(exactly one of `auto_skill`/`main_skill`/`sub_skill`/`ult_skill`). The loader
validates them and keeps them **out** of the aggregated map; a generic
objective derives the share of a cycle the buff covers:

```python
def gated_uptime(talent, period):
    level = x[talent["var"]]
    if period is None or talent["duration"] is None:
        return None                                  # ungated: always applied
    return min(talent["duration"][level], period) / period

gated = [t for t in ctx["members"]["main"].talents if t["name"] == "Sub Atk Up"][0]
assert gated["activation"] == "main_skill"
assert abs(gated_uptime(gated, main.main_skill["cd"]) - 1.0) < 1e-12   # 12 s over a 12 s CD
```

Where the pair is **absent** and a plugin still needs a share, the convention is
a knob: `ctx["objective_opts"]["uptime_fraction"]`, with a `-v` warning that the
fallback was used (R-39, R-42).

## 6. Timing is data (R-30, R-31)

`cd` (active skills, from the game spec) and `loop_time` (auto skill, measured
from gameplay) are seconds **the tool validates and forwards**; turning them into
a rate is your arithmetic, not the tool's. A skill with `sources:` lets each
portion carry its own `cd`/`loop_time` and a `dot: true` flag (R-32), otherwise
it inherits the skill-level period. Without timing data, a DPS-minded module
falls back to per-hit damage and says so with `-v`.

```python
assert main.auto_skill["loop_time"] == 4.2          # seconds per auto cycle
assert main.main_skill["cd"] == 12.0
assert main.ult_skill["sources"][1]["cd"] == 6.0    # the mark portion has its own period
```

## 7. Role availability (R-40)

Roles follow the key names, not extra flags: `main` may use `auto_skill`,
`main_skill`, `ult_skill`; a support slot may use `sub_skill`, `ult_skill` and
its own `auto_skill` - never `main_skill`. Which of them feed your number is
your choice. Multi-source skills (R-32) are calculated per source with only the
buffers that apply to it, then added - e.g. a mark portion takes `slotMarkDmg`,
not `slotSkillDmg`.

## 8. The DPS recipe (6.2), as the shipped sample reads it

`plugins/simple_dps.py` is the worked external plugin: for the main slot's
`auto_skill` and `main_skill` it takes every damage source, calculates it with
its own buffers, divides by its own period and sums the rates; ultimate
portions stay out because 0.1.0 models no energy/charge, and there is no
timeline - just the assumption "the active skill is used again as soon as its
CD is up" (R-31). Loading by path is the R-22 form for an installed copy:

```python
from ssoptim.ssoptim.plugins import resolve_plugin

fn, spec = resolve_plugin("./plugins/simple_dps.py:objective", REGISTRY, None)
assert spec == "./plugins/simple_dps.py:objective"
assert abs(fn(x, ctx) - 17221.271390400085) < 1e-9
```

`resolve_plugin` accepts the three spec forms of R-22: a built-in short name
(`auto_attack`), a dotted module path (`my_objectives.iron_maiden:dps`) or a
file path (`./plugins/my_calc.py:objective`); a load failure or a missing
attribute exits **4**.

## 9. Progress output and verbosity (R-42)

Print through `pout` or the already-bound `ctx["log"]`, never bare `print`, so
`-v` warnings and `-vv` per-evaluation values mean one thing to the tool and to
your module:

```python
from ssoptim.ssoptim.ssoptim import Level

ctx["log"]("falling back to uptime_fraction", level=Level.WARNING)   # shown with -v
```

`Level.DEBUG` messages only appear at `-vv`, where the tool itself prints the
evaluated vector, the aggregated map and the objective value per candidate (R-28).

## 10. Failure handling and tuning

A plugin that raises is reported once, with exit code 4, not once per
candidate:

```python
from ssoptim.ssoptim.plugins import PluginError, objective_call

def broken(x, ctx):
    raise ValueError("the model expected a key that is not there")

try:
    objective_call(broken, x, ctx)
except PluginError as exc:
    assert exc.code == 4
```

Tuning knobs are the tool's, not the module's: keep the objective cheap (no
YAML, no I/O - the tables are already resolved), keep the box tight
(`--restrictions`, `--total-level-mode at_most`), and raise `--runs`/`--maxiter`
before suspecting the solver on heavily constrained parties (the driver
re-checks every candidate it gets and repairs it, so a tight box costs far less
search time than a loose one).

## 11. End-to-end with the bundled set

With the wheel's own character data, the shipped sample needs no config at all:

```console
> ssoptim optimize -m チトセ -s アヤメ -s テレサ -t 40 -f ./plugins/simple_dps.py:objective \
>                  --seed 7 --maxiter 60 --popsize 16 --runs 2
objective_plugin: ./plugins/simple_dps.py:objective
total_level: 40
objective: 43534.76885493751
feasible: true
party: ...
```

`tests/test_plugins_doc.py` re-runs exactly that invocation and compares the
reported `objective:` value, so the number above is the tool's, not a hand
estimate.
