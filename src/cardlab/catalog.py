"""Build the version-level English card catalogue from TCGdex.

One row per printed version a collector would treat as a different card:
finish (normal / holo / reverse) x edition (1st Edition / Shadowless / Unlimited) x stamp x size.
Prices are joined later (prices.py) from the private daily snapshots.
"""
import re
from .sources import tcgdex

EXCLUDE_SERIES = {"Pokémon TCG Pocket"}          # digital-only cards
MAIN_STAMPS = {None, "1st-edition", "set-logo"}  # set-logo = EX-era reverse-holo stamp
RARITY_TIER = {  # rough pull-rate order within any era; raw rarity is kept as well
    "Common": 0, "Uncommon": 1, "Rare": 2, "Holo Rare": 3, "Rare Holo": 3,
    "Double rare": 4, "Holo Rare V": 4, "Holo Rare VMAX": 4, "Holo Rare VSTAR": 4, "Rare Holo LV.X": 4,
    "Rare PRIME": 4, "LEGEND": 4, "ACE SPEC Rare": 4, "Radiant Rare": 4, "Amazing Rare": 4,
    "Black White Rare": 4, "Ultra Rare": 5, "Illustration rare": 5, "Shiny rare": 5, "Shiny rare V": 5,
    "Shiny rare VMAX": 5, "Full Art Trainer": 5, "Classic Collection": 5, "Pikachu Rare": 5,
    "Futuristic Rare": 5, "Secret Rare": 6, "Special illustration rare": 6, "Shiny Ultra Rare": 6,
    "Hyper rare": 7, "Mega Hyper Rare": 7, "Crown": 7, "Promo": None, "None": None,
}
MECHANIC = [  # (flag, regex on card name)
    ("is_ex_old", r"\bex\b(?!.*\bex\b.*)"), ("is_gx", r"\bGX\b"), ("is_v", r"\bV$"), ("is_vmax", r"VMAX"),
    ("is_vstar", r"VSTAR"), ("is_lvx", r"LV\.?X"), ("is_prime", r"\bPrime\b"), ("is_break", r"BREAK"),
    ("is_mega", r"^(M |Mega )"), ("is_tag_team", r" & "), ("is_gold_star", r"☆|Star$"),
    ("is_dark", r"^Dark "), ("is_light", r"^Light "), ("is_owner", r"^[A-Z][\w.]+'s "), ("is_shining", r"^Shining "),
    ("is_delta", r"δ|Delta"), ("is_radiant", r"^Radiant "),
]


def _num(local_id):
    m = re.match(r"^\D*(\d+)", str(local_id))
    return int(m.group(1)) if m else None


def version_label(finish, subtype, stamps, size, foil=None):
    ed = "1st Edition" if "1st-edition" in stamps else ("Shadowless" if subtype == "shadowless" else None)
    if subtype in ("unlimited", "1999-2000-copyright", "no-e-reader"):
        ed = {"unlimited": "Unlimited", "1999-2000-copyright": "Unlimited (1999-2000 ©)", "no-e-reader": "No e-Reader"}[subtype]
    fin = {"normal": "", "holo": "Holo", "reverse": "Reverse Holo"}.get(finish, finish)
    parts = [p for p in (ed, fin) if p]
    extra = [s for s in stamps if s not in ("1st-edition", "set-logo")]
    if extra: parts.append("stamp:" + "+".join(extra))
    if foil: parts.append(f"({foil} pattern)")
    if size != "standard": parts.append(size)
    return " ".join(parts) or "Normal"


