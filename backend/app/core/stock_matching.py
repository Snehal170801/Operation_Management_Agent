"""Matching what someone asked for ("10 laptops", "AC", "tab") to a stock row ("Laptop", "Air conditioner
1.5 ton", "Tablet"). Pure functions, no DB or AI.

The rule is deliberately cautious: a wrong match would silently hand out the wrong item, whereas a
miss only sends the request to suppliers. So only *equivalent* descriptions match -- same words after
tidying case, plurals, punctuation, word order and a few well-known abbreviations. A request that is
less specific than the stock row ("fan" vs "Ceiling fan") or more specific ("Dell laptop" vs "Laptop")
does NOT match here; the caller may ask the AI, which is held to the same standard.
"""

import re

_NOISE = frozenset({"a", "an", "the", "of", "for", "new", "pcs", "pc's", "piece", "pieces", "unit", "units", "nos", "no"})

# Whole-description abbreviations (normalised, order-independent). Only unambiguous ones.
_SYNONYMS = {
    ("ac",): ("air", "conditioner"),
    ("aircon",): ("air", "conditioner"),
    ("airconditioner",): ("air", "conditioner"),
    ("tab",): ("tablet",),
    ("phone",): ("mobile", "phone"),
    ("mobile",): ("mobile", "phone"),
    ("smartphone",): ("mobile", "phone"),
    ("cellphone",): ("mobile", "phone"),
    ("cctv",): ("cctv", "camera"),
    ("fridge",): ("refrigerator",),
    ("projecter",): ("projector",),
}


def _singular(word: str) -> str:
    if len(word) <= 3 or word.endswith("ss") or word.endswith("us"):
        return word
    if word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith(("ches", "shes", "xes", "sses")):
        return word[:-2]
    if word.endswith("s"):
        return word[:-1]
    return word


def normalize(description: str) -> tuple[str, ...]:
    """Order-independent, case/plural/punctuation-insensitive form of a description."""
    text = re.sub(r"^\s*\d+\s*(?:x|pcs|pieces?|units?|nos)\b\.?", "", (description or "").lower())
    words = re.findall(r"[a-z0-9.]+", text.replace("-", " "))
    words = [_singular(w.strip(".")) for w in words if w.strip(".") and w not in _NOISE]
    key = tuple(sorted(words))
    return tuple(sorted(_SYNONYMS.get(key, key)))


def match_exact(description: str, stock_names: list[str]) -> str | None:
    """The stock item that is the same product as `description`, or None (also None if two stock
    rows normalise identically, since then we cannot tell which one is meant)."""
    wanted = normalize(description)
    if not wanted:
        return None
    hits = [name for name in stock_names if normalize(name) == wanted]
    return hits[0] if len(hits) == 1 else None
