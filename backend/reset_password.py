from app.database import SessionLocal
from app import models, auth

# ---- SETTINGS ----
EMAIL = "test@example.com"
NEW_PASSWORD = "student123"

def reset_password():
    db = SessionLocal()
    try:
        user = db.query(models.User).filter(models.User.email == EMAIL).first()
        if not user:
            print(f"No user found with email: {EMAIL}")
            return

        # Hash the new password using the same method as signup
        user.hashed_password = auth.hash_password(NEW_PASSWORD)
        db.commit()
        print(f"Password reset successfully for {EMAIL}")
        print(f"New password: {NEW_PASSWORD}")
    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    reset_password()