# SSOptim — Design Specification

Status: **0.1.0 in development** — milestones M0–M8 are implemented and committed
(`b45d550`…`5442b2a`); the pytest suite is green. What is still to be built is §9 (0.2.0
work); the divergences and gaps this milestone set leaves standing are §10.
Self-contained: this document restates the game-spec facts it depends on (§1.1) · damage
reference: [DamageCalculationParameters.md](DamageCalculationParameters.md), transcribed by
the tool's own kernel (`ssoptim/ssoptim/damage.py`, R-24).
Project structure basis: [click-cutter](https://github.com/koma75/click-cutter) (Click CLI
cookiecutter template, `cli_type = simple` → a click **group with exactly one command**
(`optimize`) in 0.1.0 per §7, `use_config_yaml = Yes`)

This document is the streamlined, decision-complete plan for building `ssoptim`. It restates
the goals as testable requirements, fixes the data/plugin/CLI contracts, and defines the source
tree. §1.1 restates the game model those requirements assume, so nothing here depends on any
other document for background. The rationale that fixed each contract sits next to the
requirement it justifies, as a `Notes:` bullet list under the requirement table or schema
paragraph it explains; §9 lists the work that is still to be built, and §10 the issues open at
this milestone set.

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
  left entirely to the user (R-14; the tool applies no implicit bias), and why simulating the random pulls is a non-goal (§2).
* **Damage values:** produced by the damage formula documented in
  [DamageCalculationParameters.md](DamageCalculationParameters.md), which the tool transcribes
  into its kernel — `ssoptim/ssoptim/damage.py` (R-24).
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
  Shared timeline helpers arrive with the 0.2.0 generalized objective (§9).
- A condition-expression language in the data format: condition-gated talent values
  (cooldown window, "after skill activation", "target has mark") are a documented
  convention resolved by the plugin (R-39), with the gating facts themselves in the data
  as the reserved `duration`/`activation` keys (R-43); mark/break state itself is not modelled.
  A condition DSL would drag marks, break state and status durations into the tool,
  which is an explicit non-goal, so the plugin keeps the convention instead (R-39).
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

Notes:

* **R-03 (the fixed 4/12 split):** the split is the game's structure, not a knob the tool
  may relax - the loader validates it (§4.1) and generates the core-selection constraint from
  it (R-17), so a character file that does not fit is an input error, never a degraded run.
* **R-07 (budget is user input):** the game's random pulls are not simulated (§2), so the
  number of levels available is whatever the user's build reached - typically ~40-65+.

### Optimization problem

| ID | Requirement |
| --- | --- |
| R-08 | Decision variables are the talent levels of all three party members, flattened into one integer vector: main character's talents first, then `sub1`, then `sub2`, each in YAML declaration order. |
| R-09 | The objective is an opaque, possibly non-linear scalar function `f(x)` (damage/DPS); the tool maximizes it. No gradient/convexity assumption. |
| R-10 | Solver default: `scipy.optimize.differential_evolution` with `integrality=True`, integer bounds and integer-coefficient linear constraints. |
| R-11 | Every result must satisfy all constraints (bounds, core=2, budget, per-character min/max). Infeasible input must be reported as an error, not silently relaxed. |
| R-12 | The search space is 16 variables/character (48/party); runtime for one run must stay in the seconds-to-minutes range for the default objective. |

Notes:

* **R-09 (bigger is better):** plugins return numbers where **bigger is better**, and the tool
  maximizes without negating or normalizing what it *reports* - the printed value and the §4.3
  `objective:` key are exactly what the plugin returned. A plugin wanting smaller-is-better
  negates on its own side. Internal detail: SciPy's `differential_evolution` only minimizes, so
  `optimize.py` wraps the search in a negating closure that nothing outside the wrapper ever
  sees; the greedy fill and `verify()` use the same wrapper, so the deterministic reference and
  the safety net agree on the reported value.
* **R-10 (differential evolution, not brute force/ILP):** the objective is opaque and
  non-linear, the space is combinatorially ~1e25 for a 3-character party, and evaluation is
  cheap - which rules out enumeration and leaves ILP unable to express a black-box objective.
  SciPy's constrained integrality is finicky (bounds and coefficients must be integers, and
  `polish` can break feasibility), so the mitigation set is structural: integer-only bounds and
  constraints by construction, a post-solve verify+repair pass, deterministic seeded restarts,
  and documented `runs`/`maxiter` knobs (§5, §7).
* **R-11:** infeasibility is its own error class (`Infeasible`, exit 3), never a relaxed solve,
  and a candidate that fails `verify()` is rejected rather than reported.

### Constraints (user-supplied)

| ID | Requirement |
| --- | --- |
| R-13 | `total_level` (budget) is mandatory, default semantic = **exact** sum; an explicit `total_level_mode: at_most` allows leaving levels unused. |
| R-14 | Per-character `min`/`max` on the character's **total** talent levels (e.g. `main: {min: 30}`). |
| R-15 | Per-talent `min`/`max` bounds, addressable by talent name (positional form also accepted, aligned to YAML declaration order). |
| R-16 | The user may pin core-talent choices; this is expressed as `min: 1` on the two selected core talents and is implied by R-04 to force the other two to 0. |
| R-17 | Core talents are always the first four entries of a talent set; the loader validates this and generates the `sum(core) == 2` constraint from data, not from user config. |

Notes:

* **R-13 (exact by default):** the exact sum matches the game's "these many levels are
  available" mental model. `at_most` exists because the objective is not monotone in levels, so
  equality can force "wasted levels" - with `at_most` the user sees the unused levels instead of
  the tool silently relaxing the budget.
