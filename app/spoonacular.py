import httpx
import os
from typing import Optional

SPOONACULAR_BASE = "https://api.spoonacular.com"


async def extract_recipe(url: str, servings_override: Optional[int] = None) -> dict:
    """
    Call Spoonacular's extract recipe endpoint and return a normalized dict.
    """
    api_key = os.getenv("SPOONACULAR_API_KEY")
    if not api_key:
        raise ValueError("SPOONACULAR_API_KEY not set in environment")

    params = {
        "apiKey": api_key,
        "url": url,
        "analyze": True,
        "addRecipeInformation": True,
        "forceExtraction": False,
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(f"{SPOONACULAR_BASE}/recipes/extract", params=params)

        if resp.status_code != 200:
            # Surface the actual Spoonacular error message
            try:
                error_data = resp.json()
                msg = error_data.get("message") or error_data.get("status") or f"HTTP {resp.status_code}"
            except Exception:
                msg = f"HTTP {resp.status_code}"
            raise ValueError(f"Spoonacular could not import this recipe: {msg}")

        data = resp.json()

    # Check if Spoonacular returned an empty/unusable result
    if not data.get("extendedIngredients"):
        title = data.get("title", "")
        if title:
            raise ValueError(f"Spoonacular found the page but could not extract ingredients from it. Try entering the recipe manually.")
        else:
            raise ValueError(f"Spoonacular could not read this page. The site may be blocking recipe extraction. Try entering the recipe manually.")

    servings = servings_override or data.get("servings", 4)
    original_servings = data.get("servings", 4)
    scale = servings / original_servings if original_servings else 1

    ingredients = []
    for ing in data.get("extendedIngredients", []):
        amount = (ing.get("amount") or 0) * scale
        unit = (ing.get("unit") or ing.get("measures", {}).get("us", {}).get("unitShort", "")).lower().strip()
        name = ing.get("nameClean") or ing.get("name") or ""
        aisle = ing.get("aisle") or ""
        # Spoonacular sometimes returns semicolon-separated aisles like "Baking;Spices"
        aisle = aisle.split(";")[0].strip()

        ingredients.append({
            "name": name,
            "original": ing.get("original", ""),
            "amount": round(amount, 4),
            "unit": unit,
            "aisle": aisle,
        })

    return {
        "title": data.get("title", "Untitled Recipe"),
        "image_url": data.get("image"),
        "servings": servings,
        "ready_in_minutes": data.get("readyInMinutes"),
        "summary": data.get("summary", "")[:500] if data.get("summary") else None,
        "is_vegetarian": data.get("vegetarian", False),
        "is_vegan": data.get("vegan", False),
        "is_gluten_free": data.get("glutenFree", False),
        "is_dairy_free": data.get("dairyFree", False),
        "ingredients": ingredients,
        "auto_tags": _build_auto_tags(data),
    }


def _build_auto_tags(data: dict) -> list[str]:
    tags = []
    if data.get("vegetarian"):
        tags.append("Vegetarian")
    if data.get("vegan"):
        tags.append("Vegan")
    if data.get("glutenFree"):
        tags.append("Gluten-Free")
    if data.get("dairyFree"):
        tags.append("Dairy-Free")
    for dish in data.get("dishTypes", []):
        tags.append(dish.title())
    for cuisine in data.get("cuisines", []):
        tags.append(cuisine.title())
    return list(set(tags))