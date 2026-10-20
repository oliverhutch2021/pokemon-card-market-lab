"""Polite cached HTTP: one file per URL in data/cache, so re-runs cost nothing."""
import hashlib, json, time, urllib.request
from .paths import CACHE

UA = {"User-Agent": "pokemon-card-market-lab/0.1 (+https://github.com/oliverhutch2021/pokemon-card-market-lab)"}


def get_json(url, max_age_days=7, tries=6, pause=0.0):
    f = CACHE / "http" / (hashlib.sha1(url.encode()).hexdigest() + ".json")
    if f.exists() and (time.time() - f.stat().st_mtime) < max_age_days * 86400:
        return json.loads(f.read_text())
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={**UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read())
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                data = None; break
            if i == tries - 1: raise
            wait = e.headers.get("Retry-After") if e.code == 429 else None
            time.sleep(float(wait) if wait and wait.isdigit() else (10 if e.code == 429 else 3) * (i + 1))
        except Exception:
            if i == tries - 1: raise
            time.sleep(3 * (i + 1))
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(data))
    if pause: time.sleep(pause)
    return data
