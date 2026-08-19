"""Probe the three ATS APIs for a company slug.
Usage: python discover.py stripe "stripe inc" stripe-inc
Tries each candidate slug against Greenhouse, Lever, and Ashby and reports hits.
"""
import sys

import requests

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


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    for candidate in sys.argv[1:]:
        slug = candidate.lower().replace(" ", "")
        print(f"\nProbing '{slug}':")
        probe(slug)
