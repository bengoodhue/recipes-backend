import httpx
import os

# Local ingredient → aisle map for common items
AISLE_MAP = {
    # Produce
    "apple": "Produce", "apples": "Produce", "banana": "Produce", "bananas": "Produce",
    "orange": "Produce", "oranges": "Produce", "lemon": "Produce", "lemons": "Produce",
    "lime": "Produce", "limes": "Produce", "grape": "Produce", "grapes": "Produce",
    "strawberry": "Produce", "strawberries": "Produce", "blueberry": "Produce",
    "blueberries": "Produce", "raspberry": "Produce", "raspberries": "Produce",
    "avocado": "Produce", "avocados": "Produce", "tomato": "Produce", "tomatoes": "Produce",
    "onion": "Produce", "onions": "Produce", "garlic": "Produce", "ginger": "Produce",
    "carrot": "Produce", "carrots": "Produce", "celery": "Produce", "broccoli": "Produce",
    "cauliflower": "Produce", "spinach": "Produce", "kale": "Produce", "lettuce": "Produce",
    "arugula": "Produce", "cabbage": "Produce", "cucumber": "Produce", "zucchini": "Produce",
    "squash": "Produce", "butternut squash": "Produce", "pumpkin": "Produce",
    "bell pepper": "Produce", "bell peppers": "Produce", "jalapeño": "Produce",
    "mushroom": "Produce", "mushrooms": "Produce", "potato": "Produce", "potatoes": "Produce",
    "sweet potato": "Produce", "sweet potatoes": "Produce", "corn": "Produce",
    "asparagus": "Produce", "green beans": "Produce", "peas": "Produce",
    "cilantro": "Produce", "parsley": "Produce", "basil": "Produce", "mint": "Produce",
    "rosemary": "Produce", "thyme": "Produce", "sage": "Produce", "dill": "Produce",
    "scallion": "Produce", "scallions": "Produce", "green onion": "Produce",
    "shallot": "Produce", "shallots": "Produce", "leek": "Produce", "leeks": "Produce",
    "mango": "Produce", "pineapple": "Produce", "peach": "Produce", "peaches": "Produce",
    "pear": "Produce", "pears": "Produce", "plum": "Produce", "plums": "Produce",
    "watermelon": "Produce", "cantaloupe": "Produce", "melon": "Produce",

    # Meat
    "chicken": "Meat", "chicken breast": "Meat", "chicken thigh": "Meat",
    "chicken thighs": "Meat", "chicken wings": "Meat", "ground chicken": "Meat",
    "beef": "Meat", "ground beef": "Meat", "steak": "Meat", "ribeye": "Meat",
    "sirloin": "Meat", "brisket": "Meat", "short ribs": "Meat", "pork": "Meat",
    "pork chop": "Meat", "pork chops": "Meat", "pork loin": "Meat",
    "bacon": "Meat", "ham": "Meat", "sausage": "Meat", "italian sausage": "Meat",
    "chorizo": "Meat", "turkey": "Meat", "ground turkey": "Meat", "lamb": "Meat",
    "veal": "Meat", "duck": "Meat", "prosciutto": "Meat", "pancetta": "Meat",
    "pepperoni": "Meat", "salami": "Meat",

    # Seafood
    "salmon": "Seafood", "tuna": "Seafood", "shrimp": "Seafood", "cod": "Seafood",
    "tilapia": "Seafood", "halibut": "Seafood", "sea bass": "Seafood",
    "mahi mahi": "Seafood", "crab": "Seafood", "lobster": "Seafood",
    "scallops": "Seafood", "clams": "Seafood", "mussels": "Seafood",
    "oysters": "Seafood", "anchovies": "Seafood", "sardines": "Seafood",
    "swordfish": "Seafood", "trout": "Seafood",

    # Dairy
    "milk": "Dairy", "whole milk": "Dairy", "skim milk": "Dairy", "oat milk": "Dairy",
    "almond milk": "Dairy", "butter": "Dairy", "cream": "Dairy", "heavy cream": "Dairy",
    "sour cream": "Dairy", "cream cheese": "Dairy", "yogurt": "Dairy",
    "greek yogurt": "Dairy", "cheese": "Dairy", "cheddar": "Dairy",
    "mozzarella": "Dairy", "parmesan": "Dairy", "feta": "Dairy", "brie": "Dairy",
    "gouda": "Dairy", "swiss cheese": "Dairy", "ricotta": "Dairy",
    "cottage cheese": "Dairy", "egg": "Dairy", "eggs": "Dairy",
    "half and half": "Dairy", "whipping cream": "Dairy",

    # Bakery
    "bread": "Bakery", "sourdough": "Bakery", "baguette": "Bakery",
    "sandwich bread": "Bakery", "whole wheat bread": "Bakery", "rolls": "Bakery",
    "bagel": "Bakery", "bagels": "Bakery", "english muffin": "Bakery",
    "pita": "Bakery", "tortilla": "Bakery", "tortillas": "Bakery",
    "croissant": "Bakery", "muffin": "Bakery", "muffins": "Bakery",

    # Frozen
    "frozen peas": "Frozen", "frozen corn": "Frozen", "frozen broccoli": "Frozen",
    "frozen spinach": "Frozen", "ice cream": "Frozen", "frozen pizza": "Frozen",
    "frozen vegetables": "Frozen", "edamame": "Frozen",

    # Canned
    "canned tomatoes": "Canned", "diced tomatoes": "Canned", "tomato paste": "Canned",
    "tomato sauce": "Canned", "crushed tomatoes": "Canned", "coconut milk": "Canned",
    "chicken broth": "Canned", "beef broth": "Canned", "vegetable broth": "Canned",
    "black beans": "Canned", "kidney beans": "Canned", "chickpeas": "Canned",
    "lentils": "Canned", "corn": "Canned", "tuna can": "Canned",

    # Baking
    "flour": "Baking", "all purpose flour": "Baking", "bread flour": "Baking",
    "sugar": "Baking", "brown sugar": "Baking", "powdered sugar": "Baking",
    "baking soda": "Baking", "baking powder": "Baking", "yeast": "Baking",
    "cocoa powder": "Baking", "chocolate chips": "Baking", "vanilla extract": "Baking",
    "cornstarch": "Baking", "oats": "Baking", "rolled oats": "Baking",
    "honey": "Baking", "maple syrup": "Baking", "molasses": "Baking",

    # Spices
    "salt": "Spices and Seasonings", "pepper": "Spices and Seasonings",
    "black pepper": "Spices and Seasonings", "cumin": "Spices and Seasonings",
    "paprika": "Spices and Seasonings", "chili powder": "Spices and Seasonings",
    "oregano": "Spices and Seasonings", "basil": "Spices and Seasonings",
    "thyme": "Spices and Seasonings", "cinnamon": "Spices and Seasonings",
    "turmeric": "Spices and Seasonings", "cayenne": "Spices and Seasonings",
    "garlic powder": "Spices and Seasonings", "onion powder": "Spices and Seasonings",
    "Italian seasoning": "Spices and Seasonings", "bay leaves": "Spices and Seasonings",
    "nutmeg": "Spices and Seasonings", "cardamom": "Spices and Seasonings",
    "coriander": "Spices and Seasonings", "red pepper flakes": "Spices and Seasonings",
    "smoked paprika": "Spices and Seasonings", "allspice": "Spices and Seasonings",

    # Condiments
    "ketchup": "Condiments", "mustard": "Condiments", "mayonnaise": "Condiments",
    "hot sauce": "Condiments", "worcestershire sauce": "Condiments",
    "soy sauce": "Condiments", "fish sauce": "Condiments", "oyster sauce": "Condiments",
    "hoisin sauce": "Condiments", "sriracha": "Condiments", "tahini": "Condiments",
    "peanut butter": "Condiments", "jam": "Condiments", "jelly": "Condiments",
    "salsa": "Condiments", "ranch": "Condiments", "bbq sauce": "Condiments",

    # Oil / Vinegar
    "olive oil": "Oil, Vinegar, Salad Dressing", "vegetable oil": "Oil, Vinegar, Salad Dressing",
    "canola oil": "Oil, Vinegar, Salad Dressing", "coconut oil": "Oil, Vinegar, Salad Dressing",
    "sesame oil": "Oil, Vinegar, Salad Dressing", "avocado oil": "Oil, Vinegar, Salad Dressing",
    "vinegar": "Oil, Vinegar, Salad Dressing", "apple cider vinegar": "Oil, Vinegar, Salad Dressing",
    "balsamic vinegar": "Oil, Vinegar, Salad Dressing", "rice vinegar": "Oil, Vinegar, Salad Dressing",
    "red wine vinegar": "Oil, Vinegar, Salad Dressing", "white wine vinegar": "Oil, Vinegar, Salad Dressing",

    # Pasta / Rice
    "pasta": "Pasta and Rice", "spaghetti": "Pasta and Rice", "penne": "Pasta and Rice",
    "fettuccine": "Pasta and Rice", "rigatoni": "Pasta and Rice", "linguine": "Pasta and Rice",
    "rice": "Pasta and Rice", "white rice": "Pasta and Rice", "brown rice": "Pasta and Rice",
    "jasmine rice": "Pasta and Rice", "basmati rice": "Pasta and Rice",
    "quinoa": "Pasta and Rice", "couscous": "Pasta and Rice", "orzo": "Pasta and Rice",
    "noodles": "Pasta and Rice", "ramen noodles": "Pasta and Rice",

    # Beverages
    "water": "Beverages", "sparkling water": "Beverages", "juice": "Beverages",
    "orange juice": "Beverages", "coffee": "Beverages", "tea": "Beverages",
    "wine": "Beverages", "beer": "Beverages", "soda": "Beverages",

    # Ethnic Foods
    "miso": "Ethnic Foods", "miso paste": "Ethnic Foods", "tahini": "Ethnic Foods",
    "harissa": "Ethnic Foods", "gochujang": "Ethnic Foods", "curry paste": "Ethnic Foods",
    "coconut cream": "Ethnic Foods", "rice paper": "Ethnic Foods",
    "aji amarillo": "Ethnic Foods", "aji amarillo paste": "Ethnic Foods",
}


