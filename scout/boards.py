"""Public Greenhouse / Lever / Ashby board directory for the role census.

The committed snapshot in data/ats-boards.json is derived from
groundtruthtools/ats-jobs-mcp (MIT). Refresh with:

  python -m scout.boards --refresh
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
DIRECTORY_PATH = ROOT / "data" / "ats-boards.json"
UPSTREAM = (
    "https://raw.githubusercontent.com/groundtruthtools/"
    "ats-jobs-mcp/main/src/ats_jobs_mcp/directory.json"
)
# Upstream directory has no Lever boards. These were confirmed live 2026-08-27.
LEVER_EXTRAS = (
    "palantir",
    "activecampaign",
    "metr",
    "apolloresearch",
    "spotify",
)
_PREFIX = {"g": "greenhouse", "a": "ashby", "l": "lever"}
_ATS_PREFIX = {v: k for k, v in _PREFIX.items()}

CENSUS_DEFAULTS = {
    "enabled": True,
    "max_age_days": 2,
    "concurrency": 24,
    "timeout": 8,
}
# `data` / `platform` match half the US tech board. Census drops them unless
# the user sets census.keywords in config.yaml; the watchlist still uses the
# full prefilter list.
CENSUS_DROP_KEYWORDS = frozenset({"data", "platform"})


def census_cfg(cfg: dict) -> dict:
    merged = dict(CENSUS_DEFAULTS)
    merged.update(cfg.get("census") or {})
    return merged


def lookback_days(cfg: dict) -> int:
    """Freshness window. Census runs use 2 days so a 12h cadence still overlaps."""
    cc = census_cfg(cfg)
    if cc.get("enabled", True) and DIRECTORY_PATH.exists():
        return int(cc["max_age_days"])
    return int(cfg["max_age_days"])


def census_keywords(cfg: dict) -> list[str]:
    cc = census_cfg(cfg)
    if cc.get("keywords"):
        return list(cc["keywords"])
    return [k for k in (cfg.get("prefilter_keywords") or [])
            if str(k).lower() not in CENSUS_DROP_KEYWORDS]


def load_directory(path: pathlib.Path = DIRECTORY_PATH) -> list[tuple[str, str]]:
    """Return [(ats, slug), ...] from the compact snapshot."""
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for raw in data.get("boards") or []:
        if ":" not in raw:
            continue
        p, slug = raw.split(":", 1)
        ats = _PREFIX.get(p)
        slug = slug.strip().lower()
        if not ats or not slug:
            continue
        key = (ats, slug)
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def merge_boards(cfg: dict) -> list[tuple[str, str]]:
    """Directory ∪ watchlist. Watchlist tokens win a slot even if missing upstream."""
    seen: set[tuple[str, str]] = set()
    boards: list[tuple[str, str]] = []
    for ats, slug in load_directory():
        if (ats, slug) in seen:
            continue
        seen.add((ats, slug))
        boards.append((ats, slug))
    for ats, tokens in (cfg.get("watchlist") or {}).items():
        if ats not in _ATS_PREFIX:
            continue
        for token in tokens or []:
            slug = str(token).strip().lower()
            if not slug or (ats, slug) in seen:
                continue
            seen.add((ats, slug))
            boards.append((ats, slug))
    return boards


def directory_tokens() -> dict[str, list[str]]:
    """Watchlist-shaped dict of every directory slug, for scout-id parsing."""
    by_ats: dict[str, list[str]] = {"greenhouse": [], "lever": [], "ashby": []}
    for ats, slug in load_directory():
        by_ats.setdefault(ats, []).append(slug)
    return by_ats


def refresh(path: pathlib.Path = DIRECTORY_PATH) -> int:
    import requests

    r = requests.get(UPSTREAM, timeout=60)
    r.raise_for_status()
    raw = r.json()
    seen: set[str] = set()
    boards: list[str] = []
    skipped_empty = 0
    for b in raw.get("boards") or []:
        ats = b.get("ats")
        slug = (b.get("board") or "").strip().lower()
        p = _ATS_PREFIX.get(ats or "")
        if not p or not slug:
            continue
        if b.get("jobs") == 0:
            skipped_empty += 1
            continue
        key = f"{p}:{slug}"
        if key in seen:
            continue
        seen.add(key)
        boards.append(key)
    for slug in LEVER_EXTRAS:
        key = f"l:{slug}"
        if key not in seen:
            seen.add(key)
            boards.append(key)
    boards.sort()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "source": "https://github.com/groundtruthtools/ats-jobs-mcp",
        "license": "MIT",
        "fetched": dt.date.today().isoformat(),
        "skipped_empty": skipped_empty,
        "boards": boards,
    }, separators=(",", ":")))
    return len(boards)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--refresh", action="store_true",
                   help="re-download the upstream directory snapshot")
    args = p.parse_args()
    if args.refresh:
        n = refresh()
        print(f"wrote {DIRECTORY_PATH} ({n} boards)")
        return
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    boards = merge_boards(cfg)
    from collections import Counter
    c = Counter(a for a, _ in boards)
    print(f"directory+watchlist={len(boards)}  {dict(c)}  "
          f"lookback_days={lookback_days(cfg)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(e, file=sys.stderr)
        sys.exit(1)
