"""Step 3: raw (ungraded, near-mint) English card value model.

    python -m cardlab.models.raw_value

Target: log of the TCGplayer market price (USD) of each main card version.
Split by set release date, so whole sets are unseen:
    train  sets released before 2025-01-01
    valid  sets released in 2025        (model choice, early stopping, interval widths)
    test   sets released in 2026        (scored once, by a model refit on train+valid)

Models compared:
    baseline  median price of the same rarity tier and finish in training
    linear    ridge regression on the same features (one-hot categories)
    boosted   LightGBM gradient boosting (main model)
Prediction ranges: split-conformal, i.e. the 10th-90th percentile of validation errors,
taken separately for cheap / mid / expensive predictions.
Per-card drivers: LightGBM's exact per-feature contributions (SHAP values), summed into
plain-English groups and shown as multipliers ("x2.1 from rarity").

Outputs (private data repo):  build/raw_value_predictions.parquet
Outputs (public repo):        data/derived/raw_value_metrics.json, docs/figures/raw_*.png
"""
import json, math, sys
import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.linear_model import Ridge
from sklearn.model_selection import GroupKFold
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import make_pipeline
from ..paths import BUILD, REPO

VALID_FROM, TEST_FROM = "2025-01-01", "2026-01-01"
SEED = 7

MECH = ["is_ex_old", "is_gx", "is_v", "is_vmax", "is_vstar", "is_lvx", "is_prime", "is_break", "is_mega",
        "is_tag_team", "is_gold_star", "is_dark", "is_light", "is_owner", "is_shining", "is_delta", "is_radiant"]
SPECIES = ["sp_generation", "sp_legendary", "sp_mythical", "sp_baby", "sp_evo_stage", "sp_starter_line",
           "sp_pseudo_line", "sp_eeveelution", "sp_most_graded"]
CATS = ["finish", "category", "serie", "rarity", "stage"]
GROUPS = {  # feature -> plain-English driver group
    "Rarity & pull rate": ["rarity_tier", "rarity", "is_secret", "number_ratio", "log_same_rarity_in_set", "tier_pct_in_set"],
    "Version": ["finish", "first_edition", "shadowless"],
    "Set & age": ["log_age", "release_year", "serie", "log_set_size", "set_total_ratio", "is_promo"],
    "Pokémon popularity": SPECIES + ["log_reddit", "log_poty", "poty_listed", "reddit_listed", "log_species_cards", "log_wiki"],
    "Card type & mechanic": MECH + ["category", "stage", "hp", "n_dex"],
    "Artist": ["artist_te", "log_artist_cards"],
}


def load():
    t = pd.read_parquet(BUILD / "card_table.parquet")
    m = t[(t.main_version == 1) & (t.usd_market > 0)].copy()
    m["split"] = np.where(m.release_date < VALID_FROM, "train", np.where(m.release_date < TEST_FROM, "valid", "test"))
    m["y"] = np.log(m.usd_market)
    return m


