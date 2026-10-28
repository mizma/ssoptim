# Stella Sora Talent Optimizer Design goals

Stella Sora Party build optimization tool focused on optimizing talent level
distribution within a set party composition with target level points.

## CLI tool goals

This CLI tool is intended to optimize Stella Sora Talent level distribution
for a given number of levels available for a specific party composition.

Due to character and party composition causing very different optimization
targets, the tool is intended to optimize for a specific optimization
target calculator combined with character talent information that contains
different values that may work with specific main character's specs.

The goal is to allow the user to define an optimization target calculation
and optimize the talent level distribution given a limited amount of
talent levels to distribute.

## Stella Sora Game Specification

Relevant Specification of the game itself are as follows.

* Not all information may be relevant in the base design of the cli tool itself.
* The information is there to assist in understanding the cli requirements for things
  like plugin features, as well as data structure design requirements.

### Party composition

* Stella Sora party consists of one main character and two support characters.
* Every character can be put in main or support role
* Every character has two completely separate sets of talents for main and support
  * character can only level up main talent when the role is main and vis-a-vis.

### Basic Damage Calculation

* The basic damage calculation is defined [in this gist](https://gist.github.com/AutumnVN/91afd7a37a9743488419b70f07225950).
  * sample implementation for damage calculation is in [stella_sora_damage.py](./stella_sora_damage.py)
  * calculation sample uses critical rate to calculate the Average expected damage instead.
* The individual parameters are calculated by character base stats, skill modifiers and talent modifiers.
* Each talent has different modifiers for certain parameters and conditions.
  * Conditions include things like cool down time, after skill activation, when target has sigil.
  * The conditions may be very complex and vary between characters (hence the need to have party specific
    pluggable optimization calculation modules)

~~~python
damage = (
    (
        (
            (
                (
                    Atk * ((skillPercentAmend + talentGroupPercentAmend) * 0.0001 / 100)
                    + skillAbsAmend
                    + talentGroupAbsAmend
                )
                * skillIntensity
                * perkIntensity
                * slotDmg
                * elementDmg
                * generalDmg
                + dmgPlus
            )
            * (critDmg + slotCritDmg)
            * (
                erAmend
                * defAmend
                * slotDmgTaken
                * elementDmgTaken
                * generalDmgTaken
                * resilienceBreakDmg
            )
        )
        + dmgPlusTaken
    )
    * finalDmg
) + finalDmgPlus
~~~

### Characters Specification

Characters have basic statuses as well as skills and talents for main attacker role and support role.

#### Base Stats

Base stats define things like Base damage.

#### Skills（スキル）

There are 4 skills for each character

* Main Skill
  * Main attack skill used mainly when the character's role is the main attacker.
  * Some characters have support skills that allow them to appear in field to use the main skill
    even when the role is support, in which case the character may use this skill
* Active Skill (main)
  * This is the active skill with cool down (CD) time when the character's role is main attacker
* Active Skill (support)
  * This is the active skill with cool down (CD) time when the character's role is support
* Ultimate Skill (main)
  * This is the ultimate skill used when character's role is main
  * This skill can be activated
* Ultimate Skill (support)
  * This is the ultimate skill used when character's role is support

There is no variance to this when party composition is fixed, so only the stats
relevant to optimization target calculation should be passed as fixed values from character data.
Talent levels are the only variable to optimize in the game's party build.

#### Talents (素質)

* Each character has separate set of talents for main role and support role.
  * Talent sets are completely separate when a character is used for main or support.
* There are always 4 core talents and 9 sub talents.
* Every party member is forced to choose exactly 2 of the 4 core talents.
  * core talents have no level system (level 1 only)
  * no party member can get a third core talent in a build.
  * every party member is forced to choose 2 core talents and cannot be skipped.
* All sub talents have level 0 - 6 (level 0 meaning not owning the talent).
  * During a build, you are given a choice from 3 talents randomly picked from
    the party member's skills and the player chooses one to get.
  * The number of pulls available may vary during each build, so the total
    levels available may vary from 40 to 65 or above.
    * Hence the tool needs input to target how many levels.
  * Since the random pick is not completely random, you cannot pick only one character's
    talents and skip all other.
  * Main character talents tends to be in the selection pool more.
* Each talent (including core talents) have different effects, which may modify
  any number of stats, multipliers and/or addition parameters.
  * Optimization target calculation for things like damage needs to apply those
    modifiers to the appropriate parameter in the damage calculation.
  * There may be character specific parameters that affect character
    specific damage calculation method and the tool will need to
    be able to accommodate such special cases using character
    specific optimization target calculation module plugin.

##### Talent parameters

Here are the input values relevant to damage calculation, and how the talents may affect the values.

* Atk: float,                             # キャラ攻撃力
  * mostly comes from character status.
  * some talents provide Atk bonuses
* skillPercentAmend: float,               # スキルのダメージ倍率（主にスキルの表記より）
  * comes exclusively from character skill percentage
  * should be provided by the optimization target calculator, and not the talent levels.
* skillIntensity: float = 1.0,            # 特定のスキルや攻撃の追加ダメージ倍率。特定スキル％。琥珀の「緻密温度調整」等
  * This should come from a specific talent, targetting specific optimization calculator.
* slotDmg: float = 1.0,                   # 攻撃の種類に応じたダメージ補正。通常攻撃、スキル、必殺技、印、従者などの分類に対応する。
  * Talents provide values.
  * Each value is tied to specific damage types, so talent values should be split to each type
    (Auto Attack / Skill / Ultimate / Other / Mark / Projectile / Minion damage)
* elementDmg: float = 1.0,                # 攻撃側の属性に応じたダメージ補正。水・火・地・風・光・闇の各属性に関連する。
  * Talents provide values for each type.  Should be split to Aqua / Ignis / Terra / Ventus / Lux / Umbra damage.
* critDmg: float = 1.5,                   # 会心ダメージ係数。基本は1.5倍。スキル、素質、紋章、装備等で増加
  * Talents provide modifiers.
* slotCritDmg: float = 0.0,               # 通常攻撃、スキル、必殺技、印、飛翔物、従者などの内部分類に対応するタイプ別会心ダメージ増加係数
  * Talents provide modifiers for specific slot (Auto Attack / Skill / Ultimate / Other / Mark / Projectile / Minion damage)
* crit_rate: float = 0.5,                 # 会心率。会心が発生する割合。
  * Talents may provide modifiers
* is_dot: bool = False,                   # スリップダメージか否か。スリップダメージは会心発生しない。
  * Specified by character skills. should be considered by optimization target calculator.
  * If talents provide modifiers specific to the character skill, that should be provided as a value to
    work specifically with the optimization target calculator incorporating the skill in it's calculation.
* DEF: float = 500.0,                     # 防御係数。基本は500らしい
  * Talents may provide debufs for DEF
* RES: float = 750.0,                     # 弱点属性 = 250, 中立 = 750, 耐性属性 = 2000
  * Talents may provide debufs for RES
* PEN: float = 0.0,                       # 属性貫通値。
  * Currently not used by talents?
* VUL: float = 0.0,                       # 属性耐性が０以下の場合に適用される補正値。詳細不明
  * Currently not used by talents? details unknown.
* slotDmgTaken: float = 1.0,              # ダメージの種別毎のダメージ補正
  * Probably not used?
* elementDmgTaken: float = 1.0,           # 属性被ダメージ係数。特定の属性にかかる倍率
  * Probably not used?
* resilienceBreakDmg: float = DEFAULT_RESILIENCE_BREAK_DMG,  # ブレイク時ダメージ係数。基本150%
  * Probably fixed for now.
* enemyBreakStatus: bool = False,         # ブレイク状態
  * Should only be provided by optimization target calculator.
  * Talents does not affect this value.

There may be talent/character/skill specific values that require special attention before converting into one of
the inputs in the damage calculation, in which case, the talent should provide a specialized value and let the
optimization target calculator to handle the value appropriately (i.e. simulating the DPS by applying the value
based on it's skill specification at specific intervals/conditions).

## CLI Tool Operation

### Basic Operation

CLI should receive the party composition (which character data to reference), optimization target
(which optimization target calculator module to use) and talent level restrictions like total levels(mandatory),
fixed core talent specification (optional) and minimal talent level distribution for each character (optional).

Then the tool should run optimization of talent level distribution using the inputs and
output the best talent level distribution for the party composition with given conditions.

### CLI Tool input

The inputs should be a combination of cli arguments and yaml files.

* party composition (yaml file, or command-line arguments)
  * must specify main character and two sub characters
    * character pointing to a yaml file containing character stats, skill info and talent details
* optimization target calculator module specification
  * somehow specify the python module or .py file that always takes the same inputs and outputs.
    * the modules need to be easily extensible.  possibly without re-building the pyproject package.
    * assume the base project to be installed in pipx or uv tool install.
    * module for optimization target calculator module should be pluggable from outside, and
      allow specifying the specific module/function to use from cli arg or yaml config.
  * optimization target calculator must take the following inputs
    * main and sub character data object (serialized from yaml) with all stats/skill/talent details
    * talent level distribution for main and sub1/sub2 characters
  * optimization target should return a number (typically DPS or Damage) calculated from
    the specified party information and talent level distribution.
* Available total talent level to distribute
* Optimization Restrictions options
  * Which talents are fixed at which level for which character (optional)
  * minimum talent level distribution for each character (optional)
  * maximum talent level distribution for each character (optional)

### Optimization

Optimization will use the inputs and try to optimize for the maximum output from the specified
optimization target calculator module/function by adjusting the distribution of available
talent levels (optionally following the restrictions like fixed core talent and minimum/maximum talent
level for each character).

* Optimization for each talent level are integers (no decimal points in level distribution)
* Optimization should assume the optimization target function is non-linear.
  * Optimization function should be relatively cheap to calculate
* Use something like SciPy Differential Evolution for the optimization.
  * lambda x in the evolution function's optimization target function should have the
    all the talent levels from main character first talent all the way to second sub characters
    last talent.
    * Talent list should be generated from the character data imported from yaml file
    * Talent flagged as "Core Talent" should only add upto 2 per character (generate appropriate constraints
      from reading the yaml file)
    * Other constraints should be generated appropriately from user input (args, or yaml config)
      * Constraints for total talent levels
      * Constraints for minimum total talent level for specific character
      * Constraints for maximum total talent level for specific character
      * Constraints for minimum talent level for specific talent
    * Integrality should be all set to integer (True)
* Have some debug output by the optimization target function (enabled by -v --verbose option) about the
  calculated value based on inputs
* The default optimization target function should just be some function that calculate auto attack skill damage
  as an example implementation.

#### Restrictions

* Every character needs to select exactly 2 core talent sets (always set optimization constraints)
  * core talents are fixed 1 level talents that characters must select out of 4 available
  * The user may specify which core talent is mandatory.
* User may suggest a minimal talent level distribution for each character at input, which must
  be followed.
  * If the target total level is 65, and user specifies main>=30 and Sub1>=10 Sub2>=15, then
    main character talent must total 30 or more and Sub character 1 must have 10 or more etc.

### CLI Tool output

The tool should output a YAML file similar to the character info input yaml but with just the
talent list and show the optimized talent level for each talent, plus the actual number emitted
by the optimization target calculator function with that specific talent level distribution.

## Data Set/Plugin

### Character data set

example yaml file for a character may look like the following

~~~yaml
<charname>:
  stats:
    ATK: 6966
    HP: 94662
    DEF: 0
  auto_skill:
    elemLuxDmg:
      skillPercentAmend: 11.30 # total of 1130% of Atk as elemLux damage.
  main_skill:
    elemLuxDmg:
      skillPercentAmend: 8.90 # some skills may have multiple damages
    slotMarkDmg: # each damage type must be calculated separately with only the relevant talent multipliers applied.
      skillPercentAmend: 1.22 # the skill damage with multiple damage types should be calculated separately and added together
  sub_skill:
    elemLuxDmg:
      <character specific item>: 3.55 # some skill may have a completely different multiplier mechanics
    slotMarkDmg:
      skillPercentAmend: 1.22
  ult_skill:
    elemLuxDmg:
      <character specific item>: 8.55
    slotProjectileDmg:
      skillPercentAmend: 2.22
  talents_main:
    - talent_name: "<talent name>"
      core_talent: true
      Atk_absMod:
        1: 200.0
      Atk_multiplier:
        1: 0.15 # i.e. add 15% to attack multiplier (so total will be 1.15)
      skillPercentAmend:
        1: 0.0 # core talent has only level 0 or level 1
      skillIntensity:
        1: 0.0 # in reality, only put parts that actually have any value
      slotAutoAttackDmg:
        1: 0.0
      slotSkillDmg:
        1: 0.0
      slotUltimateDmg:
        1: 0.0
      slotMarkDmg:
        1: 0.0
      slotProjectileDmg:
        1: 0.0
      slotMinionDmg:
        1: 0.0
      elemAquaDmg:
        1: 0.0
      elemIgnisDmg:
        1: 0.0
      elemTerraDmg:
        1: 0.0
      elemVentusDmg:
        1: 0.0
      elemLuxDmg:
        1: 0.0
      elemUmbraDmg:
        1: 0.0
      critDmgMod:
        1: 0.0
      slotAutoAttackCritDmg:
        1: 0.0
      slotSkillCritDmg:
        1: 0.0
      slotUltimateCritDmg:
        1: 0.0
      slotMarkCritDmg:
        1: 0.0
      slotProjectileCritDmg:
        1: 0.0
      slotMinionCritDmg:
        1: 0.0
      crit_rateMod:
        1: 0.0
      DEF_rate_mod:
        1: 0.0
    - talent_name: "<talent name>"
      core_talent: true
      # details omitted
    - talent_name: "<talent name>"
      core_talent: true
      # details omitted
    - talent_name: "<talent name>"
      core_talent: true # first 4 is always core talent.
      # details omitted
    - talent_name: "<talent name>"
      core_talent: false
      Atk_multiplier:
        1: 0.045    # i.e. add 4.5% to attack multiplier (so total will be 1.15) at level 1
        6: 0.18     # add 18% at level 6.  level 2 - 5 may be omitted.  in which case the intermediates need to be inferred.
        # When inferring intermediate levels, distribute them evenly between level 1 and level 6 values.
    # array continues for all talents for main role
  talents_sub:
    # something similar to talents_main continue
~~~

And party composition and optimization restriction config may look like the following

~~~yaml
party:
  main: "<character name>"
  sub1: "<character name>"
  sub2: "<character name>"
total_level: 65
restrictions:
  main:
    min: 10 # minimum of 10 levels should be set to main character
    talent_levels:
      - min: 1
      - min: 0
      - min: 1
      - min: 0
      - min: 6
      - max: 1
        # have arrays for all skills. for no restriction, set min to 0 and no max.
        # any value in min other than 0, or having a max value means there will be restrictions during optimization
        # Core talents should be put in the top 4 of each character yaml.
        # then only put 4 in the talent_levels array with two of them set to min 1 and the others min 0
        # to fix the two core talent selections during optimization
        # if the array only has 4 items, restrictions are set to only the first 4 talents defined in the character.
  sub1:
    min: 10 # minimum of 10 levels should be set to sub1 character
  sub2:
    min: 10 # minimum of 10 levels should be set to sub2 character
    max: 20 # sub2 character total should not exceed 20
~~~

Since skills and talent specifications are very complex, optimization target function should be built for
at least each main character, if not for each specific party composition.

### Optimization target calculation plugin

Since different party composition can have a very different strategy,
the optimization target calculation can differ wildly (including character specific mechanism).
To accommodate this difference, the tool needs to be able to select different pluggable
optimization calculation function that will emit some number.

To be able to work with character information and talent information, both character info
and talent spec is given in yaml form.  And given a specific talent level information,
it extracts the parameters from the yaml for the specific talent and parameters for the talent,
and uses those parameters for the calculation.  How parameter in a talent level is used
is completely up to the optimization target calculator and a specific calculator may not
use certain parameters at all.  Also, the talent parameter may contain character specific
parameters never referenced in general optimization calculation and only referenced in
a specific optimization calculator.

To make the optimization to work with SciPy, the first argument should be in the format
scipy.optimize expects for it's optimization parameter inputs.

Other information like character data and party composition should be passed as a separate parameter using a closure
or a lambda function.

#### Common functions for optimization target

In every target optimization function, it should take the common buf values from all the talents
at the level specified and add all the common values and create a total value for each value specified
in the talents at specified levels.  Mapping function to collect all items with the same key.
All values should be collected including character specific keys.

After all the modifier values with same keys are collected into one dictionary, then each optimization function
can do it's calculation with the values appropriately depending on the main character specification.

Keep in mind that some characters reference HP or other parameters defined in the character information
to calculate the damage output so character information must be passed to optimization target calculator function/module
