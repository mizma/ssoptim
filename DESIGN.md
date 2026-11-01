# SSOptim — Design Specification

Status: **pre-implementation design spec** (version 0.1.0 T.B.D.)
Self-contained: this document restates the game-spec facts it depends on (§1.1) · damage reference: [DamageCalculationParameters.md](DamageCalculationParameters.md), [stella_sora_damage.py](stella_sora_damage.py) (scratch reference, vendored into `ssoptim/ssoptim/damage.py` and deleted at M2)
Project structure basis: [click-cutter](https://github.com/koma75/click-cutter) (Click CLI cookiecutter template, `cli_type = simple` → a one-command group in 0.1.0 per §11 item 23, `use_config_yaml = Yes`)

This document is the streamlined, decision-complete plan for building `ssoptim`.
It restates the goals as testable requirements, fixes the data/plugin/CLI contracts,
and defines the source tree. §1.1 restates the game model those requirements assume, so
nothing here depends on any other document for background. No implementation exists yet;
§9 lists the order in which it will be built, and §12 records the decisions on the
previously open questions.

---

## 1. Purpose

`ssoptim` is a console tool that, for a **fixed party composition** in Stella Sora
(1 main + 2 support) and a **fixed budget of talent levels**, searches the space of
talent-level assignments and reports the assignment that maximizes a **pluggable
objective function** (typically expected damage / DPS of the main character).

Everything that is *not* the talent level distribution (character stats, skills, sigils,
enemy DEF/RES, rotation assumptions) is treated as constant input supplied by data files
and by the objective-function plugin.

### 1.1 Game-model background (restated so this document stands alone)

The game facts below are the only external inputs this design relies on; they are restated
here instead of delegated to any other document, so §3's requirements can be read on their own.

* **Party:** one main character and two support characters. Any character may occupy either
  kind of slot, and each character keeps two completely separate talent sets — the set in use
  follows the slot, and a character levels its main-role talents only while it is the main
  (R-01, R-02, R-40).
* **Talent structure:** per set, exactly 4 core talents (no level system: value 0/1, and every
  member must select exactly 2 of the 4 — a third is impossible and the choice cannot be skipped)
  plus 12 sub talents at integer levels 0–6, where 0 means not owned (R-03..R-05, R-17).
* **How the game grants levels:** each pick offers 3 randomly chosen talents of that member and
  the player takes one; the main member's talents appear in the selection pool more often, and
  the number of picks available varies from build to build (~40–65+). That is why the level
  budget and the per-member totals are *user inputs* (R-07, R-13, R-14), why the pool bias is
  left entirely to the user (Q-3), and why simulating the random pulls is a non-goal (§2).
* **Damage values:** produced by the damage formula documented in
  [DamageCalculationParameters.md](DamageCalculationParameters.md) and implemented by
  [stella_sora_damage.py](stella_sora_damage.py), which the tool vendors as its kernel (R-24).
  The formula's inputs come from base stats, skill values and talent modifiers; individual
  talent values may be gated on conditions (cooldown window, "after skill activation",
  "target has mark") — the convention for those is §3 R-39, with the buff's duration and
  the skill that grants it carried in the data itself as §3 R-43.
* **Scaling quirks:** some characters compute damage from HP or other base stats, so the full
  character record must reach the objective module (R-37).

## 2. Scope

**In scope**

- Talent-level optimization for a named party and a level budget.
- Data-driven character/skill/talent definitions (YAML).
- Skill timing data (active-skill **cooldowns**, auto-skill **loop time**) and **per-damage-source**
  types/ timings, so a generic calculator can approximate DPS (R-30..R-32).
- Pluggable objective functions (built-in + user-supplied files/modules, no rebuild).
- Enemy/scenario profile as user input (`scenario:` block, `--objective-opts` plugin knobs).
- A tool-provided data context handed to the plugin (party characters, resolved talent
  levels per talent, aggregated buffers, scenario) — R-37/R-38.
- Constraint handling: core-talent selection, per-character totals, per-talent bounds.
- Machine-readable YAML result + human-readable console report.

**Out of scope** (explicit non-goals)

- Choosing *which* characters/talents to pull during a real build (random-pull simulation).
- Gear, sigils, duos, or anything other than the damage-formula parameters.
- A GUI/TUI, save-file import, or live game scraping.
- Accurate DPS modelling for every character: correctness of the objective is the
  plugin author's responsibility (see R-21/R-33/R-34).
- A shared rotation/timeline model: cooldowns and loop times are *data*, and how they
  turn into DPS is the objective function's/plugin's decision (R-31); 0.1.0 has no timeline
  simulation and ships no timeline helper (only the data of R-30/R-38/R-43).
- A condition-expression language in the data format: condition-gated talent values
  (cooldown window, "after skill activation", "target has mark") are a documented
  convention resolved by the plugin (R-39), with the gating facts themselves in the data
  as the reserved `duration`/`activation` keys (R-43); mark/break state itself is not modelled.
- An energy/charge/ultimate-availability model: how often an ultimate is available is not
  simulated, so ult portions enter the objective per hit or at a plugin-assumed rate (see §6.2).
  Unrelated to the reserved `activation` key of R-43, which only names the skill whose use
  grants a buff.

## 3. Streamlined requirements

Requirement IDs are used throughout the rest of this document and will be cited in code,
tests, and `CHANGES.md` entries.

### Game model

| ID | Requirement |
| --- | --- |
| R-01 | A party is exactly one `main` character plus two support characters `sub1`, `sub2`. |
| R-02 | A character carries two independent talent sets: `talents_main` (role = main) and `talents_sub` (role = support). The set used depends only on the party slot. |
| R-03 | Each talent set has exactly **4 core** talents and **12 sub** talents. |
| R-04 | Core talents have no level system: value is 0/1, and **every party member must select exactly 2 core talents**. The constraint is always enforced by the tool. |
| R-05 | Sub talents have integer levels **0–6** (0 = not owned). |
| R-06 | Skills are fixed data for a given party; only talent levels vary. Skill values enter the objective as constants, never as optimization variables. |
| R-07 | The level budget is user input; realistic builds are ~40–65+ total levels. |

### Optimization problem

| ID | Requirement |
| --- | --- |
| R-08 | Decision variables are the talent levels of all three party members, flattened into one integer vector: main character's talents first, then `sub1`, then `sub2`, each in YAML declaration order. |
| R-09 | The objective is an opaque, possibly non-linear scalar function `f(x)` (damage/DPS); the tool maximizes it. No gradient/convexity assumption. |
| R-10 | Solver default: `scipy.optimize.differential_evolution` with `integrality=True`, integer bounds and integer-coefficient linear constraints. |
| R-11 | Every result must satisfy all constraints (bounds, core=2, budget, per-character min/max). Infeasible input must be reported as an error, not silently relaxed. |
| R-12 | The search space is 16 variables/character (48/party); runtime for one run must stay in the seconds-to-minutes range for the default objective. |

### Constraints (user-supplied)

| ID | Requirement |
| --- | --- |
| R-13 | `total_level` (budget) is mandatory, default semantic = **exact** sum; an explicit `total_level_mode: at_most` allows leaving levels unused. |
| R-14 | Per-character `min`/`max` on the character's **total** talent levels (e.g. `main: {min: 30}`). |
| R-15 | Per-talent `min`/`max` bounds, addressable by talent name (positional form also accepted, aligned to YAML declaration order). |
| R-16 | The user may pin core-talent choices; this is expressed as `min: 1` on the two selected core talents and is implied by R-04 to force the other two to 0. |
| R-17 | Core talents are always the first four entries of a talent set; the loader validates this and generates the `sum(core) == 2` constraint from data, not from user config. |

### Data / plugin contract

| ID | Requirement |
| --- | --- |
| R-18 | Character definitions are YAML files keyed by character name (`stats`, `auto_skill`, `main_skill`, `sub_skill`, `ult_skill`, `talents_main`, `talents_sub`). |
| R-19 | A talent entry maps parameter key → `{level: value}`. Only levels that change need listing; **intermediate levels are interpolated evenly** between the two declared anchors (e.g. keys 1 and 6 imply a constant step for 2–5; level 0 contributes nothing). A map with a single anchor keeps the same rule against the implicit `(0, 0)` origin, and **levels above the last declared anchor keep that anchor's value** (no extrapolation) — the rule is fixed here so sparse authoring stays deterministic (§11 item 22). |
| R-20 | Talent parameter keys are free-form strings; they are *summed* across all owned talents at their chosen levels, including character-specific keys unknown to the damage kernel. |
| R-21 | An objective plugin is a callable `f(x, ctx) -> float`. `x` is the SciPy-style flat level vector (R-08); `ctx` is the **tool-provided** data context of R-37 (party characters with full stats/skills/talents, resolved levels and buffers, scenario). The plugin author may still bind extra constants by closure/partial, but must not have to load character data itself. |
| R-22 | Plugin references accept three forms: built-in short name (`auto_attack`), dotted module path (`pkg.mod:func`), and file path (`./plugins/my_calc.py:func`). Loading must work at runtime against a `pipx`/`uv tool install`ed copy — no package rebuild. |
| R-23 | A built-in default plugin must exist that computes **auto-attack skill damage** from the damage kernel; it is the reference implementation and the objective of the doc examples. |
| R-24 | The damage kernel (DEF/RES/PEN/VUL/erAmend/defAmend, crit expectation, `is_dot`) is shared library code, unit-converted from YAML conventions via `skill_percent_to_amend`. |

### Skill timing & damage sources (plugin-facing data)

| ID | Requirement |
| --- | --- |
| R-30 | Main and sub **active skills** (`main_skill`, `sub_skill`) carry a **cooldown** `cd` in seconds, taken from the game's character spec. Every authored character's **auto skill** carries a **loop time** `loop_time` in seconds, measured from gameplay/video analysis of one full auto-attack cycle — authored for all characters, not only the one in the `main` slot, because some characters act from the sub slot with their auto skill (R-40); built-in DPS objectives use the main slot's value. |
| R-31 | Timing values are informational to the tool: it type/range-checks them and passes them through. Which period a plugin uses, and how many times a skill fires inside a window, is entirely the objective function's/plugin's decision — a plugin may follow the "use immediately when CD is up" default or model its own rotation. |
| R-32 | A skill may declare **multiple damage sources** (e.g. a base elem hit plus a separate mark portion). Each source carries its own damage type (element and/or slot class), may carry its own `cd`/`loop_time`, and may set `dot` (→ kernel `is_dot`), so a generic calculator evaluates each source as a separate `calculate_damage` call with only that source's buffers and sums the results. |
| R-33 | The damage kernel is **apply-everything**: `calculate_damage` consumes every argument it is handed and applies no policy of its own about which keys belong to which skill or damage source. Choosing the argument set — including dropping irrelevant talent keys — is the objective function's/plugin's responsibility. |
| R-34 | Buffs are applied **before** the kernel call, by the objective function/plugin: it folds the relevant Atk buffs and any other status buffs into the main party member's effective status (and the relevant enemy-side debuffs into the enemy parameters) and hands those numbers to the kernel. The tool supplies only raw `stats` and the aggregated key map (R-20); it never pre-buffs anything. |

### Plugin context, scenario & key vocabulary

| ID | Requirement |
| --- | --- |
| R-35 | A **documented buffer-key vocabulary** maps talent parameter keys to damage-kernel arguments: `Atk_absMod` → additive Atk, `Atk_multiplier` → multiplicative Atk buff, `critDmgMod` → `critDmg`, `crit_rateMod` → `crit_rate`, `skillIntensity`, `slot{AutoAttack,Skill,Ultimate,Other,Mark,Projectile,Minion}Dmg` → `slotDmg` of that source, `slot{…}CritDmg` → `slotCritDmg`, `elem{Aqua,Ignis,Terra,Ventus,Lux,Umbra}Dmg` → `elementDmg`, `DEF_rate_mod`/`RES_rate_mod` → enemy debuffs. The vocabulary is a **convention**, never enforced (R-20 keeps keys free-form), but it is the single source of truth in `PLUGINS.md` and the built-ins — because R-33 means the kernel will not map keys for the plugin. Keys outside the vocabulary are character-specific. |
| R-36 | The enemy/scenario profile is user input: a `scenario:` block in the run config with `DEF`, `RES`, an optional per-element `res_table` (weakness/neutral/resistance values), `PEN`, `VUL`, `DEF_Ignore`, `DEF_Penetrate`, `enemyBreakStatus`, `resilienceBreakDmg`, merged over the kernel's defaults and handed to the plugin as `ctx["scenario"]`. Free-form `objective_opts:` (CLI `--objective-opts KEY=VAL`) carries plugin-specific constants into `ctx["objective_opts"]`. `IGNORING`, `generalDmg`, `dmgPlus`, `finalDmg`, … stay kernel-only neutral defaults because they are not defined in game. Exactly **one** scenario per invocation in 0.1.0 (Q-4 defers multi-scenario). |
| R-37 | The tool provides the **data context** to the plugin: `f(x, ctx)`. `ctx` carries, per party slot (`main`, `sub1`, `sub2`), the full character object (`stats` incl. `HP`/`DEF` for HP-scaled mechanics, all skill blocks with `cd`/`loop_time`/`sources`, the talent set in use), the merged scenario, plugin objective options, and the buffer maps of R-38. All three members' detail must be present so plugins can model support-side contributions and sub-slot auto-skill cases (R-40). |
| R-38 | Per evaluated candidate the tool builds `ctx` with the level resolution already done: `ctx["members"][slot].talent_levels` (name-keyed, in R-08 order), `ctx["members"][slot].talent_params` (**per-talent** breakdown `talent → {key: value at that level}` using the R-19 interpolation tables), and `ctx["aggregated"]` (the summed map, identical to `aggregate_params(x)`). Helper `resolve_talent_params(x, ctx)` returns the same data. The **per-talent breakdown is mandatory**, not just the sum: talent activation is gated on skill activation, so timeline-style plugins (simple approximation or real simulation, owned by the plugin per R-31) must attribute a buff to the talent that granted it. No YAML parsing per evaluation (§5 invariant). |
| R-39 | Talent values may be **condition-gated** in the game (cooldown window, "after skill activation", "target has mark"). 0.1.0 has no condition-expression language in the data format: the *meaning* of an aggregated value — per-application amount, uptime fraction, or plain count — is a documented convention declared in the character's/plugin's docs and applied by the plugin (e.g. a value multiplied by an assumed uptime). Mark and break state are not modelled by the tool. |
| R-40 | Role semantics of the existing skill keys (no extra keys): the `main` slot uses `auto_skill` + `main_skill` + `ult_skill`; `sub1`/`sub2` use `sub_skill` + `ult_skill` and **never `main_skill`**. The special case is `auto_skill`: some characters act from the sub slot with their auto skill (currently the only such role exception), which is plugin-side logic; hence `loop_time` is authored for every character's `auto_skill` (R-30). |
| R-41 | A party must consist of three **distinct** characters; the same character name in two slots is a loader error (exit 2). |
| R-42 | The `-v/--verbose` **count** follows the same precedence as every other option (CLI > config) and is handed to plugins inside `ctx`: `ctx["verbose"]` (the integer count) and `ctx["log"]` — that `pout` **curried** with the run's verbosity already bound. The tool keeps the click-cutter template's `pout(msg, Verbose, level, newline)` (+ `Level` IntEnum: DEBUG shown at `Verbose >= 2` on stdout, WARNING at `>= 1` on stderr, INFO/ERROR/CRITICAL always) as the single definition of verbosity, and plugin-side progress output must go through `pout`/`ctx["log"]` so it follows the user's `-v`: `Level.WARNING` for "data missing, falling back" notices and `Level.DEBUG` for per-evaluation values — the R-28 levels, one definition shared by tool and plugin. |
| R-43 | Buff/debuff values carry **`duration`** and **`activation`** as reserved keys inside the same map as the level keys: `Atk_multiplier: { 1: 0.15, 6: 0.7, duration: { 1: 10, 4: 12 }, activation: main_skill }`. `duration` is in **seconds**, sparse, and read as **level bands** — the last declared anchor at or below the level applies, so `{ 1: 10, 4: 12 }` is 10 s for levels 1–3 and 12 s for 4–6 (a band, not an even step: §11 item 24); `activation` is strictly one of the four skill keys (`auto_skill`/`main_skill`/`sub_skill`/`ult_skill`, R-40) and names the skill whose use grants the buff. Skills declare the same pair on their `buf`/`debuf` maps inside a `sources[]` entry (R-32). The loader validates the pair and **excludes both keys from aggregation** (R-20, R-35): they are convention metadata, never damage-formula keys. |
| R-44 | The bundled reference character set (and the data behind the sample objective) is authored from **user-extracted** wiki data taken from the Stella Sora wiki pages forチトセ, アヤメ, テレサ; the extract is kept **in the repo workspace only as authoring source** (`wiki_data/`, git-ignored — see the §8/§9/§11 amendment below), so the tool and the build never fetch from the wiki and the wheel's provenance is the authored YAML itself. |

### CLI / IO

| ID | Requirement |
| --- | --- |
| R-25 | Input is a YAML config file **plus** CLI options; CLI options always take precedence. |
| R-26 | Required inputs: party, objective plugin, `total_level`. Optional: restrictions, character data sources, output path, solver knobs. |
| R-27 | Output is YAML (talent list per character with chosen levels) **plus** the objective value returned by the plugin. |
| R-28 | `-v/--verbose` (count) additionally prints the aggregated parameter dictionary and the objective value per evaluated candidate. |
| R-29 | Errors are non-zero exits with a message on stderr (exit-code table in §7). |

## 4. Data schemas

### 4.1 Character file (`characters/<name>.yml`)

One file per character (or several characters per file, top-level key = character name).

| Key | Type | Notes |
| --- | --- | --- |
| `stats` | map | `Atk`, `HP`, `DEF`, … plain numbers; also readable by plugins that use HP-based scaling. |
| `auto_skill` / `main_skill` / `sub_skill` / `ult_skill` | map (single source) **or** list (multi-source) | Either a damage-class map (below) plus skill-level timing, or — when parts of the skill must be computed separately — a `sources:` list (R-32). Both forms are accepted; when `sources:` is present it is authoritative. |
| `damage` | map of damage-class → map | Damage classes are `elem{Aqua,Ignis,Terra,Ventus,Lux,Umbra}Dmg`, `slot{AutoAttack,Skill,Ultimate,Other,Mark,Projectile,Minion}Dmg`, plus free-form character-specific keys. Values are `{skillPercentAmend: …}` or scenario-specific numbers. |
| `cd` | number (seconds) | Active-skill cooldown from the game's character spec (R-30); validated as a positive number but never interpreted by the tool (R-31). |
| `loop_time` | number (seconds) | Auto skill: measured duration of one full auto-attack cycle (video analysis), **authored for every character** — some characters act from the sub slot with their auto skill (R-30, R-40); built-in DPS objectives read only the `main` slot's value. |
| `sources[]` | list of maps | One entry per damage source: optional `name` label, a `damage` map in the same damage-class notation, and that source's own timing (`cd` or `loop_time`; defaults to the skill-level value when omitted) plus optional `dot: true` (→ `is_dot`), and optional `buf`/`debuf` maps (talent key → value) that use the R-43 `duration`/`activation` pair — `activation` names the skill whose use applies them (R-32, R-43). Separate sources are calculated separately with only their own buffers (R-32, §6). |
| `skillPercentAmend` | number | Percent-of-Atk in **×100 percent** units, i.e. `11.30` ⇒ 1130 % of Atk. Kernel conversion: `skill_percent_to_amend(v * 100)`. |
| `talents_main` / `talents_sub` | list | Index 0–3 = core (`core_talent: true`), index 4–15 = sub. Order defines the variable order of that character (R-08, R-17). |
| `<param_key>` | map | `level: value`; sparse on the other side. Missing intermediate levels interpolated (R-19). The reserved keys `duration`/`activation` may share the map (R-43) and are **never** parameters. |
| `duration` (reserved) | number **or** sparse map (seconds) | Buff/debuff uptime of the value at that level: `{ 1: 10, 4: 12 }` = 10 s for levels 1–3, 12 s for 4–6, i.e. the **last declared anchor at or below the level** applies (level bands, not an even step — see §11 item 24); a bare number means the same duration at every level (R-43). |
| `activation` (reserved) | `auto_skill` \| `main_skill` \| `sub_skill` \| `ult_skill` | Which skill's use grants the buff — strictly one of the four skill keys of R-40, no other tags (R-43). |

Abbreviated example (documentation sample, not shipped source):

```yaml
<charname>:
  stats: { Atk: 6966, HP: 94662, DEF: 0 }
  auto_skill:
    loop_time: 4.20                          # seconds per full auto-attack cycle (measured)
    damage:
      elemLuxDmg: { skillPercentAmend: 11.30 }   # 1130 % of Atk
  main_skill:
    cd: 12.0                               # active-skill cooldown (game spec)
    sources:                               # separate damage sources: own type, own timing
      - name: hit                          #   inherits cd: 12.0 from the skill level
        damage: { elemLuxDmg: { skillPercentAmend: 8.90 } }
      - name: mark
        cd: 6.0                            # this portion re-applies on its own period
        damage: { slotMarkDmg: { skillPercentAmend: 1.22 } }
        debuf: { DEF_rate_mod: { 1: 0.10, duration: 6, activation: main_skill } }
                                             # skill-applied debuff: same reserved-key rule (R-43)
  sub_skill:
    cd: 10.0                               # support-role active skill
    damage:
      elemLuxDmg: { skillPercentAmend: 5.00 }
  ult_skill:
    damage:
      elemLuxDmg: { skillPercentAmend: 20.00 }
  talents_main:
    - talent_name: "Talent A"
      core_talent: true
      Atk_multiplier: { 1: 0.15 }              # +15 % at level 1 (core: 0/1 only)
    - talent_name: "Talent E"
      core_talent: false
      Atk_multiplier: { 1: 0.045, 6: 0.18, duration: { 1: 10, 4: 12 }, activation: main_skill }
                                               # 2–5 interpolated evenly; buff lasts 10 s at levels 1–3,
                                               # 12 s at 4–6, granted by main_skill (R-43)
      slotSkillDmg: { 6: 0.10 }
  talents_sub:
    # same shape; used when the character sits in sub1/sub2
```

Validation rules the loader must enforce: 4 core + 12 sub per set, unique `talent_name`,
level keys ⊂ 0–6 (core ⊂ 0–1) **after the reserved `duration`/`activation` keys are stripped
off the map** (R-43), numeric values, unknown-key tolerance (never fatal), and
`cd`/`loop_time` present as numbers > 0 when given (absent is legal — DPS-minded plugins
then fall back to per-hit damage and say so with `-v`); when present, `duration` must be
> 0 (bare number or sparse level map) and `activation` must be one of the four skill keys.
A `sources[]` entry must have a non-empty `damage` map, may carry `buf`/`debuf` maps with
the same pair, and needs a label-unique `name` when named (R-30, R-32, R-43).

Interpolation of a sparse level map (R-19) is fully pinned: the origin `(0, 0)` counts as an
anchor, values between two anchors change in an even step, and values **after the last anchor
repeat it** — so `{6: 0.10}` means 0.0167 at level 1 rising to 0.10 at level 6 and 0.10 above,
and `{1: 0.15}` means 0.15 at every level at or above 1. A `duration` map is the exception: it
reads as **level bands** (the last declared anchor at or below the level), because the game states
one uptime per level band and the pair's own worked example (`10 s` for levels 1–3, `12 s` for
4–6) is not reproducible by an even step (§11 item 24).

