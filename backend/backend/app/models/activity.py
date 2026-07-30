from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, JSON
from sqlalchemy.sql import func
from app.database import Base

class Activity(Base):
    __tablename__ = "activities"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    garmin_activity_id = Column(String, unique=True, index=True)
    
    name = Column(String)
    activity_type = Column(String)
    start_time = Column(DateTime(timezone=True))
    
    distance = Column(Float) # in meters
    duration = Column(Float) # in seconds
    calories = Column(Integer)
    
    average_heart_rate = Column(Integer)
    max_heart_rate = Column(Integer)
    
    # Store detailed metrics like splits or time series as JSON
    details = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
