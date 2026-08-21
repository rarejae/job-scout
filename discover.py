"""Probe ATS boards for a company slug, or a Workday careers URL.
Usage:
  python discover.py stripe "stripe inc" stripe-inc
  python discover.py https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite
Tries each candidate slug against Greenhouse, Lever, and Ashby.
A myworkdayjobs.com URL is probed via the Workday CXS list endpoint instead.
"""
import sys

import requests

from scout.fetchers import parse_workday_url, _workday_list_page

UA = {"User-Agent": "job-scout/1.0"}

PROBES = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{t}/jobs",
    "lever": "https://api.lever.co/v0/postings/{t}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{t}",
}


def probe(token: str) -> None:
    for ats, tmpl in PROBES.items():
        try:
            r = requests.get(tmpl.format(t=token), headers=UA, timeout=10)
            if r.ok:
                data = r.json()
                n = len(data.get("jobs", data if isinstance(data, list) else []))
                print(f"  ✓ {ats:<11} token='{token}'  ({n} open postings)")
                continue
        except Exception:
            pass
        print(f"  ✗ {ats:<11} token='{token}'")


def probe_workday(url: str) -> None:
    try:
        parsed = parse_workday_url(url)
        data = _workday_list_page(parsed, 0)
        n = data.get("total")
        batch = data.get("jobPostings") or []
        print(f"  ✓ workday     tenant={parsed['tenant']} shard={parsed['shard']} "
              f"site={parsed['site']}")
        print(f"               first page {len(batch)} jobs; reported total={n}")
        print(f"               add under watchlist.workday:")
        print(f"                 - {parsed['url']}")
        print(f"               (do not trust total on later pages; poller stops "
              f"on an empty page)")
    except Exception as e:
        print(f"  ✗ workday     {e}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    for candidate in sys.argv[1:]:
        if "myworkdayjobs.com" in candidate.lower():
            print(f"\nProbing Workday URL:")
            probe_workday(candidate)
            continue
        slug = candidate.lower().replace(" ", "")
        print(f"\nProbing '{slug}':")
        probe(slug)
