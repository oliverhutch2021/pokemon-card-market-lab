#!/usr/bin/env python3
"""Cross-check card-table USD prices against pokemontcg.io's TCGplayer prices.

pokemontcg.io keeps its own TCGplayer price per printing (normal, holofoil,
reverseHolofoil, 1stEditionHolofoil, unlimitedHolofoil, 1stEdition, unlimited), so
it checks both the product-id matching and the printing choice. Its prices can be a few
days older, so agreement means within +/-25% (or $1 for cheap cards).
Usage: python tools/check_prices.py   (needs the cached pokemontcg.io pages in data/cache)
"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pandas as pd
from cardlab.http import get_json
from cardlab.marketmap import norm, num_key
from cardlab.paths import BUILD

KEY = {("reverse", 0, 0): ["reverseHolofoil"], ("holo", 1, 0): ["1stEditionHolofoil"], ("normal", 1, 0): ["1stEdition"],
       ("holo", 0, 0): ["holofoil", "unlimitedHolofoil"], ("normal", 0, 0): ["normal", "unlimited"],
       ("holo", 0, 1): ["unlimitedHolofoil", "holofoil"], ("normal", 0, 1): ["unlimited", "normal"]}


def main():
    rows, page = [], 1
    while True:
        d = get_json(f"https://api.pokemontcg.io/v2/cards?page={page}&pageSize=250&select=id,name,number,set,tcgplayer,rarity,artist", max_age_days=60)
        if not d or not d.get("data"):
            break
        rows += d["data"]; page += 1
        if len(rows) >= d["totalCount"]:
            break
    ref = {}
    for c in rows:
        prices = (c.get("tcgplayer") or {}).get("prices") or {}
        ref[(norm(c["set"]["name"]), num_key(c["number"]))] = (c["name"], prices, c.get("artist"), c.get("rarity"))
    t = pd.read_parquet(BUILD / "card_table.parquet")
    t = t[(t.main_version == 1) & t.usd_market.notna()]
    out = []
    for r in t.itertuples():
        hit = ref.get((norm(r.set_name), num_key(r.local_id)))
        if not hit:
            continue
        name, prices, artist, rarity = hit
        keys = KEY.get((r.finish, int(r.first_edition), int(r.shadowless)), [])
        p = next((prices[k].get("market") for k in keys if k in prices and prices[k].get("market")), None)
        if p is None:
            continue
        diff = abs(r.usd_market - p)
        out.append(dict(row_id=r.row_id, era=r.serie, match=r.tcgplayer_match, ours=r.usd_market, ref=p,
                        agree=diff <= max(1.0, 0.25 * p), artist_same=(norm(artist or "") == norm(r.illustrator or "")) if artist else None))
    o = pd.DataFrame(out)
    print(f"compared {len(o):,} versions; agree within ±25%: {o.agree.mean():.1%}")
    print(o.groupby("match").agree.agg(["mean", "size"]).round(3).to_string())
    print(o.groupby("era").agree.agg(["mean", "size"]).round(3).to_string())
    print("artist agrees with pokemontcg.io:", f"{o.artist_same.dropna().mean():.1%}")
    o.to_csv(BUILD / "price_check.csv", index=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
