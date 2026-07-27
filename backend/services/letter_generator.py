"""
Generates the letter order for a game. Every game uses all 26 letters,
shuffled once at game start, each appearing exactly once - no repeats,
per spec.
"""
import random

ALL_LETTERS = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")


def shuffle_letters() -> list[str]:
    """Return all 26 letters in a fresh random order."""
    letters = ALL_LETTERS.copy()
    random.shuffle(letters)
    return letters
