"""Shared clients: Vimeo, Claude (Anthropic), and the EP Ops dashboard API."""
import json
import os
import re
import time
from pathlib import Path

import requests

VIMEO_TOKEN = os.environ.get("VIMEO_TOKEN", "")
SHOWCASE_ID = os.environ.get("VIMEO_SHOWCASE_ID", "12473613")  # Professional Quality Videos (Studio-Produced)
QUEUE_FOLDER_ID = os.environ.get("VIMEO_QUEUE_FOLDER_ID", "")    # Vimeo folder for finished YouTube cuts
OPS_URL = os.environ.get("OPS_URL", "https://ops.embodiedphilosophy.com").rstrip("/")
OPS_SECRET = os.environ.get("OPS_PIPELINE_SECRET", "")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-5")

WORK = Path(os.environ.get("WORK_DIR", "work"))
WORK.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------- Vimeo
def vimeo(method, path, **kw):
    url = path if path.startswith("http") else f"https://api.vimeo.com{path}"
    headers = {"Authorization": f"bearer {VIMEO_TOKEN}",
               "Accept": "application/vnd.vimeo.*+json;version=3.4"}
    headers.update(kw.pop("headers", {}))
    for attempt in range(5):
        r = requests.request(method, url, headers=headers, timeout=120, **kw)
        if r.status_code == 429:
            time.sleep(int(r.headers.get("Retry-After", 30)))
            continue
        r.raise_for_status()
        return r.json() if r.content else {}
    r.raise_for_status()


def vimeo_id(uri):
    return uri.rstrip("/").split("/")[-1]


def showcase_videos():
    fields = "uri,name,description,duration,created_time,link,stats.plays,tags.name,pictures.base_link,metadata.connections.texttracks.total"
    page = f"/me/albums/{SHOWCASE_ID}/videos?per_page=100&fields={fields}"
    out = []
    while page:
        d = vimeo("GET", page)
        out += d.get("data", [])
        page = (d.get("paging") or {}).get("next")
    return out


def download(url, dest):
    with requests.get(url, stream=True, timeout=600) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(8 << 20):
                f.write(chunk)
    return dest


def best_source_link(vid, max_height=1080):
    """Highest-quality original/progressive MP4 at or below max_height."""
    d = vimeo("GET", f"/videos/{vid}?fields=download,files")
    files = [f for f in (d.get("download") or []) + (d.get("files") or [])
             if f.get("link") and (f.get("type") == "video/mp4" or str(f.get("quality")) in ("hd", "sd", "source"))]
    files = [f for f in files if (f.get("height") or 0) <= max_height] or files
    if not files:
        raise RuntimeError("No download link — the token needs the 'video_files' scope on the account that owns the video")
    return max(files, key=lambda f: (f.get("height") or 0, f.get("size") or 0))["link"]


def vimeo_upload(path, name, description="", private=True):
    """Upload via tus; returns new video id. Puts it in the queue folder if configured."""
    size = os.path.getsize(path)
    body = {"upload": {"approach": "tus", "size": str(size)}, "name": name, "description": description,
            "privacy": {"view": "unlisted" if private else "anybody", "embed": "public", "download": True}}
    d = vimeo("POST", "/me/videos", json=body)
    link, offset = d["upload"]["upload_link"], 0
    with open(path, "rb") as f:
        while offset < size:
            f.seek(offset)
            chunk = f.read(128 << 20)
            r = requests.patch(link, data=chunk, timeout=900, headers={
                "Tus-Resumable": "1.0.0", "Upload-Offset": str(offset),
                "Content-Type": "application/offset+octet-stream"})
            r.raise_for_status()
            offset = int(r.headers["Upload-Offset"])
    vid = vimeo_id(d["uri"])
    if QUEUE_FOLDER_ID:
        vimeo("PUT", f"/me/projects/{QUEUE_FOLDER_ID}/videos/{vid}")
    return vid


# ---------------------------------------------------------------- Claude
def claude_json(system, user, max_tokens=4000):
    r = requests.post("https://api.anthropic.com/v1/messages", timeout=600, headers={
        "x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": CLAUDE_MODEL, "max_tokens": max_tokens, "system": system,
              "messages": [{"role": "user", "content": user}]})
    r.raise_for_status()
    text = "".join(b.get("text", "") for b in r.json()["content"])
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0))


# ---------------------------------------------------------------- Ops dashboard
def ops(method, path, **kw):
    r = requests.request(method, f"{OPS_URL}/api/youtube{path}", timeout=120,
                         headers={"Authorization": f"Bearer {OPS_SECRET}"}, **kw)
    r.raise_for_status()
    return r.json() if r.content else {}


def hms(sec):
    sec = int(round(sec))
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}"
