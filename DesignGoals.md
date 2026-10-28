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

* The basic damage calculation is defined [here](https://gist.github.com/AutumnVN/91afd7a37a9743488419b70f07225950).
  * sample implementation for damage calculation is in [stella_sora_damage.py](./stella_sora_damage.py)
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
* There are always 4 special talents and 9 normal talents.
* Every party member is forced to choose exactly 2 of the 4 special talents.
  * Special talents have no level system (level 1 only)
  * no party member can get a third special talent in a build.
  * every party member is forced to choose 2 special talents and cannot be skipped.
* All normal talents have level 0 - 6 (level 0 meaning not owning the skill).
  * During a build, you are given a choice from 3 talents randomly picked from
    the party member's skills and the player chooses one to get.
  * The number of pulls available may vary during each build, so the total
    levels available may vary from 40 to 65 or above.
    * Hence the tool needs input to target how many levels.
  * Since the random pick is not completely random, you cannot pick only one character's
    talents and skip all other.
  * Main character talents tends to be in the selection pool more.
* Each talent (including special talents) have different effects, which may modify
  any number of stats, multipliers and/or addition parameters.
  * Optimization target calculation for things like damage needs to apply those
    modifiers to the appropriate parameter in the damage calculation.
  * There may be character specific parameters that affect character
    specific damage calculation method and the tool will need to
    be able to accommodate such special cases using character
    specific optimization target calculation module plugin.

## CLI Tool Operation

### Basic Operation

### CLI Tool input

### Optimization

#### Restrictions

* Every character needs to select exactly 2 special talent sets.
  * Special talents are fixed 1 level talents that characters must select out of 4 available
  * The user may specify which special talent is mandatory.
* User may suggest a minimal talent level distribution for each character at input, which must
  be followed.
  * If the target total level is 65, and user specifies main>=30 and Sub1>=10 Sub2>=15, then
    main character talent must total 30 or more and Sub character 1 must have 10 or more etc.

### CLI Tool output

## Data Set/Plugin

### Character data set

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
