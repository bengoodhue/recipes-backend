import asyncio
import json
import re
from typing import Optional
from playwright.sync_api import sync_playwright
from recipe_scrapers import scrape_html
from .aisles import lookup_aisle
from .parser import parse_ingredient_line


def _fetch_html_sync(url: str) -> str:
    """Fetch page HTML using a headless Chromium browser (sync, run in thread)."""
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
            if response and response.status != 200:
                raise ValueError(
                    f"Could not load page (HTTP {response.status}). "
                    "The site may be blocking imports."
                )
            # Wait for network to settle so JS-rendered recipe schema is in the DOM.
            # Falls back to a fixed wait if the page has continuous background requests.
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                page.wait_for_timeout(3000)
            html = page.content()
        finally:
            browser.close()
    return html


async def _fetch_html(url: str) -> str:
    """Run the sync Playwright fetch in a thread to avoid Windows asyncio subprocess limits."""
    return await asyncio.to_thread(_fetch_html_sync, url)


async def extract_recipe(url: str, servings_override: Optional[int] = None) -> dict:
    """
    Fetch a recipe page using Playwright and extract structured data.
    Strategy:
    1. Use headless Chromium to load the page (bypasses bot detection, runs JS)
    2. Try recipe-scrapers wild mode on the rendered HTML
    3. Fall back to manual JSON-LD extraction
    """
    html = await _fetch_html(url)

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
        instructions = None  # Not stored — users go back to the source site to cook
        yields_str = _safe(scraper.yields) or ""
        m = re.search(r'\d+', str(yields_str))
        if m:
            original_servings = int(m.group())
        category = _safe(scraper.category) or ""
        auto_tags = [t.strip().title() for t in str(category).split(",") if t.strip()]
    except Exception as e:
        wild_mode_error = f"{type(e).__name__}: {str(e)[:200]}"
        raw_ingredients = None

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
    try:
        return fn()
    except Exception:
        return None


async def _extract_from_jsonld(html: str, url: str, servings_override: Optional[int], wild_mode_error=None) -> dict:
    """Manual JSON-LD extraction fallback."""
    scripts = re.findall(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.DOTALL | re.IGNORECASE
    )
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

    if not recipe_data:
        # Try Article body fallback (Shopify/blog sites like Magnolia use @type:Article
        # with all content in articleBody plain text instead of @type:Recipe schema)
        for script in scripts:
            try:
                data = json.loads(script.strip())
                body = _find_article_body(data)
                if body:
                    return await _extract_from_article_body(body, html, url, servings_override)
            except Exception:
                continue

        raise ValueError(
            f"Could not extract recipe data from this page "
            f"(wild_mode: {wild_mode_error}, searched {len(scripts)} JSON-LD blocks). "
            "Try entering the recipe manually."
        )

    title = recipe_data.get("name") or "Untitled Recipe"

    image = recipe_data.get("image")
    if isinstance(image, list) and image:
        image = image[0]
    if isinstance(image, dict):
        image = image.get("url")

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

    minutes = None
    for key in ("totalTime", "cookTime", "performTime"):
        val = recipe_data.get(key)
        if val:
            minutes = _parse_iso_duration(str(val))
            if minutes:
                break

    raw_ingredients = recipe_data.get("recipeIngredient") or []
    if not raw_ingredients:
        raise ValueError(
            "Found recipe data but could not extract ingredients. "
            "Try entering the recipe manually."
        )

    ingredients = await _parse_ingredients(raw_ingredients, scale)

    instructions = None  # Not stored — users go back to the source site to cook

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
    if isinstance(data, dict):
        type_val = data.get("@type", "")
        if isinstance(type_val, list):
            if any("Recipe" in str(t) for t in type_val):
                return data
        elif "Recipe" in str(type_val):
            return data
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


def _find_article_body(data) -> Optional[str]:
    """Find articleBody in Article/BlogPosting JSON-LD that contains ingredient text."""
    if isinstance(data, dict):
        type_val = data.get("@type", "")
        types = type_val if isinstance(type_val, list) else [type_val]
        if any(t in ("Article", "BlogPosting", "NewsArticle") for t in types):
            body = data.get("articleBody")
            if body and "ingredient" in body.lower():
                return body
        if "@graph" in data:
            result = _find_article_body(data["@graph"])
            if result:
                return result
    elif isinstance(data, list):
        for item in data:
            result = _find_article_body(item)
            if result:
                return result
    return None


async def _extract_from_article_body(
    article_body: str, html: str, url: str, servings_override: Optional[int]
) -> dict:
    """
    Extract recipe from plain-text articleBody (Shopify/blog sites like Magnolia).
    These sites use @type:Article with all recipe content as a single text blob.
    """
    # Title from <h1>
    title = "Untitled Recipe"
    h1_match = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.DOTALL | re.IGNORECASE)
    if h1_match:
        raw_title = re.sub(r'<[^>]+>', '', h1_match.group(1)).strip()
        if raw_title:
            title = raw_title

    # Parse ingredient lines from the article body text blob
    lines = article_body.replace('\r\n', '\n').split('\n')
    in_ingredients = False
    raw_ingredients = []
    _section_ends = ('directions', 'instructions', 'method', 'preparation', 'steps', 'procedure')

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        lower = stripped.lower()
        if lower in ('ingredients', 'ingredient list', 'ingredients:'):
            in_ingredients = True
            continue
        if in_ingredients and lower.rstrip(':') in _section_ends:
            break
        if in_ingredients:
            # Skip ALL CAPS sub-headers like "BALSAMIC GRAPEFRUIT VINAIGRETTE"
            if stripped == stripped.upper() and re.search(r'[A-Z]', stripped):
                continue
            raw_ingredients.append(stripped)

    if not raw_ingredients:
        raise ValueError(
            "Found article content but could not extract ingredients. "
            "Try entering the recipe manually."
        )

    # Image from og:image meta tag
    image_url = None
    og = re.search(
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
        html, re.IGNORECASE
    )
    if not og:
        og = re.search(
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
            html, re.IGNORECASE
        )
    if og:
        image_url = og.group(1)

    servings = servings_override or 4
    ingredients = await _parse_ingredients(raw_ingredients, 1.0)

    return {
        "title": title,
        "image_url": image_url,
        "servings": servings,
        "ready_in_minutes": None,
        "summary": None,
        "is_vegetarian": False,
        "is_vegan": False,
        "is_gluten_free": False,
        "is_dairy_free": False,
        "ingredients": ingredients,
        "auto_tags": [],
        "instructions": None,
    }


async def _parse_ingredients(raw_ingredients: list, scale: float) -> list:
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