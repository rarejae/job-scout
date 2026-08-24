"""Resolve digest refs and re-fetch JDs. Run: python -m scout.apply [#N|id|title] ...

Prints JSON (id, title, company, url, description, digest metadata). Does not
draft prose and does not submit applications.

  python -m scout.apply 3 7
  python -m scout.apply gh-anthropic-5387827008
  python -m scout.apply --digest digests/2026-08-20.md "applied ai architect"
  python -m scout.apply --stub 3
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys

import yaml

from . import fetchers
from .digest import format_packet, parse_digest

ROOT = pathlib.Path(__file__).resolve().parent.parent
APPLICATIONS = ROOT / "applications"


def _load_watchlist() -> dict:
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    return cfg.get("watchlist") or {}


def _default_digest() -> pathlib.Path:
    working = ROOT / "digest.md"
    if working.exists() and working.stat().st_size:
        return working
    archived = sorted((ROOT / "digests").glob("*.md"))
    if not archived:
        raise SystemExit("no digest.md or digests/*.md found")
    return archived[-1]


def _expand_refs(raw: list[str]) -> list[str]:
    out = []
    for a in raw:
        for part in a.split(","):
            part = part.strip()
            if part:
                out.append(part)
    return out


def _is_digest_n(ref: str) -> bool:
    s = ref[1:] if ref.startswith("#") else ref
    return s.isdigit()


def _is_scout_id(ref: str) -> bool:
    return ref.startswith(("gh-", "lv-", "ab-", "hn-", "wd-"))


def _fuzzy(cards: list[dict], needle: str) -> list[dict]:
    n = needle.lower()
    return [c for c in cards
            if n in c["title"].lower() or n in c["company"].lower()
            or n in f"{c['title']} {c['company']}".lower()]


def resolve_refs(refs: list[str], cards: list[dict]) -> list[str]:
    """Turn #N / scout id / fuzzy title into scout ids. Exit 2 if ambiguous."""
    by_n = {c["n"]: c for c in cards}
    ids: list[str] = []
    for ref in refs:
        if _is_digest_n(ref):
            n = int(ref[1:] if ref.startswith("#") else ref)
            if n not in by_n:
                raise SystemExit(f"#{n} not in digest (have 1–{max(by_n) if by_n else 0})")
            ids.append(by_n[n]["id"])
            continue
        if _is_scout_id(ref):
            ids.append(ref)
            continue
        hits = _fuzzy(cards, ref)
        if not hits:
            raise SystemExit(f"no digest match for {ref!r} — pass a scout id or #N")
        if len(hits) > 1:
            lines = ["ambiguous — pick an id, do not guess:"]
            for c in hits:
                lines.append(f"  #{c['n']} `{c['id']}` {c['score']}/10 {c['title']} @ {c['company']}")
            raise SystemExit("\n".join(lines))
        ids.append(hits[0]["id"])
    return ids


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("refs", nargs="+", help="#N, scout id, or title/company substring")
    p.add_argument("--digest", type=pathlib.Path, help="digest markdown (default: latest)")
    p.add_argument("--stub", action="store_true",
                   help="write applications/YYYY-MM-DD-<id>.md skeletons (skip if present)")
    args = p.parse_args(argv)

    digest_path = args.digest or _default_digest()
    parsed = parse_digest(digest_path.read_text())
    cards = parsed["cards"]
    date = parsed["date"] or dt.date.today().isoformat()
    by_id = {c["id"]: c for c in cards}

    refs = _expand_refs(args.refs)
    scout_ids = resolve_refs(refs, cards)
    watchlist = _load_watchlist()

    rows = []
    for sid in scout_ids:
        try:
            job = fetchers.fetch_one(sid, watchlist)
        except Exception as e:
            raise SystemExit(f"failed to re-fetch {sid}: {e}") from e
        card = by_id.get(sid) or {}
        row = {
            "id": job["id"],
            "title": job["title"],
            "company": job["company"],
            "location": job["location"],
            "url": job["url"],
            "description": job["description"],
            "digest_n": card.get("n"),
            "score": card.get("score"),
            "one_liner": card.get("one_liner"),
            "meta": card.get("meta"),
        }
        rows.append(row)
        if args.stub:
            APPLICATIONS.mkdir(exist_ok=True)
            dest = APPLICATIONS / f"{date}-{sid}.md"
            if dest.exists():
                print(f"stub exists, not overwriting {dest}", file=sys.stderr)
                continue
            dest.write_text(format_packet(
                date=date,
                job=job,
                score=card.get("score"),
                meta=card.get("flags") or "",
            ))
            print(f"wrote {dest}", file=sys.stderr)

    json.dump(rows, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
