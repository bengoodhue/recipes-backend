import httpx
import json
import re
from typing import Optional
from recipe_scrapers import scrape_html
from .aisles import lookup_aisle
from .parser import parse_ingredient_line


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


async def extract_recipe(url: str, servings_override: Optional[int] = None) -> dict:
    """
    Fetch a recipe page and extract structured data.
    Strategy:
    1. Try recipe-scrapers in wild mode (handles schema.org on any site)
    2. Fall back to manual JSON-LD regex extraction
    """
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        resp = await client.get(url, headers=HEADERS)
        if resp.status_code != 200:
            raise ValueError(
                f"Could not load page (HTTP {resp.status_code}). "
                "The site may be blocking imports."
            )
        html = resp.text
        html_preview = html[:300].replace('\n', ' ')

    # Try recipe-scrapers wild mode

    # Try recipe-scrapers wild mode — this reads schema.org JSON-LD from any site
    raw_ingredients = None
    title = None
    image_url = None
    original_servings = 4
    ready_in_minutes = None
    instructions = None
    auto_tags = []

    wild_mode_error = None
    try:
        scraper = scrape_html(html, org_url=url, wild_mode=True)
        title = _safe(scraper.title) or None
        raw_ingredients = _safe(scraper.ingredients) or []
        image_url = _safe(scraper.image)
        ready_in_minutes = _safe(scraper.total_time)
        instructions = _safe(scraper.instructions)
        yields_str = _safe(scraper.yields) or ""
        m = re.search(r'\d+', str(yields_str))
        if m:
            original_servings = int(m.group())
        category = _safe(scraper.category) or ""
        auto_tags = [t.strip().title() for t in str(category).split(",") if t.strip()]
    except Exception as e:
        wild_mode_error = f"{type(e).__name__}: {str(e)[:200]}"
        raw_ingredients = None

    # If we got no ingredients from recipe-scrapers, try manual JSON-LD
    if not raw_ingredients:
        return await _extract_from_jsonld(html, url, servings_override, wild_mode_error)

    if not title:
        title = "Untitled Recipe"

    servings = servings_override or original_servings
    scale = servings / original_servings if original_servings else 1

    ingredients = await _parse_ingredients(raw_ingredients, scale)

    return {
        "title": title,
        "image_url": image_url,
        "servings": servings,
        "ready_in_minutes": ready_in_minutes,
        "summary": None,
        "is_vegetarian": False,
        "is_vegan": False,
        "is_gluten_free": False,
        "is_dairy_free": False,
        "ingredients": ingredients,
        "auto_tags": auto_tags,
        "instructions": instructions,
    }


def _safe(fn):
    """Call a scraper method safely, returning None on any error."""
    try:
        return fn()
    except Exception:
        return None


