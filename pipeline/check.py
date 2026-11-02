"""Read-only connection check: Vimeo showcase + downloads + captions, Claude, YouTube channel.
Uploads nothing, changes nothing."""
import os

import requests

from common import SHOWCASE_ID, claude_json, vimeo, vimeo_id

ok = True


def step(name, fn):
    global ok
    try:
        print(f"✅ {name}: {fn()}")
    except Exception as e:  # noqa: BLE001
        ok = False
        print(f"❌ {name}: {e}")


def vimeo_me():
    return vimeo("GET", "/me?fields=name,account")["name"]


def showcase():
    d = vimeo("GET", f"/me/albums/{SHOWCASE_ID}/videos?per_page=1&fields=uri,name,duration")
    v = d["data"][0]
    globals()["SAMPLE"] = vimeo_id(v["uri"])
    return f"{d['total']} videos; sample: {v['name']} ({v['duration'] // 60} min)"


def downloads():
    d = vimeo("GET", f"/videos/{SAMPLE}?fields=download")
    files = d.get("download") or []
    if not files:
        raise RuntimeError("no download links — regenerate the token with the 'video_files' scope")
    return ", ".join(sorted({str(f.get('rendition') or f.get('quality')) for f in files}))


def captions():
    t = vimeo("GET", f"/videos/{SAMPLE}/texttracks").get("data", [])
    return f"{len(t)} caption track(s)" + ("" if t else " — Whisper fallback will be used")


def claude():
    return claude_json("Reply with JSON only.", 'Return {"ok": true}')


def youtube():
    tok = requests.post("https://oauth2.googleapis.com/token", timeout=60, data={
        "client_id": os.environ["YT_CLIENT_ID"], "client_secret": os.environ["YT_CLIENT_SECRET"],
        "refresh_token": os.environ["YT_REFRESH_TOKEN"], "grant_type": "refresh_token"})
    tok.raise_for_status()
    r = requests.get("https://www.googleapis.com/youtube/v3/channels?part=snippet,statistics&mine=true",
                     headers={"Authorization": f"Bearer {tok.json()['access_token']}"}, timeout=60)
    r.raise_for_status()
    c = r.json()["items"][0]
    return f"{c['snippet']['title']} ({c['statistics'].get('subscriberCount')} subscribers)"


step("Vimeo account", vimeo_me)
step("Studio-Produced showcase", showcase)
step("Vimeo download access", downloads)
step("Vimeo captions on sample", captions)
step("Claude API", claude)
step("YouTube channel", youtube)
raise SystemExit(0 if ok else 1)
