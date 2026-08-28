# job-scout

Agentic job-opportunity screener. Twice a day a scheduled Claude routine
censuses ~7k public Greenhouse / Lever / Ashby boards for roles posted in
the last **2 days**, plus any Workday URLs and HN Who's Hiring, scores each
hit against a personal fit profile, and posts a ranked digest to Slack.
Reply in that thread with `@Claude apply #3` to get a paste-ready
application packet; you submit the ATS form yourself. No hits, no noise.

## How it works

```
data/ats-boards.json  (~7k G/L/A boards)  ∪  watchlist (Workday / extras)
        │
        ▼
title-only census → freshness (<2d) → keyword prefilter → US location
        │
        ▼
detail-fetch survivors → seen.json dedupe → city collapse
        │
        ▼
Scorer (rubric = attached profile.md): the routine's Claude agent scores
candidates itself; local runs can use Haiku via the Anthropic API
        │
        ▼
digest.md → Slack (#job-scout): 8+ as the parent, 6–7 as a thread reply
        │
        ▼
@Claude apply #N  →  re-fetch JD  →  applications/<date>-<id>.md
                  →  packet posted back to the Slack thread
        │
        ▼
seen.json + digests/ + applications/ committed back to the repo
(profile.md / resume.md / apply-facts.md stay out of git)
```

The aperture is **role queries** (`prefilter_keywords`), not a company list.
The watchlist is a priority overlay (Workday URLs, plus any G/L/A slug missing
from the directory). Refresh the directory with `python -m scout.boards --refresh`.

Cost: the census is title-only; only keyword hits get a JD and a score. The
routine draws from a normal Claude subscription (Pro allows 5 routine runs/day;
this uses 2). Local scoring with Haiku is fractions of a cent.

## Personal inputs (not in git)

Three markdowns are **yours**, not the repo. They never get committed:

| File | Role |
|------|------|
| `profile.md` | Scoring rubric for each digest |
| `resume.md` | Work history for apply packets |
| `apply-facts.md` | ATS screening facts for apply packets |

The scheduled job gets them as **prompt attachments**. Claude Code routines
don't have a separate file-picker, so the saved Instructions *are* that
surface: either paste the files into the prompt, or generate the prompt
with them already inlined.

```
cp examples/profile.md profile.md       # then fill it in
cp examples/resume.md resume.md
cp examples/apply-facts.md apply-facts.md
.venv/bin/python -m scout.prompt          # scout job → stdout
.venv/bin/python -m scout.prompt --apply  # apply job → stdout
```

Paste the printed text into the routine's Instructions. Re-run
`python -m scout.prompt` whenever you edit the markdowns, and replace the
Instructions so the next run picks up the change.

Each routine reads whatever was attached to **that** job. Two people can
point two routines at the same public repo (or two forks) and attach
different files — Claude does not look up a profile from git.

## Setup (one time, ~10 minutes)

1. Fork this repo or click **Use this template**, then clone **your** copy.
   Claude Code cloud routines need GitHub. Your fork can stay **public**:
   personal markdowns are gitignored. You need the fork so the routine can
   commit `seen.json` / `digests/` (you cannot push those to someone else's
   repo).
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
   .venv/bin/python discover.py https://adobe.wd5.myworkdayjobs.com/external_experienced
   ```
   Fix any Greenhouse/Lever/Ashby tokens in `config.yaml` that come back ✗.
   A Workday hit prints the careers URL to paste under `watchlist.workday`
   (you add that key; the agent does not edit `config.yaml`).
4. Test the pipeline (no key needed — stops after filtering and writes
   `candidates.json`). A short census:
   ```
   .venv/bin/python -m scout.main --no-score --census-limit 80
   ```
   Full census (~7k boards, a few minutes):
   ```
   .venv/bin/python -m scout.main --no-score
   ```
   Watchlist-only (no directory sweep): `--no-census`.
5. One-time: connect Slack at claude.ai → Settings → Connectors (a free
   personal workspace with a `#job-scout` channel keeps this separate from
   work). Invite Claude to `#job-scout`.
