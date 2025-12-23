from fastapi import FastAPI, Depends, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy import and_
import requests
import traceback
import json
import re
from datetime import datetime
from .email_utils import send_exam_assignment_email
import os
from dotenv import load_dotenv
from .db import Base, engine
from . import models, schemas, auth, exam,email_utils

# APP SETUP


app = FastAPI(title="NMK Certification Portal")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Base.metadata.create_all(bind=engine)

LLM_API_URL = os.getenv("LLM_API_URL")

# LLM RESPONSE PARSER


def parse_llm_response(raw_text: str):
    import json, re

    if not raw_text:
        return []

    # Remove markdown fences
    text = re.sub(r"```json|```", "", raw_text, flags=re.IGNORECASE).strip()

    # Find array start
    start = text.find("[")
    if start == -1:
        return []

    text = text[start:]  # do NOT force closing ]

    questions = []

    # 🔥 Extract COMPLETE JSON OBJECTS ONLY
    blocks = re.findall(r"\{[^{}]*\}", text, re.DOTALL)

    for block in blocks:
        try:
            item = json.loads(block)
        except Exception:
            continue

        q = item.get("Question")
        opts = item.get("Options")
        ans = item.get("Answer")

        if not q or not opts or not ans:
            continue

        answer_index = None
        for i, opt in enumerate(opts):
            if str(opt).strip() == str(ans).strip():
                answer_index = i
                break

        if answer_index is None:
            continue

        questions.append({
            "question": q,
            "options": opts,
            "answer_index": answer_index
        })

    return questions



# AUTH 


@app.post("/register")
def register(payload: schemas.RegisterIn, db: Session = Depends(auth.get_db)):
    if auth.get_user_by_email(db, payload.email):
        raise HTTPException(status_code=400, detail="Email already registered")

    user = models.User(
        email=payload.email,
        name=payload.name,
        hashed_password=auth.get_password_hash(payload.password),
        is_admin=False
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"msg": "user created", "email": user.email}


@app.post("/login", response_model=schemas.Token)
def login(payload: dict = Body(...), db: Session = Depends(auth.get_db)):
    user = auth.authenticate_user(db, payload.get("email"), payload.get("password"))
    if not user:
        raise HTTPException(status_code=400, detail="Incorrect email or password")

    token = auth.create_access_token({"sub": user.email})
    return {"access_token": token, "token_type": "bearer"}


@app.get("/me")
def me(current_user: models.User = Depends(auth.get_current_user)):
    return {
        "email": current_user.email,
        "name": current_user.name,
        "is_admin": current_user.is_admin
    }


# ADMIN


