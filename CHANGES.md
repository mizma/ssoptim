# Changelog

Change-point identifiers: **[Added]** new feature/option · **[Changed]** behavior
changed · **[Removed]** feature/doc removed · **[Breaking]** incompatible change · **[Minor]**
cosmetic/clarification · **[Performance]** performance improvement · **[Fixed]** bug fix.

## 0.1.0 (T.B.D.)

**Summary:** Initial release

### User-facing specification changes

- **[Added]** CLI: `--scenario KEY=VAL` (enemy-profile override) and `--target-opts KEY=VAL`
  (free-form plugin constants), both repeatable.
- **[Added]** config keys `scenario:` (DEF, RES, per-element `res_table`, PEN, VUL,
  DEF_Ignore, DEF_Penetrate, enemyBreakStatus, resilienceBreakDmg) and `target_opts:`.
- **[Added]** character-data keys `cd` and `loop_time`, the `damage:` shorthand map and the
  `sources[]` multi-source form with per-source element/slot type, timing and `dot`.
- **[Added]** objective signature `objective(x, ctx)`; `-vv`/`--show-params` now also dump the
  effective `scenario:` values.
- **[Added]** documentation of the buffer-key convention and of the `plugins/simple_dps.py`
  DPS sample in README; party must consist of three distinct characters (exit 2).

### Design specification changes (DESIGN.md, pre-implementation)

- **[Added]** skill timing data in the character schema: `cd` (seconds) on main/sub active
  skills from the game's character spec, and `loop_time` (seconds) on each authored character's
  auto skill from gameplay/video analysis (R-30).
- **[Added]** timing is data only: the tool validates and passes it through; how cooldowns
  and loop times become DPS is the target function's/plugin's decision, including
  rotation-specific plugins; no shared rotation/timeline model in 0.1.0 (R-31).
- **[Added]** skills may declare multiple damage sources (base element hit plus separate
  mark/projectile/minion portions), each with its own element/slot damage type, its own
  `cd`/`loop_time` and optional `dot`, so a generic calculator evaluates each separately
  with its own buffers and sums them (R-32).
- **[Added]** plugin/kernel ownership split: the damage kernel applies **every** argument it
  is handed and encodes no per-skill key policy (R-33); selecting the argument set and
  applying Atk/status buffs to the main member's status before each kernel call is the
  target function's/plugin's responsibility (R-34).
- **[Added]** §6.1 kernel/buffer ownership, §6.2 generic DPS shape
  (`Σ damage(source)/period(source)` with `period = loop_time | cd`), and §6.3 sample plugin
  plan: the shipped `plugins/simple_dps.py` sample targets a simple main-character DPS built
  from the auto-skill loop time and the main active skill's cooldown.
- **[Added]** milestone M9: a detailed plugin development guide in a separate `PLUGINS.md`
  (key selection, buffer ownership, timing data, worked `auto_attack`/`simple_dps` samples,
  "bigger is better" convention); `PLUGINS.md` added to the project tree.
- **[Added]** requirement IDs R-30..R-34 and the §4.1 timing/`sources[]` schema rows plus a
  documentation sample exercising them.
- **[Changed]** §12 open questions resolved and recorded (bigger-is-better documented in
  plugin docs; timing used per the target plugin; per-character minimums left purely to
  R-14; 0.2.0 targets a more general CD/loop-aware DPS approximation, still no real
  timeline) and promoted into §11 decisions 10-13.
- **[Minor]** doc cross-reference fix: implementation order is §9 (was cited as §12).

- **[Added]** documented buffer-key vocabulary as a convention, not enforced (R-35):
  `Atk_absMod`/`Atk_multiplier`, `critDmgMod`/`crit_rateMod`, `slot{X}Dmg`/`slot{X}CritDmg`,
  `elem{E}Dmg`, `skillIntensity`, `DEF_rate_mod`/`RES_rate_mod` — the single source of truth in
  `PLUGINS.md`, because the kernel maps nothing (R-33).
