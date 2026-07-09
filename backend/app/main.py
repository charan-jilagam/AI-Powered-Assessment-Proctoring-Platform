from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import json
from app import audit
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from fastapi import Request

from app.database import engine, Base, get_db
from app import models, schemas, auth

# Create all tables on startup (safe to run even if they already exist)
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Proctoring System API",
    description="Backend API for the AI Proctoring System",
    version="1.0.0",
)

# Rate limiter — keyed by client IP
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many attempts. Please wait a minute and try again."},
    )
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def home():
    return {
        "message": "Proctoring System is running!",
        "status": "online",
        "version": "1.0.0"
    }

@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "database": "connected"
    }

# ----------- SIGNUP -----------
@app.post("/auth/signup", response_model=schemas.UserResponse)
@limiter.limit("5/minute")
def signup(request: Request, user: schemas.UserCreate, db: Session = Depends(get_db)):
    # Check if email already exists
    existing_user = db.query(models.User).filter(models.User.email == user.email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    # Hash the password before storing
    hashed_pw = auth.hash_password(user.password)

    # Create new user record
    new_user = models.User(
        full_name=user.full_name,
        email=user.email,
        hashed_password=hashed_pw,
        role="student"
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    audit.log_event("SIGNUP", new_user.email, f"role={new_user.role}")

    return new_user


# ----------- LOGIN -----------
@app.post("/auth/login", response_model=schemas.Token)
@limiter.limit("5/minute")
def login(request: Request, credentials: schemas.UserLogin, db: Session = Depends(get_db)):
    # Find user by email
    user = db.query(models.User).filter(models.User.email == credentials.email).first()

    if not user or not auth.verify_password(credentials.password, user.hashed_password):
        audit.log_event("LOGIN_FAILED", credentials.email, "invalid credentials")
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    if not user or not auth.verify_password(credentials.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    # Create JWT token
    access_token = auth.create_access_token(data={"sub": str(user.id), "role": user.role})
    audit.log_event("LOGIN_SUCCESS", user.email, f"role={user.role}")
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user
    }
# ----------- PROTECTED ROUTE (requires login) -----------
@app.get("/auth/me", response_model=schemas.UserResponse)
def get_my_profile(current_user: models.User = Depends(auth.get_current_user)):
    return current_user

from typing import List

# ----------- CREATE EXAM (Admin only) -----------
@app.post("/exams", response_model=schemas.ExamResponse)
def create_exam(
    exam: schemas.ExamCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    # Only admins can create exams
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can create exams")

    # Create the exam record
    new_exam = models.Exam(
        title=exam.title,
        description=exam.description,
        duration_minutes=exam.duration_minutes,
        start_time=exam.start_time,
        end_time=exam.end_time,
        created_by=current_user.id
    )
    db.add(new_exam)
    db.commit()
    db.refresh(new_exam)

    # Create each question, linked to this exam
    for q in exam.questions:
        new_question = models.Question(
            exam_id=new_exam.id,
            question_text=q.question_text,
            option_a=q.option_a,
            option_b=q.option_b,
            option_c=q.option_c,
            option_d=q.option_d,
            correct_answer=q.correct_answer
        )
        db.add(new_question)

    db.commit()
    db.refresh(new_exam)

    return new_exam

# ----------- LIST ALL EXAMS (Admin sees all, with answers) -----------
@app.get("/exams", response_model=List[schemas.ExamResponse])
def list_exams(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can view all exams")

    exams = db.query(models.Exam).all()
    return exams

# ----------- LIST EXAMS (Student view - basic info only, no answers) -----------
@app.get("/exams/available")
def list_available_exams(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    exams = db.query(models.Exam).all()

    result = []
    for exam in exams:
        total_in_pool = len(exam.questions)
        # Students always get 10 (or the whole pool if it's smaller)
        questions_shown = min(10, total_in_pool)
        result.append({
            "id": exam.id,
            "title": exam.title,
            "description": exam.description,
            "duration_minutes": exam.duration_minutes,
            "start_time": exam.start_time,
            "end_time": exam.end_time,
            "questions": [{}] * questions_shown,  # length = 10 so the card shows "10 questions"
        })
    return result

# ----------- GET SINGLE EXAM (Student view - no answers) -----------
import random  # add this at the top of main.py with the other imports if not already there

@app.get("/exams/{exam_id}")
def get_exam(
    exam_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    exam = db.query(models.Exam).filter(models.Exam.id == exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    # Block if already submitted
    existing_submission = db.query(models.Submission).filter(
        models.Submission.exam_id == exam_id,
        models.Submission.student_id == current_user.id
    ).first()
    if existing_submission:
        raise HTTPException(status_code=400, detail="You have already submitted this exam")

    # Look for an existing session (resume) or create a new one (first open)
    session = db.query(models.ExamSession).filter(
        models.ExamSession.exam_id == exam_id,
        models.ExamSession.student_id == current_user.id,
    ).first()

    if session and session.status == "terminated":
        raise HTTPException(status_code=403, detail="Your exam was terminated due to violations")

    if session:
        # RESUME: return the same locked questions
        questions = json.loads(session.question_data)
    else:
        # NEW SESSION: pick random 10, shuffle options, lock them in
        all_questions = db.query(models.Question).filter(
            models.Question.exam_id == exam_id
        ).all()
        if not all_questions:
            raise HTTPException(status_code=400, detail="This exam has no questions")

        num_to_pick = min(10, len(all_questions))
        selected = random.sample(all_questions, num_to_pick)

        questions = []
        for q in selected:
            options = [q.option_a, q.option_b, q.option_c, q.option_d]
            random.shuffle(options)
            questions.append({
                "id": q.id,
                "question_text": q.question_text,
                "option_a": options[0],
                "option_b": options[1],
                "option_c": options[2],
                "option_d": options[3],
            })

        session = models.ExamSession(
            exam_id=exam_id,
            student_id=current_user.id,
            question_data=json.dumps(questions),
            status="in_progress",
        )
        db.add(session)
        db.commit()
        db.refresh(session)

    # Compute remaining time from the true server-side start
    elapsed_seconds = (datetime.now(session.started_at.tzinfo) - session.started_at).total_seconds()
    remaining_seconds = max(0, int(exam.duration_minutes * 60 - elapsed_seconds))

    return {
        "id": exam.id,
        "title": exam.title,
        "description": exam.description,
        "duration_minutes": exam.duration_minutes,
        "start_time": exam.start_time,
        "end_time": exam.end_time,
        "questions": questions,
        "remaining_seconds": remaining_seconds,
        "session_status": session.status,
    }
# ----------- SUBMIT EXAM (Student) -----------
@app.post("/exams/{exam_id}/submit", response_model=schemas.SubmissionResponse)
def submit_exam(
    exam_id: int,
    submission: schemas.SubmissionCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    exam = db.query(models.Exam).filter(models.Exam.id == exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    existing = db.query(models.Submission).filter(
        models.Submission.exam_id == exam_id,
        models.Submission.student_id == current_user.id
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="You have already submitted this exam")

    # Load the student's locked session to know which questions were actually assigned
    session = db.query(models.ExamSession).filter(
        models.ExamSession.exam_id == exam_id,
        models.ExamSession.student_id == current_user.id,
    ).first()
    if not session:
        raise HTTPException(status_code=400, detail="No active exam session found")

    # The set of question IDs this student was legitimately shown
    locked_questions = json.loads(session.question_data)
    valid_question_ids = {q["id"] for q in locked_questions}

    total_questions = len(locked_questions)

    # Score ONLY questions that belong to this session; ignore any others
    score = 0
    for question_id, submitted_text in submission.answers.items():
        qid = int(question_id)
        if qid not in valid_question_ids:
            continue  # reject answers to questions not in this session

        question = db.query(models.Question).filter(
            models.Question.id == qid
        ).first()
        if not question:
            continue

        correct_letter = question.correct_answer.upper()
        correct_text = {
            "A": question.option_a,
            "B": question.option_b,
            "C": question.option_c,
            "D": question.option_d,
        }.get(correct_letter)

        print(f"QID {qid}: submitted='{submitted_text}' | correct='{correct_text}' | match={submitted_text.strip() == correct_text.strip() if (submitted_text and correct_text) else False}")
        if submitted_text and correct_text and submitted_text.strip() == correct_text.strip():
            score += 1
            
    new_submission = models.Submission(
        exam_id=exam_id,
        student_id=current_user.id,
        answers=json.dumps(submission.answers),
        score=score,
        total_questions=total_questions
    )
    db.add(new_submission)
    db.commit()
    db.refresh(new_submission)
    # Mark the exam session as submitted
    session = db.query(models.ExamSession).filter(
        models.ExamSession.exam_id == exam_id,
        models.ExamSession.student_id == current_user.id,
    ).first()
    if session:
        session.status = "submitted"

    db.add(new_submission)
    db.commit()
    db.refresh(new_submission)
    
    audit.log_event("EXAM_SUBMITTED", current_user.email, f"exam_id={exam_id} score={score}/{total_questions}")

    return new_submission

    return new_submission

# ----------- LOG VIOLATION (Student, during exam) -----------
@app.post("/exams/{exam_id}/violations", response_model=schemas.ViolationResponse)
def log_violation(
    exam_id: int,
    violation: schemas.ViolationCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    new_violation = models.Violation(
        exam_id=exam_id,
        student_id=current_user.id,
        violation_type=violation.violation_type,
        details=violation.details
    )
    db.add(new_violation)
    db.commit()
    db.refresh(new_violation)

    return new_violation

# ----------- GET ALL VIOLATIONS FOR AN EXAM (Admin only) -----------
@app.get("/exams/{exam_id}/violations", response_model=List[schemas.ViolationWithStudent])
def get_exam_violations(
    exam_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can view violations")

    violations = (
        db.query(models.Violation)
        .filter(models.Violation.exam_id == exam_id)
        .order_by(models.Violation.created_at.desc())
        .all()
    )

    return violations

from app.proctoring import analyze_frame

# ----------- AI FRAME ANALYSIS -----------
@app.post("/proctor/analyze")
async def analyze_proctor_frame(
    request: dict,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db)
):
    exam_id = request.get("exam_id")
    image_data = request.get("image")

    if not image_data:
        # Don't error the exam over a missing frame — just skip
        return {"warnings": [], "skipped": True}

    # Run AI analysis defensively — a bad frame must never crash the exam
    try:
        results = analyze_frame(image_data)
    except Exception as e:
        print(f"Proctor analysis error (skipped frame): {e}")
        return {"warnings": [], "skipped": True}

    # Log any AI-detected violations, but never let a DB hiccup break the response
    try:
        # Severe AI signals = strong cheating indicators
        severe_keywords = ["No face", "Multiple faces", "phone", "book", "laptop", "tv", "remote", "keyboard", "mouse", "Mobile"]

        for warning in results.get("warnings", []):
            # Decide severity: severe keywords => level 2, else level 1
            is_severe = any(kw.lower() in warning.lower() for kw in severe_keywords)
            level = 2 if is_severe else 1

            violation = models.Violation(
                exam_id=exam_id,
                student_id=current_user.id,
                violation_type=f"AI: {warning}",
                details=f"Level {level} - Detected by AI proctoring engine"
            )
            db.add(violation)
        if results.get("warnings"):
            db.commit()
    except Exception as e:
        db.rollback()
        print(f"Violation logging error (non-fatal): {e}")

    return results
# ----------- GET MY RESULTS (Student) -----------
@app.get("/my-results")
def get_my_results(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    submissions = (
        db.query(models.Submission)
        .filter(models.Submission.student_id == current_user.id)
        .order_by(models.Submission.submitted_at.desc())
        .all()
    )

    results = []
    for sub in submissions:
        exam = db.query(models.Exam).filter(models.Exam.id == sub.exam_id).first()
        results.append({
            "id": sub.id,
            "exam_title": exam.title if exam else "Unknown Exam",
            "score": sub.score,
            "total_questions": sub.total_questions,
            "submitted_at": sub.submitted_at,
        })
    return results

# ----------- CREATE ADMIN (Admin only) -----------
@app.post("/admin/create-admin", response_model=schemas.UserResponse)
def create_admin(
    new_admin: schemas.UserCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can create admin accounts")

    existing = db.query(models.User).filter(models.User.email == new_admin.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user = models.User(
        full_name=new_admin.full_name,
        email=new_admin.email,
        hashed_password=auth.hash_password(new_admin.password),
        role="admin",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

# ----------- TERMINATE EXAM SESSION (called on 3-strike) -----------
@app.post("/exams/{exam_id}/terminate")
def terminate_exam_session(
    exam_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    session = db.query(models.ExamSession).filter(
        models.ExamSession.exam_id == exam_id,
        models.ExamSession.student_id == current_user.id,
    ).first()
    if session:
        session.status = "terminated"
        db.commit()
        
        audit.log_event("EXAM_TERMINATED", current_user.email, f"exam_id={exam_id}")
    return {"status": "terminated"}

# ----------- GET ALL RESULTS FOR AN EXAM (Admin only) -----------
@app.get("/exams/{exam_id}/results")
def get_exam_results(
    exam_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can view results")

    exam = db.query(models.Exam).filter(models.Exam.id == exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    submissions = (
        db.query(models.Submission)
        .filter(models.Submission.exam_id == exam_id)
        .order_by(models.Submission.score.desc())
        .all()
    )

    results = []
    for sub in submissions:
        student = db.query(models.User).filter(models.User.id == sub.student_id).first()

        # Count this student's violations for this exam
        violation_count = db.query(models.Violation).filter(
            models.Violation.exam_id == exam_id,
            models.Violation.student_id == sub.student_id,
        ).count()

        # Check if their session was terminated
        session = db.query(models.ExamSession).filter(
            models.ExamSession.exam_id == exam_id,
            models.ExamSession.student_id == sub.student_id,
        ).first()
        was_terminated = session.status == "terminated" if session else False

        results.append({
            "student_id": sub.student_id,
            "student_name": student.full_name if student else "Unknown",
            "student_email": student.email if student else "Unknown",
            "score": sub.score,
            "total_questions": sub.total_questions,
            "percentage": round((sub.score / sub.total_questions) * 100) if sub.total_questions else 0,
            "violation_count": violation_count,
            "terminated": was_terminated,
            "submitted_at": sub.submitted_at,
        })

    return {
        "exam_title": exam.title,
        "total_candidates": len(results),
        "results": results,
    }
    
    # ----------- CREATE EXAM (Admin only) -----------
@app.post("/exams/create")
def create_exam(
    exam_data: schemas.ExamCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can create exams")

    if not exam_data.questions:
        raise HTTPException(status_code=400, detail="An exam must have at least one question")

    now = datetime.now()
    new_exam = models.Exam(
        title=exam_data.title,
        description=exam_data.description or "",
        duration_minutes=exam_data.duration_minutes,
        start_time=now,
        end_time=now + timedelta(days=365),
        created_by=current_user.id,
    )
    db.add(new_exam)
    db.commit()
    db.refresh(new_exam)

    for q in exam_data.questions:
        question = models.Question(
            exam_id=new_exam.id,
            question_text=q.question_text,
            option_a=q.option_a,
            option_b=q.option_b,
            option_c=q.option_c,
            option_d=q.option_d,
            correct_answer=q.correct_answer.upper(),
        )
        db.add(question)
    db.commit()

    audit.log_event("EXAM_CREATED", current_user.email, f"exam_id={new_exam.id} title='{new_exam.title}' questions={len(exam_data.questions)}")

    return {"id": new_exam.id, "title": new_exam.title, "question_count": len(exam_data.questions)}


# ----------- UPLOAD CSV TO CREATE EXAM (Admin only) -----------
@app.post("/exams/upload-csv")
async def upload_csv_exam(
    title: str = Form(...),
    description: str = Form(""),
    duration_minutes: int = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can create exams")

    import csv
    import io

    # Read and parse the uploaded CSV
    content = await file.read()
    text = content.decode("utf-8")
    reader = csv.DictReader(io.StringIO(text))

    now = datetime.now()
    new_exam = models.Exam(
        title=title,
        description=description,
        duration_minutes=duration_minutes,
        start_time=now,
        end_time=now + timedelta(days=365),
        created_by=current_user.id,
    )
    db.add(new_exam)
    db.commit()
    db.refresh(new_exam)

    count = 0
    for row in reader:
        try:
            question = models.Question(
                exam_id=new_exam.id,
                question_text=row["Question"].strip(),
                option_a=row["Option A"].strip(),
                option_b=row["Option B"].strip(),
                option_c=row["Option C"].strip(),
                option_d=row["Option D"].strip(),
                correct_answer=row["Answer"].strip().upper(),
            )
            db.add(question)
            count += 1
        except KeyError:
            db.rollback()
            db.delete(new_exam)
            db.commit()
            raise HTTPException(
                status_code=400,
                detail="CSV must have columns: Question, Option A, Option B, Option C, Option D, Answer"
            )

    db.commit()
    audit.log_event("EXAM_CREATED_CSV", current_user.email, f"exam_id={new_exam.id} questions={count}")

    return {"id": new_exam.id, "title": title, "question_count": count}

# ----------- DELETE EXAM (Admin only) -----------
@app.delete("/exams/{exam_id}")
def delete_exam(
    exam_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can delete exams")

    exam = db.query(models.Exam).filter(models.Exam.id == exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    exam_title = exam.title

    # Delete all related records first (order matters for foreign keys)
    db.query(models.Violation).filter(models.Violation.exam_id == exam_id).delete()
    db.query(models.Submission).filter(models.Submission.exam_id == exam_id).delete()
    db.query(models.ExamSession).filter(models.ExamSession.exam_id == exam_id).delete()
    db.query(models.Question).filter(models.Question.exam_id == exam_id).delete()
    db.delete(exam)
    db.commit()

    audit.log_event("EXAM_DELETED", current_user.email, f"exam_id={exam_id} title='{exam_title}'")

    return {"status": "deleted", "exam_id": exam_id}

# ----------- LIST ALL STUDENTS (Admin only) -----------
@app.get("/admin/students")
def list_students(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can view students")

    students = db.query(models.User).filter(models.User.role == "student").all()

    result = []
    for s in students:
        submission_count = db.query(models.Submission).filter(
            models.Submission.student_id == s.id
        ).count()
        result.append({
            "id": s.id,
            "full_name": s.full_name,
            "email": s.email,
            "submission_count": submission_count,
        })
    return result


# ----------- RESET A STUDENT'S ATTEMPT FOR AN EXAM (Admin only) -----------
@app.post("/admin/students/{student_id}/reset-attempt")
def reset_student_attempt(
    student_id: int,
    exam_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can reset attempts")

    db.query(models.Violation).filter(
        models.Violation.student_id == student_id,
        models.Violation.exam_id == exam_id,
    ).delete()
    db.query(models.Submission).filter(
        models.Submission.student_id == student_id,
        models.Submission.exam_id == exam_id,
    ).delete()
    db.query(models.ExamSession).filter(
        models.ExamSession.student_id == student_id,
        models.ExamSession.exam_id == exam_id,
    ).delete()
    db.commit()

    audit.log_event("ATTEMPT_RESET", current_user.email, f"student_id={student_id} exam_id={exam_id}")
    return {"status": "reset", "student_id": student_id, "exam_id": exam_id}


# ----------- DELETE A STUDENT'S RESULT FOR AN EXAM (Admin only) -----------
@app.delete("/admin/students/{student_id}/result")
def delete_student_result(
    student_id: int,
    exam_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can delete results")

    db.query(models.Submission).filter(
        models.Submission.student_id == student_id,
        models.Submission.exam_id == exam_id,
    ).delete()
    db.commit()

    audit.log_event("RESULT_DELETED", current_user.email, f"student_id={student_id} exam_id={exam_id}")
    return {"status": "result_deleted", "student_id": student_id, "exam_id": exam_id}


# ----------- DELETE A STUDENT ACCOUNT ENTIRELY (Admin only) -----------
@app.delete("/admin/students/{student_id}")
def delete_student(
    student_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can delete students")

    student = db.query(models.User).filter(
        models.User.id == student_id,
        models.User.role == "student",
    ).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    email = student.email

    # Remove all their data first (foreign-key order), then the account
    db.query(models.Violation).filter(models.Violation.student_id == student_id).delete()
    db.query(models.Submission).filter(models.Submission.student_id == student_id).delete()
    db.query(models.ExamSession).filter(models.ExamSession.student_id == student_id).delete()
    db.delete(student)
    db.commit()

    audit.log_event("STUDENT_DELETED", current_user.email, f"student_id={student_id} email='{email}'")
    return {"status": "student_deleted", "student_id": student_id}