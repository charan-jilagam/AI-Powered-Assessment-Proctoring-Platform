from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Database connection URL
# Format: postgresql://username:password@host:port/database_name
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
# Create the database engine - this manages the connection
engine = create_engine(DATABASE_URL)

# Create a session factory - each request gets its own session
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class that all our database models will inherit from
Base = declarative_base()

# Dependency function - gives each API request a database session
# and closes it automatically when done
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()