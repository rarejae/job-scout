# job-scout

Agentic job screener run by a daily scheduled Claude routine. The pipeline and
the exact steps the routine executes live in the **Runbook** section of
[README.md](README.md) — follow it for any run, scheduled or ad-hoc. Drafting
an application packet is a separate flow: follow the **Apply runbook** in
[README.md](README.md).

Rules that apply to every session:

- `profile.md`, `resume.md`, and `apply-facts.md` are personal inputs. They
  arrive as attachments / `<profile>` blocks on the scheduled job, or as
  gitignored local files. Never edit them. Never commit them.
- Never edit `config.yaml`; the user tunes that by hand.
- `seen.json` is the dedupe state (`{id: date_first_seen}`); only change it
  via `python -m scout.main --mark-seen`.
- `digest.md` and `candidates.json` are gitignored working files;
  `digests/` is the committed archive of delivered digests.
- Application packets live in `applications/` and are only created via the
  Apply runbook. Never submit an ATS form or email a company.
- Post to Slack before committing seen state, so a failed delivery means the
  candidates resurface on the next run.
