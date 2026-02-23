from app.database import engine
from sqlmodel import Session, text

with Session(engine) as s:
    s.exec(text("DELETE FROM shoppinglistrecipelink WHERE recipe_id NOT IN (SELECT id FROM recipe)"))
    s.commit()
    print("Done")