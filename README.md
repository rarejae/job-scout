# job-scout

Agentic job-opportunity screener. Every morning a scheduled Claude routine
pulls fresh postings (< 7 days old) straight from company ATS endpoints — the
source underneath career pages, hours-to-days before postings hit aggregators —
scores each against a personal fit profile, and posts a ranked digest to
Slack. Reply in that thread with `@Claude apply #3` to get a paste-ready
application packet; you submit the ATS form yourself. No hits, no noise.

## How it works

```
config.yaml watchlist
        │
        ▼
ATS fetchers (Greenhouse / Lever / Ashby / Workday CXS) + HN Who's Hiring
        │
        ▼
freshness (<7d) → keyword prefilter → US location filter → seen.json dedupe
        │
        ▼
Scorer (rubric = profile.md): the routine's Claude agent scores candidates
itself; local runs can use Haiku via the Anthropic API
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
```

Cost: prefiltering keeps scored postings to a few dozen per run. The routine
draws from a normal Claude subscription (Pro allows 5 routine runs/day; this
uses 1). Local scoring with Haiku is fractions of a cent.

## Setup (one time, ~10 minutes)

1. Fork this repo or click **Use this template**, then clone **your** copy.
   Claude Code cloud routines need GitHub. This public repo ships blank
   `profile.md` / `resume.md` / `apply-facts.md` — fill those in on your
   copy. If you paste a real resume, make **your** GitHub repo **private**
   before committing. The daily routine reads `profile.md` from whichever
   repo you point it at; it does not pick a profile for you.
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
   `candidates.json`):
   ```
   .venv/bin/python -m scout.main --no-score
   ```
   To test scoring locally too, install `requirements-score.txt`, get a key
   from console.anthropic.com, and run
   `ANTHROPIC_API_KEY=sk-... .venv/bin/python -m scout.main`.
5. One-time: connect Slack at claude.ai → Settings → Connectors (a free
   personal workspace with a `#job-scout` channel keeps this separate from
   work). Invite Claude to `#job-scout`.
