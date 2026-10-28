# SSOptim — Design Specification

Status: **pre-implementation design spec** (version 0.1.0 T.B.D.)
Source of intent: [DesignGoals.md](DesignGoals.md) · damage reference: [DamageCalculationParameters.md](DamageCalculationParameters.md), [stella_sora_damage.py](stella_sora_damage.py)
Project structure basis: [click-cutter](https://github.com/koma75/click-cutter) (Click CLI cookiecutter template, `cli_type = simple`, `use_config_yaml = Yes`)

This document is the streamlined, decision-complete plan for building `ssoptim`.
It restates the goals as testable requirements, fixes the data/plugin/CLI contracts,
and defines the source tree. No implementation exists yet; §12 lists the order in which it will be built.

---

## 1. Purpose

`ssoptim` is a console tool that, for a **fixed party composition** in Stella Sora
(1 main + 2 support) and a **fixed budget of talent levels**, searches the space of
talent-level assignments and reports the assignment that maximizes a **pluggable
objective function** (typically expected damage / DPS of the main character).

Everything that is *not* the talent level distribution (character stats, skills, sigils,
enemy DEF/RES, rotation assumptions) is treated as constant input supplied by data files
and by the objective-function plugin.

## 2. Scope

**In scope**

- Talent-level optimization for a named party and a level budget.
- Data-driven character/skill/talent definitions (YAML).
- Pluggable objective functions (built-in + user-supplied files/modules, no rebuild).
- Constraint handling: core-talent selection, per-character totals, per-talent bounds.
- Machine-readable YAML result + human-readable console report.

**Out of scope** (explicit non-goals)

- Choosing *which* characters/talents to pull during a real build (random-pull simulation).
- Gear, sigils, duos, or anything other than the damage-formula parameters.
- A GUI/TUI, save-file import, or live game scraping.
- Accurate DPS modelling for every character: correctness of the objective is the
  plugin author's responsibility (see R-14/R-15).

## 3. Streamlined requirements

Requirement IDs are used throughout the rest of this document and will be cited in code,
tests, and `CHANGES.md` entries.

### Game model

| ID | Requirement |
| --- | --- |
| R-01 | A party is exactly one `main` character plus two support characters `sub1`, `sub2`. |
| R-02 | A character carries two independent talent sets: `talents_main` (role = main) and `talents_sub` (role = support). The set used depends only on the party slot. |
| R-03 | Each talent set has exactly **4 core** talents and **9 sub** talents. |
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
| R-12 | The search space is ~13 variables/character (≈39/party); runtime for one run must stay in the seconds-to-minutes range for the default target. |

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
| R-19 | A talent entry maps parameter key → `{level: value}`. Only levels that change need listing; **intermediate levels are interpolated evenly** between the two declared anchors (e.g. keys 1 and 6 imply a constant step for 2–5; level 0 contributes nothing). |
| R-20 | Talent parameter keys are free-form strings; they are *summed* across all owned talents at their chosen levels, including character-specific keys unknown to the damage kernel. |
| R-21 | An objective plugin is a callable `f(x, **party_kwargs) -> float`. `x` is the SciPy-style flat level vector; character data, party composition, and scenario constants are bound by the plugin author (closure/partial), not by the solver. |
| R-22 | Plugin references accept three forms: built-in short name (`auto_attack`), dotted module path (`pkg.mod:func`), and file path (`./plugins/my_calc.py:func`). Loading must work at runtime against a `pipx`/`uv tool install`ed copy — no package rebuild. |
| R-23 | A built-in default plugin must exist that computes **auto-attack skill damage** from the damage kernel; it is the reference implementation and the target of the doc examples. |
| R-24 | The damage kernel (DEF/RES/PEN/VUL/erAmend/defAmend, crit expectation, `is_dot`) is shared library code, unit-converted from YAML conventions via `skill_percent_to_amend`. |

### CLI / IO

| ID | Requirement |
| --- | --- |
| R-25 | Input is a YAML config file **plus** CLI options; CLI options always take precedence. |
| R-26 | Required inputs: party, objective plugin, `total_level`. Optional: restrictions, character data sources, output path, solver knobs. |
| R-27 | Output is YAML (talent list per character with chosen levels) **plus** the objective value returned by the plugin. |
| R-28 | `-v/--verbose` (count) additionally prints the aggregated parameter dictionary and the objective value per evaluated candidate. |
| R-29 | Errors are non-zero exits with a message on stderr (exit-code table in §8). |

## 4. Data schemas

### 4.1 Character file (`characters/<name>.yml`)

One file per character (or several characters per file, top-level key = character name).

| Key | Type | Notes |
| --- | --- | --- |
| `stats` | map | `Atk`, `HP`, `DEF`, … plain numbers; also readable by plugins that use HP-based scaling. |
| `auto_skill` / `main_skill` / `sub_skill` / `ult_skill` | map of damage-class → map | Damage classes are `elem{Aqua,Ignis,Terra,Ventus,Lux,Umbra}Dmg`, `slot{AutoAttack,Skill,Ultimate,Other,Mark,Projectile,Minion}Dmg`, plus free-form character-specific keys. Values are `{skillPercentAmend: …}` or scenario-specific numbers. |
| `skillPercentAmend` | number | Percent-of-Atk in **×100 percent** units, i.e. `11.30` ⇒ 1130 % of Atk. Kernel conversion: `skill_percent_to_amend(v * 100)`. |
| `talents_main` / `talents_sub` | list | Index 0–3 = core (`core_talent: true`), index 4–12 = sub. Order defines the variable order of that character (R-08, R-17). |
| `<param_key>` | map | `level: value`; sparse on the other side. Missing intermediate levels interpolated (R-19). |

Abbreviated example (documentation sample, not shipped source):

```yaml
<charname>:
  stats: { Atk: 6966, HP: 94662, DEF: 0 }
  auto_skill:
    elemLuxDmg: { skillPercentAmend: 11.30 }   # 1130 % of Atk
  talents_main:
    - talent_name: "Talent A"
      core_talent: true
      Atk_multiplier: { 1: 0.15 }              # +15 % at level 1 (core: 0/1 only)
    - talent_name: "Talent E"
      core_talent: false
      Atk_multiplier: { 1: 0.045, 6: 0.18 }    # 2–5 interpolated evenly
      slotSkillDmg: { 6: 0.10 }
  talents_sub:
    # same shape; used when the character sits in sub1/sub2
```

Validation rules the loader must enforce: 4 core + 9 sub per set, unique `talent_name`,
level keys ⊂ 0–6 (core ⊂ 0–1), numeric values, and unknown-key tolerance (never fatal).

### 4.2 Party / run config (`ssoptim.yml`, `--config`)

```yaml
party:
  main: "<character name>"
  sub1: "<character name>"
  sub2: "<character name>"
data_dirs: [ "./characters" ]      # searched before the bundled set
target: auto_attack                # plugin spec (R-22)
total_level: 65
total_level_mode: exact            # exact | at_most
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

### 4.3 Result file (`--out`, default stdout)

```yaml
target: auto_attack
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

`--show-params` (implied by `-vv`) appends `aggregated_params:` — the summed key/value map
the plugin received — so plugin authors can diff their assumptions against reality.

## 5. Optimization model

Variables (per party member, from YAML order):

```
x[char][i]  core i∈0..3 : bounds [0,1]
            sub  i∈4..12: bounds [0,6] → tightened by user min/max (bounds, not constraints)
```

Constraints, all generated (never hand-written), integer coefficients:

| Source | Constraint |
| --- | --- |
| R-04/R-17 | `Σ core[char][0..3] == 2` for each of main, sub1, sub2 |
| R-13 | `Σ all == total_level` (or `<=` when `at_most`) |
| R-14 | `min_char <= Σ char <= max_char` |
| R-15 | expressed as variable bounds |
| R-16 | core pinning via `min: 1` on the pinned talents |

Solver driver:

- `differential_evolution(bounds, constraints=..., integrality=True, polish=True, maxiter, popsize, seed, init='sobol')`.
- `runs` restarts with different seeds; keep the best **feasible** result (tolerance 1e-6).
- Repair/verify pass after solving: round to integers, re-check every constraint, and if
  infeasible fall back to a greedy fill (start from user mins, add levels while improving) —
  this doubles as a testable reference solver and as the safety net for SciPy's constrained-integrality caveats.
- Objective call must be cheap (no YAML parsing per evaluation): the plugin receives
  pre-resolved level→value tables (R-19 interpolation is precomputed once, per talent,
  into a list indexed by level).
- Maximization: driver maximizes directly; plugins return larger = better (documented).

## 6. Plugin contract

```python
# plugin signature (author's side; shown for contract definition only)
def objective(x) -> float:            # x: flat integer level vector, order per R-08
    ...
```

Resolution rules (`plugins.py`):

| Spec form | Resolution |
| --- | --- |
| `auto_attack`, … | registry in `ssoptim/ssoptim/targets/` |
| `pkg.mod:func` | `importlib.import_module` |
| `./path/file.py:func` | `importlib.import_module` via `spec_from_file_location` |

Built-ins are importable submodules so the built-in set can grow without touching
`pyproject.toml`; user plugins live outside the package (repo `plugins/` dir is the
convention) and are loaded by path — satisfying R-22 for a `pipx`-installed tool.

Shared helpers every plugin should use:

- `aggregate_params(x)` → `{key: Σ value}` over all owned talents at the given levels,
  including character-specific keys (R-20).
- `resolve_talent_value(talent, level)` → interpolated value (R-19).
- `damage.calculate_damage(...)` (R-24) for the damage-kernel terms; plugins own
  skill selection, multi-hit counts, cooldown windows, and any character-specific
  simulation (e.g. turning a character-specific key into per-interval applications).

## 7. CLI surface

```
ssoptim [-h] [--version] COMMAND ...
ssoptim optimize [-c CFG] [-m MAIN] [-s SUB1 ...] [-t N] [-f TARGET]
                 [--char DIR|FILE ...] [--restrictions FILE]
                 [--total-level-mode exact|at_most] [-o OUT.yml]
                 [--target-opts KEY=VAL ...] [--show-params]
                 [--maxiter N] [--popsize N] [--runs N] [--seed N] [--no-polish]
                 [-v ...]
```

| Option | Config key | Notes |
| --- | --- | --- |
| `-c, --config CFG` | (root file) | default `./ssoptim.yml`; created with the schema of §4.2 on first run if absent |
| `-m, --main NAME` | `party.main` | party override |
| `-s, --sub NAME` | `party.sub1/sub2` | repeatable, exactly twice, fills in order |
| `-t, --total-levels N` | `total_level` | mandatory (config or CLI) |
| `-f, --target SPEC` | `target` | plugin spec, default `auto_attack` |
| `--char PATH` | `data_dirs` | repeatable file or dir; searched before bundled data |
| `--restrictions FILE` | `restrictions` | separate restrictions YAML (merges over config) |
| `-o, --out FILE` | — | default: stdout YAML only |
| `--show-params` | — | dump aggregated params (same as `-vv`) |
| `--maxiter/--popsize/--runs/--seed/--no-polish` | `solver.*` | solver knobs |
| `-v, --verbose` | — | count: `-v` warnings, `-vv` per-evaluation objective + params |
| `-h/--help`, `--version` | — | version from `ssoptim.__version__` |

Precedence: CLI > `--restrictions` file > `--config` file > built-in defaults.
Sub-commands other than `optimize` (e.g. `chars`, `plugins`, `eval`) are **planned, not in 0.1.0**;
the single-command `simple` form of click-cutter is therefore used, with `optimize` as the
named verb for clarity once sub-commands land.

Exit codes:

| Code | Meaning |
| --- | --- |
| 0 | feasible optimum written |
| 2 | usage/config error (missing party, missing budget, unparseable YAML) |
| 3 | infeasible constraint set (e.g. budget < Σ mins, or mins > maxes) |
| 4 | plugin load failure / plugin raised |
| 5 | solver found no feasible point after `runs` restarts |

## 8. Project structure

The tree follows click-cutter's generated layout (root `Makefile`, `tasks.py`,
`pyproject.toml`, `README.md`, `CHANGES.md`, `LICENSE`, `.gitignore`; package dir with
`__init__.py` + `cli.py` + `<cli_name>/` implementation package) and adds four extension
dirs: bundled data, built-in targets, user plugin examples, tests.

