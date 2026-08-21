"""Fetch fresh postings from public ATS endpoints. No auth required."""
from __future__ import annotations

import datetime as dt
import html
import re

import requests

UA = {"User-Agent": "job-scout/1.0 (personal job search tool)"}
TIMEOUT = 20


def _clean(text: str, limit: int = 1500) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _days_ago(iso: str) -> float:
    try:
        ts = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return 9999
    return (dt.datetime.now(dt.timezone.utc) - ts).total_seconds() / 86400


def _greenhouse_job(token: str, j: dict, description_limit: int = 1500) -> dict:
    return {
        "id": f"gh-{token}-{j['id']}",
        "company": token,
        "title": j.get("title", ""),
        "location": (j.get("location") or {}).get("name", ""),
        "department": ", ".join(d.get("name", "") for d in j.get("departments", []) or []),
        "url": j.get("absolute_url", ""),
        "posted_days_ago": _days_ago(j.get("first_published") or j.get("updated_at", "")),
        "description": _clean(j.get("content", ""), limit=description_limit),
    }


def _lever_job(token: str, j: dict, description_limit: int = 1500) -> dict:
    created_ms = j.get("createdAt", 0)
    days = (dt.datetime.now(dt.timezone.utc).timestamp() - created_ms / 1000) / 86400
    cats = j.get("categories", {}) or {}
    return {
        "id": f"lv-{token}-{j.get('id')}",
        "company": token,
        "title": j.get("text", ""),
        "location": cats.get("location", "") or "",
        "department": cats.get("team", "") or "",
        "url": j.get("hostedUrl", ""),
        "posted_days_ago": days,
        "description": _clean(j.get("descriptionPlain") or j.get("description", ""),
                              limit=description_limit),
    }


def _ashby_job(token: str, j: dict, description_limit: int = 1500) -> dict:
    return {
        "id": f"ab-{token}-{j.get('id')}",
        "company": token,
        "title": j.get("title", ""),
        "location": j.get("location", "") or "",
        "department": j.get("department", "") or "",
        "url": j.get("jobUrl") or j.get("applyUrl", ""),
        "posted_days_ago": _days_ago(j.get("publishedAt", "")),
        "description": _clean(j.get("descriptionPlain") or "", limit=description_limit),
    }


def fetch_greenhouse(token: str) -> list[dict]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
    r = requests.get(url, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    return [_greenhouse_job(token, j) for j in r.json().get("jobs", [])]


def fetch_lever(token: str) -> list[dict]:
    url = f"https://api.lever.co/v0/postings/{token}?mode=json"
    r = requests.get(url, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    return [_lever_job(token, j) for j in r.json()]


def fetch_ashby(token: str) -> list[dict]:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true"
    r = requests.get(url, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    return [_ashby_job(token, j) for j in r.json().get("jobs", [])]


def fetch_hn_who_is_hiring(keywords: list[str], max_age_days: int) -> list[dict]:
    """Search comments in the latest 'Ask HN: Who is hiring?' thread via Algolia."""
    # search_by_date sorts by recency, so a text query returns whatever recent
    # story loosely matches. Filter by the official bot account and exact title
    # prefix instead — this also skips the sibling "Who wants to be hired?"
    # thread posted the same minute each month.
    r = requests.get(
        "https://hn.algolia.com/api/v1/search_by_date",
        params={"tags": "story,author_whoishiring", "hitsPerPage": 10},
        headers=UA, timeout=TIMEOUT,
    )
    r.raise_for_status()
    story_id = next(
        (h["objectID"] for h in r.json().get("hits", [])
         if (h.get("title") or "").startswith("Ask HN: Who is hiring?")),
        None,
    )
    if story_id is None:
        raise RuntimeError("no 'Ask HN: Who is hiring?' thread found")

    jobs = []
    for kw in keywords:
        r = requests.get(
            "https://hn.algolia.com/api/v1/search_by_date",
            params={"query": kw, "tags": f"comment,story_{story_id}", "hitsPerPage": 50},
            headers=UA, timeout=TIMEOUT,
        )
        if not r.ok:
            continue
        for c in r.json().get("hits", []):
            days = _days_ago(c.get("created_at", ""))
            if days > max_age_days:
                continue
            jobs.append(_hn_job(c, kw=kw, description_limit=1200))
    return jobs


def _hn_job(item: dict, kw: str = "", description_limit: int = 8000) -> dict:
    oid = item.get("objectID") or item.get("id")
    raw = item.get("comment_text") or item.get("text") or ""
    text = _clean(raw, limit=description_limit)
    title = f"HN Who's Hiring match: '{kw}'" if kw else "HN Who's Hiring"
    return {
        "id": f"hn-{oid}",
        "company": text.split("|")[0].strip()[:60] or "HN posting",
        "title": title,
        "location": "",
        "department": "",
        "url": f"https://news.ycombinator.com/item?id={oid}",
        "posted_days_ago": _days_ago(item.get("created_at") or item.get("createdAt", "")),
        "description": text,
    }


_ATS_PREFIX = {"gh": "greenhouse", "lv": "lever", "ab": "ashby"}


def parse_scout_id(scout_id: str, watchlist: dict | None = None) -> tuple[str, str, str]:
    """Return (ats, token, native_id) for a scout id like gh-anthropic-5387827008."""
    if scout_id.startswith("hn-"):
        return ("hn", "", scout_id[3:])
    prefix = scout_id[:2]
    ats = _ATS_PREFIX.get(prefix)
    if ats is None or not scout_id.startswith(prefix + "-"):
        raise ValueError(f"unknown scout id: {scout_id}")
    rest = scout_id[3:]
    tokens = list((watchlist or {}).get(ats) or [])
    for token in sorted(tokens, key=len, reverse=True):
        if rest == token:
            return (ats, token, "")
        if rest.startswith(token + "-"):
            return (ats, token, rest[len(token) + 1:])
    # Greenhouse job ids are numeric — split from the right if the token
    # isn't in this checkout's watchlist (stale digest, renamed slug).
    if ats == "greenhouse" and "-" in rest:
        token, native = rest.rsplit("-", 1)
        if native.isdigit():
            return (ats, token, native)
    raise ValueError(f"cannot parse token from scout id: {scout_id}")


def fetch_one(scout_id: str, watchlist: dict | None = None,
              description_limit: int = 8000) -> dict:
    """Re-fetch a single posting by scout id. Raises if the req is gone."""
    ats, token, native = parse_scout_id(scout_id, watchlist)
    if not native:
        raise ValueError(f"scout id missing native job id: {scout_id}")
    if ats == "greenhouse":
        url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{native}"
        r = requests.get(url, headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        return _greenhouse_job(token, r.json(), description_limit=description_limit)
    if ats == "lever":
        url = f"https://api.lever.co/v0/postings/{token}/{native}"
        r = requests.get(url, headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        return _lever_job(token, r.json(), description_limit=description_limit)
    if ats == "ashby":
        url = (f"https://api.ashbyhq.com/posting-api/job-board/{token}"
               "?includeCompensation=true")
        r = requests.get(url, headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        for j in r.json().get("jobs", []):
            if str(j.get("id")) == native:
                return _ashby_job(token, j, description_limit=description_limit)
        raise LookupError(f"ashby job {native} not on {token} board")
    if ats == "hn":
        url = f"https://hn.algolia.com/api/v1/items/{native}"
        r = requests.get(url, headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        return _hn_job(r.json(), description_limit=description_limit)
    raise ValueError(f"unknown ats {ats}")
