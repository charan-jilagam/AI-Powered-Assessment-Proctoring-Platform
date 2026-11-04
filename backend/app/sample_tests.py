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



def _apt(section, text, options, correct, explanation, difficulty="easy", kind="single"):
    """One aptitude MCQ: 1 mark (-0.25 for a wrong answer); multi-select questions are 2 marks (-0.5)."""
    multi = kind == "multiple"
    return _mc(text, options, correct, section, marks=2 if multi else 1, negative=0.5 if multi else 0.25, difficulty=difficulty,
               explanation=explanation, kind=kind)


QA, LR, VA, DI = "Quantitative Aptitude", "Logical Reasoning", "Verbal Ability", "Data Interpretation"
_SALES = "A company's quarterly sales (in Rs lakh): Q1 = 40, Q2 = 55, Q3 = 45, Q4 = 60.\n"

APTITUDE_OMR_QUESTIONS: List[Dict[str, Any]] = [
    # ---- Quantitative Aptitude (14)
    _apt(QA, "A shopkeeper buys an article for Rs 800 and sells it for Rs 920. What is his profit percentage?", ["12%", "15%", "18%", "20%"], [1], "Profit = 120; 120 / 800 x 100 = 15%."),
    _apt(QA, "What is the simple interest on Rs 5,000 at 8% per annum for 3 years?", ["Rs 1,000", "Rs 1,200", "Rs 1,400", "Rs 1,600"], [1], "SI = 5000 x 8 x 3 / 100 = Rs 1,200."),
    _apt(QA, "A 150 m long train crosses a pole in 10 seconds. What is its speed?", ["45 km/h", "54 km/h", "60 km/h", "72 km/h"], [1], "150 / 10 = 15 m/s; 15 x 18/5 = 54 km/h.", "medium"),
    _apt(QA, "Two numbers are in the ratio 3 : 5 and their sum is 160. What is the larger number?", ["60", "80", "100", "120"], [2], "5 / 8 x 160 = 100."),
    _apt(QA, "The average of five numbers is 24. The sum of four of them is 90. What is the fifth number?", ["24", "28", "30", "36"], [2], "Total = 5 x 24 = 120; 120 - 90 = 30."),
    _apt(QA, "A can finish a job in 12 days and B in 18 days. Working together, how long will they take?", ["6 days", "7.2 days", "7.5 days", "8 days"], [1], "Rate = 1/12 + 1/18 = 5/36 per day, so 36/5 = 7.2 days.", "medium"),
    _apt(QA, "What is the compound interest on Rs 10,000 at 10% per annum for 2 years?", ["Rs 2,000", "Rs 2,100", "Rs 2,200", "Rs 2,400"], [1], "10,000 x 1.1 x 1.1 = 12,100; CI = 2,100.", "medium"),
    _apt(QA, "The price of an item rises by 25% and then falls by 20%. What is the net change?", ["5% increase", "No change", "5% decrease", "10% increase"], [1], "1.25 x 0.80 = 1.00, so the price is back where it started.", "medium"),
    _apt(QA, "Select ALL the perfect squares.", ["49", "50", "64", "72"], [0, 2], "49 = 7 x 7 and 64 = 8 x 8; 50 and 72 are not squares.", "easy", "multiple"),
    _apt(QA, "If 40% of a number is 72, what is the number?", ["160", "180", "200", "288"], [1], "72 / 0.40 = 180."),
    _apt(QA, "A boat goes 12 km/h in still water and the stream flows at 3 km/h. How long does it take to go 45 km downstream?", ["3 hours", "3.75 hours", "4 hours", "5 hours"], [0], "Downstream speed = 15 km/h; 45 / 15 = 3 hours.", "medium"),
    _apt(QA, "What is the LCM of 12, 18 and 30?", ["90", "180", "360", "540"], [1], "12 = 2^2 x 3, 18 = 2 x 3^2, 30 = 2 x 3 x 5; LCM = 2^2 x 3^2 x 5 = 180.", "medium"),
    _apt(QA, "Two fair dice are thrown. What is the probability that the sum is 7?", ["1/12", "1/9", "1/6", "5/36"], [2], "Six of the 36 outcomes sum to 7: 6/36 = 1/6.", "medium"),
    _apt(QA, "If x + y = 10 and x - y = 4, what is x times y?", ["18", "21", "24", "28"], [1], "x = 7 and y = 3, so xy = 21.", "medium"),
    # ---- Logical Reasoning (12)
    _apt(LR, "Find the next number: 3, 6, 11, 18, 27, ?", ["36", "38", "40", "42"], [1], "The differences are 3, 5, 7, 9, so the next one is +11: 27 + 11 = 38.", "medium"),
    _apt(LR, "Find the next number: 2, 6, 18, 54, ?", ["108", "148", "162", "216"], [2], "Each term is 3 times the previous one: 54 x 3 = 162."),
    _apt(LR, "Which number is the odd one out? 8, 27, 64, 100, 125", ["27", "64", "100", "125"], [2], "8, 27, 64 and 125 are cubes; 100 is not."),
    _apt(LR, "If letters are numbered A = 1, B = 2 ... then CAT = 3 + 1 + 20 = 24. What is the value of DOG?", ["24", "26", "28", "30"], [1], "D = 4, O = 15, G = 7; 4 + 15 + 7 = 26.", "medium"),
    _apt(LR, "Asha walks 5 km north, then 3 km east, then 5 km south. How far is she from her starting point?", ["3 km", "5 km", "8 km", "13 km"], [0], "The north and south legs cancel, leaving 3 km east.", "medium"),
    _apt(LR, "Pointing to a man, a woman says, \"He is the son of my mother's only son.\" How is the man related to the woman?", ["Brother", "Nephew", "Uncle", "Cousin"], [1], "Her mother's only son is her brother, so the man is her brother's son: her nephew.", "hard"),
    _apt(LR, "Statements: All pens are books. Some books are bags.\nConclusions: I. Some pens are bags.  II. Some bags are books.", ["Only I follows", "Only II follows", "Both I and II follow", "Neither follows"], [1], "'Some books are bags' reverses to 'some bags are books' (II). Nothing links pens to bags (I).", "hard"),
    _apt(LR, "What is the angle between the hour hand and the minute hand of a clock at 3:00?", ["60 degrees", "75 degrees", "90 degrees", "120 degrees"], [2], "Each hour mark is 30 degrees apart; 3 hours = 90 degrees."),
    _apt(LR, "Today is Wednesday. What day of the week will it be after 10 days?", ["Friday", "Saturday", "Sunday", "Monday"], [1], "10 = 7 + 3; three days after Wednesday is Saturday.", "easy"),
    _apt(LR, "Rahul ranks 12th from the top and 29th from the bottom in a class. How many students are in the class?", ["39", "40", "41", "42"], [1], "12 + 29 - 1 = 40.", "medium"),
    _apt(LR, "Select ALL the numbers that are divisible by both 3 and 4.", ["24", "30", "36", "44"], [0, 2], "Divisible by 12: 24 and 36. 30 is not divisible by 4; 44 is not divisible by 3.", "medium", "multiple"),
    _apt(LR, "Book : Reading :: Fork : ?", ["Eating", "Cooking", "Cutting", "Drawing"], [0], "A book is used for reading, a fork is used for eating."),
    # ---- Verbal Ability (9)
    _apt(VA, "Choose the word closest in meaning to ABUNDANT.", ["Scarce", "Plentiful", "Rare", "Meagre"], [1], "Abundant means existing in large quantities: plentiful."),
    _apt(VA, "Choose the word opposite in meaning to BENEVOLENT.", ["Kind", "Generous", "Malevolent", "Gentle"], [2], "Benevolent means well-meaning; malevolent means wishing harm."),
    _apt(VA, "Which sentence is grammatically correct?", ["She doesn't know where is the station.", "She doesn't know where the station is.", "She don't know where the station is.", "She doesn't knows where the station is."], [1], "In an indirect question the subject comes before the verb.", "medium"),
    _apt(VA, "Fill in the blank: He has been working here ___ 2019.", ["for", "since", "from", "during"], [1], "'Since' goes with a point in time; 'for' goes with a length of time."),
    _apt(VA, "Choose the correctly spelt word.", ["Acommodation", "Accomodation", "Accommodation", "Acomodation"], [2], "Accommodation has a double c and a double m."),
    _apt(VA, "What does the idiom 'break the ice' mean?", ["To damage something fragile", "To start a conversation and ease the tension", "To end a friendship", "To feel very cold"], [1], "It means to make people feel comfortable at the start of a meeting."),
    _apt(VA, "One word for 'a person who loves books':", ["Philanthropist", "Bibliophile", "Misanthrope", "Linguist"], [1], "A bibliophile is a lover and collector of books."),
    _apt(VA, "Select ALL the words that are nouns.", ["Happiness", "Quickly", "Teacher", "Beautiful"], [0, 2], "Happiness and teacher are nouns; quickly is an adverb and beautiful an adjective.", "easy", "multiple"),
    _apt(VA, "Change to passive voice: 'The chef cooked the meal.'", ["The meal is cooked by the chef.", "The meal was cooked by the chef.", "The meal has cooked the chef.", "The chef was cooked by the meal."], [1], "Past simple active becomes 'was + past participle' in the passive.", "medium"),
    # ---- Data Interpretation (5)
    _apt(DI, _SALES + "What were the total sales for the year?", ["Rs 190 lakh", "Rs 200 lakh", "Rs 210 lakh", "Rs 220 lakh"], [1], "40 + 55 + 45 + 60 = 200.", "easy"),
    _apt(DI, _SALES + "By what percentage did sales grow from Q1 to Q2?", ["25%", "30%", "37.5%", "40%"], [2], "(55 - 40) / 40 x 100 = 37.5%.", "medium"),
    _apt(DI, _SALES + "What was the average quarterly sales figure?", ["Rs 45 lakh", "Rs 50 lakh", "Rs 52.5 lakh", "Rs 55 lakh"], [1], "200 / 4 = 50.", "easy"),
    _apt(DI, _SALES + "In which quarter did sales fall compared with the quarter before it?", ["Q1", "Q2", "Q3", "Q4"], [2], "Q3 (45) is lower than Q2 (55).", "easy"),
    _apt(DI, _SALES + "Q4 sales are what percentage of the year's total?", ["25%", "28%", "30%", "33%"], [2], "60 / 200 x 100 = 30%.", "medium"),
]

