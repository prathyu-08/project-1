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
    import json
    import re

    if not raw_text:
        return []

    text = raw_text.strip()

    # 1️⃣ Remove markdown code fences
    text = re.sub(r"```json|```", "", text, flags=re.IGNORECASE).strip()

    # 2️⃣ Extract JSON array (best effort)
    start = text.find("[")
    end = text.rfind("]")

    if start == -1:
        return []

    if end == -1:
        # JSON cut off → close array manually
        text = text[start:] + "]"
    else:
        text = text[start:end + 1]

    # 3️⃣ Remove trailing commas before ] or }
    text = re.sub(r",\s*]", "]", text)
    text = re.sub(r",\s*}", "}", text)

    # 4️⃣ Parse JSON safely
    try:
        data = json.loads(text)
    except Exception as e:
        print("❌ FINAL JSON PARSE FAILED")
        print(text)
        return []

    questions = []

    for item in data:
        question = (
            item.get("Question")
            or item.get("question")
        )

        options = (
            item.get("Options")
            or item.get("options")
        )

        answer_text = (
            item.get("Answer")
            or item.get("answer")
        )

        if not question or not options or not answer_text:
            continue

        # Convert answer → index
        answer_index = 0
        for i, opt in enumerate(options):
            if str(opt).strip() == str(answer_text).strip():
                answer_index = i
                break

        questions.append({
            "question": question,
            "options": options,
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

    try:
        response = requests.get(
            LLM_API_URL,
            headers={"Content-Type": "application/json"},
            data=json.dumps({
                "questionscount": exam_data.question_count,
                "language": exam_data.language
            }),
            timeout=30
        )

        if response.status_code != 200:
            raise HTTPException(status_code=500, detail=response.text)

        llm_questions = parse_llm_response(response.text)

        if not llm_questions:
            raise HTTPException(status_code=500, detail="Failed to parse LLM questions")

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

    DEFAULT_PASSWORD = "welcome@123"   # 🔐 change if needed

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





#/exam/{exam_id}/start endpoint in main.py:

@app.post("/exam/{exam_id}/start", response_model=schemas.CandidateExamCreateOut)
def start_exam(
    exam_id: str,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(auth.get_db)
):
    # 🔍 Check if user already has an active exam (ANY exam)
    # REMOVED ended_at.is_(None) - status is enough!
    existing_exam = db.query(models.CandidateExam).filter(
        models.CandidateExam.user_id == current_user.id,
        models.CandidateExam.status == "in_progress"
    ).first()

    if existing_exam:
        # If it's the same exam, return it for resume
        if existing_exam.exam_id == exam_id:
            print(f"✅ User {current_user.email} resuming existing exam {existing_exam.id}")
            return existing_exam
        else:
            # Different exam in progress - prevent starting new one
            raise HTTPException(
                status_code=400, 
                detail="You already have an exam in progress. Please complete or abandon it first."
            )

    # 🔍 Validate assignment
    assignment = db.query(models.ExamAssignment).filter(
        models.ExamAssignment.exam_id == exam_id,
        models.ExamAssignment.candidate_email == current_user.email
    ).first()

    if not assignment:
        raise HTTPException(status_code=403, detail="Not assigned to this exam")

    # 🔍 Validate exam exists and is active
    exam_obj = db.query(models.Exam).filter(
        models.Exam.id == exam_id,
        models.Exam.is_active == True
    ).first()

    if not exam_obj:
        raise HTTPException(status_code=404, detail="Exam not found or inactive")

    # 🔍 Load questions
    questions = db.query(models.Question).filter(
        models.Question.exam_id == exam_id
    ).all()

    if not questions:
        raise HTTPException(status_code=500, detail="No questions found for this exam")

    # 🆕 Create new candidate exam
    candidate_exam = models.CandidateExam(
        user_id=current_user.id,
        exam_id=exam_id,
        question_ids=[q.id for q in questions],
        answers={},
        time_allowed_secs=exam_obj.time_allowed_secs,
        time_elapsed=0,
        status="in_progress",
        started_at=datetime.utcnow(),
        ended_at=None  # ✅ EXPLICITLY set to None
    )

    db.add(candidate_exam)
    assignment.status = "started"
    db.commit()
    db.refresh(candidate_exam)

    print(f"\n{'='*60}")
    print(f"✅ NEW EXAM STARTED")
    print(f"   User: {current_user.email}")
    print(f"   Exam ID: {candidate_exam.id}")
    print(f"   Questions: {len(questions)}")
    print(f"{'='*60}\n")

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


# Replace the /exam/resume endpoint in main.py with this:

@app.get("/exam/resume")
def resume_exam(
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(auth.get_db)
):
    import sys
    
    # ✅ IMMEDIATE DEBUG - Print user info
    print("=" * 80, flush=True)
    print(f"RESUME ENDPOINT CALLED", flush=True)
    print(f"Current user email: {current_user.email}", flush=True)
    print(f"Current user ID: {current_user.id}", flush=True)
    print("=" * 80, flush=True)
    sys.stdout.flush()
    
    # Query with explicit logging
    candidate_exam = db.query(models.CandidateExam).filter(
        models.CandidateExam.user_id == current_user.id,
        models.CandidateExam.status == "in_progress"
    ).order_by(models.CandidateExam.started_at.desc()).first()
    
    print(f"Query result: {candidate_exam}", flush=True)
    print(f"Found exam: {'YES' if candidate_exam else 'NO'}", flush=True)
    sys.stdout.flush()

    if not candidate_exam:
        # Debug all exams
        all_exams = db.query(models.CandidateExam).filter(
            models.CandidateExam.user_id == current_user.id
        ).all()
        
        print(f"Total exams for user: {len(all_exams)}", flush=True)
        for exam in all_exams:
            print(f"  Exam: {exam.id}, Status: {exam.status}, User: {exam.user_id}", flush=True)
        sys.stdout.flush()
        
        raise HTTPException(
            status_code=404, 
            detail=f"No exam found for user {current_user.id}"
        )

    # Load questions
    questions = []
    for qid in candidate_exam.question_ids or []:
        q = db.query(models.Question).filter(models.Question.id == qid).first()
        if q:
            questions.append({
                "id": q.id,
                "text": q.text,
                "choices": q.choices
            })

    print(f"✅ RESUME SUCCESS - Exam: {candidate_exam.id}", flush=True)
    sys.stdout.flush()

    return {
        "candidate_exam_id": candidate_exam.id,
        "questions": questions,
        "answers": candidate_exam.answers or {},
        "time_allowed_secs": candidate_exam.time_allowed_secs,
        "time_elapsed": candidate_exam.time_elapsed,
        "status": "in_progress"
    }

@app.get("/test-debug")
def test_debug():
    import sys
    print("=" * 60, flush=True)
    print("TEST ENDPOINT HIT", flush=True)
    print("=" * 60, flush=True)
    sys.stdout.flush()
    return {"msg": "test successful", "timestamp": datetime.utcnow()}


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
