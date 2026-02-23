from app.database import engine
from sqlmodel import Session, text

with Session(engine) as s:
    s.exec(text("DELETE FROM shoppinglistrecipelink WHERE shopping_list_id=1 AND recipe_id=1"))
    s.commit()
    print("Done")