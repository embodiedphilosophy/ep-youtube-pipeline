# EP YouTube Pipeline

Vimeo (Studio-Produced showcase) → 5 weekly proposals → approve in Ops → AI picks the best
continuous 15–20 min stretch → cut + EP-style thumbnail → review in Ops → **Push to YouTube**.

```
Mon 07:17 UTC  propose.yml   → 5 proposals land in Ops (YouTube → This week)
Approve        produce.yml   → transcript → Claude picks window + writes title/description/thumbnail text
                               → ffmpeg cut (fades, YouTube loudness) → thumbnail → cut parked on Vimeo (unlisted)
                               → Ops "Review queue"
Re-render      produce.yml (thumb) → new thumbnail from edited headline/accent
Push           publish.yml   → YouTube upload (private / scheduled) + thumbnail + playlist → link back in Ops
```

Why GitHub Actions and not Vercel: hour-long source files and ffmpeg encodes far exceed Vercel
function limits; Actions runners allow up to 6 hours and are free at this volume.

## One-time setup (about 30 minutes)

### 1. Create the repo
1. On github.com → **New repository** → owner *embodiedphilosophy*, name `ep-youtube-pipeline`, Private.
2. On the new repo page click **uploading an existing file**, drag in everything from this folder
   (including the hidden `.github` folder — on a Mac press ⌘⇧. in Finder to show it), **Commit**.

### 2. Vimeo token
developer.vimeo.com → **Create app** → *Generate an access token* → Authenticated (you) with scopes
**public, private, video_files, upload, edit, interact**. Copy the token.
In Vimeo, create a folder called **YouTube Queue**; open it and copy the number at the end of its URL.

### 3. YouTube access (OAuth refresh token)
1. console.cloud.google.com → new project "EP YouTube" → **APIs & Services → Library** → enable
   **YouTube Data API v3**.
2. **OAuth consent screen** → External → add yourself as a test user → then **Publish app**
   (otherwise the token expires after 7 days).
3. **Credentials → Create credentials → OAuth client ID** → *Web application* → authorised redirect
   URI `https://developers.google.com/oauthplayground`. Copy client ID + secret.
4. developers.google.com/oauthplayground → ⚙️ → *Use your own OAuth credentials* → paste them →
   in the scope box type `https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube`
   → **Authorize APIs** → sign in **as the Embodied Philosophy channel** → **Exchange authorization code**
   → copy the **Refresh token**.

### 4. Add secrets to the GitHub repo
Repo → **Settings → Secrets and variables → Actions**.
*Secrets*: `VIMEO_TOKEN`, `ANTHROPIC_API_KEY`, `OPS_PIPELINE_SECRET`, `YT_CLIENT_ID`,
`YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`.
*Variables*: `OPS_URL` = `https://ops.embodiedphilosophy.com`, `VIMEO_QUEUE_FOLDER_ID` = the folder number.

### 5. Build the Ops side
Give `OPS_HANDOFF.md` to a Claude session with the ep-ops repo.

### 6. Thumbnail assets (recommended)
- `assets/backgrounds/` — drop 20–40 JPG/PNG art/collage backgrounds from the EP Drive image
  archive (deity paintings, manuscripts, cosmic art). One is chosen at random per thumbnail.
- `assets/badges/` — transparent PNG logos named `chitheads.png`, `sādhana-school.png`,
  `wisdom-school.png`, `embodied-philosophy.png`. Without them a text badge is drawn.

## Test it
Repo → **Actions** → *Produce YouTube cut* → **Run workflow** → paste one Vimeo video ID.
