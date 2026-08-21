"""Fetch fresh postings from public ATS endpoints. No auth required."""
from __future__ import annotations

import datetime as dt
import html
import re
from urllib.parse import urlparse

import requests

UA = {"User-Agent": "job-scout/1.0 (personal job search tool)"}
TIMEOUT = 20


def _clean(text: str, limit: int = 1500) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _days_ago(iso: str) -> float:
    try:
        ts = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=dt.timezone.utc)
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


_LOCALE_SEG = re.compile(r"^[a-z]{2}(?:-[a-z]{2})?$", re.I)
_WD_HOST = re.compile(r"^([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com$", re.I)
_WD_POSTED = re.compile(
    r"Posted\s+(?:Today|Yesterday|(?P<plus>\d+)\+\s+Days?\s+Ago|(?P<n>\d+)\s+Days?\s+Ago)",
    re.I,
)


def parse_workday_url(url: str) -> dict:
    """Pull tenant, shard, and site out of a careers or job URL."""
    u = urlparse(url.strip())
    host = (u.netloc or "").lower()
    m = _WD_HOST.match(host)
    if not m:
        raise ValueError(f"not a myworkdayjobs.com URL: {url}")
    tenant, shard = m.group(1).lower(), m.group(2).lower()
    parts = [p for p in u.path.split("/") if p]
    if parts and _LOCALE_SEG.match(parts[0]):
        parts = parts[1:]
    if not parts:
        raise ValueError(f"Workday URL missing site name: {url}")
    site = parts[0]
    return {
        "url": f"https://{host}/{site}",
        "host": host,
        "tenant": tenant,
        "shard": shard,
        "site": site,
        "origin": f"https://{host}",
    }


def _workday_days_ago(posted_on: str) -> float:
    """Parse CXS list 'Posted Today' / 'Posted 3 Days Ago' / 'Posted 30+ Days Ago'."""
    if not posted_on:
        return 9999
    s = posted_on.strip()
    if re.search(r"\bToday\b", s, re.I):
        return 0.0
    if re.search(r"\bYesterday\b", s, re.I):
        return 1.0
    m = _WD_POSTED.search(s)
    if m and m.group("plus"):
        return float(m.group("plus")) + 1  # 30+ → treat as older than 30
    if m and m.group("n"):
        return float(m.group("n"))
    return 9999


def _workday_req_id(posting: dict) -> str:
    bullets = posting.get("bulletFields") or []
    if bullets:
        return str(bullets[0])
    path = posting.get("externalPath") or ""
    m = re.search(r"(JR\d+[0-9]*|[A-Z]{2,}\d+)$", path)
    return m.group(1) if m else path.rsplit("/", 1)[-1]


def _workday_headers(parsed: dict, json_body: bool = False) -> dict:
    h = {
        **UA,
        "Accept": "application/json",
        "Accept-Language": "en-US",
        "Referer": f"{parsed['origin']}/en-US/{parsed['site']}",
    }
    if json_body:
        h["Content-Type"] = "application/json"
    return h


