import httpx
import json
import re
from typing import Optional
from recipe_scrapers import scrape_html
try:
    from recipe_scrapers._exceptions import WebsiteNotImplementedError, NoSchemaFoundInWildMode
except ImportError:
    WebsiteNotImplementedError = Exception
    NoSchemaFoundInWildMode = Exception
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
    Tries recipe-scrapers first, falls back to JSON-LD schema parsing.
    """
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        resp = await client.get(url, headers=HEADERS)
        if resp.status_code != 200:
            raise ValueError(
                f"Could not load page (HTTP {resp.status_code}). "
                "The site may be blocking imports."
            )
        html = resp.text

    # Try recipe-scrapers first (supports ~400 sites natively)
    scraper = None
    try:
        scraper = scrape_html(html, org_url=url)
        # Test that it actually found something useful
        _ = scraper.title()
        _ = scraper.ingredients()
    except (WebsiteNotImplementedError, NoSchemaFoundInWildMode):
        scraper = None
    except Exception:
        scraper = None

    # If recipe-scrapers failed, try wild mode (schema.org JSON-LD)
    if scraper is None:
        try:
            scraper = scrape_html(html, org_url=url, wild_mode=True)
            _ = scraper.title()
            _ = scraper.ingredients()
        except Exception:
            scraper = None

    # If still nothing, try manual JSON-LD extraction
    if scraper is None:
        return await _extract_from_jsonld(html, url, servings_override)

    return await _build_result(scraper, url, servings_override)


async def _build_result(scraper, url: str, servings_override: Optional[int]) -> dict:
    """Build normalized result dict from a scraper object."""

    try:
        title = scraper.title() or "Untitled Recipe"
    except Exception:
        title = "Untitled Recipe"

    try:
        yields_str = scraper.yields() or ""
        original_servings = int(re.search(r'\d+', yields_str).group()) if re.search(r'\d+', yields_str) else 4
    except Exception:
        original_servings = 4

    servings = servings_override or original_servings
    scale = servings / original_servings if original_servings else 1

    try:
        image_url = scraper.image()
    except Exception:
        image_url = None

    try:
        ready_in_minutes = scraper.total_time() or None
    except Exception:
        ready_in_minutes = None

    try:
        raw_ingredients = scraper.ingredients() or []
    except Exception:
        raw_ingredients = []

    if not raw_ingredients:
        raise ValueError(
            "Could not extract ingredients from this page. "
            "Try entering the recipe manually."
        )

    ingredients = await _parse_ingredients(raw_ingredients, scale)

    try:
        instructions = scraper.instructions() or None
    except Exception:
        instructions = None

    try:
        category = scraper.category() or ""
        auto_tags = [t.strip().title() for t in category.split(",") if t.strip()]
    except Exception:
        auto_tags = []

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


async def _extract_from_jsonld(html: str, url: str, servings_override: Optional[int]) -> dict:
    """
    Last resort: find Recipe schema.org JSON-LD blocks in the HTML and parse directly.
    """
    # Find all <script type="application/ld+json"> blocks
    scripts = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.DOTALL | re.IGNORECASE
    )

    recipe_data = None
    for script in scripts:
        try:
            data = json.loads(script.strip())
            # Handle @graph arrays
            if isinstance(data, dict) and data.get("@graph"):
                for item in data["@graph"]:
                    if isinstance(item, dict) and "Recipe" in str(item.get("@type", "")):
                        recipe_data = item
                        break
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and "Recipe" in str(item.get("@type", "")):
                        recipe_data = item
                        break
            elif isinstance(data, dict) and "Recipe" in str(data.get("@type", "")):
                recipe_data = data
            if recipe_data:
                break
        except Exception:
            continue

    if not recipe_data:
        raise ValueError(
            f"Could not extract recipe data from this page (found {len(scripts)} JSON-LD blocks). "
            "Try entering the recipe manually."
        )
    title = recipe_data.get("name") or "Untitled Recipe"
    image = recipe_data.get("image")
    if isinstance(image, list):
        image = image[0]
    if isinstance(image, dict):
        image = image.get("url")

    # Servings
    try:
        yields_str = str(recipe_data.get("recipeYield") or "4")
        original_servings = int(re.search(r'\d+', yields_str).group())
    except Exception:
        original_servings = 4

    servings = servings_override or original_servings
    scale = servings / original_servings if original_servings else 1

    # Cook time
    try:
        total_time_str = recipe_data.get("totalTime") or recipe_data.get("cookTime") or ""
        minutes = _parse_iso_duration(total_time_str)
    except Exception:
        minutes = None

    # Ingredients
    raw_ingredients = recipe_data.get("recipeIngredient") or []
    if not raw_ingredients:
        raise ValueError(
            "Could not extract ingredients from this page. "
            "Try entering the recipe manually."
        )

    ingredients = await _parse_ingredients(raw_ingredients, scale)

    # Instructions
    try:
        instr = recipe_data.get("recipeInstructions")
        if isinstance(instr, str):
            instructions = instr
        elif isinstance(instr, list):
            steps = []
            for step in instr:
                if isinstance(step, str):
                    steps.append(step)
                elif isinstance(step, dict):
                    steps.append(step.get("text", ""))
            instructions = "\n\n".join(s for s in steps if s)
        else:
            instructions = None
    except Exception:
        instructions = None

    # Tags
    try:
        keywords = recipe_data.get("keywords") or recipe_data.get("recipeCategory") or ""
        if isinstance(keywords, list):
            auto_tags = [k.strip().title() for k in keywords if k.strip()]
        else:
            auto_tags = [k.strip().title() for k in str(keywords).split(",") if k.strip()]
    except Exception:
        auto_tags = []

    return {
        "title": title,
        "image_url": image,
        "servings": servings,
        "ready_in_minutes": minutes,
        "summary": None,
        "is_vegetarian": False,
        "is_vegan": False,
        "is_gluten_free": False,
        "is_dairy_free": False,
        "ingredients": ingredients,
        "auto_tags": auto_tags,
        "instructions": instructions,
    }


async def _parse_ingredients(raw_ingredients: list, scale: float) -> list:
    """Parse and scale a list of raw ingredient strings."""
    ingredients = []
    for line in raw_ingredients:
        parsed = parse_ingredient_line(str(line))
        if not parsed:
            ingredients.append({
                "name": str(line).strip(),
                "original": str(line).strip(),
                "amount": None,
                "unit": "",
                "display_quantity": "",
                "aisle": "Other",
            })
            continue

        amount = parsed.get("amount")
        if amount is not None and scale != 1:
            amount = round(amount * scale, 4)

        aisle = await lookup_aisle(parsed["name"])
        ingredients.append({
            "name": parsed["name"],
            "original": str(line).strip(),
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