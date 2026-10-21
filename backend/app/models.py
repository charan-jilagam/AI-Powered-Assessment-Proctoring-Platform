from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Boolean, Float
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, default="student")  # "student" or "admin"
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Exam(Base):
    __tablename__ = "exams"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    duration_minutes = Column(Integer, nullable=False)
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    questions = relationship("Question", back_populates="exam", cascade="all, delete-orphan")
    coding_problems = relationship(
        "CodingProblem",
        back_populates="exam",
        cascade="all, delete-orphan",
        order_by="CodingProblem.id",
    )


class Question(Base):
    __tablename__ = "questions"

    id = Column(Integer, primary_key=True, index=True)
    exam_id = Column(Integer, ForeignKey("exams.id"), nullable=False)
    question_text = Column(Text, nullable=False)
    option_a = Column(String, nullable=False)
    option_b = Column(String, nullable=False)
    option_c = Column(String, nullable=False)
    option_d = Column(String, nullable=False)
    correct_answer = Column(String, nullable=False)

    exam = relationship("Exam", back_populates="questions")

    exam = relationship("Exam", back_populates="questions")


class Submission(Base):
    __tablename__ = "submissions"

    id = Column(Integer, primary_key=True, index=True)
    exam_id = Column(Integer, ForeignKey("exams.id"), nullable=False)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    answers = Column(Text, nullable=False)
    score = Column(Integer, nullable=False)
    total_questions = Column(Integer, nullable=False)
    submitted_at = Column(DateTime(timezone=True), server_default=func.now())

class Violation(Base):
    __tablename__ = "violations"

    id = Column(Integer, primary_key=True, index=True)
    exam_id = Column(Integer, ForeignKey("exams.id"), nullable=False)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    violation_type = Column(String, nullable=False)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
class ExamSession(Base):
    __tablename__ = "exam_sessions"

    id = Column(Integer, primary_key=True, index=True)
    exam_id = Column(Integer, ForeignKey("exams.id"), nullable=False)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    question_data = Column(Text, nullable=False)  # JSON: locked questions + shuffled options
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    status = Column(String, default="in_progress")  # in_progress / submitted / terminated

# ----------------------------------------------------------------------------
# Coding questions (executed and judged by Judge0)
# ----------------------------------------------------------------------------
class CodingProblem(Base):
    __tablename__ = "coding_problems"

    id = Column(Integer, primary_key=True, index=True)
    exam_id = Column(Integer, ForeignKey("exams.id"), nullable=False, index=True)
    title = Column(String, nullable=False)
    statement = Column(Text, nullable=False)        # plain text / markdown-ish problem statement
    input_format = Column(Text, nullable=True)
    output_format = Column(Text, nullable=True)
    constraints = Column(Text, nullable=True)
    points = Column(Integer, nullable=False, default=10)   # weight inside the exam score
    time_limit_seconds = Column(Float, nullable=False, default=2.0)
    memory_limit_mb = Column(Integer, nullable=False, default=256)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    exam = relationship("Exam", back_populates="coding_problems")
    test_cases = relationship(
        "TestCase",
        back_populates="problem",
        cascade="all, delete-orphan",
        order_by="TestCase.id",
    )


class TestCase(Base):
    __tablename__ = "coding_test_cases"
    __test__ = False  # not a pytest class, despite the name

    id = Column(Integer, primary_key=True, index=True)
    problem_id = Column(Integer, ForeignKey("coding_problems.id"), nullable=False, index=True)
    input_data = Column(Text, nullable=False, default="")
    expected_output = Column(Text, nullable=False)
    is_sample = Column(Boolean, nullable=False, default=False)  # sample cases are shown to candidates

    problem = relationship("CodingProblem", back_populates="test_cases")


class CodeSubmission(Base):
    __tablename__ = "code_submissions"

    id = Column(Integer, primary_key=True, index=True)
    exam_id = Column(Integer, ForeignKey("exams.id"), nullable=False, index=True)
    problem_id = Column(Integer, ForeignKey("coding_problems.id"), nullable=False, index=True)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    language_id = Column(Integer, nullable=False)
    source_code = Column(Text, nullable=False)
    verdict = Column(String, nullable=False)        # Accepted / Wrong Answer / Compilation Error / ...
    passed = Column(Integer, nullable=False, default=0)
    total = Column(Integer, nullable=False, default=0)
    details = Column(Text, nullable=True)           # JSON: per-test verdicts (no hidden data)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