```
ssoptim/                     # repo root = project "SSOptim"
├── .gitignore               # existing
├── CHANGES.md               # existing; semver2.0 entries, change-point markers
├── DESIGN.md                # this document
├── DamageCalculationParameters.md   # existing reference doc (kept)
├── DesignGoals.md                   # intent doc (kept)
├── LICENSE                          # existing (MIT, aoi mizma)
├── Makefile                         # click-cutter targets (build/venv/package/publish/clean)
├── README.md                        # user-facing: usage, config, plugins, install, dev
├── pyproject.toml                   # setuptools + setuptools-scm, [project.scripts] ssoptim = "ssoptim.cli:main"
├── tasks.py                         # invoke tasks mirroring the Makefile
├── stella_sora_damage.py            # scratch reference; vendored into the package at M2, then deleted
├── characters/          # user data set (searched by the tool); <name>.yml
├── plugins/             # example/custom objective plugins; <name>.py
├── tests/               # pytest suite + fixtures tests/data/*.yml (excluded from wheel)
└── ssoptim/             # importable package (package_name = ssoptim)
    ├── __init__.py      # __version__ fallback from _version.py (setuptools-scm)
    ├── cli.py           # click definitions + main(); delegates every command to impl.cmd(kwargs)
    ├── characters/      # bundled default character set (package data, loaded via importlib.resources)
    │   └── <charname>.yml
    └── ssoptim/         # implementation subpackage (cli_name = ssoptim)
        ├── __init__.py
        ├── ssoptim.py   # cmd(kwargs): orchestration (§9 step list), no click, no IO formatting
        ├── data.py      # YAML loading, schema validation, character/party model objects, data-dir resolution
        ├── talent.py    # sparse {level: value} → interpolated level→value tables (R-19), param aggregation (R-20)
        ├── damage.py    # damage kernel, vendored from stella_sora_damage.py (R-24)
        ├── plugins.py   # plugin spec resolution + registry (R-22)
        ├── targets/     # built-in objective functions
        │   ├── __init__.py   # REGISTRY = {"auto_attack": ...}
        │   └── auto_attack.py# default objective (R-23)
        ├── constraints.py # bounds + LinearConstraint builder from data/config (R-04..R-16)
        ├── optimize.py    # differential_evolution driver, restarts, verify/repair fallback (R-08..R-12)
        └── report.py      # result YAML + console rendering (R-27..R-29)
```

