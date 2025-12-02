# backend/app/models.py
import enum
import uuid
from sqlalchemy import Column, String, Integer, DateTime, Boolean, Enum, JSON
from sqlalchemy.sql import func
from .db import Base

def gen_id():
    return str(uuid.uuid4())

class Difficulty(str, enum.Enum):
    easy = "easy"
    medium = "medium"
    hard = "hard"

class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, default=gen_id)
    email = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=True)
    hashed_password = Column(String, nullable=False)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Question(Base):
    __tablename__ = "questions"
    id = Column(String, primary_key=True, default=gen_id)
    text = Column(String, nullable=False)
    choices = Column(JSON, nullable=False)  # list of choices
    answer_index = Column(Integer, nullable=False)  # index in choices (0-based)
    difficulty = Column(Enum(Difficulty), index=True, nullable=False)

class CandidateExam(Base):
    __tablename__ = "candidate_exams"
    id = Column(String, primary_key=True, default=gen_id)
    user_id = Column(String, nullable=False)
    question_ids = Column(JSON, nullable=True)  # ordered list of question ids
    answers = Column(JSON, nullable=True)  # mapping question_id -> selected index
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    ended_at = Column(DateTime, nullable=True)
    status = Column(String, default="in_progress")  # in_progress/completed/timed_out
    time_allowed_secs = Column(Integer, default=1800)
    time_elapsed = Column(Integer, default=0)  # seconds
    score = Column(Integer, default=0)
