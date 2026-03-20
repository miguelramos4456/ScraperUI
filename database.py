import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base

# Fetch the variable we just created in the Railway dashboard
DATABASE_URL = os.getenv("DATABASE_URL")

# If it's still None, it means the variable name in Railway 
# doesn't match 'DATABASE_URL' exactly.
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is missing! Check your App Variables in Railway.")

# Fix for newer SQLAlchemy/Postgres versions if needed
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
