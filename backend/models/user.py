from datetime import datetime
from enum import StrEnum
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class Gender(StrEnum):
    male = "male"
    female = "female"
    other = "other"


class ActivityLevel(StrEnum):
    sedentary = "sedentary"
    lightly_active = "lightly_active"
    moderately_active = "moderately_active"
    very_active = "very_active"
    extremely_active = "extremely_active"


class Goal(StrEnum):
    fat_loss = "fat_loss"
    weight_gain = "weight_gain"
    muscle_gain = "muscle_gain"
    maintenance = "maintenance"
    manage_medical = "manage_medical"


class DietType(StrEnum):
    vegetarian = "vegetarian"
    vegan = "vegan"
    non_vegetarian = "non_vegetarian"


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    full_name: str = Field(min_length=1)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ProfileCreateRequest(BaseModel):
    full_name: str
    gender: Gender
    age: int = Field(ge=13, le=100)
    height_cm: float = Field(gt=100, lt=250)
    weight_kg: float = Field(gt=20, lt=300)
    medical_conditions: list[str] = Field(default_factory=list)
    allergies: list[str] = Field(default_factory=list)
    medications: Optional[str] = None
    activity_level: ActivityLevel
    diet_type: DietType
    goal: Goal
    bot_name: str = Field(default="Nova", min_length=1)


class ProfileUpdateRequest(BaseModel):
    full_name: Optional[str] = None
    gender: Optional[Gender] = None
    age: Optional[int] = Field(default=None, ge=13, le=100)
    height_cm: Optional[float] = Field(default=None, gt=100, lt=250)
    weight_kg: Optional[float] = Field(default=None, gt=20, lt=300)
    medical_conditions: Optional[list[str]] = None
    allergies: Optional[list[str]] = None
    medications: Optional[str] = None
    activity_level: Optional[ActivityLevel] = None
    diet_type: Optional[DietType] = None
    goal: Optional[Goal] = None
    bot_name: Optional[str] = None


class UserInDB(BaseModel):
    id: str
    email: str
    full_name: str
    password_hash: Optional[str] = None
    google_id: Optional[str] = None
    gender: Optional[Gender] = None
    age: Optional[int] = None
    height_cm: Optional[float] = None
    weight_kg: Optional[float] = None
    medical_conditions: list[str] = Field(default_factory=list)
    allergies: list[str] = Field(default_factory=list)
    medications: Optional[str] = None
    activity_level: Optional[ActivityLevel] = None
    diet_type: Optional[DietType] = None
    goal: Optional[Goal] = None
    bot_name: str = "Nova"
    profile_complete: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class UserPublic(BaseModel):
    id: str
    email: str
    full_name: str
    gender: Optional[Gender] = None
    age: Optional[int] = None
    height_cm: Optional[float] = None
    weight_kg: Optional[float] = None
    medical_conditions: list[str] = Field(default_factory=list)
    allergies: list[str] = Field(default_factory=list)
    medications: Optional[str] = None
    activity_level: Optional[ActivityLevel] = None
    diet_type: Optional[DietType] = None
    goal: Optional[Goal] = None
    bot_name: str = "Nova"
    profile_complete: bool = False


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserPublic
