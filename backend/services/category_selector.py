"""
Selects categories for a round. Each round randomly picks
categories_per_round_min..categories_per_round_max categories (default
4-5) from the larger pool below, per spec, rather than always using the
same fixed four - keeps rounds varied and replayable.
"""
import random

from config import settings

CATEGORY_POOL = [
    "Name", "Place", "Animal", "Thing", "Food", "Profession", "Movie",
    "Brand", "Plant", "Sport", "Vehicle", "Instrument", "Color",
    "Celebrity", "Superhero", "Book", "Technology", "Country", "Bird",
    "Insect",
]


def select_categories() -> list[str]:
    count = random.randint(settings.categories_per_round_min, settings.categories_per_round_max)
    return random.sample(CATEGORY_POOL, count)
