from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy import text, inspect
import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./grocery.db")

# Railway (and Heroku) may provide postgres:// which SQLAlchemy doesn't accept
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# SQLite requires check_same_thread=False; PostgreSQL does not accept it
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)


def create_db():
    SQLModel.metadata.create_all(engine)
    _run_migrations()


def _run_migrations():
    """Add columns that didn't exist in older schema versions. Works on both SQLite and PostgreSQL."""
    inspector = inspect(engine)
    if "shoppinglistitem" not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns("shoppinglistitem")}
    with engine.connect() as conn:
        if "checked_at" not in existing:
            conn.execute(text("ALTER TABLE shoppinglistitem ADD COLUMN checked_at TIMESTAMP"))
            conn.commit()


def get_session():
    with Session(engine) as session:
        yield session
