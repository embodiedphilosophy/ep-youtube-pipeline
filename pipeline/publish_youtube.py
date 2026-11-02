"""Push an approved cut from Ops to YouTube (video + thumbnail + optional playlist), then report back.

Usage: python publish_youtube.py --cut-id <ops cut id>
Ops record supplies: cut_vimeo_id, yt_title, yt_description, yt_tags, hashtags, thumbnail_url,
privacy ("private"|"unlisted"|"public"), publish_at (ISO time, optional → scheduled), playlist_id (optional)."""
import argparse
import os

import requests

from common import WORK, best_source_link, download, ops

YT_CLIENT_ID = os.environ["YT_CLIENT_ID"]
YT_CLIENT_SECRET = os.environ["YT_CLIENT_SECRET"]
YT_REFRESH_TOKEN = os.environ["YT_REFRESH_TOKEN"]


def access_token():
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": YT_CLIENT_ID, "client_secret": YT_CLIENT_SECRET,
        "refresh_token": YT_REFRESH_TOKEN, "grant_type": "refresh_token"}, timeout=60)
    r.raise_for_status()
    return r.json()["access_token"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cut-id", required=True)
    cut_id = ap.parse_args().cut_id

    c = ops("GET", f"/cuts/{cut_id}")
    tok = access_token()
    H = {"Authorization": f"Bearer {tok}"}

    video = download(best_source_link(c["cut_vimeo_id"]), WORK / f"{cut_id}.mp4")
    thumb = download(c["thumbnail_url"], WORK / f"{cut_id}.jpg")

    desc = c["yt_description"].rstrip()
    if c.get("hashtags"):
        desc += "\n\n" + " ".join(c["hashtags"])
    status = {"privacyStatus": c.get("privacy", "private"), "selfDeclaredMadeForKids": False}
    if c.get("publish_at"):  # scheduled release requires private + publishAt
        status.update(privacyStatus="private", publishAt=c["publish_at"])
    body = {"snippet": {"title": c["yt_title"][:100], "description": desc[:5000],
                        "tags": c.get("yt_tags", [])[:30], "categoryId": "27",  # Education
                        "defaultLanguage": "en", "defaultAudioLanguage": "en"},
            "status": status}

    size = os.path.getsize(video)
    r = requests.post("https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
                      headers={**H, "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)},
                      json=body, timeout=60)
    r.raise_for_status()
    loc = r.headers["Location"]
    with open(video, "rb") as f:
        r = requests.put(loc, data=f, headers={**H, "Content-Type": "video/mp4", "Content-Length": str(size)},
                         timeout=7200)
    r.raise_for_status()
    yt_id = r.json()["id"]

    with open(thumb, "rb") as f:
        requests.post(f"https://www.googleapis.com/upload/youtube/v3/thumbnails/set?videoId={yt_id}",
                      headers={**H, "Content-Type": "image/jpeg"}, data=f, timeout=120).raise_for_status()

    if c.get("playlist_id"):
        requests.post("https://www.googleapis.com/youtube/v3/playlistItems?part=snippet", headers=H, timeout=60,
                      json={"snippet": {"playlistId": c["playlist_id"],
                                        "resourceId": {"kind": "youtube#video", "videoId": yt_id}}}).raise_for_status()

    ops("POST", f"/cuts/{cut_id}/published", json={"youtube_id": yt_id,
                                                    "youtube_url": f"https://youtu.be/{yt_id}"})
    print("Published:", f"https://youtu.be/{yt_id}")


if __name__ == "__main__":
    main()
