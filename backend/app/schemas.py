from pydantic import BaseModel, EmailStr
from datetime import datetime
from typing import List, Dict

# What the frontend sends us when signing up
class UserCreate(BaseModel):
    full_name: str
    email: EmailStr
    password: str
    role: str = "student"  # defaults to student unless specified

# What the frontend sends us when logging in
class UserLogin(BaseModel):
    email: EmailStr
    password: str

# What we send back to the frontend after signup/login (never includes password!)
class UserResponse(BaseModel):
    id: int
    full_name: str
    email: str
    role: str

    class Config:
        from_attributes = True

# What we send back after successful login
class Token(BaseModel):
    access_token: str
    token_type: str
    user: UserResponse
# ----------- QUESTION SCHEMAS -----------

class QuestionCreate(BaseModel):
    question_text: str
    option_a: str
    option_b: str
    option_c: str
    option_d: str
    correct_answer: str  # "A", "B", "C", or "D"

class QuestionResponse(BaseModel):
    id: int
    question_text: str
    option_a: str
    option_b: str
    option_c: str
    option_d: str
    correct_answer: str

    class Config:
        from_attributes = True

# Version sent to students - hides the correct answer!
class QuestionForStudent(BaseModel):
    id: int
    question_text: str
    option_a: str
    option_b: str
    option_c: str
    option_d: str

    class Config:
        from_attributes = True

# ----------- EXAM SCHEMAS -----------

class ExamCreate(BaseModel):
    title: str
    description: str | None = None
    duration_minutes: int
    start_time: datetime | None = None
    end_time: datetime | None = None
    questions: List[QuestionCreate]
    
class ExamResponse(BaseModel):
    id: int
    title: str
    description: str | None
    duration_minutes: int
    start_time: datetime
    end_time: datetime
    questions: List[QuestionResponse]

    class Config:
        from_attributes = True

# Version sent to students when they start an exam - no correct answers visible
class ExamForStudent(BaseModel):
    id: int
    title: str
    description: str | None
    duration_minutes: int
    start_time: datetime
    end_time: datetime
    questions: List[QuestionForStudent]

    class Config:
        from_attributes = True

# ----------- SUBMISSION SCHEMAS -----------
# ----------- SUBMISSION SCHEMAS -----------

class SubmissionCreate(BaseModel):
    answers: Dict[int, str]  # {question_id: "A"} - student's selected answers

class SubmissionResponse(BaseModel):
    id: int
    exam_id: int
    score: int
    total_questions: int
    submitted_at: datetime

    class Config:
        from_attributes = True
        
        # ----------- VIOLATION SCHEMAS -----------

class ViolationCreate(BaseModel):
    violation_type: str
    details: str | None = None

class ViolationResponse(BaseModel):
    id: int
    violation_type: str
    details: str | None
    created_at: datetime

class Config:
    from_attributes = True
        
class ViolationWithStudent(BaseModel):
    id: int
    violation_type: str
    details: str | None
    created_at: datetime
    student_id: int

    class Config:
        from_attributes = True