# Ops dashboard: "YouTube Studio" section — build brief

Paste this whole file into a Claude session that has the **embodiedphilosophy/ep-ops** repo
(ops.embodiedphilosophy.com) and ask it to build it. The worker that does the heavy video work
lives in a separate repo, **embodiedphilosophy/ep-youtube-pipeline** (GitHub Actions). Ops only
stores records, shows them, and fires the worker.

## Who sees it
Jake and Rebecka (media/ads owners). Put it in the sidebar as **YouTube**. Restyle to match the
Course Library desk look (Pine sidebar, ivory hairline workspace, Terra accent, Cormorant headings,
Inter UI, mono numbers).

## Screens
1. **This week's proposals** — 5 cards (Vimeo thumbnail, title, duration, plays, teacher, the
   one-line "angle" and "reason"). Buttons: **Approve** / **Skip**. Approve lets staff confirm/edit
   the teacher name and series (CHITHEADS · Sādhana School · Wisdom School · Embodied Philosophy),
   then fires `produce`. Card status: Proposed → Producing… → Ready for review.
2. **Review queue** — each finished cut shows:
   - the cut embedded from Vimeo (`https://player.vimeo.com/video/{cut_vimeo_id}`), with in/out
     times and "why this stretch" + the opening lines;
   - the thumbnail, with editable **headline** and **accent** fields and a **Re-render thumbnail**
     button (fires `thumb`);
   - editable YouTube title, description, tags, hashtags, privacy (default *private*),
     optional schedule date/time, optional playlist;
   - **Adjust in/out** (start/end seconds) + **Re-cut** (fires `produce` with start/end);
   - **Push to YouTube** (fires `publish`). After publishing show the YouTube link.
3. **Published** — history list with YouTube links. Anything published or skipped must never be
   proposed again (feeds `used_vimeo_ids`).

Add a "YouTube" item to the director's task list when proposals arrive and when cuts are ready.

## API the worker calls (all under `/api/youtube`, auth `Authorization: Bearer $OPS_PIPELINE_SECRET`)
| Method & path | Body / returns |
|---|---|
| `GET /state` | returns `{used_vimeo_ids: string[], upcoming_programs: [{title, start, summary}]}` — upcoming programs from the master Programming calendar, next ~10 weeks |
| `POST /proposals` | `{week_of, proposals:[{vimeo_id,title,link,duration_sec,plays,picture,teacher,angle,reason}]}` → store, status "proposed" |
| `POST /cuts` | `{proposal_id, source_vimeo_id, source_link, cut_vimeo_id, start_sec, end_sec, duration_sec, why, opening_lines, teacher, series, yt_title, yt_description, yt_tags[], hashtags[], thumb_headline, thumb_accent}` → returns `{cut_id}` |
| `GET /cuts/{cut_id}` | returns the cut record plus `thumbnail_url`, `privacy`, `publish_at`, `playlist_id` (staff edits win) |
| `POST /cuts/{cut_id}/thumbnail` | multipart `file` (JPEG 1280×720), optional `thumb_headline`, `thumb_accent` → store in Vercel Blob, save public URL as `thumbnail_url` |
| `POST /cuts/{cut_id}/published` | `{youtube_id, youtube_url}` → mark published |

Store proposals and cuts in the existing ops database (or a dashboard-owned sheet tab if that is
what ops uses now). Keep raw records editable.

## How Ops fires the worker
Server-side only, using env `GITHUB_PIPELINE_TOKEN` (fine-grained token, repo
`ep-youtube-pipeline`, permission *Contents: read & write*):

```
POST https://api.github.com/repos/embodiedphilosophy/ep-youtube-pipeline/dispatches
Authorization: Bearer $GITHUB_PIPELINE_TOKEN
Accept: application/vnd.github+json
{"event_type": "produce", "client_payload": {"vimeo_id": "...", "proposal_id": "...", "teacher": "...", "series": "...", "start": null, "end": null}}
{"event_type": "thumb",   "client_payload": {"vimeo_id": "...", "cut_id": "...", "headline": "...", "accent": "..."}}
{"event_type": "publish", "client_payload": {"cut_id": "..."}}
```

Env vars to add on the ep-ops Vercel project: `OPS_PIPELINE_SECRET` (long random string, same value
as the GitHub secret), `GITHUB_PIPELINE_TOKEN`, and a Vercel Blob store for thumbnails.