6. Fill `resume.md` and `apply-facts.md` (copied from `examples/`). The
   apply agent will refuse to draft if `resume.md` is still empty, and will
   leave screening fields blank rather than invent them. Never put these in
   `profile.md` (that's the scoring rubric only).
7. Point Slack `@Claude` at **your** GitHub copy so apply mentions actually
   run the Apply runbook (not a generic chat reply). It also needs your
   resume: attach `resume.md` / `apply-facts.md` / `profile.md` to that
   Claude Project, or paste `python -m scout.prompt --apply` into a small
   apply routine. Then `@Claude apply #3` in the digest thread is enough —
   numbers, scout ids, and URLs are in the parent message.
   - Fallback if Slack Claude has no repo access: a second Claude Code
     cloud routine, every few hours, whose prompt is the output of
     `python -m scout.prompt --apply` plus "Read new replies on today's
     `#job-scout` digest thread. For any `apply …` line, run the Apply
     runbook and reply in that thread with the packet."
     Pro allows 5 routine runs/day; the scout uses 2, so this can
     consume the rest. Same Custom network domains as the scout routine.
8. Create the scout routine at claude.ai/code/routines → New routine → Cloud:
   - Repo: **your** GitHub copy (for `seen.json` / `digests/` commits)
   - Schedule: **twice daily, 8:00 AM and 8:00 PM Central**. If the editor
     only accepts one time, make two routines with the same prompt. A 12-hour
     cadence plus a 2-day lookback means one missed run still catches the req
     (max delay ~2 days after `first_published`).
   - Connector: Slack
   - Prompt: paste the output of `.venv/bin/python -m scout.prompt`
     (use `--channel other-name` if your Slack channel isn't `#job-scout`).
     That inlines `profile.md`. Do not point the routine at a repo that
     contains a real resume.

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

   Workday boards are per-company hosts (`nvidia.wd5.myworkdayjobs.com`). Add
   each tenant host you put under `watchlist.workday`, or `*.myworkdayjobs.com`
   if the environment accepts a wildcard.

   Prefer a dedicated environment named `job-scout` over widening Default,
   so other Claude Code cloud sessions stay on Trusted. Save, then Run now.
   If everything is still blocked, the run fails loudly (`sources_ok=0`
   exits nonzero) rather than posting a false "no candidates today".

## Runbook (what the routine executes)

0. Materialize personal inputs. They are not in git. In order:
   - If this session attached `profile.md` / `resume.md` / `apply-facts.md`,
     write them into the checkout with those names.
   - Else write the prompt's `<profile>` block (and `<resume>` /
     `<apply-facts>` if present) to the same filenames.
   - Else if `profile.md` already exists on disk, use it.
   - If `profile.md` is still missing, post to Slack that the routine is
     missing its profile attachment and stop (commit nothing).
   Never commit these three files.
1. `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
2. `.venv/bin/python -m scout.main --no-score` — censuses the G/L/A directory
   (title-only, 2-day lookback) plus watchlist Workday/HN, collapses
   same-role multi-city postings to the best city in `city_priority`
   (Chicago → NYC → Atlanta → SF → other US), writes `candidates.json`.
   Dropped city clones are on each winner as `collapsed_ids` / `also_locations`
   — `--mark-seen` still records them. Read the summary line
   (`lookback_days=… census … sources_ok=…`):
   - If it exits nonzero (`census outage` or most sources failed), that's an
     outage, not an empty run — post the error output to Slack and stop
     (commit nothing).
   - If sources are healthy and it reports 0 candidates, post "no candidates
     this run" to Slack and stop (commit nothing).
3. Read `profile.md` (the rubric just materialized) and `candidates.json`.
   Score each candidate 0-10, applying the rubric literally. Cast a wide
   net: 6+ is worth a look; 8+ means apply this week. Building is a plus,
   not a gate — AI strategy and growth strategy score HIGH even without a
   build mandate. Do not auto-kill consulting; AI-adjacent work at a firm
   the candidate would learn from can score MID or HIGH.
4. Write `digest.md` with only candidates scoring >= `score_threshold` in
   `config.yaml`, sorted by score descending, **globally numbered**, in the
   digest format below. Hits at 8+ go under `## Apply this week (8+)`; 6–7
   go under `## Also looking (6–7)`. Numbering is continuous across both
   sections so `#3` is unique. If there are hits, also copy the **full**
   `digest.md` (both sections) to `digests/<YYYY-MM-DD>-<HHMM>.md` (a committed
   per-run archive — twice-daily runs must not overwrite each other). Apply
   `#N` against that run's file, or the latest `digests/<date>-*.md`.
5. Post to `#job-scout` on Slack **before** committing seen state. Split so
   Slack stays inside its size limit (a 90-hit blob can truncate, which
   breaks `#N`):
   ```
   .venv/bin/python -m scout.digest
   ```
   writes gitignored `digest-parent.md` (8+ plus header/footer) and, when
   needed, `digest-thread.md`, `digest-thread-2.md`, … (6–7 and any overflow,
   same global numbers, each under Slack's ~5k-char cap). Then:
   - Parent message: the contents of `digest-parent.md`.
   - Thread replies, in order: each `digest-thread*.md` as a reply on that
     parent (not as new channel messages).
   - If nothing scored 8+, `digest-parent.md` is the 6–7 section (never an
     empty parent).
   - If nothing cleared the threshold, post "no hits this run".
   If delivery fails, stop here so today's candidates resurface next run.
6. `.venv/bin/python -m scout.main --mark-seen` — folds this run's candidates
   into `seen.json` so they're never re-scored. Does not affect apply
   packets; apply is a separate queue.
7. `git pull --rebase` against **`main`**, then commit `seen.json` (and
   `digests/` if written) **on `main`** ("scout: update seen state") and
   push `main`. The next run clones the default branch — a commit left on
   the session `claude/…` branch will not be seen, and the same candidates
   will be scored again. If this session started on a `claude/` branch,
   checkout `main`, merge the seen-state commit, and push `main`. Do not
   finish with an unmerged `claude/` branch. If the rebase conflicts on
   `seen.json`, resolve by unioning the entries of both versions (it's a
   flat `{id: date}` object; on a duplicate id keep the earlier date).

Digest format:

```markdown
# Job Scout — <YYYY-MM-DD>

<N> match(es) above threshold. <K> apply-this-week (8+).

Interested? Reply in this thread: `@Claude apply #3, #7` or `@Claude apply gh-anthropic-…`

## Apply this week (8+)

### 1. <score>/10 — <title> @ <company>
`<scout-id>`
<location or "location unlisted"> · posted <N>d ago · ⚠️ <flags, if any>
> <one-liner, 15 words max>

[Posting](<url>)

## Also looking (6–7)

### 13. <score>/10 — <title> @ <company>
`<scout-id>`
<location or "location unlisted"> · posted <N>d ago · ⚠️ <flags, if any>
> <one-liner, 15 words max>

[Posting](<url>)
```

The scout id (`gh-anthropic-5387827008`, `ab-cursor-…`, `lv-…`, `wd-adobe-…`,
`hn-…`) is the stable handle. Company + title is not unique (office clones).
Omit a section heading when that bucket is empty.

Never edit `config.yaml` or the attached `profile.md` / `resume.md` /
`apply-facts.md`. On any failure before step 6, post the error to Slack and
commit nothing; a failure in steps 6-7 should still be reported to Slack
after retrying once.

## Apply runbook (on `@Claude apply …`)

Harness-agnostic: Slack Claude with this repo attached, a Cursor/Claude Code
session, or the polling-routine fallback. Do not auto-draft every 8+ hit;
only run this when the user asks. Do not submit the ATS form. Do not email
the company.

Trigger examples (reply in the digest thread):

- `@Claude apply #3, #7`
- `@Claude apply gh-anthropic-5387827008`
- `@Claude apply the Anthropic FDE role`

Steps:

1. Resolve to scout ids. `#N` → that run's `digests/<YYYY-MM-DD>-<HHMM>.md`
   (latest file that day if unspecified) or the parent Slack message /
   working `digest.md`. Fuzzy title → if more than one match, **ask which id**,
   do not guess.
   ```
   .venv/bin/python -m scout.apply --digest digests/<YYYY-MM-DD>-<HHMM>.md 3 7
   ```
   That re-fetches the JD from the ATS (do not rely on `candidates.json`;
   it is gone after `--mark-seen`) and prints JSON. If the posting is gone,
   say so and stop for that id. If there is no public apply URL, say so
   and stop.
2. Materialize attached inputs the same way as Runbook step 0, then read
   `profile.md` (fit + seniority calibration), `resume.md` (work history),
   and `apply-facts.md` (screening). If `resume.md` has nothing under
   `## Paste`, refuse and ask the user to attach a resume. Never invent
   employment, education, or contact details.
3. Write `applications/<YYYY-MM-DD>-<scout-id>.md` in the packet format
   below. Optional: `python -m scout.apply --stub <id>` writes a skeleton
   (header + JD) if the file does not already exist — then fill the prose
   sections. Do not overwrite a packet that already has a cover note.
4. Post the packet (why-me, cover note, screening, apply URL — skip the
   raw JD if it makes the Slack message huge) back to the same Slack
   thread. Post, then `git pull --rebase`, commit `applications/`
   ("scout: apply packet <company> <id>"), and push. If Slack fails, still
   keep the file and commit it so the draft is not lost.
5. Never mark-seen as part of this flow. Never edit `resume.md` or
   `apply-facts.md`.

Packet format:

```markdown
# Apply packet — <title> @ <company>

- date: <YYYY-MM-DD>
- id: `<scout-id>`
- score: <N>/10
- location: <location> · <flags from the digest, if any>
- apply: <url>

## Why me
1. <bullet mapped to the JD>
2. <bullet>
3. <bullet>

## Cover note
<~120 words for the ATS text box>

## Screening
- Work authorization: <from apply-facts.md, or omit>
- Location: <from apply-facts.md, or omit>
- Compensation: <from apply-facts.md, or omit>
- Start date: <from apply-facts.md, or omit>

## Do not claim
- <from profile.md seniority calibration — e.g. not a 5-year production SWE>

## Job description
<re-fetched JD; archive only, do not dump this whole block into Slack>
```

## Tuning

- **Too noisy** → raise `score_threshold` to 7 or 8, tighten `prefilter_keywords`.
- **Too quiet** → drop threshold to 5, loosen keywords. Growing the watchlist
  only helps Workday / missing directory slugs — the census already covers
  ~7k Greenhouse/Ashby boards.
- **Scores feel shallow** → the routine uses your plan's Claude model; for
  local runs, bump `MODEL` in `scout/score.py` to a Sonnet model.
- **Profile drift** → edit local `profile.md`, re-run `python -m scout.prompt`,
  and replace the routine Instructions. The next run re-aims instantly.
- **Stale directory** → `python -m scout.boards --refresh` and commit
  `data/ats-boards.json`.

## Extending

- **Role queries** are the aperture (`prefilter_keywords`). The census drops
  the tokens `data` and `platform` (too broad across 7k boards) unless you
  set `census.keywords` in `config.yaml`. Greenhouse list matches **title**
  only; Lever/Ashby include department. Watchlist Workday/HN still use the
  full keyword list.
- **Workday** — no public slug API. Paste a `*.myworkdayjobs.com` careers
  (or job) URL into `watchlist.workday`. `discover.py <url>` confirms it.
  The poller POSTs the CXS list at 20 rows, drops stale/non-keyword titles,
  then GETs detail only for survivors — same job dict as Greenhouse. Do not
  start with giant boards (NVIDIA-scale); pick companies you actually want.
  Exa is not in the pipeline (search index, not a complete board dump).
- **PE-specific / closed APIs** — EvenUp's Ashby page exists but the public
  posting API 404s. Add a fetcher that scrapes and diffs; the pipeline only
  needs the same dict shape back.
- **Apply packets** are on-demand via the Apply runbook, not auto-sent.
  Browser auto-fill / ATS submit is deliberately out of scope.
