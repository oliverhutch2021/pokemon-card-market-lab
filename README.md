# Pokémon Card Market Lab

An analysis project on the English Pokémon TCG market (1999–2026), seen from a UK buyer's side, with prices in £.

| Module | Question |
|---|---|
| Card value model | What should a card be worth, given its rarity, set, age, Pokémon popularity, artist and supply? It is tested on 2026 sets the model never saw. Raw near-mint and PSA 10 are modelled separately. |
| Price lifecycle | How do prices typically fall after release and recover once a set is out of print? What do reprints do? |
| Grading calculator | Is a card worth sending to PSA? It uses the expected value across the whole grade distribution, minus fees, shipping, VAT and the cost of waiting. |
| Cross-market gaps | US (TCGplayer) vs EU (Cardmarket) prices as a landed cost in £, and how much FX markups change the answer. |
| Sealed returns | Returns, volatility and worst drawdowns of sealed products, compared with UK inflation. |
| Supply & pop growth | How fast new PSA 10s appear, and whether a low pop is really scarce. |
| PSA 10 price index | A hedonic £ index of the PSA 10 market. |
| Backtest & risk flags | Do "cheap for its scarcity" picks catch up? Flags for suspicious sales and PSA cert checks. |

**Status:** step 2 (card table) is built; see [docs/CARD_TABLE.md](docs/CARD_TABLE.md).

See [docs/PLAN.md](docs/PLAN.md) for the method and [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md) for the data sources and their terms.

## What is not in this repo

- **No raw data.** Prices come from third-party sources whose terms forbid redistribution, so the repo holds code, method notes and small derived summaries only. Running the pipeline needs your own access to each source (see DATA_SOURCES).
- **No card images.** Card art is copyright of its owners.
- **No API keys.** Keys are read from environment variables at run time.

## Setup

```sh
git clone <this repo> && cd pokemon-card-market-lab
sh tools/setup.sh          # turns on the publish guard
pip install -r requirements.txt
```

`tools/guard.py` runs on every commit and push, and again in CI. It blocks:

- secrets
- personal contact details
- raw API responses
- data files outside `data/derived/`
- images outside `docs/figures/`
- anything over 1 MB

## Disclaimer

This is an independent data analysis project and **not investment or financial advice**. Collectibles can lose value and are illiquid. Pokémon and all related names are trademarks of Nintendo, Creatures Inc. and GAME FREAK inc. This project is not affiliated with or endorsed by them, The Pokémon Company, PSA, TCGplayer, Cardmarket, eBay or any data provider.

## Licence

Code is released under the MIT licence (see `LICENSE`). Third-party data is not covered by it and stays under its providers' terms.