def features(m):
    X = pd.DataFrame(index=m.index)
    X["rarity_tier"] = m.rarity_tier.fillna(-1)
    X["is_secret"] = m.is_secret
    X["number_ratio"] = (m.number / m.set_official).clip(upper=3).fillna(-1)
    X["first_edition"], X["shadowless"] = m.first_edition, m.shadowless
    X["is_promo"] = m.is_promo
    X["log_set_size"] = np.log1p(m.set_official.fillna(m.set_total))
    X["set_total_ratio"] = (m.set_total / m.set_official).clip(upper=3).fillna(1)
    X["log_age"] = np.log1p(m.set_age_days.clip(lower=1))
    X["release_year"] = m.release_date.dt.year
    X["hp"] = pd.to_numeric(m.hp, errors="coerce").fillna(-1)
    X["n_dex"] = m.n_dex
    for c in MECH + SPECIES:
        X[c] = m[c].fillna(-1)
    X["log_reddit"] = np.log1p(m.sp_reddit2019_votes.fillna(0))
    X["reddit_listed"] = m.sp_reddit2019_votes.notna().astype(int)
    X["log_poty"] = np.log1p(m.sp_poty2020_votes.fillna(0))
    X["poty_listed"] = m.sp_poty2020_votes.notna().astype(int)
    X["log_species_cards"] = np.log1p(m.species_card_count.fillna(0))
    X["log_wiki"] = np.log1p(m.sp_wiki_views_24m.astype(float)).fillna(-1)
    X["log_psa_total"] = np.log1p(m.psa_total.fillna(0))
    X["psa_listed"] = m.psa_total.notna().astype(int)
    # pull-rate / in-set position (no prices used): a card's share of its rarity slot, how
    # graded it is relative to the rest of its set, and how "hot" the set is for grading
    key = [m.set_id, m.rarity.fillna("NA"), m.finish]
    X["log_same_rarity_in_set"] = np.log(m.groupby(key).row_id.transform("size"))
    X["tier_pct_in_set"] = m.groupby("set_id").rarity_tier.rank(pct=True).fillna(0.5)
    X["psa_pct_in_set"] = m.groupby("set_id").psa_total.rank(pct=True).fillna(0)
    X["set_log_psa_mean"] = np.log1p(m.psa_total.fillna(0)).groupby(m.set_id).transform("mean")
    X["set_log_psa_per_day"] = X.set_log_psa_mean - np.log1p(m.set_age_days.clip(lower=1))
    for c in CATS:
        X[c] = m[c].fillna("NA").astype(str)
    return X


def artist_encoding(m, X):
    """Out-of-fold smoothed mean log price per artist. Training rows get values computed
    without their own set (GroupKFold by set); other rows use all training rows."""
    k, prior = 20.0, m.loc[m.split == "train", "y"].mean()
    X = X.copy()
    X["artist_te"] = np.nan
    art = m.illustrator.fillna("unknown").str.lower()

    def enc(src):
        g = pd.DataFrame({"a": art[src], "y": m.y[src]}).groupby("a").y.agg(["sum", "count"])
        return (g["sum"] + k * prior) / (g["count"] + k), g["count"]

    tr = m.index[m.split == "train"]
    for fit_i, app_i in GroupKFold(5).split(tr, groups=m.loc[tr, "set_id"]):
        te, _ = enc(tr[fit_i])
        X.loc[tr[app_i], "artist_te"] = art[tr[app_i]].map(te).fillna(prior).values
    return X, enc, art, prior


def apply_artist(X, idx, enc_src, enc, art, prior):
    te, cnt = enc(enc_src)
    X.loc[idx, "artist_te"] = art[idx].map(te).fillna(prior).values
    return X


def add_artist_counts(m, X, src):
    art = m.illustrator.fillna("unknown").str.lower()
    cnt = art[src].value_counts()
    X["log_artist_cards"] = np.log1p(art.map(cnt).fillna(0))
    return X


# PSA pop is left out of the raw model: young sets haven't been graded much yet, so pop
# misleads exactly where the model is tested (2025 validation: $10-100 cards 55% -> 47% error
# without it). Pop is central to the PSA 10 model instead (step 4).
GRADING_FEATURES = ["log_psa_total", "psa_listed", "psa_pct_in_set", "set_log_psa_mean", "set_log_psa_per_day"]


def model_cols(X):
    return [c for c in X.columns if c not in GRADING_FEATURES]


def lgb_data(X):
    Z = X.copy()
    for c in CATS:
        Z[c] = Z[c].astype("category")
    return Z


# chosen on 2025 validation sets (8 variants tried, see docs/RAW_MODEL.md); test scored once
PARAMS = dict(objective="regression", learning_rate=0.02, num_leaves=31, min_data_in_leaf=40,
              feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1, lambda_l2=1.0,
              verbose=-1, seed=SEED, deterministic=True, force_row_wise=True)


def fit_boosted(Xtr, ytr, Xva=None, yva=None, rounds=None):
    dtr = lgb.Dataset(Xtr, ytr, categorical_feature=CATS, free_raw_data=False)
    if rounds is None:
        dva = lgb.Dataset(Xva, yva, reference=dtr, categorical_feature=CATS)
        b = lgb.train(PARAMS, dtr, 5000, valid_sets=[dva], callbacks=[lgb.early_stopping(200, verbose=False)])
        return b, b.best_iteration
    return lgb.train(PARAMS, dtr, rounds), rounds