Role semantics of the four skill keys are fixed data conventions, **not extra keys** (R-40):
the `main` slot may use `auto_skill` + `main_skill` + `ult_skill`; `sub1`/`sub2` may use
`sub_skill` + `ult_skill` and their own `auto_skill` (never `main_skill`). Which of them
actually contributes to the objective — including sub-slot auto-skill cases and characters
that act from support — is the plugin's decision (R-37 requires the full data of all three
members to be available to it). The loader warns (never fails) when a character in a support
slot has no `sub_skill`.

Loader normalization (R-32): the shorthand `damage:` map is equivalent to a **single-element**
`sources[]` list inheriting the skill-level `cd`/`loop_time`, so plugins always see one source
list shape and never special-case the two spellings.

### 4.2 Party / run config (`ssoptim.yml`, `--config`)

```yaml
party:
  main: "<character name>"
  sub1: "<character name>"
  sub2: "<character name>"
data_dirs: [ "./characters" ]      # searched before the bundled set
objective: auto_attack             # plugin spec (R-22)
total_level: 65
total_level_mode: exact            # exact | at_most
scenario:                          # enemy profile (R-36); merged over kernel defaults
  DEF: 500
  RES: 750
  res_table: { Aqua: 250, Lux: 250, default: 750 }  # optional per-element RES
  PEN: 0
  VUL: 0
  DEF_Ignore: 0
  DEF_Penetrate: 0
  enemyBreakStatus: false
  resilienceBreakDmg: 1.5
objective_opts:                  # free-form plugin-specific constants (R-36)
  uptime_fraction: 0.6             # e.g. how often a condition-gated buff is assumed up
restrictions:
  main:
    min: 30                        # character-level total lower bound
    max: 40                        # optional upper bound
    talent_levels:                 # keyed (positional list also accepted)
      - { name: "Talent A", min: 1 }        # pins a core talent
      - { name: "Talent B", min: 1 }
      - { name: "Talent E", min: 2, max: 4 }
  sub1: { min: 10 }
  sub2: { min: 10, max: 20 }
solver:
  maxiter: 300
  popsize: 24
  seed: 1
  runs: 3                          # restarts, keep best feasible
  polish: true
```

