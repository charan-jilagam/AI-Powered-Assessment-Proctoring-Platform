"""Database models. Every tenant-owned table carries org_id so isolation can be enforced in one place."""
from sqlalchemy import (
    JSON, Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.constants import (
    ATT_REGISTERED, EXAM_DRAFT, INV_PENDING, ORG_TRIAL, REVIEW_PENDING, ROLE_CANDIDATE,
)
from app.database import Base


def _now():
    return func.now()


# =============================================================================
# SaaS layer: plans, organizations, users
# =============================================================================
class Plan(Base):
    """A subscription plan. A limit of -1 means unlimited."""
    __tablename__ = "plans"

    id = Column(Integer, primary_key=True)
    code = Column(String(40), unique=True, nullable=False, index=True)
    name = Column(String(80), nullable=False)
    description = Column(Text, nullable=True)
    price_monthly = Column(Integer, nullable=False, default=0)  # whole currency units
    currency = Column(String(3), nullable=False, default="USD")
    max_admins = Column(Integer, nullable=False, default=3)            # team seats (admins + reviewers)
    max_active_tests = Column(Integer, nullable=False, default=3)      # published tests at once
    max_candidates_per_month = Column(Integer, nullable=False, default=50)
    ai_proctoring = Column(Boolean, nullable=False, default=True)
    coding_enabled = Column(Boolean, nullable=False, default=True)
    api_access = Column(Boolean, nullable=False, default=False)
    webhooks_enabled = Column(Boolean, nullable=False, default=False)
    evidence_retention_days = Column(Integer, nullable=False, default=30)
    is_public = Column(Boolean, nullable=False, default=True)   # shown on the pricing page
    is_active = Column(Boolean, nullable=False, default=True)
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=_now())


class Organization(Base):
    """A tenant: one client / subscriber of the platform."""
    __tablename__ = "organizations"

    id = Column(Integer, primary_key=True)
    name = Column(String(160), nullable=False)
    slug = Column(String(80), unique=True, nullable=False, index=True)
    status = Column(String(20), nullable=False, default=ORG_TRIAL, index=True)
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=True)
    limits_override = Column(JSON, nullable=False, default=dict)  # per-customer deal terms
    trial_ends_at = Column(DateTime(timezone=True), nullable=True)
    subscription_ends_at = Column(DateTime(timezone=True), nullable=True)
    contact_email = Column(String(255), nullable=True)
    brand_color = Column(String(9), nullable=True)
    logo_url = Column(String(500), nullable=True)
    settings = Column(JSON, nullable=False, default=dict)
    internal_notes = Column(Text, nullable=True)   # visible to the platform owner only
    suspended_reason = Column(String(300), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=_now())
    updated_at = Column(DateTime(timezone=True), server_default=_now(), onupdate=_now())

    plan = relationship("Plan")


