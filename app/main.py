from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

from .database import create_db, engine
from .routes import router

app = FastAPI(title="Grocery App API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    create_db()
    _migrate()


def _migrate():
    """Add new columns to existing tables if they don't exist (SQLite upgrades only)."""
    from sqlalchemy import inspect as sa_inspect, text
    inspector = sa_inspect(engine)

    # Fresh PostgreSQL DB — create_db() already created tables with all columns
    if "recipe" not in inspector.get_table_names():
        return

    existing = {col["name"] for col in inspector.get_columns("recipe")}

    with engine.connect() as conn:
        if "source" not in existing:
            conn.execute(text("ALTER TABLE recipe ADD COLUMN source TEXT"))
        if "instructions" not in existing:
            conn.execute(text("ALTER TABLE recipe ADD COLUMN instructions TEXT"))
        conn.commit()


app.include_router(router, prefix="/api")


@app.get("/health")
def health():
    return {"status": "ok"}
