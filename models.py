from sqlalchemy import Column, String, Integer, Boolean, DateTime, JSON, Enum, Text
from sqlalchemy.sql import func
import uuid
import enum
from db import Base

# Function to generate unique IDs
def gen_id():
    return str(uuid.uuid4())

# Enum for difficulty levels
class Difficulty(str, enum.Enum):
    easy = "easy"
    medium = "medium"
    hard = "hard"

# -------------------
# USERS TABLE
# -------------------
class User(Base):
    __tablename__ = "users"
    id = Column(String(50), primary_key=True, default=gen_id)
    email = Column(String(100), nullable=False, unique=True)
    name = Column(String(100))
    hashed_password = Column(String(200), nullable=False)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

# -------------------
# QUESTIONS TABLE
# -------------------
class Question(Base):
    __tablename__ = "questions"
    id = Column(String(50), primary_key=True, default=gen_id)
    text = Column(String(500), nullable=False)
    choices = Column(JSON, nullable=False)
    answer_index = Column(Integer, nullable=False)
    difficulty = Column(Enum(Difficulty), nullable=False)
    subject = Column(String(100), nullable=False)

# -------------------
# EXAM TEMPLATES TABLE
# -------------------
class ExamTemplate(Base):
    __tablename__ = "exam_templates"
    id = Column(String(50), primary_key=True, default=gen_id)
    subject = Column(String(100), unique=True, nullable=False)
    description = Column(Text)
    question_count = Column(Integer, default=10)
    duration_minutes = Column(Integer, default=30)
    is_active = Column(Boolean, default=True)
    created_by = Column(String(50), nullable=False)  # admin user id
    created_at = Column(DateTime(timezone=True), server_default=func.now())

# -------------------
# CANDIDATE EXAMS TABLE
# -------------------
class CandidateExam(Base):
    __tablename__ = "candidate_exams"
    id = Column(String(50), primary_key=True, default=gen_id)
    user_id = Column(String(50), nullable=False)
    template_id = Column(String(50), nullable=False)
    subject = Column(String(100), nullable=False)
    question_ids = Column(JSON)   # list of question IDs
    answers = Column(JSON)        # dict {question_id: selected_index}
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    ended_at = Column(DateTime)
    status = Column(String(50), default="in_progress")  # in_progress, completed, timed_out
    time_allowed_secs = Column(Integer, default=1800)
    time_elapsed = Column(Integer, default=0)
    score = Column(Integer, default=0)
