# SSOptim

Stella Sora Party build optimization tool

`ssoptim` optimizes **talent level distribution** for a fixed party composition
(one main character + two support characters) when a fixed number of talent levels
is available. Because party composition changes the optimization target drastically,
the objective ("what number are we maximizing?") is a **pluggable calculation module**
— built-in defaults plus user-supplied modules that can be dropped in next to an
installed copy of the tool without rebuilding it.

> **Status:** design stage (0.1.0 T.B.D.). The CLI below is the planned 0.1.0 interface;
> see [DESIGN.md](DESIGN.md) for the implementation plan and [DesignGoals.md](DesignGoals.md)
> for the game-spec background.

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

* -c, --config CFG
    * CFG: Path to Configuration File (default: ssoptim.yml) — carries party, budget,
      target and restrictions
* -m, --main MAIN
    * MAIN: main character name (overrides `party.main`)
* -s, --sub SUB
    * SUB: support character name; repeat exactly twice, fills `sub1` then `sub2`
* -t, --total-levels N
    * N: total talent levels available to distribute (mandatory, unless given in the
      config file)
* -f, --target SPEC
    * SPEC: optimization target module/function — `auto_attack` (default), a dotted
      module path `pkg.mod:func`, or a file path `./plugins/my_calc.py:func`
* --char PATH
    * PATH: character data file or directory; repeatable, searched before the bundled
      character set
* --restrictions FILE
    * FILE: YAML file of optimization restrictions (merged over the config file)
* --total-level-mode {exact,at_most}
    * exact (default): the chosen levels must sum to the budget; at_most: levels may
      go unused when the objective stops improving
* -o, --out OUT
    * OUT: write the result YAML to this path (default: stdout)
* --show-params
    * also dump the aggregated talent-parameter dictionary the objective received
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
| 2 | usage / config error (missing party, missing budget, bad YAML) |
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
target: auto_attack
total_level: 65
total_level_mode: exact
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
    elemLuxDmg:
      skillPercentAmend: 11.30    # 1130 % of Atk
  main_skill:
    elemLuxDmg:
      skillPercentAmend: 8.90
    slotMarkDmg:
      skillPercentAmend: 1.22
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
  talents_sub:                    # used when the character is in sub1/sub2
    - talent_name: "…"
~~~

* Level-keyed values are sparse; intermediate levels are inferred as an even step
  between the declared anchors, and level 0 adds nothing.
* Parameter names are free-form. Character-specific keys (e.g. a signature-mechanic
  value) are allowed; they are passed through to the objective module untouched.
* `skillPercentAmend` in character files is percent-of-Atk (×100 percent units);
  it is converted to the in-game unit by the tool.

### Output

~~~yaml
target: auto_attack
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

With `-vv`, the aggregated parameter dictionary (every talent key summed at the chosen
levels, including character-specific keys) is appended as `aggregated_params:`.

### Objective plugins

An objective module is any callable that takes the flat level vector and returns a
number (bigger = better):

~~~python
def objective(x) -> float:
    # x = main character's talent levels, then sub1, then sub2,
    #     each in the order declared in its character file
    ...
    return expected_dps
~~~

Character/party data is not a solver argument — the plugin binds it (closure,
`functools.partial`, or by reading the data the tool hands it). Helpers the tool
provides: `aggregate_params(x)` (sum all same-key talent parameters at the chosen
levels), `resolve_talent_value(talent, level)` (interpolated level value), and the
`damage` kernel (`calculate_damage`, `def_amend`, `res_amend`, `skill_percent_to_amend`).

Reference plugin for the documented default target (`auto_attack`):

```python
from ssoptim.ssoptim.plugins import aggregate_params
from ssoptim.ssoptim.damage import calculate_damage, skill_percent_to_amend

def objective(x) -> float:
    p = aggregate_params(x)                     # all talent keys summed
    return calculate_damage(
        Atk=party.main.stats["Atk"] * (1 + p.get("Atk_multiplier", 0.0)),
        skillPercentAmend=skill_percent_to_amend(1130),   # auto skill: 1130 % Atk
        critDmg=1.5 + p.get("critDmgMod", 0.0),
        crit_rate=0.5 + p.get("crit_rateMod", 0.0),
        slotDmg=1.0 + p.get("slotAutoAttackDmg", 0.0),
        elementDmg=1.0 + p.get("elemLuxDmg", 0.0),
    )
```

Custom plugins live outside the package and are referenced by spec:

~~~console
> ssoptim optimize -f ./plugins/my_calc.py:objective -c my_party.yml
> ssoptim optimize -f my_targets.iron_maiden:dps -c my_party.yml
~~~

## Known Issues

* The tool is pre-release: the bundled character data set is incomplete, and objectives
  other than `auto_attack` (per-skill, ultimate, cooldown-window DPS) are planned for
  later 0.x releases.
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
├── tasks.py             # invoke tasks
├── CHANGES.md           # release history
├── DESIGN.md            # design specification
├── characters/          # your character YAML data
├── plugins/             # your objective modules
├── tests/               # pytest suite + YAML fixtures
└── ssoptim/             # package
    ├── __init__.py      # __version__ (setuptools-scm fallback)
    ├── cli.py           # click options -> cmd(kwargs)
    ├── characters/      # bundled default data set
    └── ssoptim/         # implementation
        ├── ssoptim.py   # orchestration
        ├── data.py      # YAML load + validation
        ├── talent.py    # level interpolation + parameter aggregation
        ├── damage.py    # damage kernel
        ├── plugins.py   # objective-module resolution
        ├── targets/     # built-in objectives (auto_attack …)
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
