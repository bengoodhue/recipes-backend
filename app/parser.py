import re
from fractions import Fraction

# Units we recognize
UNITS = [
    "cup", "cups", "c",
    "tablespoon", "tablespoons", "tbsp", "tbs",
    "teaspoon", "teaspoons", "tsp",
    "ounce", "ounces", "oz",
    "pound", "pounds", "lb", "lbs",
    "gram", "grams", "g",
    "kilogram", "kilograms", "kg",
    "liter", "liters", "l",
    "milliliter", "milliliters", "ml",
    "fluid ounce", "fluid ounces", "fl oz",
    "pint", "pints", "pt",
    "quart", "quarts", "qt",
    "gallon", "gallons", "gal",
    "slice", "slices",
    "piece", "pieces",
    "clove", "cloves",
    "can", "cans",
    "bunch", "bunches",
    "sprig", "sprigs",
    "stalk", "stalks",
    "head", "heads",
    "dash", "dashes",
    "pinch", "pinches",
    "handful", "handfuls",
    "small", "medium", "large",
    "package", "packages", "pkg",
]

# Sort by length descending so longer units match first (e.g. "fluid ounce" before "ounce")
UNITS_SORTED = sorted(UNITS, key=len, reverse=True)

UNIT_PATTERN = "|".join(re.escape(u) for u in UNITS_SORTED)


def parse_amount(text: str) -> tuple[float, str]:
    """
    Parse amount string like '1/2', '1 1/2', '2', '¼' into a float.
    Returns (amount, remaining_text).
    """
    # Replace unicode fractions
    unicode_fractions = {
        '¼': '1/4', '½': '1/2', '¾': '3/4',
        '⅓': '1/3', '⅔': '2/3', '⅛': '1/8', '⅜': '3/8',
        '⅝': '5/8', '⅞': '7/8',
    }
    for uf, replacement in unicode_fractions.items():
        text = text.replace(uf, replacement)

    text = text.strip()

    # Match patterns like: "1 1/2", "1/2", "2", "1.5"
    pattern = r'^(\d+\s+\d+/\d+|\d+/\d+|\d+\.?\d*)'
    match = re.match(pattern, text)
    if not match:
        return 0.0, text

    amount_str = match.group(1).strip()
    remaining = text[match.end():].strip()

    try:
        if ' ' in amount_str:
            # Mixed number like "1 1/2"
            parts = amount_str.split()
            amount = float(parts[0]) + float(Fraction(parts[1]))
        elif '/' in amount_str:
            amount = float(Fraction(amount_str))
        else:
            amount = float(amount_str)
    except (ValueError, ZeroDivisionError):
        return 0.0, text

    return amount, remaining


def parse_unit(text: str) -> tuple[str, str]:
    """
    Extract unit from the start of text.
    Returns (unit, remaining_text).
    """
    text = text.strip()
    pattern = rf'^({UNIT_PATTERN})\b'
    match = re.match(pattern, text, re.IGNORECASE)
    if match:
        unit = match.group(1).lower()
        remaining = text[match.end():].strip()
        # Normalize unit
        unit = normalize_unit(unit)
        return unit, remaining
    return "", text


def normalize_unit(unit: str) -> str:
    """Normalize unit to a standard form."""
    mapping = {
        "tablespoon": "tbsp", "tablespoons": "tbsp", "tbs": "tbsp",
        "teaspoon": "tsp", "teaspoons": "tsp",
        "ounce": "oz", "ounces": "oz",
        "pound": "lb", "pounds": "lb", "lbs": "lb",
        "gram": "g", "grams": "g",
        "kilogram": "kg", "kilograms": "kg",
        "liter": "l", "liters": "l",
        "milliliter": "ml", "milliliters": "ml",
        "fluid ounce": "fl oz", "fluid ounces": "fl oz",
        "cup": "cup", "cups": "cup", "c": "cup",
        "pint": "pt", "pints": "pt",
        "quart": "qt", "quarts": "qt",
        "gallon": "gal", "gallons": "gal",
        "clove": "clove", "cloves": "clove",
        "can": "can", "cans": "can",
        "bunch": "bunch", "bunches": "bunch",
        "slice": "slice", "slices": "slice",
        "piece": "piece", "pieces": "piece",
        "sprig": "sprig", "sprigs": "sprig",
        "stalk": "stalk", "stalks": "stalk",
        "head": "head", "heads": "head",
        "dash": "dash", "dashes": "dash",
        "pinch": "pinch", "pinches": "pinch",
        "handful": "handful", "handfuls": "handful",
        "package": "pkg", "packages": "pkg",
    }
    return mapping.get(unit.lower(), unit.lower())


