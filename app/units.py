"""
Unit conversion and ingredient aggregation logic.

Strategy:
- Convert all volume units to fl_oz as base
- Convert all weight units to oz as base
- Display in most readable unit
- Flag volume vs weight conflicts for manual merge
"""

from typing import Optional
import math
import re

# Volume conversions to fl_oz
VOLUME_TO_FL_OZ = {
    "tsp": 1 / 6,
    "teaspoon": 1 / 6,
    "teaspoons": 1 / 6,
    "tbsp": 0.5,
    "tablespoon": 0.5,
    "tablespoons": 0.5,
    "fl oz": 1.0,
    "fl_oz": 1.0,
    "fluid ounce": 1.0,
    "fluid ounces": 1.0,
    "cup": 8.0,
    "cups": 8.0,
    "pint": 16.0,
    "pints": 16.0,
    "quart": 32.0,
    "quarts": 32.0,
    "gallon": 128.0,
    "gallons": 128.0,
    "ml": 0.033814,
    "milliliter": 0.033814,
    "milliliters": 0.033814,
    "l": 33.814,
    "liter": 33.814,
    "liters": 33.814,
}

# Weight conversions to oz
WEIGHT_TO_OZ = {
    "oz": 1.0,
    "ounce": 1.0,
    "ounces": 1.0,
    "lb": 16.0,
    "lbs": 16.0,
    "pound": 16.0,
    "pounds": 16.0,
    "g": 0.035274,
    "gram": 0.035274,
    "grams": 0.035274,
    "kg": 35.274,
    "kilogram": 35.274,
    "kilograms": 35.274,
}

# Non-convertible units
COUNT_UNITS = {"", "whole", "piece", "pieces", "item", "items", "can", "cans",
               "bunch", "bunches", "clove", "cloves", "head", "heads",
               "stalk", "stalks", "sprig", "sprigs", "slice", "slices",
               "package", "packages", "pkg", "bag", "bags"}


def get_unit_family(unit: str) -> Optional[str]:
    u = unit.lower().strip()
    if u in VOLUME_TO_FL_OZ:
        return "volume"
    if u in WEIGHT_TO_OZ:
        return "weight"
    if u in COUNT_UNITS:
        return "count"
    return "unknown"


def to_base_unit(amount: float, unit: str) -> tuple[Optional[float], str]:
    """Convert amount to base unit (fl_oz for volume, oz for weight). Returns (base_amount, family)."""
    u = unit.lower().strip()
    if u in VOLUME_TO_FL_OZ:
        return amount * VOLUME_TO_FL_OZ[u], "volume"
    if u in WEIGHT_TO_OZ:
        return amount * WEIGHT_TO_OZ[u], "weight"
    return amount, get_unit_family(u) or "unknown"


def from_base_to_readable(amount: float, family: str) -> tuple[float, str]:
    """Convert base unit amount to a human-readable unit."""
    if family == "volume":
        if amount >= 128:
            return round(amount / 128, 6), "gallon"
        elif amount >= 32:
            return round(amount / 32, 6), "quart"
        elif amount >= 2:          # >= 1/4 cup — display in cups
            return round(amount / 8, 6), "cup"
        elif amount >= 0.5:
            return round(amount / 0.5, 4), "tbsp"
        else:
            return round(amount / (1 / 6), 4), "tsp"
    elif family == "weight":
        if amount >= 16:
            return round(amount / 16, 4), "lb"
        else:
            return round(amount, 4), "oz"
    return round(amount, 4), ""


# Cup fractions in ascending order: (decimal_value, unicode_symbol)
_CUP_FRACS = [(1/8, "⅛"), (1/4, "¼"), (1/3, "⅓"), (1/2, "½"), (2/3, "⅔"), (3/4, "¾")]
_FRAC_TOL = 0.04


