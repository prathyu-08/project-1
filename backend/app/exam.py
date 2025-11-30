# backend/app/exam.py
import secrets
import random
from typing import List
from sqlalchemy.orm import Session
from .models import Question, CandidateExam, Difficulty
from .db import SessionLocal
from datetime import datetime

def select_questions_balanced(db: Session, total_n: int = 9) -> List[str]:
    # equally split among easy/medium/hard (floor if not divisible)
    base = total_n // 3
    remainder = total_n - base*3
    counts = {"easy": base, "medium": base, "hard": base}
    # distribute remainder starting from easy
    for k in list(counts.keys()):
        if remainder <= 0:
            break
        counts[k] += 1
        remainder -= 1

    pool = {}
    for d in counts.keys():
        pool[d] = [q.id for q in db.query(Question).filter(Question.difficulty == d).all()]

    selected = []
    seed = secrets.token_hex(8)
    rng = random.Random(seed)
    for d, n in counts.items():
        items = pool.get(d, [])
        if len(items) == 0:
            continue
        if len(items) <= n:
            picks = items.copy()
        else:
            picks = rng.sample(items, n)
        selected.extend(picks)
    rng.shuffle(selected)
    return selected

def create_candidate_exam(db: Session, user_id: str, duration_secs: int = 1800, qcount: int = 9):
    qids = select_questions_balanced(db, total_n=qcount)
    ce = CandidateExam(user_id=user_id, question_ids=qids, answers={}, time_allowed_secs=duration_secs, time_elapsed=0, status="in_progress")
    db.add(ce)
    db.commit()
    db.refresh(ce)
    return ce

def compute_score(db: Session, candidate_exam: CandidateExam):
    # load questions and compute correctness
    if not candidate_exam.question_ids:
        return 0
    correct = 0
    total = len(candidate_exam.question_ids)
    answers = candidate_exam.answers or {}
    for qid in candidate_exam.question_ids:
        q = db.query(Question).filter(Question.id == qid).first()
        if not q:
            continue
        sel = answers.get(qid)
        if sel is None:
            continue
        if sel == q.answer_index:
            correct += 1
    percent = int((correct / total) * 100) if total > 0 else 0
    candidate_exam.score = percent
    return percent