"""For one approved Vimeo video: find the strongest continuous 15–20 min stretch, cut it,
make an EP-style thumbnail, park the cut on Vimeo (unlisted), and send everything to Ops for review.

Usage: python produce.py --vimeo-id 123 [--proposal-id X] [--teacher "Name"] [--series CHITHEADS]
                         [--start 754.2 --end 1801.0] [--headline "..."] [--accent "..."]
(start/end/headline/accent are overrides staff can set from Ops when re-running.)"""
import argparse
import json
import re
import subprocess

from common import (WORK, best_source_link, claude_json, download, hms, ops, showcase_videos,
                    vimeo, vimeo_id, vimeo_set_picture, vimeo_upload)
from thumbnail import pick_frame, render

MIN_S, MAX_S = 15 * 60, 20 * 60

SYSTEM = """You are the YouTube editor for Embodied Philosophy (EP): yoga philosophy, Tantra, Buddhism,
Indian thought and contemplative practice, taught by serious scholar-practitioners.
From a timestamped transcript, choose ONE continuous stretch of 15–20 minutes that works as a
standalone YouTube episode. Rules:
- Start at the beginning of a thought, ideally with a question, claim or story that hooks within 30 seconds.
- End on a resolved point, not mid-argument. No housekeeping, logistics, tech trouble or audience roll-call.
- Prefer the densest, most vivid teaching: clear ideas, stories, striking images, Sanskrit terms explained.
- The excerpt must begin at the start of a full sentence (never mid-sentence) and "why" must describe
  what is actually said in its first lines.
- Write metadata ONLY from what is actually said in the chosen stretch, plus the source title/description.
  Never invent claims, credentials, quotes, lineages or affiliations. Tags must be words or names that
  literally appear in the stretch or the source title (no inferred traditions or institutions).
- If a transcript line looks garbled (speech-to-text error), leave it out rather than guessing its meaning.
- Use correct IAST diacritics for Sanskrit (Kuṇḍalinī, Yoginīs, Śiva).
- Title style matches the channel: a clear searchable topic, optional subtitle, and "with <Teacher>" when known,
  e.g. "What Karma Actually Means with Phil Goldberg", "Who Are the Yoginīs? Origins, History & the Seven Chakras".
  Max 90 characters. No clickbait, no ALL CAPS, no emoji.
Reply with JSON only."""


def parse_vtt(text):
    segs, cur = [], None
    for line in text.splitlines():
        m = re.match(r"(\d+:)?(\d+):(\d+)[.,](\d+)\s+-->\s+(\d+:)?(\d+):(\d+)[.,](\d+)", line.strip())
        if m:
            g = m.groups()
            t = lambda h, mi, s, ms: int((h or "0:")[:-1]) * 3600 + int(mi) * 60 + int(s) + int(ms) / 1000
            cur = [t(*g[0:4]), t(*g[4:8]), ""]
            segs.append(cur)
        elif cur is not None and line.strip() and not line.strip().isdigit():
            cur[2] = (cur[2] + " " + re.sub(r"<[^>]+>", "", line.strip())).strip()
    # merge duplicates produced by rolling captions
    out = []
    for s in segs:
        if out and s[2] == out[-1][2]:
            out[-1][1] = s[1]
        elif s[2]:
            out.append(s)
    return out


def transcript(vid, src_path=None):
    tracks = vimeo("GET", f"/videos/{vid}/texttracks").get("data", [])
    tracks.sort(key=lambda t: (not t.get("active"), not str(t.get("language", "")).startswith("en")))
    for t in tracks:
        if t.get("link"):
            import requests
            segs = parse_vtt(requests.get(t["link"], timeout=120).text)
            if len(segs) > 50:
                return segs, None
    # fallback: local Whisper on the audio
    src_path = src_path or download(best_source_link(vid), WORK / f"{vid}.mp4")
    import numpy as np
    from faster_whisper import WhisperModel
    pcm = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(src_path), "-vn", "-ac", "1",
                          "-ar", "16000", "-f", "s16le", "-"], check=True, capture_output=True).stdout
    audio = np.frombuffer(pcm, np.int16).astype(np.float32) / 32768.0
    model = WhisperModel("small.en", device="cpu", compute_type="int8", cpu_threads=4)
    segs, _ = model.transcribe(audio, vad_filter=True, beam_size=1)
    return [[s.start, s.end, s.text.strip()] for s in segs], src_path


