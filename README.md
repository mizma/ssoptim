# SSOptim

Stella Sora Party build optimization tool

`ssoptim` optimizes **talent level distribution** for a fixed party composition
(one main character + two support characters) when a fixed number of talent levels
is available. Because party composition changes the optimization objective drastically,
the objective ("what number are we maximizing?") is a **pluggable calculation module**
— built-in defaults plus user-supplied modules that can be dropped in next to an
installed copy of the tool without rebuilding it.

> **Status:** 0.1.0 in development (M0–M8 implemented, test suite green). The CLI below is the
> 0.1.0 interface;
> see [DESIGN.md](DESIGN.md) for the design and requirements (it restates the game-spec rules the
> design depends on) and [PLUGINS.md](PLUGINS.md) for the objective-module contract.

## Installation

~~~console
> pip install ssoptim
~~~

Or, for a self-contained CLI environment (the assumed usage model — plugins are loaded at
runtime from your own files, so no rebuild is needed):

~~~console
> pipx install ssoptim
> uv tool install ssoptim
~~~

## Usage

~~~console
> ssoptim optimize --config ./my_party.yml -t 65 -f auto_attack -o result.yml -v
~~~

The party can also come entirely from the command line:

~~~console
> ssoptim optimize -m "Char A" -s "Char B" -s "Char C" -t 65 -f ./plugins/my_calc.py:objective -vv
~~~

Enemy profile and plugin knobs override the config file, and the shipped DPS sample is
loaded by path:

~~~console
> ssoptim optimize --config ./my_party.yml -t 65 -f ./plugins/simple_dps.py:objective \
>                  --scenario DEF=350 --scenario RES=570 --objective-opts uptime_fraction=0.6 \
>                  --show-params -o result.yml
~~~

* -c, --config CFG
  * CFG: Path to Configuration File (default: ssoptim.yml) — carries party, budget,
    objective and restrictions
* -m, --main MAIN
  * MAIN: main character name (overrides `party.main`)
* -s, --sub SUB
  * SUB: support character name; repeat exactly twice, fills `sub1` then `sub2`
* -t, --total-levels N
  * N: total talent levels available to distribute (mandatory, unless given in the
    config file)
* -f, --objective SPEC
  * SPEC: optimization objective module/function — `auto_attack` (default), a dotted
    module path `pkg.mod:func`, or a file path `./plugins/my_calc.py:func`
* --char PATH
  * PATH: character data file or directory; repeatable, searched before the bundled
    character set
* --restrictions FILE
  * FILE: YAML file of optimization restrictions (merged over the config file);
    the file holds the same block as the Configuration file's `restrictions:` key -
    either the bare `main`/`sub1`/`sub2` mapping, or the whole block wrapped in a
    `restrictions:` key. Entries name a talent, so a name given in both places is
    the file's entry that wins; a name only in the file is added.
* --total-level-mode {exact,at_most}
  * exact (default): the chosen levels must sum to the budget; at_most: levels may
    go unused when the objective stops improving
* -o, --out OUT
  * OUT: write the result YAML to this path (default: stdout)
* --scenario KEY=VAL
  * KEY=VAL: per-key override of the enemy profile (`DEF`, `RES`, `PEN`, `VUL`,
    `enemyBreakStatus`, `resilienceBreakDmg`, …); repeatable
* --objective-opts KEY=VAL
  * KEY=VAL: free-form plugin-specific constants handed to the objective module
    (e.g. `uptime_fraction=0.6` for a condition-gated buff); repeatable
* --show-params
  * also dump the aggregated talent-parameter dictionary and the effective enemy
    scenario the objective received
* --maxiter N --popsize N --runs N --seed N --no-polish
  * SciPy Differential Evolution knobs (`runs` = seeded restarts, best feasible kept)
* -v, --verbose
  * verbosity count: `-v` warnings, `-vv` per-evaluation objective values and parameters
* -h, --help, --version
  * help / version (`0.0.0+dev` from a bare checkout, otherwise the built version)

Precedence: command-line options override the `--restrictions` file, which overrides the
`--config` file, which overrides built-in defaults.

### Exit codes

