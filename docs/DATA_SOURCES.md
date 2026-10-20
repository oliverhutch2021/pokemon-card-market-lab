# Data sources

Checked in October 2026. "Stored" means the data is kept privately for analysis only. Nothing raw is published here.

| Source | Access | Used for | Notes / terms |
|---|---|---|---|
| [TCGdex](https://tcgdex.dev) | Free, no key | Card catalogue: rarity, illustrator, set size, variants; TCGplayer USD and Cardmarket EUR snapshot prices | Open-source project; check its repo licence. No price history. |
| [Pokémon TCG API](https://pokemontcg.io) | Free key | Set release dates, artist, National Pokédex numbers | Its Cardmarket prices were found to be stale (last update Nov 2025), so they are not used. |
| [Cardmarket price guide & product list](https://www.cardmarket.com/Data/Download) | Public daily file | Background only: collected daily but used in no model | Mixes every card language, so it can't give English-only prices. Terms not stated, so the data is stored privately and not redistributed. |
| [TCGCSV](https://tcgcsv.com) | Free | Daily TCGplayer prices, including sealed | Its history archive has been withdrawn, so daily snapshots are kept privately instead. Fetch each file at most once a day. |
| [PokemonPriceTracker](https://www.pokemonpricetracker.com/api) | Paid key | Graded sale summaries by grade, sealed prices, 180-day history | Personal/educational plan. No redistribution of the data on any plan. Only derived values (medians, indices, charts) are shown. |
| [PokéAPI](https://pokeapi.co) | Free | Species traits: generation, legendary/mythical, evolution stage | |
| [Wikimedia pageviews](https://wikimedia.org/api/rest_v1/) | Free | Popularity signal per Pokémon | Monthly snapshot from GitHub Actions. Redirect titles are counted too, so every species gets a figure. |
| Frankfurter (ECB reference rates) | Free | USD/EUR/GBP daily rates | |
| [ONS](https://api.beta.ons.gov.uk/v1) / US BLS | Free | UK CPIH, US CPI | |
| PokeInvest pop reports | Free web pages (robots.txt allows `/pop-report/`) | Monthly PSA pop: total, PSA 10/9/8, gem rate | One request every 2 s, once a month. Only aggregates are published. |
| [PSA public API](https://www.psacard.com/publicapi/documentation) | Free account | Cert verification | No population data in the API. |
| eBay Browse API | Free developer account | Live UK listings (asking prices) | Sold-item data (Marketplace Insights) is a limited release and is not used. |

## Known gaps

- There's no free long-run price history. Lifecycle effects are estimated by comparing sets of different ages and from returns since launch RRP. Daily snapshots build a true history from October 2026 on.
- Print runs aren't published. Total graded, active listing counts, set size and era stand in for them, and are labelled that way.
- Individual sold listings aren't available on the plan used, so the price index uses daily averages rather than repeat sales.