def _format_cups(amount: float) -> str:
    """
    Format a cup amount using common fractions.
    For non-standard amounts, decomposes as 'X cup + Y tbsp' (like recipe cards).
    """
    whole = int(amount)
    frac = amount - whole

    # Try clean fraction match first
    for val, sym in _CUP_FRACS:
        if abs(frac - val) < _FRAC_TOL:
            display = (str(whole) + sym) if whole > 0 else sym
            return f"{display} cup"

    # Whole number with negligible fraction
    if frac < 0.02:
        return f"{whole} cup"

    # No clean fraction — find largest cup fraction that fits below frac
    best_val, best_sym = 0.0, ""
    for val, sym in _CUP_FRACS:
        if val <= frac + 0.01:
            best_val, best_sym = val, sym

    remainder_tbsp = round((frac - best_val) * 16)

    if remainder_tbsp == 0:
        cup_display = (str(whole) + best_sym) if (whole > 0 and best_sym) else (best_sym or str(whole))
        return f"{cup_display} cup"

    # Build "X cup + Y tbsp"
    if best_sym:
        cup_part = (str(whole) + best_sym + " cup") if whole > 0 else (best_sym + " cup")
    elif whole > 0:
        cup_part = f"{whole} cup"
    else:
        cup_part = None

    tbsp_part = f"{remainder_tbsp} tbsp"
    return f"{cup_part} + {tbsp_part}" if cup_part else tbsp_part


def format_quantity(amount: float, unit: str) -> str:
    """Format a quantity nicely, converting fractions where appropriate."""
    if amount is None:
        return unit.strip()
    if unit == "cup":
        return _format_cups(amount)
    # Common fraction display for non-cup units
    frac_map = {0.125: "⅛", 0.25: "¼", 0.5: "½", 0.75: "¾", 0.33: "⅓", 0.67: "⅔"}
    whole = int(amount)
    frac = amount - whole
    frac_str = ""
    for val, sym in frac_map.items():
        if abs(frac - val) < 0.04:
            frac_str = sym
            break
    if frac_str:
        display = (str(whole) + frac_str) if whole > 0 else frac_str
    else:
        display = str(round(amount, 2))
    return f"{display} {unit}".strip()


class IngredientGroup:
    """Accumulates amounts for a single named ingredient."""

    def __init__(self, name: str, aisle: str = ""):
        self.name = name
        self.aisle = aisle
        self.volume_base = 0.0   # fl_oz
        self.weight_base = 0.0   # oz
        self.count_amounts: list[tuple[float, str]] = []
        self.unknown_entries: list[dict] = []
        self.source_recipe_ids: list[int] = []
        self.recipe_contributions: list[dict] = []  # [{recipe_id, amount, unit}]

    def add(self, amount: float, unit: str, recipe_id: Optional[int] = None, original_name: str = ""):
        if recipe_id is not None:
            self.source_recipe_ids.append(recipe_id)
            self.recipe_contributions.append({"recipe_id": recipe_id, "amount": amount, "unit": unit, "name": original_name})
        family = get_unit_family(unit)
        base, _ = to_base_unit(amount, unit)
        if family == "volume":
            self.volume_base += base
        elif family == "weight":
            self.weight_base += base
        elif family == "count":
            self.count_amounts.append((amount, unit))
        else:
            self.unknown_entries.append({"amount": amount, "unit": unit})

    @property
    def has_conflict(self) -> bool:
        active = sum([
            1 if self.volume_base > 0 else 0,
            1 if self.weight_base > 0 else 0,
            1 if self.count_amounts else 0,
        ])
        return active > 1

    def to_display_items(self) -> list[dict]:
        """Return one or more display line items for this ingredient."""
        items = []
        if self.volume_base > 0:
            amt, unit = from_base_to_readable(self.volume_base, "volume")
            items.append({"amount": amt, "unit": unit, "display_quantity": format_quantity(amt, unit)})
        if self.weight_base > 0:
            amt, unit = from_base_to_readable(self.weight_base, "weight")
            items.append({"amount": amt, "unit": unit, "display_quantity": format_quantity(amt, unit)})
        for amt, unit in self.count_amounts:
            if amt is not None:
                items.append({"amount": amt, "unit": unit, "display_quantity": format_quantity(amt, unit)})
            else:
                items.append({"amount": None, "unit": unit, "display_quantity": unit.strip()})
        if not items:
            for e in self.unknown_entries:
                if e["amount"] is not None:
                    items.append({"amount": e["amount"], "unit": e["unit"],
                                   "display_quantity": format_quantity(e["amount"], e["unit"])})
                else:
                    items.append({"amount": None, "unit": e["unit"],
                                   "display_quantity": e["unit"].strip() or ""})
        return items

    def to_recipe_breakdown(self) -> list[dict]:
        """Return per-recipe contribution list for display (e.g. '1 cup → Tikka Masala')."""
        result = []
        for contrib in self.recipe_contributions:
            amt = contrib["amount"]
            unit = contrib["unit"]
            original = contrib.get("name", "")
            if amt and amt > 0:
                qty = format_quantity(amt, unit)
                display = f"{qty} {original}".strip() if original else qty
            elif unit:
                display = f"{unit.strip()} {original}".strip() if original else unit.strip()
            else:
                display = original
            result.append({"recipe_id": contrib["recipe_id"], "display_quantity": display})
        return result