6. Paste a current resume into `resume.md` and fill any ATS screening facts
   in `apply-facts.md`. The apply agent will refuse to draft if `resume.md`
   is still empty, and will leave screening fields blank rather than invent
   them. Never put these in `profile.md` (that's the scoring rubric only).
7. Point Slack `@Claude` at **your** GitHub copy so apply mentions actually
   run the Apply runbook (not a generic chat reply):
   - Preferred: in Claude / Claude Code settings for Slack, attach that
     repo (or a Claude Project whose instructions are "follow the Apply
     runbook in README.md"). Then `@Claude apply #3` in the digest thread
     is enough — numbers, scout ids, and URLs are in the parent message.
   - Fallback if Slack Claude has no repo access: a second Claude Code
     cloud routine, every few hours, whose prompt is "Read new replies on
     today's `#job-scout` digest thread. For any `apply …` line, run the
     Apply runbook in README.md and reply in that thread with the packet."
     Pro allows 5 routine runs/day; the morning scout uses 1, so this can
     consume the rest. Same Custom network domains as the daily routine.
8. Create the daily routine at claude.ai/code/routines → New routine → Cloud:
   - Repo: **your** GitHub copy (the one with your filled-in `profile.md`)
   - Schedule: daily, 8:00 AM Central
   - Connector: Slack
   - Prompt: "Run the daily job-scout pipeline exactly as documented in the
     Runbook section of README.md. Post to #job-scout as specified there
     (8+ parent, 6–7 thread reply, or a one-line 'no hits today')."

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

1. `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
2. `.venv/bin/python -m scout.main --no-score` — fetches and filters, collapses
   same-role multi-city postings to the best city in `city_priority`
   (Chicago → NYC → Atlanta → SF → other US), writes `candidates.json`.
   Dropped city clones are on each winner as `collapsed_ids` / `also_locations`
   — `--mark-seen` still records them. Read the summary line
   (`sources_ok=… sources_failed=…`):
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
   `config.yaml`, sorted by score descending, **globally numbered**, in the
   digest format below. Hits at 8+ go under `## Apply this week (8+)`; 6–7
   go under `## Also looking (6–7)`. Numbering is continuous across both
   sections so `#3` is unique. If there are hits, also copy the **full**
   `digest.md` (both sections) to `digests/<YYYY-MM-DD>.md` (a committed
   archive — nothing is lost if delivery fails, and history helps tuning).
5. Post to `#job-scout` on Slack **before** committing seen state. Split so
   Slack stays inside its size limit (a 90-hit blob can truncate, which
   breaks `#N`):
   ```
   .venv/bin/python -m scout.digest
   ```
   writes gitignored `digest-parent.md` (8+ plus header/footer) and, when
   needed, `digest-thread.md` (6–7, same global numbers). Then:
   - Parent message: the contents of `digest-parent.md`.
   - Thread reply, if `digest-thread.md` was written: post it as a reply
     on that parent.
   - If nothing scored 8+, `digest-parent.md` is the 6–7 section (never an
     empty parent).
   - If nothing cleared the threshold, post "no hits this run".
   If delivery fails, stop here so today's candidates resurface next run.
6. `.venv/bin/python -m scout.main --mark-seen` — folds today's candidates
   into `seen.json` so they're never re-scored. Does not affect apply
   packets; apply is a separate queue.
7. `git pull --rebase`, then commit `seen.json` (and `digests/` if written)
   to `main` ("scout: update seen state") and push. If the rebase conflicts
   on `seen.json`, resolve by unioning the entries of both versions (it's a
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

Never edit `config.yaml` or `profile.md`. On any failure before step 6, post
the error to Slack and commit nothing; a failure in steps 6-7 should still be
reported to Slack after retrying once.

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

1. Resolve to scout ids. `#N` → that day's `digests/<YYYY-MM-DD>.md` (or
   the parent Slack message / working `digest.md`). Fuzzy title → if more
   than one match, **ask which id**, do not guess.
   ```
   .venv/bin/python -m scout.apply --digest digests/<YYYY-MM-DD>.md 3 7
   ```
   That re-fetches the JD from the ATS (do not rely on `candidates.json`;
   it is gone after `--mark-seen`) and prints JSON. If the posting is gone,
   say so and stop for that id. If there is no public apply URL, say so
   and stop.
2. Read `profile.md` (fit + seniority calibration), `resume.md` (work
   history), and `apply-facts.md` (screening). If `resume.md` has nothing
   under `## Paste`, refuse and ask the user to paste a resume. Never
   invent employment, education, or contact details.
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
- **Too quiet** → drop threshold to 5, loosen keywords, grow the watchlist.
- **Scores feel shallow** → the routine uses your plan's Claude model; for
  local runs, bump `MODEL` in `scout/score.py` to a Sonnet model.
- **Profile drift** → `profile.md` is the rubric. When your filters change
  (e.g., a PE process teaches you something new about what you want), edit it —
  the whole system re-aims instantly.

## Extending

- **More companies** is the highest-leverage change. The watchlist is the
  system's aperture. Weekly habit: notice an interesting company → run
  `discover.py` → add the token (or, for Workday, the careers URL).
- **Workday** — no public slug API. Paste a `*.myworkdayjobs.com` careers
  (or job) URL into `watchlist.workday`. `discover.py <url>` confirms it.
  The poller POSTs the CXS list at 20 rows, drops stale/non-keyword titles,
  then GETs detail only for survivors — same job dict as Greenhouse. Do not
  start with giant boards (NVIDIA-scale); pick companies you actually want.
  Exa is not in the daily pipeline (search index, not a complete board dump).
- **PE-specific boards** (no public APIs) — add a fetcher that scrapes and
  diffs; the pipeline only needs the same dict shape back. (Palantir's bespoke
  careers portal is the standing example.)
- **Apply packets** are on-demand via the Apply runbook, not auto-sent.
  Browser auto-fill / ATS submit is deliberately out of scope.