def choose(meta, segs, teacher):
    lines = "\n".join(f"[{hms(s)}] {t}" for s, _, t in segs)
    ask = f"""Source video: {meta['name']} ({hms(meta['duration'])})
Teacher (if known): {teacher or 'unknown — infer from transcript/description if clearly stated, else null'}
Description: {(meta.get('description') or '')[:800]}

Transcript:
{lines}

Return:
{{"start":"H:MM:SS","end":"H:MM:SS","why":"two sentences on why this stretch",
"teacher":"…|null","series":"CHITHEADS|Sādhana School|Wisdom School|Embodied Philosophy",
"yt_title":"…","yt_description":"3 short paragraphs drawn from what is said, then a blank line",
"tags":["…"],"hashtags":["#…"],
"thumb_headline":"2–5 punchy words for the thumbnail (no teacher name)",
"thumb_accent":"optional 1–3 word phrase (max 20 characters) for the orange italic line, or null"}}"""
    return claude_json(SYSTEM, ask, max_tokens=3000)


def fact_check(plan, segs, start, end, meta):
    """Second pass: strike anything in the metadata not supported by the chosen stretch."""
    window = "\n".join(t for s_, _, t in segs if start <= s_ <= end)
    ask = f"""Source title: {meta['name']}
Source description: {(meta.get('description') or '')[:800]}

Transcript of the chosen excerpt:
{window}

Draft YouTube metadata:
{json.dumps({k: plan.get(k) for k in ("yt_title", "yt_description", "tags", "hashtags", "why", "thumb_headline", "thumb_accent")}, ensure_ascii=False, indent=1)}

Check every claim, name and tag against the excerpt and source title/description. Remove or rewrite
anything unsupported (inferred traditions, institutions, credentials, garbled details). Keep the style.
"why" must describe what the excerpt's first lines actually say. thumb_accent max 20 characters or null.
Return the corrected object with the same keys plus "removed": ["what you cut and why"]."""
    fixed = claude_json(SYSTEM, ask, max_tokens=3000)
    if fixed.get("removed"):
        print("Fact-check removed:", json.dumps(fixed["removed"], ensure_ascii=False))
    return {**plan, **{k: v for k, v in fixed.items() if k != "removed"}}


def to_sec(t):
    if isinstance(t, (int, float)):
        return float(t)
    p = [float(x) for x in str(t).split(":")]
    return sum(v * 60 ** i for i, v in enumerate(reversed(p)))


SENT_END = (".", "?", "!", "…", '"', "”")


def _sentence_starts(segs):
    """Indices of segments that begin a new sentence (previous segment ended a sentence)."""
    return [i for i in range(len(segs)) if i == 0 or segs[i - 1][2].rstrip().endswith(SENT_END)]


def snap(segs, start, end):
    """Snap start to the nearest sentence start and end to a sentence end, keeping 15–20 min."""
    starts = _sentence_starts(segs) or list(range(len(segs)))
    near = [i for i in starts if abs(segs[i][0] - start) <= 45] or starts
    si = min(near, key=lambda i: abs(segs[i][0] - start))
    start = segs[si][0]
    ends = [e for _, e, t in segs[si:] if MIN_S <= e - start <= MAX_S and t.rstrip().endswith(SENT_END)]
    if not ends:
        ends = [e for _, e, _ in segs[si:] if MIN_S <= e - start <= MAX_S]
    end = min(ends, key=lambda e: abs(e - end)) if ends else start + min(MAX_S, max(MIN_S, end - start))
    return max(0, start - 0.3), end + 0.6


def cut(src, start, end, out):
    dur = end - start
    vf = f"fade=t=in:st=0:d=0.5,fade=t=out:st={dur - 1.0:.2f}:d=1.0,scale=-2:'min(1080,ih)'"
    af = f"afade=t=in:st=0:d=0.4,afade=t=out:st={dur - 1.0:.2f}:d=1.0,loudnorm=I=-14:TP=-1.5:LRA=11"
    subprocess.run(["ffmpeg", "-y", "-ss", f"{start:.2f}", "-i", str(src), "-t", f"{dur:.2f}",
                    "-vf", vf, "-af", af, "-c:v", "libx264", "-preset", "medium", "-crf", "19",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
                    str(out)], check=True)
    return out