# Words that indicate a form/presentation of an ingredient rather than a distinct item.
# These can appear at the end of a name and be stripped for grouping purposes.
# e.g. "garlic cloves" → "garlic", "rosemary sprigs" → "rosemary"
# e.g. "lemon zest" → "lemon", "lemon juice" → "lemon", "lemon peel" → "lemon"
_TRAILING_FORM_WORDS = frozenset({
    "clove", "cloves", "head", "heads", "stalk", "stalks",
    "sprig", "sprigs", "bunch", "bunches", "slice", "slices",
    "zest", "juice", "peel", "rind", "skin", "extract", "puree", "pulp",
    "powder", "flakes", "leaves", "leaf",
})

# Leading words that describe quality/state and are safe to strip.
# e.g. "fresh basil" → "basil", "frozen peas" → "peas"
# Color words (red, yellow) are intentionally excluded to avoid merging
# distinct ingredients like "red pepper" and "green pepper".
_LEADING_QUALITY_WORDS = frozenset({
    "fresh", "frozen", "baby", "whole", "organic", "raw",
    "large", "small", "medium",
    "juiced", "zested", "squeezed", "peeled", "grated", "minced",
    "chopped", "diced", "sliced", "crushed", "ground",
})

# Form words that appear before "of" in patterns like "zest of lemon" → "lemon".
_OF_FORM_WORDS = frozenset({
    "zest", "juice", "peel", "rind", "skin", "extract", "puree",
    "pulp", "powder", "slice", "slices",
})

# Explicit synonym table for common ingredient variants that map to the same
# shopping item.  Keys must be lowercase.  The value is the canonical display key.
_INGREDIENT_SYNONYMS: dict[str, str] = {
    # Onion varieties — all just mean "buy onions"
    "onions": "onion",
    "sweet onion": "onion",   "sweet onions": "onion",
    "yellow onion": "onion",  "yellow onions": "onion",
    "red onion": "onion",     "red onions": "onion",
    "white onion": "onion",   "white onions": "onion",
    "vidalia onion": "onion", "vidalia onions": "onion",
    "vidalia": "onion",
    "spanish onion": "onion", "spanish onions": "onion",
    "pearl onion": "onion",   "pearl onions": "onion",
    # Green onion / scallion — intentionally NOT merged with plain onion
    "scallion": "green onion", "scallions": "green onion",
    "spring onion": "green onion", "spring onions": "green onion",
    # Shallot plural
    "shallots": "shallot",
    # Bell pepper varieties — all the same vegetable to buy
    "bell peppers": "bell pepper",
    "red bell pepper": "bell pepper",  "red bell peppers": "bell pepper",
    "yellow bell pepper": "bell pepper", "yellow bell peppers": "bell pepper",
    "orange bell pepper": "bell pepper", "orange bell peppers": "bell pepper",
    "green bell pepper": "bell pepper", "green bell peppers": "bell pepper",
    # Common plurals
    "tomatoes": "tomato",
    "potatoes": "potato",
    "mushrooms": "mushroom",
    "lemons": "lemon",
    "limes": "lime",
    "eggs": "egg",
    "carrots": "carrot",
    "celery stalks": "celery",
    "garlic cloves": "garlic",  "garlic clove": "garlic",
}