| code | meaning |
| --- | --- |
| 0 | optimum found, constraints satisfied |
| 2 | usage / config error (missing party, missing budget, bad YAML, unknown or out-of-range restriction) |
| 3 | input constraints are infeasible (budget below the specified minimums, etc.) |
| 4 | objective module could not be loaded or raised an error |
| 5 | solver returned no feasible point after all restarts |

### Configuration file

YAML based configuration file (default file name: `ssoptim.yml`) is used to store
settings for the tool. Command line options take precedence over the configuration
parameters. A default file is written on first run when none exists.

~~~yaml
party:
  main: "Char A"
  sub1: "Char B"
  sub2: "Char C"
data_dirs:
  - ./characters
objective: auto_attack
total_level: 65
total_level_mode: exact
scenario:                 # enemy profile; unspecified keys keep the kernel defaults
  DEF: 500
  RES: 750
  res_table: { Lux: 250, default: 750 }   # optional per-element weakness table
  PEN: 0
  VUL: 0
  enemyBreakStatus: false
  resilienceBreakDmg: 1.5
objective_opts:          # free-form constants for the objective module
  uptime_fraction: 0.6
restrictions:
  main:
    min: 30
    max: 40
    talent_levels:
      - name: "Core Talent 1"     # pins core selections; exactly 2 per member
        min: 1
      - name: "Core Talent 2"
        min: 1
      - name: "Sub Talent Z"      # ordinary per-talent bounds
        min: 2
        max: 4
  sub1:
    min: 10
  sub2:
    min: 10
    max: 20
solver:
  maxiter: 300
  popsize: 24
  runs: 3
  seed: 1
  polish: true
~~~

Notes:

* Core talents are always the first four entries of a character's talent set and have
  only level 0/1; the tool always enforces "exactly 2 per member", so pinning two core
  talents with `min: 1` forces the other two off.
* `talent_levels` entries may also be written positionally (no `name:`), aligned to the
  character's talent declaration order.
* `data_dirs` is where character YAML files are looked up; the bundled set inside the
  installed package is searched last.

### Character data

Character stats, skills and talents are plain YAML, one top-level key per character
(`characters/<charname>.yml` or several characters per file):

~~~yaml
"Char A":
  stats: { Atk: 6966, HP: 94662, DEF: 0 }
  auto_skill:
    loop_time: 4.20                    # seconds per auto-attack cycle (measured)
    damage:
      elemLuxDmg:
        skillPercentAmend: 11.30       # 1130 % of Atk
  main_skill:
    cd: 12.0                           # active-skill cooldown (game spec)
    damage:
      elemLuxDmg:
        skillPercentAmend: 8.90
  sub_skill:
    cd: 10.0                           # active skill when the character is in support
    damage:
      elemLuxDmg:
        skillPercentAmend: 5.00
  ult_skill:
    sources:                           # damage portions calculated separately
      - name: hit
        damage: { elemLuxDmg: { skillPercentAmend: 20.00 } }
      - name: mark
        cd: 6.0                        # this portion has its own period
        damage: { slotMarkDmg: { skillPercentAmend: 1.22 } }
  talents_main:                   # first 4 = core, rest = sub
    - talent_name: "Core Talent 1"
      core_talent: true
      Atk_multiplier:
        1: 0.15
    - talent_name: "Core Talent 2"
      core_talent: true
    - talent_name: "Sub Talent Z"
      core_talent: false
      Atk_multiplier:
        1: 0.045
        6: 0.18                   # levels 2-5 interpolated evenly
        duration: { 1: 10, 4: 12 } # buff uptime in seconds (same interpolation rule)
        activation: main_skill     # which skill's use grants it
  talents_sub:                    # used when the character is in sub1/sub2
    - talent_name: "…"
~~~

* Level-keyed values are sparse; intermediate levels are inferred as an even step
  between the declared anchors, and level 0 adds nothing. Level 0 counts as an anchor, so a map
  with one anchor ramps up from 0; levels **above** the last declared anchor keep that anchor's
  value (no extrapolation) — e.g. `{6: 0.10}` is ≈0.0167 at level 1 … 0.10 at level 6.