Notes:

* `scenario:` is the single enemy profile of a 0.1.0 run (R-36): unspecified keys keep the
  damage-kernel defaults, and a per-element `res_table` (keys in the same element notation as
  `elem…Dmg`, plus a `default`) lets a plugin choose the RES for a source's element. Keys that
  are not defined in game (`IGNORING`, `generalDmg`, `generalDmgTaken`, `dmgPlus`,
  `dmgPlusTaken`, `finalDmg`, `finalDmgPlus`, `perkIntensity`, `talentGroup*`, `skillAbsAmend`)
  are **not** exposed as scenario input and stay at their neutral kernel defaults.
* `objective_opts:` is free-form and plugin-specific; the CLI form `--objective-opts KEY=VAL` merges
  over it (precedence: CLI > config). It arrives in `ctx["objective_opts"]` (R-37) and is the
  documented place where a plugin declares the semantics of condition-gated values (R-39),
  e.g. an assumed uptime fraction.
* The three party characters must be **distinct** (R-41); a repeated character name is an
  input error (exit 2).

### 4.3 Result file (`--out`, default stdout)

```yaml
objective_plugin: auto_attack
total_level: 65
objective: 1234567          # value returned by the plugin for this distribution
feasible: true
party:
  main:
    core_talents: [ "Talent A", "Talent B" ]
    talent_levels:
      "Talent A": 1
      "Talent E": 4
      # … every talent of the set, with its level
  sub1: { … }
  sub2: { … }
```