def _canonical_key(name: str) -> str:
    """
    Normalize an ingredient name to a canonical grouping key.

    Handles:
    - Explicit synonyms (e.g. "yellow onion", "red onion" → "onion")
    - "X or Y" alternate forms → picks the shorter/simpler core form
      (e.g. "garlic paste or garlic" → "garlic")
    - Leading quality/state words (e.g. "fresh basil" → "basil")
    - Trailing form words (e.g. "garlic cloves" → "garlic")
    """
    key = name.lower().strip()

    # Check synonym map first (covers the most common cases directly)
    if key in _INGREDIENT_SYNONYMS:
        return _INGREDIENT_SYNONYMS[key]

    # Handle "X of Y" form patterns — e.g. "zest of lemon" → "lemon", "zest of 1 lemon" → "lemon"
    if " of " in key:
        of_idx = key.index(" of ")
        form_part = key[:of_idx].strip()
        ingredient_part = key[of_idx + 4:].strip()
        if form_part in _OF_FORM_WORDS:
            # Strip leading count ("1 lime" → "lime", "2 lemons" → "lemons")
            ingredient_part = re.sub(r'^\d+\s*', '', ingredient_part).strip()
            key = ingredient_part
            if key in _INGREDIENT_SYNONYMS:
                return _INGREDIENT_SYNONYMS[key]

    # Handle "X or Y" alternates — find the simplest shared core
    if " or " in key:
        parts = [p.strip() for p in key.split(" or ")]
        parts_by_len = sorted(parts, key=len)
        shortest = parts_by_len[0]
        # Use shortest only when it's a word-level prefix of all the others
        # e.g. "garlic" is a prefix of "garlic paste" → use "garlic"
        # but "beef" is NOT a prefix of "chicken" → keep first alternative
        if all(p.startswith(shortest) for p in parts_by_len[1:]):
            key = shortest
        else:
            key = parts[0]
        if key in _INGREDIENT_SYNONYMS:
            return _INGREDIENT_SYNONYMS[key]

    # Strip a single leading quality/state word (e.g. "fresh basil" → "basil")
    words = key.split()
    if len(words) > 1 and words[0] in _LEADING_QUALITY_WORDS:
        words = words[1:]
        key = " ".join(words)
        if key in _INGREDIENT_SYNONYMS:
            return _INGREDIENT_SYNONYMS[key]

    # Strip trailing form words (e.g. "garlic cloves" → "garlic")
    while len(words) > 1 and words[-1] in _TRAILING_FORM_WORDS:
        words.pop()

    return " ".join(words)


def aggregate_ingredients(ingredient_lists: list[list[dict]], recipe_ids: list[int]) -> list[dict]:
    """
    Takes multiple lists of ingredients (one per recipe) and aggregates them.
    Returns a flat list of shopping item dicts ready for DB insertion.

    Each ingredient dict expected: {name, amount, unit, aisle}
    """
    groups: dict[str, IngredientGroup] = {}

    for ing_list, recipe_id in zip(ingredient_lists, recipe_ids):
        for ing in ing_list:
            key = _canonical_key(ing["name"])
            if key not in groups:
                groups[key] = IngredientGroup(key, ing.get("aisle", ""))
            groups[key].add(ing.get("amount", 0), ing.get("unit", ""), recipe_id, ing.get("name", ""))

    result = []
    for key, group in groups.items():
        display_items = group.to_display_items()
        if not display_items:
            continue

        # Combine all display strings if conflict
        if group.has_conflict:
            display_quantity = " + ".join(i["display_quantity"] for i in display_items)
            unit = "mixed"
            amount = None
        else:
            display_quantity = display_items[0]["display_quantity"]
            unit = display_items[0]["unit"]
            amount = display_items[0]["amount"]

        result.append({
            "name": group.name,
            "display_quantity": display_quantity,
            "unit": unit,
            "amount": amount,
            "aisle": group.aisle,
            "has_unit_conflict": group.has_conflict,
            "source_recipe_ids": list(set(group.source_recipe_ids)),
            "conflict_details": display_items if group.has_conflict else [],
            "recipe_breakdown": group.to_recipe_breakdown(),
        })

    return result