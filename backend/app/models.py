"""Database models (MongoDB documents).

Every tenant-owned collection carries ``org_id`` so isolation can be enforced in one place. Ids are integers handed
out by an atomic counter, which keeps the public API identical to the previous relational version.
"""
from app.constants import ATT_REGISTERED, EXAM_DRAFT, INV_PENDING, ORG_TRIAL, REVIEW_PENDING, ROLE_CANDIDATE
from app.mongo import Field, Model, Rel


# =============================================================================
# SaaS layer: plans, organizations, users
# =============================================================================
class Plan(Model):
    """A subscription plan. A limit of -1 means unlimited."""
    __collection__ = "plans"

    code = Field(unique=True)
    name = Field()
    description = Field()
    price_monthly = Field(default=0)             # whole currency units per month
    currency = Field(default="INR")
    max_admins = Field(default=3)                # team seats (admins + reviewers)
    max_active_tests = Field(default=3)          # published tests at once
    max_candidates_per_month = Field(default=50)
    ai_proctoring = Field(default=True)
    coding_enabled = Field(default=True)
    api_access = Field(default=False)
    webhooks_enabled = Field(default=False)
    evidence_retention_days = Field(default=30)
    is_public = Field(default=True)              # shown on the pricing page
    is_active = Field(default=True)
    sort_order = Field(default=0)
    created_at = Field(now=True)


class Organization(Model):
    """A tenant: one client / subscriber of the platform."""
    __collection__ = "organizations"

    name = Field()
    slug = Field(unique=True)
    status = Field(default=ORG_TRIAL, index=True)
    plan_id = Field()
    limits_override = Field(factory=dict)        # per-customer deal terms
    trial_ends_at = Field()
    subscription_ends_at = Field()
    contact_email = Field()
    brand_color = Field()
    logo_url = Field()
    settings = Field(factory=dict)
    internal_notes = Field()                     # visible to the platform owner only
    suspended_reason = Field()
    allowed_domains = Field(factory=list)        # e-mail domains that belong to this organization, e.g. ["sconexsoft.com"]
    candidate_domain_lock = Field(default=False) # when true only addresses at allowed_domains may join its tests
    created_at = Field(now=True)
    updated_at = Field(now=True, onupdate=True)

    plan = Rel("Plan", local="plan_id")


class User(Model):
    """Staff (super admin / admin / reviewer) and candidates share one collection, separated by role."""
    __collection__ = "users"
    __indexes__ = [(("org_id", "email"), True)]

    org_id = Field(index=True)
    full_name = Field()
    email = Field(lower=True, index=True)
    hashed_password = Field()                    # candidates have none
    role = Field(default=ROLE_CANDIDATE, index=True)
    is_active = Field(default=True)
    must_change_password = Field(default=False)
    failed_login_count = Field(default=0)
    locked_until = Field()
    token_version = Field(default=0)             # bump to revoke every issued token
    last_login_at = Field()
    phone = Field()
    extra = Field(factory=dict)                  # candidate custom fields (roll no, etc.)
    email_verified_at = Field()                  # staff: clicked the e-mailed link; candidates: last confirmed a join code
    created_at = Field(now=True)

    organization = Rel("Organization", local="org_id")


class PasswordToken(Model):
    """One-time tokens for password reset and for accepting a staff invitation."""
    __collection__ = "password_tokens"

    user_id = Field(index=True)
    token_hash = Field(unique=True)
    purpose = Field()                            # "reset" | "invite"
    expires_at = Field()
    used_at = Field()
    created_at = Field(now=True)


class EmailCode(Model):
    """A short-lived 6-digit code e-mailed to a candidate to prove they own the address before joining a test."""
    __collection__ = "email_codes"
    __indexes__ = [(("exam_id", "email"), False)]

    org_id = Field(index=True)
    exam_id = Field()
    email = Field(lower=True)
    code_hash = Field()
    attempts = Field(default=0)
    expires_at = Field()
    used_at = Field()
    created_at = Field(now=True, index=True)


class ApiKey(Model):
    __collection__ = "api_keys"

    org_id = Field(index=True)
    name = Field()
    key_prefix = Field()
    key_hash = Field(unique=True)
    created_by = Field()
    last_used_at = Field()
    revoked_at = Field()
    created_at = Field(now=True)


class Webhook(Model):
    __collection__ = "webhooks"

    org_id = Field(index=True)
    url = Field()
    secret = Field()
    events = Field(factory=list)
    is_active = Field(default=True)
    created_at = Field(now=True)