@app.post("/admin/exams", response_model=schemas.ExamOut)
def create_exam(
    exam_data: schemas.ExamCreateIn,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(auth.get_db)
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")

    TOTAL_QUESTIONS = exam_data.question_count
    BATCH_SIZE = 10
    MAX_ATTEMPTS = 30

    all_questions = []
    attempts = 0

    try:
        # 🔁 Generate questions in batches
        while len(all_questions) < TOTAL_QUESTIONS and attempts < MAX_ATTEMPTS:
            attempts += 1

            batch_count = min(BATCH_SIZE, TOTAL_QUESTIONS - len(all_questions))

            response = requests.get(
                LLM_API_URL,
                json={
                    "questionscount": batch_count,
                    "language": exam_data.language
                },
                timeout=90
            )

            if response.status_code != 200:
                continue

            batch_questions = parse_llm_response(response.text)

            if not batch_questions:
                continue

            all_questions.extend(batch_questions)

        # ✅ FINAL CHECK (AFTER LOOP)
        if len(all_questions) < TOTAL_QUESTIONS:
            raise HTTPException(
                status_code=500,
                detail=f"Could only generate {len(all_questions)} questions after retries"
            )

        llm_questions = all_questions[:TOTAL_QUESTIONS]

        # 🧾 Create Exam ONCE
        new_exam = models.Exam(
            title=exam_data.title,
            language=exam_data.language,
            question_count=len(llm_questions),
            time_allowed_secs=exam_data.time_allowed_secs,
            created_by=current_user.id,
            is_active=True
        )
        db.add(new_exam)
        db.flush()

        # 🧾 Insert Questions
        for q in llm_questions:
            db.add(models.Question(
                text=q["question"],
                choices=q["options"],
                answer_index=q["answer_index"],
                exam_id=new_exam.id
            ))

        db.commit()
        db.refresh(new_exam)
        return new_exam

    except Exception as e:
        db.rollback()
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/admin/exams/{exam_id}/assign")
def assign_exam(
    exam_id: str,
    payload: schemas.ExamAssignIn,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(auth.get_db)
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")

    if not payload.candidate_emails:
        raise HTTPException(
            status_code=400,
            detail="candidate_emails list cannot be empty"
        )

    exam_obj = db.query(models.Exam).filter(models.Exam.id == exam_id).first()
    if not exam_obj:
        raise HTTPException(status_code=404, detail="Exam not found")

    DEFAULT_PASSWORD = os.getenv("DEFAULT_PASSWORD")


    assigned_count = 0
    emailed_count = 0
    created_users = 0

    for email in payload.candidate_emails:
        email = email.strip().lower()

        # 🔍 Check if user exists
        candidate = auth.get_user_by_email(db, email)

        # 🆕 CREATE USER IF NOT EXISTS
        if not candidate:
            username = email.split("@")[0]

            hashed_password = auth.get_password_hash(DEFAULT_PASSWORD)

            candidate = models.User(
                email=email,
                name=username,
                hashed_password=hashed_password,
                is_admin=False
            )

            db.add(candidate)
            db.flush()  # get user.id
            created_users += 1

            print(f"👤 Auto-created user: {email}")

        # 🔍 Check assignment
        existing = db.query(models.ExamAssignment).filter(
            and_(
                models.ExamAssignment.exam_id == exam_id,
                models.ExamAssignment.candidate_email == email
            )
        ).first()

        if not existing:
            assignment = models.ExamAssignment(
                exam_id=exam_id,
                candidate_email=email,
                assigned_by=current_user.id,
                status="assigned"
            )
            db.add(assignment)
            assigned_count += 1

        # 📧 SEND EMAIL (ALWAYS)
        try:
            print(f"📧 Sending email to {email}")
            send_exam_assignment_email(
                to_email=email,
                exam_title=exam_obj.title
            )
            emailed_count += 1
        except Exception as e:
            print(f"❌ Email failed for {email}: {e}")

    db.commit()

    return {
        "new_users_created": created_users,
        "new_assignments": assigned_count,
        "emails_sent": emailed_count
    }





@app.get("/admin/candidates/results")
def get_all_candidate_results(
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(auth.get_db)
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")

    # Get all candidate exams with user and exam details
    results = []
    candidate_exams = db.query(models.CandidateExam).all()
    
    for ce in candidate_exams:
        user = db.query(models.User).filter(models.User.id == ce.user_id).first()
        exam = db.query(models.Exam).filter(models.Exam.id == ce.exam_id).first()
        
        if user and exam:
            results.append({
                "candidate_exam_id": ce.id,
                "candidate_email": user.email,
                "candidate_name": user.name,
                "exam_title": exam.title,
                "exam_language": exam.language,
                "status": ce.status,
                "score": ce.score if ce.status == "completed" else None,
                "started_at": ce.started_at,
                "ended_at": ce.ended_at,
                "time_elapsed": ce.time_elapsed
            })
    
    return results


@app.get("/admin/exams/{exam_id}/assignments")
def get_exam_assignments(
    exam_id: str,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(auth.get_db)
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")

    assignments = db.query(models.ExamAssignment).filter(
        models.ExamAssignment.exam_id == exam_id
    ).all()
    
    result = []
    for assignment in assignments:
        # Check if candidate has started/completed the exam
        candidate_exam = db.query(models.CandidateExam).filter(
            and_(
                models.CandidateExam.exam_id == exam_id,
                models.CandidateExam.user_id.in_(
                    db.query(models.User.id).filter(
                        models.User.email == assignment.candidate_email
                    )
                )
            )
        ).first()
        
        status = "assigned"
        score = None
        if candidate_exam:
            status = candidate_exam.status
            score = candidate_exam.score if candidate_exam.status == "completed" else None
        
        result.append({
            "candidate_email": assignment.candidate_email,
            "assigned_at": assignment.assigned_at,
            "status": status,
            "score": score
        })
    
    return result


# ADMIN CONTROLS


@app.get("/admin/exams")
def list_all_exams(current_user: models.User = Depends(auth.get_current_user), db: Session = Depends(auth.get_db)):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    return db.query(models.Exam).order_by(models.Exam.created_at.desc()).all()


@app.patch("/admin/exams/{exam_id}/toggle")
def toggle_exam_status(
    exam_id: str,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(auth.get_db)
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")

    exam_obj = db.query(models.Exam).filter(models.Exam.id == exam_id).first()
    if not exam_obj:
        raise HTTPException(status_code=404, detail="Exam not found")

    exam_obj.is_active = not exam_obj.is_active
    db.commit()
    return {"msg": "status updated", "is_active": exam_obj.is_active}


# USER: EXAMS


@app.get("/exams")
def list_available_exams(current_user: models.User = Depends(auth.get_current_user), db: Session = Depends(auth.get_db)):
    # Get exams assigned to this candidate
    assignments = db.query(models.ExamAssignment).filter(
        models.ExamAssignment.candidate_email == current_user.email
    ).all()
    
    assigned_exam_ids = [a.exam_id for a in assignments]
    
    # Return only active exams that are assigned to this user
    exams = db.query(models.Exam).filter(
        and_(
            models.Exam.is_active == True,
            models.Exam.id.in_(assigned_exam_ids)
        )
    ).all()
    
    return exams




@app.post("/exam/{exam_id}/start", response_model=schemas.CandidateExamCreateOut)
def start_exam(exam_id: str, current_user: models.User = Depends(auth.get_current_user), db: Session = Depends(auth.get_db)):
    # Check if exam is assigned to this candidate
    assignment = db.query(models.ExamAssignment).filter(
        and_(
            models.ExamAssignment.exam_id == exam_id,
            models.ExamAssignment.candidate_email == current_user.email
        )
    ).first()
    
    if not assignment:
        raise HTTPException(status_code=403, detail="This exam is not assigned to you")
    
    existing = db.query(models.CandidateExam).filter(
        models.CandidateExam.user_id == current_user.id,
        models.CandidateExam.status == "in_progress"
    ).first()

    if existing:
        return existing
    
    exam_obj = db.query(models.Exam).filter(models.Exam.id == exam_id, models.Exam.is_active == True).first()
    if not exam_obj:
        raise HTTPException(status_code=404, detail="Exam not found")

    questions = db.query(models.Question).filter(models.Question.exam_id == exam_id).all()
    if not questions:
        raise HTTPException(status_code=400, detail="No questions found")

    candidate_exam = models.CandidateExam(
        user_id=current_user.id,
        exam_id=exam_id,
        question_ids=[q.id for q in questions],
        answers={},
        time_allowed_secs=exam_obj.time_allowed_secs,
        time_elapsed=0,
        status="in_progress"
    )
    db.add(candidate_exam)
    
    # Update assignment status
    assignment.status = "started"
    
    db.commit()
    db.refresh(candidate_exam)
    return candidate_exam

@app.get("/exam/{candidate_exam_id}")
def get_exam(
    candidate_exam_id: str,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(auth.get_db)
):
    candidate_exam = db.query(models.CandidateExam).filter(
        models.CandidateExam.id == candidate_exam_id,
        models.CandidateExam.user_id == current_user.id
    ).first()

    if not candidate_exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    questions = []
    for qid in candidate_exam.question_ids or []:
        question = db.query(models.Question).filter(
            models.Question.id == qid
        ).first()

        if question:
            questions.append({
                "id": question.id,
                "text": question.text,
                "choices": question.choices
            })

    return {
        "id": candidate_exam.id,
        "questions": questions,
        "time_allowed_secs": candidate_exam.time_allowed_secs,
        "time_elapsed": candidate_exam.time_elapsed,
        "status": candidate_exam.status
    }

# SAVE ANSWER

@app.post("/exam/{candidate_exam_id}/save-answer")
def save_answer(
    candidate_exam_id: str,
    payload: schemas.AnswerIn,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(auth.get_db)
):
    candidate_exam = db.query(models.CandidateExam).filter(
        models.CandidateExam.id == candidate_exam_id,
        models.CandidateExam.user_id == current_user.id
    ).first()

    if not candidate_exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    answers = dict(candidate_exam.answers or {})
    answers[str(payload.question_id)] = payload.selected_index

    candidate_exam.answers = answers
    candidate_exam.time_elapsed = payload.time_elapsed
    flag_modified(candidate_exam, "answers")

    db.commit()
    db.refresh(candidate_exam)
    return {"msg": "answer_saved"}


@app.get("/exam/resume")
def resume_exam(
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(auth.get_db)
):
    exam = db.query(models.CandidateExam).filter(
        models.CandidateExam.user_id == current_user.id,
        models.CandidateExam.status == "in_progress"
    ).first()

    if not exam:
        raise HTTPException(status_code=404, detail="No active exam")

    questions = []
    for qid in exam.question_ids or []:
        q = db.query(models.Question).filter(models.Question.id == qid).first()
        if q:
            questions.append({
                "id": q.id,
                "text": q.text,
                "choices": q.choices
            })

    return {
        "candidate_exam_id": exam.id,
        "exam_id": exam.exam_id,
        "questions": questions,
        "answers": exam.answers or {},
        "time_allowed_secs": exam.time_allowed_secs,
        "time_elapsed": exam.time_elapsed,
        "status": exam.status
    }




@app.post("/exam/{candidate_exam_id}/submit")
def submit_exam(
    candidate_exam_id: str,
    final_time_elapsed: int = Body(..., embed=True),
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(auth.get_db)
):
    candidate_exam = db.query(models.CandidateExam).filter(
        models.CandidateExam.id == candidate_exam_id,
        models.CandidateExam.user_id == current_user.id
    ).first()

    if not candidate_exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    candidate_exam.time_elapsed = final_time_elapsed
    candidate_exam.status = "completed"
    candidate_exam.ended_at = datetime.utcnow()

    exam.compute_score(db, candidate_exam)

    db.commit()
    db.refresh(candidate_exam)

    return {
        "msg": "exam_submitted",
        "score": candidate_exam.score,
        "status": candidate_exam.status
    }

# RESULT

@app.get("/exam/{candidate_exam_id}/result")
def get_result(
    candidate_exam_id: str,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(auth.get_db)
):
    candidate_exam = db.query(models.CandidateExam).filter(
        models.CandidateExam.id == candidate_exam_id,
        models.CandidateExam.user_id == current_user.id
    ).first()

    if not candidate_exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    details = []
    answers = candidate_exam.answers or {}

    for qid in candidate_exam.question_ids or []:
        question = db.query(models.Question).filter(models.Question.id == qid).first()
        if question:
            selected = answers.get(str(qid))
            details.append({
                "question": question.text,
                "choices": question.choices,
                "selected": selected,
                "correct_index": question.answer_index,
                "is_correct": selected == question.answer_index
            })

    return {
        "score": candidate_exam.score,
        "status": candidate_exam.status,
        "details": details
    }