Module dependency direction (must not cycle):

```
cli.py → ssoptim/ssoptim.py → {data.py, talent.py, plugins.py/targets, constraints.py, optimize.py, report.py}
optimize.py → targets/* → {talent.py, damage.py, data.py}
```

Naming/package facts fixed here:

- `project_name = SSOptim`, `package_name = ssoptim`, `cli_name = ssoptim`
  → entry point script `ssoptim = "ssoptim.cli:main"`, console command **`ssoptim`**.
- `requires-python = ">=3.12"`; `dependencies`: `click>=8.1,<9`, `PyYAML>=6,<7`, `scipy>=1.11,<2`, `numpy` (via scipy).
- `optional-dependencies.dev`: `pyinstaller`, `build`, `twine`, `pytest`.
- setuptools-scm supplies `__version__`; `dynamic = ["version"]`.
- File headers follow click-cutter: shebang, coding line, `Copyright (c) 2026 aoi mizma <aoi@mizma.example>`,
  `SPDX-License-Identifier: MIT`.
- Data is *not* compiled into the wheel beyond a convenience seed set; plugins are never
  compiled in beyond built-ins (R-22 extensibility without rebuild).

## 9. Implementation plan

Each milestone is independently testable and lands with docs/changelog updates.

| M | Deliverable | Acceptance criteria |
| --- | --- | --- |
| M0 | click-cutter scaffold: `pyproject.toml`, `Makefile`, `tasks.py`, package dirs, `--version`/`--help` work, editable install via `uv` | `ssoptim --version` prints `0.0.0+dev`/`0.1.0`; wheel builds with `uv build` |
| M1 | `data.py` + `talent.py`: YAML load, schema validation, interpolation tables | loader round-trips §4.1 sample; interpolation of 1↔6 keys matches the even-step rule; invalid data fails with R-29 exit 2 |
| M2 | `damage.py` vendoring of `stella_sora_damage.py`; unit conversion helper | vendored file reproduces the gist sanity table already printed by the scratch file |
| M3 | `targets/auto_attack.py` + `plugins.py` aggregation path | default objective on a fixed 3-char fixture equals a hand-computed value from §4.1 constants |
| M4 | `constraints.py` bounds/constraint generation | generated matrices verified by direct check of R-04, R-13, R-14, R-15 on fixtures; infeasible inputs flagged (exit 3) |
| M5 | `optimize.py`: `differential_evolution` + verify/repair | on the fixture, the optimum matches the brute-force enumeration of the reduced (2 chars, 4 sub levels) space; all constraints hold |
| M6 | `cli.py` + `report.py`: options, precedence, YAML out, exit codes | README's documented invocation runs end-to-end and writes §4.3 YAML; precedence test: CLI overrides config |
| M7 | Packaging/CLI polish, built-in char data set, `plugins/` examples, pytest suite green, `tasks.py`/Makefile wired | `uv build` + `pipx install ssoptim` yields a working `ssoptim optimize …` with `--config` defaults |
| M8+ | Extra built-in targets (single skill, ult, cooldown DPS), planned sub-commands (`chars`, `plugins`, `eval`) | each new target documented in README §"Objective plugins" and registered in `targets/` |

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
| Data set incompleteness (only some characters authored) | data lives in `characters/` and `ssoptim/characters/`; tool validates and names missing characters explicitly; README "Known Issues" lists the shipped set |

## 11. Decisions (with rationale)

1. **Differential evolution** over brute force/ILP: objective is opaque, non-linear, and
   combinatorially ~1e25 for a 3-character party, but evaluation is cheap.
2. **Per-talent bounds instead of constraints** for R-15: keeps the bound box tight, which
   DE needs for integrality to behave.
3. **Exact-sum budget by default** with `at_most` opt-in: matches the game's "levels
   available" mental model while permitting non-monotone objectives.
4. **Keyed restrictions by talent name** (positional also accepted): name keys survive
   data-file reordering; positional keys keep compatibility with the DesignGoals sketch.
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

## 12. Open questions (resolve before M6)

1. Is `objective` always "bigger is better"? (Assumed yes; plugin docs must state it.)
2. Do skill-hit counts/cooldown windows belong to the plugin (assumed) or to a shared
   rotation model (not in 0.1.0)?
3. Should the tool ever enforce a per-character minimum automatically (the game's
   "main talents appear more often" bias) or leave it purely to R-14?
4. Multi-scenario runs (several DEF/RES enemy profiles in one invocation) — deferred to
   0.2.0 as `scenarios:` list reusing the same constraint matrix.
