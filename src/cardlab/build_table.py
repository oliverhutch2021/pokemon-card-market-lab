"""Step 2: build the version-level card table.

    python -m cardlab.build_table

Output (private data repo, never the public repo):
    build/card_table.parquet   one row per English card version
    build/card_table_report.json   coverage and match statistics
Inputs: TCGdex (cached), latest TCGCSV + Cardmarket snapshots, latest monthly pop snapshot,
species table (build/species.csv, from cardlab.sources.species).
"""
import json, sys
import pandas as pd
from . import catalog, marketmap, prices, pop
from .sources import tcgdex
from .paths import BUILD, SNAP


def latest_products(folder, pattern):
    f = sorted((SNAP / folder / "products").glob(pattern))
    if not f:
        raise FileNotFoundError(f"no product lists in {SNAP / folder / 'products'}")
    return f[-1]


def main():
    cat = pd.DataFrame(catalog.build())
    cat, tcg_sets = marketmap.tcgplayer_fill(cat, pd.read_csv(latest_products("tcgcsv", "*.csv.gz")))
    cat, cm_sets = marketmap.cardmarket_fill(cat, pd.read_csv(latest_products("cardmarket", "*_singles.csv.gz")),
                                             tcgdex.cards(tcgdex.sets()))
    cat = prices.add_missing_reverse(cat)
    df = prices.attach(cat)
    df, pop_status, pop_month = pop.attach(df)

    sp = pd.read_csv(BUILD / "species.csv")
    df = df.merge(sp.add_prefix("sp_").rename(columns={"sp_dex": "dex"}), on="dex", how="left")
    # how often TPC prints each species (main versions, distinct cards) - a supply/popularity signal
    prints = df[df.main_version == 1].drop_duplicates("card_id").groupby("dex").size().rename("species_card_count")
    df = df.merge(prints, left_on="dex", right_index=True, how="left")
    # Cardmarket's guide averages every language and condition, so it can sit far from a US
    # near-mint price; flag extreme gaps rather than trust them (cards >= $5 only)
    ratio = df.eur_robust / df.usd_market
    df["eur_suspect"] = ((df.usd_market >= 5) & ((ratio < 0.2) | (ratio > 5))).astype(int)
    df["release_date"] = pd.to_datetime(df.release_date)
    df["set_age_days"] = (pd.Timestamp(df.price_date_usd.iloc[0]) - df.release_date).dt.days

    m = df[df.main_version == 1]
    report = {
        "rows": len(df), "main_versions": len(m), "cards": int(df.card_id.nunique()), "sets": int(df.set_id.nunique()),
        "synthetic_reverse_rows": int(df.synthetic_reverse.sum()),
        "usd_price_share_main": round(float(m.usd_market.notna().mean()), 3),
        "eur_price_share_main": round(float(m.eur_robust.notna().mean()), 3),
        "pop_match_share_main": round(float(m.psa_total.notna().mean()), 3),
        "eur_suspect_rows": int(df.eur_suspect.sum()),
        "pop_rows": pop_status, "pop_month": pop_month,
        "tcgplayer_match": df.tcgplayer_match.value_counts(dropna=False).rename(index=str).to_dict(),
        "cardmarket_match": df.cardmarket_match.value_counts(dropna=False).rename(index=str).to_dict(),
        "price_date_usd": df.price_date_usd.iloc[0], "price_date_eur": df.price_date_eur.iloc[0],
        "by_serie": m.groupby("serie").agg(n=("row_id", "size"), usd=("usd_market", lambda x: round(x.notna().mean(), 2)),
                                           eur=("eur_robust", lambda x: round(x.notna().mean(), 2)),
                                           pop=("psa_total", lambda x: round(x.notna().mean(), 2))).to_dict("index"),
    }
    df.to_parquet(BUILD / "card_table.parquet", index=False)
    (BUILD / "card_table_report.json").write_text(json.dumps(report, indent=1, default=str))
    print(json.dumps({k: v for k, v in report.items() if k != "by_serie"}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