def build():
    sets = [s for s in tcgdex.sets() if s.get("serie", {}).get("name") not in EXCLUDE_SERIES]
    by_set = {s["id"]: s for s in sets}
    rows = []
    for c in tcgdex.cards(sets):
        s = by_set[c["set"]["id"]]
        off = (s.get("cardCount") or {}).get("official") or None
        n = _num(c["localId"])
        name = c["name"]
        base = dict(
            card_id=c["id"], set_id=s["id"], set_name=s["name"], serie=s["serie"]["name"],
            release_date=s.get("releaseDate"), set_official=off, set_total=(s.get("cardCount") or {}).get("total"),
            local_id=c["localId"], number=n, is_secret=int(bool(off and n and n > off)),
            name=name, category=c.get("category"), stage=c.get("stage"),
            dex=(c.get("dexId") or [None])[0], n_dex=len(c.get("dexId") or []),
            illustrator=(c.get("illustrator") or "").strip() or None,
            rarity=c.get("rarity"), rarity_tier=RARITY_TIER.get(c.get("rarity")),
            is_promo=int(c.get("rarity") == "Promo" or s["id"].endswith("p") or "Promo" in s["name"]),
            hp=c.get("hp"), regulation=c.get("regulationMark"),
            **{f: int(bool(re.search(p, name))) for f, p in MECHANIC},
        )
        variants = c.get("variants_detailed") or [{"type": None, "size": "standard"}]
        for v in variants:
            stamps = v.get("stamp") or []
            stamps = stamps if isinstance(stamps, list) else [stamps]
            tp = v.get("thirdParty") or {}
            row = dict(base)
            row.update(
                variant_id=v.get("variantId"), finish=v.get("type"), subtype=v.get("subtype"),
                stamps="+".join(stamps) or None, size=v.get("size") or "standard",
                first_edition=int("1st-edition" in stamps), shadowless=int(v.get("subtype") == "shadowless"),
                # 1999-2000 copyright / no e-Reader prints aren't priced separately by marketplaces
                # Poke Ball / Master Ball etc. pattern reverses are separate chase versions: kept, but
                # outside the main model until their marketplace products are mapped one by one
                main_version=int(all(st in MAIN_STAMPS for st in stamps) and (v.get("size") or "standard") == "standard"
                                 and v.get("subtype") not in ("1999-2000-copyright", "no-e-reader")
                                 and not str(v.get("foil") or "").endswith("ball")),
                foil=v.get("foil"),
                version=version_label(v.get("type"), v.get("subtype"), stamps, v.get("size") or "standard", v.get("foil")),
                tcgplayer_id=tp.get("tcgplayer"), cardmarket_id=tp.get("cardmarket"),
            )
            # holo-rare tier for vintage "Rare" cards that are actually holo
            if row["rarity"] == "Rare" and row["finish"] == "holo":
                row["rarity_tier"] = 3
            rows.append(row)
    # TCGdex sometimes lists the same variant twice, and its variantId isn't unique ('generated'),
    # so de-duplicate on the full printed signature and build the row key from it
    seen, out = set(), []
    for r in rows:
        sig = (r["finish"], r["subtype"], r["stamps"], r["size"], r["foil"])
        k = (r["card_id"],) + sig
        if k in seen:
            continue
        seen.add(k)
        r["row_id"] = r["card_id"] + ":" + "|".join(str(x or "") for x in sig)
        out.append(r)
    _fix_versions(out)
    return out


def _fix_versions(rows):
    """Era-specific clean-ups, applied per card.
    - EX era: reverse holos carry the set-logo stamp, but TCGdex sometimes types them 'normal'/'holo'.
      If a card has no 'reverse' row, a set-logo row becomes the reverse holo.
    - Other eras: set-logo marks stamped promo/box versions -> not a main version.
    - Patterned foils (cosmos, cracked ice, league...) are side versions when a plain row of the
      same finish exists."""
    by_card = {}
    for r in rows:
        by_card.setdefault(r["card_id"], []).append(r)
    for rs in by_card.values():
        has_rev = any(r["finish"] == "reverse" and "set-logo" not in (r["stamps"] or "") for r in rs)
        for r in rs:
            if "set-logo" in (r["stamps"] or ""):
                if r["serie"] == "EX" and r["finish"] != "reverse" and not has_rev:
                    r["finish"] = "reverse"; r["version"] = "Reverse Holo"; has_rev = True
                elif r["serie"] != "EX":
                    r["main_version"] = 0
                    r["version"] = (r["version"] + " stamp:set-logo").strip()
        plain = {(r["finish"]) for r in rs if not r["foil"] and r["main_version"]}
        for r in rs:
            if r["foil"] and r["finish"] in plain:
                r["main_version"] = 0
