import os
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime

# Build database URL from .env, fallback to SQLite for local ease-of-use
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/local_audit.db")

# Ensure the data directory exists if we fallback to local sqlite
if DATABASE_URL.startswith("sqlite:///"):
    db_path = DATABASE_URL.replace("sqlite:///", "")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

# Create SQLAlchemy engine
# connect_args is needed for SQLite to avoid thread sharing issues
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    regulation = Column(String(50), nullable=True)
    confidence = Column(Float, nullable=False)
    status = Column(String(50), nullable=False)  # e.g., AUTO_APPROVED, HUMAN_REVIEW_QUEUE
    process_time_sec = Column(Float, nullable=False)
    from_cache = Column(Boolean, default=False)
    citations = Column(Text, nullable=True) # Stored as a JSON string

# Create tables if they don't exist
Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
