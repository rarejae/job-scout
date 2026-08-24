"""Print a ready-to-paste scheduled-job prompt with local inputs inlined.

Claude Code routines have no separate file-picker. The saved Instructions
*are* the attachment surface: this command embeds your gitignored markdowns
so the cloud run has them without committing PII to GitHub.

  python -m scout.prompt                         # daily digest
  python -m scout.prompt --apply                 # @Claude apply helper
  python -m scout.prompt --channel job-scout-mkt
"""
from __future__ import annotations

import argparse
import sys

from .inputs import APPLY_FACTS, PROFILE, RESUME, load_text

DAILY = """\
Run the daily job-scout pipeline exactly as documented in the Runbook
section of README.md.

Personal inputs are attached to this prompt, not committed to git. Before
step 1 of the runbook, materialize them into the checkout:
- Write the <profile> block below to profile.md
- If <resume> / <apply-facts> blocks are present, write those too
These three files are gitignored — never commit them.

Post to #{channel} as specified in the runbook (8+ parent, 6–7 thread
reply, or a one-line "no hits today").

<profile>
{profile}
</profile>
"""

APPLY = """\
You are the job-scout apply agent. Follow the Apply runbook in README.md.
Do not submit an ATS form. Do not email the company. Do not edit the
attached inputs.

Personal inputs are attached to this prompt, not committed to git. Write
them into the checkout so the runbook can open them, then never commit them:
- profile.md from <profile>
- resume.md from <resume>
- apply-facts.md from <apply-facts>

If <resume> is empty under ## Paste, refuse and ask for a resume.

<profile>
{profile}
</profile>

<resume>
{resume}
</resume>

<apply-facts>
{apply_facts}
</apply-facts>
"""


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--apply",
        action="store_true",
        help="print the apply-packet prompt (needs resume + apply-facts too)",
    )
    p.add_argument(
        "--channel",
        default="job-scout",
        help="Slack channel name without # (daily prompt only)",
    )
    args = p.parse_args()
    channel = args.channel.lstrip("#")

    try:
        profile = load_text(PROFILE)
        if args.apply:
            resume = load_text(RESUME)
            facts = load_text(APPLY_FACTS)
            text = APPLY.format(
                profile=profile.rstrip(),
                resume=resume.rstrip(),
                apply_facts=facts.rstrip(),
            )
        else:
            text = DAILY.format(channel=channel, profile=profile.rstrip())
    except SystemExit as e:
        print(e, file=sys.stderr)
        sys.exit(1)

    sys.stdout.write(text)
    if not text.endswith("\n"):
        sys.stdout.write("\n")


if __name__ == "__main__":
    main()