* **R-14 (no implicit bias):** the tool never applies the game's "main talents appear more often"
  pull bias on the user's behalf; users provide reasonable per-character `min`/`max` to shape the
  distribution, which is documented so the config file carries that burden.
* **R-15 (bounds, not constraints):** per-talent bounds become variable bounds rather than
  constraint rows, which keeps the bound box tight - what `differential_evolution` needs for
  integrality to behave. Name keys are preferred because they survive data-file reordering; the
  positional form stays available for hand-written restriction lists transcribed in the
  character's declaration order (§4.1), which is how players copy talent order off the game.
* **R-16/R-17:** core pinning is just `min: 1` on the two chosen cores, and the `sum(core) == 2`
  row is generated from the data layout, so a hand-written or corrupted constraint cannot desync
  the variable layout from the character file.

### Data / plugin contract

| ID | Requirement |
| --- | --- |
| R-18 | Character definitions are YAML files keyed by character name (`stats`, `auto_skill`, `main_skill`, `sub_skill`, `ult_skill`, `talents_main`, `talents_sub`). |
| R-19 | A talent entry maps parameter key → `{level: value}`. Only levels that change need listing; **intermediate levels are interpolated evenly** between the two declared anchors (e.g. keys 1 and 6 imply a constant step for 2–5; level 0 contributes nothing). A map with a single anchor keeps the same rule against the implicit `(0, 0)` origin, and **levels above the last declared anchor keep that anchor's value** (no extrapolation) The rule is pinned in §4.1 so sparse authoring, the loader and the plugins compute one table. |
| R-20 | Talent parameter keys are free-form strings; they are *summed* across all owned talents at their chosen levels, including character-specific keys unknown to the damage kernel. |
| R-21 | An objective plugin is a callable `f(x, ctx) -> float`. `x` is the SciPy-style flat level vector (R-08); `ctx` is the **tool-provided** data context of R-37 (party characters with full stats/skills/talents, resolved levels and buffers, scenario). The plugin author may still bind extra constants by closure/partial, but must not have to load character data itself. |
| R-22 | Plugin references accept three forms: built-in short name (`auto_attack`), dotted module path (`pkg.mod:func`), and file path (`./plugins/my_calc.py:func`). Loading must work at runtime against a `pipx`/`uv tool install`ed copy — no package rebuild. |
| R-23 | A built-in default plugin must exist that computes **auto-attack skill damage** from the damage kernel; it is the reference implementation and the objective of the doc examples. |
| R-24 | The damage kernel (DEF/RES/PEN/VUL/erAmend/defAmend, crit expectation, `is_dot`) is shared library code, unit-converted from YAML conventions via `skill_percent_to_amend`. |

Notes:

* **R-19 (pinned at both ends):** sparse maps mirror the wiki's "X〜Y" (level 1〜level 6)
  authoring notation, so a single-anchor map needs a defined reading. The origin `(0, 0)` is an
  anchor (level 0 contributes nothing, R-05) and levels past the last declared anchor repeat that
  anchor rather than extrapolating past authored evidence. Both ends are stated in §4.1 so fixture
  data, the loader and the plugins compute one table.
* **R-20 (aggregation in the tool, not per plugin):** every plugin needs the same "sum all
  same-key params at chosen levels" step, including unknown keys, so it is one shared helper (§6).
  Mechanics that no generic key can express stay free-form keys plus per-plugin interpretation -
  which is why plugin quality, not the tool, decides modelling fidelity; `--show-params`/`-vv`
  prints the aggregated map so an author can see exactly what a plugin was handed.
* **R-22 (three spec forms):** this is the answer to the originally open "some module name?"
  question; the file-path form is what makes a `pipx`/`uv tool install`ed copy extensible without
  a rebuild.
* **R-24 (kernel as library code):** the wheel must be self-contained, so the damage formula lives
  inside the package (`ssoptim/ssoptim/damage.py`) and no module imports a repo-root scratch file.

### Skill timing & damage sources (plugin-facing data)

| ID | Requirement |
| --- | --- |
| R-30 | Main and sub **active skills** (`main_skill`, `sub_skill`) carry a **cooldown** `cd` in seconds, taken from the game's character spec. Every authored character's **auto skill** carries a **loop time** `loop_time` in seconds, measured from gameplay/video analysis of one full auto-attack cycle — authored for all characters, not only the one in the `main` slot, because some characters act from the sub slot with their auto skill (R-40); built-in DPS objectives use the main slot's value. |
| R-31 | Timing values are informational to the tool: it type/range-checks them and passes them through. Which period a plugin uses, and how many times a skill fires inside a window, is entirely the objective function's/plugin's decision — a plugin may follow the "use immediately when CD is up" default or model its own rotation. |
| R-32 | A skill may declare **multiple damage sources** (e.g. a base elem hit plus a separate mark portion). Each source carries its own damage type (element and/or slot class), may carry its own `cd`/`loop_time`, and may set `dot` (→ kernel `is_dot`), so a generic calculator evaluates each source as a separate `calculate_damage` call with only that source's buffers and sums the results. |
| R-33 | The damage kernel is **apply-everything**: `calculate_damage` consumes every argument it is handed and applies no policy of its own about which keys belong to which skill or damage source. Choosing the argument set — including dropping irrelevant talent keys — is the objective function's/plugin's responsibility. |
| R-34 | Buffs are applied **before** the kernel call, by the objective function/plugin: it folds the relevant Atk buffs and any other status buffs into the main party member's effective status (and the relevant enemy-side debuffs into the enemy parameters) and hands those numbers to the kernel. The tool supplies only raw `stats` and the aggregated key map (R-20); it never pre-buffs anything. |

Notes:

