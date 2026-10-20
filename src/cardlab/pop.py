"""Join PSA population (PokeInvest monthly snapshot) onto catalogue versions.

A pop row looks like "Charizard [Shadowless] #4" in set page "base-set". Matching:
  1. set page -> one or more TCGdex sets (main set plus subsets such as Trainer Gallery,
     Shiny Vault, Galarian Gallery; promo pages route by number prefix)
  2. same printed number and the same start of the name
  3. version from the bracket tags: [1st Edition], [Shadowless], [Reverse Holo]/[Reverse],
     [Holo], [Poke Ball]/[Master Ball]; no tag = the card's standard print
Anything unmatched or ambiguous stays unmatched and is counted in the report, never guessed.
"""
import re
from collections import defaultdict
import pandas as pd
from .marketmap import norm, num_key, clean_cm
from .paths import DATA

SLUG_SETS = {
    "expedition": ["ecard1"], "go": ["swsh10.5"], "heartgold-and-soulsilver": ["hgss1"],
    "mcdonalds-2021": ["2021swsh"], "mcdonalds-2022": ["2022swsh"], "mcdonalds-2023": ["2023sv"],
    "rumble": ["ru1"], "scarlet-and-violet-151": ["sv03.5"], "team-magma-and-team-aqua": ["ex4"],
    "gyarados-and-raichu": ["tk-hs-g", "tk-hs-r"], "hidden-fates": ["sm115", "sma"],
    "shining-fates": ["swsh4.5", "swsh4.5sv"], "crown-zenith": ["swsh12.5", "swsh12.5gg"],
    "brilliant-stars": ["swsh9", "swsh9tg"], "astral-radiance": ["swsh10", "swsh10tg"],
    "lost-origin": ["swsh11", "swsh11tg"], "silver-tempest": ["swsh12", "swsh12tg"],
    "celebrations": ["cel25", "cel25cc"], "30th-celebration": ["30th", "30th-c"],
    "unseen-forces": ["ex10", "exu"], "scarlet-and-violet": ["sv01", "sve"], "mega-evolution": ["me01", "mee"],
}
PROMO_PREFIX = {"xy": "xyp", "dp": "dpp", "sm": "smp", "bw": "bwp", "swsh": "swshp", "hgss": "hgssp", "svp": "svp", "mep": "mep"}
PROMO_PLAIN = ["basep", "np", "svp", "mep"]
SKIP_TAGS = {"Staff", "Jumbo", "Spanish", "Portuguese", "Stamped", "Stamped Staff", "Prerelease", "Prerelease Staff",
             "Pokemon Center", "General Mills", "Regional Championships", "Regional Championships Staff", "Champion",
             "Semi-Finalist", "Professor Program", "Stain Error", "Double Holo Error", "No Symbol", "Build-a-Bear",
             "Eb Games Special", "Prize Pack", "World Collection - Italian", "Play", "Wildfire Theme Deck", "WOTC"}


def parse_label(label):
    m = re.match(r"^(.*?)\s*((?:\[[^\]]+\]\s*)*)#(\S+)\s*$", label.strip())
    if not m:
        return None, [], None
    return m.group(1).strip(), re.findall(r"\[([^\]]+)\]", m.group(2)), m.group(3)


def pick_version(rows, tags):
    t = set(tags)
    if t & SKIP_TAGS:
        return None, "special-tag"
    if "1st Edition" in t:
        c = rows[rows.first_edition == 1]
    elif "Shadowless" in t:
        c = rows[(rows.shadowless == 1) & (rows.first_edition == 0)]
    elif t & {"Poke Ball", "Master Ball"}:
        f = "pokeball" if "Poke Ball" in t else "masterball"
        c = rows[rows.foil == f]
    elif t & {"Reverse Holo", "Reverse", "Rocket Reverse Holo"}:
        c = rows[(rows.finish == "reverse") & rows.foil.fillna("").map(lambda x: not x.endswith("ball"))]
    elif t & {"Holo", "Holo Rare", "Cosmos Holo", "Cracked Ice", "Confetti Holo", "Rainbow Foil"}:
        c = rows[(rows.finish == "holo") & (rows.main_version == 1)]
    else:  # standard print: main, not 1st/shadowless/reverse
        c = rows[(rows.main_version == 1) & (rows.first_edition == 0) & (rows.shadowless == 0) & (rows.finish != "reverse")]
        if len(c) > 1 and (c.finish == "holo").sum() == 1 and (c.finish == "normal").sum() == 1:
            c = c[c.finish == "normal"]  # e.g. theme-deck holo vs set normal: untagged = normal
    if len(c) > 1:  # e.g. plain reverse vs league-pattern reverse: the main print wins
        c = c[c.main_version == 1]
    if len(c) == 1:
        return c.index[0], "ok"
    return None, "no-version" if len(c) == 0 else "ambiguous"


def attach(cat, month=None):
    files = sorted((DATA / "pop").glob("*/pokeinvest.csv.gz"))
    f = [x for x in files if month is None or x.parent.name == month][-1]
    pop = pd.read_csv(f)
    by_name = {norm(n): sid for sid, n in cat.groupby("set_id").set_name.first().items()}
    cat = cat.copy()
    cat["nk"] = cat.local_id.map(num_key)
    idx = defaultdict(list)
    for i, sid, nk in cat[["set_id", "nk"]].itertuples():
        idx[(sid, nk)].append(i)
    cols = {k: [None] * len(cat) for k in ("psa_total", "psa10", "psa9", "psa8", "pop_month")}
    status = defaultdict(int)
    taken = set()
    for r in pop.itertuples():
        name, tags, number = parse_label(r.label)
        if name is None:
            status["unparsed"] += 1; continue
        nk = num_key(number)
        if r.set_slug == "promo":
            pre = re.match(r"^[a-z]+", nk or "")
            sets = [PROMO_PREFIX[pre.group(0)]] if pre and pre.group(0) in PROMO_PREFIX else PROMO_PLAIN
            nk = re.sub(r"^(xy|dp|sm|bw|swsh|hgss)", "", nk) if pre and pre.group(0) in PROMO_PREFIX and pre.group(0) not in ("svp", "mep") else nk
        else:
            sets = SLUG_SETS.get(r.set_slug) or ([by_name[norm(r.set_slug)]] if norm(r.set_slug) in by_name else [])
        if not sets:
            status["set-not-in-catalogue"] += 1; continue
        cn = clean_cm(name)
        cand = [i for s in sets for k in ({nk, nk.upper()} if nk else set()) for i in idx.get((s, k), [])]
        # promo ids in TCGdex keep the prefix (e.g. 'XY57'); try that form too
        if not cand and r.set_slug == "promo":
            cand = [i for s in sets for i in idx.get((s, num_key(number)), [])]
        cand = sorted({i for i in cand if clean_cm(cat.at[i, "name"])[:4] == cn[:4]})
        if not cand:
            status["card-not-found"] += 1; continue
        cards = cat.loc[cand]
        if cards.card_id.nunique() > 1:
            status["ambiguous-card"] += 1; continue
        i, st = pick_version(cards, tags)
        if i is None:
            status[st] += 1; continue
        if i in taken:
            status["duplicate-target"] += 1; continue
        taken.add(i)
        for k, v in (("psa_total", r.total), ("psa10", r.psa10), ("psa9", r.psa9), ("psa8", r.psa8), ("pop_month", r.month)):
            cols[k][cat.index.get_loc(i)] = v
        status["matched"] += 1
    for k, v in cols.items():
        cat[k] = v
    cat["gem_rate"] = cat.psa10 / cat.psa_total
    return cat.drop(columns="nk"), dict(status), f.parent.name