class User(Base):
    """Staff (super admin / admin / reviewer) and candidates share one table, separated by role."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=True, index=True)
    full_name = Column(String(160), nullable=False)
    email = Column(String(255), nullable=False, index=True)
    hashed_password = Column(String(255), nullable=True)   # candidates have none
    role = Column(String(20), nullable=False, default=ROLE_CANDIDATE, index=True)
    is_active = Column(Boolean, nullable=False, default=True)
    must_change_password = Column(Boolean, nullable=False, default=False)
    failed_login_count = Column(Integer, nullable=False, default=0)
    locked_until = Column(DateTime(timezone=True), nullable=True)
    token_version = Column(Integer, nullable=False, default=0)  # bump to revoke every issued token
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    phone = Column(String(40), nullable=True)
    extra = Column(JSON, nullable=False, default=dict)         # candidate custom fields (roll no, etc.)
    created_at = Column(DateTime(timezone=True), server_default=_now())

    organization = relationship("Organization")

    __table_args__ = (UniqueConstraint("org_id", "email", name="uq_user_org_email"),)


class PasswordToken(Base):
    """One-time tokens for password reset and for accepting a staff invitation."""
    __tablename__ = "password_tokens"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    token_hash = Column(String(64), unique=True, nullable=False)
    purpose = Column(String(20), nullable=False)  # "reset" | "invite"
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=_now())


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    key_prefix = Column(String(16), nullable=False)
    key_hash = Column(String(64), unique=True, nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=_now())


class Webhook(Base):
    __tablename__ = "webhooks"

    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    url = Column(String(500), nullable=False)
    secret = Column(String(80), nullable=False)
    events = Column(JSON, nullable=False, default=list)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=_now())


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"

    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    webhook_id = Column(Integer, ForeignKey("webhooks.id"), nullable=False, index=True)
    event = Column(String(60), nullable=False)
    payload = Column(JSON, nullable=False, default=dict)
    status_code = Column(Integer, nullable=True)
    success = Column(Boolean, nullable=False, default=False)
    attempts = Column(Integer, nullable=False, default=0)
    error = Column(String(300), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=_now())


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=True, index=True)
    actor_id = Column(Integer, nullable=True)
    actor_email = Column(String(255), nullable=False, default="system")
    action = Column(String(60), nullable=False, index=True)
    entity_type = Column(String(40), nullable=True)
    entity_id = Column(Integer, nullable=True)
    details = Column(Text, nullable=True)
    ip_address = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=_now(), index=True)


class EmailOutbox(Base):
    """Every e-mail the platform sends or tries to send. Doubles as the dev-mode mail viewer."""
    __tablename__ = "email_outbox"

    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=True, index=True)
    to_email = Column(String(255), nullable=False)
    subject = Column(String(255), nullable=False)
    body_html = Column(Text, nullable=False)
    status = Column(String(12), nullable=False, default="queued")  # queued | sent | logged | failed
    error = Column(String(300), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=_now())
    sent_at = Column(DateTime(timezone=True), nullable=True)


class DemoRequest(Base):
    """Leads from the public landing page."""
    __tablename__ = "demo_requests"

    id = Column(Integer, primary_key=True)
    name = Column(String(160), nullable=False)
    email = Column(String(255), nullable=False)
    company = Column(String(160), nullable=True)
    phone = Column(String(40), nullable=True)
    message = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="new")  # new | contacted | converted | dismissed
    created_at = Column(DateTime(timezone=True), server_default=_now())


# =============================================================================
# Assessments
# =============================================================================
class Exam(Base):
    """A test / assessment owned by one organization."""
    __tablename__ = "exams"

    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    instructions = Column(Text, nullable=True)
    code = Column(String(12), unique=True, nullable=False, index=True)   # what candidates type to join
    status = Column(String(12), nullable=False, default=EXAM_DRAFT, index=True)
    duration_minutes = Column(Integer, nullable=False)
    start_time = Column(DateTime(timezone=True), nullable=True)   # earliest moment a candidate may start
    end_time = Column(DateTime(timezone=True), nullable=True)     # last moment a candidate may start
    access_mode = Column(String(10), nullable=False, default="code")
    access_password_hash = Column(String(255), nullable=True)
    questions_per_attempt = Column(Integer, nullable=True)        # None = every question
    shuffle_questions = Column(Boolean, nullable=False, default=True)
    shuffle_options = Column(Boolean, nullable=False, default=True)
    pass_percentage = Column(Float, nullable=False, default=40.0)
    result_visibility = Column(String(8), nullable=False, default="score")
    proctoring = Column(JSON, nullable=False, default=dict)
    candidate_fields = Column(JSON, nullable=False, default=list)   # extra fields to collect on join
    created_at = Column(DateTime(timezone=True), server_default=_now())
    updated_at = Column(DateTime(timezone=True), server_default=_now(), onupdate=_now())
    published_at = Column(DateTime(timezone=True), nullable=True)
    closed_at = Column(DateTime(timezone=True), nullable=True)

    questions = relationship(
        "Question", back_populates="exam", cascade="all, delete-orphan", order_by="Question.position, Question.id"
    )
    coding_problems = relationship(
        "CodingProblem", back_populates="exam", cascade="all, delete-orphan", order_by="CodingProblem.id"
    )


class Question(Base):
    """A question. exam_id NULL means it lives in the organization's question bank."""
    __tablename__ = "questions"

    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    exam_id = Column(Integer, ForeignKey("exams.id"), nullable=True, index=True)
    question_type = Column(String(12), nullable=False, default="single")
    question_text = Column(Text, nullable=False)
    options = Column(JSON, nullable=False, default=list)    # list[str] for choice questions
    correct = Column(JSON, nullable=False, default=list)    # list[int] option indexes, or list[str] accepted answers
    marks = Column(Float, nullable=False, default=1.0)
    negative_marks = Column(Float, nullable=False, default=0.0)
    section = Column(String(80), nullable=True)
    difficulty = Column(String(8), nullable=False, default="medium")
    tags = Column(JSON, nullable=False, default=list)
    explanation = Column(Text, nullable=True)
    position = Column(Integer, nullable=False, default=0)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=_now())

    exam = relationship("Exam", back_populates="questions")


