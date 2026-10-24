"""Source-code similarity between candidates of the same test (plagiarism *screening*).

Method: strip comments, collapse string/number literals and rename every non-keyword identifier to one placeholder,
so renaming variables or reformatting does not hide a copy. The token stream is cut into overlapping k-grams
("shingles") and two solutions are compared with the Jaccard index of their shingle sets.

This is a screening aid for a human reviewer, not proof of copying: short or very standard solutions
(e.g. "print the sum of two numbers") are legitimately alike. Solutions with fewer than ``MIN_TOKENS`` tokens are
therefore never scored. Similarity is measured only *within the same test*; matching against the public web is
not implemented.
"""
import re
from collections import defaultdict
from itertools import combinations
from typing import Dict, FrozenSet, List, Optional

from app.mongo import Session

from app import models

K = 5                      # shingle length in tokens
MIN_TOKENS = 30            # below this a solution is too small to say anything
MAX_PER_PROBLEM = 400      # keeps the O(n^2) comparison bounded
HIGH, MEDIUM = 85, 65      # percent thresholds for the labels

_KEYWORDS = frozenset("""
abstract and as assert async await auto bool boolean break byte case catch char class const continue def default defer del
delete do double elif else enum except export extends extern false final finally float fn for from func function go goto
if implements import in include instanceof int interface is lambda len let list long map namespace new nil none not null
operator or override package pass print println private protected public range raise return self short signed sizeof static
string struct super switch template this throw throws true try type typedef typeof union unsigned using var vector virtual
void volatile while with yield cin cout endl scanf printf puts input
""".split())

_COMMENTS = re.compile(r"/\*.*?\*/|//[^\n]*|#[^\n]*", re.S)
_STRINGS = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'')
_TOKEN = re.compile(r"[A-Za-z_]\w*|\d+(?:\.\d+)?|==|!=|<=|>=|&&|\|\||\+\+|--|[-+*/%<>=!&|^~?:;,.(){}\[\]]")


def normalize(source: str) -> List[str]:
    text = _STRINGS.sub(" S ", _COMMENTS.sub(" ", source or ""))
    tokens: List[str] = []
    for tok in _TOKEN.findall(text):
        if tok == "S":
            tokens.append("S")
        elif tok[0].isdigit():
            tokens.append("N")
        elif tok[0].isalpha() or tok[0] == "_":
            tokens.append(tok.lower() if tok.lower() in _KEYWORDS else "I")
        else:
            tokens.append(tok)
    return tokens


def shingles(tokens: List[str]) -> FrozenSet[str]:
    if len(tokens) < MIN_TOKENS:
        return frozenset()
    return frozenset(" ".join(tokens[i:i + K]) for i in range(len(tokens) - K + 1))


def score(a: FrozenSet[str], b: FrozenSet[str]) -> Optional[int]:
    """0-100 similarity, or None when either side is too small to compare."""
    if not a or not b:
        return None
    return round(100 * len(a & b) / len(a | b))


def label(percent: Optional[int]) -> str:
    if percent is None:
        return "n/a"
    return "high" if percent >= HIGH else "medium" if percent >= MEDIUM else "low"


def _best_submissions(db: Session, exam_id: int) -> Dict[int, Dict[int, models.CodeSubmission]]:
    """problem_id -> {attempt_id: best submission}; later submissions win ties (same rule as scoring)."""
    rows = (db.query(models.CodeSubmission).join(models.Attempt, models.Attempt.id == models.CodeSubmission.attempt_id)
            .filter(models.CodeSubmission.exam_id == exam_id, models.Attempt.status != "voided")
            .order_by(models.CodeSubmission.id).all())
    out: Dict[int, Dict[int, models.CodeSubmission]] = defaultdict(dict)
    for row in rows:
        ratio = (row.passed / row.total) if row.total else 0
        cur = out[row.problem_id].get(row.attempt_id)
        if cur is None or ratio >= ((cur.passed / cur.total) if cur.total else 0):
            out[row.problem_id][row.attempt_id] = row
    return out


def find_pairs(db: Session, exam_id: int, min_percent: int = MEDIUM) -> List[dict]:
    """Suspicious pairs for a test, most similar first. Pairs from the same candidate are ignored."""
    problems = {p.id: p for p in db.query(models.CodingProblem).filter(models.CodingProblem.exam_id == exam_id).all()}
    names = {a.id: (a, u) for a, u in db.query(models.Attempt, models.User).join(models.User, models.User.id == models.Attempt.candidate_id)
             .filter(models.Attempt.exam_id == exam_id).all()}
    pairs: List[dict] = []
    for problem_id, by_attempt in _best_submissions(db, exam_id).items():
        items = sorted(by_attempt.items())[:MAX_PER_PROBLEM]
        sh = {aid: shingles(normalize(s.source_code)) for aid, s in items}
        for (a_id, a_sub), (b_id, b_sub) in combinations(items, 2):
            if a_sub.candidate_id == b_sub.candidate_id:
                continue
            pct = score(sh[a_id], sh[b_id])
            if pct is None or pct < min_percent:
                continue
            pairs.append({
                "problem_id": problem_id, "problem": problems[problem_id].title if problem_id in problems else str(problem_id),
                "percent": pct, "level": label(pct),
                "a": {"attempt_id": a_id, "candidate": names[a_id][1].full_name, "passed": a_sub.passed, "total": a_sub.total},
                "b": {"attempt_id": b_id, "candidate": names[b_id][1].full_name, "passed": b_sub.passed, "total": b_sub.total},
            })
    pairs.sort(key=lambda p: -p["percent"])
    return pairs


def matches_for_attempt(pairs: List[dict], attempt_id: int) -> List[dict]:
    out = []
    for p in pairs:
        if p["a"]["attempt_id"] == attempt_id:
            other = p["b"]
        elif p["b"]["attempt_id"] == attempt_id:
            other = p["a"]
        else:
            continue
        out.append({"problem": p["problem"], "percent": p["percent"], "level": p["level"],
                    "other_attempt_id": other["attempt_id"], "other_candidate": other["candidate"]})
    return out