def _workday_list_page(parsed: dict, offset: int, search_text: str = "") -> dict:
    url = (f"{parsed['origin']}/wday/cxs/{parsed['tenant']}/"
           f"{parsed['site']}/jobs")
    r = requests.post(
        url,
        json={"appliedFacets": {}, "limit": 20, "offset": offset,
              "searchText": search_text},
        headers=_workday_headers(parsed, json_body=True),
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r.json()


def _workday_detail(parsed: dict, external_path: str,
                    description_limit: int = 1500) -> dict:
    url = f"{parsed['origin']}/wday/cxs/{parsed['tenant']}/{parsed['site']}{external_path}"
    r = requests.get(url, headers=_workday_headers(parsed), timeout=TIMEOUT)
    r.raise_for_status()
    info = (r.json() or {}).get("jobPostingInfo") or {}
    req = info.get("jobReqId") or _workday_req_id({"externalPath": external_path})
    extra = info.get("additionalLocations") or []
    loc = info.get("location") or ""
    extra_bits = []
    for x in extra:
        if isinstance(x, dict):
            s = x.get("descriptor") or x.get("name") or ""
        else:
            s = str(x) if x else ""
        if s and s != loc:
            extra_bits.append(s)
    if extra_bits:
        loc = f"{loc} | {'; '.join(extra_bits)}" if loc else "; ".join(extra_bits)
    posted = info.get("startDate") or ""
    days = _days_ago(posted) if posted else _workday_days_ago(info.get("postedOn") or "")
    apply_url = (info.get("externalUrl")
                 or f"{parsed['origin']}/en-US/{parsed['site']}{external_path}")
    return {
        "id": f"wd-{parsed['tenant']}-{req}",
        "company": parsed["tenant"],
        "title": info.get("title") or "",
        "location": loc,
        "department": info.get("timeType") or "",
        "url": apply_url,
        "posted_days_ago": days,
        "description": _clean(info.get("jobDescription") or "",
                              limit=description_limit),
    }


def _title_matches(title: str, kw_patterns: list[re.Pattern[str]] | None) -> bool:
    if not kw_patterns:
        return True
    hay = (title or "").lower()
    return any(p.search(hay) for p in kw_patterns)


def fetch_workday(careers_url: str, max_age_days: int = 7,
                  kw_patterns: list[re.Pattern[str]] | None = None) -> list[dict]:
    """Poll a Workday CXS board: list at 20, detail-fetch only prefilter hits."""
    parsed = parse_workday_url(careers_url)
    jobs: list[dict] = []
    seen_ids: set[str] = set()
    offset = 0
    while offset <= 10_000:
        data = _workday_list_page(parsed, offset)
        batch = data.get("jobPostings") or []
        if not batch:
            break
        for posting in batch:
            days = _workday_days_ago(posting.get("postedOn") or "")
            if days > max_age_days:
                continue
            if not _title_matches(posting.get("title") or "", kw_patterns):
                continue
            path = posting.get("externalPath") or ""
            if not path:
                continue
            try:
                job = _workday_detail(parsed, path)
            except Exception:
                continue
            if job["id"] in seen_ids:
                continue
            seen_ids.add(job["id"])
            jobs.append(job)
        offset += 20
    return jobs


def _parse_workday_scout_id(scout_id: str, watchlist: dict | None
                            ) -> tuple[str, str, str]:
    rest = scout_id[3:]
    parsed_list = []
    for url in (watchlist or {}).get("workday") or []:
        try:
            parsed_list.append(parse_workday_url(url))
        except ValueError:
            continue
    for p in sorted(parsed_list, key=lambda x: len(x["tenant"]), reverse=True):
        t = p["tenant"]
        if rest.startswith(t + "-"):
            return ("workday", p["url"], rest[len(t) + 1:])
    raise ValueError(f"workday id {scout_id} does not match any watchlist URL")


_ATS_PREFIX = {"gh": "greenhouse", "lv": "lever", "ab": "ashby"}


def parse_scout_id(scout_id: str, watchlist: dict | None = None) -> tuple[str, str, str]:
    """Return (ats, token, native_id) for a scout id like gh-anthropic-5387827008."""
    if scout_id.startswith("hn-"):
        return ("hn", "", scout_id[3:])
    if scout_id.startswith("wd-"):
        return _parse_workday_scout_id(scout_id, watchlist)
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
    if ats == "workday":
        parsed = parse_workday_url(token)
        path = None
        data = _workday_list_page(parsed, 0, search_text=native)
        path = next(
            (j.get("externalPath") for j in (data.get("jobPostings") or [])
             if _workday_req_id(j) == native),
            None,
        )
        offset = 0
        while path is None and offset <= 10_000:
            page = _workday_list_page(parsed, offset)
            batch = page.get("jobPostings") or []
            if not batch:
                break
            path = next(
                (j.get("externalPath") for j in batch
                 if _workday_req_id(j) == native),
                None,
            )
            offset += 20
        if not path:
            raise LookupError(f"workday job {native} not on {parsed['site']}")
        return _workday_detail(parsed, path, description_limit=description_limit)
    raise ValueError(f"unknown ats {ats}")