def fit_linear(Xtr, ytr):
    num = [c for c in Xtr.columns if c not in CATS]
    ct = ColumnTransformer([("num", StandardScaler(), num),
                            ("cat", OneHotEncoder(handle_unknown="ignore", min_frequency=20), CATS)])
    return make_pipeline(ct, Ridge(alpha=3.0)).fit(Xtr, ytr)


BANDS = [(0, 1, "under $1"), (1, 10, "$1–10"), (10, 100, "$10–100"), (100, 1e9, "$100+")]


def band(p):
    for lo, hi, name in BANDS:
        if lo <= p < hi:
            return name


def metrics(actual, pred):
    r = np.exp(pred) / actual - 1
    a = np.abs(r)
    return dict(n=int(len(a)), median_abs_pct_error=round(float(np.median(a)) * 100, 1),
                within_25pct=round(float((a <= 0.25).mean()) * 100, 1), within_50pct=round(float((a <= 0.5).mean()) * 100, 1),
                r2_log=round(float(1 - ((np.log(actual) - pred) ** 2).sum() / ((np.log(actual) - np.log(actual).mean()) ** 2).sum()), 3))


def conformal_widths(pred_va, y_va):
    """10th/90th percentile of log errors in validation, per predicted-price band."""
    df = pd.DataFrame({"b": [band(math.exp(p)) for p in pred_va], "e": y_va - pred_va})
    return {b: (float(g.e.quantile(0.10)), float(g.e.quantile(0.90))) for b, g in df.groupby("b")}