- **[Added]** enemy/scenario profile as user input (R-36): a `scenario:` block in the run config
  merged over the kernel defaults and delivered as `ctx["scenario"]`, plus free-form
  `target_opts:`/`--target-opts` for plugin-specific constants; game-undefined formula terms
  (`IGNORING`, `generalDmg`, `dmgPlus`, `finalDmg`, …) are deliberately **not** exposed as
  scenario input.
- **[Added]** tool-provided data context (R-37): `objective(x, ctx)` carrying all three party
  members in full (stats incl. HP, skill blocks with timing/sources, the talent set in use), the
  scenario and the plugin knobs, so plugins bind only their own extra constants.
- **[Added]** level-resolution helpers (R-38): per candidate the tool resolves the flat `x` into
  name-keyed levels and a **per-talent** `talent → {key: value}` breakdown plus the summed map,
  exposed as `resolve_talent_params(x, ctx)`; the per-talent form is required so timeline-style
  plugins can attribute a buff to the talent that granted it. Plugins never map `x` positions
  themselves.
- **[Added]** condition-gated talent values are a documented convention, not a data expression
  (R-39): cooldown windows, "after skill activation" and "target has mark" are approximated by
  the plugin (value = per-application amount / uptime fraction / count), tunable via `target_opts:`.
- **[Added]** role rules over the existing skill keys (R-40): main uses `auto_skill` +
  `main_skill` + `ult_skill`; support slots use `sub_skill` + `ult_skill` and their own
  `auto_skill` (some characters act from support with the auto skill) and never `main_skill`;
  `loop_time` is authored for every character's auto skill accordingly.
- **[Added]** loader normalization: the shorthand `damage:` map loads as a single-element
  `sources[]` list inheriting the skill-level timing, so objective modules see one shape only.
- **[Added]** party distinctness (R-41): three different characters required, duplicates exit 2.
- **[Changed]** §11 decisions extended to 14-18 (typed scenario, tool-provided ctx, per-talent
  breakdown, prose role rules over existing keys, no condition DSL) and §12 with Q-5..Q-8
  answers; §4.2 config sample gains `scenario:`/`target_opts:`; §7 defines `--scenario`/
  `--target-opts`; §9 milestones M1/M3/M4/M6/M9 updated for the context contract and `PLUGINS.md`
  sections; §10 adds risk rows for the per-talent breakdown and key-vocabulary drift.
- **[Minor]** citation fixes: objective-responsibility cross-reference now R-21/R-33/R-34 (was
  R-14/R-15); the exit-code table reference is §7 (was §8).
- **[Added]** README: `--scenario`/`--target-opts` option docs and an example invocation,
  `scenario:`/`target_opts:` in the config sample, timing + `sources[]` in the character-data
  sample with the role/timing notes, the ctx-based objective contract and a corrected
  `auto_attack` reference plugin (the earlier sample referenced an undefined `party`), a
  `PLUGINS.md` link, and Known Issues for missing timing data, the missing shared timeline
  helper, and the unenforced key convention.

- **[Added]** §1.1 "Game-model background": DESIGN.md is now self-contained — the party/role
  rules, the 4-core-plus-12-sub talent structure, the pick-pool lore that makes the level budget
  and per-member totals user inputs, the damage-formula/condition lore, and the HP-scaled
  characters are restated in this document instead of pointing at an intent doc.
- **[Changed]** the `DesignGoals.md` links/citations removed: document header, the §8 project
  tree entry, §11 items 4 and 15, and the §9 M2 acceptance criterion (now citing
  `stella_sora_damage.py` and [DamageCalculationParameters.md]); README's background link now
  points at DESIGN.md and PLUGINS.md.

### Bug fixes

- (No bug fixes — initial implementation.)

### Other changes (Packaging, Project organization etc.)

- **[Removed]** `DesignGoals.md` deleted from the project: DESIGN.md no longer uses it as
  source of intent, and the game-spec facts it carried are restated in DESIGN.md §1.1. The
  damage reference ([DamageCalculationParameters.md](DamageCalculationParameters.md) and
  `stella_sora_damage.py`, vendored at M2) is kept.
- (No other changes — initial implementation.)