class Invite(Base):
    __tablename__ = "invites"

    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    exam_id = Column(Integer, ForeignKey("exams.id"), nullable=False, index=True)
    email = Column(String(255), nullable=False)
    name = Column(String(160), nullable=True)
    token = Column(String(64), unique=True, nullable=False, index=True)
    status = Column(String(12), nullable=False, default=INV_PENDING)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=_now())

    __table_args__ = (UniqueConstraint("exam_id", "email", name="uq_invite_exam_email"),)


class Attempt(Base):
    """A candidate's attempt at a test: the session, the answers and the outcome in one record."""
    __tablename__ = "attempts"

    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    exam_id = Column(Integer, ForeignKey("exams.id"), nullable=False, index=True)
    candidate_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    invite_id = Column(Integer, ForeignKey("invites.id"), nullable=True)
    attempt_no = Column(Integer, nullable=False, default=1)
    status = Column(String(12), nullable=False, default=ATT_REGISTERED, index=True)

    created_at = Column(DateTime(timezone=True), server_default=_now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    extra_seconds = Column(Integer, nullable=False, default=0)   # time granted by a proctor

    question_data = Column(JSON, nullable=False, default=list)   # locked questions (no answer key)
    answer_key = Column(JSON, nullable=False, default=dict)      # NEVER sent to clients
    answers = Column(JSON, nullable=False, default=dict)
    flagged = Column(JSON, nullable=False, default=list)

    score = Column(Float, nullable=True)
    max_score = Column(Float, nullable=True)
    percentage = Column(Float, nullable=True)
    passed = Column(Boolean, nullable=True)
    objective_score = Column(Float, nullable=True)
    coding_score = Column(Float, nullable=True)
    auto_submitted = Column(Boolean, nullable=False, default=False)
    terminated_reason = Column(String(200), nullable=True)

    violation_count = Column(Integer, nullable=False, default=0)
    level2_count = Column(Integer, nullable=False, default=0)
    risk_score = Column(Integer, nullable=False, default=0)
    review_status = Column(String(14), nullable=False, default=REVIEW_PENDING)
    reviewer_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    review_note = Column(Text, nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)

    ip_address = Column(String(64), nullable=True)
    user_agent = Column(String(300), nullable=True)
    session_nonce = Column(String(32), nullable=True)
    last_heartbeat_at = Column(DateTime(timezone=True), nullable=True)
    last_state = Column(JSON, nullable=False, default=dict)
    consent_at = Column(DateTime(timezone=True), nullable=True)
    system_info = Column(JSON, nullable=False, default=dict)
    profile = Column(JSON, nullable=False, default=dict)         # values of the exam's custom fields

    exam = relationship("Exam")
    candidate = relationship("User", foreign_keys=[candidate_id])

    __table_args__ = (
        UniqueConstraint("exam_id", "candidate_id", "attempt_no", name="uq_attempt_exam_candidate_no"),
        Index("ix_attempt_org_status", "org_id", "status"),
    )


class AttemptMessage(Base):
    """A message a proctor pushes to a candidate during the exam."""
    __tablename__ = "attempt_messages"

    id = Column(Integer, primary_key=True)
    attempt_id = Column(Integer, ForeignKey("attempts.id"), nullable=False, index=True)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    body = Column(String(500), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=_now())


class Violation(Base):
    __tablename__ = "violations"

    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    exam_id = Column(Integer, ForeignKey("exams.id"), nullable=False, index=True)
    attempt_id = Column(Integer, ForeignKey("attempts.id"), nullable=False, index=True)
    candidate_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    code = Column(String(30), nullable=False, index=True)
    category = Column(String(12), nullable=False, default="browser")
    severity = Column(Integer, nullable=False, default=1)
    label = Column(String(200), nullable=False)
    details = Column(Text, nullable=True)
    status = Column(String(12), nullable=False, default="open")   # open | confirmed | dismissed
    reviewed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=_now(), index=True)