`objective_plugin:` names the plugin spec that was run; `objective:` is the value that plugin
returned for the winning distribution. `--show-params` (implied by `-vv`) appends `aggregated_params:` —
the summed key/value map the plugin received — plus the effective `scenario:` values, so plugin
authors can diff both their talent-buffer assumptions and their enemy-profile assumptions against
reality (R-36).

## 5. Optimization model

Variables (per party member, from YAML order):

```
x[char][i]  core i∈0..3 : bounds [0,1]
            sub  i∈4..15: bounds [0,6] → tightened by user min/max (bounds, not constraints)
```

Constraints, all generated (never hand-written), integer coefficients:

| Source | Constraint |
| --- | --- |
| R-04/R-17 | `Σ core[char][0..3] == 2` for each of main, sub1, sub2 |
| R-13 | `Σ all == total_level` (or `<=` when `at_most`) |
| R-14 | `min_char <= Σ char <= max_char` |
| R-15 | expressed as variable bounds |
| R-16 | core pinning via `min: 1` on the pinned talents |
| R-41 | party distinctness, checked at load time (no levels involved) |

Solver driver:

- `differential_evolution(bounds, constraints=..., integrality=True, polish=True, maxiter, popsize, seed, init='sobol')`.
- `runs` restarts with different seeds; keep the best **feasible** result (tolerance 1e-6).
- Repair/verify pass after solving: round to integers, re-check every constraint, and if
  infeasible fall back to a greedy fill (start from user mins, add levels while improving) —
  this doubles as a testable reference solver and as the safety net for SciPy's constrained-integrality caveats.
- Objective call must be cheap (no YAML parsing per evaluation): the plugin receives
  pre-resolved level→value tables (R-19 interpolation is precomputed once, per talent,
  into a list indexed by level) through the `ctx` of R-37/R-38, already resolved for the
  current `x` — the plugin never maps `x` positions to talents itself.
- Maximization: driver maximizes directly; plugins return larger = better (stated
  explicitly in `PLUGINS.md`, R-21/R-27).

## 6. Plugin contract

```python
# plugin signature (author's side; shown for contract definition only)
def objective(x, ctx) -> float:      # x: flat integer level vector, order per R-08
    ...                              # ctx: tool-built data context for this x (R-37/R-38)
```

Resolution rules (`plugins.py`):

| Spec form | Resolution |
| --- | --- |
| `auto_attack`, … | registry in `ssoptim/ssoptim/objectives/` |
| `pkg.mod:func` | `importlib.import_module` |
| `./path/file.py:func` | `importlib.import_module` via `spec_from_file_location` |

Built-ins are importable submodules so the built-in set can grow without touching
`pyproject.toml`; user plugins live outside the package (repo `plugins/` dir is the
convention) and are loaded by path — satisfying R-22 for a `pipx`-installed tool.

Shared helpers every plugin should use (all read the tool-built `ctx`; nothing re-parses YAML):

- `resolve_talent_params(x, ctx)` → the level-resolved view of the current candidate:
  per member slot, name-keyed levels plus the **per-talent** `talent → {key: value}`
  breakdown (R-38) — the breakdown is what timeline-style plugins need, to attribute a
  buff to the talent that granted it (the summed map alone cannot say that).
- `aggregate_params(x)` → `{key: Σ value}` over all owned talents at the chosen levels,
  including character-specific keys (R-20); identical to `ctx["aggregated"]`.
- `resolve_talent_value(talent, level)` → interpolated value (R-19).
- `ctx["members"][slot]` for `main`, `sub1`, `sub2` → the full character object: `stats`
  (incl. `HP`/`DEF` for HP-scaled mechanics), skill blocks with `cd`/`loop_time`/`sources`,
  and the talent set in use (R-37; role availability per R-40).
- `ctx["scenario"]` / `ctx["objective_opts"]` → merged enemy profile and plugin knobs (R-36).
- `ctx["verbose"]` / `ctx["log"]` → the run's verbosity count, and the template's `pout`
  curried with it already bound: `ctx["log"](msg, level=Level.WARNING)` (R-42). Plugin-side
  progress output must use `pout` (importable from `ssoptim.ssoptim.ssoptim`, also re-exported
  by `plugins.py`) or `ctx["log"]` with the same `Level` IntEnum, so `-v`/`-vv` mean the same
  thing to the tool and to the plugin.
- `damage.calculate_damage(...)` (R-24) for the damage-kernel terms; plugins own skill
  selection, multi-hit counts, cooldown windows, and any character-specific simulation
  (e.g. turning a character-specific key into per-interval applications — R-39 convention).

### 6.1 Kernel / buffer ownership (who applies what)

The split of responsibility is fixed and must be mirrored in `PLUGINS.md`:

- **The kernel applies everything it is given** (R-33). It is a faithful transcription of
  the game formula and has no notion of "this hit is not a mark, so drop `slotMarkDmg`".
  If a key is passed, it is applied.
- **Selecting the argument set is the objective function's/plugin's job** (R-32/R-33): for
  each damage source, pick only the talent keys appropriate to that source's damage type
  and condition (element class, slot class, crit class, `is_dot`, character-specific keys).
