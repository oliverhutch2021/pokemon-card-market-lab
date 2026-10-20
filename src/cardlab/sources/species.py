"""Species traits (PokeAPI) and popularity signals.

Popularity signals, each kept separate so the model can weigh them:
  reddit2019_votes   r/pokemon favourite-Pokemon survey 2019 (52,725 votes, Gen 1-7)
  poty2020_votes     official Pokemon of the Year 2020, regional top-30 vote counts (240 species)
  wiki_views_24m     English Wikipedia views of the species' page title, last 24 full months
                     (most species titles are redirects to list pages; redirect hits are still
                     counted per title, so this works for every species)
  graded_top         Charizard/Pikachu/etc. flagged as most-graded species (from the slab project)
The species card count (how often TPC prints a species) is added later, from the catalogue.
"""
import csv, json, urllib.request
from ..http import UA

GQL = "https://beta.pokeapi.co/graphql/v1beta"

STARTER_BASES = [1, 4, 7, 152, 155, 158, 252, 255, 258, 387, 390, 393, 495, 498, 501, 650, 653, 656,
                 722, 725, 728, 810, 813, 816, 906, 909, 912]
PSEUDO_LINES = [147, 246, 371, 374, 443, 633, 704, 782, 885, 996]
EEVEE_LINE = [133, 134, 135, 136, 196, 197, 470, 471, 700]
MOST_GRADED = {"charizard", "pikachu", "blastoise", "venusaur", "gyarados", "rayquaza", "mew", "mewtwo",
               "umbreon", "gengar", "eevee", "zapdos", "bulbasaur"}  # from the slab project's S-tier rule


def _gql(query):
    req = urllib.request.Request(GQL, data=json.dumps({"query": query}).encode(),
                                 headers={**UA, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())["data"]


def pokeapi_species():
    q = """{ pokemon_v2_pokemonspecies(order_by:{id:asc}) {
        id name generation_id is_legendary is_mythical is_baby evolves_from_species_id evolution_chain_id
        capture_rate
        pokemon_v2_pokemonspeciesnames(where:{language_id:{_eq:9}}) { name } } }"""
    rows = _gql(q)["pokemon_v2_pokemonspecies"]
    by_id = {r["id"]: r for r in rows}

    def stage(r):
        s = 0
        while r["evolves_from_species_id"]:
            r = by_id[r["evolves_from_species_id"]]; s += 1
        return s

    def chain_of(ids):
        chains = {by_id[i]["evolution_chain_id"] for i in ids if i in by_id}
        return {r["id"] for r in rows if r["evolution_chain_id"] in chains}

    starters, pseudos = chain_of(STARTER_BASES), chain_of(PSEUDO_LINES)
    out = []
    for r in rows:
        en = (r["pokemon_v2_pokemonspeciesnames"] or [{}])[0].get("name") or r["name"].title()
        out.append(dict(dex=r["id"], slug=r["name"], name_en=en, generation=r["generation_id"],
                        legendary=int(r["is_legendary"]), mythical=int(r["is_mythical"]), baby=int(r["is_baby"]),
                        evo_stage=stage(r), evo_chain=r["evolution_chain_id"], capture_rate=r["capture_rate"],
                        starter_line=int(r["id"] in starters), pseudo_line=int(r["id"] in pseudos),
                        eeveelution=int(r["id"] in EEVEE_LINE), most_graded=int(r["name"] in MOST_GRADED)))
    return out


def latest_pageviews():
    """Monthly Wikipedia pageview snapshot written by the data repo's GitHub Action
    (tools/pageviews_snapshot.py). The cloud IP used for development is rate-limited by
    Wikimedia, so views are only used once a complete snapshot exists."""
    from ..paths import DATA
    files = sorted((DATA / "sources" / "pageviews").glob("????-??.csv"))
    if not files:
        return {}, None
    with open(files[-1], encoding="utf-8") as f:
        return {int(r["dex"]): (int(r["views_24m"]) if r["views_24m"] else None) for r in csv.DictReader(f)}, files[-1].stem


def popularity(species_rows, reddit_csv, poty_json):
    votes = {int(r["pokedex_number"]): int(float(r["votes"])) for r in csv.DictReader(open(reddit_csv, encoding="utf-8"))}
    poty = {}
    for block in json.load(open(poty_json, encoding="utf-8"))["regions"].values():
        for line in block.splitlines():
            rank, rest = line.split(". ", 1)
            name, v = rest.rsplit(", ", 1)
            poty[name.strip().lower()] = int(v.replace(",", ""))
    views, month = latest_pageviews()
    for s in species_rows:
        s["reddit2019_votes"] = votes.get(s["dex"])          # None for Gen 8+ (not in the 2019 poll)
        s["poty2020_votes"] = poty.get(s["name_en"].lower())  # None outside regional top 30s
        s["wiki_views_24m"] = views.get(s["dex"])
        s["wiki_views_month"] = month
    return species_rows
