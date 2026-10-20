"""TCGdex English catalogue: every set and card, with variants and marketplace ids."""
from concurrent.futures import ThreadPoolExecutor
from ..http import get_json

BASE = "https://api.tcgdex.net/v2/en"


def sets():
    out = []
    for s in get_json(f"{BASE}/sets"):
        d = get_json(f"{BASE}/sets/{s['id']}")
        if d: out.append(d)
    return out


def cards(set_details, workers=6):
    ids = [c["id"] for s in set_details for c in s.get("cards", [])]
    with ThreadPoolExecutor(workers) as ex:
        return [c for c in ex.map(lambda i: get_json(f"{BASE}/cards/{i}", pause=0.05), ids) if c]
