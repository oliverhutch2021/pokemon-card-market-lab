"""Fill in missing TCGplayer / Cardmarket product ids for catalogue rows.

TCGdex lacks marketplace ids for whole eras (DP, BW, XY, most SM). We recover them:
  TCGplayer : map each TCGdex set to TCGCSV group(s) (from known ids, else by name/date),
              then match cards on printed number + name.
  Cardmarket: map each TCGdex set to a Cardmarket expansion (from known ids, else by the
              overlap of card names), then match on name, using attack names when Cardmarket
              disambiguates duplicates as "Name [Attack | Attack]".
Every recovered id carries a `*_match` label saying how it was found.
"""
import re, unicodedata
from collections import Counter, defaultdict
import pandas as pd


def norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    s = s.replace("&", " and ").replace("é", "e")
    return re.sub(r"[^a-z0-9]+", "", s)


def num_key(x):
    """'4/102' -> '4', 'SV049' -> 'sv49', 'TG01' -> 'tg1', '025' -> '25'."""
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None
    x = str(x).split("/")[0].strip().lower()
    m = re.match(r"^([a-z]*)0*(\d+)([a-z]*)$", x)
    return f"{m.group(1)}{m.group(2)}{m.group(3)}" if m else x


def clean_name(n):
    return norm(re.sub(r"\(.*?\)|\[.*?\]", "", str(n)).replace(" - ", " "))


def clean_cm(n):
    """Cardmarket and TCGdex differ on levels: 'Empoleon Lv.42', 'Empoleon LV.X' -> 'empoleon'.
    LV.X vs non-LV.X duplicates are then split by attack names."""
    n = re.sub(r"\(.*?\)|\[.*?\]", "", str(n))
    n = re.sub(r"\bLV\.?\s*(X|\d+)\b", "", n, flags=re.I)
    return norm(n)


SET_ALIASES = {  # TCGdex set id -> TCGCSV group name
    "bwp": "Black and White Promos", "dpp": "Diamond and Pearl Promos", "ex16": "EX Power Keepers",
    "sm1": "SM Base Set", "xy1": "XY Base Set", "xyp": "XY Promos", "xya": "Alternate Art Promos",
    "tk-xy-b": "XY Trainer Kit: Bisharp & Wigglytuff", "tk-xy-w": "XY Trainer Kit: Bisharp & Wigglytuff",
}
GROUP_PREFIX = re.compile(r"^(swsh\d*|sv\d*|me\d*|sm|xy|svp|sm -|xy -)\s*[:\-]?\s*", re.I)


