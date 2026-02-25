import httpx
from typing import Optional
from recipe_scrapers import scrape_html
from .aisles import lookup_aisle
from .parser import parse_ingredient_line


async def extract_recipe(url: str, servings_override: Optional[int] = None) -> dict:
    """
    Fetch a recipe page and extract structured data using recipe-scrapers.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }

    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        resp = await client.get(url, headers=headers)
        if resp.status_code != 200:
            raise ValueError(f"Could not load page (HTTP {resp.status_code}). The site may be blocking imports.")
        html = resp.text

    try:
        scraper = scrape_html(html, org_url=url)
    except Exception as e:
        raise ValueError(f"Could not parse recipe from this page. Try entering the recipe manually.")

    # Get title
    try:
        title = scraper.title() or "Untitled Recipe"
    except Exception:
        title = "Untitled Recipe"

    # Get servings
    try:
        original_servings = int(scraper.yields().split()[0]) if scraper.yields() else 4
    except Exception:
        original_servings = 4

    servings = servings_override or original_servings
    scale = servings / original_servings if original_servings else 1

    # Get image
    try:
        image_url = scraper.image()
    except Exception:
        image_url = None

    # Get cook time
    try:
        ready_in_minutes = scraper.total_time() or None
    except Exception:
        ready_in_minutes = None

    # Get ingredients
    try:
        raw_ingredients = scraper.ingredients()
    except Exception:
        raw_ingredients = []

    if not raw_ingredients:
        raise ValueError("Could not extract ingredients from this page. Try entering the recipe manually.")

    # Parse each ingredient line
    ingredients = []
    for line in raw_ingredients:
        parsed = parse_ingredient_line(line)
        if not parsed:
            # Fall back to storing as-is with no amount
            ingredients.append({
                "name": line.strip(),
                "original": line.strip(),
                "amount": None,
                "unit": "",
                "aisle": "Other",
            })
            continue

        # Scale amount if needed
        amount = parsed.get("amount")
        if amount is not None and scale != 1:
            amount = round(amount * scale, 4)

        aisle = await lookup_aisle(parsed["name"])

        ingredients.append({
            "name": parsed["name"],
            "original": line.strip(),
            "amount": amount,
            "unit": parsed.get("unit", ""),
            "display_quantity": parsed.get("display_quantity", ""),
            "aisle": aisle,
        })

    # Get instructions
    try:
        instructions = scraper.instructions() or None
    except Exception:
        instructions = None

    # Build auto tags from dietary info (best effort)
    auto_tags = []
    try:
        for dish in (scraper.category() or "").split(","):
            dish = dish.strip().title()
            if dish:
                auto_tags.append(dish)
    except Exception:
        pass

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