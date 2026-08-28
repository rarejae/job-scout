"""Title-only census across the public G/L/A board directory.

List endpoints first (Greenhouse without job HTML). Keep stubs that already
pass freshness / keywords / US location, then hydrate JDs for scoring.
"""
from __future__ import annotations

import concurrent.futures
import sys
import time
from collections import defaultdict
from typing import Callable

import requests
from urllib3.util.retry import Retry

from . import fetchers
from .boards import census_cfg, merge_boards

_RETRY = Retry(
    total=1,
    backoff_factor=0.4,
    status_forcelist=(429, 502, 503),
    allowed_methods=frozenset(["GET"]),
)


def _session(concurrency: int) -> requests.Session:
    s = requests.Session()
    s.headers.update(fetchers.UA)
    adapter = requests.adapters.HTTPAdapter(
        pool_connections=concurrency,
        pool_maxsize=concurrency,
        max_retries=_RETRY,
    )
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


def _list_board(session: requests.Session, ats: str, slug: str,
                timeout: int) -> list[dict]:
    if ats == "greenhouse":
        return fetchers.fetch_greenhouse(
            slug, content=False, session=session, timeout=timeout)
    if ats == "lever":
        return fetchers.fetch_lever(
            slug, session=session, timeout=timeout, description_limit=0)
    if ats == "ashby":
        return fetchers.fetch_ashby(
            slug, session=session, timeout=timeout, description_limit=0)
    raise ValueError(f"unknown ats {ats}")


def census_fetch(
    cfg: dict,
    passes: Callable[[dict], bool],
    *,
    limit: int | None = None,
) -> tuple[list[dict], dict]:
    """Return (hydrated jobs that passed `passes`, stats)."""
    cc = census_cfg(cfg)
    boards = merge_boards(cfg)
    if limit:
        boards = boards[:limit]
    concurrency = int(cc["concurrency"])
    timeout = int(cc["timeout"])
    session = _session(concurrency)

    listed: list[dict] = []
    ok = failed = 0
    t0 = time.time()
    n = len(boards)

    def one(item: tuple[str, str]) -> tuple[str, str, list[dict] | None, str]:
        ats, slug = item
        try:
            jobs = _list_board(session, ats, slug, timeout)
            return (ats, slug, jobs, "")
        except Exception as e:
            return (ats, slug, None, str(e)[:160])

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as ex:
        futs = [ex.submit(one, b) for b in boards]
        for i, fut in enumerate(concurrent.futures.as_completed(futs), 1):
            ats, slug, jobs, err = fut.result()
            if jobs is None:
                failed += 1
                if failed <= 8:
                    print(f"[warn] census {ats}:{slug} failed: {err}",
                          file=sys.stderr)
            else:
                ok += 1
                listed.extend(jobs)
            if i % 500 == 0 or i == n:
                print(f"census {i}/{n} boards  ok={ok} failed={failed}  "
                      f"listed={len(listed)}  {time.time()-t0:.0f}s",
                      flush=True)

    kept = [j for j in listed if passes(j)]
    need = [j for j in kept if not (j.get("description") or "").strip()]
    have = [j for j in kept if (j.get("description") or "").strip()]
    hydrated = list(have)
    hy_fail = 0

    by_board: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for job in need:
        ats = job_ats(job)
        by_board[(ats, job["company"])].append(job)

    def hydrate_board(item: tuple[tuple[str, str], list[dict]]
                      ) -> tuple[list[dict], int]:
        (ats, slug), jobs = item
        fail = 0
        out: list[dict] = []
        if ats == "greenhouse":
            for job in jobs:
                try:
                    out.append(fetchers.fetch_one(
                        job["id"], {ats: [slug]},
                        description_limit=1500,
                        session=session, timeout=timeout))
                except Exception:
                    fail += 1
                    out.append(job)
            return out, fail
        try:
            if ats == "lever":
                full = fetchers.fetch_lever(
                    slug, session=session, timeout=timeout)
            elif ats == "ashby":
                full = fetchers.fetch_ashby(
                    slug, session=session, timeout=timeout)
            else:
                return jobs, 0
            by_id = {j["id"]: j for j in full}
            for job in jobs:
                out.append(by_id.get(job["id"], job))
        except Exception:
            fail += len(jobs)
            out.extend(jobs)
        return out, fail

    if by_board:
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as ex:
            for got, nfail in ex.map(hydrate_board, by_board.items()):
                hydrated.extend(got)
                hy_fail += nfail

    stats = {
        "boards": n,
        "boards_ok": ok,
        "boards_failed": failed,
        "listed": len(listed),
        "after_filter": len(kept),
        "hydrated": len(hydrated),
        "hydrate_failed": hy_fail,
        "seconds": round(time.time() - t0, 1),
    }
    return hydrated, stats


def job_ats(job: dict) -> str:
    prefix = (job.get("id") or "")[:2]
    return {"gh": "greenhouse", "lv": "lever", "ab": "ashby"}.get(prefix, "")
