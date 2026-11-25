# Ai-clipper
AI-powered automatic video clipping system that converts livestreams into engaging short-form videos for YouTube Shorts, Instagram Reels, and TikTok, with AI-selected highlights, captions, subtitles, and 9:16 formatting.

## Usage

Needs Python 3.9+, `ffmpeg` and `yt-dlp` (`pip install -U yt-dlp`).

```bash
# Best moments of a long YouTube stream (uses "Most replayed" + loudness peaks)
python clipper.py youtube "https://www.youtube.com/live/qSyo5d-dVzA" --top 25

# If YouTube says "Sign in to confirm you're not a bot"
python clipper.py youtube "<url>" --top 25 --cookies-from-browser chrome

# Most-viewed GTA 6 clips from a Kick channel / the whole Kick GTA VI category
python clipper.py kick-channel n3on --game "Grand Theft Auto VI" --top 28
python clipper.py kick-category grand-theft-auto-vi --time week --top 30

# Most-viewed Twitch clips of a channel
python clipper.py twitch-channel kaicenat --range 7d --top 10
```

Clips land in `output/<name>/` as 1080x1920 MP4s plus a `clips.csv` with
the original link of every clip (credit the creator when you post).
Options: `--style crop` (fill the screen instead of blur background),
`--clip-len 35`, `--max-seconds 60`, `--list-only`.
