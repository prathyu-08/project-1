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
    
    print(f"\n{'='*60}")
    print(f"COMPUTING SCORE")
    print(f"{'='*60}")
    print(f"Total questions: {total}")
    print(f"Stored answers: {answers}")
    print(f"{'='*60}\n")
    
    for qid in candidate_exam.question_ids:
        q = db.query(Question).filter(Question.id == qid).first()
        if not q:
            print(f"⚠️ Question {qid} not found in database")
            continue
        
        # ✅ FIX: Convert qid to string to match storage format
        qid_str = str(qid)
        sel = answers.get(qid_str)
        
        print(f"Question: {q.text[:50]}...")
        print(f"  Question ID: {qid} → lookup key: '{qid_str}'")
        print(f"  Selected: {sel}, Correct: {q.answer_index}")
        
        if sel is None:
            print(f"  ❌ No answer recorded")
            continue
        
        if sel == q.answer_index:
            correct += 1
            print(f"  ✅ CORRECT!")
        else:
            print(f"  ❌ WRONG!")
        print("-" * 40)
    
    percent = int((correct / total) * 100) if total > 0 else 0
    candidate_exam.score = percent
    
    print(f"\n{'='*60}")
    print(f"FINAL SCORE: {correct}/{total} = {percent}%")
    print(f"{'='*60}\n")
    
    return percent
