"""Where data lives. Raw/licensed data never sits inside the public repo:
it goes to the private data repo (default: a sibling folder) or $CARDLAB_DATA."""
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get("CARDLAB_DATA", REPO.parent / "pokemon-card-market-data")).resolve()
CACHE = REPO / "data" / "cache"          # git-ignored, safe to delete
BUILD = DATA / "build"                   # private: joined tables
SNAP = DATA / "snapshots"                # private: daily price snapshots
for p in (CACHE, BUILD):
    p.mkdir(parents=True, exist_ok=True)
