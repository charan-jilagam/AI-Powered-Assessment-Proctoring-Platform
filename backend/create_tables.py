from app.database import engine, Base
from app.models import User

# This creates all tables defined in models.py inside the database
print("Creating tables...")
Base.metadata.create_all(bind=engine)
print("Tables created successfully!")