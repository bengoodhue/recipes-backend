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
            return round(amount / 128, 2), "gallon"
        elif amount >= 32:
            return round(amount / 32, 2), "quart"
        elif amount >= 8:
            return round(amount / 8, 2), "cup"
        elif amount >= 0.5:
            return round(amount / 0.5, 2), "tbsp"
        else:
            return round(amount / (1 / 6), 2), "tsp"
    elif family == "weight":
        if amount >= 16:
            return round(amount / 16, 2), "lb"
        else:
            return round(amount, 2), "oz"
    return round(amount, 2), ""


def format_quantity(amount: float, unit: str) -> str:
    """Format a quantity nicely, converting fractions where appropriate."""
    if amount is None:
        return unit.strip()
    # Common fraction display
    frac_map = {0.25: "¼", 0.5: "½", 0.75: "¾", 0.33: "⅓", 0.67: "⅔"}
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

    def add(self, amount: float, unit: str, recipe_id: Optional[int] = None):
        if recipe_id is not None:
            self.source_recipe_ids.append(recipe_id)
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


def aggregate_ingredients(ingredient_lists: list[list[dict]], recipe_ids: list[int]) -> list[dict]:
    """
    Takes multiple lists of ingredients (one per recipe) and aggregates them.
    Returns a flat list of shopping item dicts ready for DB insertion.

    Each ingredient dict expected: {name, amount, unit, aisle}
    """
    groups: dict[str, IngredientGroup] = {}

    for ing_list, recipe_id in zip(ingredient_lists, recipe_ids):
        for ing in ing_list:
            key = ing["name"].lower().strip()
            if key not in groups:
                groups[key] = IngredientGroup(ing["name"], ing.get("aisle", ""))
            groups[key].add(ing.get("amount", 0), ing.get("unit", ""), recipe_id)

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
            "source_recipe_ids_json": str(list(set(group.source_recipe_ids))),
            "conflict_details_json": str(display_items) if group.has_conflict else "[]",
        })

    return result