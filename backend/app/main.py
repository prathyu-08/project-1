
from fastapi import FastAPI, Depends, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from .insert_questions import insert_questions
from .db import Base, engine
from . import models, schemas, auth, exam
from datetime import datetime

app = FastAPI(title="NMK Certification Portal")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Base.metadata.create_all(bind=engine)


@app.post("/register")
def register(payload: schemas.RegisterIn, db: Session = Depends(auth.get_db)):
    if auth.get_user_by_email(db, payload.email):
        raise HTTPException(status_code=400, detail="Email already registered")

    hashed = auth.get_password_hash(payload.password)

    user = models.User(
        email=payload.email,
        name=payload.name,
        hashed_password=hashed,
        is_admin=False
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return {"msg": "user created", "email": user.email}


@app.post("/login", response_model=schemas.Token)
def login(payload: dict = Body(...), db: Session = Depends(auth.get_db)):
    email = payload.get("email")
    password = payload.get("password")

    user = auth.authenticate_user(db, email, password)
    if not user:
        raise HTTPException(status_code=400, detail="Incorrect email or password")

    token = auth.create_access_token({"sub": user.email})
    return {"access_token": token, "token_type": "bearer"}


@app.post("/admin/question")
def create_question(
    q: schemas.QuestionIn,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(auth.get_db)
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")

    if q.difficulty not in ("easy", "medium", "hard"):
        raise HTTPException(status_code=400, detail="Invalid difficulty")

    question = models.Question(
        text=q.text,
        choices=q.choices,
        answer_index=q.answer_index,
        difficulty=q.difficulty
    )

    db.add(question)
    db.commit()
    db.refresh(question)

    return {"id": question.id, "text": question.text}


@app.post("/exam/start", response_model=schemas.ExamCreateOut)
def start_exam(
    qcount: int = 9,
    duration_secs: int = 1800,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(auth.get_db)
):
    candidate_exam = exam.create_candidate_exam(
        db,
        user_id=current_user.id,
        duration_secs=duration_secs,
        qcount=qcount
    )

    return {
        "id": candidate_exam.id,
        "question_ids": candidate_exam.question_ids,
        "time_allowed_secs": candidate_exam.time_allowed_secs
    }


@app.on_event("startup")
def load_default_questions():
    try:
        insert_questions()
    except Exception as e:
        print(f"Error loading questions: {e}")


@app.get("/exam/{exam_id}", response_model=schemas.ExamOut)
def get_exam(
    exam_id: str,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(auth.get_db)
):
    candidate_exam = db.query(models.CandidateExam).filter(
        models.CandidateExam.id == exam_id,
        models.CandidateExam.user_id == current_user.id
    ).first()

    if not candidate_exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    questions = []
    for qid in candidate_exam.question_ids or []:
        question = db.query(models.Question).filter(models.Question.id == qid).first()
        if question:
            questions.append({
                "id": question.id,
                "text": question.text,
                "choices": question.choices,
                "difficulty": question.difficulty
            })

    return {
        "id": candidate_exam.id,
        "questions": questions,
        "time_allowed_secs": candidate_exam.time_allowed_secs,
        "time_elapsed": candidate_exam.time_elapsed,
        "status": candidate_exam.status
    }


@app.post("/exam/{exam_id}/save-answer")
def save_answer(
    exam_id: str,
    payload: schemas.AnswerIn,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(auth.get_db)
):
    candidate_exam = db.query(models.CandidateExam).filter(
        models.CandidateExam.id == exam_id,
        models.CandidateExam.user_id == current_user.id
    ).first()

    if not candidate_exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    if candidate_exam.status != "in_progress":
        raise HTTPException(status_code=400, detail=f"Exam not in progress")

    
    answers = dict(candidate_exam.answers or {})
    question_id = str(payload.question_id)
    answers[question_id] = payload.selected_index
    
    candidate_exam.answers = answers
    candidate_exam.time_elapsed = payload.time_elapsed
    
    flag_modified(candidate_exam, "answers")

    db.commit()
    db.refresh(candidate_exam)

    return {"msg": "answer_saved", "time_elapsed": candidate_exam.time_elapsed}


@app.post("/exam/{exam_id}/submit")
def submit_exam(
    exam_id: str,
    final_time_elapsed: int = Body(..., embed=True),
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(auth.get_db)
):
    candidate_exam = db.query(models.CandidateExam).filter(
        models.CandidateExam.id == exam_id,
        models.CandidateExam.user_id == current_user.id
    ).first()

    if not candidate_exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    if candidate_exam.status != "in_progress":
        raise HTTPException(status_code=400, detail=f"Exam already {candidate_exam.status}")
   
    candidate_exam.time_elapsed = final_time_elapsed
    candidate_exam.status = "completed"
    candidate_exam.ended_at = datetime.utcnow()
    
    exam.compute_score(db, candidate_exam)
    
    db.add(candidate_exam)
    db.commit()
    db.refresh(candidate_exam)

    return {
        "msg": "exam_submitted",
        "exam_id": candidate_exam.id,
        "score": candidate_exam.score,
        "status": candidate_exam.status
    }


@app.post("/exam/{exam_id}/resume", response_model=schemas.ExamOut)
def resume_exam(
    exam_id: str,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(auth.get_db)
):
    candidate_exam = db.query(models.CandidateExam).filter(
        models.CandidateExam.id == exam_id,
        models.CandidateExam.user_id == current_user.id
    ).first()

    if not candidate_exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    if candidate_exam.time_elapsed >= candidate_exam.time_allowed_secs and candidate_exam.status == "in_progress":
        candidate_exam.status = "timed_out"
        exam.compute_score(db, candidate_exam)
        db.add(candidate_exam)
        db.commit()
        db.refresh(candidate_exam)

    questions = []
    for qid in candidate_exam.question_ids or []:
        question = db.query(models.Question).filter(models.Question.id == qid).first()
        if question:
            questions.append({
                "id": question.id,
                "text": question.text,
                "choices": question.choices,
                "difficulty": question.difficulty
            })

    return {
        "id": candidate_exam.id,
        "questions": questions,
        "time_allowed_secs": candidate_exam.time_allowed_secs,
        "time_elapsed": candidate_exam.time_elapsed,
        "status": candidate_exam.status
    }


@app.get("/exam/{exam_id}/result")
def get_result(
    exam_id: str,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(auth.get_db)
):
    candidate_exam = db.query(models.CandidateExam).filter(
        models.CandidateExam.id == exam_id,
        models.CandidateExam.user_id == current_user.id
    ).first()

    if not candidate_exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    answers = candidate_exam.answers or {}
    details = []

    for qid in candidate_exam.question_ids or []:
        question = db.query(models.Question).filter(models.Question.id == qid).first()
        if question:
            question_id = str(qid)
            selected = answers.get(question_id)
            is_correct = (selected == question.answer_index) if selected is not None else False

            details.append({
                "question_id": question_id,
                "question": question.text,
                "choices": question.choices,
                "selected": selected,
                "correct_index": question.answer_index,
                "is_correct": is_correct
            })
    
    return {"score": candidate_exam.score, "status": candidate_exam.status, "details": details}