async def _extract_from_jsonld(html: str, url: str, servings_override: Optional[int], wild_mode_error=None) -> dict:
    """
    Manual JSON-LD extraction — finds Recipe schema.org blocks in the raw HTML.
    Handles @graph arrays, nested lists, and various formats.
    """
    # Find ALL script blocks that might contain JSON
    scripts = re.findall(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.DOTALL | re.IGNORECASE
    )

    # Also try without quotes around type value
    scripts += re.findall(
        r'<script[^>]*type=application/ld\+json[^>]*>(.*?)</script>',
        html, re.DOTALL | re.IGNORECASE
    )

    recipe_data = None
    for script in scripts:
        try:
            data = json.loads(script.strip())
            recipe_data = _find_recipe_in_jsonld(data)
            if recipe_data:
                break
        except Exception:
            continue

    raise ValueError(
            f"Could not extract recipe data from this page "
            f"(wild_mode: {wild_mode_error}, searched {len(scripts)} JSON-LD blocks, "
            f"html_preview: {html_preview}). "
            "Try entering the recipe manually."
        )

    title = recipe_data.get("name") or "Untitled Recipe"

    # Image
    image = recipe_data.get("image")
    if isinstance(image, list) and image:
        image = image[0]
    if isinstance(image, dict):
        image = image.get("url")

    # Servings
    try:
        yields_str = str(recipe_data.get("recipeYield") or "4")
        if isinstance(recipe_data.get("recipeYield"), list):
            yields_str = str(recipe_data["recipeYield"][0])
        m = re.search(r'\d+', yields_str)
        original_servings = int(m.group()) if m else 4
    except Exception:
        original_servings = 4

    servings = servings_override or original_servings
    scale = servings / original_servings if original_servings else 1

    # Cook time
    minutes = None
    for key in ("totalTime", "cookTime", "performTime"):
        val = recipe_data.get(key)
        if val:
            minutes = _parse_iso_duration(str(val))
            if minutes:
                break

    # Ingredients
    raw_ingredients = recipe_data.get("recipeIngredient") or []
    if not raw_ingredients:
        raise ValueError(
            "Found recipe data but could not extract ingredients. "
            "Try entering the recipe manually."
        )

    ingredients = await _parse_ingredients(raw_ingredients, scale)

    # Instructions
    instr = recipe_data.get("recipeInstructions")
    instructions = None
    if isinstance(instr, str):
        instructions = instr.strip()
    elif isinstance(instr, list):
        steps = []
        for step in instr:
            if isinstance(step, str):
                steps.append(step.strip())
            elif isinstance(step, dict):
                text = step.get("text") or step.get("name") or ""
                if text:
                    steps.append(text.strip())
        instructions = "\n\n".join(s for s in steps if s) or None

    # Tags
    auto_tags = []
    for key in ("keywords", "recipeCategory", "recipeCuisine"):
        val = recipe_data.get(key)
        if val:
            if isinstance(val, list):
                auto_tags += [v.strip().title() for v in val if v.strip()]
            else:
                auto_tags += [v.strip().title() for v in str(val).split(",") if v.strip()]

    return {
        "title": title,
        "image_url": image if isinstance(image, str) else None,
        "servings": servings,
        "ready_in_minutes": minutes,
        "summary": None,
        "is_vegetarian": False,
        "is_vegan": False,
        "is_gluten_free": False,
        "is_dairy_free": False,
        "ingredients": ingredients,
        "auto_tags": list(set(auto_tags)),
        "instructions": instructions,
    }


def _find_recipe_in_jsonld(data) -> Optional[dict]:
    """Recursively search JSON-LD data for a Recipe object."""
    if isinstance(data, dict):
        type_val = data.get("@type", "")
        if isinstance(type_val, list):
            if any("Recipe" in str(t) for t in type_val):
                return data
        elif "Recipe" in str(type_val):
            return data
        # Check @graph
        if "@graph" in data:
            result = _find_recipe_in_jsonld(data["@graph"])
            if result:
                return result
    elif isinstance(data, list):
        for item in data:
            result = _find_recipe_in_jsonld(item)
            if result:
                return result
    return None


async def _parse_ingredients(raw_ingredients: list, scale: float) -> list:
    """Parse and scale a list of raw ingredient strings."""
    ingredients = []
    for line in raw_ingredients:
        line = str(line).strip()
        parsed = parse_ingredient_line(line)
        if not parsed:
            aisle = await lookup_aisle(line)
            ingredients.append({
                "name": line,
                "original": line,
                "amount": None,
                "unit": "",
                "display_quantity": "",
                "aisle": aisle,
            })
            continue

        amount = parsed.get("amount")
        if amount is not None and scale != 1:
            amount = round(amount * scale, 4)

        aisle = await lookup_aisle(parsed["name"])
        ingredients.append({
            "name": parsed["name"],
            "original": line,
            "amount": amount,
            "unit": parsed.get("unit", ""),
            "display_quantity": parsed.get("display_quantity", ""),
            "aisle": aisle,
        })
    return ingredients


def _parse_iso_duration(duration: str) -> Optional[int]:
    """Parse ISO 8601 duration like PT30M or PT1H30M to minutes."""
    if not duration:
        return None
    hours = re.search(r'(\d+)H', duration)
    mins = re.search(r'(\d+)M', duration)
    total = 0
    if hours:
        total += int(hours.group(1)) * 60
    if mins:
        total += int(mins.group(1))
    return total if total > 0 else None