import csv
from datetime import datetime, timedelta
from app.database import SessionLocal
from app import models

# ---- SETTINGS ----
CSV_FILE = "questions.csv"
EXAM_TITLE = "Aptitude Test"
EXAM_DESCRIPTION = "Quantitative aptitude assessment"
DURATION_MINUTES = 10 # how long the exam will be available for(Timer)
NUM_QUESTIONS = 150  # how many rows to import from the CSV

def import_questions():
    db = SessionLocal()

    try:
        # 1. Delete the old "Basic Math Test" exam (and its questions via cascade)
        old_exam = db.query(models.Exam).filter(models.Exam.title == "Basic Math Test").first()
        if old_exam:
            # Delete its questions first
            db.query(models.Question).filter(models.Question.exam_id == old_exam.id).delete()
            db.delete(old_exam)
            db.commit()
            print(f"Deleted old exam: Basic Math Test (id={old_exam.id})")
        else:
            print("No 'Basic Math Test' found to delete.")

        # 2. Find an admin user to set as the exam creator
        admin = db.query(models.User).filter(models.User.role == "admin").first()
        if not admin:
            print("ERROR: No admin user found. Create an admin account first.")
            return

        # 3. Create the new exam
        now = datetime.now()
        new_exam = models.Exam(
            title=EXAM_TITLE,
            description=EXAM_DESCRIPTION,
            duration_minutes=DURATION_MINUTES,
            start_time=now,
            end_time=now + timedelta(days=365),  # available for a year
            created_by=admin.id,
        )
        db.add(new_exam)
        db.commit()
        db.refresh(new_exam)
        print(f"Created new exam: {EXAM_TITLE} (id={new_exam.id})")

        # 4. Read the CSV and add questions
        with open(CSV_FILE, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            count = 0
            for row in reader:
                if count >= NUM_QUESTIONS:
                    break

                question = models.Question(
                    exam_id=new_exam.id,
                    question_text=row["Question"].strip(),
                    option_a=row["Option A"].strip(),
                    option_b=row["Option B"].strip(),
                    option_c=row["Option C"].strip(),
                    option_d=row["Option D"].strip(),
                    correct_answer=row["Answer"].strip().upper(),
                )
                db.add(question)
                count += 1

            db.commit()
            print(f"Imported {count} questions into '{EXAM_TITLE}'.")

    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    import_questions()