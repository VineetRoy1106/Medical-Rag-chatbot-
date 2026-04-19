"""
Curalink — User Profile Pydantic Schemas
Request/response models for user management endpoints.
"""

from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List, Literal
from datetime import datetime


class UserCondition(BaseModel):
    name:           str
    diagnosed_date: Optional[str] = None
    severity:       Optional[Literal["mild", "moderate", "severe"]] = None
    notes:          Optional[str] = None


class UserMedication(BaseModel):
    name:      str
    dose:      Optional[str] = None
    frequency: Optional[str] = None


class UserPreferences(BaseModel):
    preferred_study_types:  List[str] = [
        "human_rct", "human_systematic_review", "human_meta_analysis"
    ]
    language_complexity:    Literal["simple", "intermediate", "expert"] = "intermediate"
    show_animal_studies:    bool = False
    location_bias_trials:   bool = True
    preferred_sources:      List[str] = ["pubmed", "openalex"]
    email_updates:          bool = False


class CreateUserRequest(BaseModel):
    user_id:     str              = Field(..., example="user_john_smith_001")
    name:        str              = Field(..., example="John Smith")
    email:       Optional[str]   = Field(None, example="john@example.com")
    age:         Optional[int]   = Field(None, example=62)
    gender:      Optional[str]   = Field(None, example="male")
    location:    Optional[str]   = Field(None, example="Toronto, Canada")
    conditions:  List[UserCondition]   = []
    medications: List[UserMedication]  = []
    allergies:   List[str]             = []
    preferences: UserPreferences       = Field(default_factory=UserPreferences)

    class Config:
        json_schema_extra = {
            "example": {
                "user_id":  "user_john_smith_001",
                "name":     "John Smith",
                "email":    "john@example.com",
                "age":      62,
                "gender":   "male",
                "location": "Toronto, Canada",
                "conditions": [
                    {"name": "Parkinson's disease", "diagnosed_date": "2021-03", "severity": "moderate"}
                ],
                "medications": [
                    {"name": "Levodopa", "dose": "100mg", "frequency": "3x daily"}
                ],
                "allergies": ["Penicillin"],
                "preferences": {
                    "preferred_study_types":  ["human_rct", "human_systematic_review"],
                    "language_complexity":     "intermediate",
                    "show_animal_studies":     False,
                    "location_bias_trials":    True,
                }
            }
        }


class UpdatePreferencesRequest(BaseModel):
    preferred_study_types:  Optional[List[str]] = None
    language_complexity:    Optional[Literal["simple", "intermediate", "expert"]] = None
    show_animal_studies:    Optional[bool] = None
    location_bias_trials:   Optional[bool] = None
    preferred_sources:      Optional[List[str]] = None


class BookmarkRequest(BaseModel):
    type:     Literal["paper", "trial"] = "paper"
    item_id:  str
    title:    str
    url:      str
    source:   Optional[str] = None
    year:     Optional[int] = None
    notes:    Optional[str] = None
    tags:     List[str]     = []

    class Config:
        json_schema_extra = {
            "example": {
                "type":    "paper",
                "item_id": "abc123def456",
                "title":   "Deep Brain Stimulation outcomes in Parkinson's",
                "url":     "https://pubmed.ncbi.nlm.nih.gov/12345678/",
                "source":  "pubmed",
                "year":    2023,
                "notes":   "Relevant for DBS decision",
                "tags":    ["DBS", "treatment"]
            }
        }


class UserResponse(BaseModel):
    user_id:     str
    name:        str
    location:    Optional[str]
    conditions:  List[UserCondition]
    preferences: UserPreferences
    behavior:    dict
    created_at:  datetime
