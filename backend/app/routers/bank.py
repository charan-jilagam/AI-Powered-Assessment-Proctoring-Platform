"""The organization's reusable question bank (questions not attached to any test)."""
import json
from collections import Counter
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from app.mongo import func, or_
from app.mongo import Session

from app import auth, exam_service, models, question_rules
from app.database import get_db
from app.errors import not_found
from app.pagination import PageParams, paginate
from app.schemas import QuestionIn

router = APIRouter(prefix="/bank", tags=["question bank"])

_LIBRARY_FILE = Path(__file__).resolve().parent.parent.parent / "samples" / "question_library.json"


def _library() -> list:
    try:
        return json.loads(_LIBRARY_FILE.read_text(encoding="utf-8"))["questions"]
    except (OSError, ValueError, KeyError):
        return []


class LibraryImport(BaseModel):
    sections: List[str] = []   # empty = everything


def _bank_question(db: Session, qid: int, org_id: int) -> models.Question:
    q = db.query(models.Question).filter(models.Question.id == qid, models.Question.org_id == org_id, models.Question.exam_id.is_(None)).first()
    if q is None:
        raise not_found("Question")
    return q


@router.get("/questions")
def list_bank(
    q: Optional[str] = None, difficulty: Optional[str] = None, question_type: Optional[str] = None, tag: Optional[str] = None,
    section: Optional[str] = None, params: PageParams = Depends(), user: models.User = Depends(auth.require_org_admin), db: Session = Depends(get_db),
):
    query = db.query(models.Question).filter(models.Question.org_id == user.org_id, models.Question.exam_id.is_(None))
    if q:
        query = query.filter(func.lower(models.Question.question_text).like(f"%{q.lower()}%"))
    if difficulty:
        query = query.filter(models.Question.difficulty == difficulty)
    if question_type:
        query = query.filter(models.Question.question_type == question_type)
    if section:
        query = query.filter(models.Question.section == section)
    rows_query = query.order_by(models.Question.id.desc())
    if tag:  # JSON containment differs between SQLite and Postgres, so tag filtering is done in Python
        tag = tag.lower()
        items = [x for x in rows_query.all() if tag in (x.tags or [])]
        start = (params.page - 1) * params.page_size
        return {"items": [question_rules.question_to_dict(x) for x in items[start:start + params.page_size]],
                "total": len(items), "page": params.page, "page_size": params.page_size}
    return paginate(rows_query, params, question_rules.question_to_dict)


@router.get("/tags")
def bank_tags(user: models.User = Depends(auth.require_org_admin), db: Session = Depends(get_db)):
    tags, sections = set(), set()
    for q in db.query(models.Question).filter(models.Question.org_id == user.org_id, models.Question.exam_id.is_(None)).all():
        tags.update(q.tags or [])
        if q.section:
            sections.add(q.section)
    return {"tags": sorted(tags), "sections": sorted(sections)}


@router.post("/questions", status_code=201)
def create_bank_question(body: QuestionIn, user: models.User = Depends(auth.require_org_admin), db: Session = Depends(get_db)):
    q = models.Question(org_id=user.org_id, exam_id=None, created_by=user.id, **exam_service._normalize(body.model_dump()))
    db.add(q)
    db.commit()
    db.refresh(q)
    return question_rules.question_to_dict(q)


@router.put("/questions/{question_id}")
def update_bank_question(question_id: int, body: QuestionIn, user: models.User = Depends(auth.require_org_admin), db: Session = Depends(get_db)):
    q = _bank_question(db, question_id, user.org_id)
    for key, value in exam_service._normalize(body.model_dump()).items():
        setattr(q, key, value)
    db.commit()
    return question_rules.question_to_dict(q)


@router.delete("/questions/{question_id}")
def delete_bank_question(question_id: int, user: models.User = Depends(auth.require_org_admin), db: Session = Depends(get_db)):
    db.delete(_bank_question(db, question_id, user.org_id))
    db.commit()
    return {"status": "deleted"}


@router.get("/library")
def library_overview(user: models.User = Depends(auth.require_org_admin), db: Session = Depends(get_db)):
    """The built-in starter library, grouped by section, with how much of it is already in this organization's bank."""
    have = {t for (t,) in db.query(models.Question.question_text).filter(models.Question.org_id == user.org_id, models.Question.exam_id.is_(None)).all()}
    total, imported = Counter(), Counter()
    for q in _library():
        total[q["section"]] += 1
        imported[q["section"]] += q["question_text"] in have
    return {"sections": [{"section": s, "questions": n, "imported": imported[s]} for s, n in sorted(total.items())]}


@router.post("/library/import")
def library_import(body: LibraryImport, user: models.User = Depends(auth.require_org_admin), db: Session = Depends(get_db)):
    """Copy library questions into the bank. Safe to repeat: questions already in the bank are skipped."""
    wanted = set(body.sections)
    have = {t for (t,) in db.query(models.Question.question_text).filter(models.Question.org_id == user.org_id, models.Question.exam_id.is_(None)).all()}
    added = skipped = 0
    for item in _library():
        if wanted and item["section"] not in wanted:
            continue
        if item["question_text"] in have:
            skipped += 1
            continue
        db.add(models.Question(org_id=user.org_id, exam_id=None, created_by=user.id, **question_rules.normalize_question(item)))
        added += 1
    db.commit()
    return {"added": added, "skipped": skipped}
