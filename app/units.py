"""
Ingredient aggregation logic.

Strategy (deliberately simple):
- One shopping item per recipe ingredient — amounts are never merged or
  converted across recipes. Combining quantities produced confusing results
  ("7 tbsp") and silent mis-merges, so each line stays traceable to its recipe.
- A canonical key (synonym table + light normalization) is used only for
  low-stakes concerns: sorting related items next to each other on the list
  (e.g. "Yellow Onion" beside "Onions") — never for merging them.
"""

import re

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
# Color words (red, yellow) are intentionally excluded to avoid grouping
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
    # Green onion / scallion — intentionally NOT grouped with plain onion
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


def canonical_key(name: str) -> str:
    """
    Normalize an ingredient name to a canonical grouping key.

    Used for sorting related items next to each other (and aisle lookup) —
    NOT for merging items, so a miss here costs almost nothing.

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


def aggregate_ingredients(
    ingredient_lists: list[list[dict]],
    recipe_ids: list[int],
    scales: list[float] | None = None,
) -> list[dict]:
    """
    Takes multiple lists of ingredients (one per recipe) and flattens them into
    shopping item dicts ready for DB insertion — one item per recipe ingredient,
    no merging. Items are ordered by canonical key so related ingredients from
    different recipes land next to each other on the list.

    `scales` carries each recipe's serving multiplier (e.g. 2.0 for a doubled
    recipe). Amounts are NOT multiplied — the original text stays as written and
    the scale is surfaced on the breakdown entry for the UI to badge (e.g. "2x").

    Each ingredient dict expected: {name, original?, amount?, unit?, display_quantity?, aisle?}
    """
    if scales is None:
        scales = [1.0] * len(recipe_ids)
    result = []
    for ing_list, recipe_id, scale in zip(ingredient_lists, recipe_ids, scales):
        for ing in ing_list:
            name = (ing.get("name") or "").strip()
            if not name:
                continue
            original = (ing.get("original") or "").strip()
            if not original:
                # Recipes imported before the raw line was stored — reconstruct
                original = " ".join(
                    p for p in [(ing.get("display_quantity") or "").strip(), name] if p
                )
            breakdown = {"recipe_id": recipe_id, "display_quantity": original}
            if scale and abs(scale - 1.0) > 1e-9:
                breakdown["scale"] = round(scale, 2)
            result.append({
                "name": name,
                "display_quantity": ing.get("display_quantity", ""),
                "unit": ing.get("unit", ""),
                "amount": ing.get("amount"),
                "aisle": ing.get("aisle", ""),
                "source_recipe_ids": [recipe_id],
                "recipe_breakdown": [breakdown],
            })

    result.sort(key=lambda item: (canonical_key(item["name"]), item["name"].lower()))
    return result
