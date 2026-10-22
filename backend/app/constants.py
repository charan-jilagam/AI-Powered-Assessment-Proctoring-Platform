"""Shared vocabulary: roles, statuses, limits and the server-side violation catalog."""

# ---- roles -----------------------------------------------------------------
ROLE_SUPER_ADMIN = "super_admin"   # platform owner (no organization)
ROLE_ADMIN = "admin"               # client / subscriber admin (owner of an organization)
ROLE_REVIEWER = "reviewer"         # org staff: monitor + review, cannot change billing/team/settings
ROLE_CANDIDATE = "candidate"       # test taker, created on first join with a test code

STAFF_ROLES = {ROLE_SUPER_ADMIN, ROLE_ADMIN, ROLE_REVIEWER}
ORG_STAFF_ROLES = {ROLE_ADMIN, ROLE_REVIEWER}

# ---- organizations ---------------------------------------------------------
ORG_TRIAL = "trial"
ORG_ACTIVE = "active"
ORG_SUSPENDED = "suspended"
ORG_CANCELLED = "cancelled"
ORG_STATUSES = {ORG_TRIAL, ORG_ACTIVE, ORG_SUSPENDED, ORG_CANCELLED}

UNLIMITED = -1

# ---- tests (exams) ---------------------------------------------------------
EXAM_DRAFT = "draft"
EXAM_PUBLISHED = "published"
EXAM_CLOSED = "closed"
EXAM_ARCHIVED = "archived"
EXAM_STATUSES = {EXAM_DRAFT, EXAM_PUBLISHED, EXAM_CLOSED, EXAM_ARCHIVED}

ACCESS_CODE = "code"      # anyone holding the test code (and password, if set) may join
ACCESS_INVITE = "invite"  # only invited e-mail addresses may join

RESULT_NONE = "none"      # candidate sees only "submitted"
RESULT_SCORE = "score"    # candidate sees score + pass/fail
RESULT_FULL = "full"      # score + per-question review with explanations
RESULT_VISIBILITY = {RESULT_NONE, RESULT_SCORE, RESULT_FULL}

# ---- questions -------------------------------------------------------------
Q_SINGLE = "single"
Q_MULTIPLE = "multiple"
Q_TRUE_FALSE = "true_false"
Q_SHORT = "short_text"
QUESTION_TYPES = {Q_SINGLE, Q_MULTIPLE, Q_TRUE_FALSE, Q_SHORT}
DIFFICULTIES = {"easy", "medium", "hard"}

# ---- attempts --------------------------------------------------------------
ATT_REGISTERED = "registered"     # joined with the code, has not started the clock
ATT_IN_PROGRESS = "in_progress"
ATT_SUBMITTED = "submitted"
ATT_TERMINATED = "terminated"     # ended by proctoring rules or an admin
ATT_VOIDED = "voided"             # reset by an admin so the candidate can retake
FINAL_ATTEMPT_STATUSES = {ATT_SUBMITTED, ATT_TERMINATED}

REVIEW_PENDING = "pending"
REVIEW_CLEARED = "cleared"
REVIEW_SUSPICIOUS = "suspicious"
REVIEW_DISQUALIFIED = "disqualified"
REVIEW_STATUSES = {REVIEW_PENDING, REVIEW_CLEARED, REVIEW_SUSPICIOUS, REVIEW_DISQUALIFIED}

# ---- invites ---------------------------------------------------------------
INV_PENDING = "pending"
INV_STARTED = "started"
INV_COMPLETED = "completed"
INV_REVOKED = "revoked"

# ---- violation catalog (the SERVER decides severity; clients only report codes) ----
# code -> (severity 1|2, category, human label, risk weight)
VIOLATION_CATALOG = {
    # browser lockdown
    "TAB_SWITCH":        (2, "browser", "Switched to another tab or window", 6),
    "FULLSCREEN_EXIT":   (2, "browser", "Exited fullscreen mode", 6),
    "WINDOW_BLUR":       (1, "browser", "Exam window lost focus", 2),
    "COPY_PASTE":        (1, "browser", "Attempted copy / paste / cut", 2),
    "RIGHT_CLICK":       (1, "browser", "Attempted right-click", 1),
    "SHORTCUT":          (1, "browser", "Blocked keyboard shortcut used", 2),
    "DEVTOOLS":          (2, "browser", "Developer tools suspected", 8),
    "SCREEN_RESIZE":     (1, "browser", "Window resized unexpectedly", 1),
    # camera / microphone
    "CAMERA_LOST":       (2, "device", "Camera was disconnected or blocked", 7),
    "MIC_LOST":          (1, "device", "Microphone was disconnected or blocked", 3),
    "AUDIO_VOICE":       (1, "audio", "Talking / voices detected", 3),
    # AI vision
    "NO_FACE":           (2, "ai", "No face detected", 5),
    "MULTIPLE_FACES":    (2, "ai", "Multiple faces detected", 8),
    "LOOKING_AWAY":      (1, "ai", "Candidate looking away from screen", 2),
    "HEAD_TURNED":       (1, "ai", "Head turned away from screen", 2),
    "LIP_MOVEMENT":      (1, "ai", "Lip movement - possible speaking", 2),
    "PROHIBITED_OBJECT": (2, "ai", "Prohibited object detected", 7),
    "CAMERA_COVERED":   (2, "ai", "Camera view is covered or too dark", 7),
    # session integrity (raised by the server itself)
    "SESSION_RESUMED":   (1, "session", "Exam session resumed", 2),
    "IP_CHANGED":        (1, "session", "Network address changed during the exam", 3),
    "CONNECTION_LOST":   (1, "session", "Connection lost for an extended time", 1),
    "ADMIN_NOTE":        (1, "admin", "Note added by proctor", 0),
}
CLIENT_REPORTABLE = {
    "TAB_SWITCH", "FULLSCREEN_EXIT", "WINDOW_BLUR", "COPY_PASTE", "RIGHT_CLICK", "SHORTCUT",
    "DEVTOOLS", "SCREEN_RESIZE", "CAMERA_LOST", "MIC_LOST", "AUDIO_VOICE",
}
DUPLICATE_WINDOW_SECONDS = 8      # identical violation inside this window counts once
MAX_VIOLATIONS_PER_ATTEMPT = 400  # safety valve against a hostile/buggy client

DEFAULT_PROCTORING = {
    "webcam_required": True,
    "microphone_required": False,
    "fullscreen_required": True,
    "ai_monitoring": True,
    "id_verification": False,
    "detect_tab_switch": True,
    "block_copy_paste": True,
    "block_right_click": True,
    "auto_terminate": True,
    "ai_can_terminate": False,   # AI findings are for human review unless the org opts in
    "max_level2_violations": 3,
    "snapshot_interval_seconds": 60,
    "analysis_interval_seconds": 3,
}

LANGUAGE_IDS_NOTE = "Judge0 language ids live in app/judge0.py"
