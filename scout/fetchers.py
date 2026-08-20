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


def fetch_greenhouse(token: str) -> list[dict]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
    r = requests.get(url, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    jobs = []
    for j in r.json().get("jobs", []):
        jobs.append({
            "id": f"gh-{token}-{j['id']}",
            "company": token,
            "title": j.get("title", ""),
            "location": (j.get("location") or {}).get("name", ""),
            "department": ", ".join(d.get("name", "") for d in j.get("departments", []) or []),
            "url": j.get("absolute_url", ""),
            "posted_days_ago": _days_ago(j.get("first_published") or j.get("updated_at", "")),
            "description": _clean(j.get("content", "")),
        })
    return jobs


def fetch_lever(token: str) -> list[dict]:
    url = f"https://api.lever.co/v0/postings/{token}?mode=json"
    r = requests.get(url, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    jobs = []
    for j in r.json():
        created_ms = j.get("createdAt", 0)
        days = (dt.datetime.now(dt.timezone.utc).timestamp() - created_ms / 1000) / 86400
        cats = j.get("categories", {}) or {}
        jobs.append({
            "id": f"lv-{token}-{j.get('id')}",
            "company": token,
            "title": j.get("text", ""),
            "location": cats.get("location", "") or "",
            "department": cats.get("team", "") or "",
            "url": j.get("hostedUrl", ""),
            "posted_days_ago": days,
            "description": _clean(j.get("descriptionPlain") or j.get("description", "")),
        })
    return jobs


def fetch_ashby(token: str) -> list[dict]:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true"
    r = requests.get(url, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    jobs = []
    for j in r.json().get("jobs", []):
        jobs.append({
            "id": f"ab-{token}-{j.get('id')}",
            "company": token,
            "title": j.get("title", ""),
            "location": j.get("location", "") or "",
            "department": j.get("department", "") or "",
            "url": j.get("jobUrl") or j.get("applyUrl", ""),
            "posted_days_ago": _days_ago(j.get("publishedAt", "")),
            "description": _clean(j.get("descriptionPlain") or ""),
        })
    return jobs


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
            text = _clean(c.get("comment_text", ""), limit=1200)
            jobs.append({
                "id": f"hn-{c['objectID']}",
                "company": text.split("|")[0].strip()[:60] or "HN posting",
                "title": f"HN Who's Hiring match: '{kw}'",
                "location": "",
                "department": "",
                "url": f"https://news.ycombinator.com/item?id={c['objectID']}",
                "posted_days_ago": days,
                "description": text,
            })
    return jobs