* **R-30/R-31 (facts in data, use in the plugin):** cooldown time (from the game's character spec)
  and measured auto-skill loop time (from video analysis) are properties of the character, so they
  live in character data and any plugin may read them; turning them into DPS is modelling that
  differs per character/party and stays in the plugin. Timing data can also be missing, guessed, or
  contested (no published CD values; loop time depends on animation/movement), so it is optional:
  the loader warns with `-v` when a DPS-minded objective needs it and it is absent, falling back to
  per-hit damage, and `PLUGINS.md` records that timing numbers are the data author's responsibility
  and states the measurement method.
* **R-32 (sources list):** the game resolves element/slot buffers per damage portion (an element
  hit plus a separate mark portion), so a skill declares sources with their own type and their own
  period, letting a generic calculator evaluate each separately with different buffers and
  different periods and sum them. Single-source skills keep the shorthand `damage:` map, so
  existing character data stays valid; the loader normalizes that shorthand to a one-element
  `sources:` list inheriting skill-level timing, so plugins see exactly one shape.
* **R-33/R-34 (ownership split):** `damage.py` stays a faithful transcription of the game formula
  (R-24), so one function serves every skill and every condition. The consequence is that the
  objective function owns key selection and must pre-apply Atk/status buffs before each call; no
  per-skill key policy or implicit buffing is encoded in the tool. A plugin that picks the wrong
  key set or forgets to buffer is a real risk, so `--show-params`/`-vv` print the aggregated map
  and the per-evaluation objective, and `PLUGINS.md` gives a per-source argument table plus the
  worked `simple_dps` walkthrough as the copy/modify starting point.

### Plugin context, scenario & key vocabulary

| ID | Requirement |
| --- | --- |
| R-35 | A **documented buffer-key vocabulary** maps talent parameter keys to damage-kernel arguments: `Atk_absMod` → additive Atk, `Atk_multiplier` → multiplicative Atk buff, `critDmgMod` → `critDmg`, `crit_rateMod` → `crit_rate`, `skillIntensity`, `slot{AutoAttack,Skill,Ultimate,Other,Mark,Projectile,Minion}Dmg` → `slotDmg` of that source, `slot{…}CritDmg` → `slotCritDmg`, `elem{Aqua,Ignis,Terra,Ventus,Lux,Umbra}Dmg` → `elementDmg`, `DEF_rate_mod`/`RES_rate_mod` → enemy debuffs. The vocabulary is a **convention**, never enforced (R-20 keeps keys free-form), but it is the single source of truth in `PLUGINS.md` and the built-ins — because R-33 means the kernel will not map keys for the plugin. Keys outside the vocabulary are character-specific. |
| R-36 | The enemy/scenario profile is user input: a `scenario:` block in the run config with `DEF`, `RES`, an optional per-element `res_table` (weakness/neutral/resistance values), `PEN`, `VUL`, `DEF_Ignore`, `DEF_Penetrate`, `enemyBreakStatus`, `resilienceBreakDmg`, merged over the kernel's defaults and handed to the plugin as `ctx["scenario"]`. Free-form `objective_opts:` (CLI `--objective-opts KEY=VAL`) carries plugin-specific constants into `ctx["objective_opts"]`. `IGNORING`, `generalDmg`, `dmgPlus`, `finalDmg`, … stay kernel-only neutral defaults because they are not defined in game. Exactly **one** scenario per invocation in 0.1.0; multi-scenario runs are §9 work. |
| R-37 | The tool provides the **data context** to the plugin: `f(x, ctx)`. `ctx` carries, per party slot (`main`, `sub1`, `sub2`), the full character object (`stats` incl. `HP`/`DEF` for HP-scaled mechanics, all skill blocks with `cd`/`loop_time`/`sources`, the talent set in use), the merged scenario, plugin objective options, and the buffer maps of R-38. All three members' detail must be present so plugins can model support-side contributions and sub-slot auto-skill cases (R-40). |
| R-38 | Per evaluated candidate the tool builds `ctx` with the level resolution already done: `ctx["members"][slot].talent_levels` (name-keyed, in R-08 order), `ctx["members"][slot].talent_params` (**per-talent** breakdown `talent → {key: value at that level}` using the R-19 interpolation tables), and `ctx["aggregated"]` (the summed map, identical to `aggregate_params(x)`). Helper `resolve_talent_params(x, ctx)` returns the same data. The **per-talent breakdown is mandatory**, not just the sum: talent activation is gated on skill activation, so timeline-style plugins (simple approximation or real simulation, owned by the plugin per R-31) must attribute a buff to the talent that granted it. No YAML parsing per evaluation (§5 invariant). |
| R-39 | Talent values may be **condition-gated** in the game (cooldown window, "after skill activation", "target has mark"). 0.1.0 has no condition-expression language in the data format: the *meaning* of an aggregated value — per-application amount, uptime fraction, or plain count — is a documented convention declared in the character's/plugin's docs and applied by the plugin (e.g. a value multiplied by an assumed uptime). Mark and break state are not modelled by the tool. |
| R-40 | Role semantics of the existing skill keys (no extra keys): the `main` slot uses `auto_skill` + `main_skill` + `ult_skill`; `sub1`/`sub2` use `sub_skill` + `ult_skill` and **never `main_skill`**. The special case is `auto_skill`: some characters act from the sub slot with their auto skill (currently the only such role exception), which is plugin-side logic; hence `loop_time` is authored for every character's `auto_skill` (R-30). |
| R-41 | A party must consist of three **distinct** characters; the same character name in two slots is a loader error (exit 2). |
| R-42 | The `-v/--verbose` **count** follows the same precedence as every other option (CLI > config) and is handed to plugins inside `ctx`: `ctx["verbose"]` (the integer count) and `ctx["log"]` — that `pout` **curried** with the run's verbosity already bound. The tool keeps the click-cutter template's `pout(msg, Verbose, level, newline)` (+ `Level` IntEnum: DEBUG shown at `Verbose >= 2` on stdout, WARNING at `>= 1` on stderr, INFO/ERROR/CRITICAL always) as the single definition of verbosity, and plugin-side progress output must go through `pout`/`ctx["log"]` so it follows the user's `-v`: `Level.WARNING` for "data missing, falling back" notices and `Level.DEBUG` for per-evaluation values — the R-28 levels, one definition shared by tool and plugin. |
| R-43 | Buff/debuff values carry **`duration`** and **`activation`** as reserved keys inside the same map as the level keys: `Atk_multiplier: { 1: 0.15, 6: 0.7, duration: { 1: 10, 4: 12 }, activation: main_skill }`. `duration` is in **seconds**, sparse, and read as **level bands** — the last declared anchor at or below the level applies, so `{ 1: 10, 4: 12 }` is 10 s for levels 1–3 and 12 s for 4–6 (a band, not an even step); `activation` is strictly one of the four skill keys (`auto_skill`/`main_skill`/`sub_skill`/`ult_skill`, R-40) and names the skill whose use grants the buff. Skills declare the same pair on their `buf`/`debuf` maps inside a `sources[]` entry (R-32). The loader validates the pair and **excludes both keys from aggregation** (R-20, R-35): they are convention metadata, never damage-formula keys. |
| R-44 | The bundled reference character set (and the data behind the sample objective) is authored from **user-extracted** wiki data taken from the Stella Sora wiki pages forチトセ, アヤメ, テレサ; the extract is kept **in the repo workspace only as authoring source** (`wiki_data/`, git-ignored — see §8), so the tool and the build never fetch from the wiki and the wheel's provenance is the authored YAML itself. |

Notes:

* **R-35 (one vocabulary):** two plugins disagreeing about what `Atk_multiplier` means
  (additive vs multiplicative), or what a gated value counts, is otherwise invisible - so there is
  exactly one documented table, in `PLUGINS.md` and the built-ins, `--show-params` prints the
  aggregated map to make mismatches visible, and unknown keys are never silently applied by the
  kernel (R-33). The R-43 `duration`/`activation` pair removes most of the remaining guesswork.
* **R-36 (typed `scenario:`, not plugin-only enemy constants):** DEF/RES/PEN/VUL/break are part of
  the damage formula and identical for every plugin, so they belong to the run config and are
  diffable via `--show-params`; only genuinely plugin-specific knobs go to `objective_opts:`.
  Formula terms that are not defined in game (`IGNORING`, `generalDmg`, `generalDmgTaken`,
  `dmgPlus`, `dmgPlusTaken`, `finalDmg`, `finalDmgPlus`, `perkIntensity`, `talentGroup*`,
  `skillAbsAmend`) are not exposed as scenario input, so users cannot set meaningless values;
  they stay at their neutral kernel defaults.
* **R-37 (tool-built `ctx`, not a plugin-side loader):** the contract must give the plugin the
  character/party data - some characters scale damage off HP or other base stats - and building it
  once per candidate inside the tool keeps that data free of re-parsing while still letting plugins
  bind their own extra constants by closure.
* **R-38 (per-talent breakdown):** the summed map of R-20 is convenient but lossy, and talent
  activation is gated on skill activation, so a timeline-style plugin must know *which* talent
  granted a buff. `ctx` therefore carries the per-talent breakdown resolved for the current `x`,
  and plugins never map `x` positions to talents themselves.
* **R-39 / R-31 (who owns gating and timelines):** the plugin does. 0.1.0 ships data only -
  resolved levels, the per-talent buffer breakdown, timing (R-30/R-37/R-38) - with no shared
  timeline helper and no condition DSL, because a DSL would drag marks, break state and status
  durations into the tool. Shared timeline helpers arrive with the 0.2.0 generalized objective (§9).
* **R-40 (role rules as prose over the four keys):** the game's role availability is intrinsic to
  the key names, so no per-role data keys are added; the plugin resolves the special cases
  (including sub-slot auto-skill characters) from the full party data of R-37.
* **R-41 (distinct party):** one name in two slots is an input error, not a silent duplicate - the
  loader rejects it at load time (exit 2), before any levels are involved.
* **R-42 (verbosity through `ctx`):** plugin progress prints must obey the user's `-v`, but plugins
  never see the parsed CLI, so the run's verbosity count and the template's `pout` already curried
  with it are injected into the per-candidate `ctx` of R-37. That gives plugins the same levels as
  the tool (R-28's `-v`/`-vv`) at no per-evaluation cost, and keeps click-cutter's
  `pout`/`Level` in `ssoptim.py` the single definition of verbosity.
* **R-43 (duration/activation as data, not a condition language):** the game states a buff's uptime
  and the skill that grants it, so those facts belong next to the level values and make a generic
  objective's uptime `min(duration, period)/period` instead of a per-plugin guess, shrinking
  `objective_opts:` to genuinely plugin-specific knobs. It stays a convention: the loader only
  range-checks it, unusual cases (stacking, first-cast-only) stay documented plugin-side factors,
  and no condition DSL is introduced. **Durations read as bands, not even steps:** the worked
  example states `{ 1: 10, 4: 12 }` as "10 s for levels 1-3, 12 s for 4-6", which an even step
  cannot produce (it would give 10.7/11.3 s), so the concrete example wins and only the *value*
  maps keep the even step. Levels below the first declared band take that band: a gated buff exists
  at every owned level, and 0 s would mean "no buff". If the pair is wrong, missing, or an
  unsupported case, it is optional - absent it the value keeps the R-39 reading with an
  `objective_opts:` fallback - and the loader validates what is there (`duration > 0`,
  `activation` one of the four skill keys) and `-v` names what it had to assume.
* **R-44 (wiki data as reference, never fetched):** the three wiki pages are the authoring source
  for the bundled set and the sample objective's model, but the extracted dump is git-ignored
  reference material in the workspace (`wiki_data/`; absent from a checkout), so the committed
  artifact is the authored YAML and the build/tool stay offline and self-contained. Reviewability
  of provenance is traded for a lean repo.

### CLI / IO

| ID | Requirement |
| --- | --- |
| R-25 | Input is a YAML config file **plus** CLI options; CLI options always take precedence. |
| R-26 | Required inputs: party, objective plugin, `total_level`. Optional: restrictions, character data sources, output path, solver knobs. |
| R-27 | Output is YAML (talent list per character with chosen levels) **plus** the objective value returned by the plugin. |
| R-28 | `-v/--verbose` (count) additionally prints the aggregated parameter dictionary and the objective value per evaluated candidate. |
| R-29 | Errors are non-zero exits with a message on stderr (exit-code table in §7). |

Notes:

* **R-25/R-26:** everything a run needs is reachable from either surface - the CLI so a player can
  try one party without a file, the config file so a saved party re-runs without retyping.
  CLI > config is the one precedence rule everywhere, including the `-v` count (R-42).
* **R-27/R-28:** the result YAML is machine-readable (talent names, chosen levels, the objective
  value the plugin returned) and the `-vv` view is the plugin author's diffing tool: it prints the
  aggregated key map and the objective value per candidate, which is what makes a wrong buffer
  assumption visible instead of guessable.

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
| `duration` (reserved) | number **or** sparse map (seconds) | Buff/debuff uptime of the value at that level: `{ 1: 10, 4: 12 }` = 10 s for levels 1–3, 12 s for 4–6, i.e. the **last declared anchor at or below the level** applies (level bands, not an even step); a bare number means the same duration at every level (R-43). |
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
4–6) is not reproducible by an even step; the reason it reads as a band is in §3's R-43 note.

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
* `restrictions` may also come from a separate `--restrictions FILE`: the file carries the
  same content as this block, and both spellings are accepted — a bare
  `main`/`sub1`/`sub2` mapping, or the whole block wrapped in one `restrictions:` key — so one
  file works with or without a full config. Merging is per slot and per key: `min`/`max` are
  replaced, and `talent_levels` entries are replaced **by name** (an entry whose name already
  exists in the config is overwritten, a new name is appended); positional entries without a
  name are appended, because they address no name to match on. Concatenating lists instead
  would let a config bound and a file bound for the same talent both survive and fight over
  the variable.

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
  infeasible fall back to a **deterministic greedy fill** — start at the lower bounds, promote
  the core talents with the smallest vector index until each member's core row sums to 2
  (R-04/R-16), then repeatedly add one level at the index whose one-level gain is largest,
  skipping any trial that breaks a row or a bound, ties broken by the smallest index, and an
  `at_most` run stopping as soon as no gain is positive. The rule is pinned here because the
  tests compare an exhaustive enumeration against this fill, so the fixture, the code and the
  tests must share one answer; the fill doubles as a testable reference solver and as the
  safety net for SciPy's constrained-integrality caveats.
- Objective call must be cheap (no YAML parsing per evaluation): the plugin receives
  pre-resolved level→value tables (R-19 interpolation is precomputed once, per talent, into a
  list indexed by level) through the `ctx` of R-37/R-38, already resolved for the current `x`
  — the plugin never maps `x` positions to talents itself.
- Maximization: the driver maximizes directly; plugins return larger = better (stated
  explicitly in `PLUGINS.md`, R-21/R-27). SciPy only minimizes, so the negation is a private
  detail inside `optimize.py` (see the R-09 note in §3): nothing outside that wrapper ever
  sees the negated number, and the greedy fill and `verify()` use the same wrapper.

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

Note (one-argument helpers): `plugins.py` keeps the per-candidate context in `plugins.ACTIVE`,
set on the `resolve_candidate(x, ctx)` call that precedes every objective call, and both
`aggregate_params` and `resolve_talent_params` take an **optional** `ctx` — an explicit one
always wins. That is what keeps the documented one-argument call form (`aggregate_params(x)`
inside a plugin) short: the SciPy driver evaluates one candidate at a time, so no per-evaluation
closure plumbing or extra arguments are needed, and the plugin still never maps `x` positions
to talents (R-37, R-38).

Shared helpers every plugin should use (all read the tool-built `ctx`; nothing re-parses YAML):

- `resolve_talent_params(x, ctx)` → the level-resolved view of the current candidate:
  per member slot, name-keyed levels plus the **per-talent** `talent → {key: value}`
  breakdown (R-38) — the breakdown is what timeline-style plugins need, to attribute a
  buff to the talent that granted it (the summed map alone cannot say that).
- `aggregate_params(x)` → `{key: Σ value}` over all owned talents at the chosen levels,
  including character-specific keys (R-20); identical to `ctx["aggregated"]`. The helpers take
  an optional `ctx` and otherwise read the **active candidate context** (`plugins.ACTIVE`), which
  is what keeps the documented one-argument call form working inside a plugin (see the note under the helper list).
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
non-goal). The 0.2.0 objective generalizes this shape (still without a real timeline) — see §9.

