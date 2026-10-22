from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app import audit, models, serializers
from app.database import get_db
from app.limiter import limiter

router = APIRouter(prefix="/public", tags=["public"])


@router.get("/plans")
def public_plans(db: Session = Depends(get_db)):
    plans = db.query(models.Plan).filter(models.Plan.is_public.is_(True), models.Plan.is_active.is_(True)).order_by(models.Plan.sort_order).all()
    return [serializers.plan_out(p) for p in plans]


class DemoRequestIn(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    email: EmailStr
    company: str | None = Field(default=None, max_length=160)
    phone: str | None = Field(default=None, max_length=40)
    message: str | None = Field(default=None, max_length=2000)


@router.post("/demo-request")
@limiter.limit("5/minute")
def demo_request(request: Request, body: DemoRequestIn, db: Session = Depends(get_db)):
    db.add(models.DemoRequest(name=body.name, email=body.email, company=body.company, phone=body.phone, message=body.message))
    audit.log_event(db, "DEMO_REQUESTED", actor_email=body.email, details=f"company={body.company}")
    db.commit()
    return {"status": "received"}
