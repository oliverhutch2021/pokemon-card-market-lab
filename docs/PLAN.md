# Plan

All prices are in GBP. USD is converted at a fixed reference rate unless stated otherwise. Every number on the dashboard comes with a plain-English note on how it was made.

## Build order

1. **Snapshots.** Save TCGdex, Cardmarket and TCGCSV prices daily, and PSA pop counts monthly, to private storage.
2. **Card table.** One row per English card version (1st Edition / Shadowless / Unlimited / Reverse Holo / Holo kept separate). Fields: set, release date, rarity, artist, Pokédex number, species traits, popularity signals, pop by grade, and US and EU prices.
3. **Raw value model.** Target: log near-mint price. Train on sets released before 2025, tune on 2025 sets, test on 2026 sets. Baselines: rarity median and linear regression. Main models: a regularised linear model and gradient boosting, with per-card driver breakdowns and prediction ranges.
4. **PSA 10 model.** Target: log PSA 10 price, or the PSA 10 / raw premium. Adds pop, gem rate and total graded.
5. **Backtest.** Check whether cards flagged "cheap for scarcity" or "lagging re-rated siblings" closed the gap over the next 30, 90 and 180 days.
6. **PSA 10 price index.** A hedonic time-dummy index on daily sale averages.
7. **Modules:**
   - **Lifecycle and reprints:** price against months since release, compared across sets of different ages; event studies around reprint announcements.
   - **Grading calculator:** expected value across the full grade distribution, adjusted for pre-screened submissions, minus fees, shipping, VAT and selling fees, with a time cost for the wait. Outputs expected profit, chance of a loss and break-even gem rate.
   - **Cross-market:** landed cost to a UK buyer from the US and from the EU, at mid-market FX vs a typical retail FX markup; how fast prices follow FX moves.
   - **Sealed:** annualised return from launch RRP, volatility and maximum drawdown, compared with CPIH.
8. **Risk flags.** Outlier and suspicious-sale detection, and PSA cert checks on live UK listings.
9. **Dashboard and write-up.**

## Evaluation

- **Split by set, not by row.** Cards from one set never appear in both training and test.
- **Metrics:** median absolute % error, share of cards within ±25%, and prediction-range coverage, each reported per era and per rarity.
- **Leakage checks:** artist and set effects are target-encoded out-of-fold only, and no future prices are used as features.
