"""Request / response models shared by several routers. Router-specific payloads live next to their routes."""
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.constants import DEFAULT_PROCTORING


# ---------------------------------------------------------------------------
# users / auth
# ---------------------------------------------------------------------------
class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    full_name: str
    email: str
    role: str
    org_id: Optional[int] = None
    is_active: bool = True
    must_change_password: bool = False
    last_login_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class OrgBrief(BaseModel):
    id: int
    name: str
    slug: str
    status: str
    brand_color: Optional[str] = None
    logo_url: Optional[str] = None
    plan_code: Optional[str] = None
    plan_name: Optional[str] = None
    block_reason: Optional[str] = None
    features: Dict[str, bool] = {}


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
    organization: Optional[OrgBrief] = None


# ---------------------------------------------------------------------------
# proctoring + exam configuration
# ---------------------------------------------------------------------------
class ProctoringConfig(BaseModel):
    webcam_required: bool = DEFAULT_PROCTORING["webcam_required"]
    microphone_required: bool = DEFAULT_PROCTORING["microphone_required"]
    fullscreen_required: bool = DEFAULT_PROCTORING["fullscreen_required"]
    ai_monitoring: bool = DEFAULT_PROCTORING["ai_monitoring"]
    id_verification: bool = DEFAULT_PROCTORING["id_verification"]
    detect_tab_switch: bool = DEFAULT_PROCTORING["detect_tab_switch"]
    block_copy_paste: bool = DEFAULT_PROCTORING["block_copy_paste"]
    block_right_click: bool = DEFAULT_PROCTORING["block_right_click"]
    auto_terminate: bool = DEFAULT_PROCTORING["auto_terminate"]
    ai_can_terminate: bool = DEFAULT_PROCTORING["ai_can_terminate"]
    max_level2_violations: int = Field(DEFAULT_PROCTORING["max_level2_violations"], ge=1, le=20)
    snapshot_interval_seconds: int = Field(DEFAULT_PROCTORING["snapshot_interval_seconds"], ge=0, le=600)
    analysis_interval_seconds: int = Field(DEFAULT_PROCTORING["analysis_interval_seconds"], ge=2, le=30)


class CandidateField(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,30}$")
    label: str = Field(min_length=1, max_length=80)
    required: bool = False


class QuestionIn(BaseModel):
    question_type: Literal["single", "multiple", "true_false", "short_text"] = "single"
    question_text: str = Field(min_length=1, max_length=5000)
    options: List[str] = []
    correct: List[Any] = []
    marks: float = 1.0
    negative_marks: float = 0.0
    section: Optional[str] = None
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    tags: List[str] = []
    explanation: Optional[str] = None


# ---------------------------------------------------------------------------
# coding problems (Judge0)
# ---------------------------------------------------------------------------
class TestCaseCreate(BaseModel):
    __test__ = False  # not a pytest class, despite the name

    input_data: str = ""
    expected_output: str
    is_sample: bool = False


class CodingProblemCreate(BaseModel):
    title: str
    statement: str
    input_format: Optional[str] = None
    output_format: Optional[str] = None
    constraints: Optional[str] = None
    points: int = 10
    time_limit_seconds: float = 2.0
    memory_limit_mb: int = 256
    test_cases: List[TestCaseCreate]


class CodingProblemBulkCreate(BaseModel):
    problems: List[CodingProblemCreate]


class CodeRunRequest(BaseModel):
    language_id: int
    source_code: str
    custom_input: Optional[str] = None


class CodeSubmitRequest(BaseModel):
    language_id: int
    source_code: str


class ExamIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None
    instructions: Optional[str] = None
    duration_minutes: int = Field(ge=1, le=720)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    access_mode: Literal["code", "invite"] = "code"
    access_password: Optional[str] = Field(default=None, max_length=100)
    questions_per_attempt: Optional[int] = Field(default=None, ge=1)
    shuffle_questions: bool = True
    shuffle_options: bool = True
    pass_percentage: float = Field(default=40.0, ge=0, le=100)
    result_visibility: Literal["none", "score", "full"] = "score"
    proctoring: ProctoringConfig = ProctoringConfig()
    candidate_fields: List[CandidateField] = []
    questions: List[QuestionIn] = []
    coding_problems: List[CodingProblemCreate] = []


class ExamPatch(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = None
    instructions: Optional[str] = None
    duration_minutes: Optional[int] = Field(default=None, ge=1, le=720)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    clear_schedule: bool = False
    access_mode: Optional[Literal["code", "invite"]] = None
    access_password: Optional[str] = Field(default=None, max_length=100)  # "" clears it
    questions_per_attempt: Optional[int] = Field(default=None, ge=0)       # 0 clears it (= all questions)
    shuffle_questions: Optional[bool] = None
    shuffle_options: Optional[bool] = None
    pass_percentage: Optional[float] = Field(default=None, ge=0, le=100)
    result_visibility: Optional[Literal["none", "score", "full"]] = None
    proctoring: Optional[ProctoringConfig] = None
    candidate_fields: Optional[List[CandidateField]] = None


# ---------------------------------------------------------------------------
# candidate flow
# ---------------------------------------------------------------------------
class JoinRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=160)
    email: EmailStr
    phone: Optional[str] = Field(default=None, max_length=40)
    fields: Dict[str, str] = {}
    access_password: Optional[str] = Field(default=None, max_length=100)
    invite_token: Optional[str] = Field(default=None, max_length=100)

    @field_validator("full_name")
    @classmethod
    def _strip(cls, v: str) -> str:
        return " ".join(v.split())


class StartRequest(BaseModel):
    consent: bool
    system_info: Dict[str, Any] = {}
    id_image: Optional[str] = None
    face_image: Optional[str] = None


class AnswersIn(BaseModel):
    answers: Dict[str, Any] = {}
    flagged: List[int] = []


class ViolationIn(BaseModel):
    code: str = Field(max_length=30)
    details: Optional[str] = Field(default=None, max_length=300)
    image: Optional[str] = None


class HeartbeatIn(BaseModel):
    visible: bool = True
    fullscreen: bool = True
    camera: Optional[bool] = None
    mic: Optional[bool] = None


class ImageIn(BaseModel):
    image: str


ExamIn.model_rebuild()