- **Buffs are applied before the call, by the plugin** (R-34): the objective function builds
  the main member's effective status — `Atk` with Atk buffs (and any other status buffs,
  e.g. HP-scaled or party-sourced) folded in — plus the relevant enemy-side debuffs, and
  passes those plain numbers to the kernel. The tool only hands over raw `stats` and the
  aggregated key map; it never pre-buffs, and the kernel never buffs on its own.
- A plugin may therefore call `calculate_damage` **once per damage source** with a
  different argument set each time, then combine the numbers (sum, weighted mix, per-period
  rate).

The documented key convention (R-35) — the single source of truth in `PLUGINS.md`, not
enforced by the loader:

| Talent key (aggregated map) | Kernel argument | Applied to |
| --- | --- | --- |
| `Atk_absMod` | `Atk` (+) | attacker status |
| `Atk_multiplier` | `Atk` (× (1+v)) | attacker status |
| `skillIntensity` | `skillIntensity` | source-specific multiplier |
| `slot{X}Dmg`, `elem{E}Dmg` | `slotDmg`, `elementDmg` | only sources of that slot/element |
| `slot{X}CritDmg`, `critDmgMod`, `crit_rateMod` | `slotCritDmg`, `critDmg`, `crit_rate` | crit terms of that source |
| `DEF_rate_mod`, `RES_rate_mod` | `DEF`, `RES` (−) | enemy parameters (party-side debuffs) |
| `PEN`, `VUL` | `PEN`, `VUL` | scenario + party-side debuffs |
| anything else | — | character-specific: plugin-interpreted (R-20, R-39) |

Worked shape of the plugin-side buffering and key selection (R-33/R-34):

```python
def objective(x, ctx) -> float:
    m, p, sc = ctx["members"]["main"], ctx["aggregated"], ctx["scenario"]
    atk = m.stats["Atk"] * (1 + p.get("Atk_multiplier", 0.0)) + p.get("Atk_absMod", 0.0)
    dps = 0.0
    for skill in (m.auto_skill, m.main_skill):                # R-40 role availability
        for s in skill["sources"]:                            # per-source call (R-32)
            dmg = calculate_damage(
                Atk=atk,                                      # buffered status (R-34)
                **s_buffers(s, p, sc),                        # only this source's keys (R-33)
                DEF=sc["DEF"], RES=source_res(sc, s),         # per-element RES (R-36)
            )
            period = s.get("loop_time") or s.get("cd") or skill.get("loop_time") or skill.get("cd")
            dps += dmg / period if period else dmg            # §6.2 rate; per-hit if untimed
    return dps
```

`s_buffers`/`source_res` are the plugin's own helpers: they choose the aggregated keys that
belong to the source (element/slot/crit class, gated-value convention) and read the right
`ctx["scenario"]` entry — exactly the responsibility split of R-33/R-35/R-36, and the reason
the kernel itself never inspects the talent map.

### 6.2 Generic DPS shape (0.1.0 approximation)

No timeline: a source is assumed available at its own period, which is the default the game
roughly exhibits ("skill used again as soon as its CD is up"). Buff **durations are data**
(R-43), so a generic calculator can derive a gated buff's uptime instead of guessing one:

```
uptime(value)      = min(duration, period(activation)) / period(activation)
                     period(activation) = that activating skill's loop_time or cd
dps = Σ over sources of the main character:  damage(source) / period(source)
      period(source) = loop_time   (auto skill, measured)
                     = cd          (active skill; skill-level cd unless the source overrides)
      damage(source) = calculate_damage(<buffered main status>, <source skillPercentAmend>,
                                        <source elem/slot buffers>, <crit terms>, …)
      buffered status  applies each buf/debuf value x uptime(value) when the value
                       carries the R-43 pair (stacks, first-cast-only and similar quirks
                       stay a plugin-side factor, documented per R-39)
```

A value with no `duration`/`activation` pair keeps the R-39 convention: the plugin declares
the meaning and reads a fallback such as `objective_opts.uptime_fraction`. Alternative plugins
may instead report raw per-hit damage (`auto_attack`, the 0.1.0 default) or a rotation-weighted
mix; the period arithmetic is theirs (R-31). A source carrying neither `loop_time` nor `cd` is
per-hit only — the built-in DPS shape skips it and says so with `-v` (this covers ultimate
portions and burst hits: the tool has no energy/charge/activation model, which is an explicit
non-goal). The 0.2.0 objective generalizes this shape (still without a real timeline) — see §12
Q-2/Q-4.

### 6.3 Sample plugin plan

The reference code we ship (built-ins in `objectives/` and examples in `plugins/`) is planned
as follows, so that timing data is actually exercised end-to-end:

1. `auto_attack` (built-in, R-23): single auto-skill source, **per-hit** damage — plugin
   applies Atk buffs and the auto-attack elem/slot/crit buffers itself, one kernel call.
   Remains the documented default and the objective of the README example.
2. `simple_dps` (sample plugin, `plugins/simple_dps.py`): **the main character's DPS**
   from the timing data — the auto skill's `loop_time` and the main active skill's `cd`,
   each damage source calculated separately with only its own buffers (e.g. the mark
   portion uses `slotMarkDmg`, not `slotSkillDmg`), divided by its period and summed;
   demonstrates the plugin-side Atk/status buffering of R-34 and the "CD up ⇒ used again"
   default of R-31, reads the enemy profile from `ctx["scenario"]` (R-36), derives a gated
   buff's uptime from the R-43 `duration`/`activation` pair when present (falling back to
   `objective_opts.uptime_fraction` per R-39), and uses the per-talent breakdown of R-38 when
   attributing a buff. No timeline.
3. 0.1.0 ships **data only** for timeline-style objectives: `ctx` carries levels, per-talent
   buffers and timing (R-30/R-37/R-38), but no shared timeline helper. Plugins that want an
   approximation build their own.
4. The **model data** for these samples is the user-extracted wiki dump forチトセ, アヤメ,
   テレサ (R-44): the three characters supply the skill percents, `cd`/`loop_time` and talent
   tables (including the `duration`/`activation` pair) that the sample objective is written
   against. Details are not pinned down yet — see the §9 TODO, which blocks M7 data authoring.
5. Later (0.2.0): promote `simple_dps` to a built-in `dps` objective and extend it with
   rotation overrides, more general CD/loop accounting, and shared timeline helpers
   (§12 Q-2/Q-4, M9+).

## 7. CLI surface

```
ssoptim [-h] [--version] COMMAND ...
ssoptim optimize [-c CFG] [-m MAIN] [-s SUB1 ...] [-t N] [-f OBJECTIVE]
                 [--char DIR|FILE ...] [--restrictions FILE]
                 [--total-level-mode exact|at_most] [-o OUT.yml]
                 [--scenario KEY=VAL ...] [--objective-opts KEY=VAL ...] [--show-params]
                 [--maxiter N] [--popsize N] [--runs N] [--seed N] [--no-polish]
                 [-v ...]
```

| Option | Config key | Notes |
| --- | --- | --- |
| `-c, --config CFG` | (root file) | default `./ssoptim.yml`; created with the schema of §4.2 on first run if absent |
| `-m, --main NAME` | `party.main` | party override |
| `-s, --sub NAME` | `party.sub1/sub2` | repeatable, exactly twice, fills in order |
| `-t, --total-levels N` | `total_level` | mandatory (config or CLI) |
| `-f, --objective SPEC` | `objective` | plugin spec, default `auto_attack` |
| `--char PATH` | `data_dirs` | repeatable file or dir; searched before bundled data |
| `--restrictions FILE` | `restrictions` | separate restrictions YAML (merges over config) |
| `-o, --out FILE` | — | default: stdout YAML only |
| `--scenario KEY=VAL` | `scenario.*` | repeatable; per-key override of the enemy profile (R-36) |
| `--objective-opts KEY=VAL` | `objective_opts` | repeatable; free-form plugin-specific constants, delivered as `ctx["objective_opts"]` (R-36, R-37) |
| `--show-params` | — | dump aggregated params (same as `-vv`) |
| `--maxiter/--popsize/--runs/--seed/--no-polish` | `solver.*` | solver knobs |
| `-v, --verbose` | — | count: `-v` warnings, `-vv` per-evaluation objective + params; merged (CLI > config) and handed to plugins as `ctx["verbose"]` / curried `ctx["log"]` (R-42) |
| `-h/--help`, `--version` | — | version from `ssoptim.__version__` |

