from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Date, JSON
from sqlalchemy.sql import func
from app.database import Base

class DailySummary(Base):
    __tablename__ = "daily_summaries"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    date = Column(Date, unique=True, index=True)
    
    # Recovery & Readiness
    recovery_score = Column(Integer, nullable=True) # Custom calculated score
    training_readiness = Column(Integer, nullable=True)
    body_battery_highest = Column(Integer, nullable=True)
    body_battery_lowest = Column(Integer, nullable=True)
    body_battery_current = Column(Integer, nullable=True)
    
    # Sleep
    sleep_score = Column(Integer, nullable=True)
    sleep_duration = Column(Integer, nullable=True) # in seconds
    deep_sleep = Column(Integer, nullable=True)
    rem_sleep = Column(Integer, nullable=True)
    light_sleep = Column(Integer, nullable=True)
    awake_time = Column(Integer, nullable=True)
    
    # Stress & HR
    hrv_status = Column(String, nullable=True)
    current_hrv = Column(Integer, nullable=True) # 7-day average or last night
    resting_heart_rate = Column(Integer, nullable=True)
    average_stress_level = Column(Integer, nullable=True)
    
    # Training
    training_load = Column(Float, nullable=True)
    calories_burned = Column(Integer, nullable=True)
    
    # Detailed Raw JSON Data (for deep dive charts)
    details = Column(JSON, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
