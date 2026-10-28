"""
Stella Sora damage calculator.

Python port of AutumnVN's gist "Stella Sora: DEF, RES, PEN, VUL and your damage"
https://gist.github.com/AutumnVN/91afd7a37a9743488419b70f07225950

Every input from the full damage formula is kept, including the ones the gist
marks as "NOT USED". Unused inputs default to their neutral value
(0 for additive terms, 1 for multiplicative terms) so you can ignore them.

Quick start:

    from stella_sora_damage import calculate_damage

    dmg = calculate_damage(
        Atk=3000,
        skillPercentAmend=2_500_000,     # 250% Atk, see note on units below
        DEF=350,
        RES=570,
        PEN=0,
        critDmg=1.5,
    )

Units note
----------
The formula uses (skillPercentAmend + talentGroupPercentAmend) * 0.0001 / 100
as the fraction of Atk, so a skill that deals 250% Atk (fraction 2.5) has
skillPercentAmend = 2_500_000, i.e. percent * 10000.
Use `skill_percent_to_amend(250)` to convert from a plain percentage.
"""

from __future__ import annotations

# --------------------------------------------------------------------------
# Constants (from the game config in the gist, 4.config.json)
# --------------------------------------------------------------------------
BASE_SUPPRESS = 0.1
DYNAMIC_SUPPRESS = 0.9

# (valueLowerLimit, valueUpperLimit, amendLowerLimit, amendUpperLimit)
LOW_RES_LIMITS = (0.0, 250.0, 0.0, 0.25)
MIDDLE_RES_LIMITS = (251.0, 750.0, 0.35, 0.6)
HIGH_RES_LIMITS = (751.0, 2000.0, 0.9, 0.99)

# Assumed value according to the gist author's testing
DEFAULT_RESILIENCE_BREAK_DMG = 1.5


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def skill_percent_to_amend(percent: float) -> float:
    """Convert a plain skill percentage (e.g. 250 for 250% Atk) into the
    in-game skillPercentAmend unit (1/10000 of a percent)."""
    return percent * 10000


# --------------------------------------------------------------------------
# DEF
# --------------------------------------------------------------------------
def effective_def(
    DEF: float, DEF_Ignore: float = 0.0, DEF_Penetrate: float = 0.0
) -> float:
    """Effective_DEF = DEF * (1 - DEF_Ignore) - DEF_Penetrate

    DEF_Ignore and DEF_Penetrate are currently not used in game.
    """
    return DEF * (1 - DEF_Ignore) - DEF_Penetrate


def def_amend(DEF: float, DEF_Ignore: float = 0.0, DEF_Penetrate: float = 0.0) -> float:
    """defAmend = 1 - (Effective_DEF * 40) / (Effective_DEF * 32 + 24000)

    This is your damage multiplier from enemy DEF.
    """
    eff = effective_def(DEF, DEF_Ignore, DEF_Penetrate)
    return 1 - (eff * 40) / (eff * 32 + 24000)


# --------------------------------------------------------------------------
# RES / PEN / VUL
# --------------------------------------------------------------------------
def effective_res(RES: float, PEN: float = 0.0, IGNORING: float = 0.0) -> float:
    """Effective_RES = RES * (1 - IGNORING) - PEN

    IGNORING is currently not used in game.
    """
    return RES * (1 - IGNORING) - PEN


def _res_limits(eff_res: float) -> tuple[float, float, float, float]:
    """Return (valueLower, valueUpper, amendLower, amendUpper) for Effective_RES > 0.

    The game config defines tiers 0-250, 251-750 and 751-2000. Values that fall
    in the 1-wide gaps between tiers (e.g. 250.5) are assigned to the tier below,
    and the result is clamped (see `res_amend`).
    """
    if eff_res < MIDDLE_RES_LIMITS[0]:
        return LOW_RES_LIMITS
    if eff_res < HIGH_RES_LIMITS[0]:
        return MIDDLE_RES_LIMITS
    return HIGH_RES_LIMITS


def res_amend(
    RES: float, PEN: float = 0.0, VUL: float = 0.0, IGNORING: float = 0.0
) -> float:
    """erAmend: the damage multiplier from enemy RES, PEN and VUL.

    * Effective_RES <= 0 (suppress / VUL branch):
        erAmend = (1 + VUL * 0.1) + ((VUL * Effective_RES) * -0.01) * 0.9
    * Effective_RES > 0:
        reduction = amendLower + (amendUpper - amendLower)
                    * ((Effective_RES - valueLower) / (valueUpper - valueLower)) ** 2
        erAmend = 1 - reduction

    VUL is 0.05 (5%) only on Ridge lv51+, Jinglin lv1-40, Teresa lv51+.
    """
    eff = effective_res(RES, PEN, IGNORING)

    if eff <= 0:
        return (1 + VUL * BASE_SUPPRESS) + ((VUL * eff) * -0.01) * DYNAMIC_SUPPRESS

    v_lo, v_hi, a_lo, a_hi = _res_limits(eff)
    ratio = (eff - v_lo) / (v_hi - v_lo)
    ratio = min(max(ratio, 0.0), 1.0)  # clamp: gaps between tiers and > 2000
    reduction = a_lo + (a_hi - a_lo) * ratio**2
    return 1 - reduction