Precedence: CLI > `--restrictions` file > `--config` file > built-in defaults.
Sub-commands other than `optimize` (e.g. `chars`, `plugins`, `eval`) are **planned, not in 0.1.0**.
The command shape is nevertheless a click **group with exactly one command**, `optimize`, so the
verb is live in 0.1.0 and every README invocation (`ssoptim optimize …`) runs verbatim; the
template's verb-less `simple` form would have contradicted the README, which is the
semver-pinned interface surface (§11 item 23; the later sub-commands just add sibling commands).

Exit codes:

| Code | Meaning |
| --- | --- |
| 0 | feasible optimum written |
| 2 | usage/config error (missing party, missing budget, unparseable YAML, duplicate party characters R-41) |
| 3 | infeasible constraint set (e.g. budget < Σ mins, or mins > maxes) |
| 4 | plugin load failure / plugin raised |
| 5 | solver found no feasible point after `runs` restarts |

## 8. Project structure

The tree follows click-cutter's generated layout (root `Makefile`, `tasks.py`,
`pyproject.toml`, `README.md`, `CHANGES.md`, `LICENSE`, `.gitignore`; package dir with
`__init__.py` + `cli.py` + `<cli_name>/` implementation package) and adds five extension
dirs: bundled data, built-in objectives, user plugin examples, tests, and the extracted
wiki-data dump (R-44).

```
ssoptim/                     # repo root = project "SSOptim"
├── .gitignore               # existing
├── CHANGES.md               # existing; semver2.0 entries, change-point markers
├── DESIGN.md                # this document
├── DamageCalculationParameters.md   # existing reference doc (kept)
├── LICENSE                          # existing (MIT, aoi mizma)
├── Makefile                         # click-cutter targets (build/venv/package/publish/clean)
├── README.md                        # user-facing: usage, config, plugins, install, dev
├── PLUGINS.md                       # detailed plugin development guide (authored at M8)
├── pyproject.toml                   # setuptools + setuptools-scm, [project.scripts] ssoptim = "ssoptim.cli:main"
├── tasks.py                         # invoke tasks mirroring the Makefile
├── stella_sora_damage.py            # scratch reference; vendored into the package at M2, then deleted
├── wiki_data/                       # reference-only wiki extract (R-44): git-ignored, never committed,
│                                    #   never read at build or runtime; authoring source for ssoptim/characters/
├── characters/          # user data set (searched by the tool); <name>.yml
├── plugins/             # example/custom objective plugins; simple_dps.py is the shipped DPS sample (§6.3)
├── tests/               # pytest suite + fixtures tests/data/*.yml (excluded from wheel)
└── ssoptim/             # importable package (package_name = ssoptim)
    ├── __init__.py      # __version__ fallback from _version.py (setuptools-scm)
    ├── cli.py           # click definitions + main(); delegates every command to impl.cmd(kwargs)
    ├── characters/      # bundled default character set (package data, loaded via importlib.resources)
    │   └── <charname>.yml
    └── ssoptim/         # implementation subpackage (cli_name = ssoptim)
        ├── __init__.py
        ├── ssoptim.py   # cmd(kwargs): orchestration (§9 step list), no click, no IO formatting;
        │                #   keeps the template's pout + Level enum, the one verbosity definition (R-42)
        ├── data.py      # YAML loading, schema validation (R-30/R-41/R-43), scenario block (R-36), character/party model objects, data-dir resolution
        ├── talent.py    # sparse {level: value} → interpolated level→value tables (R-19), reserved duration/activation keys kept aside (R-43), per-talent breakdown + param aggregation (R-20, R-38)
        ├── damage.py    # damage kernel, vendored from stella_sora_damage.py (R-24); apply-everything (R-33)
        ├── plugins.py   # plugin spec resolution + registry (R-22), ctx builder for the current x (R-37, R-38), ctx["verbose"]/ctx["log"] injecting (R-42)
        ├── objectives/  # built-in objective functions
        │   ├── __init__.py   # REGISTRY = {"auto_attack": ...}
        │   └── auto_attack.py# default objective (R-23)
        ├── constraints.py # bounds + LinearConstraint builder from data/config (R-04..R-16, R-41 checked at load)
        ├── optimize.py    # differential_evolution driver, restarts, per-candidate ctx, verify/repair fallback (R-08..R-12, R-38)
        └── report.py      # result YAML + console rendering (R-27..R-29)
```

Module dependency direction (must not cycle):

```
cli.py → ssoptim/ssoptim.py → {data.py, talent.py, plugins.py/objectives, constraints.py, optimize.py, report.py}
optimize.py → objectives/* → {talent.py, damage.py, data.py}
```

Naming/package facts fixed here:

- `project_name = SSOptim`, `package_name = ssoptim`, `cli_name = ssoptim`
  → entry point script `ssoptim = "ssoptim.cli:main"`, console command **`ssoptim`**.
- `requires-python = ">=3.12"`; `dependencies`: `click>=8.1,<9`, `PyYAML>=6,<7`, `scipy>=1.11,<2`, `numpy` (via scipy).
- `optional-dependencies.dev`: `pyinstaller`, `build`, `twine`, `pytest`.
- setuptools-scm supplies `__version__`; `dynamic = ["version"]`.
- File headers follow click-cutter: shebang, coding line, `Copyright (c) 2026 aoi mizma <aoi.mizma@path-works.net>`,
  `SPDX-License-Identifier: MIT`.
- Data is *not* compiled into the wheel beyond a convenience seed set; plugins are never
  compiled in beyond built-ins (R-22 extensibility without rebuild).

## 9. Implementation plan

Each milestone is independently testable and lands with docs/changelog updates.

| M | Deliverable | Acceptance criteria |
| --- | --- | --- |
| M0 | click-cutter scaffold: `pyproject.toml`, `Makefile`, `tasks.py`, package dirs, `--version`/`--help` work, editable install via `uv` | `ssoptim --version` prints `0.0.0+dev`/`0.1.0`; wheel builds with `uv build` |
| M1 | `data.py` + `talent.py`: YAML load, schema validation (incl. `cd`/`loop_time`, multi-`sources` skills, distinct-party rule R-41), scenario block (R-36), interpolation tables, per-talent breakdown (R-38) | loader round-trips §4.1 sample; interpolation of 1↔6 keys matches the even-step rule; `scenario:` merges over kernel defaults; a duplicate party and invalid data both fail with R-29 exit 2 |
| M2 | `damage.py` vendoring of `stella_sora_damage.py`; unit conversion helper | vendored file reproduces the sanity table the scratch file prints (parameter names documented in [DamageCalculationParameters.md](DamageCalculationParameters.md)) |
| M3 | `objectives/auto_attack.py` + `plugins.py` ctx builder/aggregation path + `plugins/simple_dps.py` DPS sample (§6.3) | default objective on a fixed 3-char fixture equals a hand-computed value from §4.1 constants; `simple_dps` reproduces a hand-computed main-character DPS from §4.1's `loop_time`/`cd` and its two sources (per-source buffers, R-32/R-34); both plugins take `(x, ctx)` and read levels/buffers through the helpers, never by indexing `x` (R-37, R-38) |
| M4 | `constraints.py` bounds/constraint generation | generated matrices verified by direct check of R-04, R-13, R-14, R-15 on fixtures; infeasible inputs flagged (exit 3); duplicate party flagged (exit 2, R-41) |
| M5 | `optimize.py`: `differential_evolution` + verify/repair | on the fixture, the optimum matches the brute-force enumeration of the reduced (2 chars, 4 sub levels) space; all constraints hold |
| M6 | `cli.py` + `report.py`: options (incl. `--scenario`, `--objective-opts`), precedence, YAML out, exit codes | README's documented invocation runs end-to-end and writes §4.3 YAML; precedence tests: CLI overrides config, `--scenario DEF=…` overrides the `scenario:` block; `--show-params` prints the aggregated map and the effective scenario (R-36) |
| M7 | Packaging/CLI polish, built-in char data set (authored from the `wiki_data/` reference extract of R-44), `plugins/` examples, pytest suite green, `tasks.py`/Makefile wired | `uv build` + `pipx install ssoptim` yields a working `ssoptim optimize …` with `--config` defaults; the bundled set loads and round-trips through the §4.1 validation rules |
| M8 | `PLUGINS.md`: detailed plugin development guide (separate document) — objective contract and "bigger is better" convention (R-21/Q-1), flat `x` vector layout (R-08), the `ctx` contract and level-resolution helpers (R-37/R-38, incl. the per-talent breakdown), the buffer-key vocabulary (R-35) and gated-value conventions (R-39), scenario inputs (R-36), **kernel/buffer ownership** (R-33/R-34: the kernel applies everything it is given; the plugin selects keys and applies Atk/status buffs first), skill timing (R-30/R-31), the **duration/activation gating convention** (R-43: reserved keys inside the level map, `activation` as one of the four skill keys, and the `min(duration, period)/period` uptime derivation), plugin-side progress output through `pout`/`ctx["log"]` (R-42), role availability (R-40), multi-source skills (R-32), the §6.2 DPS recipe with a hand-rolled timeline approximation, worked `auto_attack` and `simple_dps` walkthroughs, plugin exception → exit 4 behaviour, solver-knob tuning | every code snippet in `PLUGINS.md` runs verbatim against the M3 fixture party; `ssoptim optimize -f ./plugins/simple_dps.py:objective` matches the documented value; README §"Objective plugins" links to it |
| M9+ | Extra built-in objectives (single skill, ult, cooldown-aware `dps` promoted from `simple_dps`, §12 Q-4 generalization), planned sub-commands (`chars`, `plugins`, `eval`) | each new objective documented in `PLUGINS.md` §"Built-in objectives" and registered in `objectives/`; `PLUGINS.md` extended in place |

