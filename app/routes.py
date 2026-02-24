from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select
from typing import Optional
from pydantic import BaseModel
from urllib.parse import urlparse
import json
from datetime import datetime

from .models import (Recipe, Tag, RecipeTagLink, ShoppingList,
                      ShoppingListItem, ShoppingListRecipeLink)
from .spoonacular import extract_recipe
from .units import aggregate_ingredients
from .database import get_session

router = APIRouter()  # v2


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _normalize_url(url: str) -> str:
    """Normalize a URL for duplicate detection."""
    parsed = urlparse(url.lower().strip())
    host = parsed.netloc.replace("www.", "")
    path = parsed.path.rstrip("/")
    return f"{host}{path}"


# ─── Pydantic request/response models ────────────────────────────────────────

class RecipeImportRequest(BaseModel):
    url: str
    servings_override: Optional[int] = None
    tags: list[str] = []
    rating: Optional[int] = None

class RecipeUpdateRequest(BaseModel):
    tags: Optional[list[str]] = None
    rating: Optional[int] = None
    servings: Optional[int] = None

class ListCreateRequest(BaseModel):
    name: str

class ListRenameRequest(BaseModel):
    name: str

class AddRecipeToListRequest(BaseModel):
    recipe_id: int
    servings_override: Optional[int] = None

class AddManualItemRequest(BaseModel):
    name: str
    display_quantity: Optional[str] = None
    unit: Optional[str] = None
    amount: Optional[float] = None
    aisle: Optional[str] = None

class UpdateItemRequest(BaseModel):
    is_checked: Optional[bool] = None
    is_pantry_staple: Optional[bool] = None
    display_quantity: Optional[str] = None
    sort_order: Optional[int] = None


# ─── Tags ─────────────────────────────────────────────────────────────────────

@router.get("/tags/suggestions")
def tag_suggestions(q: str = Query(""), session: Session = Depends(get_session)):
    """Fuzzy tag suggestions as user types."""
    statement = select(Tag).where(Tag.name.ilike(f"%{q}%")).limit(10)
    return session.exec(statement).all()


# ─── Recipes ──────────────────────────────────────────────────────────────────

@router.post("/recipes/import")
async def import_recipe(req: RecipeImportRequest, session: Session = Depends(get_session)):
    """Extract a recipe from a URL via Spoonacular and save it."""

    # Duplicate check on normalized URL
    normalized = _normalize_url(req.url)
    existing_recipes = session.exec(select(Recipe)).all()
    for r in existing_recipes:
        if _normalize_url(r.url) == normalized:
            raise HTTPException(400, detail=f"Recipe already exists: {r.title}")

    data = await extract_recipe(req.url, req.servings_override)

    # Title duplicate check as fallback
    title_match = session.exec(
        select(Recipe).where(Recipe.title == data["title"])
    ).first()
    if title_match:
        raise HTTPException(400, detail=f"Recipe already exists: {title_match.title}")

    recipe = Recipe(
        url=req.url,
        title=data["title"],
        image_url=data.get("image_url"),
        servings=data["servings"],
        ready_in_minutes=data.get("ready_in_minutes"),
        summary=data.get("summary"),
        rating=req.rating,
        is_vegetarian=data["is_vegetarian"],
        is_vegan=data["is_vegan"],
        is_gluten_free=data["is_gluten_free"],
        is_dairy_free=data["is_dairy_free"],
        ingredients_json=json.dumps(data["ingredients"]),
    )
    session.add(recipe)
    session.flush()

    # Merge requested tags + auto tags from Spoonacular
    all_tag_names = list(set(req.tags + data.get("auto_tags", [])))
    for tag_name in all_tag_names:
        tag = session.exec(select(Tag).where(Tag.name == tag_name)).first()
        if not tag:
            tag = Tag(name=tag_name)
            session.add(tag)
            session.flush()
        link = RecipeTagLink(recipe_id=recipe.id, tag_id=tag.id)
        session.add(link)

    session.commit()
    session.refresh(recipe)
    return _recipe_response(recipe, session)


@router.get("/recipes")
def list_recipes(
    tag: Optional[str] = None,
    rating_min: Optional[int] = None,
    session: Session = Depends(get_session)
):
    statement = select(Recipe)
    recipes = session.exec(statement).all()
    if tag:
        recipes = [r for r in recipes if any(t.name.lower() == tag.lower() for t in r.tags)]
    if rating_min:
        recipes = [r for r in recipes if r.rating and r.rating >= rating_min]
    return [_recipe_response(r, session) for r in recipes]


@router.get("/recipes/{recipe_id}")
def get_recipe(recipe_id: int, session: Session = Depends(get_session)):
    recipe = session.get(Recipe, recipe_id)
    if not recipe:
        raise HTTPException(404, "Recipe not found")
    return _recipe_response(recipe, session)