### 6.3 Sample plugin plan

The reference code we ship (built-ins in `objectives/` and examples in `plugins/`) is:

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
4. The **model data** for these samples is the bundled set itself (R-44): the three shipped
   characters (`ssoptim/characters/チトセ.yml`, `アヤメ.yml`, `テレサ.yml`) supply the skill
   percents, `cd`/`loop_time` and talent tables — including the `duration`/`activation` pair —
   that the sample objective is written against; see §8 for their provenance.
5. Later (§9, 0.2.0): promote `simple_dps` to a built-in `dps` objective and extend it with
   rotation overrides, more general CD/loop accounting, and shared timeline helpers
   (see §9).

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
| `--restrictions FILE` | `restrictions` | separate restrictions YAML: the 4.2 restrictions block itself, bare or wrapped in a `restrictions:` key; merged by talent name (see the notes under the table) |
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
verb is live in 0.1.0 and every README invocation (`ssoptim optimize …`) runs verbatim: README's
Usage section is the semver-pinned interface surface, and the template's verb-less `simple` form
would have made those documented invocations fail. The planned sub-commands only add sibling
commands to the same group.

Exit codes:

| Code | Meaning |
| --- | --- |
| 0 | feasible optimum written |
| 2 | usage/config error (missing party, missing budget, unparseable YAML, duplicate party characters R-41, unknown or out-of-range restriction R-15/R-16) |
| 3 | infeasible constraint set (e.g. budget < Σ mins, or mins > maxes) |
| 4 | plugin load failure / plugin raised |
| 5 | solver found no feasible point after `runs` restarts |

