from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User

router = APIRouter(prefix="/profile", tags=["Profile"])


class ProfileOut(BaseModel):
    id: int
    name: Optional[str] = None
    birth_date: Optional[date] = None
    sex: Optional[str] = None
    weight_kg: Optional[float] = None
    height_cm: Optional[float] = None
    max_hr_override: Optional[int] = None
    resting_hr_baseline_override: Optional[int] = None
    vo2_max: Optional[float] = None

    class Config:
        from_attributes = True


class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    birth_date: Optional[date] = None
    sex: Optional[str] = None
    weight_kg: Optional[float] = None
    height_cm: Optional[float] = None
    max_hr_override: Optional[int] = None
    resting_hr_baseline_override: Optional[int] = None
    vo2_max: Optional[float] = None

    @field_validator("sex")
    @classmethod
    def validate_sex(cls, v):
        if v is not None and v not in ("male", "female", "other"):
            raise ValueError("sex must be 'male', 'female', or 'other'")
        return v


def _get_or_create_user(db: Session) -> User:
    user = db.query(User).first()
    if not user:
        user = User(name="Local User", garmin_id="local")
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


@router.get("", response_model=ProfileOut)
def get_profile(db: Session = Depends(get_db)):
    user = _get_or_create_user(db)
    return user


@router.patch("", response_model=ProfileOut)
def update_profile(update: ProfileUpdate, db: Session = Depends(get_db)):
    user = _get_or_create_user(db)

    data = update.model_dump(exclude_unset=True)
    for field, value in data.items():
        if field == "birth_date" and value is not None:
            # Store as DateTime column, midnight local
            value = datetime.combine(value, datetime.min.time())
        setattr(user, field, value)

    db.commit()
    db.refresh(user)
    return user
