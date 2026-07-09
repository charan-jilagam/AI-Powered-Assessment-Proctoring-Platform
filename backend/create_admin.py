"""Create an admin account. Run inside the container."""
from app.database import SessionLocal
from app import models, auth

# ---- SETTINGS ----
ADMIN_NAME = "Admin User"
ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "admin123"

def create_admin():
    db = SessionLocal()
    try:
        existing = db.query(models.User).filter(models.User.email == ADMIN_EMAIL).first()
        if existing:
            print(f"Admin already exists: {ADMIN_EMAIL}")
            return

        admin = models.User(
            full_name=ADMIN_NAME,
            email=ADMIN_EMAIL,
            hashed_password=auth.hash_password(ADMIN_PASSWORD),
            role="admin",
        )
        db.add(admin)
        db.commit()
        print(f"Admin created: {ADMIN_EMAIL} / {ADMIN_PASSWORD}")
    finally:
        db.close()

if __name__ == "__main__":
    create_admin()