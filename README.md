# job-scout

Agentic job-opportunity screener. Every morning a scheduled Cursor Automation
pulls fresh postings (< 7 days old) straight from company ATS endpoints — the
source underneath career pages, hours-to-days before postings hit aggregators —
scores each against a personal fit profile with Claude, and ends its run with a
ranked digest. No hits, no noise.

## How it works

```
config.yaml watchlist
        │
        ▼
ATS fetchers (Greenhouse / Lever / Ashby public JSON) + HN Who's Hiring
        │
        ▼
freshness (<7d) → keyword prefilter → location filter → seen.json dedupe
        │
        ▼
Scorer (rubric = profile.md): the automation agent itself on Cursor models,
or Claude Haiku for local runs
        │
        ▼
digest.md → automation run summary · seen.json committed back to the repo
```

Cost: prefiltering keeps scored postings to a few dozen per run. In the
automation, scoring is done by the agent itself — no API keys, covered by
your Cursor subscription. Local runs use Haiku at fractions of a cent.

## Setup (one time, ~10 minutes)

1. The repo lives on Cursor origin (private). Clone it elsewhere with
   `origin repo clone <org>/job-scout`.
2. Local environment:
   ```
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   ```
3. Validate/expand the watchlist (starter set last validated 2026-08-19):
   ```
   .venv/bin/python discover.py anthropic ramp sierra
   ```
   Fix any tokens in `config.yaml` that come back ✗.
4. Test the pipeline (no key needed — stops after filtering and writes
   `candidates.json`):
   ```
   .venv/bin/python -m scout.main --no-score
   ```
   To test scoring locally too, get a key from console.anthropic.com and run
   `ANTHROPIC_API_KEY=sk-... .venv/bin/python -m scout.main`.
5. The scheduled Cursor Automation (every day, 8:00 AM Central) checks out
   this repo, runs the scout in `--no-score` mode, scores the candidates
   itself against `profile.md`, runs `--mark-seen`, commits `seen.json` back,
   and finishes with the digest in its run summary. No API keys to manage.
6. Optional: give the automation a Slack action so it DMs you the digest
   instead of just logging it.

## Tuning

- **Too noisy** → raise `score_threshold` to 8, tighten `prefilter_keywords`.
- **Too quiet** → drop threshold to 6, loosen keywords, grow the watchlist.
- **Scores feel shallow** → pick a stronger model on the automation, or bump
  `MODEL` in `scout/score.py` to a Sonnet model for local runs.
- **Profile drift** → `profile.md` is the rubric. When your filters change
  (e.g., a PE process teaches you something new about what you want), edit it —
  the whole system re-aims instantly.

## Extending

- **More companies** is the highest-leverage change. The watchlist is the
  system's aperture. Weekly habit: notice an interesting company → run
  `discover.py` → add the token.
- **PE-specific boards** (no public APIs) — add a fetcher that scrapes and
  diffs; the pipeline only needs the same dict shape back. (Palantir's bespoke
  careers portal is the standing example.)
- **Auto-drafted outreach**: add a second Claude call for 9-10/10 hits that
  drafts a first-line-of-cover-note using profile.md. Deliberately not
  included by default — review before anything leaves your name.