def clean_ingredient_name(text: str) -> str:
    """
    Remove descriptive text after commas and clean up the ingredient name.
    e.g. "garlic, finely grated" -> "garlic"
    e.g. "eggs, lightly beaten" -> "eggs"
    But keep things like "salt and pepper" intact.
    """
    # Remove leading numbers/bullets
    text = re.sub(r'^[\d\.\-\*\•]+\s*', '', text).strip()

    # Split on comma and take first part (removes "finely chopped" etc)
    if ',' in text:
        parts = text.split(',')
        text = parts[0].strip()

    # Remove parenthetical notes
    text = re.sub(r'\(.*?\)', '', text).strip()

    # Remove trailing descriptors like "lightly beaten", "at room temperature"
    stop_words = [
        'lightly', 'finely', 'coarsely', 'roughly', 'thinly', 'thickly',
        'freshly', 'well', 'loosely', 'packed', 'heaping', 'leveled',
        'beaten', 'chopped', 'minced', 'diced', 'sliced', 'grated',
        'shredded', 'peeled', 'trimmed', 'halved', 'quartered', 'crushed',
        'toasted', 'roasted', 'cooked', 'softened', 'melted', 'divided',
        'optional', 'room temperature', 'at room temperature',
    ]
    for word in stop_words:
        text = re.sub(rf'\b{word}\b', '', text, flags=re.IGNORECASE).strip()

    # Clean up extra spaces
    text = re.sub(r'\s+', ' ', text).strip()

    return text


def parse_ingredient_line(line: str) -> dict | None:
    """
    Parse a single ingredient line into amount, unit, name.
    Returns None if the line is empty or a section header.
    """
    line = line.strip()
    if not line:
        return None

    # Skip lines that look like section headers (no numbers, all caps or ends with :)
    if line.endswith(':') or (line.isupper() and len(line) > 3):
        return None

    # Try to parse amount
    amount, remaining = parse_amount(line)

    # Try to parse unit
    unit, remaining = parse_unit(remaining)

    # Clean up the name
    name = clean_ingredient_name(remaining)

    if not name:
        return None

    # Build display quantity
    if amount > 0:
        display = format_amount(amount)
        if unit:
            display = f"{display} {unit}"
    else:
        display = ""

    return {
        "name": name,
        "amount": amount if amount > 0 else None,
        "unit": unit or "",
        "display_quantity": display,
    }


def format_amount(amount: float) -> str:
    """Format a float amount nicely, using fractions where appropriate."""
    fraction_map = {
        0.25: "¼", 0.5: "½", 0.75: "¾",
        0.33: "⅓", 0.67: "⅔", 0.125: "⅛",
    }

    whole = int(amount)
    remainder = round(amount - whole, 3)

    frac_str = fraction_map.get(round(remainder, 2), "")

    if whole == 0 and frac_str:
        return frac_str
    elif whole > 0 and frac_str:
        return f"{whole}{frac_str}"
    elif whole > 0:
        return str(whole)
    else:
        return str(amount)


def parse_ingredient_block(text: str) -> list[dict]:
    """
    Parse a multi-line ingredient block.
    Returns list of parsed ingredient dicts.
    """
    lines = text.strip().split('\n')
    results = []
    for line in lines:
        parsed = parse_ingredient_line(line)
        if parsed:
            results.append(parsed)
    return results