def main():
    m = load()
    X = features(m)
    tr, va, te = (m.index[m.split == s] for s in ("train", "valid", "test"))
    # --- stage A: train only, choose model on 2025 sets -------------------------------
    XA, enc, art, prior = artist_encoding(m, X)
    XA = apply_artist(XA, va.union(te), tr, enc, art, prior)
    XA = add_artist_counts(m, XA, tr)
    XA = XA[model_cols(XA)]
    base = m.loc[tr].groupby(["rarity_tier", "finish"], dropna=False).y.median()
    def baseline(idx):
        k = list(zip(m.loc[idx, "rarity_tier"], m.loc[idx, "finish"]))
        return np.array([base.get(x, m.loc[tr, "y"].median()) for x in k])
    lin = fit_linear(XA.loc[tr], m.y[tr])
    boo, best = fit_boosted(lgb_data(XA.loc[tr]), m.y[tr], lgb_data(XA.loc[va]), m.y[va])
    pred_va = {"baseline": baseline(va), "linear": lin.predict(XA.loc[va]), "boosted": boo.predict(lgb_data(XA.loc[va]))}
    widths = conformal_widths(pred_va["boosted"], m.y[va].values)
    # --- stage B: refit on train+valid, score 2026 sets once ---------------------------
    trva = tr.union(va)
    mB = m.copy(); mB.loc[va, "split"] = "train"
    XB, encB, artB, priorB = artist_encoding(mB, X)
    XB = apply_artist(XB, te, trva, encB, artB, priorB)
    XB = add_artist_counts(m, XB, trva)
    XB = XB[model_cols(XB)]
    baseB = m.loc[trva].groupby(["rarity_tier", "finish"], dropna=False).y.median()
    base_te = np.array([baseB.get(x, m.loc[trva, "y"].median()) for x in zip(m.loc[te, "rarity_tier"], m.loc[te, "finish"])])
    linB = fit_linear(XB.loc[trva], m.y[trva])
    booB, _ = fit_boosted(lgb_data(XB.loc[trva]), m.y[trva], rounds=best)
    pred_te = {"baseline": base_te, "linear": linB.predict(XB.loc[te]), "boosted": booB.predict(lgb_data(XB.loc[te]))}

    # --- metrics ------------------------------------------------------------------------
    out = {"split": {"train_sets_before": VALID_FROM, "test_sets_from": TEST_FROM,
                     "n": {s: int((m.split == s).sum()) for s in ("train", "valid", "test")},
                     "sets": {s: int(m.loc[m.split == s, "set_id"].nunique()) for s in ("train", "valid", "test")}},
           "boosted_rounds": int(best), "price_date": str(m.price_date_usd.iloc[0])}
    for name, idx, preds in (("valid_2025", va, pred_va), ("test_2026", te, pred_te)):
        act = m.usd_market[idx].values
        out[name] = {k: metrics(act, p) for k, p in preds.items()}
        b = np.array([band(x) for x in act])
        out[name + "_by_band"] = {bn: {k: metrics(act[b == bn], p[b == bn]) for k, p in preds.items()}
                                  for _, _, bn in BANDS if (b == bn).sum() >= 10}
    # intervals on test
    p = pred_te["boosted"]
    lo = np.array([p_ + widths.get(band(math.exp(p_)), (-0.5, 0.5))[0] for p_ in p])
    hi = np.array([p_ + widths.get(band(math.exp(p_)), (-0.5, 0.5))[1] for p_ in p])
    yt = m.y[te].values
    out["test_2026_interval_coverage_pct"] = round(float(((yt >= lo) & (yt <= hi)).mean()) * 100, 1)
    out["interval_target_pct"] = 80
    # leakage / sanity: shuffled-target model should be useless
    rng = np.random.default_rng(SEED)
    shuf, _ = fit_boosted(lgb_data(XA.loc[tr]), rng.permutation(m.y[tr].values), rounds=best)
    out["sanity_shuffled_target_valid"] = metrics(m.usd_market[va].values, shuf.predict(lgb_data(XA.loc[va])))

    # --- drivers (exact per-feature contributions of the final model) -----------------
    allX = XB.copy()
    allX = apply_artist(allX, trva, trva, encB, artB, priorB)  # in-sample artist values for the explanation view
    contrib = booB.predict(lgb_data(allX), pred_contrib=True)
    cols = list(allX.columns)
    C = pd.DataFrame(contrib[:, :-1], columns=cols, index=allX.index)
    G = pd.DataFrame({g: C[[c for c in fs if c in cols]].sum(axis=1) for g, fs in GROUPS.items()})
    imp = (G.abs().mean() / G.abs().mean().sum() * 100).round(1).sort_values(ascending=False)
    out["driver_share_pct"] = imp.to_dict()
    gain = pd.Series(booB.feature_importance("gain"), index=cols)
    out["top_features_by_gain_pct"] = (gain / gain.sum() * 100).round(1).sort_values(ascending=False).head(15).to_dict()

    # --- per-card predictions (private) -------------------------------------------------
    pred_all = booB.predict(lgb_data(allX))
    pr = pd.DataFrame({"row_id": m.row_id, "split": m.split, "usd_market": m.usd_market,
                       "pred_usd": np.exp(pred_all)}, index=m.index)
    # held-out predictions where they exist (valid: stage-A model; test: stage-B model)
    pr.loc[va, "pred_usd_heldout"] = np.exp(pred_va["boosted"])
    pr.loc[te, "pred_usd_heldout"] = np.exp(pred_te["boosted"])
    # the "model value" shown for a card: held-out prediction where one exists, else the final model's
    pr["model_usd"] = pr.pred_usd_heldout.fillna(pr.pred_usd)
    w = pr.model_usd.map(lambda v: widths.get(band(v), (-0.5, 0.5)))
    pr["range_lo_usd"] = pr.model_usd * np.exp([a for a, _ in w])
    pr["range_hi_usd"] = pr.model_usd * np.exp([b for _, b in w])
    pr["vs_model_pct"] = (pr.usd_market / pr.model_usd - 1) * 100
    # a rarity name the model had never seen when it scored the card: value not trustworthy
    seen_A, seen_B = set(m.loc[tr, "rarity"].dropna()), set(m.loc[trva, "rarity"].dropna())
    pr["unseen_rarity"] = 0
    pr.loc[va, "unseen_rarity"] = (~m.loc[va, "rarity"].isin(seen_A) & m.loc[va, "rarity"].notna()).astype(int)
    pr.loc[te, "unseen_rarity"] = (~m.loc[te, "rarity"].isin(seen_B) & m.loc[te, "rarity"].notna()).astype(int)
    out["unseen_rarity_rows"] = {"valid": int(pr.loc[va, "unseen_rarity"].sum()), "test": int(pr.loc[te, "unseen_rarity"].sum())}
    pr["base_usd"] = math.exp(contrib[0, -1])
    for g in G.columns:
        pr["x_" + g] = np.exp(G[g])
    pr.to_parquet(BUILD / "raw_value_predictions.parquet")
    figures(m, pr, out)
    (REPO / "data" / "derived").mkdir(parents=True, exist_ok=True)
    (REPO / "data" / "derived" / "raw_value_metrics.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({k: out[k] for k in ("split", "valid_2025", "test_2026", "test_2026_interval_coverage_pct",
                                          "driver_share_pct", "sanity_shuffled_target_valid")}, indent=1))
    return m, pr, out, booB, allX


