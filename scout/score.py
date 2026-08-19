"""Score prefiltered postings against the candidate profile with Claude."""
from __future__ import annotations

import json
import os

import anthropic

MODEL = "claude-haiku-4-5-20251001"  # cheap + fast; upgrade to a Sonnet model if scores feel shallow

SYSTEM = """You are a ruthless job-fit screener working for one specific candidate.
You will receive the candidate's profile and one job posting. Score fit 0-10.

Scoring discipline:
- The profile's HIGH/LOW criteria are the rubric. Apply them literally.
- 'AI' appearing in a posting is not enough — the question is whether building
  and operationalizing AI systems is the sanctioned core of the job.
- Penalize billable-hours consulting structures hard, even at prestigious firms.
- Be stingy: a 7+ means the candidate should actually spend time applying.

Respond ONLY with JSON, no markdown fences, exactly:
{"score": <int 0-10>, "one_liner": "<15 words max on why>", "flags": ["<any concern, e.g. 'wants 5+ yrs'>"]}"""


def score_posting(client: anthropic.Anthropic, profile: str, job: dict) -> dict:
    posting = (
        f"Company: {job['company']}\nTitle: {job['title']}\n"
        f"Location: {job['location']}\nDepartment: {job['department']}\n"
        f"Posted: {job['posted_days_ago']:.1f} days ago\n\n{job['description']}"
    )
    msg = client.messages.create(
        model=MODEL,
        max_tokens=300,
        system=SYSTEM,
        messages=[{
            "role": "user",
            "content": f"<profile>\n{profile}\n</profile>\n\n<posting>\n{posting}\n</posting>",
        }],
    )
    raw = msg.content[0].text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        out = json.loads(raw)
    except json.JSONDecodeError:
        out = {"score": 0, "one_liner": "scorer returned unparseable output", "flags": ["parse_error"]}
    out["score"] = int(out.get("score", 0))
    return out


def get_client() -> anthropic.Anthropic:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise SystemExit("ANTHROPIC_API_KEY not set")
    return anthropic.Anthropic(api_key=key)