class WebhookDelivery(Model):
    __collection__ = "webhook_deliveries"

    org_id = Field(index=True)
    webhook_id = Field(index=True)
    event = Field()
    payload = Field(factory=dict)
    status_code = Field()
    success = Field(default=False)
    attempts = Field(default=0)
    error = Field()
    created_at = Field(now=True)


class AuditLog(Model):
    __collection__ = "audit_logs"

    org_id = Field(index=True)
    actor_id = Field()
    actor_email = Field(default="system")
    action = Field(index=True)
    entity_type = Field()
    entity_id = Field()
    details = Field()
    ip_address = Field()
    created_at = Field(now=True, index=True)


class EmailOutbox(Model):
    """Every e-mail the platform sends or tries to send. Doubles as the dev-mode mail viewer."""
    __collection__ = "email_outbox"

    org_id = Field(index=True)
    to_email = Field()
    subject = Field()
    body_html = Field()
    status = Field(default="queued")             # queued | sent | logged | failed
    error = Field()
    created_at = Field(now=True)
    sent_at = Field()


class DemoRequest(Model):
    """Leads from the public landing page."""
    __collection__ = "demo_requests"

    name = Field()
    email = Field()
    company = Field()
    phone = Field()
    message = Field()
    status = Field(default="new")                # new | contacted | converted | dismissed
    created_at = Field(now=True)


class Payment(Model):
    """A Razorpay checkout for a plan purchase. One row per order; ``status`` moves created -> paid | failed."""
    __collection__ = "payments"

    org_id = Field(index=True)
    plan_id = Field()
    user_id = Field()                            # who started the checkout
    order_id = Field(unique=True)                # Razorpay order id
    payment_id = Field(index=True)               # Razorpay payment id once paid
    receipt = Field()
    amount = Field(default=0)                    # in the smallest currency unit (paise)
    currency = Field(default="INR")
    months = Field(default=1)
    status = Field(default="created", index=True)
    method = Field()
    error = Field()
    period_start = Field()
    period_end = Field()
    paid_at = Field()
    created_at = Field(now=True)


# =============================================================================
# Assessments
# =============================================================================
class Exam(Model):
    """A test / assessment owned by one organization."""
    __collection__ = "exams"

    org_id = Field(index=True)
    created_by = Field()
    title = Field()
    description = Field()
    instructions = Field()
    code = Field(unique=True)                    # what candidates type to join
    status = Field(default=EXAM_DRAFT, index=True)
    duration_minutes = Field()
    start_time = Field()                         # earliest moment a candidate may start
    end_time = Field()                           # last moment a candidate may start
    access_mode = Field(default="code")
    access_password_hash = Field()
    questions_per_attempt = Field()              # None = every question
    shuffle_questions = Field(default=True)
    shuffle_options = Field(default=True)
    pass_percentage = Field(default=40.0)
    result_visibility = Field(default="score")
    proctoring = Field(factory=dict)
    candidate_fields = Field(factory=list)       # extra fields to collect on join
    is_sample = Field(default=False)             # a ready-made trial test; does not count against the plan's active-test limit
    sample_key = Field()                         # which trial test it is (makes installing them idempotent)
    created_at = Field(now=True)
    updated_at = Field(now=True, onupdate=True)
    published_at = Field()
    closed_at = Field()

    questions = Rel("Question", fk="exam_id", order=("position", "id"), cascade=True)
    coding_problems = Rel("CodingProblem", fk="exam_id", order=("id",), cascade=True)


class Question(Model):
    """A question. exam_id None means it lives in the organization's question bank."""
    __collection__ = "questions"
    __indexes__ = [(("org_id", "exam_id"), False)]

    org_id = Field(index=True)
    exam_id = Field(index=True)
    question_type = Field(default="single")
    question_text = Field()
    options = Field(factory=list)                # list[str] for choice questions
    correct = Field(factory=list)                # list[int] option indexes, or list[str] accepted answers
    marks = Field(default=1.0)
    negative_marks = Field(default=0.0)
    section = Field()
    difficulty = Field(default="medium")
    tags = Field(factory=list)
    explanation = Field()
    position = Field(default=0)
    created_by = Field()
    created_at = Field(now=True)

    exam = Rel("Exam", local="exam_id")


