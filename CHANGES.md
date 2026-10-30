# Changelog

Change-point identifiers: **[Added]** new feature/option · **[Changed]** behavior
changed · **[Breaking]** incompatible change · **[Minor]** cosmetic/clarification
· **[Performance]** performance improvement · **[Fixed]** bug fix.

## 0.1.0 (T.B.D.)

**Summary:** Initial release

### User-facing specification changes

- **[Added]** T.B.D.

### Design specification changes (DESIGN.md, pre-implementation)

- **[Added]** skill timing data in the character schema: `cd` (seconds) on main/sub active
  skills from the game's character spec, and `loop_time` (seconds) on the main character's
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

### Bug fixes

- (No bug fixes — initial implementation.)

### Other changes (Packaging, Project organization etc.)

- (No other changes — initial implementation.)
