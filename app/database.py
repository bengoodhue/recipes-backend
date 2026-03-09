from sqlmodel import SQLModel, create_engine, Session
import os

# Default to a persistent-volume path on Railway (/data is mounted as a volume).
# Falls back to local ./grocery.db for dev.  PostgreSQL takes priority if DATABASE_URL is set.
_default_db = "sqlite:////data/grocery.db" if os.path.isdir("/data") else "sqlite:///./grocery.db"
DATABASE_URL = os.getenv("DATABASE_URL", _default_db)

# Railway (and Heroku) may provide postgres:// which SQLAlchemy doesn't accept
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# SQLite requires check_same_thread=False; PostgreSQL does not accept it
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)


def create_db():
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
