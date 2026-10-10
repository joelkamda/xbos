"""Explicit WND restaurant operational policy; no neutral business authority.

Selected ONLY when an active Restaurant pack and an effective WND-owned
operating-context declaration both exist. No tenant-name/ID inference.
"""
from __future__ import annotations
from typing import Optional

FAMILY_BAR = "bar"
FAMILY_KITCHEN = "kitchen"
FAMILY_OTHER = "other"

def _lower(value: object) -> str:
    return str(value or "").strip().lower()

def _category_family(category_name: Optional[str]) -> Optional[str]:
    text = _lower(category_name)
    if text == "drinks":
        return FAMILY_BAR
    if text == "food":
        return FAMILY_KITCHEN
    if text == "others":
        return FAMILY_OTHER
    return None

KITCHEN_ROUTE_NAMES = frozenset({
    "MAIN DISH", "BREAKFAST", "COMPLEMENT", "DESERT", "DESSERT",
    "HOT DRINKS", "FOOD", "KITCHEN", "PREP",
})
NON_KITCHEN_ROUTE_NAMES = frozenset({
    "BEER", "SOFT DRINKS", "ENERGY DRINKS", "WHISKY", "WHISKEY",
    "WINE", "CHAMPAGNE", "LIQUOR", "CIGARETTES", "SHISHA",
})

FOOD_KEYWORDS = {
    "beans",
    "eru",
    "ndole",
    "achu",
    "koki",
    "cornchaff",
    "chicken",
    "goat",
    "pork",
    "fish",
    "snail",
    "snails",
    "eggs",
    "salade",
    "salad",
    "breakfast",
    "okro",
    "egussi",
    "egusi",
    "kati",
    "gambas",
    "poulet",
    "complement",
    "plantain",
    "rice",
    "fufu",
    "gari",
    "towel",  # WND menu spelling / item naming context
}

DRINK_KEYWORDS = {
    "beer",
    "guinness",
    "export",
    "castel",
    "castle",
    "mutzig",
    "heineken",
    "kadji",
    "skoll",
    "dopple",
    "booster",
    "malta",
    "smooth",
    "origin",
    "ice",
    "red bull",
    "fanta",
    "coca",
    "coke",
    "sprite",
    "top",
    "jus",
    "juice",
    "whiskey",
    "whisky",
    "vodka",
    "jack daniels",
    "monkey shoulder",
    "champagne",
    "ruinart",
}

WINE_KEYWORDS = {
    "wine",
    "domaine",
    "chenet",
    "calvet",
    "sauvignon",
    "merlot",
    "cabernet",
    "sandara",
    "ballart",
    "oliver",
    "eschenauer",
    "chateau",
    "château",
    "bordeaux",
    "rose",
    "rosé",
}


def _name_suggests_family(name: str) -> Optional[str]:
    text = _lower(name)

    # Food gets priority to avoid "White Beans" being confused with white wine.
    if any(k in text for k in FOOD_KEYWORDS):
        return FAMILY_KITCHEN

    if any(k in text for k in DRINK_KEYWORDS):
        return FAMILY_BAR

    return None


def _subcategory_score(name: str, subcategory_name: Optional[str]) -> int:
    """
    Helps choose between multiple COMMERCE subcategory mappings.

    Example:
    - White Beans mapped to Main Dish + Wine
      => food heuristic wins category first.
    - RED BULL mapped to Beer + Wine
      => both are Drinks, but Wine is penalized because Red Bull is not wine.
    """

    text = _lower(name)
    sub = _lower(subcategory_name)

    if not sub:
        return 0

    score = 0

    if sub == "main dish":
        if any(k in text for k in FOOD_KEYWORDS):
            score += 20

    if sub == "breakfast":
        if any(k in text for k in {"egg", "eggs", "breakfast", "salade", "salad"}):
            score += 20

    if sub == "complement":
        if any(k in text for k in {"complement", "plantain", "rice", "fufu", "gari"}):
            score += 20

    if sub == "beer":
        if any(k in text for k in {
            "beer",
            "guinness",
            "export",
            "castel",
            "castle",
            "mutzig",
            "heineken",
            "kadji",
            "skoll",
            "dopple",
            "booster",
            "malta",
            "smooth",
            "origin",
            "ice",
        }):
            score += 20

        # Not perfect, but safer than Wine for common bar soft/energy drinks
        # if the product was wrongly mapped to Beer + Wine.
        if "red bull" in text:
            score += 8

    if sub == "soft drinks":
        if any(k in text for k in {"red bull", "fanta", "coke", "coca", "sprite", "top"}):
            score += 25

    if sub == "wine":
        if any(k in text for k in WINE_KEYWORDS):
            score += 20
        else:
            score -= 10

    if sub == "whiskey":
        if any(k in text for k in {"whiskey", "whisky", "jack daniels", "monkey shoulder"}):
            score += 20

    if sub == "champagne":
        if any(k in text for k in {"champagne", "ruinart"}):
            score += 20

    if sub == "juice":
        if any(k in text for k in {"juice", "jus"}):
            score += 20

    return score



class WndOperationalPolicy:
    """WND-specific behavior extracted from the accepted shared runtime."""

    @staticmethod
    def category_family(category_name: str | None) -> str | None:
        return _category_family(category_name)

    @staticmethod
    def name_family(name: str) -> str | None:
        return _name_suggests_family(name)

    @staticmethod
    def subcategory_score(name: str, subcategory: str | None) -> int:
        return _subcategory_score(name, subcategory)

    @staticmethod
    def negative_stock(family: str) -> bool:
        return family == FAMILY_KITCHEN

    @staticmethod
    def disable_when_out(family: str, stock_tracked: bool) -> bool:
        return bool(stock_tracked and family in {FAMILY_BAR, FAMILY_OTHER})

    @staticmethod
    def fulfillment(names: set[str], category: str, subcategory: str, status: str) -> dict:
        explicit_non_kitchen = bool(names.intersection(NON_KITCHEN_ROUTE_NAMES))
        kitchen = bool(names.intersection(KITCHEN_ROUTE_NAMES)
                       or category in KITCHEN_ROUTE_NAMES
                       or subcategory in KITCHEN_ROUTE_NAMES)
        required = bool(kitchen and not explicit_non_kitchen)
        return {
            "requires_fulfillment": required,
            "requires_preparation": required,
            "fulfillment_queue": "kitchen" if required else None,
            "fulfillment_station": "kitchen" if required else None,
            "fulfillment_status": status if required or status != "waiting" else None,
            "show_queue_qualifier": required,
        }

WND_POLICY = WndOperationalPolicy()
