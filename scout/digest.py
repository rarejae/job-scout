"""Digest markdown: numbered, id-tagged cards the apply runbook can resolve."""
from __future__ import annotations

import datetime as dt
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
# Slack connector truncates around 5k; stay under so `#N` never gets cut mid-card.
SLACK_CHAR_LIMIT = 4800


def archive_relpath(when: dt.datetime | None = None) -> str:
    """Per-run archive name so a twice-daily cadence does not overwrite."""
    when = when or dt.datetime.now()
    return f"digests/{when:%Y-%m-%d-%H%M}.md"


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


def _extract_cards(section: str) -> list[str]:
    return [p for p in re.split(r"(?=^### )", section, flags=re.M) if p.startswith("###")]


def _split_sections(text: str) -> tuple[str, list[str], list[str]]:
    """Preamble (title/counts/footer), 8+ cards, 6–7 cards."""
    if _APPLY_WEEK in text:
        top, rest = text.split(_APPLY_WEEK, 1)
        if _ALSO_LOOKING in rest:
            high_part, mid_part = rest.split(_ALSO_LOOKING, 1)
            return top, _extract_cards(high_part), _extract_cards(mid_part)
        return top, _extract_cards(rest), []
    if _ALSO_LOOKING in text:
        top, mid_part = text.split(_ALSO_LOOKING, 1)
        return top, [], _extract_cards(mid_part)
    return text, _extract_cards(text), []


def _fill(header: str, cards: list[str], limit: int) -> tuple[str, list[str]]:
    """One Slack message and the cards that did not fit. Never splits a card."""
    buf = header
    for i, card in enumerate(cards):
        candidate = buf + card
        if i > 0 and len(candidate) > limit:
            return buf.rstrip() + "\n", cards[i:]
        buf = candidate
    return buf.rstrip() + "\n", []


def split_for_slack(
    text: str, limit: int = SLACK_CHAR_LIMIT,
) -> tuple[str, list[str]]:
    """Parent message plus zero or more thread replies, each within `limit`.

    8+ stays in the parent when it fits. Overflow 8+ cards and the 6–7
    section become thread replies, split on card boundaries. If nothing
    scored 8+, the 6–7 section is the parent so Slack is never empty.
    """
    date_m = _DATE_RE.search(text)
    date = date_m.group(1) if date_m else ""
    top, high, mid = _split_sections(text)
    top = top.rstrip() + "\n\n"

    threads: list[str] = []
    if high:
        parent, rest_high = _fill(top + _APPLY_WEEK + "\n\n", high, limit)
        cont = (
            f"# Job Scout — {date} (apply this week continued)\n\n"
            f"{APPLY_FOOTER}\n\n{_APPLY_WEEK}\n\n"
        )
        while rest_high:
            part, rest_high = _fill(cont, rest_high, limit)
            threads.append(part)
        looking_header = (
            f"# Job Scout — {date} (also looking 6–7)\n\n"
            f"{APPLY_FOOTER}\n\n{_ALSO_LOOKING}\n\n"
        )
        looking_cont = (
            f"# Job Scout — {date} (also looking 6–7 continued)\n\n"
            f"{APPLY_FOOTER}\n\n{_ALSO_LOOKING}\n\n"
        )
        rest_mid = mid
        first = True
        while rest_mid:
            hdr = looking_header if first else looking_cont
            part, rest_mid = _fill(hdr, rest_mid, limit)
            threads.append(part)
            first = False
        return parent, threads

    parent, rest_mid = _fill(top + _ALSO_LOOKING + "\n\n", mid, limit) if mid else (top, [])
    looking_cont = (
        f"# Job Scout — {date} (also looking 6–7 continued)\n\n"
        f"{APPLY_FOOTER}\n\n{_ALSO_LOOKING}\n\n"
    )
    while rest_mid:
        part, rest_mid = _fill(looking_cont, rest_mid, limit)
        threads.append(part)
    return parent, threads


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
    parent, threads = split_for_slack(src.read_text())
    parent_out = src.with_name("digest-parent.md")
    parent_out.write_text(parent)
    for old in src.parent.glob("digest-thread*.md"):
        old.unlink()
    if not threads:
        print(f"wrote {parent_out} (no thread)")
    else:
        written = []
        for i, body in enumerate(threads, 1):
            name = "digest-thread.md" if i == 1 else f"digest-thread-{i}.md"
            path = src.with_name(name)
            path.write_text(body)
            written.append(f"{path.name} ({len(body)} chars)")
        print(f"wrote {parent_out} ({len(parent)} chars) and "
              f"{len(threads)} thread file(s): {', '.join(written)}")