_OMR_INSTRUCTIONS = (
    "This sample shows the OMR feature. The 40 multiple-choice questions come in three fixed sets (A, B and C): each candidate "
    "is given one set, and everyone in the same set sees the identical paper. Click an option, or click a bubble on the OMR "
    "sheet (use the 'OMR sheet' button at the top), and both stay in sync. Some questions allow more than one answer: "
    "mark all correct options. A wrong answer costs 0.25 marks (0.5 for multi-answer questions). Admins can download every "
    "candidate's OMR sheet from the test's Results tab. Your camera is on and AI proctoring watches the whole camera view; this is a "
    "competitive-style paper, so looking down at your rough work is allowed, but phones, other people and leaving the camera view are "
    "still flagged. An on-screen scientific calculator is available from the Calculator button."
)

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
    {
        "key": "trial-aptitude-omr",
        "title": "[Trial] Aptitude Test with OMR (Sets A, B, C)",
        "description": "A 40-question aptitude paper (quantitative, logical, verbal, data interpretation) with single and multi-answer MCQs, "
                       "fixed question sets A, B and C, and a live OMR answer sheet for candidates.",
        "duration_minutes": 45,
        "pass_percentage": 40,
        "question_sets": 3,
        "omr_enabled": True,
        "calculator": "scientific",
        # camera + AI monitoring on, as for a real exam; competitive mode lets candidates look down at rough work
        "proctoring": {"webcam_required": True, "microphone_required": False, "ai_monitoring": True, "fullscreen_required": True,
                       "competitive_exam": True},
        "instructions": _OMR_INSTRUCTIONS,
        "questions": APTITUDE_OMR_QUESTIONS,
        "coding": [],
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
            org_id=org.id, created_by=user.id, title=spec["title"], description=spec["description"], instructions=spec.get("instructions", _INSTRUCTIONS),
            code=exam_service.new_code(db), status=EXAM_PUBLISHED, published_at=utcnow(), duration_minutes=spec["duration_minutes"],
            pass_percentage=spec["pass_percentage"], proctoring=dict(spec.get("proctoring") or SAMPLE_PROCTORING), is_sample=True, sample_key=spec["key"],
            question_sets=spec.get("question_sets", 1), omr_enabled=bool(spec.get("omr_enabled", False)), calculator=spec.get("calculator", "off"),
        )
        db.add(exam)
        db.flush()
        for q in spec["questions"]:
            exam_service.add_question(db, exam, q, user)
        for problem in spec["coding"]:
            coding.create_problem(db, exam.id, schemas.CodingProblemCreate(**problem))
        created.append(exam)
    return created