* Parameter names are free-form. Character-specific keys (e.g. a signature-mechanic
  value) are allowed; they are passed through to the objective module untouched.
  A documented key convention maps the common buffers to formula arguments
  (`Atk_multiplier`, `Atk_absMod`, `critDmgMod`, `crit_rateMod`, `slot{X}Dmg`,
  `slot{X}CritDmg`, `elem{E}Dmg`, `DEF_rate_mod`, `RES_rate_mod`); see
  [PLUGINS.md](PLUGINS.md) for the full table.
* `cd` (active skills, from the game's character spec) and `loop_time` (auto skill,
  measured from gameplay/video analysis) are seconds of **data**: the tool validates and
  forwards them, and the objective module decides how they become DPS. They are optional;
  without them a DPS-minded objective falls back to per-hit damage and says so with `-v`.
* Buff/debuff values may carry the reserved keys `duration` (seconds, sparse and
  read as **level bands** — the last declared band at or below the level, so
  `{ 1: 10, 4: 12 }` is 10 s at levels 1-3 and 12 s at 4-6) and `activation` (strictly
  `auto_skill`/`main_skill`/`sub_skill`/`ult_skill`)
  inside the same map as the level keys — `Atk_multiplier: { 1: 0.045, 6: 0.18, duration: { 1: 10, 4: 12 }, activation: main_skill }`
  means 10 s at levels 1-3 and 12 s at 4-6, granted by the main skill. Skills use the same
  pair on their `buf`/`debuf` maps. The two keys are convention metadata: the loader validates
  them and keeps them **out** of the aggregated parameter map, and a generic objective derives a
  gated buff's uptime as `min(duration, period) / period` for the activating skill — the
  `objective_opts.uptime_fraction` fallback is only needed where the pair is absent.
* A skill may split into `sources:`, each with its own damage type, its own `cd`/`loop_time`
  and optional `dot: true`; each source is damage-calculated separately with only the buffers
  that apply to it and the results are added. A skill with a single portion may still use the
  shorthand `damage:` map. When loading, the shorthand is normalized to a single-element
  `sources:` list inheriting the skill-level timing, so objective modules always see one shape.
* Skill-role availability is fixed by the key names, not by extra keys: the `main` slot uses
  `auto_skill` + `main_skill` + `ult_skill`; a support slot uses `sub_skill` + `ult_skill` and
  its own `auto_skill` (some characters act from support with the auto skill) — never
  `main_skill`. The objective module decides which of them feed its number.
* `skillPercentAmend` in character files is percent-of-Atk (×100 percent units);
  it is converted to the in-game unit by the tool.

### Output

~~~yaml
objective_plugin: auto_attack
total_level: 65
objective: 1234567        # value the objective module returned for this distribution
feasible: true
party:
  main:
    core_talents: ["Core Talent 1", "Core Talent 2"]
    talent_levels:
      "Core Talent 1": 1
      "Core Talent 2": 1
      "Sub Talent Z": 4
  sub1:
    core_talents: ["…", "…"]
    talent_levels: { … }
  sub2:
    core_talents: ["…", "…"]
    talent_levels: { … }
~~~

`objective_plugin:` names the plugin spec that was run; `objective:` is the value that plugin
returned. With `-vv`, the aggregated parameter dictionary (every talent key summed at the chosen
levels, including character-specific keys) is appended as `aggregated_params:`, together with the
effective `scenario:` values.

### Objective plugins

An objective module is any callable that takes the flat level vector **plus the data
context the tool builds for it**, and returns a number (bigger = better):

~~~python
def objective(x, ctx) -> float:
    # x   = main character's talent levels, then sub1, then sub2,
    #       each in the order declared in its character file
    # ctx = per-slot character objects (stats, skills, talents),
    #       resolved levels, per-talent buffers, aggregated buffers, scenario
    ...
    return expected_dps
~~~

