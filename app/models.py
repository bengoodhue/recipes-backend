from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from datetime import datetime
import json


class RecipeTagLink(SQLModel, table=True):
    recipe_id: Optional[int] = Field(default=None, foreign_key="recipe.id", primary_key=True)
    tag_id: Optional[int] = Field(default=None, foreign_key="tag.id", primary_key=True)


class Tag(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    recipes: List["Recipe"] = Relationship(back_populates="tags", link_model=RecipeTagLink)


class Recipe(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    url: str
    title: str
    image_url: Optional[str] = None
    servings: int = 4
    ready_in_minutes: Optional[int] = None
    summary: Optional[str] = None
    rating: Optional[int] = None  # 1-5
    is_vegetarian: bool = False
    is_vegan: bool = False
    is_gluten_free: bool = False
    is_dairy_free: bool = False
    source: Optional[str] = None       # e.g. "Serious Eats", "Joy of Cooking p.142"
    instructions: Optional[str] = None # free-form instructions text
    # Store ingredients as JSON string
    ingredients_json: str = Field(default="[]")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    tags: List[Tag] = Relationship(back_populates="recipes", link_model=RecipeTagLink)

    @property
    def ingredients(self):
        return json.loads(self.ingredients_json)

    @ingredients.setter
    def ingredients(self, value):
        self.ingredients_json = json.dumps(value)


class ShoppingList(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    items: List["ShoppingListItem"] = Relationship(back_populates="shopping_list")
    recipe_links: List["ShoppingListRecipeLink"] = Relationship(back_populates="shopping_list")


class ShoppingListRecipeLink(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    shopping_list_id: int = Field(foreign_key="shoppinglist.id")
    recipe_id: int = Field(foreign_key="recipe.id")
    servings_override: Optional[int] = None
    shopping_list: Optional[ShoppingList] = Relationship(back_populates="recipe_links")


class PantryItem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)  # stored lowercase for matching


class ShoppingListItem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    shopping_list_id: int = Field(foreign_key="shoppinglist.id")
    name: str
    display_quantity: Optional[str] = None
    unit: Optional[str] = None
    amount: Optional[float] = None
    aisle: Optional[str] = None
    is_pantry_staple: bool = False
    is_checked: bool = False
    is_manual: bool = False
    source_recipe_ids_json: str = Field(default="[]")
    has_unit_conflict: bool = False
    conflict_details_json: str = Field(default="[]")
    sort_order: int = 0
    shopping_list: Optional[ShoppingList] = Relationship(back_populates="items")

    @property
    def source_recipe_ids(self):
        import json
        return json.loads(self.source_recipe_ids_json)

    @property
    def conflict_details(self):
        import json
        return json.loads(self.conflict_details_json)