class Invite(Model):
    __collection__ = "invites"
    __indexes__ = [(("exam_id", "email"), True)]

    org_id = Field(index=True)
    exam_id = Field(index=True)
    email = Field(lower=True)
    name = Field()
    token = Field(unique=True)
    status = Field(default=INV_PENDING)
    sent_at = Field()
    expires_at = Field()
    created_by = Field()
    created_at = Field(now=True)


class Attempt(Model):
    """A candidate's attempt at a test: the session, the answers and the outcome in one document."""
    __collection__ = "attempts"
    __indexes__ = [(("exam_id", "candidate_id", "attempt_no"), True), (("org_id", "status"), False)]

    org_id = Field(index=True)
    exam_id = Field(index=True)
    candidate_id = Field(index=True)
    invite_id = Field()
    attempt_no = Field(default=1)
    status = Field(default=ATT_REGISTERED, index=True)

    created_at = Field(now=True)
    started_at = Field()
    submitted_at = Field()
    extra_seconds = Field(default=0)             # time granted by a proctor

    question_data = Field(factory=list)          # locked questions (no answer key)
    answer_key = Field(factory=dict)             # NEVER sent to clients
    answers = Field(factory=dict)
    flagged = Field(factory=list)

    score = Field()
    max_score = Field()
    percentage = Field()
    passed = Field()
    objective_score = Field()
    coding_score = Field()
    auto_submitted = Field(default=False)
    terminated_reason = Field()

    violation_count = Field(default=0)
    level2_count = Field(default=0)
    risk_score = Field(default=0)
    review_status = Field(default=REVIEW_PENDING)
    reviewer_id = Field()
    review_note = Field()
    reviewed_at = Field()

    ip_address = Field()
    user_agent = Field()
    session_nonce = Field()
    last_heartbeat_at = Field()
    last_state = Field(factory=dict)
    consent_at = Field()
    system_info = Field(factory=dict)
    profile = Field(factory=dict)                # values of the exam's custom fields

    exam = Rel("Exam", local="exam_id")
    candidate = Rel("User", local="candidate_id")


class AttemptMessage(Model):
    """A message a proctor pushes to a candidate during the exam."""
    __collection__ = "attempt_messages"

    attempt_id = Field(index=True)
    sender_id = Field()
    body = Field()
    created_at = Field(now=True)


class Violation(Model):
    __collection__ = "violations"

    org_id = Field(index=True)
    exam_id = Field(index=True)
    attempt_id = Field(index=True)
    candidate_id = Field(index=True)
    code = Field(index=True)
    category = Field(default="browser")
    severity = Field(default=1)
    label = Field()
    details = Field()
    status = Field(default="open")               # open | confirmed | dismissed
    reviewed_by = Field()
    created_at = Field(now=True, index=True)


class Snapshot(Model):
    """A webcam image kept as evidence (ID check, face check, periodic or violation snapshot).

    ``path`` is the storage key: ``cld:<public_id>`` for a Cloudinary asset, otherwise a path below EVIDENCE_DIR
    (local development, tests, or when Cloudinary is not configured).
    """
    __collection__ = "snapshots"

    org_id = Field(index=True)
    attempt_id = Field(index=True)
    violation_id = Field(index=True)
    kind = Field()                               # id | face | periodic | violation
    path = Field()
    created_at = Field(now=True)


# =============================================================================
# Coding questions (executed and judged by Judge0 or the local runner)
# =============================================================================
class CodingProblem(Model):
    __collection__ = "coding_problems"

    exam_id = Field(index=True)
    title = Field()
    statement = Field()
    input_format = Field()
    output_format = Field()
    constraints = Field()
    points = Field(default=10)
    time_limit_seconds = Field(default=2.0)
    memory_limit_mb = Field(default=256)
    created_at = Field(now=True)

    exam = Rel("Exam", local="exam_id")
    test_cases = Rel("TestCase", fk="problem_id", order=("id",), cascade=True)


class TestCase(Model):
    __collection__ = "coding_test_cases"
    __test__ = False  # not a pytest class, despite the name

    problem_id = Field(index=True)
    input_data = Field(default="")
    expected_output = Field()
    is_sample = Field(default=False)

    problem = Rel("CodingProblem", local="problem_id")


class CodeSubmission(Model):
    __collection__ = "code_submissions"

    exam_id = Field(index=True)
    problem_id = Field(index=True)
    candidate_id = Field(index=True)
    attempt_id = Field(index=True)
    language_id = Field()
    source_code = Field()
    verdict = Field()
    passed = Field(default=0)
    total = Field(default=0)
    details = Field()
    created_at = Field(now=True)
