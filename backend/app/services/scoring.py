"""
Scoring engine — turns raw Garmin fields into Whoop-style, explainable
daily scores: Recovery, Strain, Sleep Performance, Stress Monitor, and
Whoop Age.

Design principles (matching the noop reference app's philosophy):
  1. Every score is a HONEST APPROXIMATION from published/plausible methods,
     never a claim to reproduce Whoop's or Garmin's proprietary algorithms.
  2. Every score is re-computable at any time from stored raw data — nothing
     is a one-way black box. `explanations` on DailyScore stores a
     plain-English sentence for each number so the UI never shows a bare
     figure with no reasoning.
  3. Baselines are ALWAYS personal (rolling N-day mean/stdev against the
     user's own history), never population norms — this is what makes the
     numbers meaningful day to day.
  4. Not a medical device. Nothing here diagnoses or treats.

This module has no FastAPI/DB-session coupling beyond taking plain Python
values in and returning plain Python values out, so it's independently
testable.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _zscore(value: Optional[float], baseline_mean: Optional[float], baseline_std: Optional[float]) -> Optional[float]:
    if value is None or baseline_mean is None or not baseline_std or baseline_std <= 0:
        return None
    return (value - baseline_mean) / baseline_std


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _logistic(x: float, midpoint: float = 0.0, steepness: float = 1.0) -> float:
    """Standard logistic squashing to (0, 1)."""
    try:
        return 1.0 / (1.0 + math.exp(-steepness * (x - midpoint)))
    except OverflowError:
        return 0.0 if x < midpoint else 1.0


def rolling_baseline(values: list[float], window: int = 30) -> tuple[Optional[float], Optional[float]]:
    """Mean/stdev over the most recent `window` non-null values (excluding today)."""
    recent = [v for v in values[-window:] if v is not None]
    if len(recent) < 5:
        return (statistics.mean(recent) if recent else None, None)
    mean = statistics.mean(recent)
    std = statistics.pstdev(recent) if len(recent) > 1 else None
    return mean, std


# ---------------------------------------------------------------------------
# 1. RECOVERY (Whoop "Recovery %", 0-100, green/yellow/red)
# ---------------------------------------------------------------------------
#
# Whoop's real algorithm is proprietary; this is a transparent stand-in
# combining three inputs, each expressed as a personal z-score:
#   - HRV vs your 30-day baseline (higher is better)
#   - Resting HR vs your 30-day baseline (lower is better)
#   - Prior night's sleep performance (see section 3)
# Weighted sum -> logistic squash -> 0-100.

RECOVERY_WEIGHTS = {"hrv": 0.5, "rhr": 0.3, "sleep": 0.2}


@dataclass
class RecoveryResult:
    score: int
    band: str  # red < 34, yellow 34-66, green > 66 (Whoop's own bands)
    hrv_baseline: Optional[float]
    hrv_z: Optional[float]
    rhr_baseline: Optional[float]
    rhr_z: Optional[float]
    explanation: str


def compute_recovery(
    hrv_today: Optional[float],
    hrv_history: list[float],
    rhr_today: Optional[float],
    rhr_history: list[float],
    prior_sleep_performance: Optional[int],
) -> RecoveryResult:
    hrv_mean, hrv_std = rolling_baseline(hrv_history)
    rhr_mean, rhr_std = rolling_baseline(rhr_history)

    hrv_z = _zscore(hrv_today, hrv_mean, hrv_std)
    # RHR is inverted: being BELOW baseline is good, so flip sign
    rhr_z = _zscore(rhr_today, rhr_mean, rhr_std)
    rhr_z_inverted = -rhr_z if rhr_z is not None else None

    components = []
    weighted_sum = 0.0
    weight_total = 0.0

    if hrv_z is not None:
        weighted_sum += RECOVERY_WEIGHTS["hrv"] * hrv_z
        weight_total += RECOVERY_WEIGHTS["hrv"]
        components.append(("HRV", hrv_z))
    if rhr_z_inverted is not None:
        weighted_sum += RECOVERY_WEIGHTS["rhr"] * rhr_z_inverted
        weight_total += RECOVERY_WEIGHTS["rhr"]
        components.append(("resting HR", rhr_z_inverted))
    if prior_sleep_performance is not None:
        # Map 0-100 sleep performance to a rough z-equivalent centered on 75
        sleep_z = (prior_sleep_performance - 75) / 15.0
        weighted_sum += RECOVERY_WEIGHTS["sleep"] * sleep_z
        weight_total += RECOVERY_WEIGHTS["sleep"]
        components.append(("sleep", sleep_z))

    if weight_total == 0:
        # No data at all — return a neutral, clearly-flagged default
        return RecoveryResult(50, "yellow", hrv_mean, None, rhr_mean, None,
                               "Not enough data yet to compute recovery — keep syncing.")

    normalized_z = weighted_sum / weight_total
    score = round(_logistic(normalized_z, midpoint=0.0, steepness=1.1) * 100)
    score = int(_clamp(score, 1, 100))

    band = "red" if score < 34 else ("yellow" if score < 67 else "green")

    driver = max(components, key=lambda c: abs(c[1])) if components else None
    if driver:
        direction = "above" if driver[1] > 0 else "below"
        explanation = f"{band.capitalize()} recovery — {driver[0]} is the biggest driver, running {direction} your baseline."
    else:
        explanation = f"{band.capitalize()} recovery."

    return RecoveryResult(score, band, hrv_mean, hrv_z, rhr_mean, rhr_z, explanation)


# ---------------------------------------------------------------------------
# 2. STRAIN (Whoop "Strain", 0-21 Borg-scale-inspired cumulative load)
# ---------------------------------------------------------------------------
#
# Whoop's real strain uses continuous HR-zone integration across the whole
# day. We approximate with two contributing signals available from Garmin:
#   - Active calories burned relative to a resting baseline (proxy for
#     cardiovascular load across the day)
#   - Average daily stress level (Garmin's own 0-100 stress score, itself
#     HRV/RHR-derived) as a lower-resolution fill-in on days without
#     detailed HR-zone data.
# Combined on a 0-21 exponential scale (matches Whoop's own non-linear
# curve — each whole point is a meaningfully bigger jump in load).

@dataclass
class StrainResult:
    score: float
    band: str  # light <10, moderate 10-14, high 14-18, all_out >18
    target_low: float
    target_high: float
    explanation: str


def compute_strain(
    active_calories: Optional[float],
    resting_calories_baseline: float,
    avg_stress_today: Optional[float],
    recovery_score: Optional[int],
) -> StrainResult:
    active_calories = active_calories or 0.0
    cal_component = 0.0
    if active_calories > 0:
        # Diminishing-returns curve: log growth capped at 21
        cal_component = min(21.0, 3.0 + math.log(active_calories + 1) * 2.1)

    stress_component = 0.0
    if avg_stress_today is not None:
        stress_component = min(21.0, (avg_stress_today / 100.0) * 15.0)

    # Combine as "1 - product of remaining headroom", so neither signal alone
    # can dominate but both push strain up (mirrors Whoop's own additive-ish
    # but capped curve).
    headroom = (1.0 - cal_component / 21.0) * (1.0 - stress_component / 21.0)
    strain = round(21.0 * (1.0 - headroom), 1)
    strain = _clamp(strain, 0.0, 21.0)

    if strain < 10:
        band = "light"
    elif strain < 14:
        band = "moderate"
    elif strain < 18:
        band = "high"
    else:
        band = "all_out"

    # Suggested target range: higher recovery -> app can safely handle more strain
    if recovery_score is None:
        target_low, target_high = 8.0, 14.0
    elif recovery_score >= 67:
        target_low, target_high = 14.0, 18.0
    elif recovery_score >= 34:
        target_low, target_high = 10.0, 14.0
    else:
        target_low, target_high = 4.0, 9.0

    explanation = f"{band.replace('_', ' ').capitalize()} day (strain {strain}/21)."
    if recovery_score is not None:
        if strain > target_high:
            explanation += " That's above what your recovery suggested — recovery may take a hit tomorrow."
        elif strain < target_low:
            explanation += " You had more capacity today than you used."

    return StrainResult(strain, band, target_low, target_high, explanation)


# ---------------------------------------------------------------------------
# 3. SLEEP PERFORMANCE (Whoop "Sleep Performance %", debt, consistency)
# ---------------------------------------------------------------------------

@dataclass
class SleepResult:
    performance: int          # 0-100, actual/need
    need_minutes: int
    debt_minutes: int         # rolling debt vs need, floored at 0
    consistency: Optional[int]
    efficiency: Optional[int]
    restorative_pct: Optional[int]
    explanation: str


def estimate_sleep_need_minutes(
    baseline_sleep_minutes: Optional[float],
    recent_strain_avg: Optional[float],
    sleep_debt_prior_minutes: float = 0.0,
) -> int:
    """
    Whoop's Sleep Need = baseline + strain debt + sleep debt (from prior nights)
    + naps offset. We approximate with baseline (rolling personal average,
    default 8h if unknown) nudged up slightly on high-strain days, plus
    carry-forward debt.
    """
    base = baseline_sleep_minutes if baseline_sleep_minutes else 480.0  # 8h default
    strain_bump = 0.0
    if recent_strain_avg is not None and recent_strain_avg > 14:
        strain_bump = (recent_strain_avg - 14) * 3  # up to ~20min extra on hard days
    need = base + strain_bump + min(sleep_debt_prior_minutes, 90)  # cap carried debt influence
    return int(round(_clamp(need, 360, 600)))  # clamp 6h-10h


def compute_sleep(
    time_asleep_minutes: Optional[int],
    time_in_bed_minutes: Optional[int],
    deep_minutes: Optional[int],
    rem_minutes: Optional[int],
    need_minutes: int,
    bed_time_history: list[Optional[datetime]],
    wake_time_history: list[Optional[datetime]],
    prior_debt_minutes: float = 0.0,
) -> SleepResult:
    asleep = time_asleep_minutes or 0
    performance = int(_clamp(round((asleep / need_minutes) * 100), 0, 100)) if need_minutes else 0

    debt = max(0, need_minutes - asleep)
    # Rolling debt carries forward but decays 30%/night so it doesn't spiral forever
    total_debt = int(round(prior_debt_minutes * 0.7 + debt))

    efficiency = None
    if time_in_bed_minutes and time_in_bed_minutes > 0:
        efficiency = int(_clamp(round((asleep / time_in_bed_minutes) * 100), 0, 100))

    restorative_pct = None
    if asleep > 0 and (deep_minutes is not None or rem_minutes is not None):
        restorative_pct = int(_clamp(round(((deep_minutes or 0) + (rem_minutes or 0)) / asleep * 100), 0, 100))

    # Consistency: stdev of bed/wake clock times over last 2 weeks, mapped to 0-100
    consistency = _consistency_score(bed_time_history, wake_time_history)

    if performance >= 85:
        headline = "Well rested"
    elif performance >= 70:
        headline = "Adequately rested"
    elif performance >= 50:
        headline = "Short on sleep"
    else:
        headline = "Significant sleep debt"

    explanation = f"{headline} — {asleep // 60}h {asleep % 60}m of an estimated {need_minutes // 60}h {need_minutes % 60}m need."
    if total_debt > 60:
        explanation += f" Carrying ~{total_debt} min of sleep debt."

    return SleepResult(performance, need_minutes, total_debt, consistency, efficiency, restorative_pct, explanation)


def _consistency_score(bed_times: list[Optional[datetime]], wake_times: list[Optional[datetime]]) -> Optional[int]:
    def minutes_of_day(dt: Optional[datetime]) -> Optional[float]:
        if dt is None:
            return None
        return dt.hour * 60 + dt.minute

    bed_mins = [m for m in (minutes_of_day(t) for t in bed_times) if m is not None]
    wake_mins = [m for m in (minutes_of_day(t) for t in wake_times) if m is not None]
    if len(bed_mins) < 4 or len(wake_mins) < 4:
        return None

    def circ_stdev(mins: list[float]) -> float:
        # Handle midnight wraparound by shifting anything before noon +1440
        shifted = [m + 1440 if m < 720 else m for m in mins]
        return statistics.pstdev(shifted)

    bed_std = circ_stdev(bed_mins)
    wake_std = circ_stdev(wake_mins)
    avg_std = (bed_std + wake_std) / 2
    # 0 min stdev -> 100, 120+ min stdev -> ~0
    score = _clamp(100 - (avg_std / 120) * 100, 0, 100)
    return int(round(score))


# ---------------------------------------------------------------------------
# 4. STRESS MONITOR (0-3 gauge, noop-style baseline comparison)
# ---------------------------------------------------------------------------

@dataclass
class StressResult:
    score: float  # 0-3
    band: str     # low <1.0, medium 1.0-2.0, high >2.0
    explanation: str


def compute_stress_monitor(
    rhr_today: Optional[float],
    rhr_history: list[float],
    hrv_today: Optional[float],
    hrv_history: list[float],
    garmin_stress_today: Optional[float] = None,
) -> StressResult:
    # Prefer Garmin's own recorded stress score if present, rescaled to 0-3
    if garmin_stress_today is not None:
        score = _clamp(garmin_stress_today / 100.0 * 3.0, 0.0, 3.0)
        band = "low" if score < 1.0 else ("medium" if score < 2.0 else "high")
        return StressResult(round(score, 1), band, f"Stress {round(score,1)}/3 from today's recorded stress reading.")

    rhr_mean, rhr_std = rolling_baseline(rhr_history)
    hrv_mean, hrv_std = rolling_baseline(hrv_history)
    rhr_z = _zscore(rhr_today, rhr_mean, rhr_std) or 0.0
    hrv_z = _zscore(hrv_today, hrv_mean, hrv_std) or 0.0

    # Higher RHR and lower HRV both push stress up
    combined = (rhr_z - hrv_z) / 2.0
    score = round(_logistic(combined, midpoint=0.0, steepness=1.0) * 3.0, 1)
    band = "low" if score < 1.0 else ("medium" if score < 2.0 else "high")

    explanation = f"Stress {score}/3, derived from today's resting HR and HRV vs your 30-day baseline."
    return StressResult(score, band, explanation)


# ---------------------------------------------------------------------------
# 5. WHOOP AGE / PHYSIOLOGICAL AGE
# ---------------------------------------------------------------------------
#
# Not a clinical fitness-age test. Approximates Whoop Age's spirit: compare
# your resting HR, HRV, VO2max proxy, and activity consistency against
# population-typical age curves, and nudge chronological age up/down.
# Cite: Tanaka max-HR formula (208 - 0.7*age); RHR/HRV age-decline curves
# are simplified linear approximations for a self-tracking estimate only.

@dataclass
class WhoopAgeResult:
    age_years: float
    delta_years: float  # negative = younger than chronological
    inputs: dict
    explanation: str


def compute_whoop_age(
    chronological_age: float,
    resting_hr_avg: Optional[float],
    hrv_avg: Optional[float],
    vo2_max: Optional[float],
    weekly_active_minutes: Optional[float],
    sex: Optional[str] = None,
) -> WhoopAgeResult:
    delta = 0.0
    inputs = {}

    # RHR: population norm roughly rises ~0.15 bpm/year from a 60bpm/age-30 anchor.
    # Every 5bpm below/above the age-adjusted norm shifts age ~2 years.
    if resting_hr_avg is not None:
        expected_rhr = 60 + 0.15 * (chronological_age - 30)
        rhr_delta_years = ((resting_hr_avg - expected_rhr) / 5.0) * 2.0
        delta += rhr_delta_years
        inputs["resting_hr"] = {"value": resting_hr_avg, "expected": round(expected_rhr, 1), "years": round(rhr_delta_years, 1)}

    # HRV: population norm declines roughly linearly from ~55ms at 25 to ~25ms
    # at 65 (a widely-cited rough shape, not a clinical constant).
    if hrv_avg is not None:
        expected_hrv = max(20.0, 55 - (chronological_age - 25) * 0.75)
        hrv_delta_years = ((expected_hrv - hrv_avg) / 5.0) * 1.5
        delta += hrv_delta_years
        inputs["hrv"] = {"value": hrv_avg, "expected": round(expected_hrv, 1), "years": round(hrv_delta_years, 1)}

    # VO2max: every 3.5 ml/kg/min (roughly 1 MET) above/below age-typical
    # shifts estimated age ~1.5 years.
    if vo2_max is not None:
        sex_base = 45 if sex == "male" else 40
        expected_vo2 = max(20.0, sex_base - (chronological_age - 25) * 0.4)
        vo2_delta_years = ((expected_vo2 - vo2_max) / 3.5) * 1.5
        delta += vo2_delta_years
        inputs["vo2_max"] = {"value": vo2_max, "expected": round(expected_vo2, 1), "years": round(vo2_delta_years, 1)}

    # Activity consistency: 150+ active minutes/week is the WHO baseline;
    # being well above/below nudges age down/up modestly.
    if weekly_active_minutes is not None:
        activity_delta_years = -_clamp((weekly_active_minutes - 150) / 150.0, -1.5, 1.5)
        delta += activity_delta_years
        inputs["weekly_active_minutes"] = {"value": weekly_active_minutes, "years": round(activity_delta_years, 1)}

    delta = _clamp(delta, -15.0, 15.0)
    age_years = round(chronological_age + delta, 1)

    if delta <= -2:
        explanation = f"Your metrics track like someone about {abs(round(delta))} years younger than your age."
    elif delta >= 2:
        explanation = f"Your metrics track like someone about {round(delta)} years older than your age — room to close the gap."
    else:
        explanation = "Your metrics track close to your actual age."

    return WhoopAgeResult(age_years, round(delta, 1), inputs, explanation)


# ---------------------------------------------------------------------------
# 6. ILLNESS / STRAIN-SIGNATURE EARLY WARNING (noop-style)
# ---------------------------------------------------------------------------

@dataclass
class IllnessWatchResult:
    flags: list[str]
    level: str  # "clear" | "watch" | "elevated"


def compute_illness_watch(
    rhr_today: Optional[float],
    rhr_baseline: Optional[float],
    hrv_today: Optional[float],
    hrv_baseline: Optional[float],
    respiration_today: Optional[float],
    respiration_baseline: Optional[float],
) -> IllnessWatchResult:
    flags = []

    if rhr_today is not None and rhr_baseline is not None and rhr_today - rhr_baseline >= 5:
        flags.append(f"Resting HR up {round(rhr_today - rhr_baseline)} bpm vs your baseline")

    if hrv_today is not None and hrv_baseline is not None and hrv_baseline > 0:
        drop_pct = (hrv_baseline - hrv_today) / hrv_baseline
        if drop_pct >= 0.20:
            flags.append(f"HRV down {round(drop_pct * 100)}% vs your baseline")

    if respiration_today is not None and respiration_baseline is not None and respiration_today - respiration_baseline >= 1.5:
        flags.append("Respiratory rate elevated vs your baseline")

    level = "clear"
    if len(flags) == 1:
        level = "watch"
    elif len(flags) >= 2:
        level = "elevated"

    return IllnessWatchResult(flags, level)