**Data-authoring note (was the M7 blocker, R-44):** theチトセ、アヤメ、テレサ extract exists in the
workspace under `wiki_data/`. It is **not** checked in (the user keeps it as reference material;
`.gitignore` lists `wiki_data/`), so the wheel's provenance is the authored YAML in
`ssoptim/characters/` rather than a committed dump. Neither the build nor the tool ever reads
`wiki_data/`, which is what keeps M7 self-contained: the milestone authors the bundled set from
that extract and commits only the resulting character files.

Testing strategy: pure functions at `data`/`talent`/`constraints` boundaries (no scipy needed),
scipy driver tested against a deterministic exhaustive reference for a reduced fixture,
CLI tested via `click.CliRunner` on fixture YAML in `tests/data/`.

## 10. Risks & mitigations

| Risk | Mitigation |
| --- | --- |
| SciPy `integrality=True` + constraints is finicky (bounds must be integer, coefficients integer, polish can break feasibility) | integer-only bounds/constraints by construction; post-solve verify+repair; deterministic seeded restarts; documented `runs`/`maxiter` knobs |
| Objective non-monotone in levels → budget equality may be "wasted levels" | `total_level_mode: at_most` exists (R-13); default remains `exact` |
| Objective plugins are user code (slow/raising) | precomputed interpolation tables (no YAML per call); plugin exceptions mapped to exit 4; `-vv` prints each evaluated value for diagnosis |
| Character-specific mechanics can't be expressed generically | free-form keys (R-20) + per-plugin interpretation; docs state clearly that plugin quality, not the tool, decides modelling fidelity |
| Timing data missing, guessed, or contested (no published CD values; loop time depends on animation/movement) | `cd`/`loop_time` are optional and authored per character from game spec or video analysis (R-30); the loader warns (`-v`) when a DPS-minded objective needs them and they are absent, falling back to per-hit damage; `PLUGINS.md` states that timing numbers are the data author's responsibility and records the measurement method |
| Plugin applies the wrong key set or forgets to buffer Atk/status (R-33/R-34 are on the plugin, not the kernel) | `--show-params`/`-vv` prints the aggregated map and the per-evaluation objective; `PLUGINS.md` gives a per-source argument table and the worked `simple_dps` example as the copy/modify starting point |
| Data set incompleteness (only some characters authored) | data lives in `characters/` and `ssoptim/characters/`; tool validates and names missing characters explicitly; README "Known Issues" lists the shipped set |
| Plugin needs per-talent attribution but only gets the summed map (or re-maps `x` positions by hand) | `ctx` carries the per-talent `talent → {key: value}` breakdown resolved for the current `x` (R-38); `resolve_talent_params(x, ctx)` is the documented entry point |
| Two plugins disagree on what an unknown key means (`Atk_multiplier` additive vs multiplicative; gated value = amount vs uptime fraction) | one documented vocabulary in `PLUGINS.md` (R-35) plus `objective_opts:` for the gated-value convention (R-39); `--show-params` prints the aggregated map so mismatches are visible; unknown keys are never silently applied by the kernel (R-33). The R-43 `duration`/`activation` pair removes most of the guesswork — uptime becomes `min(duration, period)/period` instead of a per-plugin constant |
| Duration/activation data is wrong, missing, or an unsupported case (stacking, first-cast-only) | the pair is optional: absent it, the value keeps the R-39 documented-convention reading and a `objective_opts:` fallback; unusual cases stay a documented plugin-side factor; the loader validates the pair itself (`duration > 0`, `activation` one of the four skill keys) and `-v` names what it had to assume (R-43) |

## 11. Decisions (with rationale)

1. **Differential evolution** over brute force/ILP: objective is opaque, non-linear, and
   combinatorially ~1e25 for a 3-character party, but evaluation is cheap.
2. **Per-talent bounds instead of constraints** for R-15: keeps the bound box tight, which
   DE needs for integrality to behave.
3. **Exact-sum budget by default** with `at_most` opt-in: matches the game's "levels
   available" mental model while permitting non-monotone objectives.
4. **Keyed restrictions by talent name** (positional also accepted): name keys survive
   data-file reordering; the positional form stays available for hand-written restriction
   lists copied in the character's declaration order (§4.1), which is how players transcribe
   talent order from the game.
5. **Plugin loading by spec string, three forms** (R-22): the original design's open
   question "some module name?" is resolved; file-path form is what makes `pipx`-installed
   extension possible without rebuild.
6. **Damage kernel vendored** into `ssoptim/ssoptim/damage.py` instead of imported from the
   root scratch file: the wheel must be self-contained; the root file stays until M2.
7. **`simple` click-cutter CLI type** for 0.1.0: only `optimize` is specified; the `verb`
   argument keeps the door open for the planned `chars`/`plugins`/`eval` sub-commands.
8. **Aggregation helper inside the tool, not per plugin** (R-20): every plugin needs the
    same "sum all same-key params at chosen levels" step, including unknown keys.
9. **Semver 2.0 pre-1.0.0 alpha** and `CHANGES.md` change-point markers: interface
    versioning is pinned to README's Usage + config-file format (see README §Versioning).
