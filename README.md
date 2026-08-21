# job-scout

Agentic job-opportunity screener. Every morning a scheduled Claude routine
pulls fresh postings (< 7 days old) straight from company ATS endpoints — the
source underneath career pages, hours-to-days before postings hit aggregators —
scores each against a personal fit profile, and posts a ranked digest to
Slack. No hits, no noise.

## How it works

```
config.yaml watchlist
        │
        ▼
ATS fetchers (Greenhouse / Lever / Ashby public JSON) + HN Who's Hiring
        │
        ▼
freshness (<7d) → keyword prefilter → US location filter → seen.json dedupe
        │
        ▼
Scorer (rubric = profile.md): the routine's Claude agent scores candidates
itself; local runs can use Haiku via the Anthropic API
        │
        ▼
digest.md → Slack (#job-scout) · seen.json + digests/ committed back to the repo
```

Cost: prefiltering keeps scored postings to a few dozen per run. The routine
draws from a normal Claude subscription (Pro allows 5 routine runs/day; this
uses 1). Local scoring with Haiku is fractions of a cent.

## Setup (one time, ~10 minutes)

1. The repo lives on GitHub (private — routines require GitHub) with a copy
   on Cursor origin. Clone: `gh repo clone rarejae/job-scout` or
   `origin repo clone rarejae/job-scout`.
2. Local environment:
   ```
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   ```
   (Add `-r requirements-score.txt` only if you'll score locally via the API —
   the routine doesn't need it.)
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
   To test scoring locally too, install `requirements-score.txt`, get a key
   from console.anthropic.com, and run
   `ANTHROPIC_API_KEY=sk-... .venv/bin/python -m scout.main`.
5. One-time: connect Slack at claude.ai → Settings → Connectors (a free
   personal workspace with a `#job-scout` channel keeps this separate from
   work).
6. Create the routine at claude.ai/code/routines → New routine → Cloud:
   - Repo: `rarejae/job-scout`
   - Schedule: daily, 8:00 AM Central
   - Connector: Slack
   - Prompt: "Run the daily job-scout pipeline exactly as documented in the
     Runbook section of README.md, then post the digest (or a one-line 'no
     hits today') to the #job-scout Slack channel."

   Requires Claude Code on the web enabled; Pro includes 5 routine runs/day.

   ⚠️ Network access: the Default environment is **Trusted**, which only
   allows package registries — job-board APIs get `403 Forbidden` on CONNECT.
   In the routine editor, click the cloud-environment icon below Instructions,
   open the environment settings, set **Network access** to **Custom**, keep
   **Also include default list of common package managers** checked (needed
   for pip), and add these allowed domains (one per line):

   ```
   boards-api.greenhouse.io
   api.ashbyhq.com
   api.lever.co
   hn.algolia.com
   ```

   Prefer a dedicated environment named `job-scout` over widening Default,
   so other Claude Code cloud sessions stay on Trusted. Save, then Run now.
   If everything is still blocked, the run fails loudly (`sources_ok=0`
   exits nonzero) rather than posting a false "no candidates today".

## Runbook (what the routine executes)

1. `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
2. `.venv/bin/python -m scout.main --no-score` — fetches and filters, writes
   `candidates.json`. Read its summary line (`sources_ok=… sources_failed=…`):
   - If it exits nonzero or most sources failed, that's an outage, not an
     empty day — post the error output to Slack and stop (commit nothing).
   - If sources are healthy and it reports 0 candidates, post "no candidates
     today" to Slack and stop (commit nothing).
3. Read `profile.md` (the rubric) and `candidates.json`. Score each candidate
   0-10, applying the rubric literally. Cast a wide net: 6+ is worth a look;
   8+ means apply this week. Building is a plus, not a gate — AI strategy
   and growth strategy score HIGH even without a build mandate. Do not
   auto-kill consulting; AI-adjacent work at a firm he'd learn from can
   score MID or HIGH.
4. Write `digest.md` with only candidates scoring >= `score_threshold` in
   `config.yaml`, sorted by score descending, in the digest format below.
   If there are hits, also copy it to `digests/<YYYY-MM-DD>.md` (a committed
   archive — nothing is lost if delivery fails, and history helps tuning).
5. Post the full `digest.md` to `#job-scout` on Slack (or "no hits this run"
   if nothing cleared the threshold). Post BEFORE committing seen state:
   if delivery fails, stop here so today's candidates resurface next run.
6. `.venv/bin/python -m scout.main --mark-seen` — folds today's candidates
   into `seen.json` so they're never re-scored.
7. `git pull --rebase`, then commit `seen.json` (and `digests/` if written)
   to `main` ("scout: update seen state") and push. If the rebase conflicts
   on `seen.json`, resolve by unioning the entries of both versions (it's a
   flat `{id: date}` object; on a duplicate id keep the earlier date).

Digest format:

```markdown
# Job Scout — <YYYY-MM-DD>

<N> match(es) above threshold.

### <score>/10 — <title> @ <company>
<location or "location unlisted"> · posted <N>d ago · ⚠️ <flags, if any>
> <one-liner, 15 words max>

[Posting](<url>)
```

Never edit `config.yaml` or `profile.md`. On any failure before step 6, post
the error to Slack and commit nothing; a failure in steps 6-7 should still be
reported to Slack after retrying once.

## Tuning

- **Too noisy** → raise `score_threshold` to 7 or 8, tighten `prefilter_keywords`.
- **Too quiet** → drop threshold to 5, loosen keywords, grow the watchlist.
- **Scores feel shallow** → the routine uses your plan's Claude model; for
  local runs, bump `MODEL` in `scout/score.py` to a Sonnet model.
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
