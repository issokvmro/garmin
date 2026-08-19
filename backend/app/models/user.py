from sqlalchemy import Column, Integer, String, Float, DateTime
from sqlalchemy.sql import func
from app.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    garmin_id = Column(String, unique=True, index=True)
    name = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # --- Profile fields powering scoring (Recovery baselines, Strain zones,
    # Sleep Need, Whoop Age). All nullable so the app degrades gracefully
    # until the user fills these in via Settings. ---
    birth_date = Column(DateTime(timezone=True), nullable=True)
    sex = Column(String, nullable=True)              # "male" | "female" | "other"
    weight_kg = Column(Float, nullable=True)
    height_cm = Column(Float, nullable=True)
    max_hr_override = Column(Integer, nullable=True)  # if unset, Tanaka formula is used
    resting_hr_baseline_override = Column(Integer, nullable=True)
    vo2_max = Column(Float, nullable=True)            # pulled from Garmin if available