@router.patch("/recipes/{recipe_id}")
def update_recipe(recipe_id: int, req: RecipeUpdateRequest, session: Session = Depends(get_session)):
    recipe = session.get(Recipe, recipe_id)
    if not recipe:
        raise HTTPException(404, "Recipe not found")
    if req.rating is not None:
        recipe.rating = req.rating
    if req.servings is not None:
        recipe.servings = req.servings
    if req.tags is not None:
        existing = session.exec(select(RecipeTagLink).where(RecipeTagLink.recipe_id == recipe_id)).all()
        for link in existing:
            session.delete(link)
        session.flush()
        for tag_name in req.tags:
            tag = session.exec(select(Tag).where(Tag.name == tag_name)).first()
            if not tag:
                tag = Tag(name=tag_name)
                session.add(tag)
                session.flush()
            session.add(RecipeTagLink(recipe_id=recipe.id, tag_id=tag.id))
    session.commit()
    session.refresh(recipe)
    return _recipe_response(recipe, session)


@router.delete("/recipes/{recipe_id}")
def delete_recipe(recipe_id: int, session: Session = Depends(get_session)):
    recipe = session.get(Recipe, recipe_id)
    if not recipe:
        raise HTTPException(404, "Recipe not found")
    links = session.exec(
        select(ShoppingListRecipeLink)
        .where(ShoppingListRecipeLink.recipe_id == recipe_id)
    ).all()
    for link in links:
        session.delete(link)
    session.flush()
    session.delete(recipe)
    session.commit()
    return {"ok": True}


# ─── Shopping Lists ───────────────────────────────────────────────────────────

@router.post("/lists")
def create_list(req: ListCreateRequest, session: Session = Depends(get_session)):
    lst = ShoppingList(name=req.name)
    session.add(lst)
    session.commit()
    session.refresh(lst)
    return _list_response(lst, session)


@router.get("/lists")
def get_lists(session: Session = Depends(get_session)):
    lists = session.exec(select(ShoppingList)).all()
    return [_list_summary(l) for l in lists]


@router.get("/lists/{list_id}")
def get_list(list_id: int, session: Session = Depends(get_session)):
    lst = session.get(ShoppingList, list_id)
    if not lst:
        raise HTTPException(404, "List not found")
    return _list_response(lst, session)


@router.patch("/lists/{list_id}")
def rename_list(list_id: int, req: ListRenameRequest, session: Session = Depends(get_session)):
    lst = session.get(ShoppingList, list_id)
    if not lst:
        raise HTTPException(404)
    lst.name = req.name
    session.commit()
    return _list_summary(lst)


@router.delete("/lists/{list_id}")
def delete_list(list_id: int, session: Session = Depends(get_session)):
    lst = session.get(ShoppingList, list_id)
    if not lst:
        raise HTTPException(404)
    session.delete(lst)
    session.commit()
    return {"ok": True}


@router.post("/lists/{list_id}/recipes")
def add_recipe_to_list(list_id: int, req: AddRecipeToListRequest, session: Session = Depends(get_session)):
    """Add a recipe to a list and regenerate aggregated ingredients."""
    lst = session.get(ShoppingList, list_id)
    if not lst:
        raise HTTPException(404, "List not found")
    recipe = session.get(Recipe, req.recipe_id)
    if not recipe:
        raise HTTPException(404, "Recipe not found")

    existing = session.exec(
        select(ShoppingListRecipeLink)
        .where(ShoppingListRecipeLink.shopping_list_id == list_id)
        .where(ShoppingListRecipeLink.recipe_id == req.recipe_id)
    ).first()
    if existing:
        raise HTTPException(400, "Recipe already in list")

    link = ShoppingListRecipeLink(
        shopping_list_id=list_id,
        recipe_id=req.recipe_id,
        servings_override=req.servings_override,
    )
    session.add(link)
    session.flush()

    _rebuild_list_items(list_id, session)
    lst.updated_at = datetime.utcnow()
    session.commit()
    session.refresh(lst)
    return _list_response(lst, session)


@router.delete("/lists/{list_id}/recipes/{recipe_id}")
def remove_recipe_from_list(list_id: int, recipe_id: int, session: Session = Depends(get_session)):
    link = session.exec(
        select(ShoppingListRecipeLink)
        .where(ShoppingListRecipeLink.shopping_list_id == list_id)
        .where(ShoppingListRecipeLink.recipe_id == recipe_id)
    ).first()
    if not link:
        raise HTTPException(404)
    session.delete(link)
    session.flush()
    _rebuild_list_items(list_id, session)
    session.commit()
    return {"ok": True}


