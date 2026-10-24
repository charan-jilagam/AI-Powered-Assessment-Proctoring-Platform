#!/usr/bin/env python
"""Operations CLI.   python manage.py --help

  create-superadmin   create the platform owner
  reset-password      set a new password for a staff user
  seed-plans          (re)create the default subscription plans
  sweep-expired       force-submit attempts whose time ran out
  purge-evidence      delete webcam evidence older than each plan's retention period
  demo-data           create a demo organization with a ready-to-use sample test
"""
import argparse
import getpass
import sys
from datetime import timedelta


def _db():
    from app.config import settings
    from app import database
    database.init_db()
    return database.SessionLocal()


def _password(args) -> str:
    if getattr(args, "password", None):
        return args.password
    first = getpass.getpass("Password: ")
    if first != getpass.getpass("Repeat password: "):
        sys.exit("Passwords do not match")
    return first


def create_superadmin(args):
    from app import auth, models, staff_service
    from app.constants import ROLE_SUPER_ADMIN
    password = _password(args)
    auth.validate_password(password)
    db = _db()
    try:
        if staff_service.find_staff_by_email(db, args.email):
            sys.exit("A staff account with that email already exists")
        db.add(models.User(full_name=args.name, email=args.email.lower(), hashed_password=auth.hash_password(password), role=ROLE_SUPER_ADMIN))
        db.commit()
        print(f"Platform owner created: {args.email}")
    finally:
        db.close()


def reset_password(args):
    from app import auth, staff_service
    password = _password(args)
    auth.validate_password(password)
    db = _db()
    try:
        user = staff_service.find_staff_by_email(db, args.email)
        if not user:
            sys.exit("No staff account with that email")
        user.hashed_password = auth.hash_password(password)
        user.token_version += 1
        user.failed_login_count, user.locked_until = 0, None
        db.commit()
        print("Password updated; all existing sessions were signed out.")
    finally:
        db.close()


def seed_plans(_):
    from app.seed import seed_plans as run
    db = _db()
    try:
        print(f"{run(db)} plan(s) created")
    finally:
        db.close()


def sweep_expired(_):
    from app import attempt_service
    db = _db()
    try:
        print(f"{attempt_service.sweep_expired(db)} attempt(s) finalised")
    finally:
        db.close()


def purge_evidence(_):
    from app import models, storage
    from app.timeutil import utcnow
    db = _db()
    removed = 0
    try:
        for org in db.query(models.Organization).all():
            from app.tenancy import effective_limits
            days = effective_limits(org)["evidence_retention_days"]
            cutoff = utcnow() - timedelta(days=days)
            for snap in db.query(models.Snapshot).filter(models.Snapshot.org_id == org.id, models.Snapshot.created_at < cutoff).all():
                storage.delete_image(snap.path)
                db.delete(snap)
                removed += 1
        db.commit()
        print(f"{removed} evidence image(s) deleted")
    finally:
        db.close()


def demo_data(args):
    from app import auth, models, staff_service
    from app.constants import EXAM_PUBLISHED, ORG_ACTIVE, ROLE_ADMIN
    from app.exam_service import new_code
    from app.seed import seed_plans as plans
    from app.timeutil import utcnow
    db = _db()
    try:
        plans(db)
        if db.query(models.Organization.id).filter(models.Organization.slug == "acme-demo").first():
            sys.exit("Demo organization already exists")
        pro = db.query(models.Plan).filter(models.Plan.code == "professional").first()
        org = models.Organization(name="Acme Demo Corp", slug="acme-demo", status=ORG_ACTIVE, plan_id=pro.id, contact_email=args.email)
        db.add(org)
        db.flush()
        password = _password(args)
        auth.validate_password(password)
        admin = models.User(org_id=org.id, full_name="Demo Admin", email=args.email.lower(), hashed_password=auth.hash_password(password), role=ROLE_ADMIN)
        db.add(admin)
        db.flush()
        exam = models.Exam(
            org_id=org.id, created_by=admin.id, title="General Aptitude Demo", description="A short demo assessment.",
            instructions="Answer every question. Do not leave the full-screen window.", code=new_code(db), status=EXAM_PUBLISHED,
            published_at=utcnow(), duration_minutes=15, proctoring={"webcam_required": False, "ai_monitoring": False, "fullscreen_required": True},
        )
        db.add(exam)
        db.flush()
        samples = [
            ("single", "What is 12 x 12?", ["122", "144", "124", "132"], [1]),
            ("single", "Which is the largest planet?", ["Earth", "Mars", "Jupiter", "Venus"], [2]),
            ("multiple", "Select all even numbers", ["2", "3", "4", "7"], [0, 2]),
            ("true_false", "Water boils at 100C at sea level.", [], ["True"]),
            ("short_text", "Capital of France?", [], ["Paris"]),
        ]
        from app import question_rules
        for position, (qtype, text, options, correct) in enumerate(samples, start=1):
            data = question_rules.normalize_question({"question_type": qtype, "question_text": text, "options": options, "correct": correct})
            db.add(models.Question(org_id=org.id, exam_id=exam.id, position=position, created_by=admin.id, **data))
        db.commit()
        print(f"Demo organization ready.\n  Admin login : {args.email}\n  Test code   : {exam.code}")
    finally:
        db.close()


def init_db(_args=None):
    """Connect to MongoDB, create the database, collections and indexes, seed the plans. Run this once to verify Atlas."""
    from app import database, mongo
    from app.config import settings
    from app.seed import seed_plans as seed
    mongo.ping()
    database.init_db()
    db = database.SessionLocal()
    try:
        seed(db)
        db.commit()
    finally:
        db.close()
    names = sorted(mongo.database().list_collection_names())
    print(f"Connected. Database '{settings.mongodb_db}' is ready with {len(names)} collections: {', '.join(names)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("create-superadmin"); p.add_argument("--email", required=True); p.add_argument("--name", default="Platform Owner"); p.add_argument("--password"); p.set_defaults(fn=create_superadmin)
    p = sub.add_parser("reset-password"); p.add_argument("--email", required=True); p.add_argument("--password"); p.set_defaults(fn=reset_password)
    sub.add_parser("init-db").set_defaults(fn=init_db)
    sub.add_parser("seed-plans").set_defaults(fn=seed_plans)
    sub.add_parser("sweep-expired").set_defaults(fn=sweep_expired)
    sub.add_parser("purge-evidence").set_defaults(fn=purge_evidence)
    p = sub.add_parser("demo-data"); p.add_argument("--email", default="demo@acme.example.com"); p.add_argument("--password"); p.set_defaults(fn=demo_data)
    args = parser.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
