# backend/app/models.py
import enum
import uuid
from sqlalchemy import Column, String, Integer, DateTime, Boolean, Enum, JSON, ForeignKey
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
    exam_id = Column(String, ForeignKey('exams.id'), nullable=True)  # Link to exam

class Exam(Base):
    __tablename__ = "exams"
    id = Column(String, primary_key=True, default=gen_id)
    title = Column(String, nullable=False)
    language = Column(String, nullable=False)
    question_count = Column(Integer, nullable=False)
    time_allowed_secs = Column(Integer, nullable=False)
    created_by = Column(String, ForeignKey('users.id'), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    is_active = Column(Boolean, default=True)

class ExamAssignment(Base):
    __tablename__ = "exam_assignments"
    id = Column(String, primary_key=True, default=gen_id)
    exam_id = Column(String, ForeignKey('exams.id'), nullable=False)
    candidate_email = Column(String, nullable=False)  # Email of the candidate
    assigned_by = Column(String, ForeignKey('users.id'), nullable=False)  # Admin who assigned
    assigned_at = Column(DateTime(timezone=True), server_default=func.now())
    status = Column(String, default="assigned")  # assigned/started/completed

class CandidateExam(Base):
    __tablename__ = "candidate_exams"
    id = Column(String, primary_key=True, default=gen_id)
    user_id = Column(String, nullable=False)
    exam_id = Column(String, ForeignKey('exams.id'), nullable=False)  # Link to exam template
    question_ids = Column(JSON, nullable=True)  # ordered list of question ids
    answers = Column(JSON, nullable=True)  # mapping question_id -> selected index
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    ended_at = Column(DateTime, nullable=True)
    status = Column(String, default="not_started")  # in_progress/completed/timed_out
    time_allowed_secs = Column(Integer, default=1800)
    time_elapsed = Column(Integer, default=0)  # seconds

    score = Column(Integer, default=0)