Notes:

* **Where the codes are mapped:** the owning modules raise their own class with the code attached
  — `InputError` 2 in `data.py`, `Infeasible` 3 in `constraints.py`, `PluginError` 4 in `plugins.py`,
  `NoFeasible` 5 in `optimize.py` — and `cli.py`'s `optimize` handler prints the message through
  `pout` and raises `SystemExit(code)`. Mapping at the command layer, not only inside `main()`,
  keeps this table testable through click's `CliRunner` (which invokes the command object, not the
  console-script wrapper) and gives the installed console script the same behaviour.
* **Exit 2 covers the restrictions surface:** an unknown or out-of-range restriction (R-15/R-16)
  and a duplicate party name (R-41) are both load-time input errors, resolved before the solver
  runs.
* **Exit 5 stays open as a test gap:** the greedy fill of §5 is complete enough that no fixture
  box currently fails it, so exit 5 is exercised at the class level with a stubbed solver; §10
  K-6 keeps that gap open.

## 8. Project structure

The tree follows click-cutter's generated layout (root `Makefile`, `tasks.py`,
`pyproject.toml`, `README.md`, `CHANGES.md`, `LICENSE`, `.gitignore`; package dir with
`__init__.py` + `cli.py` + `<cli_name>/` implementation package) and adds five extension
dirs: bundled data, built-in objectives, user plugin examples, tests, and the extracted
wiki-data dump (R-44), which is reference-only and not checked in.