def tcgplayer_fill(cat, tcg_products):
    p = tcg_products.copy()
    p["nk"] = p["number"].map(num_key)
    p["cn"] = p["name"].map(clean_cm)
    p["has_paren"] = p["name"].str.contains(r"\(", regex=True)
    pid_group = dict(zip(p.productId, p.groupId))
    # 1) set -> groups seen through ids TCGdex already gives
    known = defaultdict(Counter)
    for sid, tid in cat.loc[cat.tcgplayer_id.notna(), ["set_id", "tcgplayer_id"]].itertuples(index=False):
        g = pid_group.get(int(tid))
        if g: known[sid][g] += 1
    groups = p.groupby("groupId").agg(groupName=("groupName", "first"), date=("groupPublishedOn", "first")).reset_index()
    groups["gn"] = groups.groupName.map(lambda s: norm(GROUP_PREFIX.sub("", s)))
    groups["date"] = groups.date.str[:10]
    sets = cat.groupby("set_id").agg(set_name=("set_name", "first"), date=("release_date", "first")).reset_index()
    set_groups = {}
    for s in sets.itertuples():
        if known.get(s.set_id):
            set_groups[s.set_id] = [g for g, n in known[s.set_id].most_common() if n >= 3] or [known[s.set_id].most_common(1)[0][0]]
            continue
        sn = norm(s.set_name)
        if s.set_id in SET_ALIASES:
            set_groups[s.set_id] = list(groups[groups.groupName == SET_ALIASES[s.set_id]].groupId)
            continue
        cand = groups[(groups.gn == sn) | (groups.gn == norm("Diamond and Pearl")) & (sn == norm("Diamond & Pearl"))]
        if cand.empty:
            cand = groups[groups.gn.str.contains(sn, regex=False) & (groups.date == s.date)]
        if cand.empty:
            cand = groups[groups.date == s.date]
            cand = cand.loc[cand.gn.map(lambda g: sn[:5] in g or g[:5] in sn).astype(bool)]
        set_groups[s.set_id] = list(cand.groupId)
    # 2) card match: same group, same printed number, same cleaned name; prefer products without "(...)"
    idx = {}
    for r in p.sort_values("has_paren").itertuples():
        idx.setdefault((r.groupId, r.nk, r.cn), r.productId)
        idx.setdefault((r.groupId, r.nk, None), r.productId)
    pname = dict(zip(p.productId, p.cn))
    out_id, how = [], []
    for r in cat.itertuples():
        if pd.notna(r.tcgplayer_id):
            out_id.append(int(r.tcgplayer_id)); how.append("tcgdex"); continue
        if not r.main_version:
            out_id.append(None); how.append(None); continue
        nk, cn, hit, h = num_key(r.local_id), clean_cm(r.name), None, None
        for g in set_groups.get(r.set_id, []):
            hit = idx.get((g, nk, cn))
            if hit: h = "number+name"; break
        if not hit:  # same number, name starts the same (e.g. 'Empoleon' vs 'Empoleon LV.X')
            for g in set_groups.get(r.set_id, []):
                cand = idx.get((g, nk, None))
                if cand and pname.get(cand, "")[:5] == cn[:5]:
                    hit, h = cand, "number+name-prefix"; break
        how.append(h)
        out_id.append(hit)
    cat = cat.copy()
    cat["tcgplayer_id"] = pd.array(out_id, dtype="Int64")
    cat["tcgplayer_match"] = how
    return cat, set_groups


def cardmarket_fill(cat, cm_products, tcgdex_cards):
    p = cm_products[cm_products.categoryName == "Pokémon Single"].copy()
    p["base"] = p.name.map(clean_cm)
    p["attacks"] = p.name.map(lambda n: {norm(a) for a in re.findall(r"\[(.*?)\]", n)[-1].split("|")} if "[" in n else set())
    exp_of = dict(zip(p.idProduct, p.idExpansion))
    known = defaultdict(Counter)
    for sid, cid in cat.loc[cat.cardmarket_id.notna(), ["set_id", "cardmarket_id"]].itertuples(index=False):
        e = exp_of.get(int(cid))
        if e: known[sid][e] += 1
    set_exp = {s: c.most_common(1)[0][0] for s, c in known.items()}
    # unmapped sets: pick the unclaimed expansion whose card names overlap most (Jaccard)
    claimed = set(set_exp.values())
    exp_names = p[~p.idExpansion.isin(claimed)].groupby("idExpansion").base.agg(set)
    for sid, names in cat[~cat.set_id.isin(set_exp)].groupby("set_id").name.agg(lambda x: {clean_cm(n) for n in x}).items():
        best, score = None, 0.0
        for e, en in exp_names.items():
            j = len(names & en) / max(1, len(names | en))
            if j > score: best, score = e, j
        if best is not None and score >= 0.5:
            set_exp[sid] = best
    attacks = {c["id"]: {norm(a.get("name", "")) for a in c.get("attacks") or []} for c in tcgdex_cards}
    by_key = defaultdict(list)
    for r in p.itertuples():
        by_key[(r.idExpansion, r.base)].append(r)
    out_id, how = [], []
    for r in cat.itertuples():
        if pd.notna(r.cardmarket_id):
            out_id.append(int(r.cardmarket_id)); how.append("tcgdex"); continue
        cands = by_key.get((set_exp.get(r.set_id), clean_cm(r.name)), [])
        hit = None
        if len(cands) == 1:
            hit, h = cands[0].idProduct, "name"
        elif len(cands) > 1:
            a = attacks.get(r.card_id, set())
            m = [c for c in cands if c.attacks and c.attacks <= a]
            if len(m) == 1:
                hit, h = m[0].idProduct, "name+attacks"
        out_id.append(hit); how.append(h if hit else None)
    cat = cat.copy()
    cat["cardmarket_id"] = pd.array(out_id, dtype="Int64")
    cat["cardmarket_match"] = how
    return cat, set_exp