@router.post("/lists/{list_id}/items")
def add_manual_item(list_id: int, req: AddManualItemRequest, session: Session = Depends(get_session)):
    item = ShoppingListItem(
        shopping_list_id=list_id,
        name=req.name,
        display_quantity=req.display_quantity,
        unit=req.unit,
        amount=req.amount,
        aisle=req.aisle,
        is_manual=True,
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


@router.patch("/lists/{list_id}/items/{item_id}")
def update_item(list_id: int, item_id: int, req: UpdateItemRequest, session: Session = Depends(get_session)):
    item = session.get(ShoppingListItem, item_id)
    if not item or item.shopping_list_id != list_id:
        raise HTTPException(404)
    if req.is_checked is not None:
        item.is_checked = req.is_checked
    if req.is_pantry_staple is not None:
        item.is_pantry_staple = req.is_pantry_staple
    if req.display_quantity is not None:
        item.display_quantity = req.display_quantity
    if req.sort_order is not None:
        item.sort_order = req.sort_order
    session.commit()
    return item


@router.delete("/lists/{list_id}/items/{item_id}")
def delete_item(list_id: int, item_id: int, session: Session = Depends(get_session)):
    item = session.get(ShoppingListItem, item_id)
    if not item or item.shopping_list_id != list_id:
        raise HTTPException(404)
    session.delete(item)
    session.commit()
    return {"ok": True}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _rebuild_list_items(list_id: int, session: Session):
    """Delete non-manual items and re-aggregate from all recipes on the list."""
    existing_items = session.exec(
        select(ShoppingListItem)
        .where(ShoppingListItem.shopping_list_id == list_id)
        .where(ShoppingListItem.is_manual == False)
    ).all()
    for item in existing_items:
        session.delete(item)
    session.flush()

    links = session.exec(
        select(ShoppingListRecipeLink).where(ShoppingListRecipeLink.shopping_list_id == list_id)
    ).all()

    if not links:
        return

    ingredient_lists = []
    recipe_ids = []
    for link in links:
        recipe = session.get(Recipe, link.recipe_id)
        if not recipe:
            continue
        ings = recipe.ingredients
        if link.servings_override and recipe.servings:
            scale = link.servings_override / recipe.servings
            ings = [{**i, "amount": i["amount"] * scale} for i in ings]
        ingredient_lists.append(ings)
        recipe_ids.append(link.recipe_id)

    aggregated = aggregate_ingredients(ingredient_lists, recipe_ids)

    for i, agg in enumerate(aggregated):
        item = ShoppingListItem(
            shopping_list_id=list_id,
            name=agg["name"],
            display_quantity=agg["display_quantity"],
            unit=agg["unit"],
            amount=agg.get("amount"),
            aisle=agg["aisle"],
            has_unit_conflict=agg["has_unit_conflict"],
            source_recipe_ids_json=str(agg["source_recipe_ids_json"]),
            conflict_details_json=str(agg["conflict_details_json"]),
            sort_order=i,
        )
        session.add(item)


def _recipe_response(recipe: Recipe, session: Session) -> dict:
    tags = session.exec(
        select(Tag).join(RecipeTagLink).where(RecipeTagLink.recipe_id == recipe.id)
    ).all()
    return {
        "id": recipe.id,
        "url": recipe.url,
        "title": recipe.title,
        "image_url": recipe.image_url,
        "servings": recipe.servings,
        "ready_in_minutes": recipe.ready_in_minutes,
        "summary": recipe.summary,
        "rating": recipe.rating,
        "is_vegetarian": recipe.is_vegetarian,
        "is_vegan": recipe.is_vegan,
        "is_gluten_free": recipe.is_gluten_free,
        "is_dairy_free": recipe.is_dairy_free,
        "tags": [t.name for t in tags],
        "ingredients": recipe.ingredients,
        "created_at": recipe.created_at,
    }


def _list_response(lst: ShoppingList, session: Session) -> dict:
    items = session.exec(
        select(ShoppingListItem).where(ShoppingListItem.shopping_list_id == lst.id)
    ).all()
    links = session.exec(
        select(ShoppingListRecipeLink).where(ShoppingListRecipeLink.shopping_list_id == lst.id)
    ).all()

    recipes = []
    for link in links:
        recipe = session.get(Recipe, link.recipe_id)
        if recipe:
            tags = session.exec(
                select(Tag).join(RecipeTagLink).where(RecipeTagLink.recipe_id == recipe.id)
            ).all()
            recipes.append({
                "id": recipe.id,
                "title": recipe.title,
                "image_url": recipe.image_url,
                "servings": link.servings_override or recipe.servings,
                "ready_in_minutes": recipe.ready_in_minutes,
                "rating": recipe.rating,
                "tags": [t.name for t in tags],
            })

    return {
        **_list_summary(lst),
        "items": [_item_dict(i) for i in items],
        "recipes": recipes,
    }


def _list_summary(lst: ShoppingList) -> dict:
    return {
        "id": lst.id,
        "name": lst.name,
        "created_at": lst.created_at,
        "updated_at": lst.updated_at,
    }


def _item_dict(item: ShoppingListItem) -> dict:
    return {
        "id": item.id,
        "name": item.name,
        "display_quantity": item.display_quantity,
        "unit": item.unit,
        "amount": item.amount,
        "aisle": item.aisle,
        "is_pantry_staple": item.is_pantry_staple,
        "is_checked": item.is_checked,
        "is_manual": item.is_manual,
        "has_unit_conflict": item.has_unit_conflict,
        "sort_order": item.sort_order,
        "source_recipe_ids": item.source_recipe_ids,
        "conflict_details": item.conflict_details,
    }