def frames(src, start, end, n=24):
    paths = []
    for i in range(n):
        t = start + (end - start) * (i + 0.5) / n
        p = WORK / f"frame_{i:02d}.jpg"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(src),
                        "-frames:v", "1", "-q:v", "2", str(p)], check=True)
        paths.append(p)
    return paths


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vimeo-id", required=True)
    ap.add_argument("--proposal-id")
    ap.add_argument("--teacher")
    ap.add_argument("--series")
    ap.add_argument("--start", type=float)
    ap.add_argument("--end", type=float)
    ap.add_argument("--headline")
    ap.add_argument("--accent")
    ap.add_argument("--thumb-only", help="Ops cut_id: just re-render that cut's thumbnail")
    ap.add_argument("--dry-run", action="store_true",
                    help="test mode: park the cut on Vimeo with its thumbnail, skip Ops")
    a = ap.parse_args()

    vid = a.vimeo_id
    if vid == "auto":  # test helper: most-played long talk in the showcase
        vids = [v for v in showcase_videos() if 40 * 60 <= v.get("duration", 0) <= 120 * 60]
        vid = vimeo_id(max(vids, key=lambda v: (v.get("stats") or {}).get("plays") or 0)["uri"])
        print("Auto-picked video", vid)
    if a.thumb_only:  # fast path when staff only change the headline/accent
        c = ops("GET", f"/cuts/{a.thumb_only}")
        src = download(best_source_link(vid), WORK / f"{vid}.mp4")
        thumb = render(pick_frame(frames(src, c["start_sec"], c["end_sec"])),
                       a.headline or c["thumb_headline"], WORK / f"{vid}_thumb.jpg",
                       accent=a.accent if a.accent is not None else c.get("thumb_accent"),
                       teacher=c.get("teacher"), series=c.get("series"))
        with open(thumb, "rb") as f:
            ops("POST", f"/cuts/{a.thumb_only}/thumbnail", files={"file": ("thumb.jpg", f, "image/jpeg")},
                data={"thumb_headline": a.headline or c["thumb_headline"], "thumb_accent": a.accent or ""})
        return
    meta = vimeo("GET", f"/videos/{vid}?fields=name,description,duration,link")
    segs, src = transcript(vid)
    plan = choose(meta, segs, a.teacher)
    start, end = snap(segs, to_sec(plan["start"]), to_sec(plan["end"]))
    if a.start is not None and a.end is not None:
        start, end = a.start, a.end
    plan = fact_check(plan, segs, start, end, meta)
    teacher = a.teacher or plan.get("teacher")
    series = a.series or plan.get("series")

    src = src or download(best_source_link(vid), WORK / f"{vid}.mp4")
    out = cut(src, start, end, WORK / f"{vid}_yt.mp4")
    fr = frames(src, start, end)
    best = pick_frame(fr)
    thumb = render(best, a.headline or plan["thumb_headline"],
                   WORK / f"{vid}_thumb.jpg", accent=a.accent or plan.get("thumb_accent"),
                   teacher=teacher, series=series, bg_frame=fr[len(fr) // 2] if fr[len(fr) // 2] != best else fr[0])

    print(json.dumps({"window": f"{hms(start)}–{hms(end)}", **plan}, indent=1, ensure_ascii=False))
    cut_id = vimeo_upload(out, f"[YT] {plan['yt_title']}",
                          f"YouTube cut of {meta['link']} ({hms(start)}–{hms(end)})")
    excerpt = " ".join(t for s, _, t in segs if start <= s <= start + 45)
    if a.dry_run:
        vimeo_set_picture(cut_id, thumb)
        report = {"source": meta["link"], "window": f"{hms(start)}–{hms(end)}",
                  "cut": f"https://vimeo.com/{cut_id}", "opening_lines": excerpt, **plan}
        out = json.dumps(report, indent=1, ensure_ascii=False)
        print(out)
        import os
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
                f.write(f"## Test cut\n\n**Watch:** https://vimeo.com/{cut_id}\n\n```json\n{out}\n```\n")
        return
    record = ops("POST", "/cuts", json={
        "proposal_id": a.proposal_id, "source_vimeo_id": vid, "source_link": meta["link"],
        "cut_vimeo_id": cut_id, "start_sec": start, "end_sec": end, "duration_sec": end - start,
        "why": plan.get("why"), "opening_lines": excerpt, "teacher": teacher, "series": series,
        "yt_title": plan["yt_title"], "yt_description": plan["yt_description"],
        "yt_tags": plan.get("tags", []), "hashtags": plan.get("hashtags", []),
        "thumb_headline": a.headline or plan["thumb_headline"], "thumb_accent": a.accent or plan.get("thumb_accent")})
    with open(thumb, "rb") as f:
        ops("POST", f"/cuts/{record['cut_id']}/thumbnail", files={"file": ("thumb.jpg", f, "image/jpeg")})
    print(json.dumps({"cut_id": record["cut_id"], "window": f"{hms(start)}–{hms(end)}", **plan},
                     indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
