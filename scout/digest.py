"""Digest markdown: numbered, id-tagged cards the apply runbook can resolve."""
from __future__ import annotations

import re

APPLY_WEEK_MIN = 8
APPLY_FOOTER = (
    "Interested? Reply in this thread: `@Claude apply #3, #7` "
    "or `@Claude apply gh-anthropic-…`"
)

_CARD_RE = re.compile(
    r"^### (\d+)\. (\d+)/10 — (.+) @ (.+)\n"
    r"`([^`]+)`\n"
    r"(.*)\n"
    r"> (.*)\n\n"
    r"\[Posting\]\((.*)\)",
    re.M,
)
_DATE_RE = re.compile(r"^# Job Scout — (\d{4}-\d{2}-\d{2})", re.M)
_ALSO_LOOKING = "## Also looking (6–7)"
_APPLY_WEEK = "## Apply this week (8+)"


def format_card(n: int, result: dict, job: dict) -> list[str]:
    flags_list = list(result.get("flags") or [])
    if job.get("also_locations"):
        flags_list.append("also listed: " + "; ".join(job["also_locations"]))
    flags = f" · ⚠️ {', '.join(flags_list)}" if flags_list else ""
    return [
        f"### {n}. {result['score']}/10 — {job['title']} @ {job['company']}",
        f"`{job['id']}`",
        f"{job['location'] or 'location unlisted'} · posted {job['posted_days_ago']:.0f}d ago{flags}",
        f"> {result['one_liner']}",
        "",
        f"[Posting]({job['url']})",
        "",
    ]


def format_digest(hits: list[tuple[dict, dict]], today: str) -> str:
    """hits is [(score_result, job), ...] already sorted score descending."""
    high = [(i, r, j) for i, (r, j) in enumerate(hits, 1)
            if int(r["score"]) >= APPLY_WEEK_MIN]
    mid = [(i, r, j) for i, (r, j) in enumerate(hits, 1)
           if int(r["score"]) < APPLY_WEEK_MIN]
    lines = [
        f"# Job Scout — {today}",
        "",
        f"{len(hits)} match(es) above threshold. {len(high)} apply-this-week (8+).",
        "",
        APPLY_FOOTER,
        "",
    ]
    if high:
        lines += [_APPLY_WEEK, ""]
        for n, r, j in high:
            lines += format_card(n, r, j)
    if mid:
        lines += [_ALSO_LOOKING, ""]
        for n, r, j in mid:
            lines += format_card(n, r, j)
    return "\n".join(lines)


def parse_digest(text: str) -> dict:
    """Return {date, cards: [{n, score, title, company, id, meta, one_liner, url}]}."""
    date_m = _DATE_RE.search(text)
    cards = []
    for m in _CARD_RE.finditer(text):
        cards.append({
            "n": int(m.group(1)),
            "score": int(m.group(2)),
            "title": m.group(3).strip(),
            "company": m.group(4).strip(),
            "id": m.group(5),
            "meta": m.group(6).strip(),
            "one_liner": m.group(7).strip(),
            "url": m.group(8).strip(),
            "flags": (m.group(6).split("⚠️", 1)[1].strip()
                      if "⚠️" in m.group(6) else ""),
        })
    return {"date": date_m.group(1) if date_m else None, "cards": cards}


def split_for_slack(text: str) -> tuple[str, str | None]:
    """Parent message (8+ if any) and optional 'also looking' thread body.

    If nothing scored 8+, the 6–7 section is the parent so Slack is never empty.
    """
    if _ALSO_LOOKING not in text:
        return text.rstrip() + "\n", None
    pre, mid = text.split(_ALSO_LOOKING, 1)
    if _APPLY_WEEK in pre:
        parent = pre.rstrip() + "\n"
        date_m = _DATE_RE.search(text)
        date = date_m.group(1) if date_m else ""
        thread = (
            f"# Job Scout — {date} (also looking 6–7)\n\n"
            f"{APPLY_FOOTER}\n\n"
            f"{_ALSO_LOOKING}{mid}"
        )
        return parent, thread
    return text.rstrip() + "\n", None


def format_packet(
    *,
    date: str,
    job: dict,
    score: int | None = None,
    meta: str = "",
    why_me: list[str] | None = None,
    cover_note: str = "",
    screening: dict[str, str] | None = None,
    do_not_claim: list[str] | None = None,
) -> str:
    score_s = f"{score}/10" if score is not None else "unscored"
    why = why_me or ["", "", ""]
    why_lines = "\n".join(f"{i}. {b}".rstrip() for i, b in enumerate(why[:3], 1))
    screen = screening or {}
    screen_lines = "\n".join(
        f"- {k}: {screen.get(k, '')}"
        for k in ("Work authorization", "Location", "Compensation", "Start date")
    )
    dont = do_not_claim or []
    dont_block = "\n".join(f"- {x}" for x in dont) if dont else "- "
    loc = job.get("location") or "location unlisted"
    extra = f" · ⚠️ {meta}" if meta else ""
    return "\n".join([
        f"# Apply packet — {job.get('title', '')} @ {job.get('company', '')}",
        "",
        f"- date: {date}",
        f"- id: `{job.get('id', '')}`",
        f"- score: {score_s}",
        f"- location: {loc}{extra}",
        f"- apply: {job.get('url', '')}",
        "",
        "## Why me",
        why_lines,
        "",
        "## Cover note",
        cover_note,
        "",
        "## Screening",
        screen_lines,
        "",
        "## Do not claim",
        dont_block,
        "",
        "## Job description",
        job.get("description") or "",
        "",
    ])


if __name__ == "__main__":
    import pathlib
    import sys

    src = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "digest.md")
    parent, thread = split_for_slack(src.read_text())
    parent_out = src.with_name("digest-parent.md")
    thread_out = src.with_name("digest-thread.md")
    parent_out.write_text(parent)
    if thread:
        thread_out.write_text(thread)
        print(f"wrote {parent_out} and {thread_out}")
    else:
        thread_out.unlink(missing_ok=True)
        print(f"wrote {parent_out} (no 6–7 thread)")