class Snapshot(Base):
    """A webcam image kept as evidence (ID check, face check, periodic or violation snapshot)."""
    __tablename__ = "snapshots"

    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    attempt_id = Column(Integer, ForeignKey("attempts.id"), nullable=False, index=True)
    violation_id = Column(Integer, ForeignKey("violations.id"), nullable=True, index=True)
    kind = Column(String(12), nullable=False)   # id | face | periodic | violation
    path = Column(String(300), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=_now())


# =============================================================================
# Coding questions (executed and judged by Judge0)
# =============================================================================
class CodingProblem(Base):
    __tablename__ = "coding_problems"

    id = Column(Integer, primary_key=True)
    exam_id = Column(Integer, ForeignKey("exams.id"), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    statement = Column(Text, nullable=False)
    input_format = Column(Text, nullable=True)
    output_format = Column(Text, nullable=True)
    constraints = Column(Text, nullable=True)
    points = Column(Integer, nullable=False, default=10)
    time_limit_seconds = Column(Float, nullable=False, default=2.0)
    memory_limit_mb = Column(Integer, nullable=False, default=256)
    created_at = Column(DateTime(timezone=True), server_default=_now())

    exam = relationship("Exam", back_populates="coding_problems")
    test_cases = relationship(
        "TestCase", back_populates="problem", cascade="all, delete-orphan", order_by="TestCase.id"
    )


class TestCase(Base):
    __tablename__ = "coding_test_cases"
    __test__ = False  # not a pytest class, despite the name

    id = Column(Integer, primary_key=True)
    problem_id = Column(Integer, ForeignKey("coding_problems.id"), nullable=False, index=True)
    input_data = Column(Text, nullable=False, default="")
    expected_output = Column(Text, nullable=False)
    is_sample = Column(Boolean, nullable=False, default=False)

    problem = relationship("CodingProblem", back_populates="test_cases")


class CodeSubmission(Base):
    __tablename__ = "code_submissions"

    id = Column(Integer, primary_key=True)
    exam_id = Column(Integer, ForeignKey("exams.id"), nullable=False, index=True)
    problem_id = Column(Integer, ForeignKey("coding_problems.id"), nullable=False, index=True)
    candidate_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    attempt_id = Column(Integer, ForeignKey("attempts.id"), nullable=True, index=True)
    language_id = Column(Integer, nullable=False)
    source_code = Column(Text, nullable=False)
    verdict = Column(String(60), nullable=False)
    passed = Column(Integer, nullable=False, default=0)
    total = Column(Integer, nullable=False, default=0)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=_now())