```
ssoptim/                     # repo root = project "SSOptim"
├── .gitignore               # existing
├── CHANGES.md               # existing; semver2.0 entries, change-point markers
├── DESIGN.md                # this document
├── DamageCalculationParameters.md   # existing reference doc (kept)
├── LICENSE                          # existing (MIT, aoi mizma)
├── Makefile                         # click-cutter targets (build/venv/package/publish/clean)
├── MANIFEST.in                      # sdist manifest prunes tests/, characters/, plugins/, wiki_data/
├── README.md                        # user-facing: usage, config, plugins, install, dev
├── PLUGINS.md                       # detailed plugin development guide; its python blocks run in tests/test_plugins_doc.py
├── pyproject.toml                   # setuptools + setuptools-scm, [project.scripts] ssoptim = "ssoptim.cli:main"
├── tasks.py                         # invoke tasks mirroring the Makefile
├── wiki_data/                       # reference-only wiki extract (R-44): git-ignored, never committed,
│                                    #   never read at build or runtime; authoring source for ssoptim/characters/
├── characters/          # user data set (searched by the tool); <name>.yml
├── plugins/             # example/custom objective plugins; simple_dps.py is the shipped DPS sample (§6.3)
├── tests/               # pytest suite + fixtures tests/data/*.yml (excluded from wheel and sdist)
└── ssoptim/             # importable package (package_name = ssoptim)
    ├── __init__.py      # __version__ fallback from _version.py (setuptools-scm)
    ├── cli.py           # click definitions + main(); delegates every command to impl.cmd(kwargs)
    ├── characters/      # bundled default character set (package data, loaded via importlib.resources)
    │   └── <charname>.yml
    └── ssoptim/         # implementation subpackage (cli_name = ssoptim)
        ├── __init__.py
        ├── ssoptim.py   # cmd(kwargs): orchestration (the §3–§7 pipeline), no click, no IO formatting;
        │                #   keeps the template's pout + Level enum, the one verbosity definition (R-42)
        ├── data.py      # YAML loading, schema validation (R-30/R-41/R-43), scenario block (R-36), character/party model objects, data-dir resolution
        ├── talent.py    # sparse {level: value} → interpolated level→value tables (R-19), reserved duration/activation keys kept aside (R-43), per-talent breakdown + param aggregation (R-20, R-38)
        ├── damage.py    # damage kernel transcribing the game formula (R-24); apply-everything (R-33)
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

Notes:

* **Package data, no VCS pickup:** `include-package-data = false` plus an explicit
  `[tool.setuptools.package-data]` naming `ssoptim/characters/*.yml`, so the wheel carries
  exactly the package modules plus the bundled character set; the test fixtures, the repo-root
  `characters/` and `plugins/` user dirs and the reference `wiki_data/` extract never ship. The
  bundled files are named after the in-game character names, which is what a `party:` block
  addresses, so an installed copy can run a first optimization with no user data at all. The
  sdist half needs the same control on the other side of the build: setuptools' sdist walks the
  VCS-tracked file list, so `MANIFEST.in` prunes `tests`, `characters`, `plugins` and `wiki_data`
  from that manifest (root-level names only, so the bundled `ssoptim/characters/` stays inside),
  and `tests/test_bundled.py` now enforces both halves - `TestWheelContents` on the `.whl`,
  `TestSdistContents` on the `.tar.gz`.
* **Data authoring (R-44):** the チトセ、アヤメ、テレサ wiki extract lives in the workspace under
  `wiki_data/` as **reference only** - git-ignored, never committed, and absent from a fresh
  checkout - so the committed artifact is the authored YAML in `ssoptim/characters/` and neither
  the build nor the tool ever reads `wiki_data/`.
* **Testing strategy:** pure functions at the `data`/`talent`/`constraints` boundaries (no SciPy
  needed), the SciPy driver tested against a deterministic exhaustive reference for a reduced
  fixture (with the pinned greedy fill of §5 as the reference answer), and the CLI tested via
  `click.CliRunner` on fixture YAML in `tests/data/`. `PLUGINS.md` doubles as a test: its python
  blocks run in document order against the fixture party and its documented console session is
  re-run and compared against the reported `objective:` value, so every number in the guide is
  the tool's own output (`tests/test_plugins_doc.py`).
* **`PLUGINS.md` as its own document:** the plugin contract (key selection, buffer ownership,
  timing data, the DPS shape, worked samples) is far more detailed than README's Usage section,
  which is the semver-pinned interface surface, so it lives in a document README links to and
  that grows with each new built-in objective (§9).
* **Versioning:** semver 2.0, pre-1.0.0 alpha while in development; `CHANGES.md` uses the
  change-point markers above. What versioning tracks is README's Usage section - the `optimize`
  command and its options, plus the `ssoptim.yml`, character-data and result-YAML formats
  documented in §4.

## 9. Planned work (0.2.0 and later)

Milestones M0–M8 — scaffold, data/talent loaders, the vendored damage kernel, the built-in
objective plus the DPS sample plugin, constraint generation, the solver driver, the full CLI
and report surface, the bundled character set, and `PLUGINS.md` — are implemented and
committed, so their rows are no longer part of this plan; the requirements they realised are
§3's, and the behaviour they pinned is §4–§8. What remains stays independently testable and
lands with docs/changelog updates.

| M | Deliverable | Acceptance criteria |
| --- | --- | --- |
| M9+ | Extra built-in objectives — `dps` promoted from `plugins/simple_dps.py` with the §6.2 shape generalized (rotation overrides, more general CD/loop accounting), single-skill and ult objectives — shared timeline helpers for gating-minded plugins, and the planned sub-commands (`chars`, `plugins`, `eval`) | each new objective is documented in `PLUGINS.md` §"Built-in objectives" and registered in `objectives/`; `PLUGINS.md` is extended in place and stays executable by `tests/test_plugins_doc.py`; each new verb is a sibling command in the same click group and lands with README's Usage surface and exit-code table |

Notes:

* **Multi-scenario runs stay deferred** (the `scenarios:` list): the priority for the second
  release is a more general *objective* that folds CD/loop time into the score — still a
  simplified calculation with no real timeline, since buff durations are data (R-43) and what
  M9+ ships is a shared timeline helper, not a simulator.

## 10. Known issues — open at the current milestone set (M0–M8 committed)

Not defects to fix before release, but the divergences and gaps the M0–M8 work left standing;
each is where a follow-up milestone or a documentation change has to land. Data-set
incompleteness is handled the same way: the tool validates and names missing characters
explicitly, and README's Known Issues lists the shipped set.

| # | Issue | Where it bites today | What would close it |
| --- | --- | --- | --- |
| K-2 | **Free-form keys the built-ins do not read**: the bundled characters carry mechanics keys outside the documented vocabulary (`extraSkillPct`, `extraAutoAttackPct`, `extraUltimatePct`, `elemAquaDmgTaken`, `Atk_multiplier_ally`, `Atk_multiplier_cond`, `Atk_multiplier_aqua`, `slotSkillCdMod`, `duration_mod`, `shield_absorb_pct`, `shield_duration_pct`, `spGain`, `break_penMod`, `stun_duration`) | they load, validate and aggregate (R-20) but neither `auto_attack` nor the shipped `simple_dps` consumes them, so those talents do not move the built-in objective value | a plugin reads them (they are visible in `ctx["aggregated"]` and in the per-talent breakdown), or a later built-in models them; the keys are listed in `PLUGINS.md` as "passed through, plugin-interpreted" |
| K-3 | **`activation` vocabulary is too small for the authored data** (R-43 fixes exactly the four skill keys): dodge-triggered buffs (チトセ's 石穿's dance) are authored with `activation: auto_skill` as the closest legal value, flagged in the YAML comment | an uptime-derived value for those talents is approximate for a gating-minded plugin | extend the pair's reading (e.g. a fifth `dodge`/`avoid` activation name plus the data validation that follows in R-43) or keep it plugin-side |
| K-4 | **Stack caps are comments only**: "10 stacks", "20 stacks", "3 stacks" appear as YAML comments, not as data | a plugin sees the per-talent value but cannot cap stacks or know their rate | add an authored cap field (e.g. `stacks:` as a level map, kept out of the aggregate like the R-43 pair) and document it next to `duration`/`activation` |
| K-5 | **The built-in objective is single-target, main-slot only**: `auto_attack` scores the main's auto skill alone (support `sub_skill`, sub-slot `auto_skill`, ult portions and marks are untouched), and 0.1.0 ships no built-in DPS (§9) | party-wide support buffs do move the score through the aggregated map (R-20), but support *damage* never does | the §9 `dps` built-in or the shipped `simple_dps` external plugin, which already reads both slots' timing data |
| K-6 | **Exit 5 has no end-to-end trigger**: `NoFeasible` (§7's exit 5) is exercised only at the class level with a stubbed solver, because the greedy fill is complete enough that no fixture box currently fails it | a user could see a different exit than the table promises on a box we have not built | construct (or keep searching for) a constraint set that `check_feasible` accepts and both the DE restarts and the greedy fill fail, then assert exit 5 through the CLI |
| K-7 | **Release-tooling targets are unverified here**: `README.md` Development's PyInstaller freeze and the `tasks.py`/Makefile `freeze`/`package`/`publish`/`pubtest` paths were not exercised in this environment (only `uv build` and an isolated `uv pip install` from the wheel) | a built `dist/ssoptim(.exe)` and a published sdist are untested artefacts | run `tasks.py freeze`/`package`/`publish` once the release is planned (MANIFEST.in's sdist pruning is already in place, so `publish` ships the pruned tarball) |
| K-8 | **Planned-not-implemented milestones**: M9+ (extra built-in objectives, the bundled `dps` promotion, `chars`/`plugins`/`eval` sub-commands, multi-scenario runs) stay out of 0.1.0 by design | the CLI group registers exactly one command (§7), so the README's planned verbs are not callable | the §9 milestones, unchanged plan |
| K-9 | **The `duration`/`activation` pair resolves per talent, not per key**: R-43 puts the pair inside one key's level map, but `talent.py` keeps one pair per talent record and `plugins/simple_dps.py` applies it to every key of that talent | a talent that mixes a gated key and an ungated key in one entry gates **both** in a gating-minded plugin; the authored data pairs them per talent, so no shipped example is wrong today | move the pair into the key's own level map in `talent.py`'s table build and read it per key in `simple_dps`, or restate R-43/§4.1 and `PLUGINS.md` in favour of the coarser per-talent reading |
| K-10 | **A `duration` level-map entry of 0 is accepted** (`talent.py` rejects negatives and an all-zero table only) while §4.1 requires `duration > 0` | a zero band yields 0 uptime for that band silently instead of a loader error, which contradicts the §3 rule that levels below the first band inherit it | tighten the validation to reject a zero band, or document 0 as "no buff at that level" in §4.1/R-43 |
| K-11 | **Unknown keys are fatal, not tolerated**: §4.1 promises unknown-key tolerance is never fatal, but an unknown `scenario:` key (`data.py`), an unknown top-level config key (`cli.py`) and an unknown `restrictions.<slot>` key (`constraints.py`) all raise exit 2 | a typo in a run config aborts the run instead of warning with `-v` | split the rule in §4.1 (tolerant for character data, strict for the run config, which is where a typo matters) or downgrade those three sites to a `pout(Level.WARNING)` notice |
| K-12 | **Duplicate character definition: first definition wins** with a `-v` notice (`data.py`) | a name defined in both a user dir and the bundled set resolves by search order, and the shadowed definition is invisible without `-v` | state the shadowing rule in §4.2 next to `data_dirs`, or reject the duplicate as an input error |
| K-13 | **A plugin returning a non-numeric score is a plugin error** (exit 4, `plugins.py`) while §7's exit-4 row says only "plugin load failure / plugin raised" | a plugin that returns a tuple or a string fails with an exit code the table does not name, and `PLUGINS.md` never mentions the check | extend §7's exit-4 row and `PLUGINS.md` to "…or returned a non-numeric score" |
| K-14 | **Solver exceptions are swallowed into "no candidate"** (`optimize.py` catches anything a restart raises) whereas §5 describes only verify/repair | a SciPy failure looks like an infeasible box and continues into the greedy fill / exit-5 path instead of reporting the solver error | keep the exception visible (distinct exit or a named `-v` notice) and state that policy in §5/§7 |
| K-15 | **§8 says the bundled character set is loaded via `importlib.resources`**; `data.py` resolves the installed package's own path and globs `*.yml` | the documented mechanism does not match the code, so a reader looking for package-resource loading finds none | restate §8's annotation to the implemented lookup, or move `data.py` to `importlib.resources` |
| K-16 | **The `at_most` budget row** is documented in `optimize.py` as "reported separately and left out of the ineq set", but it is emitted as a negated ineq row | behaviour matches §5 (`Σ all <= total_level`), the module docstring contradicts the code | restate the docstring; §5 already matches the emitted row |
| K-17 | **The reduced fixture is broader than the deleted M5 wording suggested**: `tests/test_optimize.py` enumerates a 3-member party (one free sub-talent each, cap 4) over the real 48-variable layout, not the "2 chars, 4 sub levels" space the removed M5 milestone row named | the exhaustive-agreement test covers more than the milestone wording claimed, and that wording is gone from the document, so it can no longer be checked against the code | keep the broader fixture; record the fixture's shape in `tests/test_optimize.py` (already documented there) and do not restate it in §1–§8 |

**Resolved since the M0–M8 set:** **K-1 (sdist packaging asymmetry)** closed by `MANIFEST.in`
pruning `tests`, `characters`, `plugins` and `wiki_data` from the VCS-based sdist manifest - the
same dirs the wheel already excludes - so both halves of §8's packaging promise now hold and
`tests/test_bundled.py` enforces them from both sides (`TestWheelContents` on the `.whl`,
`TestSdistContents` on the `.tar.gz`).

`README.md`'s "Known Issues" section stays user-facing and short; this table is
the implementor's list.