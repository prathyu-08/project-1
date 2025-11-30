# backend/app/main.py
from fastapi import FastAPI, Depends, HTTPException, Body
from sqlalchemy.orm import Session

from .insert_questions import insert_questions
from .db import Base, engine
from . import models, schemas, auth, exam
from datetime import datetime
from typing import List

app = FastAPI(title="NMK Certification Portal - MVP")

Base.metadata.create_all(bind=engine)


@app.post("/register", response_model=dict)
def register(payload: schemas.RegisterIn, db: Session = Depends(auth.get_db)):
    if auth.get_user_by_email(db, payload.email):
        raise HTTPException(status_code=400, detail="Email already registered")

    hashed = auth.get_password_hash(payload.password)

    u = models.User(
        email=payload.email,
        name=payload.name,
        hashed_password=hashed,
        is_admin=False
    )
    db.add(u)
    db.commit()
    db.refresh(u)

    return {"msg": "user created", "email": u.email}


@app.post("/login", response_model=schemas.Token)
def login(payload: dict = Body(...), db: Session = Depends(auth.get_db)):
    email = payload.get("email")
    password = payload.get("password")

    user = auth.authenticate_user(db, email, password)
    if not user:
        raise HTTPException(status_code=400, detail="Incorrect email or password")

    token = auth.create_access_token({"sub": user.email})
    return {"access_token": token, "token_type": "bearer"}


@app.post("/admin/question", response_model=dict)
def create_question(
    q: schemas.QuestionIn,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(auth.get_db)
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")

    if q.difficulty not in ("easy", "medium", "hard"):
        raise HTTPException(status_code=400, detail="Invalid difficulty")

    ques = models.Question(
        text=q.text,
        choices=q.choices,
        answer_index=q.answer_index,
        difficulty=q.difficulty
    )

    db.add(ques)
    db.commit()
    db.refresh(ques)

    return {"id": ques.id, "text": ques.text}


@app.post("/exam/start", response_model=schemas.ExamCreateOut)
def start_exam(
    qcount: int = 9,
    duration_secs: int = 1800,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(auth.get_db)
):
    ce = exam.create_candidate_exam(
        db,
        user_id=current_user.id,
        duration_secs=duration_secs,
        qcount=qcount
    )

    return {
        "id": ce.id,
        "question_ids": ce.question_ids,
        "time_allowed_secs": ce.time_allowed_secs
    }



@app.on_event("startup")
def load_default_questions():
    try:
        insert_questions()
    except Exception as e:
        print("Error loading default questions:", e)



@app.get("/exam/{exam_id}", response_model=schemas.ExamOut)
def get_exam(
    exam_id: str,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(auth.get_db)
):
    ce = db.query(models.CandidateExam).filter(
        models.CandidateExam.id == exam_id,
        models.CandidateExam.user_id == current_user.id
    ).first()

    if not ce:
        raise HTTPException(status_code=404, detail="Exam not found")

    questions = []
    for qid in ce.question_ids or []:
        q = db.query(models.Question).filter(models.Question.id == qid).first()
        if q:
            questions.append({
                "id": q.id,
                "text": q.text,
                "choices": q.choices,
                "difficulty": q.difficulty
            })

    return {
        "id": ce.id,
        "questions": questions,
        "time_allowed_secs": ce.time_allowed_secs,
        "time_elapsed": ce.time_elapsed,
        "status": ce.status
    }



@app.post("/exam/{exam_id}/save-answer", response_model=dict)
def save_answer(
    exam_id: str,
    payload: schemas.AnswerIn,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(auth.get_db)
):
    ce = db.query(models.CandidateExam).filter(
        models.CandidateExam.id == exam_id,
        models.CandidateExam.user_id == current_user.id
    ).first()

    if not ce:
        raise HTTPException(status_code=404, detail="Exam not found")

    if ce.status != "in_progress":
        raise HTTPException(status_code=400, detail=f"Exam not in progress ({ce.status})")

    # Save the answer and update time elapsed
    answers = ce.answers or {}
    answers[payload.question_id] = payload.selected_index
    ce.answers = answers
    ce.time_elapsed = payload.time_elapsed

    db.add(ce)
    db.commit()
    db.refresh(ce)

    return {"msg": "answer_saved", "time_elapsed": ce.time_elapsed}



@app.post("/exam/{exam_id}/submit", response_model=dict)
def submit_exam(
    exam_id: str,
    final_time_elapsed: int = Body(..., embed=True),
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(auth.get_db)
):
    ce = db.query(models.CandidateExam).filter(
        models.CandidateExam.id == exam_id,
        models.CandidateExam.user_id == current_user.id
    ).first()

    if not ce:
        raise HTTPException(status_code=404, detail="Exam not found")

    if ce.status != "in_progress":
        raise HTTPException(status_code=400, detail=f"Exam already {ce.status}")

   
    ce.time_elapsed = final_time_elapsed
    ce.status = "completed"
    ce.ended_at = datetime.utcnow()
    
    
    exam.compute_score(db, ce)
    
    db.add(ce)
    db.commit()
    db.refresh(ce)

    return {
        "msg": "exam_submitted",
        "exam_id": ce.id,
        "score": ce.score,
        "status": ce.status
    }



@app.post("/exam/{exam_id}/resume", response_model=schemas.ExamOut)
def resume_exam(
    exam_id: str,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(auth.get_db)
):
    ce = db.query(models.CandidateExam).filter(
        models.CandidateExam.id == exam_id,
        models.CandidateExam.user_id == current_user.id
    ).first()

    if not ce:
        raise HTTPException(status_code=404, detail="Exam not found")

    if ce.time_elapsed >= ce.time_allowed_secs and ce.status == "in_progress":
        ce.status = "timed_out"
        exam.compute_score(db, ce)
        db.add(ce)
        db.commit()
        db.refresh(ce)

    questions = []
    for qid in ce.question_ids or []:
        q = db.query(models.Question).filter(models.Question.id == qid).first()
        if q:
            questions.append({
                "id": q.id,
                "text": q.text,
                "choices": q.choices,
                "difficulty": q.difficulty
            })

    return {
        "id": ce.id,
        "questions": questions,
        "time_allowed_secs": ce.time_allowed_secs,
        "time_elapsed": ce.time_elapsed,
        "status": ce.status
    }



@app.get("/exam/{exam_id}/result", response_model=dict)
def get_result(
    exam_id: str,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(auth.get_db)
):
    ce = db.query(models.CandidateExam).filter(
        models.CandidateExam.id == exam_id,
        models.CandidateExam.user_id == current_user.id
    ).first()

    if not ce:
        raise HTTPException(status_code=404, detail="Exam not found")

    answers = ce.answers or {}
    details = []

    for qid in ce.question_ids or []:
        q = db.query(models.Question).filter(models.Question.id == qid).first()
        if q:
            selected = answers.get(qid)
            is_correct = (selected == q.answer_index) if selected is not None else False

            details.append({
                "question_id": qid,
                "question": q.text,
                "selected": selected,
                "correct_index": q.answer_index,
                "is_correct": is_correct
            })

    return {"score": ce.score, "status": ce.status, "details": details}