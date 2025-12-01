# backend/app/schemas.py
from pydantic import BaseModel, EmailStr
from typing import List, Dict, Optional

class RegisterIn(BaseModel):
    email: EmailStr
    password: str
    name: Optional[str] = None

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class LoginIn(BaseModel):
    email: EmailStr
    password: str

class QuestionIn(BaseModel):
    text: str
    choices: List[str]
    answer_index: int
    difficulty: str  # "easy"/"medium"/"hard"

class QuestionOut(BaseModel):
    id: str
    text: str
    choices: List[str]
    difficulty: str

class ExamCreateOut(BaseModel):
    id: str
    question_ids: List[str]
    time_allowed_secs: int

class ExamOut(BaseModel):
    id: str
    questions: List[QuestionOut]
    time_allowed_secs: int
    time_elapsed: int
    status: str

class AnswerIn(BaseModel):
    question_id: str
    selected_index: int
    time_elapsed: int  # seconds elapsed so far on client (to help server)
