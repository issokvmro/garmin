"""
Score pipeline — bridges the DB (DailySummary/Activity rows) and the pure
scoring engine in app/services/scoring.py. This is the only place that
touches SQLAlchemy sessions for scoring; scoring.py itself stays framework-free
and unit-testable.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.models.daily_summary import DailySummary
from app.models.daily_score import DailyScore
from app.models.activity import Activity
from app.models.user import User
from app.services import scoring

logger = logging.getLogger(__name__)

HISTORY_WINDOW_DAYS = 45  # enough for 30-day rolling baselines + a buffer


def _get_or_create_user(db: Session) -> User:
    user = db.query(User).first()
    if not user:
        user = User(name="Local User", garmin_id="local")
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def _history_series(rows: list[DailySummary], attr: str) -> list[Optional[float]]:
    return [getattr(r, attr) for r in rows]


def _bed_wake_times(row: Optional[DailySummary]) -> tuple[Optional[datetime], Optional[datetime]]:
    if not row or not row.details:
        return None, None
    sleep = row.details.get("sleep") if isinstance(row.details, dict) else None
    if not sleep:
        return None, None
    dto = sleep.get("dailySleepDTO", {}) if isinstance(sleep, dict) else {}
    start_ms = dto.get("sleepStartTimestampLocal") or dto.get("sleepStartTimestampGMT")
    end_ms = dto.get("sleepEndTimestampLocal") or dto.get("sleepEndTimestampGMT")
    start = datetime.fromtimestamp(start_ms / 1000) if start_ms else None
    end = datetime.fromtimestamp(end_ms / 1000) if end_ms else None
    return start, end


def _respiration(row: Optional[DailySummary]) -> Optional[float]:
    if not row or not row.details:
        return None
    sleep = row.details.get("sleep") if isinstance(row.details, dict) else None
    if not isinstance(sleep, dict):
        return None
    dto = sleep.get("dailySleepDTO", {})
    return dto.get("averageRespirationValue")


def compute_and_store_score(db: Session, target_date: date) -> Optional[DailyScore]:
    """Compute all scores for a single date and upsert the DailyScore row."""
    user = _get_or_create_user(db)

    window_start = target_date - timedelta(days=HISTORY_WINDOW_DAYS)
    rows = (
        db.query(DailySummary)
        .filter(DailySummary.user_id == user.id)
        .filter(DailySummary.date >= window_start)
        .filter(DailySummary.date <= target_date)
        .order_by(DailySummary.date.asc())
        .all()
    )
    if not rows:
        logger.warning(f"No DailySummary data found for or before {target_date}")
        return None

    today_row = next((r for r in rows if r.date == target_date), None)
    if not today_row:
        logger.warning(f"No DailySummary row for {target_date} itself")
        return None

    history_rows = [r for r in rows if r.date < target_date]
    prior_row = history_rows[-1] if history_rows else None

    hrv_history = _history_series(history_rows, "current_hrv")
    rhr_history = _history_series(history_rows, "resting_heart_rate")

    # --- Sleep (compute first — recovery depends on it) ---
    bed_times = [_bed_wake_times(r)[0] for r in rows[-14:]]
    wake_times = [_bed_wake_times(r)[1] for r in rows[-14:]]
    sleep_minutes_history = [
        (r.sleep_duration / 60.0) if r.sleep_duration else None for r in history_rows
    ]
    baseline_sleep_minutes, _ = scoring.rolling_baseline(
        [v for v in sleep_minutes_history if v is not None]
    )
    strain_history = []  # filled in below after we know prior DailyScore rows
    prior_strain_avg = None
    prior_scores = (
        db.query(DailyScore)
        .filter(DailyScore.user_id == user.id)
        .filter(DailyScore.date < target_date)
        .order_by(DailyScore.date.desc())
        .limit(7)
        .all()
    )
    strain_vals = [s.strain_score for s in prior_scores if s.strain_score is not None]
    if strain_vals:
        prior_strain_avg = sum(strain_vals) / len(strain_vals)
    prior_debt = prior_scores[0].sleep_debt_minutes if prior_scores and prior_scores[0].sleep_debt_minutes else 0.0

    need_minutes = scoring.estimate_sleep_need_minutes(baseline_sleep_minutes, prior_strain_avg, prior_debt)

    sleep_result = scoring.compute_sleep(
        time_asleep_minutes=(today_row.sleep_duration // 60) if today_row.sleep_duration else None,
        time_in_bed_minutes=(
            (today_row.sleep_duration + (today_row.awake_time or 0)) // 60
            if today_row.sleep_duration else None
        ),
        deep_minutes=(today_row.deep_sleep // 60) if today_row.deep_sleep else None,
        rem_minutes=(today_row.rem_sleep // 60) if today_row.rem_sleep else None,
        need_minutes=need_minutes,
        bed_time_history=bed_times,
        wake_time_history=wake_times,
        prior_debt_minutes=prior_debt,
    )

    # --- Recovery ---
    recovery_result = scoring.compute_recovery(
        hrv_today=today_row.current_hrv,
        hrv_history=hrv_history,
        rhr_today=today_row.resting_heart_rate,
        rhr_history=rhr_history,
        prior_sleep_performance=(
            prior_scores[0].sleep_performance if prior_scores else sleep_result.performance
        ),
    )

    # --- Strain ---
    day_activities = (
        db.query(Activity)
        .filter(Activity.user_id == user.id)
        .filter(Activity.start_time >= datetime.combine(target_date, datetime.min.time()))
        .filter(Activity.start_time <= datetime.combine(target_date, datetime.max.time()))
        .all()
    )
    active_calories = sum((a.calories or 0) for a in day_activities)
    if not active_calories and today_row.calories_burned:
        active_calories = max(0, today_row.calories_burned - 1800)  # rough BMR floor

    strain_result = scoring.compute_strain(
        active_calories=active_calories,
        resting_calories_baseline=1800,
        avg_stress_today=today_row.average_stress_level,
        recovery_score=recovery_result.score,
    )

    # --- Stress monitor ---
    stress_result = scoring.compute_stress_monitor(
        rhr_today=today_row.resting_heart_rate,
        rhr_history=rhr_history,
        hrv_today=today_row.current_hrv,
        hrv_history=hrv_history,
        garmin_stress_today=today_row.average_stress_level,
    )

    # --- Illness watch ---
    resp_today = _respiration(today_row)
    resp_history = [v for v in (_respiration(r) for r in history_rows) if v is not None]
    resp_baseline = sum(resp_history) / len(resp_history) if resp_history else None
    illness_result = scoring.compute_illness_watch(
        rhr_today=today_row.resting_heart_rate,
        rhr_baseline=recovery_result.rhr_baseline,
        hrv_today=today_row.current_hrv,
        hrv_baseline=recovery_result.hrv_baseline,
        respiration_today=resp_today,
        respiration_baseline=resp_baseline,
    )

    # --- Whoop Age (only if we have a birth date on the profile) ---
    whoop_age_result = None
    if user.birth_date:
        chronological_age = (target_date - user.birth_date.date()).days / 365.25
        recent_hrv = [v for v in hrv_history[-30:] if v is not None]
        recent_rhr = [v for v in rhr_history[-30:] if v is not None]
        weekly_active_minutes = None
        two_weeks_ago = target_date - timedelta(days=14)
        recent_acts = (
            db.query(Activity)
            .filter(Activity.user_id == user.id)
            .filter(Activity.start_time >= datetime.combine(two_weeks_ago, datetime.min.time()))
            .all()
        )
        if recent_acts:
            total_minutes = sum((a.duration or 0) / 60.0 for a in recent_acts)
            weekly_active_minutes = total_minutes / 2.0

        whoop_age_result = scoring.compute_whoop_age(
            chronological_age=chronological_age,
            resting_hr_avg=(sum(recent_rhr) / len(recent_rhr)) if recent_rhr else None,
            hrv_avg=(sum(recent_hrv) / len(recent_hrv)) if recent_hrv else None,
            vo2_max=user.vo2_max,
            weekly_active_minutes=weekly_active_minutes,
            sex=user.sex,
        )

    # --- Upsert ---
    score_row = (
        db.query(DailyScore)
        .filter(DailyScore.user_id == user.id, DailyScore.date == target_date)
        .first()
    )
    if not score_row:
        score_row = DailyScore(user_id=user.id, date=target_date)
        db.add(score_row)

    score_row.recovery_score = recovery_result.score
    score_row.recovery_band = recovery_result.band
    score_row.hrv_baseline = recovery_result.hrv_baseline
    score_row.hrv_z = recovery_result.hrv_z
    score_row.rhr_baseline = recovery_result.rhr_baseline
    score_row.rhr_z = recovery_result.rhr_z

    score_row.strain_score = strain_result.score
    score_row.strain_band = strain_result.band
    score_row.strain_target_low = strain_result.target_low
    score_row.strain_target_high = strain_result.target_high

    score_row.sleep_performance = sleep_result.performance
    score_row.sleep_need_minutes = sleep_result.need_minutes
    score_row.sleep_debt_minutes = sleep_result.debt_minutes
    score_row.sleep_consistency = sleep_result.consistency
    score_row.sleep_efficiency = sleep_result.efficiency
    score_row.restorative_sleep_pct = sleep_result.restorative_pct

    score_row.stress_score = stress_result.score
    score_row.stress_band = stress_result.band

    if whoop_age_result:
        score_row.whoop_age_years = whoop_age_result.age_years
        score_row.whoop_age_delta = whoop_age_result.delta_years
        score_row.whoop_age_inputs = whoop_age_result.inputs

    score_row.illness_risk_flags = illness_result.flags
    score_row.illness_risk_level = illness_result.level

    score_row.explanations = {
        "recovery": recovery_result.explanation,
        "strain": strain_result.explanation,
        "sleep": sleep_result.explanation,
        "stress": stress_result.explanation,
        "whoop_age": whoop_age_result.explanation if whoop_age_result else None,
    }

    db.commit()
    db.refresh(score_row)
    return score_row


def recompute_range(db: Session, start_date: date, end_date: date) -> int:
    """Recompute scores for every day in [start_date, end_date]. Returns count computed."""
    count = 0
    current = start_date
    while current <= end_date:
        result = compute_and_store_score(db, current)
        if result:
            count += 1
        current += timedelta(days=1)
    return count
