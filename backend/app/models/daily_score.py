from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Date, JSON
from sqlalchemy.sql import func
from app.database import Base


class DailyScore(Base):
    """
    Computed, explainable daily scores in the Whoop/noop style.

    These are DERIVED metrics — always recomputable from DailySummary /
    Activity rows. Nothing here comes directly from Garmin; it's our own
    scoring layer on top of raw Garmin data. See app/services/scoring.py
    for the exact formulas.
    """
    __tablename__ = "daily_scores"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    date = Column(Date, unique=True, index=True)

    # --- Recovery (Whoop "Recovery %") ---
    recovery_score = Column(Integer, nullable=True)       # 0-100
    recovery_band = Column(String, nullable=True)         # "red" | "yellow" | "green"
    hrv_baseline = Column(Float, nullable=True)            # rolling 30d mean RMSSD-proxy
    hrv_z = Column(Float, nullable=True)
    rhr_baseline = Column(Float, nullable=True)
    rhr_z = Column(Float, nullable=True)

    # --- Strain (Whoop "Strain", 0-21 Borg-style) ---
    strain_score = Column(Float, nullable=True)            # 0-21
    strain_band = Column(String, nullable=True)            # "light" | "moderate" | "high" | "all_out"
    strain_target_low = Column(Float, nullable=True)       # suggested target range from recovery
    strain_target_high = Column(Float, nullable=True)

    # --- Sleep Performance (Whoop "Sleep Performance %") ---
    sleep_performance = Column(Integer, nullable=True)     # 0-100, actual/need
    sleep_need_minutes = Column(Integer, nullable=True)
    sleep_debt_minutes = Column(Integer, nullable=True)    # rolling debt, floored at 0
    sleep_consistency = Column(Integer, nullable=True)     # 0-100, bed/wake time stability
    sleep_efficiency = Column(Integer, nullable=True)      # 0-100, time asleep / time in bed
    restorative_sleep_pct = Column(Integer, nullable=True) # deep+REM share

    # --- Stress Monitor (0-3 gauge, noop-style) ---
    stress_score = Column(Float, nullable=True)            # 0-3
    stress_band = Column(String, nullable=True)            # "low" | "medium" | "high"

    # --- Whoop Age / Physiological Age ---
    whoop_age_years = Column(Float, nullable=True)
    whoop_age_delta = Column(Float, nullable=True)         # negative = younger than chronological
    whoop_age_inputs = Column(JSON, nullable=True)         # component breakdown for transparency

    # --- Illness / strain-signature early warning ---
    illness_risk_flags = Column(JSON, nullable=True)       # list of anomaly strings, empty if none
    illness_risk_level = Column(String, nullable=True)     # "clear" | "watch" | "elevated"

    # Explainability: plain-English one-liners per score, shown in UI
    explanations = Column(JSON, nullable=True)

    computed_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
