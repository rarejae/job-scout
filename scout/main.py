"""Orchestrator. Run: python -m scout.main [--no-score | --mark-seen]
Fetch watchlist -> freshness/keyword/US-location filters -> dedupe against
seen.json -> scoring -> write digest.md.

Default mode scores with Claude (needs ANTHROPIC_API_KEY). --no-score stops
after the filters and writes candidates.json so an automation agent can do
the scoring itself; --mark-seen folds those candidate ids into seen.json
once scoring has succeeded.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import re
import sys

import yaml

from . import fetchers
from .digest import format_digest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SEEN_PATH = ROOT / "seen.json"
DIGEST_PATH = ROOT / "digest.md"
CANDIDATES_PATH = ROOT / "candidates.json"


def load_seen() -> dict[str, str]:
    """id -> ISO date first seen. Tolerates the legacy plain-list format."""
    if not SEEN_PATH.exists():
        return {}
    data = json.loads(SEEN_PATH.read_text())
    if isinstance(data, list):  # legacy format carried no dates
        today = dt.date.today().isoformat()
        return {i: today for i in data}
    return data


def save_seen(seen: dict[str, str], max_age_days: int) -> None:
    # Prune by age, with slack past the freshness window so a pruned id can
    # never re-enter (the freshness filter already rejects anything that old).
    cutoff = (dt.date.today() - dt.timedelta(days=max_age_days + 21)).isoformat()
    kept = {i: d for i, d in sorted(seen.items()) if d >= cutoff}
    SEEN_PATH.write_text(json.dumps(kept, indent=0))


def _keyword_patterns(keywords: list[str]) -> list[re.Pattern[str]]:
    # Word boundaries so "ai" can't match inside "maintain"/"detail"/"retail".
    return [re.compile(r"\b" + re.escape(k.lower()) + r"\b") for k in keywords]


def passes_prefilter(job: dict, cfg: dict, kw_patterns: list[re.Pattern[str]]) -> bool:
    if job["posted_days_ago"] > cfg["max_age_days"]:
        return False
    # HN items were already keyword-searched at fetch time, and their synthetic
    # title/department would fail this check spuriously.
    if not job["id"].startswith("hn-"):
        hay = f"{job['title']} {job['department']}".lower()
        if not any(p.search(hay) for p in kw_patterns):
            return False
    loc_needles = [l.lower() for l in (cfg.get("locations") or [])]
    if loc_needles:
        loc = job["location"].lower()
        if loc and not any(l in loc for l in loc_needles):
            return False
    return True


def _location_rank(loc: str, buckets: list[list[str]]) -> int:
    hay = (loc or "").lower()
    for i, needles in enumerate(buckets):
        if any(n.lower() in hay for n in needles):
            return i
    return len(buckets)  # other US


# Trailing geo tokens on titles like "FDE - Poland" / "Architect (France)".
_GEO_TAIL = re.compile(
    r"(?:,|\s[-–]|[\s(])+\s*(?:north america|united states|usa|us|"
    r"chicago|new york|nyc|san francisco|sf|atlanta|seattle|boston|"
    r"austin|denver|los angeles|california|illinois|remote|"
    r"poland|germany|france|denmark|switzerland|ireland|portugal|"
    r"spain|greece|india|bangalore|mumbai|sydney|australia|tokyo|"
    r"japan|seoul|korea|paris|munich|berlin|london|dublin|uk|"
    r"united kingdom|uae|saudi arabia|brazil|emea|apac)"
    r"\)?\s*$",
    re.I,
)


def _role_key(job: dict) -> tuple[str, str]:
    if job["id"].startswith("hn-"):
        return ("hn", job["id"])
    title = job["title"].strip()
    while True:
        stripped = _GEO_TAIL.sub("", title).strip()
        if stripped == title:
            break
        title = stripped
    return (job["company"].lower(), re.sub(r"\s+", " ", title).lower())


def collapse_city_duplicates(jobs: list[dict], cfg: dict) -> list[dict]:
    """Keep one posting per role, preferring city_priority. Dropped ids stay
    on the winner as collapsed_ids so --mark-seen still eats them."""
    buckets = cfg.get("city_priority") or []
    groups: dict[tuple[str, str], list[dict]] = {}
    for j in jobs:
        groups.setdefault(_role_key(j), []).append(j)

    kept: list[dict] = []
    for key, group in groups.items():
        if key[0] == "hn" or len(group) == 1:
            kept.extend(group)
            continue
        group.sort(key=lambda j: (
            _location_rank(j.get("location") or "", buckets),
            j.get("posted_days_ago", 0),
        ))
        winner = dict(group[0])
        others = group[1:]
        winner["collapsed_ids"] = [o["id"] for o in others]
        extra_locs = sorted({
            (o.get("location") or "").strip() for o in others if (o.get("location") or "").strip()
        } - {(winner.get("location") or "").strip()})
        if extra_locs:
            winner["also_locations"] = extra_locs
        kept.append(winner)
    return kept


def mark_seen(max_age_days: int) -> None:
    if not CANDIDATES_PATH.exists():
        print("no candidates.json — nothing to mark")
        return
    seen = load_seen()
    today = dt.date.today().isoformat()
    ids = set()
    for j in json.loads(CANDIDATES_PATH.read_text()):
        ids.add(j["id"])
        ids.update(j.get("collapsed_ids") or [])
    seen.update({i: today for i in ids})
    save_seen(seen, max_age_days)
    CANDIDATES_PATH.unlink()
    print(f"marked {len(ids)} candidate ids as seen")


def main() -> None:
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    if "--mark-seen" in sys.argv:
        mark_seen(cfg["max_age_days"])
        return
    no_score = "--no-score" in sys.argv

    seen = load_seen()
    kw_patterns = _keyword_patterns(cfg["prefilter_keywords"])

    raw: list[dict] = []
    sources_ok = sources_failed = 0
    fetch_map = {
        "greenhouse": fetchers.fetch_greenhouse,
        "lever": fetchers.fetch_lever,
        "ashby": fetchers.fetch_ashby,
    }
    for ats, tokens in (cfg.get("watchlist") or {}).items():
        if ats == "workday":
            for url in tokens or []:
                try:
                    raw.extend(fetchers.fetch_workday(
                        url,
                        max_age_days=cfg["max_age_days"],
                        kw_patterns=kw_patterns,
                    ))
                    sources_ok += 1
                except Exception as e:
                    sources_failed += 1
                    print(f"[warn] workday:{url} failed: {e}", file=sys.stderr)
            continue
        fn = fetch_map.get(ats)
        if fn is None:
            print(f"[warn] unknown ats '{ats}' — skipping", file=sys.stderr)
            continue
        for token in tokens or []:
            try:
                raw.extend(fn(token))
                sources_ok += 1
            except Exception as e:  # one dead token shouldn't kill the run
                sources_failed += 1
                print(f"[warn] {ats}:{token} failed: {e}", file=sys.stderr)

    if cfg.get("hn_who_is_hiring"):
        try:
            raw.extend(fetchers.fetch_hn_who_is_hiring(cfg.get("hn_keywords", []), cfg["max_age_days"]))
            sources_ok += 1
        except Exception as e:
            sources_failed += 1
            print(f"[warn] HN fetch failed: {e}", file=sys.stderr)

    fresh: list[dict] = []
    run_ids: set[str] = set()  # HN comments can match several keywords per run
    for j in raw:
        if j["id"] in seen or j["id"] in run_ids:
            continue
        if passes_prefilter(j, cfg, kw_patterns):
            fresh.append(j)
            run_ids.add(j["id"])
    n_before = len(fresh)
    fresh = collapse_city_duplicates(fresh, cfg)
    print(f"sources_ok={sources_ok} sources_failed={sources_failed} "
          f"fetched={len(raw)} candidates_after_filters={n_before} "
          f"after_city_dedupe={len(fresh)}")
    if sources_ok == 0:
        raise SystemExit("all sources failed — outage, not an empty day; nothing written")

    if no_score:
        CANDIDATES_PATH.write_text(json.dumps(fresh, indent=2))
        print(f"{len(fresh)} candidates written to candidates.json "
              f"(seen.json untouched until --mark-seen)")
        return

    from .score import get_client, score_posting  # lazy: --no-score needs no anthropic package

    profile = (ROOT / "profile.md").read_text()
    client = get_client()
    today = dt.date.today().isoformat()
    hits = []
    for job in fresh:
        seen[job["id"]] = today  # mark scored either way; never re-score
        result = score_posting(client, profile, job)
        print(f"  {result['score']}/10  {job['company']} — {job['title']}")
        if result["score"] >= cfg["score_threshold"]:
            hits.append((result, job))

    save_seen(seen, cfg["max_age_days"])

    if not hits:
        DIGEST_PATH.write_text("")  # empty file = Action skips issue creation
        print("no hits above threshold")
        return

    hits.sort(key=lambda x: -x[0]["score"])
    DIGEST_PATH.write_text(format_digest(hits, today))
    print(f"digest written with {len(hits)} hits")


if __name__ == "__main__":
    main()
