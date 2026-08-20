# job-scout

Agentic job screener run by a daily scheduled Claude routine. The pipeline and
the exact steps the routine executes live in the **Runbook** section of
[README.md](README.md) — follow it for any run, scheduled or ad-hoc.

Rules that apply to every session:

- Never edit `config.yaml` or `profile.md`; the user tunes those by hand.
- `seen.json` is the dedupe state (`{id: date_first_seen}`); only change it
  via `python -m scout.main --mark-seen`.
- `digest.md` and `candidates.json` are gitignored working files;
  `digests/` is the committed archive of delivered digests.
- Post to Slack before committing seen state, so a failed delivery means the
  candidates resurface on the next run.
