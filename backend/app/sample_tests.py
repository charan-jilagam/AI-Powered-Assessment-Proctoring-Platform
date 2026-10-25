"""The two ready-made trial tests every new organization gets, so there is something to try on day one.

They are real tests (own join code, editable, deletable) flagged ``is_sample`` so they are labelled "Trial" in the
UI and do not use up the plan's active-test allowance. Installing is idempotent: one test per ``sample_key``.
"""
from typing import Any, Dict, List

from app.mongo import Session

from app import coding, exam_service, models, schemas
from app.constants import EXAM_PUBLISHED
from app.timeutil import utcnow

SAMPLE_PROCTORING = {"webcam_required": False, "microphone_required": False, "ai_monitoring": False, "fullscreen_required": True}

_INSTRUCTIONS = (
    "This is a ready-made ORVEXA trial test. Take it yourself with the join code to see exactly what candidates see, then "
    "open the results to see scoring and proctoring evidence. You can edit or delete this test like any other."
)


def _mc(text, options, correct, section, marks=1, negative=0, difficulty="easy", explanation=None, kind="single"):
    return {"question_type": kind, "question_text": text, "options": options, "correct": correct, "section": section,
            "marks": marks, "negative_marks": negative, "difficulty": difficulty, "explanation": explanation}


def _tf(text, answer, section, explanation=None):
    return {"question_type": "true_false", "question_text": text, "correct": [answer], "section": section, "explanation": explanation, "difficulty": "easy"}


def _short(text, answers, section, explanation=None):
    return {"question_type": "short_text", "question_text": text, "correct": answers, "section": section, "explanation": explanation, "difficulty": "easy"}


SAMPLES: List[Dict[str, Any]] = [
    {
        "key": "trial-aptitude",
        "title": "[Trial] General Aptitude & Tech Basics",
        "description": "Ten quick questions covering aptitude and computing basics. Shows every question type: single choice, multiple choice, true/false and short answer.",
        "duration_minutes": 15,
        "pass_percentage": 40,
        "questions": [
            _mc("What is 15% of 240?", ["24", "30", "36", "40"], [2], "Aptitude", negative=0.25, explanation="0.15 x 240 = 36."),
            _mc("What comes next? 2, 6, 12, 20, 30, ?", ["36", "40", "42", "44"], [2], "Aptitude", negative=0.25, difficulty="medium", explanation="Differences grow by 2: +4, +6, +8, +10, +12."),
            _mc("Select all prime numbers.", ["2", "9", "11", "15"], [0, 2], "Aptitude", marks=2, difficulty="medium", kind="multiple", explanation="9 = 3x3 and 15 = 3x5 are not prime."),
            _tf("The three angles of a triangle always add up to 180 degrees.", "True", "Aptitude"),
            _short("How many minutes are there in 2.5 hours?", ["150", "150 minutes", "150 min"], "Aptitude"),
            _mc("Which data structure works on a Last-In-First-Out basis?", ["Queue", "Stack", "Array", "Graph"], [1], "Tech basics"),
            _mc("What does HTTP stand for?", ["HyperText Transfer Protocol", "High Transfer Text Process", "HyperText Transmission Platform", "Host Transfer Terminal Protocol"], [0], "Tech basics"),
            _mc("Which of these are programming languages?", ["Python", "HTML", "Java", "JSON"], [0, 2], "Tech basics", marks=2, difficulty="medium", kind="multiple",
                explanation="HTML is a markup language and JSON is a data format."),
            _tf("A SQL SELECT statement is used to modify existing rows.", "False", "Tech basics", "UPDATE modifies rows; SELECT only reads them."),
            _short("What does CPU stand for?", ["central processing unit"], "Tech basics"),
        ],
        "coding": [],
    },
    {
        "key": "trial-coding",
        "title": "[Trial] Coding Challenge",
        "description": "Three concept questions and two coding problems with sample and hidden test cases. Candidates can write code in the built-in editor in many languages.",
        "duration_minutes": 30,
        "pass_percentage": 50,
        "questions": [
            _mc("What is the time complexity of binary search on a sorted array of n items?", ["O(n)", "O(log n)", "O(n log n)", "O(1)"], [1], "Concepts", difficulty="medium"),
            _tf("In Python, a list can be changed after it has been created.", "True", "Concepts"),
            _mc("Which keyword defines a function in Python?", ["func", "function", "def", "lambda only"], [2], "Concepts"),
        ],
        "coding": [
            {
                "title": "Sum of Two Numbers",
                "statement": "Read two integers a and b and print their sum.",
                "input_format": "One line with two integers a and b separated by a space.",
                "output_format": "A single integer: a + b.",
                "constraints": "-10^9 <= a, b <= 10^9",
                "points": 10, "time_limit_seconds": 2.0, "memory_limit_mb": 256,
                "test_cases": [
                    {"input_data": "3 4\n", "expected_output": "7\n", "is_sample": True},
                    {"input_data": "-5 12\n", "expected_output": "7\n", "is_sample": True},
                    {"input_data": "0 0\n", "expected_output": "0\n", "is_sample": False},
                    {"input_data": "1000000000 1000000000\n", "expected_output": "2000000000\n", "is_sample": False},
                    {"input_data": "-7 -8\n", "expected_output": "-15\n", "is_sample": False},
                ],
            },
            {
                "title": "Palindrome Check",
                "statement": "A palindrome reads the same forwards and backwards. Read a word and print YES if it is a palindrome, otherwise print NO.",
                "input_format": "One line containing a word of lowercase letters.",
                "output_format": "YES or NO.",
                "constraints": "1 <= length <= 1000",
                "points": 20, "time_limit_seconds": 2.0, "memory_limit_mb": 256,
                "test_cases": [
                    {"input_data": "level\n", "expected_output": "YES\n", "is_sample": True},
                    {"input_data": "coding\n", "expected_output": "NO\n", "is_sample": True},
                    {"input_data": "a\n", "expected_output": "YES\n", "is_sample": False},
                    {"input_data": "abba\n", "expected_output": "YES\n", "is_sample": False},
                    {"input_data": "abcd\n", "expected_output": "NO\n", "is_sample": False},
                ],
            },
        ],
    },
]


def install(db: Session, org: models.Organization, user: models.User) -> List[models.Exam]:
    """Create whichever trial tests the organization does not have yet. The caller commits. Returns the new ones."""
    have = {e.sample_key for e in db.query(models.Exam).filter(models.Exam.org_id == org.id, models.Exam.is_sample.is_(True)).all()}
    created: List[models.Exam] = []
    for spec in SAMPLES:
        if spec["key"] in have:
            continue
        exam = models.Exam(
            org_id=org.id, created_by=user.id, title=spec["title"], description=spec["description"], instructions=_INSTRUCTIONS,
            code=exam_service.new_code(db), status=EXAM_PUBLISHED, published_at=utcnow(), duration_minutes=spec["duration_minutes"],
            pass_percentage=spec["pass_percentage"], proctoring=dict(SAMPLE_PROCTORING), is_sample=True, sample_key=spec["key"],
        )
        db.add(exam)
        db.flush()
        for q in spec["questions"]:
            exam_service.add_question(db, exam, q, user)
        for problem in spec["coding"]:
            coding.create_problem(db, exam.id, schemas.CodingProblemCreate(**problem))
        created.append(exam)
    return created