10. **Timing facts in data, DPS arithmetic in the plugin** (R-30/R-31): cooldown (from the
    game's character spec) and auto-skill loop time (from video analysis) are properties of
    the character, so they live in character data and any plugin may read them; turning them
    into DPS is modelling and differs per character/party, so it stays in the plugin. This
    resolves Q-2 without importing a rotation model into 0.1.0.
11. **Skills are a list of damage sources** (R-32): the game resolves element/slot buffers
    per damage portion (an element hit plus a separate mark portion), so a skill declares
    sources with their own type and their own `cd`/`loop_time`, letting a generic calculator
    evaluate each separately (different buffers, different period) and sum them. Single-source
    skills keep the shorthand `damage:` map, so existing character data stays valid.
12. **The kernel stays "apply-everything" and unbuffered** (R-33/R-34): `damage.py` remains a
    faithful transcription of the game formula (R-24), so one function serves every skill and
    every condition. The consequence is that the objective function owns key selection and must
    pre-apply Atk/status buffs to the main member's status before each call; no per-skill key
    policy or implicit buffing is encoded in the tool, and `PLUGINS.md` documents the split.
13. **`PLUGINS.md` as a separate guide, authored at M8**: the plugin contract (key selection,
    buffer ownership, timing data, DPS shape, worked samples) is far more detailed than
    README's Usage section — which is the semver-pinned interface surface — so it lives in its
    own document that README links to and that grows with each new built-in objective.
14. **Typed `scenario:` block, not plugin-only enemy constants** (R-36): DEF/RES/PEN/VUL/break
    are part of the damage formula and are identical for every plugin, so they belong to the
    run config and are diffable via `--show-params`; only genuinely plugin-specific knobs go to
    `objective_opts:`. Game-undefined formula terms (`IGNORING`, `generalDmg`, `dmgPlus`,
    `finalDmg`, …) stay kernel-only neutral defaults so users cannot set meaningless values.
15. **Tool-provided `ctx`, not a plugin-side loader** (R-37): the plugin contract must give the
    plugin character/party data — some characters scale damage off HP or other base stats — and
    building it once per candidate inside the tool keeps that data free of re-parsing while still
    letting plugins bind their own extra constants by closure.
16. **Per-talent breakdown alongside the summed map** (R-38): talent activation is gated on
    skill activation, so a timeline-style plugin must know *which* talent granted a buff. The
    summed map of R-20 is convenient but lossy; `ctx` therefore also carries
    `talent → {key: value}` per member, resolved for the current `x`. Plugins never map `x`
    positions to talents themselves.
17. **Role rules kept as prose over the existing four skill keys** (R-40): the game's role
    availability (main uses auto/main/ult; support uses sub/ult and, for a few characters, its
    **auto skill** — never `main_skill`) is intrinsic to the key names, so no per-role data keys
    are added; the plugin resolves the special cases from the full party data of R-37.
18. **No condition-expression language in 0.1.0** (R-39): condition-gated values stay
    "value + documented convention" (uptime fraction / per-application / count) applied by the
    plugin, because a condition DSL would drag marks, break state and status durations into the
    tool, which are explicit non-goals.
19. **Duration and activation as data, not as a condition language** (R-43): the game states a
    buff's uptime and the skill that grants it, so those facts belong in character data next to the
    level values (`duration`/`activation` as reserved keys inside the same map, `activation` one of
    the four skill keys of R-40). That makes a generic objective's uptime `min(duration, period)/period`
    instead of a per-plugin guess, and shrinks `objective_opts:` to genuinely plugin-specific knobs.
    Still a convention: the loader only range-checks it, unusual cases (stacking, first cast) stay
    documented plugin-side factors, and no condition DSL is introduced (R-39, R-35 keep keys free-form).
20. **Verbosity delivered through `ctx`, plugin output through the template's `pout`** (R-42): plugin
    progress prints must obey the user's `-v`, but plugins never see the parsed CLI. Keeping click-cutter's
    `pout`/`Level` in `ssoptim.py` as the single definition and injecting both the count (`ctx["verbose"]`)
    and the curried logger (`ctx["log"]`) into the per-candidate `ctx` of R-37 gives plugins the same
    levels as the tool (R-28's `-v`/`-vv`) at no per-evaluation cost.
21. **Wiki data kept as reference, never fetched** (R-44): theチトセ/アヤメ/テレサ pages are the
     authoring source for the bundled set and for the sample objective's model. The user keeps the
     extracted dump in the workspace under `wiki_data/` as **reference only** — it is git-ignored and
     never committed — so the wheel's committed artifact is the authored YAML, while the build and the
     tool still never touch the wiki. Reviewability of provenance is traded for a lean repo; the
     requirement is otherwise unchanged (offline build, self-contained wheel).
22. **Interpolation pinned at both ends** (R-19): sparse maps are the authoring convenience of the
     wiki's "X〜Y" (level 1〜level 6) notation, so a single-anchor map needs a defined reading. The
     origin `(0, 0)` is an anchor (level 0 contributes nothing, R-05/R-19) and levels past the last
     declared anchor repeat that anchor. Both rules are stated in §4.1 so fixture data, the loader and
     the plugins agree on one table without extrapolating past authored evidence.
23. **Click group with one command, not the verb-less simple form** (§7): README's Usage section is the
     semver-pinned interface surface and every example says `ssoptim optimize …`, so 0.1.0 registers
     exactly one command under the group. The template's `cli_type = simple` would have made the
     documented invocations fail; the planned `chars`/`plugins`/`eval` sub-commands then only add
      sibling commands to the same group.
 24. **Duration bands, not even steps** (R-43): the spec's own worked example states
      `{ 1: 10, 4: 12 }` as "10 s for levels 1-3, 12 s for 4-6" while labelling it "interpolated
      by the R-19 rule", which an even step cannot produce (it would give 10.7/11.3 s). The
      concrete example wins: the game states one uptime per level band, so durations are read
      last-anchor-at-or-below and only the *value* maps keep the even step. Levels below the
      first band take that band — a gated buff exists at every owned level, and 0 s would mean
      "no buff". R-43, §4.1 and §10 now say "level bands" so data, loader and plugins agree.

## 12. Open questions — answers recorded (see §11 items 10–24 for rationale)

| # | Question (as originally open) | Answer |
| --- | --- | --- |
| Q-1 | Is `objective` always "bigger is better"? (Assumed yes; plugin docs must state it.) | **Yes.** Plugins must return numbers where bigger is better; the tool maximizes and never negates or normalizes. This is stated in `PLUGINS.md` (M8) and in the plugin contract (R-21, R-27, §5). A plugin wanting "smaller is better" negates its own score. |
| Q-2 | Do skill-hit counts / cooldown windows belong to the plugin (assumed) or to a shared rotation model (not in 0.1.0)? | **Data supplies the facts, the plugin supplies the use.** Character data carries the basic cooldown time in seconds from the game's character spec for main/sub active skills, and a measured loop time in seconds (video analysis) for every authored character's auto skill (R-30; the built-in DPS objectives use the `main` slot's value, and sub-slot auto-skill cases read the sub's own — R-40). How `cd`/`loop_time` are used is entirely up to the objective function/plugin (R-31): per-hit damage, the §6.2 `damage(source)/period(source)` sum, or a character-specific rotation. No shared rotation model in 0.1.0. |
| Q-3 | Should the tool ever enforce a per-character minimum automatically (the game's "main talents appear more often" bias) or leave it purely to R-14? | **Purely R-14.** The tool applies no implicit bias; users are expected to provide reasonable per-character `min`/`max` to tune the talent-level distribution. Documented so the config carries the burden. |
| Q-4 | Multi-scenario runs (several DEF/RES enemy profiles in one invocation)? | **Deferred.** The priority for the second release is instead a more general *objective* that incorporates CD/loop time in seconds — still a simplified calculation with no real timeline (buff durations are data per R-43), approximating CD/loop effects (the §6.2 shape generalized; `simple_dps` promoted to a built-in `dps` objective, M9+). The `scenarios:` list remains deferred. |
| Q-5 | Which skills may a character use from each party slot? | **Fixed role rules over the existing four skill keys, no extra keys** (R-40): `main` uses `auto_skill` + `main_skill` + `ult_skill`; `sub1`/`sub2` use `sub_skill` + `ult_skill` and never `main_skill`; the role exception is the **auto skill** — some characters act from the sub slot with it, so `loop_time` is authored for every character's `auto_skill`. Which of these actually feed the objective is plugin-side logic, and `ctx` must carry all three members in full (R-37). |
| Q-6 | Who owns timeline/condition simulation (talent gated on skill activation, "after activation", "target has mark")? | **The plugin** (R-31/R-39): 0.1.0 ships data only — resolved levels, the per-talent buffer breakdown, and timing (R-30/R-37/R-38) — with no shared timeline helper and no condition DSL; the gated-value convention is documented per character/plugin (R-39) and tunable via `objective_opts:`. Shared timeline helpers arrive with the 0.2.0 generalized objective. |
| Q-7 | May the same character occupy two party slots? | **No.** Three distinct characters are required; a repeated name is an input error (exit 2, R-41). |
| Q-8 | Where do enemy DEF/RES/PEN/VUL and break state come from? | **The `scenario:` block** in the run config (R-36), merged over kernel defaults and delivered as `ctx["scenario"]`; `--scenario KEY=VAL` overrides single keys. Formula terms that are not defined in game (`IGNORING`, `generalDmg`, `dmgPlus`, `finalDmg`, …) are not exposed. |