# --------------------------------------------------------------------------
# Full damage formula
# --------------------------------------------------------------------------
def calculate_damage(
    # --- attacker stats ---
    Atk: float,                             # キャラ攻撃力
    skillPercentAmend: float,               # スキルのダメージ倍率（主にスキルの表記より）
    talentGroupPercentAmend: float = 0.0,   # not used in game 素質グループの割合ダメージ（未使用）
    skillAbsAmend: float = 0.0,             # not used in game スキルの固定ダメージ加算値（未使用）
    talentGroupAbsAmend: float = 0.0,       # not used in game 素質の固定ダメージ加算値（未使用）
    skillIntensity: float = 1.0,            # 特定のスキルや攻撃の追加ダメージ倍率。特定スキル％。琥珀の「緻密温度調整」等
    perkIntensity: float = 1.0,             # not used in game パーク？
    slotDmg: float = 1.0,                   # 攻撃の種類に応じたダメージ補正。通常攻撃、スキル、必殺技、印、従者などの分類に対応する。
    elementDmg: float = 1.0,                # 攻撃側の属性に応じたダメージ補正。水・火・地・風・光・闇の各属性に関連する。
    generalDmg: float = 1.0,                # not used in game 汎用的なダメージ倍率補正（未使用）
    dmgPlus: float = 0.0,                   # not used in game 固定値ダメージ加算補正（未使用）
    critDmg: float = 1.5,                   # 会心ダメージ係数。基本は1.5倍。スキル、素質、紋章、装備等で増加
    slotCritDmg: float = 0.0,               # 通常攻撃、スキル、必殺技、印、飛翔物、従者などの内部分類に対応するタイプ別会心ダメージ増加係数
    crit_rate: float = 0.5,                 # 会心率。会心が発生する割合。
    is_dot: bool = False,                   # スリップダメージか否か。スリップダメージは会心発生しない。
    # --- enemy stats ---
    DEF: float = 500.0,                     # 防御係数。基本は500らしい
    DEF_Ignore: float = 0.0,                # not used in game 防御無視係数（未使用）
    DEF_Penetrate: float = 0.0,             # not used in game 敵の防御値を固定値で差し引く補正値（未使用）
    RES: float = 750.0,                     # 弱点属性 = 250, 中立 = 750, 耐性属性 = 2000
    PEN: float = 0.0,                       # 属性貫通値。
    IGNORING: float = 0.0,                  # not used in game
    VUL: float = 0.0,                       # 属性耐性が０以下の場合に適用される補正値。詳細不明
    slotDmgTaken: float = 1.0,              # ダメージの種別毎のダメージ補正
    elementDmgTaken: float = 1.0,           # 属性被ダメージ係数。特定の属性にかかる倍率
    generalDmgTaken: float = 1.0,           # not used in game 汎用ダメージ係数（未使用）
    resilienceBreakDmg: float = DEFAULT_RESILIENCE_BREAK_DMG,  # ブレイク時ダメージ係数。基本150%
    enemyBreakStatus: bool = False,         # ブレイク状態
    dmgPlusTaken: float = 0.0,              # not used in game 未使用
    # --- final ---
    finalDmg: float = 1.0,                  # not used in game 未使用
    finalDmgPlus: float = 0.0,              # not used in game 未使用
    # --- output ---
    as_int: bool = True,
) -> float | int:
    """Return the final damage value.

    Damage = (
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

    Like the game, the result is truncated to an integer and is at least 1.
    Pass as_int=False to get the raw float instead.

    Defaults for unused inputs are neutral, so only the inputs you care about
    need to be supplied. Note that RES defaults to 750 ("neutral" enemy, erAmend
    0.4) and DEF defaults to 500 (defAmend 0.5); resilienceBreakDmg defaults to 1.5
    as assumed in the gist. Set resilienceBreakDmg=1.0 to ignore it.
    """
    er = res_amend(RES, PEN, VUL, IGNORING)
    de = def_amend(DEF, DEF_Ignore, DEF_Penetrate)

    base = Atk * ((skillPercentAmend + talentGroupPercentAmend) * 0.0001 / 100)
    base += skillAbsAmend + talentGroupAbsAmend

    base *= skillIntensity * perkIntensity * slotDmg * elementDmg * generalDmg
    base += dmgPlus

    crit_mult = (
        (((critDmg + slotCritDmg) * crit_rate) + (1 * (1 - crit_rate)))
        if (not is_dot)
        else 1.0
    )

    taken_mult = er * de * slotDmgTaken * elementDmgTaken * generalDmgTaken
    if enemyBreakStatus:
        taken_mult = taken_mult * resilienceBreakDmg

    damage = base * crit_mult * taken_mult
    damage += dmgPlusTaken
    damage *= finalDmg
    damage += finalDmgPlus

    if as_int:
        return max(1, int(damage))
    return damage


if __name__ == "__main__":
    # Sanity checks against the examples in the gist
    for d, expected in [(500, 0.5), (350, 0.60227272727), (199, 0.73788198103)]:
        print(f"DEF {d}: defAmend = {def_amend(d):.11f} (gist: {expected})")

    for res, expected in [
        (30, 0.9964),
        (140, 0.9216),
        (250, 0.75),
        (350, 0.64015967808),
        (460, 0.60614375043),
        (570, 0.54783073161),
        (750, 0.4),
        (2000, 0.01),
    ]:
        print(f"RES {res}: erAmend = {res_amend(res):.11f} (gist: {expected})")

    print(
        f"VUL 0.05, Effective_RES -60: erAmend = {res_amend(RES=-60, VUL=0.05):.4f} (gist: 1.032)"
    )

    print(
        "Example damage:",
        calculate_damage(
            Atk=3000,
            skillPercentAmend=skill_percent_to_amend(250),
            DEF=350,
            RES=570,
            critDmg=1.5,
        ),
    )
