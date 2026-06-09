import html as html_lib
import json
import re
from typing import Optional

from curl_cffi.requests import AsyncSession
from ingredient_parser import parse_ingredient as _nlp_parse


def _parse_fraction(s: str) -> float:
    s = str(s).strip()
    if not s:
        return 0.0
    if '/' in s:
        try:
            num, den = s.split('/', 1)
            return float(num) / float(den)
        except (ValueError, ZeroDivisionError):
            return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _parse_ingredient(raw: str) -> dict:
    original = raw.strip()
    try:
        parsed = _nlp_parse(original)

        names = parsed.name if isinstance(parsed.name, list) else ([parsed.name] if parsed.name else [])
        name = " and ".join(n.text for n in names if n and n.text) if names else original

        amount = 0.0
        unit = ""
        amounts = parsed.amount if isinstance(parsed.amount, list) else ([parsed.amount] if parsed.amount else [])
        if amounts:
            a = amounts[0]
            amount = _parse_fraction(getattr(a, "quantity", "") or "")
            unit = str(getattr(a, "unit", "") or "").lower().strip()

        return {"name": name, "original": original, "amount": round(amount, 4), "unit": unit, "aisle": ""}
    except Exception:
        return {"name": original, "original": original, "amount": 0.0, "unit": "", "aisle": ""}


def _parse_iso_duration(duration: Optional[str]) -> Optional[int]:
    if not duration:
        return None
    m = re.search(r'(?:(\d+)H)?(?:(\d+)M)?', str(duration))
    if m and (m.group(1) or m.group(2)):
        total = int(m.group(1) or 0) * 60 + int(m.group(2) or 0)
        return total or None
    return None


def _find_recipe_jsonld(html: str) -> Optional[dict]:
    blocks = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.DOTALL | re.IGNORECASE,
    )
    for block in blocks:
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue

        candidates = []
        if isinstance(data, list):
            candidates = data
        elif isinstance(data, dict):
            candidates = data.get('@graph', [data])

        for item in candidates:
            if not isinstance(item, dict):
                continue
            item_type = item.get('@type', '')
            if isinstance(item_type, list):
                item_type = ' '.join(item_type)
            if 'Recipe' in item_type:
                return item

    return None


async def extract_recipe(url: str, servings_override: Optional[int] = None) -> dict:
    async with AsyncSession() as session:
        resp = await session.get(url, impersonate="chrome124", timeout=20)
        resp.raise_for_status()
        html = resp.text

    recipe = _find_recipe_jsonld(html)
    if not recipe:
        raise ValueError(
            f"No recipe data found at {url}. "
            "The page may not contain structured recipe markup."
        )

    title = html_lib.unescape(recipe.get('name') or 'Untitled Recipe').replace('�', '').strip()

    image = recipe.get('image')
    image_url = None
    if isinstance(image, list):
        image = image[0] if image else None
    if isinstance(image, dict):
        image_url = image.get('url')
    elif isinstance(image, str):
        image_url = image

    yield_val = recipe.get('recipeYield', '')
    if isinstance(yield_val, list):
        yield_val = yield_val[0] if yield_val else ''
    original_servings = 4
    m = re.search(r'\d+', str(yield_val))
    if m:
        original_servings = int(m.group())
    servings = servings_override or original_servings

    total_time = (
        recipe.get('totalTime') or
        recipe.get('cookTime') or
        recipe.get('prepTime')
    )
    ready_in_minutes = _parse_iso_duration(total_time)

    description = re.sub(r'<[^>]+>', '', recipe.get('description') or '').strip()
    summary = description[:500] or None

    raw_ings = recipe.get('recipeIngredient') or []
    scale = servings / original_servings if original_servings else 1
    ingredients = []
    for raw in raw_ings:
        if not raw:
            continue
        ing = _parse_ingredient(str(raw))
        if scale != 1:
            ing['amount'] = round(ing['amount'] * scale, 4)
        ingredients.append(ing)

    auto_tags = []
    for field in ('keywords', 'recipeCategory', 'recipeCuisine'):
        val = recipe.get(field, '')
        if isinstance(val, list):
            auto_tags.extend(v.strip().title() for v in val if v.strip())
        elif isinstance(val, str):
            auto_tags.extend(v.strip().title() for v in re.split(r'[,;]', val) if v.strip())
    auto_tags = list(set(auto_tags))

    return {
        "title": title,
        "image_url": image_url,
        "servings": servings,
        "ready_in_minutes": ready_in_minutes,
        "summary": summary,
        "is_vegetarian": False,
        "is_vegan": False,
        "is_gluten_free": False,
        "is_dairy_free": False,
        "ingredients": ingredients,
        "auto_tags": auto_tags,
    }
