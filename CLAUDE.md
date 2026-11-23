# AI Clipper: how to work in this repo

The owner sends a stream link (Kick / Twitch, sometimes YouTube) and wants ready-to-post
**vertical 4K clips (Shorts / Reels / TikTok)** plus a title, description and hashtags for each,
delivered as **download pages** he can open on his iPad. This file is the full playbook. Follow it
without asking him to repeat anything.

## About the owner (important)
- Talk to him in **Hinglish: a natural mix of Hindi and English, written in Roman letters**
  (e.g. "Bhai, clip ready hai, download page pe daal diya"). **Not pure English, not pure Hindi / Devanagari.**
  He has had to repeat this many times; get it right from the first message.
- He is in **Canada**: give times in Toronto (ET) and, if useful, Vancouver (PT). Never UTC alone.
- He uses an **iPad only**, so no computer. He can't download files from chat cards; give him **download pages** (see below).
- He wants **4K quality, never downscaled**. He refused 1080p versions.
- **No music** in the clips: he adds music himself in the apps.
- He asks "how much time left?" often: answer with a short table and honest estimates. If an estimate slips, say so.
- Don't ask him for passwords. Don't offer to post to his social accounts (no tool for it).

## The pipeline (what worked)
1. **Setup** (first thing in a fresh session): `bash setup_linux.sh` → must print `READY`.
   It installs the skills to `~/.claude/skills/gta6-clipper` and builds everything. ~10-15 min.
   Python for the scripts: `~/.claude/skills/gta6-clipper/.venv/bin/python`. Call it `$PY` below.
2. **Get the stream**
   - **Kick** works. Kick VOD page URLs fail in yt-dlp, so use the direct `.m3u8`:
     `python3 tools/kick_vods.py <channel> [--gta]` → pick the stream (biggest / the one he named) → copy its `source` m3u8.
   - **Twitch** VOD links should work directly.
   - **YouTube is blocked** on cloud servers ("Sign in to confirm you're not a bot"). Tell him straight away;
     the only fix is a cookies.txt exported from a computer (throwaway Google account). Prefer finding the same stream on Kick/Twitch.
   - If the stream is not in English (e.g. Hindi), set `whisper_model` in `~/.claude/skills/gta6-clipper/config.json`
     to `models/ggml-small.bin` and change `-l en` in `transcribe()` in `gta6clip.py` to `-l auto`.
3. **Prep** (download audio + transcript), run in the background:
   `$PY ~/.claude/skills/gta6-clipper/scripts/gta6clip.py prep "<m3u8 or url>"`
   An 8 h stream ≈ 90 min on 4 CPUs. Then fix `stream.json` in the run folder: set `"streamer"` (e.g. "N3on") and `"title"`.
4. **Pick moments yourself**: read `references/picking.md`, then every `chunks/chunk_NN.md`, write `picks/chunk_NN.json`
   (`[]` if nothing). Per pick also write: `hook`, `hook_emoji`, `title`, `description` (ends with a question),
   `hashtags` (6-8, include #shorts #reels and the streamer tag), `emojis` (2-3 `[word, emoji]` pairs), `score`.
   - Be harsh: only 7+/10 gets rendered. Aim for every strong moment ("as many as you can").
   - **Skip sexual content** (strip club lap dances, nudity jokes): Shorts/Reels restrict it.
   - Ignore the LOUD markers' absolute values; they are often inflated. Read the words.
5. **Render** (approved style = `pro_render.py`), one background job, best clips first:
   `$PY ~/.claude/skills/gta6-clipper/scripts/pro_render.py <run> --top 40 --min-score 7.0 > ~/render.log 2>&1 &`
   Watch `~/render.log` with a Monitor (`grep "clip [0-9]*:|FAILED"`), ~5 min per clip.
   What the style does: 2160x3840, **Neon facecam top 30%**, then a dark caption band (subtitles live here, never on his face or the gameplay), then gameplay, green seams; white hook card only for the first 3.5 s,
   big word-by-word captions (yellow active word), a few emojis, punch-in zooms on loud peaks,
   **jump cuts that remove pauses** (he asked for this), progress bar, loudness -14 LUFS, **30-60 s** per clip.
   - If a clip fails with an `imgutils.c ... dst_linesize` assertion, it's a layout problem (dead facecam):
     the script retries as `"layout": "gameplay"` automatically; else set it in that pick and use `--only N`.
   - `pro_render_v4.py` = alternative "full-screen gameplay + small Neon box" style. He looked at it and decided
     to **keep the original style**, so use `pro_render.py` unless he asks for full-screen.
   - **QA every clip before delivering**: grab a frame (ffmpeg -ss 12) and look at it. The facecam must be the
     whole overlay box (not just the face), same size as the other clips, and sharp. `overlay_box.py` finds the box
     from its straight edges; he was upset when clips 11-37 shipped with a blurry over-zoomed face.
6. **Deliver**: download pages (claude.ai Artifacts), see the next section. After each clip: tell him in 2-3 lines
   (title, length, size, page link, what's rendering next).

## Download pages (how he gets the files on iPad)
Chat file cards have no download button on his iPad, and outside file hosts are blocked. What works:
- `web/download_page.html` is the page (Download 4K button + Copy title / description / hashtags).
  Copy it per page, replace `__TITLE__` (2-4 words, e.g. "Neon GTA 6 Clips 2"), `__HEADING__`, `__INTRO__`,
  and publish it with `capabilities: {"assets": {}, "downloads": true}` plus a `clips.json` file (start with `[]`).
- Per clip: `RUN=<run> OUT=<dir> web/prep.sh N` splits the 4K mp4 into 18 MB parts + thumb → upload them with
  the Artifact tool (`asset: true`, `file_paths`: thumb first, then parts in order) → `RUN=<run> PAGE_DIR=<page dir>
  python3 web/add.py N <thumb_id> <part ids...>` → republish the page with the updated `clips.json`.
  The page re-joins the parts in the browser into the exact original file and saves it.
- **Each page holds max 1 GB** (≈ 5-7 clips). Open the next page before an upload would pass ~950 MB.
- iPad steps to tell him: open in Safari → Download 4K → wait for "Saved." → Files app › Downloads →
  Share › Save Video (to Photos) or Move › Google Drive. Download one clip at a time.

## Music / posting advice he liked
- Music: search in-app trending sounds (check with a web search for the current month). Phonk for hype, synthwave
  for Miami/city, funny/cartoon for fails, suspense for twists. Volume 10-20 %.
- Posting from iPad: Buffer or Metricool (free) to post to Instagram, YouTube, TikTok, Facebook at once.
  2-3 clips a day, credit the streamer in the description.

## OpusClip (connected: YouTube AVYUKTX, Instagram avyuk_tx, Facebook page Avyuktx; NOT TikTok, he doesn't want TikTok)
- Our 4K clips can be uploaded (create_upload_link → resumable PUT → submit_project with skipCurate:true,
  enableCaption:false) and posted with create_post_task / schedule_publish (he approves each in the OpusClip app).
- **On the TRIAL plan OpusClip burns an "OpusClip" watermark into the video. He does NOT want any watermark.**
  Never post through OpusClip while the plan is TRIAL (check opusclip_whoami). Tell him this up front.
- Ask him which clip numbers to post; never pick or post on your own.
