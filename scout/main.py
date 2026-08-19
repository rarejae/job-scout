"""Orchestrator. Run: python -m scout.main [--no-score | --mark-seen]
Fetch watchlist -> freshness/keyword/location filters -> dedupe against
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

ROOT = pathlib.Path(__file__).resolve().parent.parent
SEEN_PATH = ROOT / "seen.json"
DIGEST_PATH = ROOT / "digest.md"
CANDIDATES_PATH = ROOT / "candidates.json"


def load_seen() -> set[str]:
    if SEEN_PATH.exists():
        return set(json.loads(SEEN_PATH.read_text()))
    return set()


def save_seen(seen: set[str]) -> None:
    # Cap growth; old ids age out harmlessly because freshness filter rejects them anyway.
    SEEN_PATH.write_text(json.dumps(sorted(seen)[-5000:], indent=0))


def _keyword_patterns(keywords: list[str]) -> list[re.Pattern[str]]:
    # Word boundaries so "ai" can't match inside "maintain"/"detail"/"retail".
    return [re.compile(r"\b" + re.escape(k.lower()) + r"\b") for k in keywords]


def passes_prefilter(job: dict, cfg: dict, kw_patterns: list[re.Pattern[str]]) -> bool:
    if job["posted_days_ago"] > cfg["max_age_days"]:
        return False
    hay = f"{job['title']} {job['department']}".lower()
    if not any(p.search(hay) for p in kw_patterns):
        return False
    loc = job["location"].lower()
    if loc and not any(l in loc for l in cfg["locations"]):
        return False
    return True


def mark_seen() -> None:
    if not CANDIDATES_PATH.exists():
        print("no candidates.json — nothing to mark")
        return
    seen = load_seen()
    ids = {j["id"] for j in json.loads(CANDIDATES_PATH.read_text())}
    save_seen(seen | ids)
    CANDIDATES_PATH.unlink()
    print(f"marked {len(ids)} candidate ids as seen")


def main() -> None:
    if "--mark-seen" in sys.argv:
        mark_seen()
        return
    no_score = "--no-score" in sys.argv

    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    seen = load_seen()

    raw: list[dict] = []
    fetch_map = {
        "greenhouse": fetchers.fetch_greenhouse,
        "lever": fetchers.fetch_lever,
        "ashby": fetchers.fetch_ashby,
    }
    for ats, tokens in (cfg.get("watchlist") or {}).items():
        fn = fetch_map.get(ats)
        for token in tokens or []:
            try:
                raw.extend(fn(token))
            except Exception as e:  # one dead token shouldn't kill the run
                print(f"[warn] {ats}:{token} failed: {e}", file=sys.stderr)

    if cfg.get("hn_who_is_hiring"):
        try:
            raw.extend(fetchers.fetch_hn_who_is_hiring(cfg.get("hn_keywords", []), cfg["max_age_days"]))
        except Exception as e:
            print(f"[warn] HN fetch failed: {e}", file=sys.stderr)

    kw_patterns = _keyword_patterns(cfg["prefilter_keywords"])
    fresh: list[dict] = []
    run_ids: set[str] = set()  # HN comments can match several keywords per run
    for j in raw:
        if j["id"] in seen or j["id"] in run_ids:
            continue
        if passes_prefilter(j, cfg, kw_patterns):
            fresh.append(j)
            run_ids.add(j["id"])
    print(f"fetched={len(raw)} candidates_after_filters={len(fresh)}")

    if no_score:
        CANDIDATES_PATH.write_text(json.dumps(fresh, indent=2))
        print(f"{len(fresh)} candidates written to candidates.json "
              f"(seen.json untouched until --mark-seen)")
        return

    from .score import get_client, score_posting  # lazy: --no-score needs no anthropic package

    profile = (ROOT / "profile.md").read_text()
    client = get_client()
    hits = []
    for job in fresh:
        seen.add(job["id"])  # mark scored either way; never re-score
        result = score_posting(client, profile, job)
        print(f"  {result['score']}/10  {job['company']} — {job['title']}")
        if result["score"] >= cfg["score_threshold"]:
            hits.append((result, job))

    save_seen(seen)

    if not hits:
        DIGEST_PATH.write_text("")  # empty file = Action skips issue creation
        print("no hits above threshold")
        return

    hits.sort(key=lambda x: -x[0]["score"])
    today = dt.date.today().isoformat()
    lines = [f"# Job Scout — {today}", "", f"{len(hits)} match(es) above threshold.", ""]
    for result, job in hits:
        flags = f" · ⚠️ {', '.join(result['flags'])}" if result.get("flags") else ""
        lines += [
            f"### {result['score']}/10 — {job['title']} @ {job['company']}",
            f"{job['location'] or 'location unlisted'} · posted {job['posted_days_ago']:.0f}d ago{flags}",
            f"> {result['one_liner']}",
            "",
            f"[Posting]({job['url']})",
            "",
        ]
    DIGEST_PATH.write_text("\n".join(lines))
    print(f"digest written with {len(hits)} hits")


if __name__ == "__main__":
    main()
