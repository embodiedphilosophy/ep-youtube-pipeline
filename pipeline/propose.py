"""Weekly: propose 5 videos from the Studio-Produced showcase and send them to Ops for approval."""
import datetime as dt
import json
import random

from common import claude_json, ops, showcase_videos, vimeo_id, hms

MIN_SOURCE_MIN = 22  # source must be long enough to yield a 15–20 min cut

SYSTEM = """You are the YouTube programmer for Embodied Philosophy (EP), a school of yoga philosophy,
Tantra, Buddhism and contemplative practice. Its channel publishes 15–20 minute teaching excerpts.
Pick videos that will make strong standalone YouTube episodes: a clear, searchable topic, a teacher
speaking directly (not a guided practice or Q&A logistics), and ideally a link to an upcoming EP program.
Never invent facts about a video; reason only from the metadata given. Reply with JSON only."""


def main():
    state = ops("GET", "/state")  # {used_vimeo_ids:[], upcoming_programs:[{title,start,summary}]}
    used = set(map(str, state.get("used_vimeo_ids", [])))
    vids = [v for v in showcase_videos()
            if v.get("duration", 0) >= MIN_SOURCE_MIN * 60 and vimeo_id(v["uri"]) not in used]

    # Shortlist: half by plays, half random for variety, so the archive keeps rotating
    vids.sort(key=lambda v: (v.get("stats") or {}).get("plays") or 0, reverse=True)
    top, rest = vids[:25], vids[25:]
    shortlist = top + random.sample(rest, min(15, len(rest)))

    catalog = [{"id": vimeo_id(v["uri"]), "title": v["name"], "duration": hms(v["duration"]),
                "plays": (v.get("stats") or {}).get("plays"), "created": v["created_time"][:10],
                "has_captions": bool(((v.get("metadata") or {}).get("connections") or {}).get("texttracks", {}).get("total")),
                "tags": [t["name"] for t in v.get("tags") or []],
                "description": (v.get("description") or "")[:500]} for v in shortlist]

    ask = f"""Upcoming EP programming (favour videos that seed interest in these):
{json.dumps(state.get('upcoming_programs', []), ensure_ascii=False, indent=1)}

Candidate videos:
{json.dumps(catalog, ensure_ascii=False, indent=1)}

Choose exactly 5, varied in teacher and topic. Return:
{{"proposals":[{{"id":"…","teacher":"name if evident, else null","angle":"the YouTube hook in one line",
"reason":"why this one, now (mention the related upcoming program if any)"}}]}}"""
    picks = claude_json(SYSTEM, ask)["proposals"][:5]

    by_id = {vimeo_id(v["uri"]): v for v in shortlist}
    payload = {"week_of": dt.date.today().isoformat(), "proposals": []}
    for p in picks:
        v = by_id.get(str(p["id"]))
        if not v:
            continue
        payload["proposals"].append({
            "vimeo_id": vimeo_id(v["uri"]), "title": v["name"], "link": v["link"],
            "duration_sec": v["duration"], "plays": (v.get("stats") or {}).get("plays"),
            "picture": (v.get("pictures") or {}).get("base_link"),
            "teacher": p.get("teacher"), "angle": p.get("angle"), "reason": p.get("reason")})
    ops("POST", "/proposals", json=payload)
    print(json.dumps(payload, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