def lookup_aisle_local(name: str) -> str | None:
    """Check local map first. Returns aisle string or None."""
    key = name.lower().strip()
    if key in AISLE_MAP:
        return AISLE_MAP[key]
    # Try partial match — if any key is contained in the item name
    for map_key, aisle in AISLE_MAP.items():
        if map_key in key:
            return aisle
    return None


async def lookup_aisle_spoonacular(name: str) -> str:
    """Call Spoonacular ingredient search to find aisle. Falls back to 'Other'."""
    api_key = os.getenv("SPOONACULAR_API_KEY", "").strip()
    if not api_key:
        return "Other"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://api.spoonacular.com/food/ingredients/search",
                params={"query": name, "number": 1, "apiKey": api_key},
                timeout=5.0,
            )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            if results:
                ingredient_id = results[0]["id"]
                # Get ingredient info including aisle
                info_resp = await client.get(
                    f"https://api.spoonacular.com/food/ingredients/{ingredient_id}/information",
                    params={"apiKey": api_key},
                    timeout=5.0,
                )
                info_resp.raise_for_status()
                info = info_resp.json()
                return info.get("aisle", "Other")
    except Exception:
        pass
    return "Other"


async def lookup_aisle(name: str) -> str:
    """Main lookup: local map first, Spoonacular fallback."""
    local = lookup_aisle_local(name)
    if local:
        return local
    return await lookup_aisle_spoonacular(name)