# Card table (step 2)

Built by `python -m cardlab.build_table` and saved to the **private** data repo (`build/card_table.parquet`). It isn't published, because it contains third-party prices.

**One row per card version** a collector treats as a different card. 1st Edition, Shadowless, Unlimited, Reverse Holo, Holo, stamped and patterned versions each get their own row. `main_version = 1` marks the versions used for modelling: standard size, no promo or player stamps, no Poké Ball / Master Ball patterns. Pattern versions are kept but stay out of the main set until their own marketplace products are mapped.

## How each part is made

| Part | Source | Method |
|---|---|---|
| Cards, sets, rarity, artist, Pokédex no., variants | TCGdex | Every English set except TCG Pocket (which is digital). Release date is the set's. |
| Missing reverse holos | TCGplayer via TCGCSV | TCGdex misses reverse holos for much of XY and BW. Where TCGplayer prices a "Reverse Holofoil" for the card's product, a reverse row is added and flagged `synthetic_reverse = 1`. |
| TCGplayer product id | TCGdex, else TCGCSV | Where TCGdex has none, the set is mapped to its TCGplayer group(s) and matched on printed number plus name (`tcgplayer_match` says which way). |
| Cardmarket product id | TCGdex, else Cardmarket product list | The set is mapped to a Cardmarket expansion by card-name overlap, then matched on name, using attack names when Cardmarket lists duplicates (`cardmarket_match`). |
| `usd_market`, `usd_low`, `usd_mid` | TCGCSV daily snapshot | The price line (`usd_subtype`) is chosen from the version, e.g. 1st Edition holo gives "1st Edition Holofoil". |
| `eur_trend`, `eur_avg7`, `eur_avg30`, `eur_robust` | Cardmarket daily price guide | Reverse holo uses Cardmarket's "-holo" price family. `eur_robust` is the median of trend, 7-day and 30-day averages. If versions share one product and can't be split, the price is left blank (`eur_ambiguous = 1`). |
| `psa_total`, `psa10`, `psa9`, `psa8`, `gem_rate` | PokeInvest monthly pop snapshot | Matched on set, printed number, the start of the name and the bracket tag ([1st Edition], [Shadowless], [Reverse Holo]...). Unmatched rows stay blank; nothing is guessed. `gem_rate` = PSA 10 ÷ total graded. |
| `sp_*` species traits | PokéAPI | Generation, legendary/mythical/baby, evolution stage, starter line, pseudo-legendary line, Eeveelution, most-graded species. |
| `sp_reddit2019_votes`, `sp_poty2020_votes` | 2019 r/pokemon survey; official Pokémon of the Year 2020 | Raw vote counts. Blank where the species wasn't in the poll or its regional top 30. |
| `sp_wiki_views_24m` | Wikipedia pageviews | Total over the last 24 months, from the monthly snapshot. Blank until the first snapshot runs. |
| `species_card_count` | This table | Number of distinct main cards printed for the species: how often TPC prints it. |
| `set_age_days` | | Price date minus set release date. |

## Coverage (first build, 20 Oct 2026)

`build/card_table_report.json` has the full breakdown by era.

- **Size:** 38,418 rows, 35,326 of them main versions, covering 21,255 cards in 201 sets.
- **US price:** 97.8% of main versions.
- **EU price:** 85.7%. It's weakest for SM, XY and EX, and for WOTC 1st Editions, which Cardmarket sells as separate products not yet mapped.
- **PSA pop:** 88.6% of main versions have a row. 96.6% of PokeInvest's English pop rows found a match, covering about 16.5M graded cards. Most cards without a pop row have simply never been graded.
- **Known gap:** PokeInvest has no 1st Edition rows for Neo Genesis.
- **EU prices need care.** Cardmarket's guide averages every language and condition, so for older eras it runs far below the US near-mint price. The median EUR/USD ratio is about 0.25–0.3 for DP, Platinum and HGSS, against 0.8–1.0 for modern sets. Cards of $5 or more whose EUR/USD ratio is outside 0.2–5× are flagged `eur_suspect = 1`. Module 4 (cross-market) will deal with this before any gap is reported.

## Checks

- **Pop:** 2,695 of 2,744 versions agree with the earlier slab project's pop data (98.2%). The rest are small revisions or mistakes in the old data; the sampled ones were checked by hand.
- **Prices:** checked against pokemontcg.io's TCGplayer prices, which come from a separate pipeline (`tools/check_prices.py`). 99.3% of 29,070 versions agree within ±25%, both for ids from TCGdex (99.2%) and for ids recovered here (99.4%). The artist agrees on 99.2%.
