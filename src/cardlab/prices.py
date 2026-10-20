"""Attach marketplace prices from the private daily snapshots to catalogue rows.

TCGplayer (USD, via TCGCSV): one row per productId x subTypeName. The subType is chosen
from the row's version, e.g. 1st Edition holo -> "1st Edition Holofoil", reverse -> "Reverse Holofoil".
Cardmarket (EUR): one product per card holding two price families. The base family is the
card's own printing; the "-holo" family is reverse holo (per the PokemonPriceTracker docs).
eur_robust = median of trend, 7-day and 30-day averages (single fields can be stale or floored).
If two non-reverse versions of a card share one Cardmarket product, the price goes to the
single non-1st-Edition version (Cardmarket lists 1st Edition separately); if that still
leaves more than one candidate, every version in the group is left blank and flagged.
"""
import pandas as pd
from .paths import SNAP


def latest(folder):
    files = sorted((SNAP / folder).glob("????-??-??.csv.gz"))
    if not files:
        raise FileNotFoundError(f"no snapshots in {SNAP / folder}")
    return files[-1]


def subtype_candidates(r):
    if r.finish == "reverse":
        return ["Reverse Holofoil"]
    holo = r.finish == "holo"
    if r.first_edition:
        return ["1st Edition Holofoil"] if holo else ["1st Edition", "1st Edition Normal"]
    if r.shadowless or r.subtype == "unlimited":
        return ["Unlimited Holofoil", "Holofoil"] if holo else ["Unlimited", "Normal"]
    return ["Holofoil", "Unlimited Holofoil"] if holo else ["Normal", "Unlimited"]


def add_missing_reverse(cat, tcg_file=None):
    """TCGdex misses reverse holos for whole sets (much of XY/BW). Where TCGplayer lists a
    'Reverse Holofoil' price for the card's product and the catalogue has no reverse row,
    add one (copied from the card's standard row) and mark it `synthetic_reverse=1`."""
    t = pd.read_csv(tcg_file or latest("tcgcsv"))
    rev_products = set(t.loc[t.subTypeName == "Reverse Holofoil", "productId"])
    have_rev = set(cat.loc[cat.finish == "reverse", "card_id"])
    base = cat[(cat.main_version == 1) & (cat.finish != "reverse") & (cat.first_edition == 0) & (cat.shadowless == 0)
               & cat.tcgplayer_id.notna() & ~cat.card_id.isin(have_rev)]
    base = base[base.tcgplayer_id.astype("int64").isin(rev_products)].drop_duplicates("card_id")
    new = base.copy()
    new["finish"], new["version"], new["foil"], new["stamps"] = "reverse", "Reverse Holo", None, None
    new["row_id"] = new.card_id + ":reverse||standard|"
    new["variant_id"] = "synthetic-reverse"
    out = pd.concat([cat.assign(synthetic_reverse=0), new.assign(synthetic_reverse=1)], ignore_index=True)
    return out


def attach(cat, tcg_file=None, cm_file=None):
    tcg_file = tcg_file or latest("tcgcsv")
    cm_file = cm_file or latest("cardmarket")
    t = pd.read_csv(tcg_file)
    tix = {(r.productId, r.subTypeName): r for r in t.itertuples()}
    cm = pd.read_csv(cm_file).set_index("idProduct")
    cat = cat.copy()
    # Cardmarket ambiguity: >1 non-reverse version of one card mapped to the same product
    nonrev = cat[(cat.finish != "reverse") & cat.cardmarket_id.notna() & (cat.main_version == 1)]
    # Cardmarket sells 1st Edition as a separate product and the id we hold is the non-1st one
    # (PokemonPriceTracker docs), so in a shared group the price goes to the single non-1st version.
    amb = set()
    for key, g in nonrev.groupby(["card_id", "cardmarket_id"]):
        if len(g) == 1:
            continue
        non1st = g[g.first_edition == 0]
        if len(non1st) == 1:
            amb.update(g[g.first_edition == 1].row_id)
        else:
            amb.update(g.row_id)
    # cards with a single non-reverse version: accept whichever non-reverse subtype TCGplayer lists
    single = cat[(cat.finish != "reverse") & (cat.main_version == 1)].groupby("card_id").size()
    single = set(single[single == 1].index)
    subtypes_of = t.groupby("productId").subTypeName.agg(list).to_dict()
    out = []
    for r in cat.itertuples():
        rec = dict(usd_market=None, usd_low=None, usd_mid=None, usd_subtype=None,
                   eur_trend=None, eur_avg7=None, eur_avg30=None, eur_low=None, eur_robust=None, eur_ambiguous=0)
        if pd.notna(r.tcgplayer_id):
            for st in subtype_candidates(r):
                hit = tix.get((int(r.tcgplayer_id), st))
                if hit is not None:
                    rec.update(usd_market=hit.marketPrice, usd_low=hit.lowPrice, usd_mid=hit.midPrice, usd_subtype=st)
                    break
            if rec["usd_subtype"] is None and r.card_id in single and r.finish != "reverse":
                alts = [st for st in subtypes_of.get(int(r.tcgplayer_id), []) if st in ("Holofoil", "Normal", "Unlimited Holofoil", "Unlimited")]
                if len(alts) == 1:
                    hit = tix[(int(r.tcgplayer_id), alts[0])]
                    rec.update(usd_market=hit.marketPrice, usd_low=hit.lowPrice, usd_mid=hit.midPrice, usd_subtype=alts[0] + " (only listing)")
        if pd.notna(r.cardmarket_id) and int(r.cardmarket_id) in cm.index:
            if r.row_id in amb:
                rec["eur_ambiguous"] = 1
            else:
                c = cm.loc[int(r.cardmarket_id)]
                sfx = "-holo" if r.finish == "reverse" else ""
                vals = {k: c.get(f"{k}{sfx}") for k in ("trend", "avg7", "avg30", "low")}
                vals = {k: (None if pd.isna(v) or v == 0 else float(v)) for k, v in vals.items()}
                rob = [v for v in (vals["trend"], vals["avg7"], vals["avg30"]) if v]
                rec.update(eur_trend=vals["trend"], eur_avg7=vals["avg7"], eur_avg30=vals["avg30"], eur_low=vals["low"],
                           eur_robust=float(pd.Series(rob).median()) if rob else None)
        out.append(rec)
    res = pd.concat([cat.reset_index(drop=True), pd.DataFrame(out)], axis=1)
    res["price_date_usd"] = tcg_file.name[:10]
    res["price_date_eur"] = cm_file.name[:10]
    return res