def figures(m, pr, out):
    """Aggregate-only charts for the public repo (no individual card prices)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig_dir = REPO / "docs" / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    ink, muted, grid = "#1f2328", "#6e7781", "#d0d7de"
    plt.rcParams.update({"font.size": 10, "axes.edgecolor": grid, "axes.labelcolor": ink, "xtick.color": muted,
                         "ytick.color": muted, "axes.spines.top": False, "axes.spines.right": False})
    # 1. error by price band, test 2026, three models
    bands = [b for _, _, b in BANDS if b in out["test_2026_by_band"]]
    models = [("baseline", "Rarity median", "#afb8c1"), ("linear", "Linear", "#8c959f"), ("boosted", "Boosted (final)", "#0969da")]
    fig, ax = plt.subplots(figsize=(7, 3.6))
    w = 0.26
    for i, (k, label, col) in enumerate(models):
        vals = [out["test_2026_by_band"][b][k]["median_abs_pct_error"] for b in bands]
        ax.bar([j + (i - 1) * w for j in range(len(bands))], vals, w, label=label, color=col)
    ns = [out["test_2026_by_band"][b]["boosted"]["n"] for b in bands]
    ax.set_xticks(range(len(bands)), [f"{b}\n(n={n})" for b, n in zip(bands, ns)])
    ax.set_ylabel("Median error, % of actual price")
    ax.set_title("Unseen 2026 sets: error by card price", loc="left", color=ink)
    ax.legend(frameon=False); ax.grid(axis="y", color=grid, lw=0.6); ax.set_axisbelow(True)
    fig.tight_layout(); fig.savefig(fig_dir / "raw_error_by_band.png", dpi=160); plt.close(fig)
    # 2. calibration: mean actual vs mean predicted by decile of prediction (test)
    t = pr[pr.split == "test"].copy()
    t["dec"] = pd.qcut(np.log(t.pred_usd_heldout), 10, labels=False, duplicates="drop")
    g = t.groupby("dec").agg(p=("pred_usd_heldout", "median"), a=("usd_market", "median"))
    fig, ax = plt.subplots(figsize=(4.6, 4.2))
    lim = [min(g.min()) * 0.7, max(g.max()) * 1.4]
    ax.plot(lim, lim, color=grid, lw=1)
    ax.plot(g.p, g.a, "o-", color="#0969da", ms=5)
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlabel("Model value, median of decile ($)"); ax.set_ylabel("Actual price, median of decile ($)")
    ax.set_title("Calibration on unseen 2026 sets", loc="left", color=ink)
    fig.tight_layout(); fig.savefig(fig_dir / "raw_calibration.png", dpi=160); plt.close(fig)
    # 3. driver share
    d = pd.Series(out["driver_share_pct"]).sort_values()
    fig, ax = plt.subplots(figsize=(6, 3))
    ax.barh(d.index, d.values, color="#0969da")
    for y, v in enumerate(d.values):
        ax.text(v + 0.5, y, f"{v:.0f}%", va="center", color=muted)
    ax.set_xlabel("Share of the model's price explanation (mean |contribution|)")
    ax.set_title("What drives raw card prices", loc="left", color=ink)
    fig.tight_layout(); fig.savefig(fig_dir / "raw_drivers.png", dpi=160); plt.close(fig)


if __name__ == "__main__":
    main()
    sys.exit(0)