`ctx` is built by the tool for every candidate, so the plugin never maps `x` positions to
talents and never re-reads YAML. Its contents (see [PLUGINS.md](PLUGINS.md) for the full
contract): `ctx["members"]["main"|"sub1"|"sub2"]` (full character data, incl. `HP` for HP-scaled
mechanics, skill blocks with `cd`/`loop_time`/`sources`, the talent set in use),
`ctx["members"][slot].talent_params` (per-talent `talent → {key: value}` at the current levels —
what a timeline-style plugin needs to attribute a buff), `ctx["aggregated"]` (the summed map),
`ctx["scenario"]` (enemy profile), `ctx["objective_opts"]` (plugin knobs from `--objective-opts`), and
`ctx["verbose"]` / `ctx["log"]` (the run's `-v` count, and the `pout` printer already bound to it).
Plugins may still bind their own extra constants by closure or `functools.partial`.

Helpers the tool provides: `resolve_talent_params(x, ctx)` (the level-resolved view above),
`aggregate_params(x)` (sum of all same-key talent parameters at the chosen levels),
`resolve_talent_value(talent, level)` (interpolated level value), the `damage` kernel
(`calculate_damage`, `def_amend`, `res_amend`, `skill_percent_to_amend`), and `pout(msg, verbose,
level)` — the click-cutter printer, also reachable as `ctx["log"]` with the verbosity already
bound. Plugin progress output must go through it, so `-v` warnings (`Level.WARNING`) and `-vv`
per-evaluation values (`Level.DEBUG`) mean the same thing to the tool and to your module.

Two rules matter when you write one (R-33/R-34): the damage kernel **applies every argument
you give it** and knows nothing about which talent keys belong to which skill, so the plugin
picks the argument set per damage source; and the plugin — not the kernel — applies the
buffers, folding `Atk_multiplier`/`Atk_absMod` and any other status buff into the attacker's
effective `Atk` **before** the call.

Reference plugin for the documented default objective (`auto_attack`):

~~~python
from ssoptim.ssoptim.damage import calculate_damage, skill_percent_to_amend
from ssoptim.ssoptim.plugins import aggregate_params

def objective(x, ctx) -> float:
    main, sc = ctx["members"]["main"], ctx["scenario"]
    p = aggregate_params(x)                     # all talent keys summed
    src = main.auto_skill["sources"][0]         # shorthand `damage:` -> one normalized source
    hit = src["damage"]["elemLuxDmg"]
    return calculate_damage(
        Atk=main.stats["Atk"] * (1 + p.get("Atk_multiplier", 0.0)) + p.get("Atk_absMod", 0.0),
        skillPercentAmend=skill_percent_to_amend(hit["skillPercentAmend"] * 100),
        critDmg=1.5 + p.get("critDmgMod", 0.0),
        crit_rate=0.5 + p.get("crit_rateMod", 0.0),
        slotDmg=1.0 + p.get("slotAutoAttackDmg", 0.0),   # auto-attack keys only
        elementDmg=1.0 + p.get("elemLuxDmg", 0.0),
        DEF=sc["DEF"], RES=sc["RES"],                   # enemy profile
    )
~~~

The shipped DPS sample (`plugins/simple_dps.py`) does the same per damage source, then divides
each source's damage by its period (`loop_time` for the auto skill, `cd` for the active skill)
and sums the rates — each source gets only its own buffers (e.g. `slotMarkDmg` for a mark
portion, not `slotSkillDmg`). 0.1.0 ships timing/buffer **data** only; the timeline
approximation lives in the plugin. Full walkthroughs are in [PLUGINS.md](PLUGINS.md).

Custom plugins live outside the package and are referenced by spec:

~~~console
> ssoptim optimize -f ./plugins/my_calc.py:objective -c my_party.yml
> ssoptim optimize -f my_objectives.iron_maiden:dps -c my_party.yml
~~~

## Known Issues

Implementor-level list of what is still open (gating/activation vocabulary gaps, unverified
release artefacts, planned M9+ features) is in [DESIGN.md](DESIGN.md) 10; the list below is what
a user of 0.1.0 sees.

* The tool is pre-release: the bundled character data set is the three authored characters
  (チトセ, アヤメ, テレサ - values read off the reference wiki extract), other characters are
  user data, and built-in objectives other than `auto_attack` are planned for later 0.x
  releases. The DPS sample (`plugins/simple_dps.py`) ships as an external plugin, not as a
  built-in objective.
* Timing data (`cd`, `loop_time`) is authored from the game spec or video analysis and is the
  data author's responsibility; where it is missing, DPS-minded objectives fall back to per-hit
  damage and warn with `-v`.
* 0.1.0 ships no shared timeline helper and no condition expression: talent gating and
  rotation assumptions are approximated inside each plugin, using the per-talent buffers, the
  gating pair (`duration`/`activation`) and timing in `ctx`.
* The bundled character data is authored from a **reference-only** extract of theチトセ,アヤメ and
  テレサ wiki pages: the extract lives in the workspace under `wiki_data/` and is *not* committed
  (git-ignored, never read by the tool or the build), so the committed artifact is the authored
  YAML in the installed package — the tool stays offline and self-contained either way.
* The buffer-key convention (`Atk_multiplier`, `slotMarkDmg`, …) is documented, not enforced;
  unknown keys are passed to the plugin untouched, and the damage kernel applies exactly the
  arguments the plugin hands it.
* Objective accuracy is the plugin author's responsibility — the tool guarantees the
  *talent distribution* obeys the constraints, not that a plugin models a character
  correctly.
* SciPy's constrained integer optimization may need `--runs`/`--maxiter` raised on
  heavily constrained parties.

## Development

### Building an Executable

The project venv is managed by uv, so use uv to provision and run it. Install
pyinstaller and package the project.

~~~console
> uv venv --python 3.12 .venv
> uv pip install --editable .
> uv pip install pyinstaller
> uv run pyinstaller ssoptim/cli.py --onefile --name ssoptim
~~~

The executable should be ready in `dist/ssoptim(.exe)`.

### Task runner

`tasks.py` (invoke) and the equivalent `Makefile` targets are provided:

* `build` (default) — create the uv venv and `uv pip install --editable .`
* `venv` — provision the dev venv
* `freeze` — write `requirements.txt`
* `package` / `publish` / `pubtest` — `uv build`, then `twine upload` (PyPI / TestPyPI)
* `clean` — remove `dist` and `*.egg-info`
* `install` — `uv pip install -r requirements.txt`

### Layout

Project layout follows the [click-cutter](https://github.com/koma75/click-cutter)
Click CLI template, extended with a data set, pluggable objective modules, and tests:

~~~
ssoptim/                 # repo root (project "SSOptim")
├── pyproject.toml       # ssoptim = "ssoptim.cli:main"
├── Makefile             # uv/build/publish targets
├── MANIFEST.in          # sdist prune: tests/, characters/, plugins/, wiki_data/ stay out
├── tasks.py             # invoke tasks
├── CHANGES.md           # release history
├── DESIGN.md            # design specification
├── PLUGINS.md           # plugin development guide
├── characters/          # your character YAML data
├── plugins/             # your objective modules (simple_dps.py is the shipped sample)
├── tests/               # pytest suite + YAML fixtures
└── ssoptim/             # package
    ├── __init__.py      # __version__ (setuptools-scm fallback)
    ├── cli.py           # click options -> cmd(kwargs)
    ├── characters/      # bundled default data set
    └── ssoptim/         # implementation
        ├── ssoptim.py   # orchestration
        ├── data.py      # YAML load + validation + scenario block
        ├── talent.py    # interpolation + per-talent/aggregated buffers
        ├── damage.py    # damage kernel (applies every argument it is given)
        ├── plugins.py   # objective-module resolution + data context (ctx)
        ├── objectives/  # built-in objectives (auto_attack …)
        ├── constraints.py
        ├── optimize.py  # SciPy Differential Evolution driver
        └── report.py    # YAML/console rendering
~~~

### Versioning

The project follows the [semver 2.0](http://semver.org/) versioning scheme, starting at
0.1.0 in development and reaching 1.0.0 on production release. The interface relevant to
versioning is everything defined in this document's **Usage** section: the
(`optimize`) command and its arguments/options, and the format of the configuration file
`ssoptim.yml` (plus the character data and output YAML formats documented above).

## Version History

See [CHANGES.md](CHANGES.md) for the full release history.
