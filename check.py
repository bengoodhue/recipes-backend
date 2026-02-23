from app.database import engine
from sqlmodel import Session, text

with Session(engine) as s:
    links = s.exec(text("SELECT * FROM shoppinglistrecipelink")).all()
    print("Links:", links)
    recipes = s.exec(text("SELECT id, title FROM recipe")).all()
    print("Recipes:", recipes)